# PyInstaller recipe for the LOR Sequencer desktop app.
#
# Build from the repository root:
#   uv run --no-sync --with pyinstaller==6.22.3 --with pyinstaller-hooks-contrib==2026.9 \
#       --with pywebview==6.2.1 pyinstaller packaging/lor_sequencer.spec --noconfirm
#
# Set LOR_FFMPEG_DIR to a folder holding ffmpeg(.exe) and its LICENSE to bundle FFmpeg,
# so the installed app reads songs without anything else installed.
# The result is a folder app in dist/LOR Sequencer/ (one folder starts much faster
# than a single packed file); packaging/windows/installer.iss turns it into a setup.exe.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
datas = collect_data_files("lor_sequence_builder", includes=["web/*", "rules/*.yaml"])
datas += collect_data_files("librosa")
hidden = collect_submodules("lor_sequence_builder") + collect_submodules("librosa")

ffmpeg_dir = os.environ.get("LOR_FFMPEG_DIR")
if ffmpeg_dir:
    for name in os.listdir(ffmpeg_dir):
        datas.append((str(Path(ffmpeg_dir) / name), "ffmpeg"))

windows = sys.platform.startswith("win")
icon = root / "packaging" / "windows" / "lor-sequencer.ico"

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
    console=not windows,
    icon=str(icon) if windows and icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LOR Sequencer")
