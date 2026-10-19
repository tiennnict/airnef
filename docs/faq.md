# FAQ - Frequently Asked Questions

> Docs: [README](../README.md) · [Installation](installation.md) · [Camera setup](camera-setup.md) · [User guide](user-guide.md) · [Renaming engine](renaming-engine.md) · [Command line](command-line-reference.md) · [FAQ](faq.md)

### Sometimes during extended transfer sessions airnefcmd reports a MTP_RESP_StoreNotAvailable error and exits. Why is that?

Cameras have a data-integrity mechanism that disables access to their SD/CF cards when the battery is low. This is done to prevent incomplete writes in case the battery charge runs out while the camera is writing to a card.

### My camera has a WiFi option but it wont let me enable it (it's greyed out)

The mostly likely cause is low battery charge - for example Nikon bodies wont let you enable WiFi when the battery is low. There also might be a configuration setting in the camera that is incompatible with WiFi operation. On Nikon bodies the camera wont let you use WiFi when the HDMI port is in use.

### I have a wired connection to my router and whenever I try to connect wirelessly to my camera Airnef reports "A device at 192.1681.1.1 responded but the connection was refused. This is likely because you are connected to a normal WiFi network instead"

The default IP address of most routers is 192.168.1.1, which unfortunately is also the default IP address of the wireless network created by Nikon cameras. Even though you have separate a wired connection to your router there can only be one device with a given IP address and so when you attempt to connect to your camera at 192.168.1.1 you'll be connecting to your router instead. Fortunately changing the IP address of your Nikon camera is easy - see [Nikon Cameras](camera-setup.md#nikon-cameras) in the camera setup guide.

### My wireless download performance is only half the 2 - 2.5 MB/s that Airnef is quoted to achieve. I'm getting around 1 MB/s for my downloads.

If your camera uses the wireless infrastructure mode then you'll need to use a wired connection to your router to achieve 2 MB/s. See [Optimizing Wireless Download Performance](camera-setup.md#optimizing-wireless-download-performance).

### Whenever airnef runs it changes my camera's clock to the wrong time.

Airnef synchronizes the camera's clock to your system's UTC time. The time that the camera displays is then localized to the time zone and DST setting (Daylight Savings Time for USA) that you configured in the camera. If the camera's time zone and/or DST is not matched to your system's time zone/DST then the time will appear incorrect. If you'd prefer for Airnef to not synchronize your camera's clock then add "--maxclockdeltabeforesync disablesync" (without the quotes) to the command line.
