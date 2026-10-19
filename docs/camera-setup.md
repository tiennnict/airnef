# One-Time Camera Setup

> Docs: [README](../README.md) · [Installation](installation.md) · [Camera setup](camera-setup.md) · [User guide](user-guide.md) · [Renaming engine](renaming-engine.md) · [Command line](command-line-reference.md) · [FAQ](faq.md)

## Nikon Cameras

By default your Nikon camera has an IP address of 192.168.1.1 and runs without encryption. You can modify both the IP address and wireless security via a one-time procedure using Nikon's Wireless Mobile Utility app (iOS and Android). Modifying the IP address of your camera is useful if you run a typical network configuration that has the router at 192.168.1.1, which conflicts with the camera and makes it impossible to use a wired connection to your router/Internet at the same time you'd like to download from the camera. Here are instructions for the one-time procedure to change your cameras IP address:

1. Install the Nikon Wireless Mobile Utility (WMU) app on your phone (iOS and Android).
1. Turn your camera's WiFi on and then have your phone/tablet connect to that Network (Nikon's network usually starts with "Nikon_", such as "Nikon_WU2_52A670FB7F45"
1. Run WMU and click the gear icon at the top-right of the main screen to get to the Settings page.
1. Click "WMA Settings" on the Settings Page.
1. Click "Advanced Settings" on the WMA Settings Page.
1. On the Advanced Settings Page, click on the DHCP Server IP address and change the subnet. For example, change it from the default of 192.168.1.1 to 192.168.2.1. Then click the DHCP client IP address and change it to the same subnet. For example, from 192.168.1.2 to 192.168.2.2.
1. You're done. Enter the new DHCP Server IP address in the Camera IP address field of Airnef (192.168.2.1 in this example).

## Nikon D500 and other SnapBridge Cameras

Nikon recently introduced their SnapBridge technology on the D500. SnapBridge is an "always-on" connectivity feature that allows the camera to use a low-power bluetooth connection to send JPEGs to a smartphone/tablet, both automatically in realtime as photographs are taken and manually if the user prefers to select specific images to download. Most SnapBridge implementations including the one of the D500 also include WiFi capability to allow for faster download of a large batch of images from the camera. Fortunately this WiFi implementation is identical to the MTP implementation on previous Nikon bodies, which means it is compatible with Airnef. Unfortunately, Nikon only allows the WiFi on SnapBridge-enabled cameras to be activated through the SnapBridge app - Nikon removed the ability for users to manually turn on the WiFi from the camera. This means that in order to use Airnef with SnapBridge-featured cameras you must first use the SnapBridge app to activate the camera's WiFi, then intervene to have Airnef to connect to the camera's WiFi network before the SnapBridge app does. Here are instructions on how to do this for both the iOS and Android versions of the SnapBridge app:

One-Time Setup:

1. Install the SnapBridge app on your smartphone/tablet, using Apple's App Store (iOS) or Google's Play Store (Android).
1. Follow the SnapBridge app instructions to perform the one-time bluetooth paring between your smartphone/tablet and the camera. This only needs to be done once for a given smart device/camera pair.
Activating the camera's WiFi using the iOS SnapBridge App:

1. Click the 'Camera' icon on the bottom row of icons within the SnapBridge app, then click "Download selected pictures"
1. You will be prompted to confirm that you wish to temporarily switch SnapBridge from bluetooth to WiFi - click "Yes" to confirm.
1. At this point the SnapBridge app will connect to the camera's bluetooth (if it isn't already connected) and will then activate/enable the camera's WiFi. This may take a while because the bluetooth connection process is sometimes very slow - see the 'Additional Details' section below for a method to accelerate this process. After activating the camera's WiFi the SnapBridge app will then prompt you to go into your iPhone/iPad's settings to connect to the camera's WiFi - do not do this. Instead, click "Close".
1. The camera's WiFi is now enabled. Join the camera's network from your computer - the network will be your cameras model number + serial number. Launch Airnef and set the IP address of Camera IP Address to 192.168.1.1. Read the 'Additional Details' section below.
Activating the camera's WiFi using the Android SnapBridge App:

