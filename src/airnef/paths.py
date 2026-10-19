#!/usr/bin/env python

#
#############################################################################
#
# paths.py - Where airnef finds its files and keeps its data
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Shared by the GUI and airnefcmd, which must agree on these locations: airnefcmd writes
# the log the GUI shows, and both use the same settings directory.
#
#############################################################################
#

import os
import platform
import sys

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def isFrozen():
	return bool(getattr(sys, 'frozen', False))


#
# directory of the application: where the executable lives when frozen, else the installed package
#
def appDir():
	if isFrozen():
		return os.path.dirname(os.path.realpath(sys.argv[0]))
	return PACKAGE_DIR


#
# directory with the read-only resources (icons, button images)
#
def resourceDir():
	return os.path.join(appDir(), 'appresource')


#
# directory for the files airnef creates: logs, download history, object cache, GUI settings.
#
#   AIRNEF_APPDATA environment variable   explicit override (used by the test suite)
#   <source checkout>/appdata             if it already exists, so data from earlier runs of a
#                                         checkout isn't orphaned
#   Windows                               %LOCALAPPDATA%\airnef\appdata
#   macOS                                 ~/Library/Application Support/airnef/appdata
#   elsewhere                             $XDG_DATA_HOME/airnef/appdata (default ~/.local/share/airnef/appdata)
#
def appDataDir():
	override = os.getenv('AIRNEF_APPDATA')
	if override:
		return override
	checkoutRoot = os.path.dirname(os.path.dirname(PACKAGE_DIR))	# <root>/src/airnef -> <root>
	legacyDir = os.path.join(checkoutRoot, 'appdata')
	if os.path.isfile(os.path.join(checkoutRoot, 'pyproject.toml')) and os.path.isdir(legacyDir):
		return legacyDir
	system = platform.system()
	home = os.path.expanduser('~')
	if system == 'Windows':
		base = os.getenv('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')
		return os.path.join(base, 'airnef', 'appdata')
	if system == 'Darwin':
		return os.path.join(home, 'Library', 'Application Support', 'airnef', 'appdata')
	return os.path.join(os.getenv('XDG_DATA_HOME') or os.path.join(home, '.local', 'share'), 'airnef', 'appdata')


#
# creates the app data directory if necessary and returns its path
#
def ensureAppDataDir():
	path = appDataDir()
	os.makedirs(path, exist_ok=True)
	return path
