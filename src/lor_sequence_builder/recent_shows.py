"""Shows made recently, kept on this computer so they can be opened or saved again.

Every show New show builds (one song or a playlist) is copied into the user data
folder (``shows`` next to the remembered requirements) with its report, plan picture
and a small description. The newest 30 are kept. Nothing leaves this computer, and
each one can be removed from the start page.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_KEPT = 30
_ID = re.compile(r"\d{8}-\d{6}-\d{6}-[0-9a-f]{4}")
_lock = threading.Lock()
_FILES = {"sequence": "show.loredit", "summary": "report.html", "picture": "plan.svg"}


class RecentShowError(ValueError):
    """A recent show that is not there (removed, or never kept)."""


def recent_folder() -> Path:
    from lor_sequence_builder.vocal_separation import model_folder

    return model_folder().parent / "shows"


def keep(sequence: Path, summary: Path | None, picture: Path | None, *, file_name: str,
         display: str, song: str, style: str | None, rules_ok: bool,
         folder: Path | None = None) -> str:
    """Copy a finished show in; returns its id. Older shows past MAX_KEPT are removed."""
    from lor_sequence_builder import __version__

    root = folder or recent_folder()
    show_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(2)
    with _lock:
        root.mkdir(parents=True, exist_ok=True)
        # The same show built again (Generate pressed twice) is not listed twice: the
        # one already kept just moves to the top.
        newest = _kept(root)[:1]
        if newest and newest[0].get("file_name") == file_name[:200] and \
                newest[0].get("version") == __version__ and \
                (root / newest[0]["id"] / _FILES["sequence"]).read_bytes() == \
                Path(sequence).read_bytes():
            return str(newest[0]["id"])
        staging = root / (".incoming-" + show_id)
        staging.mkdir()
        try:
            shutil.copyfile(sequence, staging / _FILES["sequence"])
            for kind, source in (("summary", summary), ("picture", picture)):
                if source is not None and source.is_file():
                    shutil.copyfile(source, staging / _FILES[kind])
            (staging / "show.json").write_text(json.dumps({
                "id": show_id, "file_name": file_name[:200], "display": display[:200],
                "song": song[:260], "style": style, "rules_ok": rules_ok,
                "version": __version__,
                "made": datetime.now().isoformat(timespec="seconds"),
            }, indent=2), encoding="utf-8")
            staging.rename(root / show_id)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        for old in _kept(root)[MAX_KEPT:]:
            shutil.rmtree(root / old["id"], ignore_errors=True)
    return show_id


def _style_name(key: Any) -> str | None:
    """'energetic' -> 'High energy'; a learned style by its own name."""
    if not isinstance(key, str) or not key:
        return None
    from lor_sequence_builder.style import get_style

    try:
        return get_style(key).name
    except ValueError:
        return key


def _kept(root: Path) -> list[dict[str, Any]]:
    found = []
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and _ID.fullmatch(p.name)]
    except OSError:
        return []
    for path in folders:
        try:
            meta = json.loads((path / "show.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and (path / _FILES["sequence"]).is_file():
            meta["id"] = path.name
            meta["has_report"] = (path / _FILES["summary"]).is_file()
            meta["has_picture"] = (path / _FILES["picture"]).is_file()
            meta["style_name"] = _style_name(meta.get("style"))
            found.append(meta)
    return sorted(found, key=lambda meta: meta["id"], reverse=True)


def listing(folder: Path | None = None) -> list[dict[str, Any]]:
    """Newest first."""
    return _kept(folder or recent_folder())


def _path(show_id: str, folder: Path | None) -> Path:
    """The kept show with exactly this id. The path comes from the folder's own listing,
    never from the id, so no id can point anywhere else."""
    if isinstance(show_id, str) and _ID.fullmatch(show_id):
        root = folder or recent_folder()
        try:
            for path in root.iterdir():
                if (path.name == show_id and path.is_dir() and not path.is_symlink()
                        and (path / _FILES["sequence"]).is_file()):
                    return path
        except OSError:
            pass
    raise RecentShowError("That recent show is not there any more")


def load(show_id: str, folder: Path | None = None) -> dict[str, Any]:
    path = _path(show_id, folder)
    meta = json.loads((path / "show.json").read_text(encoding="utf-8"))
    result: dict[str, Any] = {"id": show_id, "file_name": meta.get("file_name") or "show.loredit",
                              "song": meta.get("song") or ""}
    for kind, name in _FILES.items():
        target = path / name
        result[kind] = target.read_text(encoding="utf-8") if target.is_file() else None
    return result


def remove(show_id: str, folder: Path | None = None) -> None:
    path = _path(show_id, folder)
    with _lock:
        shutil.rmtree(path, ignore_errors=True)


def clear(folder: Path | None = None) -> int:
    root = folder or recent_folder()
    removed = 0
    with _lock:
        for meta in _kept(root):
            shutil.rmtree(root / meta["id"], ignore_errors=True)
            removed += 1
    return removed