1. Temporarily disable the WiFi on your smartphone/tablet. This is necessary to prevent the SnapBridge app from automatically connecting to the camera's WiFi network after you enable the camera' WiFi within the SnapBridge app.
1. Click the 'Camera' icon on the top row of icons within the SnapBridge app, then click "Download selected pictures".
1. You will be prompted to confirm that you wish to temporarily switch SnapBridge from bluetooth to WiFi - click "OK" to confirm.
1. At this point the SnapBridge app will connect to the camera's bluetooth (if it isn't already connected) and will then activate/enable the camera's WiFi. This may take a while because the bluetooth connection process is sometimes very slow - see the 'Additional Details' section below for a method to accelerate this process. After activating the camera's WiFi the SnapBridge app will then attempt to connect to the camera's WiFi network but will fail because we disabled your smart device's WiFi in step #1. The SnapBridge app will report this failure in a pop-up. Even though the SnapBridge app reported this error the camera's WiFi is now enabled.
1. The camera's WiFi is now enabled. Join the camera's network from your computer - the network will be your cameras model number + serial number. Launch Airnef and set the IP address of Camera IP Address to 192.168.1.1. Read the 'Additional Details' section below.
Additional Details:

1. The camera's WiFi will only stay enabled for a single Airnef session - it will revert back to disabled when the session is over. A session starts when you click the 'Start Download' (or 'Preview File List') button within Airnef and ends when the operations associated with that action have completed. Even though Airnef remains running after the session is over (in a state ready to perform another action/session), the camera's WiFi is now disabled. To perform another action/session from Airnef you will need to repeat the 'Activating the camera's WiFi' steps above.
1. Although the camera's WiFi is enabled for only a single Airnef session at a time, that single session can optionally use realtime download feature of Airnef, which will keep the session open for as long as you'd like, allowing you to transfer images from the camera to your computer in realtime as you take them. See the Realtime Downloads section for details on this feature.
1. By default the D500 is configured to use WPA-2 encryption, with a password default of "NIKOND500". You can change the default password in the camera's Setup -> WiFi menu (or optionally switch to an unsecure OPEN network without a password). Note that in order to change the WiFi configuration you'll need to first disable the camera's bluetooth (Setup -> Bluetooth -> Network connection to OFF)
1. Unlike previous, non-SnapBridge enabled cameras, Nikon does not allow the user to configure the IP subnet/address of the camera's WiFi network. Instead, the camera's network is hard-coded to use subnet 192.168.1.x, with the camera's IP address set to 192.168.1.1. If your computer uses a dual-network setup, where you connect to your local network+internet through a wired ethernet connection and use your WiFi for Airnef, you will need to either make sure that your wired network is configured for a subnet other than 192.168.1.x (which is the default for most ethernet routers) or you will need to temporarily disable your ethernet connection while using Airnef so that it doesn't conflict with the camera's 192.168.1.x network.
1. Sometimes the SnapBridge app can take a long time to establish its bluetooth connection to the camera - this bluetooth connection is required for the SnapBridge app to command the camera to enable its WiFi. You can accelerate the bluetooth connection process by going into the camera's setup menu, selecting 'Bluetooth', then 'Paired Devices', then selecting your smartphone/tablet device within the list of paired devices.

## Sony Cameras

To enable wireless transfer-to-desktop functionality Sony cameras require a one-time configuration setup that must be performed with the camera attached to the computer via USB. For Windows the setup is performed using Sony's PlayMemories Home application. For OSX the setup is done using Sony's Wireless Auto Import application. Sony doesn't provide a Linux application but if you can get access to a Windows or OSX machine you can perform the one-time setup on that system and then use Airnef under Linux thereafter, even on a system other than the one in which you authenticated via the one-time setup using Sony's software.

Here are the one-time setup instructions:

### Enable Sony Wireless transfers (OSX via Sony's Wireless Auto Import Application)

1. Install Sony's Wireless Auto Import application and launch it from your Applications folder.
1. Go to the USB Connection option in your camera's setup menu and set it to MTP, then connect the camera to a USB port on your computer.
1. Launch the Wireless Auto Import application and press the 'Set' button on the Main Window.
1. When complete you should see a dialog stating that your computer has been set as the Wireless Import Device. With Sony's application now installed and the camera activated your Mac will automatically transfers images from your camera using Sony's Wireless Auto Import application whenever your camera connects to your networking using the Send to Computer option. Sony's Auto Import application is a bit slow and doesn't let you select which files to transfer, which is why Airnef might be a better transfer solution for you. To use Airnef on this system you'll have to drag the Sony Wireless Auto Import application from the Application Folder into the OSX trash can, otherwise Sony's application will intercept the camera before Airnef has a chance to communicate with it.

