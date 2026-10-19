#!/usr/bin/env python

#
#############################################################################
#
# airnef.py - Wireless file transfer for PTP/MTP-equipped cameras (GUI app)
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Camera bitmap courtesy of rg1024 at https://openclipart.org/detail/20364/cartoon-camera
# Computer bitmap courtesy of lnasto at https://openclipart.org/detail/171010/computer-client
# Icon courtesy of Paomedia at https://www.iconfinder.com/icons/285680/camera_icon,
#     licensed under Creative Commons (Attribution 3.0 Unported)
#
# The GUI collects the download criteria and launches airnefcmd (the command-line
# app) to do the actual transfer, then shows airnefcmd's report. It is built with
# themed ttk widgets so it follows the native look of each OS, and every user-visible
# string goes through i18n._() so the interface can be translated (see i18n.py).
#
#############################################################################
#

from tkinter import *
from tkinter.font import Font, nametofont
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk
from tkinter import filedialog as tkFileDialog
from tkinter import messagebox as tkMessageBox
import time
import subprocess
import os
import re
import errno
import platform
import json
import datetime
import sys
import i18n
from i18n import _, N_

#
# constants
#
AIRNEF_APP_VERSION	= "1.1"
APP_CONFIG_VERSION	= 2		# v2 stores option keys instead of (English) display text
OUTPUTDIR_HISTORY_MAX = 32	# number of most-recently-used output directories remembered
PAD = 8						# standard spacing between widgets, in pixels

#
# choices offered in the combo boxes, as (key, display text) pairs. the key is what is stored
# in the app config and mapped to the airnefcmd option, so the stored settings don't depend on
# the interface language. display text is translated when shown
#
LoggingLevelChoices = [ ('normal', N_('normal')), ('verbose', N_('verbose')), ('debug', N_('debug')) ]
RealtimeTransferChoices = [
	('disabled', N_('none - exit after normal download')),
	('afternormal', N_('normal download then realtime')),
	('only', N_('only realtime download')) ]
IfExistsChoices = [
	('uniquename', N_('generate unique filename')),
	('overwrite', N_('overwrite file')),
	('skip', N_('skip file')),
	('prompt', N_('prompt for each file')),
	('exit', N_('exit')) ]
ActionChoices = [
	('getfiles', N_('full-sized images/movies')),
	('getsmallthumbs', N_('small thumbnails')),
	('getlargethumbs', N_('large thumbnails')) ]
CardSlotChoices = [
	('firstfound', N_('first card found')),
	('first', N_('card in slot #1')),
	('second', N_('card in slot #2')),
	('both', N_('both cards (not recommended)')) ]
TransferOrderChoices = [
	('oldestfirst', N_('oldest images/movies first')),
	('newestfirst', N_('newest images/movies first')) ]
DownloadDateChoices = [
	('all', N_('All Dates')),
	('today', N_('today')),
	('yesterday', N_('yesterday')),
	('week', N_('past week')),
	('month', N_('past month')),
	('year', N_('past year')),
	('custom', N_('custom date range')) ]
FileTypeChoices = [ 'NEF', 'JPG', 'MOV', 'CR2', 'ARW' ]

#
# structures
#
class GlobalVarsStruct:
	def __init__(self):
		self.isWin32 = None			# True if we're running on a Windows platform
		self.isOSX = None			# True if we're runnong on an OSX platform
		self.isFrozen = None		# True if we're running in a pyintaller frozen environment (ie, built as an executable)
		self.appDir = None			# directory where script is located. this path is used to store all metadata files, in case script is run in different working directory
		self.appDataDir = None		# directory where we keep app metadata
		self.appResourceDir = None	# directory where we keep app resources (read-only files needed by app, self.appDir + "resouce")
		self.app = None				# reference to main Application class
		self.headerFont = None		# font of the page titles, created by configureStyles()

#
# global variables
#
root = None		# Tk root
g = GlobalVarsStruct()


#
#############################################################################
#
# OSX workarounds for running in "frozen" app
#
# We use py2app to generate the OSX executable bundle. Unfortunately there are some limitations
# and odd behavior when running under this environment:
#
# * py2app only supports one python-generated executable per application gundle
# * py2app only supports GUI apps, and the environment created doesn't natively support launching airnefcmd
# * Our GUI app always launches as minimized. Every workaround to fix this causes even worse side-effects,
# such modal windows no longer functioning correctly. Update: Finally resolved this - it's something
# with py2app's argv_emulation logic. I disabled it since we don't use it and it resolved the issue.
#
# The workaround for not being able to encode airnefcmd as a native OSX app nor the ability
# to launch it in a terminal window is pretty bad. I use the OSX "open" command to launch
# our python airnefcmd script - unfortunately Terminal doesn't propagate the --args to the python
# app, so to work around that I have to write the arguments to a file. The second gotcha is that
# open's -W wait parameter doesn't work when executed through the Terminal app, which breaks the logic
# of this module waiting for airnefcmd.py to complete before presenting the output log to the user. The
# work-around for this ugly - I use the creation of files as a signaling mechanism between this module
# and airnefcmd - to keep this ugliness out of airnefcmd itself I created a new wrapper module named
# airnefcmd_OSX_Frozen_Wrapper.py - that module handles reading the cmd-line args we encode in a file
# and also the lame file-communication mechanism. To detect the termination of the wrapper/airnefcmd
# outside of the normal completion/ctrl-c the wrapper writes its process ID to the notify-start file
# and we monitor that ID to detect if the process is killed - this is necessary because the process
# created by Popen on open(Terminal) completes immediately, so we can't wait on that process ID.
#
def osxFrozenWorkaround_deleteWrapperCommunicationFile(filename):
	# deletes a file we're using to communicate with airnefcmd_OSX_Frozen_Wrapper.py
	if os.path.exists(filename):
		os.remove(filename)

def osxFrozenWorkaround_waitWrapperCommunicationFileExist(filename, maxWaitTimeSecs=sys.maxsize, processIdCheckTermination=None):
	# waits for airnefcmd_OSX_Frozen_Wrapper.py to create a file to signal the start or completion of airnefcmd.py
	timeStart = time.time()
	while not os.path.exists(filename):
		if time.time() - timeStart >= maxWaitTimeSecs:
			return True
		if processIdCheckTermination:
			try:
				groupId = os.getpgid(processIdCheckTermination)
			except OSError as e:
				if e.errno == errno.ESRCH:
					if not os.path.exists(filename): # exclude race condition between us checking file vs process ID (only for print purposes - doesn't really matter otherwise)
						print("airnefcmd wrapper termination detected")
					return False
		time.sleep(0.5)
	return False

