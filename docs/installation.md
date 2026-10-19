# Installation

> Docs: [README](../README.md) · [Installation](installation.md) · [Camera setup](camera-setup.md) · [User guide](user-guide.md) · [Renaming engine](renaming-engine.md) · [Command line](command-line-reference.md) · [FAQ](faq.md)

## Windows Installer

1. Download the Windows installer and launch it
1. The application is unsigned so you'll receive a warning from Windows about it coming from an "unknown publisher"
1. Once the installer is running you'll be prompted to agree to the GPL v3 license.
1. You'll then be prompted for the installation directory, which defaults to C:\Program Files\airnef (32-bit Windows) or C:\Program Files (x86)\airnef (64-bit Windows)
1. A start-menu folder will be created under testcams.com, from which you can launch Airnef
Here are a few post-installation Windows tips that will help make Airnef more convenient to use:

1. Windows Wireless Tip - There is a one-time wireless setup you can perform that will allow Windows to automatically switch to your camera's WiFi network whenever you turn your camera on and/or enable its WiFi. This is much more convenient than having to manually select the network every time you'd like to download images/videos from your camera. Here are the steps for the one-time setup:
  1. Turn on your camera's WiFi feature and wait for the network to be listed in the available wireless network list. It should have a name prefixed with "Nikon_", such as "Nikon_WU2_52A670FB7F45". When you see the camera's network listed, click on the network and make sure "Connect automatically" is checked, then press "Connect" button.
  1. Right-click the WiFi icon in the bottom-right system tray and select "Open Network and Sharing Center", then click "Manage wireless networks" in the dialog that comes up. You'll be presented with a list of all the wireless networks you have ever connected to on your network. The list is sorted in order of connection priority, with the first item having the highest priority. Make sure the Nikon wireless network you just added is at the top of the priority list.
  1. Even though you've made the Nikon network the highest priority, Windows will still connect to your main home/work wireless network when you don't have your camera powered on and its WiFi enabled. This is desirable. However, whenever you do turn on your camera and its WiFi to download images, by default Windows will not drop the connection to your home/work network and automatically switch to your camera's network. To have it automatically switch to your camera's WiFi network whenever it's available, right-click on your home/work network(s) and select 'Properties' from the pop-up menu. Then check the box "Connect to a more preferred network if available" and press OK to accept the changes. Now whenever you turn your camera's on and enable its WiFi your system will automatically switch to its network. Note that sometimes Windows will a while before automatically switching to the camera's network after it becomes available - you can expedite the process by clicking on the WiFi icon in the bottom-right system tray. This causes Windows to perform a network rescan immediately rather than waiting its normal polling interval.
1. Whenever you'd like to cancel the current Airnef download/operation, press <ctrl-c> within the terminal window that airnefcmd is running. **DO NOT click the "X" in that terminal window's title bar** - doing this will cause airnefcmd to be terminated without properly cleaning up the resources and files it was processing.

## OS X application (.dmg)

1. Download the OS X .dmg and double-click it
1. The virtual disk image will be mounted and it should automatically open up to reveal the Airnef application and a shortcut to your Applications folder.
1. Drag and drop the Airnef application into the Applications shortcut icon.
1. The application is unsigned so you'll likely need to perform a one-time security override to permanently add the application to OS X's safe application list. You can do this by right-clicking (Control-Mouse Click) on the Airnef icon in your Applications folder and selecting open.
1. Agree to open the application when prompted about it being downloaded from the internet.
1. Airnef requires xterm but newer versions of OSX don't install it by default. You can install it from XQuartz, which is an Apple Project.
Here are a few post-installation OS X tips that will help make Airnef more convenient to use:

1. When you tell the Airnef GUI to start downloading images it launches the airnefcmd application in a terminal window to perform the actual download. When airnefcmd has completed its downloads, OS X will by default leave the terminal window open, requiring you to manually close it. This can be annoying because you'll have to repeat this action after every download completion. Fortunately the OS X terminal app has a configurable setting which allows the terminal window to automatically close after a console app has completed. In the Terminal application, select 'Preferences' in the menu. In the dialog that opens, click 'Profiles' in the top left and then the 'Shell' tab. Set "When the shell exits" to either "Close if the shell exited cleanly" or "Close". See this sample screen image of the dialog to help you locate this option.
1. Whenever you'd like to cancel the current Airnef download/operation, press <ctrl-c> within the terminal window that airnefcmd is running. **DO NOT click the "X" in that terminal window's title bar** - doing this will cause airnefcmd to be terminated without properly cleaning up the resources and files it was processing.

## Linux Binary

1. The Linux binary ships in a compressed image that expands to directory tree of files, with the base directory expanding as ./airnef. You can unzip to your directory of choice and optionally add that directory/airnef to PATH
1. The GUI is airnef/airnef and the command-line utility is airnef/airnefcmd

## Windows/OS X/Linux running Airnef source with installed Python interpreter

Instead of running the bundled Python environment that ships with the pre-built executables you can also run the source through your existing Python installation. Airnef supports both Python 2.7.x and 3.4.x environments. OS X and most Linux distributions install Python by default. For Linux the Tkinter GUI framework may not come preinstalled; you can install it via "sudo apt-get install python-tk". For Windows you'll need to download and install Python - I suggest enabling the option to add Python to your system path during the installation. For Linux and OSX you may need to set the airnef.pyw and airnefcmd.py as executable via 'chmod +x airnef.pyw' and 'chmod +x airnefcmd.py'
