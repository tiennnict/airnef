"""
Extracts translatable strings - the literal arguments of _() and N_() - from the
airnef sources into locale/airnef.pot, and merges new strings into existing catalogs.

    uv run tools/extract_messages.py          # update locale/airnef.pot and every airnef.po
    uv run tools/extract_messages.py --check  # exit 1 if a catalog is missing translations

Uses the Python AST, so implicit string concatenation across lines is handled the same
way the interpreter handles it. Existing translations are preserved when merging.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
from airnef import i18n  # noqa: E402

SOURCES = ['src/airnef/gui.py']


def extract():
    """Returns [(msgid, [locations])] in order of first appearance."""
    messages = {}
    for source in SOURCES:
        path = os.path.join(ROOT, source)
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=source)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('_', 'N_')
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                messages.setdefault(node.args[0].value, []).append('{:s}:{:d}'.format(source, node.lineno))
    return sorted(messages.items(), key=lambda item: (item[1][0].split(':')[0], int(item[1][0].split(':')[1])))


def po_quote(text):
    escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\t', '\\t')
    lines = escaped.split('\n')
    if len(lines) == 1:
        return '"{}"'.format(escaped)
    parts = [line + '\\n' for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    return '""\n' + '\n'.join('"{}"'.format(p) for p in parts)


def write_catalog(path, messages, header, translations=None):
    out = [header]
    for msgid, locations in messages:
        out.append('#: ' + ' '.join(locations))
        out.append('msgid ' + po_quote(msgid))
        out.append('msgstr ' + po_quote((translations or {}).get(msgid, '')))
        out.append('')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out))


def header_for(language):
    return '\n'.join([
        '# airnef user interface translations' + (' ({})'.format(i18n.LANGUAGE_NAMES.get(language, language)) if language else ' (template)'),
        '# This file is distributed under the same license as airnef (GPL v3).',
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: airnef\\n"',
        '"Language: {}\\n"'.format(language or ''),
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        ''])


def main():
    messages = extract()
    check = '--check' in sys.argv
    missing_total = 0
    if not check:
        write_catalog(os.path.join(i18n.LOCALE_DIR, i18n.DOMAIN + '.pot'), messages, header_for(None))
    for language in i18n.availableLanguages()[1:]:
        path = os.path.join(i18n.LOCALE_DIR, language, 'LC_MESSAGES', i18n.DOMAIN + '.po')
        translations = i18n.parsePoFile(path)
        missing = [msgid for msgid, _ in messages if msgid not in translations]
        missing_total += len(missing)
        for msgid in missing:
            print('{}: untranslated: {!r}'.format(language, msgid))
        if not check:
            write_catalog(path, messages, header_for(language), translations)
    print('{:d} messages, {:d} untranslated'.format(len(messages), missing_total))
    return 1 if (check and missing_total) else 0


if __name__ == '__main__':
    sys.exit(main())
