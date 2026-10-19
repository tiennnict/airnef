# Changelog

All notable changes to this fork of [airnef](https://github.com/tiennnict/airnef) relative to the
original v1.1 release. The version number lives in `version.py`.

## 2.0.0

### Platform
- Ported to Python 3 (3.12 or newer); Python 2 and the bundled `six.py` are gone.
- Project is managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml`, `uv.lock`,
  `.python-version`); run it with `uv sync` / `uv run`.
- Packaged: the code is the `airnef` package (`src/airnef/`) built with `uv_build`, with `airnef`
  (GUI, no console window on Windows) and `airnefcmd` commands; install with
  `uv tool install git+https://github.com/tiennnict/airnef`. The former flat modules
  (`cmdline`, `appstate`, ...) no longer clutter the top-level import namespace.
- Settings, logs, history and the object cache live in a per-user directory (`paths.py`) instead of
  next to the code; a checkout's existing `appdata` directory keeps being used.
- The GUI launches `airnefcmd` with its own interpreter instead of whatever `python` is on `PATH`.
- Prebuilt installers (Windows, OS X `.dmg`, Linux binaries) are no longer part of this repository.

### Transport (CIPA DC-005 / PTP-IP)
- Event channel serviced on a background thread: answers camera Probe Requests so the session is
  not dropped, and queues events.
- Realtime downloads react immediately to `ObjectAdded` events; polling remains as the fallback.
- `<ctrl-c>` (or Cancel in the GUI) cancels the running transaction with a Cancel packet on both
  connections and waits for `Transaction_Cancelled`, so the session closes cleanly. The cancel is
  noticed within 250 ms at a safe point before each socket read, so no received bytes can be lost.
- TCP keep-alive on both connections; full Init Command Ack parsing; Init Fail reasons reported
  (a busy camera is retried); TransactionIDs restart at 1 for each session.
- Fixed hangs when `recv()` returns no data, split length prefixes, partial `send()`, and
  64-bit / unknown "Total Data Length" in Start Data packets.

### Performance and large files
- Bulk enumeration with `GetObjectPropList` or `GetFilesystemManifest` instead of one
  `GetObjectInfo` per file (new hidden `--objinfomethod` option); falls back automatically.
- Files of 4GB or more are downloaded in full using `GetPartialObject64` / Nikon
  `GetPartialObjectEx` (previously truncated at 4GB).
- Larger socket receive buffer; O(1) insertion for the capture-date sorted list.

### Object cache
- The MTP object cache is stored as versioned JSON written atomically instead of a pickle file
  (no code execution risk, no SHA-512 side file). Obsolete v1.x pickle caches are removed.

### GUI
- Redesigned with themed ttk widgets (native look on Windows/macOS), grouped options, titled
  pages, resizable window, high-DPI support on Windows, keyboard shortcuts (Enter / Escape) and a
  read-only transfer report with Copy and Close buttons.
- Translations (gettext `.po`, no extra dependency): English and Vietnamese, selectable from the
  **Language** menu; `tools/extract_messages.py` maintains the template and catalogs.
- Settings are stored as language-independent keys; settings saved by v1 are still understood.
- Output paths containing spaces or quotes are passed to `airnefcmd` intact.
- Self-contained: airnefcmd runs in the background and a transfer window shows per-file progress,
  totals and speed, the details and a Cancel button; no terminal window is needed. The GUI and
  airnefcmd talk over pipes (hidden `--guimode`, see `guilink.py`), and airnefcmd cancels itself
  if the GUI disappears. "If file exists: prompt" is answered in a dialog.

### Fixes
- `Start Download` failed with `NameError` (missing `re` import after the Python 3 port).
- Custom start date was saved under the end-date key.
- `--extlist` matching is case-insensitive as documented.
- A malformed download-history line no longer deletes the whole history; history and logs are UTF-8.
- Session log closed twice and lifetime log never closed; UTF-16 helpers mishandled non-ASCII text.
- `GetPartialObject` advanced by the requested rather than received byte count.
- `MtpObject.genFullPathStr()` raised `NameError` when a parent folder was missing.
- Capture-date linked list lost its tail pointer on `remove()` and raised `NameError` in `insert()`.

### Internals and tests
- `airnefcmd.py` split into `appstate`, `mtpdatasets`, `camerasession`, `objectcatalog`,
  `downloader`, `realtime` and `cmdline`; command-line behaviour unchanged.
- Simulated PTP/IP camera (`tests/ptpip_sim.py`) and a pytest suite including end-to-end
  downloads; hidden `--port` option and `AIRNEF_APPDATA` override to support it.
- Documentation converted to Markdown under `docs/`.

## 1.1

Original release by testcams.com (the starting point of this fork).