def osxFrozenWorkaround_readWrapperCommunicationFile(filename):
	with open(filename, "r") as fo:
		return fo.read()

#
# launches airnefcmd via airnefcmd_OSX_Frozen_Wrapper and waits for the completion
#
def osxFrozenWorkaround_LaunchAirnefcmdWrapper(argList):

	FILENAME_CMD_OPTS		= os.path.join(g.appDataDir, "airnefcmd-osxfrozen-cmdopts")		# file we encode options for the wrapper to read
	FILENAME_NOTIFY_START	= os.path.join(g.appDataDir, "airnefcmd-osxfrozen-notifystart") # file created by wrapper to signal it's started running
	FILENAME_NOTIFY_DONE	= os.path.join(g.appDataDir, "airnefcmd-osxfrozen-notifydone")	# file created by wrapper to signal when airnefcmd is done

	# write options to temporary file
	with open(FILENAME_CMD_OPTS, 'w') as fo:
		for arg in argList:
			fo.write(arg + "\n")

	#
	# launch the OSX frozen wrapper for a airnefcmd.py. delete
	# any leftover notify-start/notify-done files, which shouldn't exist
	# but just in case the wrapper didn't execute properly last time
	#
	osxFrozenWorkaround_deleteWrapperCommunicationFile(FILENAME_NOTIFY_START)
	osxFrozenWorkaround_deleteWrapperCommunicationFile(FILENAME_NOTIFY_DONE)
	subprocess.Popen(['open', '-a', 'Terminal.app', os.path.join(g.appDir, 'airnefcmd_OSX_Frozen_Wrapper.py')])

	#
	# make sure the wraper launched by checking the notify-start file was created by the wrapper.
	# this is to make sure we don't sit forever on systems where for some reasons the workaround
	# via the wrapper is not functioning properly
	#
	if osxFrozenWorkaround_waitWrapperCommunicationFileExist(FILENAME_NOTIFY_START, 5):
		tkMessageBox.showwarning(_("airnefcmd launch error"), _("Launch of airnefcmd was unsuccessful"))
		return 1
	processIdWrapper = int(osxFrozenWorkaround_readWrapperCommunicationFile(FILENAME_NOTIFY_START))

	#
	# wait for completion of airnefcd, which is signified by the wrapper creating the notify-done file.
	# the file created by the wrapper actually contains the exit code from airnefcmd but since we're
	# not presently using that code I don't bother to read and return it
	#
	osxFrozenWorkaround_waitWrapperCommunicationFileExist(FILENAME_NOTIFY_DONE, processIdCheckTermination=processIdWrapper)
	return 0


#
# creates a list of arguments from an argument string, honoring quoted args as a single argument.
# used for the free-form 'Additional arguments' field. (shlex isn't used because its POSIX
# rules would eat the backslashes in Windows paths)
#
def createArgListFromArgStr(argStr):
	return [x.strip('"') for x in re.split('( |".*?")', argStr) if x.strip()]


#
# spawns airnefcmd with the specified argument list. returns the errno that airnefcmd exited with
#
def launchAirnefcmd(argList):

	print("Launching airnefcmd with args: ", argList)
	_errno = 0
	process = None
	try:

		root.withdraw() # make our main GUI window invisible while running airnefcmd

		if g.isFrozen:
			if g.isOSX:
				_errno = osxFrozenWorkaround_LaunchAirnefcmdWrapper(argList)
			elif g.isWin32:
				process = subprocess.Popen([os.path.join(g.appDir, 'airnefcmd.exe')] + argList)
			else: # linux
				process = subprocess.Popen(['xterm', '+hold', '-e', os.path.join(g.appDir, 'airnefcmd')] + argList)
		else:
			# same interpreter/venv as the GUI, but the console variant so airnefcmd gets a terminal window
			pythonExe = sys.executable
			if os.path.basename(pythonExe).lower() == 'pythonw.exe':
				pythonExe = os.path.join(os.path.dirname(pythonExe), 'python.exe')
			creationFlags = subprocess.CREATE_NEW_CONSOLE if g.isWin32 else 0
			process = subprocess.Popen([pythonExe, os.path.join(g.appDir, 'airnefcmd.py')] + argList, creationflags=creationFlags)

		if process:
			_errno = process.wait()

	except KeyboardInterrupt as e:
		print("SIGINT received while waiting for airnefcmd to complete")
		if process:
			#
			# both airnef and airnefcmd rceive the SIGINT. make sure airnefcmd
			# has completed processing its SIGTERM by waiting for it to exit
			#
			if process.poll() == None:
				print("waiting for airnefcmd to finish handling its SIGINT")
				process.wait()
		_errno = errno.EINTR
	finally:
		root.deiconify() # bring our main GUI window back

	displayAirnefcmdOutput()
	return _errno


