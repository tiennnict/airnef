#!/usr/bin/env python

#
#############################################################################
#
# i18n.py - Translation support
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# User-visible strings are written in English and wrapped in _() (or N_() where
# the string must be marked for translation but looked up later). Translations
# live in standard gettext catalogs:
#
#     locale/<language>/LC_MESSAGES/airnef.po
#
# The .po files are read directly by a small parser, so no compilation step (.mo)
# or third-party package is needed, while the files stay compatible with the usual
# gettext tools (xgettext, msgmerge, Poedit, Weblate, ...).
#
#############################################################################
#

import os
import sys
import locale

DOMAIN = 'airnef'
SOURCE_LANGUAGE = 'en'
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locale')

# native names of the languages, shown untranslated in the language menu
LANGUAGE_NAMES = {
	'en' : 'English',
	'vi' : 'Tiếng Việt',
}

_catalog = {}
_language = SOURCE_LANGUAGE


#
# decodes the C-style escapes allowed in .po strings
#
def _unescapePoString(text):
	result = []
	i = 0
	while i < len(text):
		ch = text[i]
		if ch == '\\' and i + 1 < len(text):
			nxt = text[i+1]
			result.append({'n' : '\n', 't' : '\t', '"' : '"', '\\' : '\\', 'r' : '\r'}.get(nxt, '\\' + nxt))
			i += 2
		else:
			result.append(ch)
			i += 1
	return ''.join(result)


#
# parses a .po file into { msgid : msgstr }. fuzzy and untranslated entries are skipped
# so the English source text is shown for them
#
def parsePoFile(path):
	catalog = {}
	entry = {}
	field = None
	fuzzy = False

	def finishEntry():
		if 'msgid' in entry and entry.get('msgstr') and entry['msgid'] and not fuzzy:
			catalog[entry['msgid']] = entry['msgstr']

	with open(path, encoding='utf-8') as f:
		for rawLine in f:
			line = rawLine.strip()
			if not line:
				continue
			if line.startswith('#'):
				if line.startswith('#,') and 'fuzzy' in line:
					finishEntry()
					entry, field, fuzzy = {}, None, True
				continue
			if line.startswith('msgid '):
				if field == 'msgstr':
					finishEntry()
					entry, fuzzy = {}, False
				field = 'msgid'
				entry['msgid'] = _unescapePoString(line[6:].strip()[1:-1])
			elif line.startswith('msgstr '):
				field = 'msgstr'
				entry['msgstr'] = _unescapePoString(line[7:].strip()[1:-1])
			elif line.startswith('"') and field:
				entry[field] += _unescapePoString(line[1:-1])
	finishEntry()
	return catalog


#
# returns the languages that have a catalog (plus the English source language)
#
def availableLanguages():
	languages = [SOURCE_LANGUAGE]
	if os.path.isdir(LOCALE_DIR):
		for name in sorted(os.listdir(LOCALE_DIR)):
			if os.path.exists(os.path.join(LOCALE_DIR, name, 'LC_MESSAGES', DOMAIN + '.po')):
				languages.append(name)
	return languages


#
# determines the user's preferred language from the environment / OS settings
#
def detectSystemLanguage():
	candidates = []
	for envVar in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
		value = os.environ.get(envVar)
		if value:
			candidates += value.split(':')
	if sys.platform == 'win32':
		try:
			import ctypes
			langId = ctypes.windll.kernel32.GetUserDefaultUILanguage()
			candidates.append(locale.windows_locale.get(langId, ''))
		except (AttributeError, OSError):
			pass
	try:
		candidates.append(locale.getlocale()[0] or '')
	except ValueError:
		pass
	available = availableLanguages()
	for candidate in candidates:
		code = candidate.split('.')[0].split('_')[0].lower()
		if code in available:
			return code
	return SOURCE_LANGUAGE


#
# switches the active language. unknown languages fall back to English
#
def setLanguage(language):
	global _catalog, _language
	if language not in availableLanguages():
		language = SOURCE_LANGUAGE
	_language = language
	_catalog = {}
	if language != SOURCE_LANGUAGE:
		_catalog = parsePoFile(os.path.join(LOCALE_DIR, language, 'LC_MESSAGES', DOMAIN + '.po'))
	return language


def getLanguage():
	return _language


#
# translates a message; untranslated messages are returned unchanged
#
def gettext(message):
	return _catalog.get(message, message)

_ = gettext


#
# marks a string for translation without translating it at that point (for tables that
# are defined at import time and translated when displayed)
#
def N_(message):
	return message
