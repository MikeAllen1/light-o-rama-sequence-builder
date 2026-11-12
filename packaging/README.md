# Desktop app packaging

The Windows app is the browser workspace in its own window, with Python, the audio
libraries and FFmpeg inside, so nothing else needs to be installed.

| File | What it does |
| --- | --- |
| `launch.py` | The app's entry point; runs `lor_sequence_builder.desktop`. |
| `lor_sequencer.spec` | PyInstaller recipe: the program, its workspace files and rules, librosa's data, and FFmpeg from `LOR_FFMPEG_DIR`. Makes `dist/LOR Sequencer/`. |
| `windows/installer.iss` | Inno Setup script: a per-user installer (no administrator prompt) with a Start menu entry, an optional desktop shortcut and a normal uninstaller. |
| `windows/lor-sequencer.ico` | The icon, drawn by `make_icon.py`. |

## How it runs

`desktop.py` puts the bundled FFmpeg first on the search path and starts the
workspace server on a free loopback port. It then opens the workspace in a
native window (WebView2, through pywebview), or in the default browser if no
window can be made. Closing the window stops the server and removes temporary
show files. A windowed app has no console, so its log goes to
`%LOCALAPPDATA%\lor-sequence-builder\logs\desktop.log`.

`"LOR Sequencer.exe" --self-test result.json` checks an installed copy without a
window: the workspace is served, every required `doctor` check passes, and a
demo show is generated. The result is written as JSON.

## Builds

`.github/workflows/desktop.yml` runs on every pull request and every push to
master:

1. Sync the locked environment with the `desktop` extra (pywebview, PyInstaller,
   pinned in `pyproject.toml` and `uv.lock`).
2. Download the pinned FFmpeg build and check its SHA-256.
3. Build with PyInstaller.
4. Run the app's self-test.
5. Build the installer with Inno Setup.
6. Zip the same app folder (with a short README.txt and the license) as the
   portable version, for PCs that block installers.
7. Keep both as artifacts for 30 days.

Publishing a release (or pushing a tag such as `v0.1.0`) attaches the installer and
the portable zip to it.

To build on a Windows PC:

```powershell
uv sync --locked --extra desktop
$env:LOR_FFMPEG_DIR = "C:\path\to\folder\with\ffmpeg.exe"
uv run --no-sync pyinstaller packaging\lor_sequencer.spec --noconfirm
& "dist\LOR Sequencer\LOR Sequencer.exe" --self-test result.json
iscc /DAppVersion=0.1.0 packaging\windows\installer.iss
```

From a source checkout, `uv run lor-sequencer` opens the same window (with the
`desktop` extra installed) or the browser.

## Releasing a new version

1. `uv run python scripts/prepare_release.py 0.2.0` sets the version in
   `pyproject.toml`, `uv.lock`, the package and the installer script, and drafts
   `docs/releases/v0.2.0.md` from the pull requests merged since the last version.
2. Edit the notes if you like, open a pull request with the changes, and merge it.
3. On GitHub: **Releases**, **Draft a new release**, tag `v0.2.0` on master, title
   `LOR Sequencer 0.2.0`, and **Publish**. Leave the description empty to use the
   drafted notes, or paste them.
4. The Desktop app workflow builds, self-tests and attaches the installer and the
   portable zip. Everyone's app announces the new version the next time it starts.

A test checks that every file carries the same version and that it has notes.
