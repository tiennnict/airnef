"""Tests for the PTP/IP transport behaviour defined by CIPA DC-005."""
import os
import struct
import subprocess
import sys
import time

import pytest

import mtpwifi
from mtpdef import MTP_OP_GetDeviceInfo, MTP_OP_GetObject, MTP_RESP_Ok, MTP_RESP_TransactionCancelled
from ptpip_sim import EVENT_OBJECT_ADDED, wait_for
from test_integration import ROOT, make_camera, run_airnefcmd
from test_p0_fixes import ScriptedSocket, packet


def test_parse_init_command_ack():
    ack = (struct.pack('<II', mtpwifi.MTP_TCPIP_INIT_CMD_ACK, 0x55) + bytes(range(16))
           + 'D7200\x00'.encode('utf-16-le') + struct.pack('<I', 0x00010000))
    parsed = mtpwifi.parseInitCommandAck(ack)
    assert parsed.connectionNumber == 0x55
    assert parsed.responderGuid == bytes(range(16))
    assert parsed.responderName == 'D7200'
    assert parsed.protocolVersion == 0x00010000


def test_parse_init_command_ack_without_optional_fields():
    parsed = mtpwifi.parseInitCommandAck(struct.pack('<II', mtpwifi.MTP_TCPIP_INIT_CMD_ACK, 1))
    assert parsed.connectionNumber == 1 and parsed.protocolVersion is None


def test_init_fail_busy_is_a_retryable_connection_failure():
    fail = struct.pack('<II', mtpwifi.MTP_TCPIP_INIT_FAIL, mtpwifi.MTP_TCPIP_INIT_FAIL_BUSY)
    sock = ScriptedSocket([packet(fail)])
    with pytest.raises(mtpwifi.MtpConnectionFailureException, match='busy'):
        mtpwifi.sendInitCmdReq(sock, (0, 0), 'airnef', 0x00010000)


def test_init_fail_rejected_initiator_explains_guid():
    fail = struct.pack('<II', mtpwifi.MTP_TCPIP_INIT_FAIL, mtpwifi.MTP_TCPIP_INIT_FAIL_REJECTED_INITIATOR)
    with pytest.raises(mtpwifi.MtpProtocolException, match='GUID'):
        mtpwifi.sendInitCmdReq(ScriptedSocket([packet(fail)]), (0, 0), 'airnef', 0x00010000)


def test_transaction_ids_restart_each_session():
    mtpwifi.resetTransactionIds()
    assert next(mtpwifi.generateTransactionId) == 1
    mtpwifi.resetTransactionIds()
    assert next(mtpwifi.generateTransactionId) == 1


def test_ctrl_c_cancels_transaction_and_keeps_session_usable():
    """<ctrl-c> mid data phase: Cancel is sent, the rest of the packet is skipped, the session survives."""
    mtpwifi.resetTransactionIds()
    txid = 1
    start = struct.pack('<IIQ', mtpwifi.MTP_TCPIP_PAYLOAD_ID_DataStart, txid, 200_000)
    data = struct.pack('<II', mtpwifi.MTP_TCPIP_PAYLOAD_ID_DataPayload, txid) + b'x' * 100_000
    cancelled = struct.pack('<IHI', mtpwifi.MTP_TCPIP_PAYLOAD_ID_CmdResponse, MTP_RESP_TransactionCancelled, txid)
    ok = struct.pack('<IHI', mtpwifi.MTP_TCPIP_PAYLOAD_ID_CmdResponse, MTP_RESP_Ok, 2)
    stream = packet(start) + packet(data) + packet(cancelled) + packet(ok)
    sock = ScriptedSocket([stream[i:i + 4096] for i in range(0, len(stream), 4096)])

    def interrupt(received, expected):
        if received > 10_000:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        mtpwifi.execMtpOp(sock, MTP_OP_GetObject, struct.pack('<I', 5), rxTxProgressFunc=interrupt)
    assert struct.pack('<III', 12, mtpwifi.MTP_TCPIP_CANCEL, txid) in sock.sent
    assert mtpwifi.gTransferInterruptedBySIGINT is False
    assert mtpwifi.execMtpOp(sock, MTP_OP_GetDeviceInfo).mtpRespCode == MTP_RESP_Ok


def test_camera_probe_is_answered(tmp_path):
    cam = make_camera(probe_initiator_on_open=True)
    try:
        result = run_airnefcmd(cam, tmp_path, '--action', 'listfiles')
        assert result.returncode == 0, result.stdout + result.stderr
        assert cam.probe_responses == 1
    finally:
        cam.close()


def test_realtime_download_reacts_to_object_added_event(tmp_path):
    """With a 60s polling interval, only the ObjectAdded event can trigger a quick download."""
    cam = make_camera(manufacturer='Canon Inc.', model='Canon EOS 6D',
                      operations=(0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1007, 0x1008, 0x101B, 0x9110))
    out = tmp_path / 'out'
    out.mkdir()
    env = dict(os.environ, AIRNEF_APPDATA=str(tmp_path / 'appdata'))
    cmd = [sys.executable, str(ROOT / 'airnefcmd.py'), '--ipaddress', '127.0.0.1', '--port', str(cam.port),
           '--retrycount', '1', '--outputdir', str(out), '--realtimedownload', 'only', '--realtimepollsecs', '60']
    proc = subprocess.Popen(cmd, cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # wait until airnef is in its realtime loop (it has fetched the initial handle list)
        assert wait_for(lambda: sum(1 for op, _ in cam.ops_log if op == 0x1007) >= 1, 20)
        time.sleep(1.0)
        new = cam.add_file(0x20000010, 'IMG_0100.JPG', 0x10000002, os.urandom(50_000), capture_date='20990101T000000')
        cam.push_event(EVENT_OBJECT_ADDED, new.handle)
        assert wait_for(lambda: (out / 'IMG_0100.JPG').exists(), 15)
        assert wait_for(lambda: (out / 'IMG_0100.JPG').read_bytes() == new.data, 5)
        assert not (out / 'DSC_0001.JPG').exists()  # realtime-only: existing images are not downloaded
    finally:
        proc.kill()
        proc.wait()
        cam.close()
