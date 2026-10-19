import re
from pathlib import Path

from airnef import appstate
from airnef.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "%s"$' % re.escape(__version__), text, re.M)


def test_airnefcmd_uses_version_module():
    assert appstate.AIRNEFCMD_APP_VERSION == __version__


def test_gui_uses_version_module():
    source = (ROOT / "src" / "airnef" / "gui.py").read_text(encoding="utf-8")
    assert "from .version import __version__ as AIRNEF_APP_VERSION" in source
