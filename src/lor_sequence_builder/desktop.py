"""The LOR Sequencer desktop app: the browser workspace in its own window.

The installed app (built with PyInstaller, see ``packaging/``) starts here. It:

1. puts the FFmpeg bundled with the app on the search path, so songs can be read
   without installing anything else;
2. starts the local workspace server on a free loopback port in the background;
3. opens the workspace in a native window (WebView2 on Windows, through
   pywebview). If no native window can be made, it opens the default browser
   instead and keeps running until closed;
4. stops the server and removes temporary show files when the window closes.

``--self-test RESULT.json`` checks an installed copy without opening a window:
the server answers, the workspace files are served, every required ``doctor``
check passes, and a demo show is generated. The result is written as JSON (the
windowed app has no console) and the exit code is 0 only when all pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from collections.abc import Sequence
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

APP_NAME = "LOR Sequencer"


def _bundle_root() -> Path | None:
    """The unpacked app folder when running as a built desktop app."""
    root = getattr(sys, "_MEIPASS", None)
    return Path(root) if root else None


def use_bundled_ffmpeg() -> Path | None:
    """Put the app's own FFmpeg first on PATH; return its folder when there is one."""
    root = _bundle_root()
    folder = root / "ffmpeg" if root else None
    if folder is not None and (folder / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")).is_file():
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
        return folder
    return None


def _ensure_streams() -> None:
    """A windowed app has no console: send its output to a log file instead of nowhere,
    so writing a log line can never stop the app."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from lor_sequence_builder.vocal_separation import model_folder

    folder = model_folder().parent / "logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = open(folder / "desktop.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def start_server(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    from lor_sequence_builder.ui_server import SequencerRequestHandler

    server = ThreadingHTTPServer(("127.0.0.1", port), SequencerRequestHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="workspace-server", daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def stop_server(server: ThreadingHTTPServer) -> None:
    from lor_sequence_builder.ui_server import SHOWS

    server.shutdown()
    server.server_close()
    SHOWS.close()


def self_test(result_path: Path) -> int:
    """Check this copy works end to end, without a window; write the result as JSON."""
    from lor_sequence_builder.demo import build_demo
    from lor_sequence_builder.doctor import run_checks

    result: dict[str, Any] = {"app": APP_NAME, "ok": False, "steps": []}

    def step(name: str, ok: bool, detail: str = "") -> None:
        result["steps"].append({"name": name, "ok": ok, "detail": detail})

    server = None
    try:
        bundled = use_bundled_ffmpeg()
        step("Bundled FFmpeg", bundled is not None or _bundle_root() is None,
             str(bundled) if bundled else "not bundled (running from source)")
        server, url = start_server()
        with urlopen(url, timeout=10) as page:
            html = page.read().decode("utf-8")
        with urlopen(url + "app.js", timeout=10) as script:
            script_size = len(script.read())
        step("Workspace served", "New show" in html and script_size > 10_000, url)
        failed = [c for c in run_checks() if c.required and not c.ok]
        step("Doctor", not failed, "; ".join(f"{c.name}: {c.detail}" for c in failed))
        with tempfile.TemporaryDirectory(prefix="lor-self-test-") as folder:
            started = time.monotonic()
            show = build_demo(Path(folder) / "demo")
            step("Demo show", show.report.ok and show.sequence_path.stat().st_size > 1000,
                 f"{time.monotonic() - started:.1f} s")
        result["ok"] = all(s["ok"] for s in result["steps"])
    except Exception as exc:  # noqa: BLE001 - every failure must reach the result file
        step("Unexpected error", False, "".join(traceback.format_exception(exc))[-2000:])
    finally:
        if server is not None:
            stop_server(server)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def _open_window(url: str) -> bool:
    """Show the workspace in a native window; False when that is not possible here."""
    try:
        import webview
    except ImportError:
        return False
    webview.settings["ALLOW_DOWNLOADS"] = True
    try:
        webview.create_window(APP_NAME, url, width=1480, height=940, min_size=(1000, 680),
                              text_select=True)
        webview.start(private_mode=False)
    except Exception:  # noqa: BLE001 - fall back to the browser on any window failure
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lor-sequencer", description=f"{APP_NAME} desktop app")
    parser.add_argument("--self-test", metavar="RESULT_JSON",
                        help="check this copy without opening a window; write the result here")
    parser.add_argument("--browser", action="store_true",
                        help="open the workspace in the default browser instead of a window")
    _ensure_streams()
    options = parser.parse_args(argv)
    # The audio libraries probe the CPU with shell tools a packaged app may lack.
    os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
    if options.self_test:
        return self_test(Path(options.self_test))
    use_bundled_ffmpeg()
    server, url = start_server()
    try:
        if options.browser or not _open_window(url):
            webbrowser.open(url)
            print(f"{APP_NAME} is running at {url}. Close this window to stop it.")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
    finally:
        stop_server(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