### Enable Sony Wireless transfers (Windows via PlayMemories Home)

1. Install the PlayMemories Home Windows application.
1. Connect the camera to your computer via USB.
1. Launch the PlayMemories Home application. You may get a dialog asking you to temporarily switch the USB operation mode. Click 'Yes' if you get this prompt.
1. You may get a dialog asking you to see options for cameras. Click 'No' if you get this prompt.
1. Near the top-left of the PlayMemories window you should see your attached camera listed. Click the camera to bring up the camera settings options.
1. Click 'Wi-Fi Import Settings' in the settings page.
1. Click 'Custom' in the Wi-Fi Import Settings dialog.
1. Click 'Set' in the dialog whose text reads This Computer must be set as the automatic Wi-Fi import destination for the camera.
1. Click 'Next' to accept the Windows Firewall changes.
1. You should see a dialog indicating that settings change completed.
1. Your camera is now configured to allow wireless desktop transfers. By default your computer will automatically mount your camera whenever you use its Send to Computer feature, which utilizes Microsoft's built-in MTP-IP driver to treat the camera as a storage device, allowing you to drag and drop files from the camera to your local folders. This feature is very slow and produces intermittent errors, which is why Airnef might be a better transfer solution for you. You'll need to disable auto-mounting of the camera via another one-time process (instructions below) - uninstalling PlayMemories Home will not disable the auto-mounting feature. Until you have disabled auto-mounting Airnef will be unable to communicate with the camera because the auto-mounting driver will intercept the camera when it becomes available over WiFi, making it unavailable for other wireless clients like Airnef.

### Disabling Auto-Mounting of Sony camera on Windows

1. To disable auto-mounting you must allow your system to mount the camera once so that it shows up in the Device Manager of the Windows Control Panel, where it can then be disabled for all future mount attempts. For the camera to show up on your system its wireless settings must be configured, which is also required to use Airnef. See [Sony Wireless Setup](#sony-wireless-setup) below.
1. With the camera disconnected from USB, go to your camera's wireless menu and click Send to Computer. After the camera establishes its connection to the router you should see a screen indicating that it's attempting to connect to your computer, listing the name of the machine you configured in PlayMemories Home and the SSID of your wireless router.
1. Wait for your computer to discover the presence of your camera over WiFi. This might take up to a minute. When discovered your computer will either display an auto-play dialog asking what action to take with the camera, or failing that, an icon representing the camera within your windows filesystem. If neither of these happens and your computer fails to discover the camera then your done with this process (ie, for whatever reason the auto-mounting isn't working and since the goal is to disable auto-mounting there's nothing more for you to do).
1. Run the Windows Control Panel's Device Manager. For example in Windows 7 you can do this by clicking the Start Menu and typing "Device Manager" and clicking the search result associated with Device Manager.
1. In Device manager look for the icon in associated with the camera. On my Windows 7 system it shows up under the portable devices category.
1. Right-click on the camera and click 'Disable' from the popup menu. The icon representing the camera within your windows filesystem should now disappear - and should not reappear in the future when you perform a Send to Computer operation from the camera. The camera's icon will still appear within the Device Manager whenever the camera is available, but with a greyed-out tag indicating that the device is disabled. If you ever want to re-enable the Microsoft MTP-IP driver, perform a Send to Computer on the camera so that the icon shows up in the Device Manager and then right-click on the camera and click 'Enable'.

### Sony Wireless Setup

Sony's Send to Computer functionality requires that you perform a one-time wireless setup on your camera. Unlike the 'Send to Smartphone' feature where the camera creates its own ad hoc wireless network that you connect to, the Send to Computer' feature requires that the camera connect to your existing wireless network/router. Here are the steps to perform this one-time wireless setup on your camera:

1. Go to your camera's wireless menu and click the Access Point Set option.
1. Select the network name of your home/work wireless network from the list of networks presented by the camera.
1. If your network is password-protected, click on the input line of the password field to bring up the password-entry screen and enter your network's password.
1. The next screen lets you select the IP address method (Auto or Manual) and the 'Priority Connection' setting. Set 'Priority Connection' to ON - this will allow the camera to automatically connect to this network whenever you perform Send to Computer operations from the camera. For IP address Airnef supports the 'Auto' method, where Airnef will search the network every time it runs and automatically detect the IP address of your Sony camera via the SSDP Discovery protocol. However, SSDP Discovery may not work on all systems so if Airnef is failing to discover your Sony camera then use the Manual IP address method instead - for example, if your router is configured at IP address 192.168.1.1 your manual settings might look like this, where the camera is configured for IP address 192.168.1.10 - be sure to select an IP address that's not within the range of IP addresses that your router's DHCP server will use. Set the default gateway to the IP address of your router. The subnet mask should usually be set to 255.255.255.0
1. The camera will now attempt to connect to your wireless network to confirm that your settings (including the wireless password) are correct. Once confirmed you should see a screen indicating that the network is registered.
1. When using Airnef, if you chose "Auto" as the IP address mechanism during the camera's wireless setup then enter "Auto" in the IP address field of Airnef, otherwise enter the static IP address you chose for the camera.

### Important note regarding Sony 'Send to Computer' and transfer sessions

Each use of the camera's Send to Computer function supports only a single wireless session with a client like Airnef. For Airnef a wireless session is defined as anytime you press the 'Start Download' or 'Preview File List for Criteria', including all files that Airnef downloads/lists as part of that session. When the wireless session to the camera is over Airnef will automatically send a command to the camera to take it out of the Send to Compute (and put the camera into sleep mode), provided the session terminates cleanly (ie, you don't press <ctrl-c> within the command window to abort the session early). If the session does not terminate cleanly/properly then the camera will stay in the Send to Computer mode after Airnef's session has ended - because this mode only supports a single wireless session any future connection attempt from Airnef will be unsuccessful. To resolve this you will have to manually cancel out of the the Send to Computer mode on the camera and then re-enter the mode again.