#
# displays a top-level window with the last output from airnefcmd
#
def displayAirnefcmdOutput():

	#
	# load report
	#
	mostRecentAirnefReportFilename = os.path.join(g.appDataDir, "airnefcmd-log-last.txt")
	if not os.path.exists(mostRecentAirnefReportFilename):
		tkMessageBox.showinfo(_("Transfer Report"), _("No airnefcmd operations have been performed yet."))
		return
	try:
		with open(mostRecentAirnefReportFilename, "r", encoding="utf-8", errors="replace") as fileReport:
			reportContents = fileReport.read()
	except IOError as e:
		tkMessageBox.showerror(_("Transfer Report"), _("Error reading airnefcmd report file \"{:s}\". {:s}").format(mostRecentAirnefReportFilename, str(e)))
		return

	#
	# detect an unclean shutdown of airnefcmd by checking if the logfile is either
	# empty (no data flushed before termation) or is missing the final "session over"
	# message (last set of message(s) not flushed).
	#
	posSessionOverMessage = reportContents.find(">>>> airnefcmd session over") if reportContents else -1
	if posSessionOverMessage == -1:
		g.app.showQuickTip('airnefcmd_unclean_shutdown', 1,
			_("It appears airnefcmd was uncleanly terminated. In the future please press <ctrl-c> if "
			"you'd like to terminate airnefcmd instead of closing its terminal window. This will "
			"allow airnefcmd to perform any necessary cleanup prior to exiting."))
		if not reportContents:
			# log file is empty so no point in presenting window with contents
			return
	else:
		reportContents = reportContents[:posSessionOverMessage] # trim off ">>>> airnefcmd session over ...." message

	if g.isOSX and g.isFrozen:
		g.app.showQuickTip('osx_terminal_auto_close', 4,
			_("airnef performs its job by launching airnefcmd in a terminal window. By default OSX "
			"keeps that terminal window open even after airnefcmd has completed, requiring you to "
			"close it manually. You can configure OSX to close the terminal window automatically. "
			"Go to the Terminal application and select 'Preferences' in the Terminal menu. "
			"Click 'Profiles' at the top and then the \"Shell\" tab in the upper part of the window. "
			"Set \"When the shell exits\" option to 'Close if the shell exited cleanly' or 'Close "
			"the window'"))

	#
	# create top-level window: read-only monospaced report with Copy / Close buttons
	#
	window = Toplevel(root)
	window.title(_("Transfer Report"))
	window.geometry('960x480')
	window.minsize(480, 240)
	setFrameIcon(window)

	frame = ttk.Frame(window, padding=PAD)
	frame.pack(fill=BOTH, expand=1)
	textWidget = ScrolledText(frame, wrap=NONE, font=nametofont('TkFixedFont'), relief=FLAT, borderwidth=1, padx=PAD, pady=PAD)
	textWidget.insert(END, reportContents)
	textWidget.configure(state=DISABLED)	# read-only; text can still be selected and copied
	textWidget.see(END)
	textWidget.pack(side=TOP, fill=BOTH, expand=1)

	buttonFrame = ttk.Frame(frame)
	buttonFrame.pack(side=BOTTOM, fill=X, pady=(PAD, 0))
	closeButton = ttk.Button(buttonFrame, text=_("Close"), command=window.destroy, default=ACTIVE)
	closeButton.pack(side=RIGHT)
	ttk.Button(buttonFrame, text=_("Copy to Clipboard"),
		command=lambda : [root.clipboard_clear(), root.clipboard_append(reportContents)]).pack(side=RIGHT, padx=PAD)
	closeButton.focus_set()
	window.bind('<Escape>', lambda e : window.destroy())
	window.bind('<Return>', lambda e : window.destroy())

	#
	# present top-level window as modal and wait for it to be dismissed
	#
	window.transient(root)
	window.grab_set()
	bringAppToFront()
	root.wait_window(window)


#
# brings our app window(s) to the front of the OS's window z-order
#
def bringAppToFront():
	# fix for bringing our app to front on OS X
	root.lift()
	root.call('wm', 'attributes', '.', '-topmost', True)
	root.after_idle(root.call, 'wm', 'attributes', '.', '-topmost', False)

#
# sets the icon for the given window/frame
#
def setFrameIcon(frame):
	try:
		if g.isWin32:
			frame.wm_iconbitmap(bitmap = os.path.join(g.appResourceDir, 'airnef.ico'))
		else:
			frame.wm_iconbitmap(bitmap = '@' + os.path.join(g.appResourceDir, 'airnef.xbm'))
	except TclError:
		pass	# a missing/unsupported icon is cosmetic only


#
# selects the native-looking ttk theme for the platform and defines the styles used by the app
#
def configureStyles(master):
	style = ttk.Style(master)
	available = style.theme_names()
	for theme in (('vista', 'winnative') if g.isWin32 else ('aqua',) if g.isOSX else ('clam',)):
		if theme in available:
			style.theme_use(theme)
			break
	baseFont = nametofont('TkDefaultFont')
	baseSize = abs(int(baseFont.actual('size'))) or 9	# Tk reports pixel sizes as negative numbers
	headerFont = Font(master, family=baseFont.actual('family'), size=baseSize + 5, weight='bold')
	subtleColor = 'gray35'
	style.configure('Header.TLabel', font=headerFont)
	g.headerFont = headerFont	# also set directly on the label: some themes (vista) ignore fonts set via styles
	style.configure('Subtle.TLabel', foreground=subtleColor)
	style.configure('Hint.TLabel', foreground=subtleColor)
	style.configure('Card.TButton', padding=(24, 16))
	style.configure('Primary.TButton', padding=(24, 16))
	return style


#
# read-only combo box over a list of (key, display text) choices. the displayed text is
# translated; get_key()/set_key() work with the language-independent keys
#
class ChoiceCombobox(ttk.Combobox):

	def __init__(self, master, choices, initialKey=None, **kwargs):
		self.choices = choices
		ttk.Combobox.__init__(self, master, values=[_(text) for (key, text) in choices], state='readonly', **kwargs)
		self.set_key(initialKey)

	def set_key(self, key):
		keys = [k for (k, text) in self.choices]
		self.current(keys.index(key) if key in keys else 0)

	def get_key(self):
		index = self.current()
		return self.choices[index if index >= 0 else 0][0]


#
# maps a stored config value to a choice key. v1 configs stored the English display
# text, which is still accepted so existing users keep their settings
#
def choiceKeyFromConfig(value, choices):
	for (key, text) in choices:
		if value == key or value == text:
			return key
	return choices[0][0]


#
# builds the airnefcmd arguments for the "select in camera" page
#
def buildArgsSelectInCamera(settings):
	args = ['--cameratransferlist', 'exitifnotavail']
	args += buildCommonArgs(settings)
	return args


