"""Tests for the GUI (airnef/gui.py): argument building, config migration, i18n and a widget smoke test."""
import datetime
import gc
import json
import re
from pathlib import Path

import pytest

from airnef import i18n

ROOT = Path(__file__).resolve().parent.parent


pytest.importorskip('tkinter', reason='tkinter is not available in this Python build')
from airnef import gui


def settings(**overrides):
    base = {'output_dir': r'C:\My Pictures', 'skip_downloaded': True, 'if_exists': 'uniquename', 'ip_address': '192.168.1.1',
            'realtime_download': 'disabled', 'logging_level': 'normal', 'action': 'getfiles', 'file_exts': ['NEF', 'JPG'],
            'file_exts_more': '', 'download_date': 'all', 'custom_date_start': '', 'custom_date_end': '',
            'card_slot': 'firstfound', 'transfer_order': 'oldestfirst', 'additional_args': ''}
    base.update(overrides)
    return base


def test_select_in_camera_args_keep_paths_with_spaces_intact():
    args = gui.buildArgsSelectInCamera(settings(skip_downloaded=False))
    assert args[args.index('--outputdir') + 1] == r'C:\My Pictures'
    assert ['--downloadhistory', 'ignore'] == args[args.index('--downloadhistory'):args.index('--downloadhistory') + 2]
    assert args[:2] == ['--cameratransferlist', 'exitifnotavail']


def test_select_on_computer_args():
    args = gui.buildArgsSelectOnComputer(settings(file_exts_more='TIF RAF', download_date='week',
                                                  additional_args='--filenamespec "@cameramodel@ @filename@"'),
                                         today=datetime.date(2026, 10, 19))
    assert args[:2] == ['--action', 'getfiles']
    assert args[args.index('--extlist') + 1:args.index('--extlist') + 5] == ['NEF', 'JPG', 'TIF', 'RAF']
    assert args[args.index('--startdate') + 1] == '10/12/26'
    assert args[-2:] == ['--filenamespec', '@cameramodel@ @filename@']
    assert '--downloadhistory' not in args


def test_preview_and_custom_dates():
    args = gui.buildArgsSelectOnComputer(settings(download_date='custom', custom_date_start='01/02/24',
                                                  custom_date_end='01/03/24 10:00:00'), preview=True)
    assert args[:2] == ['--action', 'listfiles']
    assert args[args.index('--enddate') + 1] == '01/03/24 10:00:00'


def test_generated_args_are_accepted_by_airnefcmd(monkeypatch):
    from airnef import cmdline
    from airnef.appstate import g
    args = gui.buildArgsSelectOnComputer(settings(download_date='custom', custom_date_start='01/02/24'))
    monkeypatch.setattr(cmdline.sys, 'argv', ['airnefcmd.py'] + args)
    monkeypatch.setattr(g, 'appDir', str(ROOT / 'nonexistent'))
    monkeypatch.setattr(g, 'appDataDir', str(ROOT / 'nonexistent'))
    cmdline.processCmdLine()
    assert g.args['outputdir'] == r'C:\My Pictures'
    assert g.args['extlist'] == {'NEF', 'JPG'}


def test_v1_config_values_are_migrated():
    assert gui.choiceKeyFromConfig('normal download then realtime', gui.RealtimeTransferChoices) == 'afternormal'
    assert gui.choiceKeyFromConfig('afternormal', gui.RealtimeTransferChoices) == 'afternormal'
    assert gui.choiceKeyFromConfig(None, gui.IfExistsChoices) == 'uniquename'


def test_custom_date_validation():
    assert gui.isValidCustomDate('12/31/15')
    assert gui.isValidCustomDate('12/31/15 23:59:59')
    assert not gui.isValidCustomDate('2015-12-31')


def test_vietnamese_catalog_is_complete_and_keeps_placeholders():
    from tools import extract_messages
    catalog = i18n.parsePoFile(Path(i18n.LOCALE_DIR) / 'vi' / 'LC_MESSAGES' / 'airnef.po')
    for msgid, _ in extract_messages.extract():
        assert msgid in catalog, msgid
        assert re.findall(r'\{[^}]*\}', msgid) == re.findall(r'\{[^}]*\}', catalog[msgid]), msgid


def test_language_switch_and_fallback():
    assert i18n.setLanguage('vi') == 'vi'
    assert i18n._('Start Download') == 'Bắt đầu tải'
    assert i18n.setLanguage('xx') == 'en'
    assert i18n._('Start Download') == 'Start Download'


@pytest.fixture(autouse=True)
def collect_tk_garbage():
    """Finalise leftover Tk objects (variables, images) on the main thread, right after each test.

    If the garbage collector ran in another thread instead - for example a simulated camera's thread in a
    later test - each Variable/Image deallocation would wait about a second for the Tk main loop (Linux),
    stalling that thread long enough to make unrelated subprocess tests time out.
    """
    yield
    gc.collect()


@pytest.fixture(scope='module')
def tk_root():
    """One Tk interpreter for all GUI tests - Tk doesn't reliably support re-creating it in one process."""
    tkinter = pytest.importorskip('tkinter')
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip('no display available')
    root.withdraw()
    yield root
    gc.collect()
    root.destroy()


