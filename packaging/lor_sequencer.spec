# PyInstaller recipe for the LOR Sequencer desktop app.
#
# Build from the repository root:
#   uv run --no-sync --with pyinstaller==6.22.3 --with pyinstaller-hooks-contrib==2026.9 \
#       --with pywebview==6.2.1 pyinstaller packaging/lor_sequencer.spec --noconfirm
#
# Set LOR_FFMPEG_DIR to a folder holding ffmpeg(.exe) and its LICENSE to bundle FFmpeg,
# so the installed app reads songs without anything else installed.
# The result is a folder app in dist/LOR Sequencer/ (one folder starts much faster
# than a single packed file). On Windows packaging/windows/installer.iss turns it into a
# setup.exe; on Linux packaging/linux/build_appimage.sh makes an AppImage; on macOS this
# also makes dist/LOR Sequencer.app.

import os
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
datas = collect_data_files("lor_sequence_builder", includes=["web/*", "rules/*.yaml"])
datas += collect_data_files("librosa")
hidden = collect_submodules("lor_sequence_builder") + collect_submodules("librosa")

# The program's own license and the notices of every library bundled with it.
notices = Path(workpath) / "THIRD-PARTY-NOTICES.txt"
notices.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, str(root / "scripts" / "third_party_notices.py"), str(notices)],
               check=True)
datas += [(str(notices), "."), (str(root / "LICENSE"), ".")]

ffmpeg_dir = os.environ.get("LOR_FFMPEG_DIR")
if ffmpeg_dir:
    for name in os.listdir(ffmpeg_dir):
        datas.append((str(Path(ffmpeg_dir) / name), "ffmpeg"))

windows = sys.platform.startswith("win")
macos = sys.platform == "darwin"
icon = root / "packaging" / "windows" / "lor-sequencer.ico"
mac_icon = root / "packaging" / "macos" / "lor-sequencer.icns"
version = {}
exec((root / "src" / "lor_sequence_builder" / "__init__.py").read_text(), version)

a = Analysis(
    [str(root / "packaging" / "launch.py")],
    pathex=[str(root / "src")],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LOR Sequencer",
    # Linux keeps a console: with no window of its own the app runs in the browser,
    # and its terminal says where and how to stop it.
    console=not (windows or macos),
    icon=str(icon) if windows and icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LOR Sequencer")
if macos:
    app = BUNDLE(
        coll,
        name="LOR Sequencer.app",
        icon=str(mac_icon) if mac_icon.exists() else None,
        bundle_identifier="io.github.mikeallen1.lorsequencer",
        version=version["__version__"],
        info_plist={
            "CFBundleDisplayName": "LOR Sequencer",
            "CFBundleShortVersionString": version["__version__"],
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
        },
    )
