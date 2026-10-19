"""
Simulated PTP/IP camera (responder) for testing airnef without hardware.

Implements the PTP-IP transport from CIPA DC-005-2005 (two TCP connections,
Init Command/Event handshake, Operation Request/Response, Start/Data/End Data,
Event, Probe and Cancel packets) plus the subset of PTP/MTP operations that
airnef uses. Behaviour that differs between vendors (multi-packet data phases,
Nikon event polling, transfer lists) is configurable per instance.
"""
import socket
import struct
import threading
import time
from dataclasses import dataclass, field

# PTP-IP packet types (CIPA DC-005 2.3)
INIT_COMMAND_REQUEST = 0x01
INIT_COMMAND_ACK = 0x02
INIT_EVENT_REQUEST = 0x03
INIT_EVENT_ACK = 0x04
INIT_FAIL = 0x05
OPERATION_REQUEST = 0x06
OPERATION_RESPONSE = 0x07
EVENT = 0x08
START_DATA = 0x09
DATA = 0x0A
CANCEL = 0x0B
END_DATA = 0x0C
PROBE_REQUEST = 0x0D
PROBE_RESPONSE = 0x0E

DATA_PHASE_OUT = 2

# PTP response codes
RC_OK = 0x2001
RC_GENERAL_ERROR = 0x2002
RC_OPERATION_NOT_SUPPORTED = 0x2005
RC_INVALID_OBJECT_HANDLE = 0x2009
RC_DEVICE_PROP_NOT_SUPPORTED = 0x200A
RC_TRANSACTION_CANCELLED = 0x201F
RC_NIKON_NO_TRANSFER_LIST = 0xA205

FORMAT_ASSOCIATION = 0x3001
FORMAT_JPEG = 0x3801
FORMAT_NEF = 0x3000
ASSOC_GENERIC_FOLDER = 0x0001
PROP_DATETIME = 0x5011
EVENT_OBJECT_ADDED = 0x4002

STORAGE_SLOT1 = 0x00010001


