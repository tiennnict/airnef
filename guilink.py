#!/usr/bin/env python

#
#############################################################################
#
# guilink.py - Link between airnefcmd and the GUI (airnef.pyw)
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# When the GUI runs airnefcmd it passes --guimode yes, starts it without a console
# window and talks to it over the stdout/stdin pipes instead:
#
#   airnefcmd -> GUI (stdout, one line each; ordinary log lines are shown as text):
#       @@PROGRESS <TAB> file name <TAB> bytes received <TAB> bytes expected
#       @@DONE     <TAB> file name <TAB> size in bytes <TAB> seconds
#       @@PROMPT   <TAB> question <TAB> valid keys
#   GUI -> airnefcmd (stdin, one line each):
#       cancel                     same as pressing <ctrl-c> in the console
#       answer <TAB> key           reply to a @@PROMPT
#
# If the GUI goes away (stdin closes) airnefcmd cancels itself, so it never keeps
# running invisibly.
#
#############################################################################
#

import _thread
import queue
import sys
import threading

import applog
import mtpwifi

PREFIX = '@@'

_enabled = False
_answers = queue.Queue()
_currentFile = ''


def isEnabled():
	return _enabled


#
# switches airnefcmd to GUI mode: no console status-line effects, UTF-8 line-buffered output
# and a background thread that reads commands from the GUI
#
def enable():
	global _enabled
	_enabled = True
	applog.gConsoleStatusEnabled = False
	try:
		sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
		sys.stdin.reconfigure(encoding='utf-8', errors='replace')
	except (AttributeError, ValueError):
		pass
	threading.Thread(target=_readCommands, name='airnef-guilink', daemon=True).start()


def _readCommands():
	for line in sys.stdin:
		line = line.rstrip('\r\n')
		if line == 'cancel':
			_requestCancel()
		elif line.startswith('answer\t'):
			_answers.put(line[len('answer\t'):])
	_requestCancel() # stdin closed: the GUI is gone


#
# cancels like <ctrl-c>. during a camera transaction the transport is asked to cancel at a safe point; at any
# other time (waiting, sleeping between retries, enumerating) a KeyboardInterrupt is raised in the main thread
#
def _requestCancel():
	if mtpwifi.gInTransaction:
		mtpwifi.requestCancel()
	else:
		_thread.interrupt_main()

def _emit(*fields):
	print(PREFIX + '\t'.join(str(f).replace('\t', ' ').replace('\n', ' ') for f in fields), flush=True)


def setCurrentFile(name):
	global _currentFile
	_currentFile = name

def emitProgress(bytesReceived, bytesExpected):
	if _enabled:
		_emit('PROGRESS', _currentFile, bytesReceived, bytesExpected)

def emitDone(name, sizeBytes, seconds):
	if _enabled:
		_emit('DONE', name, sizeBytes, '{:.3f}'.format(seconds))


#
# asks the GUI user to press one of validKeys. returns the (uppercase) key
#
def prompt(question, validKeys):
	_emit('PROMPT', question, validKeys)
	while True:
		try:
			answer = _answers.get(timeout=0.2) # short timeouts keep <ctrl-c>/cancel responsive
		except queue.Empty:
			continue
		if answer and answer.upper() in validKeys.upper():
			return answer.upper()
