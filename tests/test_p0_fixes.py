"""Regression tests for the transport and file-handling fixes (P0 / N3)."""
import socket
import struct

import pytest

import applog
import mtpwifi
import strutil
from mtpdef import MTP_OP_GetDeviceInfo, MTP_RESP_Ok


class ScriptedSocket:
    """Socket stand-in that returns pre-scripted chunks from recv() and records sendall()."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = b''

    def recv(self, maxBytes):
        if not self.chunks:
            return b''  # peer closed the connection
        chunk = self.chunks.pop(0)
        if len(chunk) > maxBytes:
            self.chunks.insert(0, chunk[maxBytes:])
            chunk = chunk[:maxBytes]
        return chunk

    def sendall(self, data):
        self.sent += data


def packet(payload):
    return struct.pack('<I', len(payload) + 4) + payload


def split_bytes(data):
    """Deliver a byte string one byte at a time, as an extreme case of TCP fragmentation."""
    return [data[i:i + 1] for i in range(len(data))]


def test_rxpayload_reassembles_fragmented_packet():
    payload = struct.pack('<I', 0x07) + b'abcdefgh'
    sock = ScriptedSocket(split_bytes(packet(payload)))
    assert mtpwifi.rxPayload(sock) == payload


def test_rxpayload_raises_when_peer_closes_instead_of_hanging():
    payload = struct.pack('<I', 0x0a) + b'x' * 100
    sock = ScriptedSocket([packet(payload)[:20]])  # connection drops mid-packet
    with pytest.raises(socket.error):
        mtpwifi.rxPayload(sock)


def test_rxpayload_raises_when_peer_closes_before_length():
    with pytest.raises(socket.error):
        mtpwifi.rxPayload(ScriptedSocket([b'\x10\x00']))


def test_txdata_uses_sendall():
    sock = ScriptedSocket([])
    mtpwifi.txdata(sock, b'\x01\x02')
    assert sock.sent == struct.pack('<I', 6) + b'\x01\x02'


def test_execmtpop_accepts_uint64_and_unknown_data_length():
    txid = 0x1234
    mtpwifi.generateTransactionId = iter([txid])
    data = b'0123456789'
    start = struct.pack('<IIQ', mtpwifi.MTP_TCPIP_PAYLOAD_ID_DataStart, txid, mtpwifi.MTP_TCPIP_DATA_LENGTH_UNKNOWN)
    end = struct.pack('<II', mtpwifi.MTP_TCPIP_PAYLOAD_ID_DataPayloadLast, txid) + data
    resp = struct.pack('<IHI', mtpwifi.MTP_TCPIP_PAYLOAD_ID_CmdResponse, MTP_RESP_Ok, txid)
    sock = ScriptedSocket([packet(start), packet(end), packet(resp)])
    result = mtpwifi.execMtpOp(sock, MTP_OP_GetDeviceInfo)
    assert result.dataReceived == data


def test_utf16_helpers_encode_non_ascii():
    assert strutil.stringToUtf16ByteArray('Tiến', True) == 'Tiến\x00'.encode('utf-16-le')
    counted = strutil.stringToCountedUtf16('Tiến', True)
    assert counted[0] == 5 and counted[1:] == 'Tiến\x00'.encode('utf-16-le')


def test_applog_shutdown_closes_both_logs(tmp_path):
    applog.applog_init(applog.APPLOGF_LEVEL_INFORMATIONAL, str(tmp_path / 'last.txt'), str(tmp_path / 'lifetime.txt'))
    applog.applog_shutdown()
    assert applog.gFileSessionLog.closed and applog.gFileLifetimeLog.closed


def test_extension_filter_is_case_insensitive():
    from objectcatalog import isMtpFilenameExtInList
    assert isMtpFilenameExtInList('dsc_0001.jpg', {'JPG'})
    assert not isMtpFilenameExtInList('dsc_0001.nef', {'JPG'})


def test_download_history_skips_truncated_line(tmp_path):
    import downloader
    from appstate import g
    root = tmp_path / 'cam'
    hist = tmp_path / 'cam-downloadhist'
    hist.write_text('DSC_1.NEF::20150101T000000::1,000::::01/01/15 00:00:00::/pics/DSC_1.NEF\n'
                    'DSC_2.NEF::2015010', encoding='utf-8')  # second line truncated, no newline
    g.cameraLocalMetadataPathAndRootName = str(root)
    g.downloadHistoryDict = None
    g.args = {'downloadhistory': 'skipfiles'}
    history, f = downloader.loadDownloadHistory()
    f.close()
    assert list(history) == ['DSC_1.NEF::20150101T000000::1,000']
    assert hist.exists()