@pytest.mark.parametrize('language', ['en', 'vi'])
def test_gui_builds_every_page(tmp_path, language, monkeypatch, tk_root):
    root = tk_root
    try:
        (tmp_path / 'airnef-gui1-config').write_text(json.dumps({'language': language, 'realtime_download_choice': 'only realtime download'}), encoding='utf-8')
        monkeypatch.setattr(gui, 'root', root)
        gui.g.appDir = gui.paths.appDir()
        gui.g.appResourceDir = gui.paths.resourceDir()
        gui.g.appDataDir = str(tmp_path)
        gui.g.isWin32 = gui.platform.system() == 'Windows'
        gui.g.isOSX = False
        gui.g.app = None
        gui.configureStyles(root)
        gui.rebuildApplication()
        app = gui.g.app
        assert app.realtimeDownloadCombo.get_key() == 'only'   # v1 display text migrated
        app.setContent_Wizard_1_0()
        app.setContent_Wizard_2_0()
        app.dateCombo.set_key('custom')
        app.dateChoiceChanged(None)
        assert str(app.dateStartEntry['state']) == 'normal'
        expected = 'Bắt đầu tải' if language == 'vi' else 'Start Download'
        texts = [w.cget('text') for w in app.contentFrame.winfo_children()[-1].winfo_children() if 'text' in w.keys()]
        assert expected in texts
        app.setContent_Wizard_0()
    finally:
        i18n.setLanguage('en')
        if gui.g.app:
            gui.g.app.destroy()
            gui.g.app = None


#
# TransferWindow: runs the real airnefcmd against the simulated camera and drives it like a user
#
@pytest.fixture
def transfer_env(tmp_path, monkeypatch, tk_root):
    from types import SimpleNamespace
    monkeypatch.setenv('AIRNEF_APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setattr(gui, 'root', tk_root)
    gui.g.appDir = gui.paths.appDir()
    gui.g.appResourceDir = gui.paths.resourceDir()
    gui.g.appDataDir = str(tmp_path / 'appdata')
    gui.g.isWin32 = gui.platform.system() == 'Windows'
    gui.g.isOSX = gui.g.isFrozen = False
    gui.g.app = SimpleNamespace(showQuickTip=lambda *args: None)
    gui.configureStyles(tk_root)
    (tmp_path / 'appdata').mkdir()
    (tmp_path / 'out').mkdir()
    i18n.setLanguage('en')
    yield tmp_path
    i18n.setLanguage('en')


def run_window(tk_root, window, until, timeout=60):
    import time
    end = time.time() + timeout
    while time.time() < end and not until():
        tk_root.update()
        time.sleep(0.02)
    assert until(), 'timed out; log so far:\n' + '\n'.join(window.logLines[-15:])


def camera_args(cam, tmp_path, *extra):
    return ['--ipaddress', '127.0.0.1', '--port', str(cam.port), '--retrycount', '1', '--outputdir', str(tmp_path / 'out'), *extra]


def test_transfer_window_downloads_and_reports(transfer_env, tk_root):
    from test_integration import make_camera
    cam = make_camera()
    try:
        window = gui.TransferWindow(camera_args(cam, transfer_env))
        run_window(tk_root, window, lambda: window.finished)
        assert window.returncode == 0
        assert window.statusLabel['text'] == 'Transfer complete'
        assert window.filesDone == 3 and window.bytesDone == 300_000 + 2_500_000 + 1_000
        assert '3 file(s) downloaded' in window.summaryLabel['text']
        assert window.actionButton['text'] == 'Close'
        assert (transfer_env / 'out' / 'DSC_0002.NEF').read_bytes() == cam.objects[0x20000002].data
        assert '@@' not in window.logText.get('1.0', 'end')   # protocol lines are not shown as log text
        window.window.destroy()
    finally:
        cam.close()


def test_transfer_window_cancel(transfer_env, tk_root):
    from test_integration import make_camera
    cam = make_camera(bytes_per_sec=1_000_000)
    try:
        window = gui.TransferWindow(camera_args(cam, transfer_env, '--extlist', 'NEF', '--maxgetobjtransfersizekb', '256'))
        run_window(tk_root, window, lambda: str(window.progressBar['mode']) == 'determinate' and float(window.progressBar['value']) > 0)
        window.onActionButton()                 # the user presses Cancel
        assert window.statusLabel['text'] == 'Cancelling...'
        run_window(tk_root, window, lambda: window.finished, timeout=30)
        assert window.statusLabel['text'] == 'Transfer cancelled'
        assert not list((transfer_env / 'out').glob('*'))
        window.window.destroy()
    finally:
        cam.close()


def test_transfer_window_answers_file_exists_prompt(transfer_env, tk_root, monkeypatch):
    from test_integration import make_camera
    cam = make_camera()
    existing = transfer_env / 'out' / 'DSC_0001.JPG'
    existing.write_bytes(b'old')
    asked = []
    monkeypatch.setattr(gui.ChoiceDialog, 'show', lambda self: asked.append(self.window.title()) or 'S')
    try:
        window = gui.TransferWindow(camera_args(cam, transfer_env, '--extlist', 'JPG', '--ifexists', 'prompt'))
        run_window(tk_root, window, lambda: window.finished)
        assert window.returncode == 0 and asked == ['File exists']
        assert existing.read_bytes() == b'old'
        window.window.destroy()
    finally:
        cam.close()


def test_format_size():
    assert gui.formatSize(512) == '512 bytes'
    assert gui.formatSize(1536) == '1.5 KB'
    assert gui.formatSize(5 * 1048576) == '5.0 MB'
