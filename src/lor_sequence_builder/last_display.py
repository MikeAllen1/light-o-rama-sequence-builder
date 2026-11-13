"""The display and style used last, kept on this computer for the next New show.

New show remembers the preview (or S4 sequence) it was last given and the style last
chosen, so a returning user picks a song and generates. Requirements are already
remembered per display. Nothing leaves this computer; choosing another display
replaces what is kept.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

# Larger than any preview or S4 sequence New show accepts.
MAX_BYTES = 60 * 1024 * 1024
_lock = threading.Lock()
_DISPLAY = "display.bin"
_ABOUT = "about.json"


def last_folder() -> Path:
    from lor_sequence_builder.vocal_separation import model_folder

    return model_folder().parent / "last-display"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".incoming-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _about(folder: Path) -> dict[str, Any]:
    try:
        about = json.loads((folder / _ABOUT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return about if isinstance(about, dict) else {}


def remember_display(payload: bytes, file_name: str, display_name: str,
                     folder: Path | None = None) -> None:
    """Keep the display just opened (replacing the one kept before)."""
    root = folder or last_folder()
    if len(payload) > MAX_BYTES:
        return
    with _lock:
        style = _about(root).get("style")
        _write(root / _DISPLAY, payload)
        about = {"file_name": Path(file_name).name[:200], "display": display_name[:200]}
        if isinstance(style, str):
            about["style"] = style
        _write(root / _ABOUT, json.dumps(about).encode("utf-8"))


def remember_style(style: str, folder: Path | None = None) -> None:
    """Keep the style last chosen."""
    root = folder or last_folder()
    if not isinstance(style, str) or not style or len(style) > 100:
        return
    with _lock:
        about = _about(root)
        about["style"] = style
        _write(root / _ABOUT, json.dumps(about).encode("utf-8"))


def describe(folder: Path | None = None) -> dict[str, Any]:
    """What is kept: the display's name and file name and the style, or nothing."""
    root = folder or last_folder()
    about = _about(root)
    out: dict[str, Any] = {}
    if (root / _DISPLAY).is_file() and isinstance(about.get("file_name"), str):
        out["file_name"] = about["file_name"]
        out["display"] = about.get("display") or about["file_name"]
    if isinstance(about.get("style"), str):
        out["style"] = about["style"]
    return out


def load_display(folder: Path | None = None) -> tuple[bytes, str] | None:
    """The kept display's bytes and file name, or None."""
    root = folder or last_folder()
    about = _about(root)
    name = about.get("file_name")
    try:
        data = (root / _DISPLAY).read_bytes()
    except OSError:
        return None
    if not isinstance(name, str) or not data or len(data) > MAX_BYTES:
        return None
    return data, name


def forget(folder: Path | None = None) -> None:
    """Forget the kept display and style."""
    root = folder or last_folder()
    with _lock:
        for name in (_DISPLAY, _ABOUT):
            (root / name).unlink(missing_ok=True)
