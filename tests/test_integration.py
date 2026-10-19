"""End-to-end tests: run the real airnefcmd against the simulated PTP/IP camera."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ptpip_sim import FORMAT_NEF, SimCamera

ROOT = Path(__file__).resolve().parent.parent


def make_camera(**kwargs):
    cam = SimCamera(**kwargs)
    cam.add_folder(0x10000001, 'DCIM')
    cam.add_folder(0x10000002, '100NIKON', parent=0x10000001)
    cam.add_file(0x20000001, 'DSC_0001.JPG', 0x10000002, os.urandom(300_000), capture_date='20240102T030405')
    cam.add_file(0x20000002, 'DSC_0002.NEF', 0x10000002, os.urandom(2_500_000), FORMAT_NEF, '20240102T030410')
    cam.add_file(0x20000003, 'dsc_0003.jpg', 0x10000002, os.urandom(1_000), capture_date='20240102T030415')
    return cam


def run_airnefcmd(cam, tmp_path, *args, timeout=60):
    env = dict(os.environ, AIRNEF_APPDATA=str(tmp_path / 'appdata'), PYTHONIOENCODING='utf-8')
    cmd = [sys.executable, '-m', 'airnef.airnefcmd', '--ipaddress', '127.0.0.1', '--port', str(cam.port),
           '--retrycount', '1', '--connecttimeout', '5', '--logginglevel', 'debug', *args]
    return subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, encoding='utf-8', timeout=timeout)


@pytest.fixture
def camera():
    cam = make_camera()
    yield cam
    cam.close()


def test_download_all_files_matches_camera_bytes(camera, tmp_path):
    out = tmp_path / 'out'
    out.mkdir()
    result = run_airnefcmd(camera, tmp_path, '--outputdir', str(out), '--maxgetobjtransfersizekb', '256')
    assert result.returncode == 0, result.stdout + result.stderr
    for obj in camera.objects.values():
        if not obj.is_folder:
            assert (out / obj.filename).read_bytes() == obj.data
    assert not list(out.glob('*.part'))


def test_second_run_skips_files_in_download_history(camera, tmp_path):
    out = tmp_path / 'out'
    out.mkdir()
    assert run_airnefcmd(camera, tmp_path, '--outputdir', str(out)).returncode == 0
    second = run_airnefcmd(camera, tmp_path, '--outputdir', str(out))
    assert second.returncode == 0
    assert '3 previously-downloaded files skipped' in second.stdout
    assert not list(out.glob('*-new-*'))


def test_extlist_filter_is_case_insensitive(camera, tmp_path):
    out = tmp_path / 'out'
    out.mkdir()
    result = run_airnefcmd(camera, tmp_path, '--outputdir', str(out), '--extlist', 'jpg')
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(p.name for p in out.iterdir()) == ['DSC_0001.JPG', 'dsc_0003.jpg']


def test_listfiles(camera, tmp_path):
    result = run_airnefcmd(camera, tmp_path, '--action', 'listfiles')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DCIM\\100NIKON\\DSC_0002.NEF' in result.stdout
    assert '3 File(s)' in result.stdout


def test_multi_packet_data_phase(tmp_path):
    """Canon-style responders split the data phase into several Data packets."""
    cam = make_camera(manufacturer='Canon Inc.', model='Canon EOS 6D', data_packet_size=16_384,
                      operations=(0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1007, 0x1008, 0x1009, 0x101B, 0x9110))
    try:
        out = tmp_path / 'out'
        out.mkdir()
        result = run_airnefcmd(cam, tmp_path, '--outputdir', str(out))
        assert result.returncode == 0, result.stdout + result.stderr
        assert (out / 'DSC_0002.NEF').read_bytes() == cam.objects[0x20000002].data
    finally:
        cam.close()


def test_thumbnails(camera, tmp_path):
    out = tmp_path / 'out'
    out.mkdir()
    result = run_airnefcmd(camera, tmp_path, '--outputdir', str(out), '--action', 'getsmallthumbs')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out / 'DSC_0001.JPG.sthumb.jpg').read_bytes() == b'THUMB:DSC_0001.JPG'
