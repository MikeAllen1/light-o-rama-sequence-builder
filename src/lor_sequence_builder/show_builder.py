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

import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.generate import generate_show
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
from lor_sequence_builder.vocal_separation import (
    model_folder,
    separate_vocals,
    separation_available,
)

MAX_SESSIONS = 4
SESSION_SECONDS = 2 * 60 * 60
MAX_REQUIREMENTS = 50


class ShowBuildError(ValueError):
    """Raised when a step of building a show cannot be done; the message is for the user."""


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
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def path(self) -> Path:
        return Path(self.folder.name)


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
                raise ShowBuildError("This show was not found or has expired; start again")
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
                raise ShowBuildError("This show was not found or has expired; start again")
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
            preview_path = Path(folder.name) / "display.lorprev"
            preview_path.write_bytes(payload)
            try:
                preview = preview_element(read_lorprev(preview_path))
                display = display_from_preview(preview)
            except (ValueError, OSError) as exc:
                raise ShowBuildError(f"Cannot read this preview: {exc}") from exc
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
            "requirements": [describe_requirement(r) for r in session.requirements],
        }

    # -- 2. song

    def add_audio(self, token: str, payload: bytes, suffix: str, demuxer: str,
                  file_name: str, beats_per_bar: int,
                  request_id: int | None = None) -> dict[str, Any]:
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
            session.audio_name = Path(file_name).name or audio.name
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
            session.requirements_revision = revision
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
            session.requirements = draft.requirements
            self._remember(session)
            return {"requirements": [describe_requirement(r) for r in draft.requirements],
                    "raw": [_raw(r) for r in draft.requirements],
                    "problems": problems}

    def _remember(self, session: _Session) -> None:
        folder = requirements_folder()
        path = folder / f"{session.display_key}.requirements.yaml"
        if not session.requirements:
            path.unlink(missing_ok=True)
            return
        folder.mkdir(parents=True, exist_ok=True)
        text = requirements_profile_text(session.requirements,
                                         f"Requirements for {session.display_name}")
        temporary = path.with_name(path.name + f".{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8", newline="\n")
            load_rule_set((temporary,))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    # -- 4. generate

    def generate(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        music = body.get("music_filename")
        sing_value = body.get("sing", False)
        if not isinstance(sing_value, bool):
            raise ShowBuildError("'sing' must be a JSON boolean")
        sing = sing_value
        with self.locked(token) as session:
            if session.analysis_path is None or session.audio_path is None:
                raise ShowBuildError("Add the song before generating")
            if not isinstance(music, str) or not music.strip() or len(music) > 260:
                music = session.audio_name
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
                stem = Path(session.audio_name).stem or "show"
                output = run / f"{stem} (generated).loredit"
                try:
                    show = generate_show(session.preview_path, output, rule_set,
                                         analysis_path=session.analysis_path,
                                         music_filename=music.strip(), vocals_path=vocals,
                                         separate=False)
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
                return {
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


def _raw(requirement: Requirement) -> dict[str, Any]:
    """The requirement as the form edits it."""
    return dict(requirement_mapping(requirement))


def to_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")
