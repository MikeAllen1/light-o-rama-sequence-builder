"""Add new props to a sequence that already exists.

A new prop in the yard this year should not mean re-sequencing every song. This
takes a finished sequence (S5/S6 ``.loredit``, or S4 ``.lms``) and choreographs only
the props it has nothing for, so they fit the show around them:

- **Same style.** The style is learned from the sequence itself (how long its lights
  stay on, fades or cuts, brightness, flashes, twinkle); see style_learning.py.
- **Same music.** With the song, the new props follow its analysis. Without it, the
  song's shape is read from the sequence: its beat from the timing grid, its loud
  and quiet parts from how much of the yard is lit, its big hits from the moments
  most of the yard lights together.
- **Same dark moments.** Wherever the sequence goes dark, the new props stay dark.
- **Nothing else changes.** Every existing prop, effect, timing grid and setting is
  copied exactly; only the new props' effects are added. The source file is never
  modified.

For S5/S6 the new props come from an updated preview (``.lorprev``) that has them,
or from the sequence's own preview when they were added there and left empty. For
S4, add the new channels to the sequence in the S4 Sequencer and leave them empty.
"""

from __future__ import annotations

import copy
import itertools
import statistics
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lor_sequence_builder.choreography import Effect
from lor_sequence_builder.lms import (
    LmsEffect,
    LmsError,
    display_from_lms,
    parse_lms,
    read_lms,
    write_lms,
)
from lor_sequence_builder.lms import (
    _effect_attributes as _lms_attributes,
)
from lor_sequence_builder.loredit import LoreditDocument, LoreditError, read_loredit, write_loredit
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.new_sequence import NewSequenceError, build_new_sequence
from lor_sequence_builder.planner import Plan, plan_show
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.quality import QualityReport
from lor_sequence_builder.quality import check as check_quality
from lor_sequence_builder.rules import RuleReport, RuleSet, check_choreography
from lor_sequence_builder.rules.engine import Display, display_from_preview
from lor_sequence_builder.sequence_writer import _effect_attributes as _s6_attributes
from lor_sequence_builder.style import Style
from lor_sequence_builder.style_learning import (
    Lit,
    StyleLearningError,
    measure_effects,
    sequence_effects,
    song_beat,
    style_from_habits,
)

# The sequence counts as dark where nothing is lit for at least this long.
BLACKOUT = 30
# Bars either side compared when looking for a change of part.
PART_BARS = 4
# Most of the yard starting within this long of each other is a hit.
TOGETHER = 5


class AddPropsError(ValueError):
    """A sequence or preview that props cannot be added to safely."""


@dataclass(frozen=True, slots=True)
class AddedProps:
    sequence_path: Path
    added: tuple[str, ...]
    style: Style
    plan: Plan
    report: RuleReport
    notes: tuple[str, ...]
    from_song: bool
    # The whole sequence, old and new props together, checked as one show.
    quality: QualityReport | None = None


# ---------------------------------------------------------------- the song's shape


def _blackouts(lits: list[Lit], duration: int) -> list[tuple[int, int]]:
    """Where nothing in the sequence is lit, for at least BLACKOUT."""
    spans = sorted((lit.start, lit.end) for lit in lits)
    dark: list[tuple[int, int]] = []
    cursor = 0
    for start, end in spans:
        if start - cursor >= BLACKOUT:
            dark.append((max(1, cursor), start))
        cursor = max(cursor, end)
    if duration - cursor >= BLACKOUT:
        dark.append((max(1, cursor), duration))
    return dark


def _beats(marks: list[int], lits: list[Lit], duration: int) -> tuple[list[int], bool]:
    starts = sorted(lit.start for lit in lits)
    beat, from_grid = song_beat(marks, starts)
    if from_grid:
        gaps = [b - a for a, b in itertools.pairwise(marks) if b > a]
        step = 1
        while statistics.median(gaps) * step < 0.75 * beat:
            step *= 2
        grid = marks[::step]
        if len(grid) >= 8:
            return [t for t in grid if t < duration], True
    # No usable grid: the period (to a twentieth of a centisecond) and phase that put
    # the most effect starts on a beat.
    best = (-1, float(beat), 0.0)
    for tenth in range(-40, 41):
        period = beat + tenth / 20
        bins = [0] * (int(period) + 1)
        for t in starts:
            bins[int(t % period)] += 1
        size = len(bins)
        for offset in range(size):
            score = sum(bins[(offset + d) % size] for d in (-2, -1, 0, 1, 2))
            if score > best[0]:
                best = (score, period, float(offset))
    _, period, phase = best
    count = int((duration - phase) / period) + 1
    return [round(phase + k * period) for k in range(count)
            if round(phase + k * period) < duration], False