#
# builds the airnefcmd arguments for the "select on computer" page. 'preview' lists the files
# matching the criteria instead of downloading them. 'today' is the date relative date ranges
# are computed from (a parameter so the logic can be tested)
#
def buildArgsSelectOnComputer(settings, preview=False, today=None):
	args = ['--action', 'listfiles' if preview else settings['action']]
	args += buildCommonArgs(settings)
	extList = list(settings['file_exts']) + createArgListFromArgStr(settings['file_exts_more'])
	if extList:
		args += ['--extlist'] + extList
	args += ['--slot', settings['card_slot'], '--transferorder', settings['transfer_order']]

	dateChoice = settings['download_date']
	if dateChoice == 'custom':
		if settings['custom_date_start']:
			args += ['--startdate', settings['custom_date_start']]
		if settings['custom_date_end']:
			args += ['--enddate', settings['custom_date_end']]
	elif dateChoice != 'all':
		todayMidnight = datetime.datetime.combine(today or datetime.date.today(), datetime.time.min)
		daysBack = { 'today' : 0, 'yesterday' : 1, 'week' : 7, 'month' : 31, 'year' : 365 }[dateChoice]
		startDate = todayMidnight - datetime.timedelta(days=daysBack)
		args += ['--startdate', startDate.strftime('%m/%d/%y')]

	args += ['--cameratransferlist', 'ignore']
	args += createArgListFromArgStr(settings['additional_args'])
	return args


def buildCommonArgs(settings):
	args = ['--outputdir', settings['output_dir']]
	if not settings['skip_downloaded']:
		args += ['--downloadhistory', 'ignore']
	args += ['--ifexists', settings['if_exists']]
	if settings['ip_address']:
		args += ['--ipaddress', settings['ip_address']]
	args += ['--realtimedownload', settings['realtime_download'], '--logginglevel', settings['logging_level']]
	return args


#
# validates a mm/dd/yy or mm/dd/yy hh:mm:ss date entered by the user
#
def isValidCustomDate(userDateTimeStr):
	formatStr = "%m/%d/%y %H:%M:%S" if ":" in userDateTimeStr else "%m/%d/%y"
	try:
		time.strptime(userDateTimeStr, formatStr)
		return True
	except ValueError:
		return False


#
# returns the default download directory (the user's Pictures folder if it exists)
#
def defaultOutputDir():
	homeDir = os.path.expanduser('~')
	picturesDir = os.path.join(homeDir, 'Pictures')
	if os.path.isdir(picturesDir):
		return picturesDir
	if os.path.isdir(homeDir):
		return homeDir
	return os.getcwd()


