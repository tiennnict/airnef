"""Tests for the GUI (airnef.pyw): argument building, config migration, i18n and a widget smoke test."""
import datetime
import importlib.util
import json
import re
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

import i18n

ROOT = Path(__file__).resolve().parent.parent


def load_gui():
    loader = SourceFileLoader('airnef_gui', str(ROOT / 'airnef.pyw'))
    spec = importlib.util.spec_from_loader('airnef_gui', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


pytest.importorskip('tkinter', reason='tkinter is not available in this Python build')
gui = load_gui()


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
    import cmdline
    from appstate import g
    args = gui.buildArgsSelectOnComputer(settings(download_date='custom', custom_date_start='01/02/24'))
    monkeypatch.setattr(cmdline.sys, 'argv', ['airnefcmd.py'] + args)
    monkeypatch.setattr(g, 'appDir', str(ROOT / 'nonexistent'))
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
    root.destroy()


@pytest.mark.parametrize('language', ['en', 'vi'])
def test_gui_builds_every_page(tmp_path, language, monkeypatch, tk_root):
    root = tk_root
    try:
        (tmp_path / 'airnef-gui1-config').write_text(json.dumps({'language': language, 'realtime_download_choice': 'only realtime download'}), encoding='utf-8')
        monkeypatch.setattr(gui, 'root', root)
        gui.g.appDir = str(ROOT)
        gui.g.appResourceDir = str(ROOT / 'appresource')
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