def _downbeats(beats: list[int], lits: list[Lit], per_bar: int) -> list[int]:
    """Bars start on the beat that most often has the most starts on it."""
    starts: dict[int, int] = defaultdict(int)
    for lit in lits:
        starts[lit.start] += 1

    def weight(beat: int) -> int:
        return sum(starts.get(beat + d, 0) for d in range(-3, 4))

    phase = max(range(per_bar), key=lambda p: (sum(weight(b) for b in beats[p::per_bar]), -p))
    return beats[phase::per_bar]


def song_shape(lits: list[Lit], marks: list[int], duration: int, channels: int,
               beats_per_bar: int = 4) -> dict[str, Any]:
    """An analysis report made from a finished sequence instead of the song: its beat,
    its loud and quiet parts (how much is lit), its hits and its dark moments."""
    beats, from_grid = _beats(marks, lits, duration)
    if len(beats) < 8:
        raise AddPropsError("The sequence is too short or too sparse to find its beat.")
    downbeats = _downbeats(beats, lits, beats_per_bar)
    frames = duration // 50 + 1
    lit = [0.0] * frames
    for item in lits:
        level = item.peak / 100 * (0.5 if item.kind == "fade" else 1.0)
        for f in range(item.start // 50, min(frames, -(-item.end // 50))):
            lit[f] += level
    smooth = []
    for f in range(frames):
        window = lit[max(0, f - 4):f + 5]
        smooth.append(sum(window) / len(window) / max(1, channels))
    # Part changes: where the bars after a downbeat are clearly busier or calmer
    # than the bars before it.
    bar_level = [statistics.fmean(smooth[a // 50:max(a // 50 + 1, b // 50)])
                 for a, b in zip(downbeats, [*downbeats[1:], duration], strict=True)]
    top = max(bar_level, default=0.0) or 1.0
    change = [0.0] * len(bar_level)
    for i in range(PART_BARS, len(bar_level) - PART_BARS + 1):
        after = statistics.fmean(bar_level[i:i + PART_BARS])
        before = statistics.fmean(bar_level[i - PART_BARS:i])
        change[i] = abs(after - before) / top
    candidates: list[int] = []
    for i in sorted(range(len(change)), key=lambda i: -change[i]):
        if change[i] < 0.15:
            break
        if all(abs(i - j) >= 2 * PART_BARS for j in candidates):
            candidates.append(i)
    together: dict[int, set[str]] = defaultdict(set)
    for item in lits:
        together[item.start // TOGETHER].add(item.channel)
    onsets = sorted((bucket * TOGETHER, len(chans) / max(1, channels))
                    for bucket, chans in together.items())
    hits = [t for t, share in onsets if share >= 0.6 and share * channels >= 3]
    return {
        "schema_version": "2.0",
        "configuration": {"beats_per_bar": beats_per_bar},
        "audio": {"file_name": "", "duration_seconds": duration / 100},
        "analysis": {
            "beats": [{"time": t / 100, "confidence": 1.0} for t in beats],
            "downbeats": [{"time": t / 100, "confidence": 1.0} for t in downbeats],
            "energy": [{"time": f / 2, "rms": round(v, 4)} for f, v in enumerate(smooth)],
            "section_candidates": [{"time": downbeats[i] / 100} for i in sorted(candidates)],
            "onsets": [{"time": t / 100, "strength": round(share, 3)} for t, share in onsets],
            "crashes": [{"time": t / 100} for t in hits],
            "hard_stops": [{"time": a / 100, "silence_duration": (b - a) / 100}
                           for a, b in _blackouts(lits, duration)],
        },
        "source": "sequence" if not from_grid else "sequence timing grid",
    }


def _with_blackouts(analysis: dict[str, Any], lits: list[Lit], duration: int) -> dict[str, Any]:
    """A song's analysis, with the sequence's own dark moments as stops."""
    extra = [{"time": a / 100, "silence_duration": (b - a) / 100}
             for a, b in _blackouts(lits, duration)]
    inner = dict(analysis.get("analysis", {}))
    inner["hard_stops"] = [*inner.get("hard_stops", []), *extra]
    return {**analysis, "analysis": inner}


# ---------------------------------------------------------------- what to add


def _subset(display: Display, keep: set[str]) -> Display:
    return Display({pid: prop for pid, prop in display.props.items() if pid in keep},
                   {name: tuple(m for m in members if m in keep)
                    for name, members in display.groups.items()
                    if sum(1 for m in members if m in keep) >= 2})


def _preview_subset(preview: ET.Element, keep: set[str]) -> ET.Element:
    """The preview with only these props (and what links to them), for the rules."""
    trimmed = copy.deepcopy(preview)
    for prop in trimmed.findall("PropClass"):
        master = prop.get("MasterPropId", "").strip()
        if prop.get("id") not in keep and master not in keep:
            trimmed.remove(prop)
    kept = {p.get("id") for p in trimmed.findall("PropClass")}
    for group in trimmed.findall("PropGroup"):
        for member in group.findall("member"):
            if member.get("id") not in kept:
                group.remove(member)
        if not group.findall("member"):
            trimmed.remove(group)
    return trimmed


def _plan(lits: list[Lit], marks: list[int], duration: int, preview: ET.Element,
          targets: set[str], rule_set: RuleSet, style: Style | None,
          analysis: dict[str, Any] | None, beats_per_bar: int,
          ) -> tuple[Plan, RuleReport, Style, list[str], dict[str, Any]]:
    channels = len({lit.channel for lit in lits})
    notes: list[str] = []
    if style is None:
        try:
            habits = measure_effects(lits, channels, marks)
        except StyleLearningError as exc:
            raise AddPropsError("The sequence " + str(exc)) from exc
        style, changes = style_from_habits(habits, "This sequence's style")
        notes.append("Style learned from the sequence: " + " ".join(changes))
    if analysis is None:
        analysis = song_shape(lits, marks, duration, channels, beats_per_bar)
        notes.append("The song's beat and its loud and quiet parts were read from the "
                     f"sequence ({analysis['source']}); add the song for a closer fit.")
    else:
        analysis = _with_blackouts(analysis, lits, duration)
    display = _subset(display_from_preview(preview), targets)
    plan = plan_show(analysis, display, rule_set, None, style)
    report = check_choreography(_preview_subset(preview, targets), plan.choreography, rule_set)
    if not report.ok:
        raise AddPropsError("The new props' effects did not pass the rules: "
                            + "; ".join(e.message for e in report.errors[:3]))
    return plan, report, style, notes, analysis


def _whole_show_quality(lits: list[Lit], prop_of: Callable[[str], str], plan: Plan,
                        analysis: dict[str, Any], preview: ET.Element,
                        duration: int) -> QualityReport:
    """The quality check on the finished sequence: the props that were there and the
    new ones, as one show."""
    old = [Effect(prop_of(lit.channel), 0, lit.start, lit.end, "on", lit.peak, lit.peak)
           for lit in lits]
    effects = sorted([*old, *plan.choreography.effects],
                     key=lambda e: (e.start_centisecond, e.prop_id))
    display = display_from_preview(preview)
    props = {e.prop_id for e in effects}
    roles = {p: display.props[p].role if p in display.props else "unknown:" + p for p in props}
    inner = analysis.get("analysis", {})

    def times(key: str) -> list[int]:
        return [round(float(v["time"]) * 100) for v in inner.get(key, [])
                if isinstance(v, dict) and isinstance(v.get("time"), int | float)]

    beats = times("beats")
    marks = [*beats, *((a + b) // 2 for a, b in itertools.pairwise(beats)),
             *times("onsets"), *times("kicks"), *times("snares"), *times("crashes"),
             *(s.start_centisecond for s in plan.sections)]
    bars = times("downbeats")
    phrases = [(a, b) for a, b in zip(bars[::4], [*bars[4::4], duration], strict=False)]
    quiet = [(round(float(h["time"]) * 100),
              round((float(h["time"]) + float(h.get("silence_duration", 0))) * 100))
             for h in inner.get("hard_stops", [])]
    excused = [(t, t + 100) for kind, t in plan.moments
               if kind in {"crash", "return", "lyric_cue", "lift"}]
    excused += [(t - 200, duration) for kind, t in plan.moments if kind == "finale_hits"]
    return check_quality(effects, duration, props, roles,
                         [(s.start_centisecond, s.end_centisecond, s.level)
                          for s in plan.sections],
                         marks, phrases, quiet, excused)


def _analysis_from_song(audio_path: str | Path, beats_per_bar: int,
                        input_demuxer: str | None = None) -> dict[str, Any]:
    from lor_sequence_builder.audio_analysis import analyze_audio
    from lor_sequence_builder.evaluation import load_analysis

    with tempfile.TemporaryDirectory(prefix="lor-add-") as folder:
        report = Path(folder) / "song.analysis.json"
        analyze_audio(audio_path, report, Path(folder) / "song.svg",
                      beats_per_bar=beats_per_bar, input_demuxer=input_demuxer)
        return load_analysis(report)


def _effect_count(element: ET.Element) -> int:
    return sum(1 for _ in element.iter("effect"))


# ---------------------------------------------------------------- S5/S6


def _add_s6(sequence_path: Path, output: Path, rule_set: RuleSet, preview_path: Path | None,
            analysis: dict[str, Any] | None, style: Style | None,
            beats_per_bar: int) -> AddedProps:
    if output.suffix.lower() != ".loredit":
        raise AddPropsError("The new sequence must use the .loredit extension")
    try:
        old = read_loredit(sequence_path)
    except LoreditError as exc:
        raise AddPropsError(str(exc)) from exc
    root = copy.deepcopy(old.root)
    duration = old.total_centiseconds
    if preview_path is not None:
        preview = preview_element(read_lorprev(preview_path))
    else:
        found = root.find("PreviewClass")
        if found is None:
            raise AddPropsError("The sequence has no preview")
        preview = found
    music = root.get("musicFilename") or "song.mp3"
    try:
        fresh = build_new_sequence(preview, max(1, duration), music)
    except NewSequenceError as exc:
        raise AddPropsError(str(exc)) from exc
    fresh_props = {p.get("id", ""): p for p in fresh.document.root.iterfind(
        "SequenceProps/SeqProp")}
    fresh_preview = fresh.document.root.find("PreviewClass")
    assert fresh_preview is not None
    known = {e.get("id") for tag in ("PropClass", "PropGroup")
             for e in fresh_preview.findall(tag)}
    sequence_props = root.find("SequenceProps")
    if sequence_props is None:
        raise AddPropsError("The sequence has no SequenceProps")
    old_props = {p.get("id", ""): p for p in sequence_props.findall("SeqProp")}
    missing = [p.get("name") or pid for pid, p in old_props.items() if pid not in known]
    if missing:
        raise AddPropsError("The preview no longer has " + ", ".join(sorted(missing)[:8])
                            + ". This adds props; remove props in the Sequencer instead.")
    changed = [p.get("name") or pid for pid, p in old_props.items()
               if pid in fresh_props and _effect_count(p)
               and len(p.findall("channel")) != len(fresh_props[pid].findall("channel"))]
    if changed:
        raise AddPropsError("These props have a different number of channels in the "
                            "preview than in the sequence: " + ", ".join(sorted(changed)[:8]))
    targets = {pid for pid, p in fresh_props.items()
               if pid not in old_props or not _effect_count(old_props[pid])}
    if not targets:
        raise AddPropsError("Every prop in the preview already has effects in this "
                            "sequence; there is nothing new to add.")
    lits, marks = sequence_effects(root, s4=False)
    plan, report, style, notes, used = _plan(lits, marks, duration, fresh_preview, targets,
                                             rule_set, style, analysis, beats_per_bar)
    quality = _whole_show_quality(lits, lambda key: key.rsplit("/", 1)[0], plan, used,
                                  fresh_preview, duration)
    # The updated preview replaces the old one in place; new props join the end.
    if preview_path is not None:
        index = list(root).index(root.find("PreviewClass"))  # type: ignore[arg-type]
        root.remove(root[index])
        root.insert(index, copy.deepcopy(fresh_preview))
    for pid in sorted(targets, key=lambda p: list(fresh_props).index(p)):
        if pid in old_props:
            continue
        sequence_props.append(copy.deepcopy(fresh_props[pid]))
    channels = {p.get("id", ""): p.findall("channel")
                for p in sequence_props.findall("SeqProp")}
    for effect in sorted(plan.choreography.effects,
                         key=lambda e: (e.prop_id, e.channel_index, e.start_centisecond)):
        target = channels[effect.prop_id][effect.channel_index]
        ET.SubElement(target, "effect", _s6_attributes(effect))
    try:
        written = write_loredit(LoreditDocument(root, sequence_path), output)
    except LoreditError as exc:
        raise AddPropsError(str(exc)) from exc
    names = tuple(sorted(fresh_props[p].get("name", p) for p in targets
                         if any(e.prop_id == p for e in plan.choreography.effects)))
    return AddedProps(written, names, style, plan, report, tuple(notes), analysis is not None,
                      quality)


# ---------------------------------------------------------------- S4


def _add_s4(sequence_path: Path, output: Path, rule_set: RuleSet,
            analysis: dict[str, Any] | None, style: Style | None,
            beats_per_bar: int) -> AddedProps:
    if output.suffix.lower() != ".lms":
        raise AddPropsError("An S4 sequence stays S4: use the .lms extension")
    try:
        old = read_lms(sequence_path)
        display = display_from_lms(old, sequence_path.stem)
    except LmsError as exc:
        raise AddPropsError(str(exc)) from exc
    root = copy.deepcopy(old.root)
    by_index = {int(c.get("savedIndex", "-1")): c for c in root.iterfind("channels/channel")}
    empty = {pid for pid, index in display.prop_channels.items()
             if not by_index[index].findall("effect")}
    if not empty:
        raise AddPropsError("Every LOR channel already has effects in this sequence. Add the "
                            "new channels in the S4 Sequencer first, and leave them empty.")
    if len(empty) == len(display.prop_channels):
        raise AddPropsError("This sequence has no effects yet; make a new show for it "
                            "instead.")
    lits, marks = sequence_effects(root, s4=True)
    duration = old.total_centiseconds
    plan, report, style, notes, used = _plan(lits, marks, duration, display.preview, empty,
                                             rule_set, style, analysis, beats_per_bar)
    prop_at = {f"s{index}": pid for pid, index in display.prop_channels.items()}
    quality = _whole_show_quality(lits, lambda key: prop_at.get(key, key), plan, used,
                                  display.preview, duration)
    for effect in sorted(plan.choreography.effects,
                         key=lambda e: (e.prop_id, e.start_centisecond)):
        index = display.prop_channels[effect.prop_id]
        ET.SubElement(by_index[index], "effect", _lms_attributes(LmsEffect(
            index, effect.kind, effect.start_centisecond, effect.end_centisecond,
            effect.start_intensity, effect.end_intensity)))
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    text = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + body
    content = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    try:
        parse_lms(content, "The new .lms")
        written = write_lms(output, content)
    except LmsError as exc:
        raise AddPropsError(str(exc)) from exc
    names = {pid: e.get("Name", pid) for pid, e in
             ((p.get("id", ""), p) for p in display.preview.findall("PropClass"))}
    added = tuple(sorted(names[p] for p in empty
                         if any(e.prop_id == p for e in plan.choreography.effects)))
    return AddedProps(written, added, style, plan, report, tuple(notes), analysis is not None,
                      quality)


def add_props(
    sequence_path: str | Path,
    output_path: str | Path,
    rule_set: RuleSet,
    preview_path: str | Path | None = None,
    audio_path: str | Path | None = None,
    style: Style | None = None,
    beats_per_bar: int = 4,
    progress: Callable[[str], None] | None = None,
    input_demuxer: str | None = None,
) -> AddedProps:
    """Choreograph the props a finished sequence has nothing for, and write the
    sequence with them added as a new file."""
    source = Path(sequence_path)
    output = Path(output_path)
    if output.exists():
        raise AddPropsError(f"{output.name} already exists; choose a new name")
    try:
        if output.resolve() == source.resolve():
            raise AddPropsError("Write the new sequence to a new file; the original is kept "
                                "as it is.")
    except OSError as exc:
        raise AddPropsError(f"Cannot use {output}") from exc
    analysis = None
    if audio_path is not None:
        if progress is not None:
            progress("Listening to the song")
        analysis = _analysis_from_song(audio_path, beats_per_bar, input_demuxer)
    if progress is not None:
        progress("Planning the new props")
    if source.suffix.lower() == ".lms":
        if preview_path is not None:
            raise AddPropsError("For S4, add the new channels to the .lms itself in the S4 "
                                "Sequencer; there is no separate preview.")
        return _add_s4(source, output, rule_set, analysis, style, beats_per_bar)
    if source.suffix.lower() != ".loredit":
        raise AddPropsError("Add props to a .loredit (S5/S6) or .lms (S4) sequence.")
    return _add_s6(source, output, rule_set, None if preview_path is None else Path(preview_path),
                   analysis, style, beats_per_bar)



# ---------------------------------------------------------------- the app

SESSION_SECONDS = 3600
MAX_SESSIONS = 3


@dataclass(slots=True)
class _Job:
    token: str
    folder: tempfile.TemporaryDirectory[str]
    sequence: Path
    file_name: str
    preview: Path | None = None
    audio: Path | None = None
    demuxer: str | None = None
    last_used: float = 0.0


class AddSessions:
    """Bounded, expiring places to keep one sequence, its new preview and its song
    while the app adds props. Nothing is kept after the session ends."""

    def __init__(self) -> None:
        import threading

        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def _drop(self, token: str) -> None:
        job = self._jobs.pop(token, None)
        if job is not None:
            job.folder.cleanup()

    def start(self, payload: bytes, file_name: str) -> dict[str, Any]:
        import secrets
        import time

        name = Path(file_name).name[:200]
        suffix = Path(name).suffix.lower()
        if suffix not in {".loredit", ".lms"}:
            raise AddPropsError("Choose the finished sequence: a .loredit (S5/S6) or .lms (S4).")
        with self._lock:
            now = time.monotonic()
            for token, job in list(self._jobs.items()):
                if now - job.last_used > SESSION_SECONDS:
                    self._drop(token)
            while len(self._jobs) >= MAX_SESSIONS:
                self._drop(min(self._jobs.values(), key=lambda j: j.last_used).token)
            folder = tempfile.TemporaryDirectory(prefix="lor-add-")
            path = Path(folder.name) / ("sequence" + suffix)
            path.write_bytes(payload)
            try:
                if suffix == ".lms":
                    read_lms(path)
                else:
                    read_loredit(path)
            except (LmsError, LoreditError) as exc:
                folder.cleanup()
                raise AddPropsError(str(exc)) from exc
            token = secrets.token_urlsafe(16)
            self._jobs[token] = _Job(token, folder, path, name, last_used=now)
        lits, _ = sequence_effects(read_lms(path).root if suffix == ".lms"
                                   else read_loredit(path).root, s4=suffix == ".lms")
        return {"token": token, "file_name": name, "s4": suffix == ".lms",
                "effects": len(lits), "channels": len({lit.channel for lit in lits})}

    def _job(self, token: str) -> _Job:
        import time

        with self._lock:
            job = self._jobs.get(token)
            if job is None:
                raise AddPropsError("Choose the sequence again; it was put away after a long "
                                    "break.")
            job.last_used = time.monotonic()
            return job

    def preview(self, token: str, payload: bytes) -> dict[str, Any]:
        job = self._job(token)
        if job.sequence.suffix == ".lms":
            raise AddPropsError("For S4, add the new channels to the .lms in the S4 Sequencer; "
                                "there is no separate preview.")
        path = Path(job.folder.name) / "display.lorprev"
        path.write_bytes(payload)
        model = read_lorprev(path)
        job.preview = path
        return {"props": len(preview_element(model).findall("PropClass"))}

    def audio(self, token: str, payload: bytes, suffix: str, demuxer: str) -> dict[str, Any]:
        job = self._job(token)
        path = Path(job.folder.name) / ("song" + suffix)
        path.write_bytes(payload)
        job.audio, job.demuxer = path, demuxer
        return {"ok": True}

    def build(self, token: str, rule_set: RuleSet, style: Style | None = None
              ) -> dict[str, Any]:
        job = self._job(token)
        stem = Path(job.file_name).stem
        output = Path(job.folder.name) / "out" / (stem + " (new props)" + job.sequence.suffix)
        if output.exists():
            output.unlink()
        output.parent.mkdir(exist_ok=True)
        result = add_props(job.sequence, output, rule_set, job.preview, job.audio, style,
                           input_demuxer=job.demuxer)
        content = result.sequence_path.read_bytes()
        return {
            "file_name": output.name,
            "sequence": content.decode("utf-8"),
            "added": list(result.added),
            "notes": [*result.notes, *(n for n in result.plan.notes
                                      if n.startswith("Arrangement"))],
            "quality": None if result.quality is None else {
                "summary": result.quality.summary(),
                "findings": [f.message for f in result.quality.findings
                             if f.status != "good"]},
            "from_song": result.from_song,
        }

    def close(self) -> None:
        with self._lock:
            for token in list(self._jobs):
                self._drop(token)
