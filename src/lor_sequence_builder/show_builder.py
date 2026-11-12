"""Build a new show from the browser: preview, song, requirements, then generate.

The browser workspace sends the files the user picks; this module keeps them in
a private temporary folder for the session and runs the same steps as the
``generate`` command:

1. ``start``: read the preview and report what the program sees in the display
   (each prop's kind, what it cannot sequence and why).
2. ``add_audio``: analyze the song.
3. ``set_requirements``: optional display requirements, typed in plain English
   (when a translator is configured) or chosen in a form. They are remembered
   per display in the user's data folder, as the command line does next to the
   preview.
4. ``generate``: plan the show, check every rule, write the sequence, and return
   it with the plan picture and the rules report.

Sessions live in memory and in temporary folders that are deleted when the
session expires or the server stops. Nothing is sent anywhere except, when the
user asks for it, requirement text to the configured translator.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lor_sequence_builder import recent_shows
from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.lms import LmsError, display_from_lms, parse_lms, preview_bytes
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.planner import LEVEL_NAMES, display_has_mouths
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.requirements_intake import (
    translator_from_environment,
    validate_draft,
)
from lor_sequence_builder.rules import (
    Requirement,
    RuleProfileError,
    describe_requirement,
    display_from_preview,
    load_rule_set,
    requirements_profile_text,
)
from lor_sequence_builder.rules.engine import Display
from lor_sequence_builder.rules.profile import requirement_mapping
from lor_sequence_builder.sequence_writer import RulesFailedError
from lor_sequence_builder.style import DEFAULT_STYLE, STYLES
from lor_sequence_builder.vocal_separation import (
    model_folder,
    separate_vocals,
    separation_available,
)

MAX_SESSIONS = 4
SESSION_SECONDS = 12 * 60 * 60
MAX_REQUIREMENTS = 50
MAX_BATCH_SONGS = 40
MAX_BATCH_ARCHIVE_BYTES = 100 * 1024 * 1024


class ShowBuildError(ValueError):
    """Raised when a step of building a show cannot be done; the message is for the user."""


def _sequence_suffix(display_path: Path) -> str:
    """S4 displays (.lms) make S4 sequences; S5/S6 previews make .loredit sequences."""
    return ".lms" if display_path.suffix.lower() == ".lms" else ".loredit"


@dataclass
class _Session:
    token: str
    folder: tempfile.TemporaryDirectory[str]
    preview_path: Path
    display: Display
    display_key: str
    display_name: str
    created: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    analysis_path: Path | None = None
    audio_path: Path | None = None
    audio_name: str = ""
    audio_revision: int = 0
    requirements_revision: int = 0
    generated_dir: Path | None = None
    requirements: tuple[Requirement, ...] = ()
    batch: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def path(self) -> Path:
        return Path(self.folder.name)


_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                     *(f"LPT{n}" for n in range(1, 10))}


def file_stem(name: str, fallback: str = "song") -> str:
    """A song's name made safe to save on Windows: no folder parts, none of
    <>:"/\\|?* or control characters, no trailing dots or spaces, not a reserved
    device name, at most 120 characters."""
    stem = Path(name.replace("\\", "/")).name
    stem = Path(stem).stem if Path(stem).suffix else stem
    cleaned = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in stem)
    cleaned = cleaned.strip(" .")[:120].strip(" .")
    if not cleaned or cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        cleaned = (cleaned + " " if cleaned else "") + fallback
    return cleaned


def _safe_name(name: str) -> str:
    """A file name made from a display name: letters, digits, spaces and a few marks."""
    cleaned = "".join(ch if ch.isalnum() or ch in " -_()." else "_" for ch in name).strip(" .")
    return cleaned[:80] or "Display test"


def requirements_folder() -> Path:
    """Where requirements are remembered per display (next to the model cache)."""
    return model_folder().parent / "requirements"


def _display_key(preview: Any, payload: bytes) -> str:
    """A display keeps its key when the preview is saved again: S6 keeps its id."""
    identity = preview.get("id") or ""
    if identity.strip():
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return hashlib.sha256(payload).hexdigest()[:20]


_ROLE_NAMES = {
    "arch": ("arch", "arches"), "mini_tree": ("mini tree", "mini trees"),
    "mega_tree": ("mega tree", "mega trees"), "snowflake": ("snowflake", "snowflakes"),
    "star": ("star", "stars"), "outline": ("outline", "outlines"),
    "icicles": ("icicle line", "icicle lines"), "singing_face": ("singing face", "singing faces"),
    "decor": ("decoration", "decorations"), "unknown": ("other prop", "other props"),
}


def _kind_label(role: str, count: int) -> str:
    singular, plural = _ROLE_NAMES.get(role, (role, role))
    return singular if count == 1 else plural


class ShowSessions:
    """Bounded, expiring sessions for building shows."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.monotonic()
        for token, session in list(self._sessions.items()):
            if now - session.last_used > SESSION_SECONDS:
                self._drop(token)
        while len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.last_used)
            self._drop(oldest.token)

    def _drop(self, token: str) -> None:
        session = self._sessions.get(token)
        if session is not None:
            # Serialize cleanup with every operation that can read/write the folder.
            with session.lock:
                self._sessions.pop(token, None)
                session.folder.cleanup()

    def close(self) -> None:
        with self._lock:
            for token in list(self._sessions):
                self._drop(token)

    def get(self, token: str) -> _Session:
        with self._lock:
            session = self._sessions.get(token)
            if session is not None and time.monotonic() - session.last_used > SESSION_SECONDS:
                self._drop(token)
                session = None
            if session is None:
                raise ShowBuildError("This New show was put away after a long break. Choose your "
                                     "preview again to carry on; saved requirements come back.")
            session.last_used = time.monotonic()
            return session

    @contextmanager
    def locked(self, token: str) -> Iterator[_Session]:
        """Acquire a session lease before releasing the manager lock.

        This closes the lookup-to-lock race: eviction cannot remove the folder
        after a request looks up its session but before it begins using it.
        """
        with self._lock:
            session = self._sessions.get(token)
            if session is not None and time.monotonic() - session.last_used > SESSION_SECONDS:
                self._drop(token)
                session = None
            if session is None:
                raise ShowBuildError("This New show was put away after a long break. Choose your "
                                     "preview again to carry on; saved requirements come back.")
            session.lock.acquire()
            session.last_used = time.monotonic()
        try:
            yield session
        finally:
            session.lock.release()

    # -- 1. preview

    def start(self, payload: bytes, file_name: str) -> dict[str, Any]:
        folder = tempfile.TemporaryDirectory(prefix="lor-new-show-")
        try:
            s4 = Path(file_name).suffix.lower() == ".lms"
            preview_path = Path(folder.name) / "display.lorprev"
            if s4:
                # An S4 sequence is the display: its channels become the props, and
                # the show is written back as an S4 sequence with the same channels.
                try:
                    lms_display = display_from_lms(parse_lms(payload, Path(file_name).name),
                                                   Path(file_name).stem or "S4 display")
                except LmsError as exc:
                    raise ShowBuildError(f"{exc}. Choose one of your S4 sequences (.lms) or "
                                         "an S5/S6 preview (.lorprev).") from exc
                preview_path.write_bytes(preview_bytes(lms_display))
            else:
                preview_path.write_bytes(payload)
            try:
                preview = preview_element(read_lorprev(preview_path))
                display = display_from_preview(preview)
            except (ValueError, OSError) as exc:
                raise ShowBuildError(f"This preview could not be read ({exc}). Choose the "
                                     ".lorprev file exported from S6's Preview Editor.") from exc
            if s4:
                preview_path = Path(folder.name) / "display.lms"
                preview_path.write_bytes(payload)
            name = preview.get("Name") or Path(file_name).stem or "Display"
            session = _Session(secrets.token_urlsafe(18), folder, preview_path, display,
                               _display_key(preview, payload), name)
            remembered = self._remembered(session)
            if remembered is not None:
                try:
                    session.requirements = load_rule_set((remembered,)).requirements
                except RuleProfileError:
                    session.requirements = ()
        except BaseException:
            folder.cleanup()
            raise
        with self._lock:
            self._expire()
            self._sessions[session.token] = session
        return {"token": session.token, **self._summary(session)}

    def _remembered(self, session: _Session) -> Path | None:
        path = requirements_folder() / f"{session.display_key}.requirements.yaml"
        return path if path.is_file() else None

    def _summary(self, session: _Session) -> dict[str, Any]:
        display = session.display
        props = sorted(display.props.values(), key=lambda p: (p.role, p.name))
        kinds: dict[str, int] = {}
        for prop in props:
            if prop.sequenceable:
                kinds[prop.role] = kinds.get(prop.role, 0) + 1
        rules = load_rule_set()
        return {
            "display": session.display_name,
            "props": [{"name": p.name, "role": p.role, "sequenceable": p.sequenceable,
                       "reason": p.layout_problem or (
                           f"driven by {display.props[p.linked_to].name}"
                           if p.linked_to in display.props else None)}
                      for p in props],
            "kinds": [{"role": role, "label": _kind_label(role, count), "count": count,
                       "plural": _kind_label(role, 2)}
                      for role, count in sorted(kinds.items())],
            "groups": sorted(display.groups),
            "faces": display_has_mouths(display, rules),
            "can_separate_vocals": separation_available(),
            "can_translate": translator_from_environment() is not None,
            "styles": [STYLES[key].to_dict() for key in STYLES],
            "default_style": DEFAULT_STYLE,
            "requirements": [describe_requirement(r) for r in session.requirements],
            "raw_requirements": [_raw(r) for r in session.requirements],
        }

    # -- 2. song

    def add_audio(self, token: str, payload: bytes, suffix: str, demuxer: str,
                  file_name: str, beats_per_bar: int,
                  request_id: int | None = None) -> dict[str, Any]:
        audio_name = Path(file_name).name or f"song{suffix}"
        if len(audio_name) > 200:
            raise ShowBuildError("Song file name must be 200 characters or fewer.")
        with self.locked(token) as session:
            revision = session.audio_revision + 1 if request_id is None else request_id
            if revision <= session.audio_revision:
                return {"stale": True}
            session.audio_revision = revision
            staging = session.path / ("audio-" + secrets.token_hex(6))
            staging.mkdir()
            audio = staging / f"song{suffix}"
            analysis = staging / "song.analysis.json"
            try:
                audio.write_bytes(payload)
                report = analyze_audio(
                    audio, analysis, staging / "song.analysis.svg",
                    beats_per_bar=beats_per_bar, input_demuxer=demuxer,
                )
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            old_audio = session.audio_path
            session.audio_path = audio
            session.analysis_path = analysis
            session.audio_name = audio_name
            if old_audio is not None and old_audio.parent != session.path:
                shutil.rmtree(old_audio.parent, ignore_errors=True)
        return report

    # -- 3. requirements

    def set_requirements(
        self, token: str, body: dict[str, Any], request_id: int | None = None
    ) -> dict[str, Any]:
        with self.locked(token) as session:
            revision = session.requirements_revision + 1 if request_id is None else request_id
            if revision <= session.requirements_revision:
                return {"stale": True}
            raw = body.get("requirements", [])
            text = body.get("text")
            if not isinstance(raw, list) or len(raw) > MAX_REQUIREMENTS or not all(
                    isinstance(item, dict) for item in raw):
                raise ShowBuildError("Requirements must be a list of up to 50 items")
            problems: list[str] = []
            if isinstance(text, str) and text.strip():
                if len(text) > 4000:
                    raise ShowBuildError("Plain-English requirements must be 4,000 characters or fewer")
                translator = translator_from_environment()
                if translator is None:
                    raise ShowBuildError("Plain-English requirements need a translator (set "
                                         "ANTHROPIC_API_KEY before starting the workspace); "
                                         "use the form instead")
                translation = translator.translate(text.strip(), session.display)
                raw = [*raw, *translation.requirements]
                problems.extend(f"Not supported: {item}" for item in translation.not_supported)
            draft = validate_draft(raw, session.display)
            problems.extend(draft.problems)
            # Persist the proposed profile before publishing it to the live session.
            # If disk I/O fails, neither the in-memory requirements nor their revision
            # changes, so a failed request cannot affect the next generated show.
            self._remember(session, draft.requirements)
            session.requirements = draft.requirements
            session.requirements_revision = revision
            return {"requirements": [describe_requirement(r) for r in draft.requirements],
                    "raw": [_raw(r) for r in draft.requirements],
                    "problems": problems}

    def _remember(
        self, session: _Session, requirements: tuple[Requirement, ...] | None = None
    ) -> None:
        """Persist a proposed profile atomically without mutating the live session."""
        proposed = session.requirements if requirements is None else requirements
        folder = requirements_folder()
        path = folder / f"{session.display_key}.requirements.yaml"
        if not proposed:
            path.unlink(missing_ok=True)
            return
        folder.mkdir(parents=True, exist_ok=True)
        text = requirements_profile_text(proposed, f"Requirements for {session.display_name}")
        temporary = path.with_name(path.name + f".{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8", newline="\n")
            load_rule_set((temporary,))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    # -- 4. generate

    def display_test(self, token: str) -> dict[str, Any]:
        """A 10-second test for this display, as files to save and to watch."""
        from lor_sequence_builder.display_test import build_display_test

        with self.locked(token) as session:
            if session.preview_path.suffix.lower() == ".lms":
                raise ShowBuildError("The display test is made for S5/S6 displays. With an S4 "
                                     "sequence, build a show and play it in the S4 Sequencer.")
            folder = session.path / ("test-" + secrets.token_hex(6))
            name = f"{session.display_name} - display test"
            try:
                test = build_display_test(session.preview_path, folder, name=_safe_name(name))
            except (FileExistsError, OSError) as exc:
                raise ShowBuildError(f"The display test could not be written: {exc}") from exc
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in (test.sequence_path, test.sound_path, test.notes_path):
                    archive.write(path, path.name)
            return {
                "file_name": test.sequence_path.name,
                "zip_name": test.sequence_path.stem + ".zip",
                "sound_name": test.sound_path.name,
                "sequence": test.sequence_path.read_text(encoding="utf-8"),
                "notes": test.notes_path.read_text(encoding="utf-8"),
                "schedule": [{"start": a, "end": b, "what": what} for a, b, what in test.schedule],
                "zip": base64.b64encode(bundle.getvalue()).decode("ascii"),
                "sound": base64.b64encode(test.sound_path.read_bytes()).decode("ascii"),
            }

    def generate(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        music = body.get("music_filename")
        sing_value = body.get("sing", False)
        if not isinstance(sing_value, bool):
            raise ShowBuildError("'sing' must be a JSON boolean")
        sing = sing_value
        style = body.get("style") or None
        if style is not None and (not isinstance(style, str) or style not in STYLES):
            raise ShowBuildError("Unknown style; choose one of: " + ", ".join(STYLES))
        with self.locked(token) as session:
            if session.analysis_path is None or session.audio_path is None:
                raise ShowBuildError("Add the song before generating")
            if music is None or (isinstance(music, str) and not music.strip()):
                music = session.audio_name
            elif not isinstance(music, str):
                raise ShowBuildError("Music file name must be text.")
            elif len(music) > 260:
                raise ShowBuildError("Music file name must be 260 characters or fewer.")
            run = session.path / ("run-" + secrets.token_hex(6))
            run.mkdir()
            try:
                profile = run / "requirements.yaml"
                profiles: tuple[Path, ...] = ()
                if session.requirements:
                    profile.write_text(requirements_profile_text(session.requirements, "Requirements"),
                                       encoding="utf-8", newline="\n")
                    profiles = (profile,)
                rule_set = load_rule_set(profiles)
                vocals: Path | None = None
                note = None
                if display_has_mouths(session.display, rule_set):
                    if sing and separation_available():
                        vocals = separate_vocals(session.audio_path, run / "vocals.wav")
                    elif sing:
                        note = ("Singing faces need the vocals add-on (uv sync --extra vocals); "
                                "the mouths stay still in this show.")
                stem = file_stem(session.audio_name, "show")
                output = run / f"{stem} (generated){_sequence_suffix(session.preview_path)}"
                try:
                    show = generate_show(session.preview_path, output, rule_set,
                                         analysis_path=session.analysis_path,
                                         music_filename=music.strip(), vocals_path=vocals,
                                         separate=False, style=style)
                except RulesFailedError as failed:
                    if session.generated_dir is not None:
                        shutil.rmtree(session.generated_dir, ignore_errors=True)
                    session.generated_dir = run
                    picture = run / f"{stem} (generated).plan.svg"
                    return {
                        "rules_ok": False, "file_name": output.name, "sequence": None,
                        "picture": picture.read_text(encoding="utf-8") if picture.is_file() else "",
                        "report": failed.report.format_text(), "sections": [], "used": [],
                        "skipped": [], "notes": [], "moments": [],
                        "requirements": [describe_requirement(r) for r in session.requirements],
                    }
                if session.generated_dir is not None:
                    shutil.rmtree(session.generated_dir, ignore_errors=True)
                session.generated_dir = run
                plan = show.plan
                recent_id = _keep_recent(show.sequence_path, show.summary_path,
                                         show.picture_path, output.name, session.display_name,
                                         music, style)
                return {
                    "recent_id": recent_id,
                    "file_name": output.name,
                    "sequence": show.sequence_path.read_text(encoding="utf-8"),
                    "picture": show.picture_path.read_text(encoding="utf-8"),
                    "summary": show.summary_path.read_text(encoding="utf-8"),
                    "report": show.report.format_text(),
                    "rules_ok": show.report.ok,
                    "sections": [{"label": s.label, "level": LEVEL_NAMES[s.level],
                                  "start": s.start_centisecond, "end": s.end_centisecond}
                                 for s in plan.sections],
                    "used": list(plan.used_props),
                    "skipped": [{"name": s.name, "reason": s.reason}
                                for s in plan.skipped_props],
                    "notes": [*plan.notes, *([note] if note else []),
                              *([show.vocals_note] if show.vocals_note and not note else [])],
                    "moments": [{"kind": k, "centisecond": t} for k, t in plan.moments],
                    "requirements": [describe_requirement(r) for r in session.requirements],
                }
            except BaseException:
                if session.generated_dir != run:
                    shutil.rmtree(run, ignore_errors=True)
                raise

    # -- several songs at once

    def batch_song(self, token: str, payload: bytes, suffix: str, demuxer: str,
                   file_name: str, beats_per_bar: int, style: str | None) -> dict[str, Any]:
        """Analyze one song and build its show with the session's display, requirements
        and the chosen style. The show is kept for :meth:`batch_zip`; the session's own
        song is untouched. Faces do not sing in batch shows (no vocal splitting)."""
        if style is not None and style not in STYLES:
            raise ShowBuildError("Unknown style; choose one of: " + ", ".join(STYLES))
        with self.locked(token) as session:
            if len(session.batch) >= MAX_BATCH_SONGS:
                raise ShowBuildError(f"A batch holds up to {MAX_BATCH_SONGS} songs; save "
                                     "these and start another")
            name = Path(file_name).name or f"song{suffix}"
            if len(name) > 200:
                raise ShowBuildError("Song file name must be 200 characters or fewer.")
            if any(
                isinstance(entry.get("file_name"), str) and
                entry["file_name"].casefold() == name.casefold()
                for entry in session.batch
            ):
                raise ShowBuildError(
                    f"The playlist already contains a song named {name!r}. "
                    "Rename duplicate audio files before building."
                )
            stem = file_stem(name)
            taken = {entry["stem"] for entry in session.batch}
            unique, n = stem, 2
            while unique in taken:
                unique, n = f"{stem} ({n})", n + 1
            done = session.path / "batch"
            done.mkdir(exist_ok=True)
            work = session.path / ("batch-work-" + secrets.token_hex(6))
            work.mkdir()
            try:
                audio = work / f"song{suffix}"
                audio.write_bytes(payload)
                analysis = work / "song.analysis.json"
                report = analyze_audio(audio, analysis, work / "song.analysis.svg",
                                       beats_per_bar=beats_per_bar, input_demuxer=demuxer)
                profiles: tuple[Path, ...] = ()
                if session.requirements:
                    profile = work / "requirements.yaml"
                    profile.write_text(requirements_profile_text(session.requirements,
                                                                 "Requirements"),
                                       encoding="utf-8", newline="\n")
                    profiles = (profile,)
                output = work / f"{unique} (generated){_sequence_suffix(session.preview_path)}"
                entry: dict[str, Any] = {"stem": unique, "file_name": name,
                                         "duration": (report.get("audio") or {}).get("duration_seconds")}
                try:
                    show = generate_show(session.preview_path, output, load_rule_set(profiles),
                                         analysis_path=analysis, music_filename=name,
                                         vocals_path=None, separate=False, style=style)
                except RulesFailedError as failed:
                    entry.update(ok=False, problem=failed.report.format_text()[:2000])
                else:
                    existing_artifacts = [
                        path
                        for previous in session.batch if previous.get("ok")
                        for path in (
                            done / previous["show"],
                            done / f"{previous['stem']} (generated).report.html",
                        )
                    ]
                    existing_bytes = sum(path.stat().st_size for path in existing_artifacts)
                    candidate_bytes = (
                        show.sequence_path.stat().st_size + show.summary_path.stat().st_size
                    )
                    if existing_bytes + candidate_bytes > MAX_BATCH_ARCHIVE_BYTES:
                        raise ShowBuildError(
                            "Adding this show would exceed the 100 MiB playlist download limit. "
                            "Save the current playlist, then start another playlist for the remaining songs."
                        )
                    # Publish both artifacts without overwriting anything. If the
                    # report cannot be published after the sequence, remove the
                    # sequence link so the batch manifest and directory stay in sync.
                    published: list[Path] = []
                    try:
                        sequence_target = done / output.name
                        report_target = done / f"{unique} (generated).report.html"
                        os.link(show.sequence_path, sequence_target)
                        published.append(sequence_target)
                        os.link(show.summary_path, report_target)
                        published.append(report_target)
                    except OSError:
                        for target in published:
                            target.unlink(missing_ok=True)
                        raise
                    _keep_recent(show.sequence_path, show.summary_path, show.picture_path,
                                 output.name, session.display_name, name, style)
                    entry.update(ok=True, show=output.name,
                                 parts=len(show.plan.sections),
                                 props=len(show.plan.used_props))
                session.batch.append(entry)
                return {key: value for key, value in entry.items() if key != "stem"}
            finally:
                shutil.rmtree(work, ignore_errors=True)

    def batch_zip(self, token: str) -> dict[str, Any]:
        """Create a disk-backed ZIP of every successfully built show and report."""
        with self.locked(token) as session:
            done = session.path / "batch"
            shows = [entry for entry in session.batch if entry.get("ok")]
            if not shows:
                raise ShowBuildError("No batch shows have been built yet")
            artifacts = [
                path
                for entry in shows
                for path in (done / entry["show"],
                             done / f"{entry['stem']} (generated).report.html")
            ]
            total_bytes = sum(path.stat().st_size for path in artifacts)
            if total_bytes > MAX_BATCH_ARCHIVE_BYTES:
                raise ShowBuildError(
                    "This playlist's show files exceed the 100 MiB download limit. "
                    "Save the playlist in smaller batches."
                )

            archive_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="lor-batch-", suffix=".zip", delete=False
                ) as temporary:
                    archive_path = Path(temporary.name)
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in artifacts:
                        archive.write(path, path.name)
                    lines = ["Shows in this batch", ""]
                    for entry in session.batch:
                        lines.append(f"{entry['file_name']}: " + (
                            f"{entry['show']}" if entry.get("ok") else "not built (rules failed)"))
                    if _sequence_suffix(session.preview_path) == ".lms":
                        lines += ["", "Copy each song into your S4 audio folder with the same name,",
                                  "then open its .lms in the S4 Sequencer."]
                    else:
                        lines += ["", "Copy each song into S6's audio folder with the same name, then",
                                  "open its .loredit in the S6 Sequencer."]
                    archive.writestr("Batch - read me.txt", "\r\n".join(lines) + "\r\n")
                name = _safe_name(session.display_name) + " shows.zip"
                return {"zip_path": str(archive_path), "zip_name": name, "count": len(shows)}
            except BaseException:
                if archive_path is not None:
                    try:
                        archive_path.unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        from lor_sequence_builder.diagnostics import write_log

                        write_log("server", f"Could not remove incomplete batch archive: {cleanup_error}")
                raise

    def batch_clear(self, token: str) -> dict[str, Any]:
        with self.locked(token) as session:
            done = session.path / "batch"
            if done.exists():
                # Move the active batch out of the way atomically before deleting it.
                # A partial rmtree failure must never leave the live manifest pointing
                # at a half-deleted batch that the user can no longer download.
                retired = session.path / ("batch-reset-" + secrets.token_hex(6))
                os.replace(done, retired)
                session.batch.clear()
                try:
                    shutil.rmtree(retired)
                except OSError as cleanup_error:
                    # The reset succeeded; only orphan cleanup failed. The session's
                    # temporary folder will remove this retired directory on expiry.
                    from lor_sequence_builder.diagnostics import write_log

                    write_log("show", f"Could not remove retired batch directory: {cleanup_error}")
            else:
                session.batch.clear()
        return {"cleared": True}


def _keep_recent(sequence: Path, summary: Path, picture: Path, file_name: str, display: str,
                 song: str, style: str | None) -> str | None:
    """Keep a copy for Recent shows; a full disk only means it is not kept."""
    try:
        return recent_shows.keep(sequence, summary, picture, file_name=file_name,
                                 display=display, song=song, style=style, rules_ok=True)
    except OSError:
        return None


def _raw(requirement: Requirement) -> dict[str, Any]:
    """The requirement as the form edits it."""
    return dict(requirement_mapping(requirement))


def to_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")