## Canon Cameras

Canon cameras support SSDP Discovery, which allows Airnef to automatically discover the IP address of your camera when you've set the camera's IP address to "Auto". Simply type "Auto" for the Camera IP address field in Airnef. However, SSDP Discovery may not work on all systems so if Airnef is failing to discover your camera then use the Manual IP address method instead. Canon supports both ad hoc and infrastructure modes - for ad hoc the camera creates its own wireless network that you connect your computer - for infrastructure the camera connects to your existing home/work wireless network. In ad hoc mode Canon cameras typically use a fixed IP address of 192.168.1.2. For infrastructure mode Canon lets you specify either 'Auto' or a static IP address of the camera. When using a static IP address make sure to select an address outside the range of DHCP addresses that your router is configured to supply. For example if the DHCP range of the router is 192.168.1.100 to 192.168.1.200 then select an IP address below 192.168.1.100 or above 192.168.1.200 (don't pick 192.168.1.1 because that is likely the address of your router). For this example you can use 192.168.1.20, with a subnet mask of 255.255.255.0 and a default gateway of 192.168.1.1 (gateway is the router's IP address).

After you create the wireless configuration on your Canon camera, the camera will usually wait for a connection from a wireless client (Airnef in this case) to complete the configuration, which then associates that specific client to the wireless configuration/set. If you have an existing wireless configuration that you've used with other non-Airnef clients then you'll have to recreate the setup to allow the camera to associate the configuration with Airnef.

## Optimizing Wireless Download Performance

If you are using a camera that connects to your existing wireless network in infrastructure mode rather than creating its own ad hoc wireless network then your wireless performance may reach only half its potential because two nodes on an infrastructure network can't communicate directly like they can on an ad hoc wireless network - this means that all data from the camera to your computer must make two trips, one from the camera to your wireless router and another from the router to your computer. This applies to all Sony cameras in 'Send to Computer' mode and Canon cameras where you've elected to use infrastructure mode instead of ad hoc. You can avoid this double-trip penalty by using a wired connection from your computer to the router - that way the data from the camera only has to take one trip over your wireless network.
