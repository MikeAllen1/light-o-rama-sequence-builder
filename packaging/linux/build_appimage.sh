#!/bin/sh
# Make dist/LOR-Sequencer-<version>-x86_64.AppImage from the PyInstaller folder app.
#   packaging/linux/build_appimage.sh <version> <path to appimagetool>
# Run from the repository root after: pyinstaller packaging/lor_sequencer.spec
set -eu
version="$1"
appimagetool="$2"
here="$(cd "$(dirname "$0")" && pwd)"
appdir="dist/LOR-Sequencer.AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib"
cp -a "dist/LOR Sequencer" "$appdir/usr/lib/lor-sequencer"
cp LICENSE "$appdir/usr/lib/lor-sequencer/LICENSE.txt"
cp "$here/AppRun" "$appdir/AppRun"
chmod +x "$appdir/AppRun"
cp "$here/lor-sequencer.desktop" "$appdir/lor-sequencer.desktop"
cp "$here/lor-sequencer.png" "$appdir/lor-sequencer.png"
cp "$here/lor-sequencer.png" "$appdir/.DirIcon"
# The build machine has no FUSE; appimagetool can run unpacked.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 VERSION="$version" \
  "$appimagetool" --no-appstream "$appdir" "dist/LOR-Sequencer-$version-x86_64.AppImage"
ls -l "dist/LOR-Sequencer-$version-x86_64.AppImage"
