"""Tests for bulk object enumeration, >4GB handling and the capture-date list."""
import struct
from types import SimpleNamespace

import pytest

from airnef import downloader
from airnef import mtpwifi
from airnef.appstate import g
from airnef import mtpbulk
from airnef.dlinkedlist import LinkedList, LinkedListObj
from airnef.mtpdef import (MTP_OP_GetPartialObject, MTP_OP_GetPartialObject64, MTP_OP_Nikon_GetPartialObjectEx,
                    MTP_OBJPROP_ObjectFileName, MTP_OBJPROP_ObjectFormat)
from test_integration import make_camera, run_airnefcmd

BASE_OPS = (0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1006, 0x1007, 0x1008, 0x101B, 0x1015, 0x1016, 0x9408)
GET_OBJECT_INFO = 0x1008


def download_and_check(cam, tmp_path, *args):
    out = tmp_path / 'out'
    out.mkdir()
    result = run_airnefcmd(cam, tmp_path, '--outputdir', str(out), *args)
    assert result.returncode == 0, result.stdout + result.stderr
    for obj in cam.objects.values():
        if not obj.is_folder:
            assert (out / obj.filename).read_bytes() == obj.data
    return result


@pytest.mark.parametrize('extra_op, desc', [(0x9805, 'GetObjectPropList'), (0x1023, 'GetFilesystemManifest')])
def test_bulk_enumeration_replaces_per_object_requests(tmp_path, extra_op, desc):
    cam = make_camera(operations=BASE_OPS + (extra_op,))
    try:
        result = download_and_check(cam, tmp_path)
        assert desc in result.stdout
        assert not [op for op, _ in cam.ops_log if op == GET_OBJECT_INFO]
    finally:
        cam.close()


def test_perobject_method_can_be_forced(tmp_path):
    cam = make_camera(operations=BASE_OPS + (0x9805,))
    try:
        download_and_check(cam, tmp_path, '--objinfomethod', 'perobject')
        assert 0x9805 not in [op for op, _ in cam.ops_log]
    finally:
        cam.close()


def test_unknown_32bit_size_uses_objectsize_property(tmp_path):
    cam = make_camera(operations=BASE_OPS + (0x9803,), size_unknown=True)
    try:
        download_and_check(cam, tmp_path, '--mtpobjcache', 'disabled')
        assert 0x9803 in [op for op, _ in cam.ops_log]
    finally:
        cam.close()


def test_partial_object_request_switches_to_64bit_beyond_4gb(monkeypatch):
    def device(ops):
        monkeypatch.setattr(g, 'mtpDeviceInfo', SimpleNamespace(operationsSupportedSet=set(ops)))

    device([])
    assert downloader.genGetPartialObjectRequest(7, 100, 50) == (MTP_OP_GetPartialObject, struct.pack('<III', 7, 100, 50))
    offset = 0x1_0000_0010
    device([MTP_OP_GetPartialObject64])
    assert downloader.genGetPartialObjectRequest(7, offset, 50) == (MTP_OP_GetPartialObject64, struct.pack('<IIII', 7, 0x10, 1, 50))
    device([MTP_OP_Nikon_GetPartialObjectEx])
    assert downloader.genGetPartialObjectRequest(7, offset, 50)[0] == MTP_OP_Nikon_GetPartialObjectEx
    device([])
    with pytest.raises(mtpwifi.MtpProtocolException):
        downloader.genGetPartialObjectRequest(7, offset, 50)


def test_proplist_parser_skips_objects_without_name():
    data = (struct.pack('<I', 2)
            + struct.pack('<IHH', 1, MTP_OBJPROP_ObjectFormat, 0x0004) + struct.pack('<H', 0x3801)
            + struct.pack('<IHH', 1, MTP_OBJPROP_ObjectFileName, 0xFFFF) + b'\x02' + 'A\x00'.encode('utf-16-le'))
    infos = mtpbulk.objectInfosFromPropList(data, 0x00010001)
    assert infos[1].filename == 'A' and infos[1].storageId == 0x00010001
    with pytest.raises(mtpbulk.BulkDatasetError):
        mtpbulk.objectInfosFromPropList(data[:-3], 0)


def test_linked_list_keeps_sorted_stable_order():
    ll = LinkedList()
    objs = [LinkedListObj(k, ll) for k in [5, 1, 5, 3, 9, 0, 5]]
    keys, node = [], ll.head()
    while node:
        keys.append(node._key)
        node = node.llNext()
    assert keys == [0, 1, 3, 5, 5, 5, 9]
    fives = [o for o in objs if o._key == 5]
    assert fives[0].llNext() is fives[1] and fives[1].llNext() is fives[2]
    ll.remove(ll.tail())
    assert ll.tail()._key == 5 and ll.count() == 6
    ll.remove(ll.head())
    assert ll.head()._key == 1 and ll.head().llPrev() is None


def test_json_object_cache_is_reused_on_next_session(tmp_path):
    cam = make_camera()
    try:
        assert run_airnefcmd(cam, tmp_path, '--action', 'listfiles').returncode == 0
        cache_files = list((tmp_path / 'appdata').glob('*-objinfocache.json'))
        assert len(cache_files) == 1
        cam.ops_log.clear()
        result = run_airnefcmd(cam, tmp_path, '--action', 'listfiles')
        assert result.returncode == 0 and '5 from object cache' in result.stdout, result.stdout + result.stderr
        # only the two folders are re-read to validate the cache
        assert len([op for op, _ in cam.ops_log if op == GET_OBJECT_INFO]) == 2
    finally:
        cam.close()


def test_corrupt_json_cache_is_discarded(tmp_path):
    cam = make_camera()
    try:
        assert run_airnefcmd(cam, tmp_path, '--action', 'listfiles').returncode == 0
        cache_file = next((tmp_path / 'appdata').glob('*-objinfocache.json'))
        cache_file.write_text('{not json', encoding='utf-8')
        result = run_airnefcmd(cam, tmp_path, '--action', 'listfiles')
        assert result.returncode == 0 and '0 from object cache' in result.stdout, result.stdout + result.stderr
    finally:
        cam.close()
