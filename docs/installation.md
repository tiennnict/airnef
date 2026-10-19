# Installation

> Docs: [README](../README.md) · [Installation](installation.md) · [Camera setup](camera-setup.md) · [User guide](user-guide.md) · [Renaming engine](renaming-engine.md) · [Command line](command-line-reference.md) · [FAQ](faq.md)

## Prebuilt releases

The original Windows installer, OS X `.dmg` and Linux binaries published by testcams.com are
**not provided in this repository**. This fork runs from source.

## Requirements

- **Python 3.12 or newer** (the project pins 3.15 in `.python-version`; Python 2 is not supported).
- [uv](https://docs.astral.sh/uv/), which creates the project's own virtual environment (`.venv`)
  and installs the locked dependencies. airnef itself needs no third-party packages.
- Tkinter for the GUI. It ships with Python on Windows and macOS; on Linux install it with
  `sudo apt-get install python3-tk` (or your distribution's equivalent).

## Running from source

```bash
git clone https://github.com/tiennnict/airnef.git
cd airnef
uv sync                          # creates .venv from pyproject.toml / uv.lock
uv run airnef.pyw                # GUI
uv run airnefcmd.py --help       # command-line app
uv run pytest                    # test suite (uses a simulated PTP/IP camera)
```

`uv sync` downloads a suitable Python if none is installed. The GUI launches `airnefcmd.py` with
the same interpreter, so there is nothing else to configure.

On Windows the download runs in its own console window. On macOS and Linux the `airnefcmd` output
appears in the terminal you started the GUI from, so start it from a terminal.

Whenever you'd like to cancel the current Airnef download/operation, press `<ctrl-c>` in the
console/terminal window that airnefcmd is running in. **Do not click the "X" in that window's
title bar** - doing this terminates airnefcmd without properly cleaning up the resources and files
it was processing.

airnef keeps its settings, download history, logs and object cache in the `appdata` directory next
to the scripts.

## Windows wireless tip

There is a one-time wireless setup you can perform that will allow Windows to automatically switch to your camera's WiFi network whenever you turn your camera on and/or enable its WiFi. This is much more convenient than having to manually select the network every time you'd like to download images/videos from your camera. Here are the steps for the one-time setup:

1. Turn on your camera's WiFi feature and wait for the network to be listed in the available wireless network list. It should have a name prefixed with "Nikon_", such as "Nikon_WU2_52A670FB7F45". When you see the camera's network listed, click on the network and make sure "Connect automatically" is checked, then press "Connect" button.
1. Right-click the WiFi icon in the bottom-right system tray and select "Open Network and Sharing Center", then click "Manage wireless networks" in the dialog that comes up. You'll be presented with a list of all the wireless networks you have ever connected to on your network. The list is sorted in order of connection priority, with the first item having the highest priority. Make sure the Nikon wireless network you just added is at the top of the priority list.
1. Even though you've made the Nikon network the highest priority, Windows will still connect to your main home/work wireless network when you don't have your camera powered on and its WiFi enabled. This is desirable. However, whenever you do turn on your camera and its WiFi to download images, by default Windows will not drop the connection to your home/work network and automatically switch to your camera's network. To have it automatically switch to your camera's WiFi network whenever it's available, right-click on your home/work network(s) and select 'Properties' from the pop-up menu. Then check the box "Connect to a more preferred network if available" and press OK to accept the changes. Now whenever you turn your camera's on and enable its WiFi your system will automatically switch to its network. Note that sometimes Windows will a while before automatically switching to the camera's network after it becomes available - you can expedite the process by clicking on the WiFi icon in the bottom-right system tray. This causes Windows to perform a network rescan immediately rather than waiting its normal polling interval.
