"""Tests for SSDP discovery: packet filtering, LOCATION parsing and hostname fallback."""
import socket
import time

import pytest

import ssdp

SONY_SVC = "urn:microsoft-com:service:MtpNullService:1"
CANON_SVC = "urn:schemas-canon-com:service:ICPO-SmartPhoneEOSSystemService:1"

SONY_NOTIFY = (
    "NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nCACHE-CONTROL: max-age=1800\r\n"
    "LOCATION: http://192.168.1.209:1900/DeviceDescription.xml\r\n"
    "NT: " + SONY_SVC + "\r\nNTS: ssdp:alive\r\nSERVER: FedoraCore/2 UPnP/1.0 MINT-X/1.8.1\r\n"
    "USN: uuid:00000000-0001-0010-8000-98f17039c6fc::" + SONY_SVC + "\r\n\r\n")
CANON_RESPONSE = (
    "HTTP/1.1 200 OK\r\nCache-Control: max-age=1800\r\nEXT:\r\n"
    "Location: http://192.168.1.10:49152/upnp/CameraDevDesc.xml\r\n"
    "ST: " + CANON_SVC + "\r\nUSN: uuid:1::" + CANON_SVC + "\r\n\r\n")
CANON_BYEBYE = (
    "NOTIFY * HTTP/1.1\r\nHost: 239.255.255.250:1900\r\nNT: " + CANON_SVC + "\r\n"
    "NTS: ssdp:byebye\r\nUSN: uuid:1::" + CANON_SVC + "\r\n\r\n")
OTHER_DEVICE = (
    "NOTIFY * HTTP/1.1\r\nLOCATION: http://192.168.1.5:80/x.xml\r\n"
    "NT: upnp:rootdevice\r\nNTS: ssdp:alive\r\n\r\n")
JUNK = b"NOTIFY * HTTP/1.1\r\nSERVER: caf\xe9 \xff\xfe\x80 UPnP\r\nNT: junk\r\n\r\n"


class FakeSocket:
    """Stands in for a UDP socket: records sends and replays queued packets."""
    def __init__(self):
        self.packets = []
        self.sent = []
        self.closed = False

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        return len(data)

    def recv(self, n):
        return self.packets.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def fake(monkeypatch):
    sock = FakeSocket()
    monkeypatch.setattr(ssdp, 'createUdpSocket', lambda flags: sock)

    def fake_select(rlist, wlist, xlist, timeout):
        if sock.packets:
            return ([sock], [], [])
        time.sleep(min(timeout, 0.01))
        return ([], [], [])
    monkeypatch.setattr(ssdp.select, 'select', fake_select)
    return sock


def run_discover(sock, packets, services=(SONY_SVC, CANON_SVC), callback=None):
    sock.packets = [p if isinstance(p, bytes) else p.encode() for p in packets]
    return ssdp.discover(list(services), callback, numAttempts=1, timeoutSecsPerAttempt=0.2, flags=0)


def test_non_utf8_junk_is_ignored(fake):
    result = run_discover(fake, [JUNK, b'\xff\xfe\xfd', SONY_NOTIFY])
    assert result == SONY_NOTIFY
    assert fake.closed


def test_only_junk_returns_none(fake):
    assert run_discover(fake, [JUNK, b'\x80\x81']) is None


def test_sony_notify_matched(fake):
    result = run_discover(fake, [OTHER_DEVICE, SONY_NOTIFY], services=[SONY_SVC])
    assert ssdp.extractIpAddressFromSSDPMessage(result) == '192.168.1.209'


def test_canon_http_response_matched(fake):
    result = run_discover(fake, [CANON_RESPONSE], services=[CANON_SVC])
    assert ssdp.extractIpAddressFromSSDPMessage(result) == '192.168.1.10'


def test_byebye_ignored(fake):
    assert run_discover(fake, [CANON_BYEBYE], services=[CANON_SVC]) is None
    assert not ssdp.isMessageForService(CANON_BYEBYE, CANON_SVC)


def test_msearch_ignored(fake):
    msearch = "M-SEARCH * HTTP/1.1\r\nST: " + SONY_SVC + "\r\n\r\n"
    assert run_discover(fake, [msearch]) is None


def test_verify_callback_can_reject(fake):
    assert run_discover(fake, [SONY_NOTIFY], callback=lambda m: False) is None


def test_message_type_and_service_matching():
    assert ssdp.ssdpTypeFromMessage(SONY_NOTIFY) == ssdp.SSDP_TYPE_NOTIFY
    assert ssdp.ssdpTypeFromMessage(CANON_RESPONSE) == ssdp.SSDP_TYPE_RESPONSE
    assert ssdp.isMessageForService(SONY_NOTIFY, SONY_SVC)
    assert not ssdp.isMessageForService(SONY_NOTIFY, CANON_SVC)
    assert not ssdp.isMessageForService(OTHER_DEVICE, SONY_SVC)


@pytest.mark.parametrize('location,expected', [
    ('http://192.168.1.209:1900/DeviceDescription.xml', '192.168.1.209'),
    ('http://192.168.1.10/desc.xml', '192.168.1.10'),
    ('  HTTP://10.0.0.7:8080/a?b=c  ', '10.0.0.7'),
    ('http://camera.local:80/x.xml', None),
    ('http://[fe80::1]:80/x.xml', None),
    ('http://999.1.1.1/x.xml', None),
    ('http://1.2.3/x.xml', None),
    ('not a url', None),
    ('http://', None),
    ('', None),
])
def test_location_parsing(location, expected):
    msg = "NOTIFY * HTTP/1.1\r\nLOCATION: {}\r\nNTS: ssdp:alive\r\n\r\n".format(location)
    assert ssdp.extractIpAddressFromSSDPMessage(msg) == expected


def test_location_missing_or_none():
    assert ssdp.extractIpAddressFromSSDPMessage("NOTIFY * HTTP/1.1\r\n\r\n") is None
    assert ssdp.extractIpAddressFromSSDPMessage(None) is None


def test_hostname_lookup_failure_falls_back(monkeypatch):
    def boom(name):
        raise socket.gaierror(11001, 'getaddrinfo failed')
    monkeypatch.setattr(ssdp.socket, 'gethostbyname', boom)
    assert ssdp.getHostnameIpAddrStr() == '0.0.0.0'


def test_hostname_lookup_success(monkeypatch):
    monkeypatch.setattr(ssdp.socket, 'gethostbyname', lambda name: '192.168.1.2')
    assert ssdp.getHostnameIpAddrStr() == '192.168.1.2'
