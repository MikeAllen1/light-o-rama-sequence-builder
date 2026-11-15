# Installing

Every download includes everything it needs (Python, the audio libraries and FFmpeg). Nothing else to install. Light-O-Rama itself runs on Windows; you can make shows on any computer and copy them to your show computer.

## Windows

1. Download **[LOR-Sequencer-Setup.exe](https://github.com/MikeAllen1/light-o-rama-sequence-builder/releases/latest/download/LOR-Sequencer-Setup.exe)**.
2. Double-click it. If Windows says "Windows protected your PC", click **More info**, then **Run anyway** (the installer is not code-signed yet).
3. Click through the installer (no administrator rights needed) and open **LOR Sequencer** from the Start menu.

The installer can add **Build a show with LOR Sequencer** to the right-click menu of your `.lorprev` files.

Can't run installers? Download the **[portable zip](https://github.com/MikeAllen1/light-o-rama-sequence-builder/releases/latest/download/LOR-Sequencer-Portable.zip)**, right-click it, choose **Extract All**, and double-click `LOR Sequencer.exe`.

## Mac

Apple silicon (M1 or newer), macOS 14 Sonoma or later.

1. Download **[LOR-Sequencer-macOS.zip](https://github.com/MikeAllen1/light-o-rama-sequence-builder/releases/latest/download/LOR-Sequencer-macOS.zip)** and double-click it.
2. Drag **LOR Sequencer** into Applications.
3. The first time, macOS says it cannot check the app (it is not notarized by Apple). Click **Done**, open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to "LOR Sequencer" and confirm. After that it opens normally.

Intel Mac? Run it from the source folder (see [For Developers](For-Developers)).

## Linux

64-bit Intel or AMD; Ubuntu 22.04, Debian 12, Fedora 36 or newer.

1. Download **[LOR-Sequencer-x86_64.AppImage](https://github.com/MikeAllen1/light-o-rama-sequence-builder/releases/latest/download/LOR-Sequencer-x86_64.AppImage)**.
2. Make it runnable: right-click → Properties → *Allow executing as a program*, or `chmod +x LOR-Sequencer-x86_64.AppImage`.
3. Double-click it. It opens in your web browser and stops by itself about 15 minutes after you close the page.

If nothing happens, install FUSE (`sudo apt install libfuse2`, or `libfuse2t64` on Ubuntu 24.04), or start it with `./LOR-Sequencer-x86_64.AppImage --appimage-extract-and-run`.

## Updating

The app tells you, in the bottom corner, when a newer version is out, and links to the right download. On Windows, run the new installer over the old one; on a Mac, replace the app in Applications; on Linux, replace the AppImage. Your settings, requirements and recent shows are kept.