def ptp_string(text):
    if not text:
        return b'\x00'
    encoded = (text + '\x00').encode('utf-16-le')
    return struct.pack('<B', len(encoded) // 2) + encoded


def ptp_array16(values):
    return struct.pack('<I', len(values)) + b''.join(struct.pack('<H', v) for v in values)


def ptp_array32(values):
    return struct.pack('<I', len(values)) + b''.join(struct.pack('<I', v) for v in values)


def packet(packet_type, payload=b''):
    return struct.pack('<II', len(payload) + 8, packet_type) + payload


@dataclass
class SimObject:
    handle: int
    filename: str
    parent: int = 0
    data: bytes = b''
    object_format: int = FORMAT_JPEG
    capture_date: str = '20240102T030405'
    storage_id: int = STORAGE_SLOT1

    @property
    def is_folder(self):
        return self.object_format == FORMAT_ASSOCIATION

    def object_info(self):
        assoc = ASSOC_GENERIC_FOLDER if self.is_folder else 0
        return (struct.pack('<IHHIHI', self.storage_id, self.object_format, 0, len(self.data), 0, 0)
                + struct.pack('<IIIIIIHII', 0, 0, 0, 0, 0, self.parent, assoc, 0, 0)
                + ptp_string(self.filename) + ptp_string(self.capture_date)
                + ptp_string(self.capture_date) + ptp_string(''))


@dataclass
class SimCamera:
    manufacturer: str = 'Nikon Corporation'
    model: str = 'D7200'
    serial: str = '0001234'
    objects: dict = field(default_factory=dict)
    data_packet_size: int = 0            # >0: split data phases into Data packets of this size (Canon style)
    operations: tuple = (0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1006, 0x1007, 0x1008,
                         0x1009, 0x100A, 0x1015, 0x1016, 0x101B, 0x90C7, 0x9408)
    camera_datetime: str = '20240102T030405'
    reject_initiator: bool = False       # answer Init Command Request with Init Fail
    probe_initiator_on_open: bool = False  # send a Probe Request on the event channel when the session opens

    def __post_init__(self):
        self.ops_log = []                # (opcode, params) of every operation received
        self.nikon_events = []           # queued (code, param) for Nikon GetEvent (0x90C7)
        self.probe_responses = 0         # Probe Responses received from the initiator
        self.cancels = []                # transaction IDs from Cancel packets
        self._lock = threading.Lock()
        self._event_conn = None
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(('127.0.0.1', 0))
        self._server.listen(4)
        self.port = self._server.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    # ---- object helpers -------------------------------------------------
    def add_folder(self, handle, name, parent=0):
        self.objects[handle] = SimObject(handle, name, parent, object_format=FORMAT_ASSOCIATION)
        return self.objects[handle]

    def add_file(self, handle, name, parent, data, object_format=FORMAT_JPEG, capture_date='20240102T030405'):
        self.objects[handle] = SimObject(handle, name, parent, data, object_format, capture_date)
        return self.objects[handle]

    def push_event(self, code, param1=0xFFFFFFFF):
        """Send a PTP-IP Event packet on the event channel (CIPA DC-005 2.3.8)."""
        payload = struct.pack('<HIIII', code, 0xFFFFFFFF, param1, 0, 0)
        with self._lock:
            if self._event_conn:
                self._event_conn.sendall(packet(EVENT, payload))

    def close(self):
        self._stop = True
        try:
            self._server.close()
        except OSError:
            pass

    # ---- transport ------------------------------------------------------
    @staticmethod
    def _recv_exact(conn, n):
        buf = b''
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('initiator closed connection')
            buf += chunk
        return buf

    def _recv_packet(self, conn):
        (length,) = struct.unpack('<I', self._recv_exact(conn, 4))
        body = self._recv_exact(conn, length - 4)
        (ptype,) = struct.unpack('<I', body[:4])
        return ptype, body[4:]

    def _accept_loop(self):
        while not self._stop:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            ptype, payload = self._recv_packet(conn)
            if ptype == INIT_COMMAND_REQUEST:
                if self.reject_initiator:
                    conn.sendall(packet(INIT_FAIL, struct.pack('<I', 1)))  # FAIL_REJECTED_INITIATOR
                    return
                ack = (struct.pack('<I', 0x00000001) + bytes(range(16)) + ptp_string(self.model)[1:]
                       + struct.pack('<I', 0x00010000))
                conn.sendall(packet(INIT_COMMAND_ACK, ack))
                self._command_loop(conn)
            elif ptype == INIT_EVENT_REQUEST:
                conn.sendall(packet(INIT_EVENT_ACK))
                with self._lock:
                    self._event_conn = conn
                self._event_loop(conn)
        except (ConnectionError, OSError):
            pass
        finally:
            conn.close()

    def _event_loop(self, conn):
        while True:
            ptype, payload = self._recv_packet(conn)
            if ptype == PROBE_REQUEST:
                with self._lock:
                    conn.sendall(packet(PROBE_RESPONSE))
            elif ptype == PROBE_RESPONSE:
                self.probe_responses += 1
            elif ptype == CANCEL:
                self.cancels.append(struct.unpack('<I', payload[:4])[0])

    def _command_loop(self, conn):
        while True:
            ptype, payload = self._recv_packet(conn)
            if ptype == CANCEL:
                self.cancels.append(struct.unpack('<I', payload[:4])[0])
                continue
            if ptype != OPERATION_REQUEST:
                raise ConnectionError('unexpected packet type 0x%x' % ptype)
            data_phase, opcode, txid = struct.unpack('<IHI', payload[:10])
            params = list(struct.unpack('<%dI' % ((len(payload) - 10) // 4), payload[10:]))
            data_out = b''
            if data_phase == DATA_PHASE_OUT:
                ptype, start = self._recv_packet(conn)
                assert ptype == START_DATA
                while True:
                    ptype, body = self._recv_packet(conn)
                    data_out += body[4:]
                    if ptype == END_DATA:
                        break
            self.ops_log.append((opcode, params))
            code, data_in, resp_params = self._dispatch(opcode, params, data_out)
            if data_in is not None:
                self._send_data(conn, txid, data_in)
            resp = struct.pack('<HI', code, txid) + b''.join(struct.pack('<I', p) for p in resp_params)
            conn.sendall(packet(OPERATION_RESPONSE, resp))
            if opcode == 0x1003:
                return

    def _send_data(self, conn, txid, data):
        conn.sendall(packet(START_DATA, struct.pack('<IQ', txid, len(data))))
        size = self.data_packet_size
        if size and len(data) > size:
            for offset in range(0, len(data) - size, size):
                conn.sendall(packet(DATA, struct.pack('<I', txid) + data[offset:offset + size]))
            last = data[(len(data) - 1) // size * size:]
        else:
            last = data
        conn.sendall(packet(END_DATA, struct.pack('<I', txid) + last))

    # ---- operations -----------------------------------------------------
    def _handles(self, storage_id, parent=0):
        return [h for h, o in sorted(self.objects.items())
                if storage_id in (0xFFFFFFFF, o.storage_id) and (not parent or o.parent == parent)]

    def _device_info(self):
        return (struct.pack('<HIH', 100, 0x0000000A, 100) + ptp_string('') + struct.pack('<H', 0)
                + ptp_array16(list(self.operations)) + ptp_array16([0x4002])
                + ptp_array16([PROP_DATETIME]) + ptp_array16([]) + ptp_array16([FORMAT_JPEG])
                + ptp_string(self.manufacturer) + ptp_string(self.model) + ptp_string('1.00')
                + ptp_string(self.serial))

    def _dispatch(self, opcode, params, data_out):
        p = params + [0] * 5
        if opcode not in self.operations and opcode not in (0x1001, 0x1002, 0x1003):
            return RC_OPERATION_NOT_SUPPORTED, None, []
        if opcode == 0x1001:
            return RC_OK, self._device_info(), []
        if opcode == 0x1002 and self.probe_initiator_on_open:
            with self._lock:
                if self._event_conn:
                    self._event_conn.sendall(packet(PROBE_REQUEST))
        if opcode in (0x1002, 0x1003):
            return RC_OK, None, []
        if opcode == 0x1004:
            return RC_OK, ptp_array32([STORAGE_SLOT1, 0x00020000]), []
        if opcode == 0x1005:
            info = struct.pack('<HHHQQI', 4, 3, 0, 32 << 30, 16 << 30, 0xFFFFFFFF) + ptp_string('') + ptp_string('NIKON')
            return RC_OK, info, []
        if opcode == 0x1006:
            return RC_OK, None, [len(self._handles(p[0], p[2]))]
        if opcode == 0x1007:
            return RC_OK, ptp_array32(self._handles(p[0], p[2])), []
        obj = self.objects.get(p[0])
        if opcode in (0x1008, 0x1009, 0x100A, 0x101B) and obj is None:
            return RC_INVALID_OBJECT_HANDLE, None, []
        if opcode == 0x1008:
            return RC_OK, obj.object_info(), []
        if opcode == 0x1009:
            return RC_OK, obj.data, []
        if opcode == 0x100A:
            return RC_OK, b'THUMB:' + obj.filename.encode(), []
        if opcode == 0x101B:
            count = len(obj.data) - p[1] if p[2] == 0xFFFFFFFF else p[2]
            chunk = obj.data[p[1]:p[1] + count]
            return RC_OK, chunk, [len(chunk)]
        if opcode == 0x1015:
            if p[0] != PROP_DATETIME:
                return RC_DEVICE_PROP_NOT_SUPPORTED, None, []
            return RC_OK, ptp_string(self.camera_datetime), []
        if opcode == 0x1016:
            return RC_OK, None, []
        if opcode == 0x9408:
            return RC_NIKON_NO_TRANSFER_LIST, None, []
        if opcode == 0x90C7:
            events, self.nikon_events = self.nikon_events, []
            return RC_OK, struct.pack('<H', len(events)) + b''.join(struct.pack('<HI', c, v) for c, v in events), []
        return RC_OPERATION_NOT_SUPPORTED, None, []


def wait_for(predicate, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False