#
# main application Tkinter class
#
# root -> Application(Frame) -> toolbar (camera connection options, report button)
#                            -> header (page title / subtitle)
#                            -> content (one of the three wizard pages)
#
class Application(ttk.Frame):

	def __init__(self, master):

		ttk.Frame.__init__(self, master)

		root.title(_("airnef - Wireless download of images and movies from your camera"))
		setFrameIcon(root)

		self.resource_PhotoDict = {}
		self.loadAppConfig()
		self.createTopLevelMenu()
		self.createToolbar()

		# page title area between the toolbar and the page content
		headerFrame = ttk.Frame(self, padding=(2*PAD, 2*PAD, 2*PAD, PAD))
		self.headerLabel = ttk.Label(headerFrame, style='Header.TLabel', font=g.headerFont)
		self.headerLabel.pack(anchor=W)
		self.subHeaderLabel = ttk.Label(headerFrame, style='Subtle.TLabel')
		self.subHeaderLabel.pack(anchor=W)
		headerFrame.pack(side=TOP, fill=X)
		ttk.Separator(self).pack(side=TOP, fill=X)

		self.contentFrame = ttk.Frame(self, padding=2*PAD)
		self.contentFrame.pack(side=TOP, fill=BOTH, expand=1)

		self.pack(fill=BOTH, expand=1)
		self.setContent_Wizard_0()
		bringAppToFront()

	#########################################################################
	# app config

	def loadAppConfig(self):
		appConfigFilename = os.path.join(g.appDataDir, "airnef-gui1-config")
		self.appConfigDict = {}
		try:
			if os.path.exists(appConfigFilename):
				with open(appConfigFilename, "r", encoding="utf-8") as f:
					self.appConfigDict = json.loads(f.read())
		except IOError as e:
			tkMessageBox.showwarning(_("Loading App Config"), _("Could not read app config data. {:s}. Defaults will be used.").format(str(e)))
		except ValueError as e:
			tkMessageBox.showwarning(_("Loading App Config"), _("Could not decode app config data. {:s}. Defaults will be used.").format(str(e)))
		if not isinstance(self.appConfigDict, dict):
			self.appConfigDict = {}

	def saveAppConfig(self):
		appConfigFilename = os.path.join(g.appDataDir, "airnef-gui1-config")
		self.appConfigDict['app_version'] = AIRNEF_APP_VERSION
		self.appConfigDict['config_version'] = APP_CONFIG_VERSION
		try:
			with open(appConfigFilename, "w", encoding="utf-8") as f:
				f.write(json.dumps(self.appConfigDict, indent=1))
		except (IOError, ValueError) as e:
			tkMessageBox.showwarning(_("Saving App Config"), _("Could not write app config data. {:s}.").format(str(e)))

	def configChoice(self, configKey, choices):
		return choiceKeyFromConfig(self.appConfigDict.get(configKey), choices)

	def showQuickTip(self, tipReference, numOccurrencesBeforePresentingTip, tipStr):
		#
		# presents a tip/warning about using the app. 'tipReference' tags the tip and
		# 'numOccurrencesBeforePresentingTip' is how many times the situation must occur
		# before the tip is shown. once shown, the tip is never presented again
		#
		quickTipsDict = self.appConfigDict.setdefault('quick_tips', {})
		count = quickTipsDict.get(tipReference, 0)
		if count >= numOccurrencesBeforePresentingTip:
			return
		quickTipsDict[tipReference] = count + 1
		self.saveAppConfig()
		if quickTipsDict[tipReference] >= numOccurrencesBeforePresentingTip:
			tkMessageBox.showinfo(_("airnef Quick Tip"), tipStr)

	#########################################################################
	# menu and toolbar

	def createTopLevelMenu(self):
		menubar = Menu(root)

		filemenu = Menu(menubar, tearoff=0)
		filemenu.add_command(label=_("Last Transfer Report"), command=displayAirnefcmdOutput)
		filemenu.add_separator()
		filemenu.add_command(label=_("Exit"), command=root.quit)
		menubar.add_cascade(label=_("File"), menu=filemenu)

		# language names are shown in their own language so users can always find theirs
		self.languageVar = StringVar(value=self.appConfigDict.get('language', ''))
		languagemenu = Menu(menubar, tearoff=0)
		languagemenu.add_radiobutton(label=_("System default"), value='', variable=self.languageVar, command=self.languageChanged)
		languagemenu.add_separator()
		for language in i18n.availableLanguages():
			languagemenu.add_radiobutton(label=i18n.LANGUAGE_NAMES.get(language, language), value=language,
				variable=self.languageVar, command=self.languageChanged)
		menubar.add_cascade(label=_("Language"), menu=languagemenu)

		helpmenu = Menu(menubar, tearoff=0)
		helpmenu.add_command(label=_("About"), command=self.showAbout)
		menubar.add_cascade(label=_("Help"), menu=helpmenu)

		root.config(menu=menubar)

	def showAbout(self):
		tkMessageBox.showinfo("airnef",
			_("airnef - Version {:s}\n\nRunning under Python Version {:d}.{:d}.{:d}\n\nApplication is licensed under GPL v3\n\n"
			"Special thanks to Joe FitzPatrick for his work on reverse engineering Nikon's Wifi interface\n\n"
			"Camera bitmap courtesy of rg1024 at openclipart.org\n\n"
			"Computer bitmap courtesy of lnasto at openclipart.org\n\n"
			"Icon courtesy of Paomedia at iconfinder.com, licensed under Creative Commons (Attribution 3.0 Unported)")
			.format(AIRNEF_APP_VERSION, sys.version_info.major, sys.version_info.minor, sys.version_info.micro))

	def languageChanged(self):
		self.appConfigDict['language'] = self.languageVar.get()
		self.saveAppConfig()
		rebuildApplication()

	def createToolbar(self):
		toolbar = ttk.Frame(self, padding=(PAD, PAD//2))

		self.backButton = ttk.Button(toolbar, text=_("< Back"), command=self.setContent_Wizard_0)

		connectionFrame = ttk.Frame(toolbar)
		ttk.Label(connectionFrame, text=_("Camera IP address:")).grid(column=0, row=0, sticky=E, padx=(0, PAD//2))
		self.ipAddressEntry = ttk.Entry(connectionFrame, width=16)
		self.ipAddressEntry.insert(0, self.appConfigDict.get('ip_address', "192.168.1.1"))
		self.ipAddressEntry.grid(column=1, row=0, sticky=W, padx=(0, 2*PAD))

		ttk.Label(connectionFrame, text=_("Realtime download:")).grid(column=2, row=0, sticky=E, padx=(0, PAD//2))
		self.realtimeDownloadCombo = ChoiceCombobox(connectionFrame, RealtimeTransferChoices,
			self.configChoice('realtime_download_choice', RealtimeTransferChoices), width=30)
		self.realtimeDownloadCombo.grid(column=3, row=0, sticky=W, padx=(0, 2*PAD))

		ttk.Label(connectionFrame, text=_("Logging:")).grid(column=4, row=0, sticky=E, padx=(0, PAD//2))
		self.loggingLevelCombo = ChoiceCombobox(connectionFrame, LoggingLevelChoices,
			self.configChoice('logging_level_choice', LoggingLevelChoices), width=10)
		self.loggingLevelCombo.grid(column=5, row=0, sticky=W)
		connectionFrame.pack(side=LEFT)

		ttk.Button(toolbar, text=_("Last Transfer Report"), command=displayAirnefcmdOutput).pack(side=RIGHT)
		toolbar.pack(side=TOP, fill=X)
		ttk.Separator(self).pack(side=TOP, fill=X)
		self.toolbarFrame = toolbar

	def showBackButton(self, show):
		if show:
			self.backButton.pack(side=LEFT, padx=(0, 2*PAD), before=self.toolbarFrame.winfo_children()[1])
		else:
			self.backButton.pack_forget()

	#########################################################################
	# shared widgets

	def clearContent(self):
		for widget in self.contentFrame.winfo_children():
			widget.destroy()
		# grid settings are per container, so reset what the previous page configured
		for index in range(4):
			self.contentFrame.columnconfigure(index, weight=0, uniform='')
			self.contentFrame.rowconfigure(index, weight=0)
		for sequence in ('<Return>', '<Escape>'):
			root.unbind(sequence)

	def setHeader(self, title, subtitle=""):
		self.headerLabel['text'] = title
		self.subHeaderLabel['text'] = subtitle

	def getResource_Image(self, filename):
		# keep a reference to each image - Tk doesn't, so it would otherwise be garbage collected
		if filename not in self.resource_PhotoDict:
			self.resource_PhotoDict[filename] = PhotoImage(master=self, file = os.path.join(g.appResourceDir, filename))
		return self.resource_PhotoDict[filename]

	def createOutputOptions(self, parent):
		#
		# "Save to" group shared by both download pages: output directory, what to do with
		# existing files and whether to skip previously downloaded files
		#
		group = ttk.LabelFrame(parent, text=_("Save to"), padding=PAD)
		group.columnconfigure(1, weight=1)

		ttk.Label(group, text=_("Output directory:")).grid(column=0, row=0, sticky=E, padx=(0, PAD), pady=PAD//2)
		self.outputDirCombo = ttk.Combobox(group, state='readonly')
		history = [d for d in self.appConfigDict.get('outputdir_history', []) if isinstance(d, str)]
		self.outputDirCombo['values'] = history if history else [defaultOutputDir()]
		self.outputDirCombo.current(0)
		self.outputDirCombo.grid(column=1, row=0, sticky=EW, pady=PAD//2)
		ttk.Button(group, text=_("Browse..."), command=self.changeDownloadDirectory_ButtonClick).grid(column=2, row=0, sticky=W, padx=(PAD, 0))

		ttk.Label(group, text=_("If file exists:")).grid(column=0, row=1, sticky=E, padx=(0, PAD), pady=PAD//2)
		self.ifExistsCombo = ChoiceCombobox(group, IfExistsChoices, self.configChoice('if_file_exists_choice', IfExistsChoices), width=28)
		self.ifExistsCombo.grid(column=1, row=1, sticky=W, pady=PAD//2)

		self.skipDownloadedVar = BooleanVar(value=bool(self.appConfigDict.get('skip_files_in_download_history_choice', True)))
		ttk.Checkbutton(group, variable=self.skipDownloadedVar,
			text=_("Skip images/movies you've previously downloaded")).grid(column=0, columnspan=3, row=2, sticky=W, pady=(PAD//2, 0))
		return group

	def createStartDownloadButton(self, parent, command):
		button = ttk.Button(parent, image=self.getResource_Image("wifi_200x134.gif"), compound=TOP,
			text=_("Start Download"), style='Primary.TButton', command=command)
		root.bind('<Return>', lambda e : command())
		return button

	def changeDownloadDirectory_ButtonClick(self):
		newDir = tkFileDialog.askdirectory(initialdir=self.outputDirCombo.get(), mustexist=True,
			title=_("Select folder to download images/movies into"))
		if newDir: # user selected a directory
			newDir = os.path.normpath(newDir) # askdirectory() returns unix-style paths, even on Windows
			values = list(self.outputDirCombo['values'])
			if newDir in values:
				values.remove(newDir)
			self.outputDirCombo['values'] = [newDir] + values
			self.outputDirCombo.current(0)

	def saveCommonSettings(self):
		# remember the choices so they are the defaults next time; output dirs are kept most-recently-used first
		outputDirList = list(self.outputDirCombo['values'])
		currentDir = self.outputDirCombo.get()
		if currentDir in outputDirList:
			outputDirList.remove(currentDir)
		self.appConfigDict.update({
			'ip_address' : self.ipAddressEntry.get().strip(),
			'logging_level_choice' : self.loggingLevelCombo.get_key(),
			'realtime_download_choice' : self.realtimeDownloadCombo.get_key(),
			'outputdir_history' : ([currentDir] + outputDirList)[:OUTPUTDIR_HISTORY_MAX],
			'if_file_exists_choice' : self.ifExistsCombo.get_key(),
			'skip_files_in_download_history_choice' : self.skipDownloadedVar.get(),
		})

	def commonSettings(self):
		return {
			'output_dir' : self.outputDirCombo.get(),
			'skip_downloaded' : self.skipDownloadedVar.get(),
			'if_exists' : self.ifExistsCombo.get_key(),
			'ip_address' : self.ipAddressEntry.get().strip(),
			'realtime_download' : self.realtimeDownloadCombo.get_key(),
			'logging_level' : self.loggingLevelCombo.get_key(),
		}

	#########################################################################
	# page 0: choose how to select images

	def setContent_Wizard_0(self):
		self.clearContent()
		self.showBackButton(False)
		self.setHeader(_("How would you like to choose which images to download?"),
			_("Pick the images on the camera itself, or set criteria such as file type and date on this computer."))

		cards = [
			("camera_button_200x134.gif", _("Select in Camera"),
				_("Download the images you've marked for upload on the camera (Nikon)."), self.setContent_Wizard_1_0),
			("computer_200x134.gif", _("Select on Computer"),
				_("Download by file type, capture date, folder and card slot (Nikon, Canon, Sony)."), self.setContent_Wizard_2_0),
		]
		for column, (image, title, description, command) in enumerate(cards):
			self.contentFrame.columnconfigure(column, weight=1, uniform='cards')
			card = ttk.Frame(self.contentFrame, padding=PAD)
			button = ttk.Button(card, image=self.getResource_Image(image), compound=TOP, text=title, style='Card.TButton', command=command)
			button.pack(pady=(PAD, PAD))
			ttk.Label(card, text=description, style='Subtle.TLabel', wraplength=280, justify=CENTER).pack()
			card.grid(column=column, row=0, sticky=N, padx=PAD, pady=PAD)
			if column == 0:
				button.focus_set()

	#########################################################################
	# page 1: download images selected in the camera

	def setContent_Wizard_1_0(self):
		self.clearContent()
		self.showBackButton(True)
		self.setHeader(_("Download images you've selected in the camera"),
			_("airnef downloads the images on the camera's transfer list, then removes them from the list."))
		root.bind('<Escape>', lambda e : self.setContent_Wizard_0())

		self.contentFrame.columnconfigure(0, weight=1)
		leftFrame = ttk.Frame(self.contentFrame)
		leftFrame.columnconfigure(0, weight=1)

		steps = ttk.LabelFrame(leftFrame, text=_("On the camera"), padding=PAD)
		stepTexts = [
			_("Turn your camera on and select which images you'd like to upload. This may be under the "
			"camera's WiFi menu as \"Select to send to smart device\" or in the playback menu, depending on the camera model."),
			_("Make sure your camera's WiFi is on. The camera may sometimes disable it without direction from the user."),
			_("Join your camera's WiFi network on your computer. It will have a name prefixed with \"Nikon\", such as \"Nikon_WU2_0090B6245A45\"."),
		]
		for row, text in enumerate(stepTexts):
			ttk.Label(steps, text="{:d}.".format(row+1)).grid(column=0, row=row, sticky=NW, padx=(0, PAD//2), pady=PAD//2)
			ttk.Label(steps, text=text, wraplength=520, justify=LEFT).grid(column=1, row=row, sticky=W, pady=PAD//2)
		steps.grid(column=0, row=0, sticky=EW)

		self.createOutputOptions(leftFrame).grid(column=0, row=1, sticky=EW, pady=(2*PAD, 0))
		leftFrame.grid(column=0, row=0, sticky=NSEW)

		startButton = self.createStartDownloadButton(self.contentFrame, self.startDownloadSelectedInCamera)
		startButton.grid(column=1, row=0, sticky=N, padx=(3*PAD, 0))
		startButton.focus_set()

	def startDownloadSelectedInCamera(self):
		self.saveCommonSettings()
		self.saveAppConfig()
		launchAirnefcmd(buildArgsSelectInCamera(self.commonSettings()))

	#########################################################################
	# page 2: select images by criteria on the computer

	def setContent_Wizard_2_0(self):
		self.clearContent()
		self.showBackButton(True)
		self.setHeader(_("Set criteria for which images/movies to download"),
			_("Only files matching every criterion are downloaded."))
		root.bind('<Escape>', lambda e : self.setContent_Wizard_0())

		self.contentFrame.columnconfigure(0, weight=1)
		leftFrame = ttk.Frame(self.contentFrame)
		leftFrame.columnconfigure(0, weight=1)

		#
		# what to download: action and file types
		#
		whatGroup = ttk.LabelFrame(leftFrame, text=_("What to download"), padding=PAD)
		ttk.Label(whatGroup, text=_("Download:")).grid(column=0, row=0, sticky=E, padx=(0, PAD), pady=PAD//2)
		self.actionCombo = ChoiceCombobox(whatGroup, ActionChoices, self.configChoice('action_choice', ActionChoices), width=28)
		self.actionCombo.grid(column=1, row=0, sticky=W, pady=PAD//2)

		ttk.Label(whatGroup, text=_("File types:")).grid(column=0, row=1, sticky=E, padx=(0, PAD), pady=PAD//2)
		typesFrame = ttk.Frame(whatGroup)
		savedTypes = self.appConfigDict.get('file_exts', FileTypeChoices)
		self.fileTypeVars = {}
		for column, fileType in enumerate(FileTypeChoices):
			self.fileTypeVars[fileType] = BooleanVar(value=fileType in savedTypes)
			ttk.Checkbutton(typesFrame, text=fileType, variable=self.fileTypeVars[fileType]).grid(column=column, row=0, sticky=W, padx=(0, PAD))
		ttk.Label(typesFrame, text=_("More:")).grid(column=len(FileTypeChoices), row=0, sticky=E, padx=(PAD, PAD//2))
		self.fileTypesMoreEntry = ttk.Entry(typesFrame, width=12)
		self.fileTypesMoreEntry.insert(0, self.appConfigDict.get('file_exts_more', ''))
		self.fileTypesMoreEntry.grid(column=len(FileTypeChoices)+1, row=0, sticky=W)
		typesFrame.grid(column=1, row=1, sticky=W, pady=PAD//2)
		whatGroup.grid(column=0, row=0, sticky=EW)

		#
		# which images: capture date range, card slot and order
		#
		whichGroup = ttk.LabelFrame(leftFrame, text=_("Which images"), padding=PAD)
		ttk.Label(whichGroup, text=_("Capture date:")).grid(column=0, row=0, sticky=E, padx=(0, PAD), pady=PAD//2)
		dateFrame = ttk.Frame(whichGroup)
		self.dateCombo = ChoiceCombobox(dateFrame, DownloadDateChoices, self.configChoice('download_date_choice', DownloadDateChoices), width=18)
		self.dateCombo.bind("<<ComboboxSelected>>", self.dateChoiceChanged)
		self.dateCombo.grid(column=0, row=0, sticky=W)
		ttk.Label(dateFrame, text=_("From:")).grid(column=1, row=0, sticky=E, padx=(2*PAD, PAD//2))
		self.dateStartEntry = ttk.Entry(dateFrame, width=18)
		self.dateStartEntry.insert(0, self.appConfigDict.get('custom_download_date_start', ''))
		self.dateStartEntry.grid(column=2, row=0, sticky=W)
		ttk.Label(dateFrame, text=_("To:")).grid(column=3, row=0, sticky=E, padx=(PAD, PAD//2))
		self.dateEndEntry = ttk.Entry(dateFrame, width=18)
		self.dateEndEntry.insert(0, self.appConfigDict.get('custom_download_date_end', ''))
		self.dateEndEntry.grid(column=4, row=0, sticky=W)
		self.dateHintLabel = ttk.Label(dateFrame, text=_("Format: mm/dd/yy or mm/dd/yy hh:mm:ss"), style='Hint.TLabel')
		self.dateHintLabel.grid(column=1, columnspan=4, row=1, sticky=W, padx=(2*PAD, 0))
		dateFrame.grid(column=1, row=0, sticky=W, pady=PAD//2)
		self.dateChoiceChanged(None)

		ttk.Label(whichGroup, text=_("Media card:")).grid(column=0, row=1, sticky=E, padx=(0, PAD), pady=PAD//2)
		self.cardSlotCombo = ChoiceCombobox(whichGroup, CardSlotChoices, self.configChoice('card_slot_choice', CardSlotChoices), width=28)
		self.cardSlotCombo.grid(column=1, row=1, sticky=W, pady=PAD//2)

		ttk.Label(whichGroup, text=_("Download order:")).grid(column=0, row=2, sticky=E, padx=(0, PAD), pady=PAD//2)
		self.transferOrderCombo = ChoiceCombobox(whichGroup, TransferOrderChoices, self.configChoice('transfer_order_choice', TransferOrderChoices), width=28)
		self.transferOrderCombo.grid(column=1, row=2, sticky=W, pady=PAD//2)
		whichGroup.grid(column=0, row=1, sticky=EW, pady=(2*PAD, 0))

		self.createOutputOptions(leftFrame).grid(column=0, row=2, sticky=EW, pady=(2*PAD, 0))

		#
		# advanced: free-form airnefcmd arguments
		#
		advancedGroup = ttk.LabelFrame(leftFrame, text=_("Advanced"), padding=PAD)
		advancedGroup.columnconfigure(1, weight=1)
		ttk.Label(advancedGroup, text=_("Additional arguments:")).grid(column=0, row=0, sticky=E, padx=(0, PAD))
		self.additionalArgsEntry = ttk.Entry(advancedGroup)
		self.additionalArgsEntry.insert(0, self.appConfigDict.get('additional_args', ''))
		self.additionalArgsEntry.grid(column=1, row=0, sticky=EW)
		advancedGroup.grid(column=0, row=3, sticky=EW, pady=(2*PAD, 0))
		leftFrame.grid(column=0, row=0, sticky=NSEW)

		#
		# action buttons
		#
		rightFrame = ttk.Frame(self.contentFrame)
		startButton = self.createStartDownloadButton(rightFrame, lambda : self.startSelectedOnComputer(False))
		startButton.pack(side=TOP, fill=X)
		ttk.Button(rightFrame, text=_("Preview File List"), command=lambda : self.startSelectedOnComputer(True)).pack(side=TOP, fill=X, pady=(PAD, 0))
		rightFrame.grid(column=1, row=0, sticky=N, padx=(3*PAD, 0))
		self.actionCombo.focus_set()

	def dateChoiceChanged(self, event):
		# the From/To fields only apply to the custom date range
		state = NORMAL if self.dateCombo.get_key() == 'custom' else DISABLED
		for widget in (self.dateStartEntry, self.dateEndEntry):
			widget.configure(state=state)
		if state == NORMAL and event:
			self.dateStartEntry.focus_set()

	def startSelectedOnComputer(self, preview):
		fileTypes = [fileType for fileType in FileTypeChoices if self.fileTypeVars[fileType].get()]
		fileTypesMore = self.fileTypesMoreEntry.get().strip()
		if not fileTypes and not fileTypesMore:
			tkMessageBox.showwarning(_("Selection Issue"), _("At least one file type must be checked or entered, otherwise there won't be anything to download."))
			return
		dateStart = self.dateStartEntry.get().strip()
		dateEnd = self.dateEndEntry.get().strip()
		if self.dateCombo.get_key() == 'custom':
			for (dateStr, title) in ((dateStart, _("Invalid Start Date")), (dateEnd, _("Invalid End Date"))):
				if dateStr and not isValidCustomDate(dateStr):
					tkMessageBox.showwarning(title, _("The date \"{:s}\" is formatted incorrectly or is not a valid date/time. It must be formatted as mm/dd/yy or mm/dd/yy hh:mm:ss (including leading zeros).").format(dateStr))
					return

		self.saveCommonSettings()
		self.appConfigDict.update({
			'action_choice' : self.actionCombo.get_key(),
			'file_exts' : fileTypes,
			'file_exts_more' : fileTypesMore,
			'download_date_choice' : self.dateCombo.get_key(),
			'custom_download_date_start' : dateStart,
			'custom_download_date_end' : dateEnd,
			'card_slot_choice' : self.cardSlotCombo.get_key(),
			'transfer_order_choice' : self.transferOrderCombo.get_key(),
			'additional_args' : self.additionalArgsEntry.get(),
		})
		self.saveAppConfig()

		settings = self.commonSettings()
		settings.update({
			'action' : self.actionCombo.get_key(),
			'file_exts' : fileTypes,
			'file_exts_more' : fileTypesMore,
			'download_date' : self.dateCombo.get_key(),
			'custom_date_start' : dateStart,
			'custom_date_end' : dateEnd,
			'card_slot' : self.cardSlotCombo.get_key(),
			'transfer_order' : self.transferOrderCombo.get_key(),
			'additional_args' : self.additionalArgsEntry.get(),
		})
		launchAirnefcmd(buildArgsSelectOnComputer(settings, preview))


#
# (re)creates the main window contents, used at startup and when the language changes
#
def rebuildApplication():
	if g.app:
		g.app.destroy()
	language = g.app.appConfigDict.get('language', '') if g.app else readConfiguredLanguage()
	i18n.setLanguage(language or i18n.detectSystemLanguage())
	g.app = Application(master=root)
	root.update_idletasks()
	root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())


#
# reads the interface language from the app config before the Application exists
#
def readConfiguredLanguage():
	try:
		with open(os.path.join(g.appDataDir, "airnef-gui1-config"), encoding="utf-8") as f:
			config = json.load(f)
		return config.get('language', '') if isinstance(config, dict) else ''
	except (OSError, ValueError):
		return ''


#
# verifies user is running version a modern-enough version of python for this app
#
def verifyPythonVersion():
	if sys.version_info < (3, 12):
		print("Warning: You are running a Python version older than app was tested with.")
		print("Version running is {:d}.{:d}.{:d}, app requires 3.12 or newer".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro))

#
# sets app-level globals related to the platform we're running under and
# creates path to app directories, creating them if necessary
#
def establishAppEnvironment():

	g.isWin32 = (platform.system() == 'Windows')
	g.isOSX = (platform.system() == 'Darwin')
	g.isFrozen = (getattr(sys, 'frozen', False))

	#
	# determine the directory our script resides in, in case the
	# user is executing from a different working directory.
	#
	g.appDir = os.path.dirname(os.path.realpath(sys.argv[0]))
	g.appResourceDir = os.path.join(g.appDir, "appresource")

	#
	# determine directory for our APPDATA, which contains log
	# and configuration files. For Win32 if we're frozen this
	# goes in the dedicated OS area for application data files.
	# must match the logic in airnefcmd.py, which writes the report we display
	#
	g.appDataDir = os.getenv('AIRNEF_APPDATA')
	if g.appDataDir:
		pass
	elif g.isFrozen and g.isWin32:
		if os.getenv('LOCALAPPDATA'):
			g.appDataDir = os.path.join(os.getenv('LOCALAPPDATA'), "airnef\\appdata") # typically C:\Users\<username>\AppData\Local\airnef\appdata
	elif g.isOSX: # for OSX we always try to store our app data under Application Support
		userHomeDir = os.getenv('HOME')
		if userHomeDir:
			applicationSupportDir = os.path.join(userHomeDir, 'Library/Application Support')
			if os.path.exists(applicationSupportDir): # probably not necessary to check existence since every system should have this directory
				g.appDataDir = os.path.join(applicationSupportDir, 'airnef/appdata')
	if not g.appDataDir:
		# none of runtime-specific cases above selected an app data directory - use directory based off our app directory
		g.appDataDir = os.path.join(g.appDir, "appdata")
	# create our app-specific subdirectories if necessary
	if not os.path.exists(g.appDataDir):
		os.makedirs(g.appDataDir)


#
# makes the window crisp on high-DPI Windows displays (otherwise Windows bitmap-scales the whole UI)
#
def enableHighDpiAwareness():
	if g.isWin32:
		try:
			import ctypes
			ctypes.windll.shcore.SetProcessDpiAwareness(1)	# system DPI aware
		except (AttributeError, OSError):
			pass


#
# main app routine
#
def main():

	global root

	verifyPythonVersion()
	establishAppEnvironment()
	enableHighDpiAwareness()

	root = Tk()
	if not os.path.exists(g.appResourceDir):
		tkMessageBox.showwarning("Setup Error", "The appresource subdirectory is missing. This directory and its files (icons/bitmaps/etc..) are needed for proper functioning of airnef :(")
		return
	configureStyles(root)
	rebuildApplication()
	root.mainloop()
	try: # root.destroy() throws exception if user exited app via native OS menu. Can't find a way to detect if it's been destroyed
		root.destroy()
	except:
		pass

#
# program entry point
#
if __name__ == "__main__":
	main()
