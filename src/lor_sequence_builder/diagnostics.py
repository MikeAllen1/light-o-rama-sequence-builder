"""A log of what went wrong, and a diagnostics report people can paste when asking for help.

The workspace log (``logs/workspace.log`` in the user data folder, next to the
desktop app's ``desktop.log``) records refused requests and errors from the page,
so "I clicked it and nothing happened" leaves a trail. The report gathers the
version, the system, every ``doctor`` check, the last steps taken in the workspace
and the end of both logs. Paths under the user's home folder are shortened to
``~`` and the user name is removed, so the report can be shared as it is.
"""

from __future__ import annotations

import getpass
import os
import platform
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from lor_sequence_builder import __version__

MAX_LOG_BYTES = 512 * 1024
MAX_LINE = 2000
MAX_ENTRIES_PER_RUN = 500
_lock = threading.Lock()
_written = 0


def log_folder() -> Path:
    from lor_sequence_builder.vocal_separation import model_folder

    return model_folder().parent / "logs"


def scrub(text: str) -> str:
    """Shorten the home folder to ~ and drop the user name."""
    home = str(Path.home())
    for form in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if len(form) > 3:
            text = text.replace(form, "~")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name to hide
        user = ""
    if len(user) >= 3:
        text = text.replace(user, "<user>")
    return text


def write_log(source: str, message: str, folder: Path | None = None) -> None:
    """Append one line; keeps the file small and never raises."""
    global _written
    line = " ".join(scrub(message).split())[:MAX_LINE]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    target = (folder or log_folder()) / "workspace.log"
    with _lock:
        if _written >= MAX_ENTRIES_PER_RUN:
            return
        _written += 1
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size > MAX_LOG_BYTES:
                target.replace(target.with_suffix(".log.1"))
            with target.open("a", encoding="utf-8") as stream:
                stream.write(f"{stamp} [{source[:20]}] {line}\n")
        except OSError:
            pass


def _tail(path: Path, lines: int) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


def report(browser: str = "", steps: list[str] | None = None,
           folder: Path | None = None) -> str:
    """Plain text to paste into a message or an issue."""
    from lor_sequence_builder.doctor import run_checks

    logs = folder or log_folder()
    out = [
        f"LOR Sequencer {__version__}",
        f"Made: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"System: {platform.platform()} ({platform.machine()})",
        f"Python: {platform.python_version()}"
        + (" (desktop app)" if getattr(sys, "frozen", False) else " (from source)"),
        f"Window: {browser[:300] or 'unknown'}",
        f"Update checks: {'off' if os.environ.get('LOR_NO_UPDATE_CHECK') else 'on'}",
        "Home folder paths are shortened to ~. Error lines can name the files you",
        "chose; read it over before sharing.",
        "",
        "Checks:",
    ]
    for check in run_checks():
        mark = "ok  " if check.ok else ("FAIL" if check.required else "--  ")
        out.append(f"  {mark} {check.name}: {check.detail}")
    out += ["", "Last steps in the workspace:"]
    out += [f"  {step[:200]}" for step in (steps or [])[-40:]] or ["  (none)"]
    for name in ("workspace.log", "desktop.log"):
        out += ["", f"End of {name}:"]
        out += [f"  {line}" for line in _tail(logs / name, 80)] or ["  (empty)"]
    return scrub("\n".join(out)) + "\n"
