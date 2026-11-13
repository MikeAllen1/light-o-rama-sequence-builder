"""Planner v1: turn music analysis and a display into a choreography Timeline.

The plan reads the song the way a person sequencing by hand would:

1. Split the song into sections at the analyzer's section candidates and give
   each an energy level (low, mid, high) from its loudness relative to the rest
   of the song. Sections are labeled intro, verse, chorus, finale or outro from
   that level and their place in the song. Labels are guesses from energy, not
   recognition, and the report says so.
2. Cut out hard stops: nothing moves through a silence, and movements are
   planned inside the gaps between stops, so they always finish.
3. Give each kind of prop a look per energy level. Quiet sections use few props
   and slow motion; loud sections use more props and faster motion. Rows of
   look-alike props (arches, mini trees) chase or fill in their real order in
   the preview; a mega tree rotates through its segments; outlines, stars and
   decorations hold, pulse or twinkle. A section louder than the one before
   starts with an accent.
4. Honor display requirements while planning, not after: excluded props are
   never used, kept-on props hold, quiet sections are respected, colors and
   brightness are limited, and chases run the required way.

5. Arrange the show like a song (Planner v2): a part that repeats (a second
   chorus) repeats its look, and a later repeat of a loud part lifts with one
   more lead; in mid-energy parts two groups trade bars, call and response;
   the last phrase before a louder part builds up in brightness; crashes and
   returns from a hard stop are signature moments that flash the whole
   display. The song's own shape picks where the handoffs start, so two
   songs give two different shows.

Singing faces follow vocal analysis when it is given (Phase 8). Everything is
deterministic: the same inputs give the same plan.
"""

from __future__ import annotations

import bisect
import dataclasses
import itertools
import math
import re
import zlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lor_sequence_builder.choreography import Choreography, Effect, Movement, Section
from lor_sequence_builder.formation import Formation, formation
from lor_sequence_builder.quality import DEAD_SHARE, DEAD_SPAN, QualityReport, lit_share
from lor_sequence_builder.quality import check as check_quality
from lor_sequence_builder.rules import RuleSet, select_props
from lor_sequence_builder.rules.engine import ANCHOR_FLOOR, Display, DisplayProp
from lor_sequence_builder.style import Style, get_style

LOW, MID, HIGH = 0, 1, 2
LEVEL_NAMES = ("low", "mid", "high")
SECTION_FALLBACK_BARS = 8
MIN_SECTION_CENTISECONDS = 400

_OPPOSITE = {
    "left_to_right": "right_to_left",
    "right_to_left": "left_to_right",
    "row_order": "reverse_row_order",
    "reverse_row_order": "row_order",
    "top_to_bottom": "bottom_to_top",
    "bottom_to_top": "top_to_bottom",
}


class PlanningError(ValueError):
    """Raised when a show cannot be planned from the inputs."""


@dataclass(frozen=True, slots=True)
class PlannedSection:
    label: str
    level: int
    start_centisecond: int
    end_centisecond: int
    energy: float
    # Sections that sound alike (a verse and its return) share a part number, when
    # the analysis has bar signatures; None when not known.
    part: int | None = None


@dataclass(frozen=True, slots=True)
class SkippedProp:
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class Plan:
    choreography: Choreography
    sections: tuple[PlannedSection, ...]
    used_props: tuple[str, ...]
    skipped_props: tuple[SkippedProp, ...]
    notes: tuple[str, ...]
    # Signature moments and arrangement choices, for the report: (kind, centisecond).
    moments: tuple[tuple[str, int], ...] = ()
    # How the finished show measures up (see quality.py).
    quality: QualityReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [
                {"label": s.label, "energy_level": LEVEL_NAMES[s.level],
                 "start_centisecond": s.start_centisecond, "end_centisecond": s.end_centisecond,
                 "relative_energy": round(s.energy, 3)}
                for s in self.sections
            ],
            "used_props": list(self.used_props),
            "skipped_props": [{"name": s.name, "reason": s.reason} for s in self.skipped_props],
            "notes": list(self.notes),
            "effects": len(self.choreography.effects),
            "movements": len(self.choreography.movements),
            "moments": [{"kind": kind, "centisecond": time} for kind, time in self.moments],
            "quality": None if self.quality is None else self.quality.to_dict(),
        }


# ---------------------------------------------------------------- music


def _cs(seconds: float) -> int:
    return round(seconds * 100)


def _times(analysis: dict[str, Any], key: str) -> list[int]:
    values = analysis.get("analysis", {}).get(key, [])
    return sorted({_cs(float(v["time"])) for v in values
                   if isinstance(v, dict) and isinstance(v.get("time"), int | float)})


@dataclass(frozen=True, slots=True)
class _Music:
    duration: int
    beats: list[int]
    downbeats: list[int]
    energy: list[tuple[int, float]]
    section_starts: list[int]
    stops: list[tuple[int, int]]
    notes: list[str]
    # Part names the user gave sections in a music review, by section start.
    labels: dict[int, str] = field(default_factory=dict)
    beats_per_bar: int = 4
    bar_phase: int = 0
    # What each bar sounds like (start, harmony and tone colour), centred on the
    # song's average, from the analysis's bar signatures.
    bars: list[tuple[int, list[float]]] = field(default_factory=list)


def _music(analysis: dict[str, Any]) -> _Music:
    try:
        duration = _cs(float(analysis["audio"]["duration_seconds"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanningError("Analysis is missing the audio duration") from exc
    if duration <= 0:
        raise PlanningError("Analysis has no audio duration")
    notes: list[str] = []
    beats = [b for b in _times(analysis, "beats") if 0 <= b < duration]
    if len(beats) < 2:
        raise PlanningError(
            "Audio analysis did not find a usable beat grid. Re-analyze the song; "
            "the planner will not invent a tempo and generate choreography against it."
        )
    beat_set = set(beats)
    downbeats = [d for d in _times(analysis, "downbeats") if d in beat_set]
    # The analyzer records its configured meter in the report. Preserve that
    # setting when its downbeat phase is unavailable instead of silently
    # treating every song as 4/4.
    configuration = analysis.get("configuration", {})
    configured_meter = configuration.get("beats_per_bar", 4) if isinstance(
        configuration, dict) else 4
    beats_per_bar = int(configured_meter) if (
        isinstance(configured_meter, int | float)
        and not isinstance(configured_meter, bool)
        and configured_meter in (3, 4)
    ) else 4
    if len(downbeats) < 2:
        phase = beats.index(downbeats[0]) % beats_per_bar if downbeats else 0
        downbeats = [beat for index, beat in enumerate(beats)
                     if index % beats_per_bar == phase]
        notes.append(
            f"Downbeat phase was unavailable; assumed a bar every {beats_per_bar} beats."
        )
    else:
        phase = beats.index(downbeats[0]) % beats_per_bar
    energy: list[tuple[int, float]] = []
    for frame in analysis.get("analysis", {}).get("energy", []):
        if isinstance(frame, dict) and isinstance(frame.get("rms"), int | float):
            energy.append((_cs(float(frame["time"])), float(frame["rms"])))
    stops: list[tuple[int, int]] = []
    for stop in analysis.get("analysis", {}).get("hard_stops", []):
        try:
            start = _cs(float(stop["time"]))
            length = _cs(float(stop.get("silence_duration", 0)))
        except (KeyError, TypeError, ValueError):
            continue
        # A silence at the very start is a lead-in, not a stop.
        if start > 0 and length > 0:
            stops.append((start, min(duration, start + length)))
    starts = sorted({_snap(t, downbeats) for t in _times(analysis, "section_candidates")
                     if 0 < t < duration})
    reviewed = any(isinstance(c, dict) and c.get("label")
                   for c in analysis.get("analysis", {}).get("section_candidates", []))
    bars = _bar_vectors(analysis)
    if not reviewed and bars:
        # Where the song moves on to a different part (verse to chorus), even when
        # the loudness barely changes.
        starts = sorted(set(starts) | set(_repetition_starts(bars, downbeats, starts)))
    if not reviewed:
        # Detected changes land near, not on, the song's phrases; a person's own
        # section marks from a music review are left where they put them.
        phrased = _on_phrases(starts, downbeats)
        if phrased != starts:
            notes.append("Section starts were moved to the nearest four-bar phrase line.")
        starts = phrased
    labels: dict[int, str] = {}
    for candidate in analysis.get("analysis", {}).get("section_candidates", []):
        if (isinstance(candidate, dict) and isinstance(candidate.get("label"), str)
                and candidate["label"].strip() and isinstance(candidate.get("time"), int | float)):
            labels[_snap(_cs(float(candidate["time"])), downbeats)] = (
                candidate["label"].strip().lower())
    return _Music(duration, beats, downbeats, energy, starts, stops, notes, labels,
                   beats_per_bar, phase, bars)


def _bar_vectors(analysis: dict[str, Any]) -> list[tuple[int, list[float]]]:
    """Each bar's harmony and (at half weight) tone colour, minus the song's average,
    so what is left is what makes this bar different from the rest of the song."""
    raw: list[tuple[int, list[float]]] = []
    for bar in analysis.get("analysis", {}).get("bar_signatures", []):
        if not isinstance(bar, dict) or not isinstance(bar.get("time"), int | float):
            continue
        chroma, timbre = bar.get("chroma"), bar.get("timbre")
        if not (isinstance(chroma, list) and len(chroma) == 12 and isinstance(timbre, list)
                and len(timbre) == 6):
            continue
        raw.append((_cs(float(bar["time"])),
                    [float(v) for v in chroma] + [0.5 * float(v) for v in timbre]))
    if len(raw) < 8:
        return []
    mean = [sum(v[i] for _, v in raw) / len(raw) for i in range(18)]
    return [(t, [x - m for x, m in zip(v, mean, strict=True)]) for t, v in raw]


PHRASE_BARS = 4


def _repetition_starts(bars: list[tuple[int, list[float]]], downbeats: list[int],
                       starts: list[int]) -> list[int]:
    """Phrase lines where the song moves on to a different part. Four-bar phrases are
    grouped by how alike they sound bar for bar; a new part starts where the group
    changes and stays changed for at least two phrases."""
    by_time = dict(bars)
    marks = [d for d in downbeats if d in by_time]
    if len(marks) < 4 * PHRASE_BARS:
        return []
    # Count phrases from the bar most detected changes fall on.
    index = {d: i for i, d in enumerate(marks)}
    phases = [index[t] % PHRASE_BARS for t in starts if t in index]
    phase = max(range(PHRASE_BARS), key=lambda p: (phases.count(p), -p)) if phases else 0
    phrases = [marks[i:i + PHRASE_BARS] for i in range(phase, len(marks) - PHRASE_BARS + 1,
                                                       PHRASE_BARS)]
    groups: list[list[list[float]]] = []
    kinds: list[int] = []
    for phrase in phrases:
        vectors = [by_time[t] for t in phrase]
        alike = [sum(_cosine(a, b) for a, b in zip(vectors, rep, strict=True)) / len(vectors)
                 for rep in groups]
        best = max(range(len(alike)), key=lambda g: alike[g], default=-1)
        if best >= 0 and alike[best] >= SAME_PART:
            kinds.append(best)
        else:
            groups.append(vectors)
            kinds.append(len(groups) - 1)
    found = []
    for k in range(1, len(kinds)):
        # A change that the old part does not come straight back from.
        if kinds[k] != kinds[k - 1] and (k + 1 == len(kinds) or kinds[k + 1] != kinds[k - 1]):
            found.append(phrases[k][0])
    return found


def _on_phrases(starts: list[int], downbeats: list[int]) -> list[int]:
    """Move section starts onto four-bar phrase lines.

    The bar a phrase count starts from is the one that puts the detected changes
    nearest to phrase lines; a change already within two bars of a line moves to it
    (an exact tie goes earlier, since a change is heard after it happens).
    """
    if len(downbeats) < 2 * PHRASE_BARS or not starts:
        return starts
    position = {d: i for i, d in enumerate(downbeats)}
    indices = [position[t] for t in starts if t in position]
    if not indices:
        return starts

    def distance(index: int, phase: int) -> int:
        r = (index - phase) % PHRASE_BARS
        return min(r, PHRASE_BARS - r)

    # A tie goes to counting phrases from the song's first bar.
    phase = min(range(PHRASE_BARS),
                key=lambda p: (sum(distance(i, p) for i in indices), distance(0, p), p))
    moved = set()
    for t in starts:
        i = position.get(t)
        if i is None:
            moved.add(t)
            continue
        r = (i - phase) % PHRASE_BARS
        target = i - r if r <= PHRASE_BARS // 2 else i + (PHRASE_BARS - r)
        moved.add(downbeats[max(0, min(len(downbeats) - 1, target))])
    return sorted(moved)


def _snap(time: int, grid: list[int]) -> int:
    if not grid:
        return time
    return min(grid, key=lambda g: abs(g - time))


def _sections(music: _Music) -> list[PlannedSection]:
    starts = [s for s in music.section_starts if s > 0]
    if not starts:
        starts = music.downbeats[SECTION_FALLBACK_BARS::SECTION_FALLBACK_BARS]
        music.notes.append(
            f"No section changes were detected; the song was split every "
            f"{SECTION_FALLBACK_BARS} bars."
        )
    bounds: list[int] = [0]
    for start in starts:
        if start - bounds[-1] >= MIN_SECTION_CENTISECONDS and music.duration - start >= \
                MIN_SECTION_CENTISECONDS:
            bounds.append(start)
    bounds.append(music.duration)
    spans = list(itertools.pairwise(bounds))

    def loudness(start: int, end: int) -> float:
        values = [rms for t, rms in music.energy if start <= t < end]
        return sum(values) / len(values) if values else 0.0

    raw = [loudness(a, b) for a, b in spans]
    # Rank sections against each other, weighted by length: the quietest third of the
    # song is low energy, the loudest third high. Mastered songs differ only a little
    # in loudness from section to section, so a scale from quietest to loudest would
    # call almost everything loud.
    total = sum(b - a for a, b in spans) or 1
    order = sorted(range(len(spans)), key=lambda i: raw[i])
    relative = [0.0] * len(spans)
    elapsed = 0
    for i in order:
        length = spans[i][1] - spans[i][0]
        relative[i] = (elapsed + length / 2) / total
        elapsed += length
    # Sections equally loud share one rank (the middle of their run), so a song
    # with an even level is not split into quiet, mid and loud by order alone.
    tolerance = 0.01 * max(raw, default=0.0)
    runs: list[list[int]] = []
    for i in order:
        if runs and raw[i] - raw[runs[-1][0]] <= tolerance:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        if len(run) > 1:
            weight = sum(spans[j][1] - spans[j][0] for j in run)
            shared = sum(relative[j] * (spans[j][1] - spans[j][0]) for j in run) / weight
            for j in run:
                relative[j] = shared
    levels = [LOW if r < 1 / 3 else MID if r < 2 / 3 else HIGH for r in relative]
    if len(spans) == 1:
        levels = [MID]
    sections: list[PlannedSection] = []
    for index, ((start, end), level, rel) in enumerate(zip(spans, levels, relative,
                                                           strict=True)):
        last = index == len(spans) - 1
        if index == 0 and len(spans) > 1 and level < HIGH and end - start <= 3000:
            label = "intro"
        elif last and len(spans) > 1:
            label = "finale" if level == HIGH else "outro"
        else:
            label = "chorus" if level == HIGH else "verse"
        # A name from the music review wins over the guess. Its marker is matched to
        # the section that starts nearest it (within a second before, four after).
        sections.append(PlannedSection(label, level, start, end, rel))
    sections = _name_parts(sections, music)
    # A name from the music review wins over the guess. Its marker is matched to
    # the section that starts nearest it (within a second before, four after).
    named_sections = []
    for section in sections:
        start, end = section.start_centisecond, section.end_centisecond
        named = [t for t in music.labels if start - 100 <= t < min(end, start + 400)]
        if named:
            section = dataclasses.replace(
                section, label=music.labels[min(named, key=lambda t: abs(t - start))])
        named_sections.append(section)
    return named_sections


# Two sections are the same part when their bars, matched in order, are this alike.
SAME_PART = 0.6


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _alike(first: list[list[float]], second: list[list[float]]) -> float:
    """How alike two sections sound, bar against bar in order (allowing a bar of
    pickup either way): a returning verse plays the same chords in the same order."""
    best = 0.0
    for shift in (-1, 0, 1):
        pairs = [(first[i], second[i + shift]) for i in range(len(first))
                 if 0 <= i + shift < len(second)]
        if len(pairs) >= 4:
            best = max(best, sum(_cosine(a, b) for a, b in pairs) / len(pairs))
    return best


def _name_parts(sections: list[PlannedSection], music: _Music) -> list[PlannedSection]:
    """Name sections by what repeats, not only by loudness: the loudest part that
    comes back is the chorus, other parts that come back are verses, and a part
    heard once between choruses is the bridge. Without bar signatures, or when
    nothing repeats, the loudness names stand."""
    if not music.bars or len(sections) < 3:
        return sections
    bars = [[v for t, v in music.bars if s.start_centisecond <= t < s.end_centisecond]
            for s in sections]
    count = len(sections)
    part = list(range(count))

    def root(i: int) -> int:
        while part[i] != i:
            i = part[i]
        return i

    for i in range(count):
        for j in range(i + 1, count):
            if bars[i] and bars[j] and _alike(bars[i], bars[j]) >= SAME_PART:
                part[root(j)] = root(i)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(count):
        groups[root(i)].append(i)
    repeating = [members for members in groups.values() if len(members) >= 2]
    if not repeating:
        return sections

    def loudness(members: list[int]) -> float:
        return sum(sections[i].energy for i in members) / len(members)

    chorus = max(repeating, key=loudness)
    median = sorted(s.energy for s in sections)[count // 2]
    names: dict[int, str] = {}
    if loudness(chorus) >= median:
        for i in chorus:
            names[i] = "chorus"
    for members in repeating:
        for i in members:
            names.setdefault(i, "verse")
    choruses = sorted(i for i, name in names.items() if name == "chorus")
    for members in groups.values():
        if len(members) == 1:
            i = members[0]
            if choruses and choruses[0] < i < choruses[-1]:
                names[i] = "bridge"
    named: list[PlannedSection] = []
    numbers = {root(i): n for n, i in enumerate(sorted({root(i) for i in range(count)}))}
    for i, section in enumerate(sections):
        label = section.label
        if i in names and label not in {"intro", "outro", "finale"}:
            label = names[i]
        named.append(dataclasses.replace(section, label=label, part=numbers[root(i)]))
    music.notes.append("Section names come from which parts of the song repeat (and how "
                       "loud they are), not from recognizing the words.")
    return named


@dataclass(frozen=True, slots=True)
class _Window:
    """Part of a section between hard stops. Motion lives inside one window."""

    section_index: int
    start: int
    end: int
    beats: tuple[int, ...]
    downbeats: tuple[int, ...]
    accent: bool
    # Beats of the section's window before this one starts: patterns that alternate
    # beat by beat keep the same footing however the window was cut.
    offset: int = 0
    beats_per_bar: int = 4
    bar_phase: int = 0
    bar_offset: int = 0


def _windows(music: _Music, sections: list[PlannedSection]) -> list[_Window]:
    windows: list[_Window] = []
    for index, section in enumerate(sections):
        pieces = [(section.start_centisecond, section.end_centisecond)]
        for stop_start, stop_end in music.stops:
            next_pieces = []
            for a, b in pieces:
                if stop_end <= a or stop_start >= b:
                    next_pieces.append((a, b))
                    continue
                if a < stop_start:
                    next_pieces.append((a, stop_start))
                if stop_end < b:
                    next_pieces.append((stop_end, b))
            pieces = next_pieces
        louder = index > 0 and section.level > sections[index - 1].level
        for piece_index, (a, b) in enumerate(pieces):
            if b - a < 50:
                continue
            windows.append(_Window(
                index, a, b,
                tuple(t for t in music.beats if a <= t < b),
                tuple(t for t in music.downbeats if a <= t < b),
                louder and piece_index == 0,
                sum(1 for t in music.beats
                    if section.start_centisecond <= t < a),
                music.beats_per_bar,
                music.bar_phase,
                sum(1 for t in music.beats if t < a),
            ))
    return windows


# ---------------------------------------------------------------- display and requirements


@dataclass
class _Constraints:
    excluded: dict[str, str] = field(default_factory=dict)
    channels: dict[str, list[int]] = field(default_factory=dict)
    caps: dict[str, int] = field(default_factory=dict)
    keep_on: dict[str, list[str] | None] = field(default_factory=dict)
    quiet: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    directions: list[tuple[set[str], str, str]] = field(default_factory=list)
    # Channels that show exactly what another channel shows: the other channels of a
    # prop that lights whole, and a second prop wired to the same circuit.
    copies: dict[tuple[str, int], list[tuple[str, int]]] = field(
        default_factory=lambda: defaultdict(list))
    # Props that only follow another prop (whole circuits shared), by the prop they
    # follow.
    followers: dict[str, str] = field(default_factory=dict)
    # Channels that stay at least this bright while the rest of their prop is lit and
    # go dark with it (a mega tree's star), by prop.
    anchors: dict[str, tuple[list[int], int]] = field(default_factory=dict)
    # Words that light props when sung, from the owner's own cue list.
    word_cues: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _named(name: str, words: list[str]) -> bool:
    found = _words(name)
    return any(_words(word) <= found for word in words)


def _constraints(display: Display, rule_set: RuleSet, vocals_known: bool) -> _Constraints:
    c = _Constraints()
    mouth_words = list({
        *rule_set.rules["face_outline_with_mouth"].params.get("mouth_names", []),
        *rule_set.rules["mouths_only_during_vocals"].params.get("mouth_names", []),
    })
    rest_words = rule_set.rules["mouths_only_during_vocals"].params.get("rest_names", [])
    for prop in display.props.values():
        if prop.linked_to is not None:
            master = display.props.get(prop.linked_to)
            c.excluded[prop.prop_id] = (
                f"driven by its master prop {master.name if master else '(missing)'}")
        elif prop.layout_problem is not None:
            c.excluded[prop.prop_id] = f"cannot be sequenced yet: {prop.layout_problem}"
        elif (prop.role == "singing_face" and _named(prop.name, mouth_words)
              and not _named(prop.name, rest_words) and not vocals_known):
            c.excluded[prop.prop_id] = (
                "no vocals for this song: pass --vocals, or install the vocals add-on")
        else:
            c.channels[prop.prop_id] = list(range(prop.channel_count))
    for req in rule_set.requirements:
        if req.severity == "off":
            continue
        chosen, _ = select_props(display, req)
        for pid in chosen:
            prop = display.props[pid]
            if req.type == "never_use":
                c.excluded[pid] = f"requirement {req.requirement_id!r}: never used"
            elif req.type == "max_intensity":
                c.caps[pid] = min(c.caps.get(pid, 100), int(req.params["max"]))
            elif req.type == "keep_on":
                during = req.params.get("during")
                c.keep_on[pid] = None if not during else list(during)
            elif req.type == "quiet_during":
                c.quiet[pid].update(s.lower() for s in req.params["sections"])
            elif req.type == "colors_only":
                allowed = {color.lower() for color in req.params["colors"]}
                if prop.color_kind == "combined_colors":
                    c.excluded[pid] = (f"requirement {req.requirement_id!r}: its colors share "
                                       "one circuit and cannot be limited")
                    continue
                keep = [i for i in c.channels.get(pid, [])
                        if prop.channel_colors[i].strip().lower() in allowed]
                if not keep:
                    c.excluded[pid] = (f"requirement {req.requirement_id!r}: it has none of "
                                       "the allowed colors")
                else:
                    c.channels[pid] = keep
            elif req.type == "light_whole":
                whole = c.channels.get(pid, [])
                if len(whole) > 1:
                    c.channels[pid] = whole[:1]
                    c.copies[(pid, whole[0])].extend((pid, ch) for ch in whole[1:])
            if req.type == "light_on_words":
                for word in req.params["words"]:
                    for token in re.findall(r"[a-z0-9']+", word.lower()):
                        c.word_cues[token].add(pid)
            if req.type == "anchor_channels":
                count = prop.channel_count
                chosen_channels = [c - 1 for c in req.params["channels"] if c - 1 < count]
                if chosen_channels and len(chosen_channels) < count:
                    c.anchors[pid] = (chosen_channels, int(req.params.get("min", ANCHOR_FLOOR)))
        if req.type == "move_direction":
            c.directions.append((set(chosen), req.params.get("movement", "chase"),
                                 req.params["direction"]))
    for pid in c.excluded:
        c.channels.pop(pid, None)
        c.keep_on.pop(pid, None)
    # One circuit drawn as two props: the prop with more channels (the mega tree whose
    # last channel is also the roofline) leads, and the other shows the same light.
    for outlet in display.shared_outlets():
        owner = max(outlet, key=lambda pc: (display.props[pc[0]].channel_count,
                                            display.props[pc[0]].name, -pc[1]))
        for pid, channel in outlet:
            if (pid, channel) == owner or pid in c.excluded:
                continue
            if channel in c.channels.get(pid, []):
                c.channels[pid].remove(channel)
            c.copies[owner].append((pid, channel))
            if not c.channels.get(pid):
                c.channels.pop(pid, None)
                c.followers[pid] = display.props[owner[0]].name
    return c


@dataclass(frozen=True, slots=True)
class _Row:
    role: str
    props: tuple[str, ...]
    direction: str


def _rows(display: Display, usable: set[str]) -> tuple[list[_Row], list[str]]:
    keyed: dict[tuple[str, str], list[DisplayProp]] = defaultdict(list)
    for prop in display.props.values():
        # Parts of a singing face share a group but are never chased like a row, and
        # snowflakes move by their own formation (see formation.py).
        if (prop.prop_id in usable and prop.position_in_row is not None
                and prop.row_id is not None and prop.role not in {"singing_face", "snowflake"}):
            keyed[(prop.role, prop.row_id)].append(prop)
    rows: list[_Row] = []
    in_rows: set[str] = set()
    for (role, _), members in sorted(keyed.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda p: p.position_in_row or 0)
        xs = [p.center[0] if p.center else None for p in ordered]
        if all(x is not None for x in xs) and all(
            b > a for a, b in itertools.pairwise(xs)  # type: ignore[operator]
        ):
            direction = "left_to_right"
        elif all(x is not None for x in xs) and all(
            b < a for a, b in itertools.pairwise(xs)  # type: ignore[operator]
        ):
            direction = "right_to_left"
        else:
            direction = "row_order"
        rows.append(_Row(role, tuple(p.prop_id for p in ordered), direction))
        in_rows.update(p.prop_id for p in ordered)
    singles = [pid for pid in display.props if pid in usable and pid not in in_rows]
    return rows, singles


# ---------------------------------------------------------------- building effects


class _Canvas:
    def __init__(self, caps: dict[str, int]) -> None:
        self.effects: dict[tuple[str, int], list[Effect]] = defaultdict(list)
        self.movements: list[Movement] = []
        self.caps = caps

    def _free(self, key: tuple[str, int], start: int, end: int) -> bool:
        return all(e.end_centisecond <= start or e.start_centisecond >= end
                   for e in self.effects[key])

    def put(self, prop_id: str, channel: int, start: int, end: int, kind: str = "on",
            intensity: int = 100, end_intensity: int | None = None,
            color: str | None = None, movement: str | None = None) -> bool:
        if end <= start:
            return False
        cap = self.caps.get(prop_id, 100)
        first = min(intensity, cap)
        last = min(intensity if end_intensity is None else end_intensity, cap)
        if kind == "fade" and first == last:
            kind = "on"
        if kind != "fade":
            last = first
        if first == 0 and last == 0:
            return False
        key = (prop_id, channel)
        if not self._free(key, start, end):
            return False
        self.effects[key].append(Effect(prop_id, channel, start, end, kind, first, last,
                                        color, movement))
        return True


def _at(effect: Effect, time: int) -> int:
    """A fade's intensity at a time inside it."""
    span = effect.end_centisecond - effect.start_centisecond
    if effect.kind != "fade" or span <= 0:
        return effect.start_intensity
    share = (time - effect.start_centisecond) / span
    return round(effect.start_intensity + (effect.end_intensity - effect.start_intensity) * share)


def _piece(effect: Effect, start: int, end: int) -> Effect:
    first, last = _at(effect, start), _at(effect, end)
    # A short piece of a fade can start and end at the same level: then it holds.
    kind = "on" if effect.kind == "fade" and first == last else effect.kind
    return Effect(effect.prop_id, effect.channel_index, start, end, kind, first, last,
                  effect.color, effect.movement_id)


# The rest of a prop counts as lit for its anchor channels from this brightness.
ANCHOR_DIM = 5


def _effect_kinds(effects: tuple[Effect, ...], movements: list[Movement]) -> str:
    """What the show is made of, in the three kinds the owner sorts effects into:
    native LOR effects, moves built from them, and anything the controllers cannot
    show (always none: every effect is one a dimmable channel plays)."""
    kinds: dict[str, int] = defaultdict(int)
    for e in effects:
        kinds[{"on": "intensity", "fade": "fade"}.get(e.kind, e.kind)] += 1
    native = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
    moves: dict[str, int] = defaultdict(int)
    for m in movements:
        moves[m.kind] += 1
    built = ", ".join(f"{count} {kind}{'s' if count != 1 else ''}"
                      for kind, count in sorted(moves.items())) or "none"
    return (f"Effects: native LOR effects ({native}); moves built from them ({built}); "
            "nothing the controllers cannot show.")


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _anchor(canvas: _Canvas, pid: str, count: int, anchors: list[int], floor: int) -> None:
    """Anchor channels light only while the rest of the prop is lit, and then at
    ``floor`` or more: a mega tree's star never shows alone, and never drops out of a
    tree that is moving."""
    rest = [e for c in range(count) if c not in anchors
            for e in canvas.effects.get((pid, c), [])]

    def shown(e: Effect) -> tuple[int, int]:
        # A fade to or from dark shows next to nothing for its last (or first)
        # moments: the anchor follows only while the rest is at ANCHOR_DIM or more.
        span = e.end_centisecond - e.start_centisecond
        a, b = e.start_centisecond, e.end_centisecond
        if e.kind == "fade" and e.end_intensity < ANCHOR_DIM <= e.start_intensity:
            b -= -(-span * (ANCHOR_DIM - e.end_intensity)
                   // (e.start_intensity - e.end_intensity))
        if e.kind == "fade" and e.start_intensity < ANCHOR_DIM <= e.end_intensity:
            a += -(-span * (ANCHOR_DIM - e.start_intensity)
                   // (e.end_intensity - e.start_intensity))
        return a, b

    lit = _merge_spans([s for e in rest if max(e.start_intensity, e.end_intensity) >= ANCHOR_DIM
                        for s in [shown(e)] if s[0] < s[1]])
    for channel in anchors:
        key = (pid, channel)
        own = canvas.effects.get(key, [])
        kept: list[Effect] = []
        for a, b in lit:
            marks = sorted({a, b} | {t for e in own for t in (e.start_centisecond, e.end_centisecond)
                              if a < t < b})
            for x, y in itertools.pairwise(marks):
                mine = next((e for e in own if e.start_centisecond <= x
                             and y <= e.end_centisecond), None)
                first = max(_at(mine, x) if mine else 0, floor)
                last = max(_at(mine, y) if mine else 0, floor)
                kept.append(Effect(pid, channel, x, y, "on" if first == last else "fade",
                                   first, last, mine.color if mine else None, None))
        canvas.effects[key] = sorted(kept, key=lambda e: e.start_centisecond)


def _punch(canvas: _Canvas, prop_id: str, channel: int, start: int, end: int,
           color: str | None, dip: int = 0, fade: bool = True) -> bool:
    """Flash over whatever this channel is doing, cutting a gap for it.

    Steps of a chase or fill are never cut: a movement must finish as planned. With
    ``dip``, a channel lit just before goes dark for that long first, so the flash
    reads as a hit even on a light that was already on.
    """
    key = (prop_id, channel)
    current = canvas.effects[key]
    if dip and any(e.start_centisecond < start <= e.end_centisecond
                   and e.movement_id is None for e in current):
        start_cut = max(0, start - dip)
        if not any(e.movement_id is not None and e.start_centisecond < start
                   and start_cut < e.end_centisecond for e in current):
            current = [p for e in current for p in (
                [e] if e.end_centisecond <= start_cut or e.start_centisecond >= start else
                ([_piece(e, e.start_centisecond, start_cut)]
                 if e.start_centisecond < start_cut else [])
                + ([_piece(e, start, e.end_centisecond)] if start < e.end_centisecond else []))]
            canvas.effects[key] = current
    overlapping = [e for e in current
                   if e.start_centisecond < end and start < e.end_centisecond]
    if any(e.movement_id is not None for e in overlapping):
        return False
    cap = canvas.caps.get(prop_id, 100)
    if cap <= 0:
        return False
    kept = [e for e in current if e not in overlapping]
    for e in overlapping:
        if e.start_centisecond < start:
            kept.append(_piece(e, e.start_centisecond, start))
        if end < e.end_centisecond:
            kept.append(_piece(e, end, e.end_centisecond))
    kept.append(Effect(prop_id, channel, start, end, "fade", cap, 0, color, None) if fade
                else Effect(prop_id, channel, start, end, "on", cap, cap, color, None))
    canvas.effects[key] = sorted(kept, key=lambda e: e.start_centisecond)
    return True


def _swell(canvas: _Canvas, start: int, end: int, low: float = 0.5,
           exclude: set[str] | None = None) -> None:
    """Scale brightness from ``low`` at ``start`` up to full at ``end``: a build-up."""
    span = max(1, end - start)
    _scale(canvas, start, end,
           lambda time: low + (1 - low) * min(1.0, max(0.0, (time - start) / span)), exclude)


def _dim(canvas: _Canvas, start: int, end: int, level: float, exclude: set[str]) -> None:
    """Hold everything (but ``exclude``) at ``level`` of its brightness for a moment."""
    _scale(canvas, start, end, lambda _: level, exclude)


def _scale(canvas: _Canvas, start: int, end: int, factor: Callable[[int], float],
           exclude: set[str] | None = None) -> None:
    """Multiply brightness between ``start`` and ``end`` by ``factor(time)``."""
    for key, effects in canvas.effects.items():
        if exclude and key[0] in exclude:
            continue
        out: list[Effect] = []
        for e in effects:
            if e.end_centisecond <= start or e.start_centisecond >= end:
                out.append(e)
                continue
            pieces = []
            a, b = max(start, e.start_centisecond), min(end, e.end_centisecond)
            if e.start_centisecond < a:
                pieces.append(_piece(e, e.start_centisecond, a))
            middle = _piece(e, a, b)
            first = max(1, round(middle.start_intensity * factor(a))) \
                if middle.start_intensity else 0
            last = max(1, round(middle.end_intensity * factor(b))) if middle.end_intensity else 0
            kind = middle.kind
            if kind == "on" and first != last:
                kind = "fade"
            elif kind == "fade" and first == last:
                kind = "on"
            if kind in {"twinkle", "shimmer"}:
                last = first
            pieces.append(Effect(e.prop_id, e.channel_index, a, b, kind, first, last,
                                 e.color, e.movement_id))
            if b < e.end_centisecond:
                pieces.append(_piece(e, b, e.end_centisecond))
            out.extend(pieces)
        canvas.effects[key] = out


def _darken(canvas: _Canvas, start: int, end: int, keep: set[str]) -> None:
    """Clear a moment: effects that would light between ``start`` and ``end`` are cut
    short, except on props in ``keep`` and steps of a movement (which must finish)."""
    for key, effects in canvas.effects.items():
        if key[0] in keep:
            continue
        out: list[Effect] = []
        for e in effects:
            if e.end_centisecond <= start or e.start_centisecond >= end or e.movement_id:
                out.append(e)
                continue
            if e.start_centisecond < start:
                out.append(_piece(e, e.start_centisecond, start))
            if end < e.end_centisecond:
                out.append(_piece(e, end, e.end_centisecond))
        canvas.effects[key] = out


def _beat_length(window: _Window, index: int) -> int:
    beats = window.beats
    if index + 1 < len(beats):
        return beats[index + 1] - beats[index]
    if len(beats) >= 2:
        return min(beats[-1] - beats[-2], window.end - beats[index])
    return window.end - beats[index]


def _bars(window: _Window) -> list[tuple[int, int]]:
    # When a stop splits a bar, a window may contain zero or one detected
    # downbeat. Reconstruct the bar grid from the global beat phase, not from
    # the first beat after the stop (and never assume 4/4).
    if len(window.downbeats) >= 2:
        marks = list(window.downbeats)
    else:
        first = (window.bar_phase - window.bar_offset) % window.beats_per_bar
        marks = list(window.beats[first::window.beats_per_bar])
    bars = [(a, b) for a, b in itertools.pairwise(marks)]
    if marks and window.end - marks[-1] >= 50:
        typical = bars[-1][1] - bars[-1][0] if bars else window.end - marks[-1]
        bars.append((marks[-1], min(window.end, marks[-1] + typical)))
    return bars


def _sub(window: _Window, a: int, b: int) -> _Window:
    """The part of a window from ``a`` to ``b``, keeping its beat and bar footing."""
    before = sum(1 for t in window.beats if t < a)
    return _Window(window.section_index, a, b,
                   tuple(t for t in window.beats if a <= t < b),
                   tuple(t for t in window.downbeats if a <= t < b), False,
                   window.offset + before, window.beats_per_bar, window.bar_phase,
                   window.bar_offset + before)


def _marks(window: _Window, grid: str) -> list[int]:
    """The times a motion moves on: once a phrase, each bar, every other beat, each
    beat, or each half beat."""
    if grid == "phrase":
        return [window.start]
    if grid == "bar":
        marks = [a for a, _ in _bars(window)]
        return marks or [window.start]
    if grid == "half_bar":
        return [t for i, t in enumerate(window.beats) if (i + window.offset) % 2 == 0]
    if grid == "half":
        out: list[int] = []
        for b, beat in enumerate(window.beats):
            out.extend((beat, beat + _beat_length(window, b) // 2))
        return out
    if grid == "sixteenth":
        fours: list[int] = []
        for b, beat in enumerate(window.beats):
            length = _beat_length(window, b)
            fours.extend(beat + length * k // 4 for k in range(4))
        return [t for t in fours if t < window.end]
    return list(window.beats)


def _spans(window: _Window, marks: list[int]) -> list[tuple[int, int]]:
    """Each mark to the next (the last one to the end of the window)."""
    marks = [m for m in marks if window.start <= m < window.end]
    if not marks:
        return []
    return [(a, b) for a, b in zip(marks, [*marks[1:], window.end], strict=True) if b - a >= 5]


@dataclass
class _Planner:
    display: Display
    constraints: _Constraints
    sections: list[PlannedSection]
    canvas: _Canvas
    movement_counter: int = 0
    # Mid-energy sections hit hard; quiet and loud ones flare and decay. Mixing the
    # two is what keeps a show from feeling all-flash or all-fade.
    soft: bool = True
    style: Style = field(default_factory=lambda: get_style(None))
    turns: dict[frozenset[str], int] = field(default_factory=dict)
    # How the snowflakes stand in the preview, and so how they move.
    snow: Formation = field(default_factory=lambda: Formation("single", (), (), ("chase",
                                                                                "left_to_right")))
    fall_turn: int = 0
    # The song's last loud part: props taking turns hold longer, so it is the fullest.
    peak: bool = False
    # Drum hits from the analysis (centiseconds), for motions on the kick or snare.
    kicks: list[int] = field(default_factory=list)
    snares: list[int] = field(default_factory=list)

    def marks(self, window: _Window, grid: str) -> list[int]:
        """The times a motion moves on; the drums when the style asks and the song has
        them (at least a hit a bar in this phrase), otherwise the beat they stand for."""
        if grid in {"kick", "snare"}:
            hits = [t for t in (self.kicks if grid == "kick" else self.snares)
                    if window.start <= t < window.end]
            if len(hits) >= max(2, len(_bars(window))):
                return hits
            if grid == "snare":
                # The backbeat: beats two and four.
                return [t for i, t in enumerate(window.beats)
                        if (i + window.offset) % 2 == 1]
            return list(window.beats)
        return _marks(window, grid)

    def channels(self, pid: str, section_index: int) -> list[int]:
        """Channels to light: all of them, or one color at a time for per-color props."""
        prop = self.display.props[pid]
        allowed = self.constraints.channels[pid]
        if prop.color_kind == "color_per_channel" and len(allowed) > 1:
            return [allowed[section_index % len(allowed)]]
        return allowed

    def color(self, pid: str, channel: int) -> str | None:
        prop = self.display.props[pid]
        if prop.color_kind == "color_per_channel":
            return prop.channel_colors[channel] or None
        return None

    def light(self, pid: str, section_index: int, start: int, end: int, kind: str = "on",
              intensity: int = 100, end_intensity: int | None = None,
              movement: str | None = None, sweep: str | None = None) -> bool:
        """Light a prop. ``sweep`` ("forward" or "back") staggers a multi-segment prop's
        segments so the light wipes across it instead of switching on all at once."""
        channels = self.channels(pid, section_index)
        step = 0
        if sweep is not None and len(channels) > 1:
            step = min(SWEEP_STEP, (end - start) // (2 * len(channels)))
            if sweep == "back":
                channels = list(reversed(channels))
        placed = False
        for index, ch in enumerate(channels):
            placed |= self.canvas.put(pid, ch, start + index * step, end, kind, intensity,
                                      end_intensity, self.color(pid, ch), movement)
        return placed

    def direction_for(self, row: _Row, kind: str) -> tuple[tuple[str, ...], str]:
        props, natural = row.props, row.direction
        for chosen, movement_kind, required in self.constraints.directions:
            if movement_kind == kind and set(props) <= chosen:
                if required == natural:
                    return props, natural
                if required == _OPPOSITE.get(natural):
                    return tuple(reversed(props)), required
                raise _CannotHonor(required)
        # Each new chase or fill on this row runs the other way from the last one.
        key = frozenset(props)
        turn = self.turns.get(key, 0)
        self.turns[key] = turn + 1
        if turn % 2 == 1:
            return tuple(reversed(props)), _OPPOSITE[natural]
        return props, natural

    def movement(self, kind: str, props: tuple[str, ...], direction: str, start: int,
                 end: int) -> str:
        self.movement_counter += 1
        movement_id = f"{kind}-{self.movement_counter}"
        self.canvas.movements.append(Movement(movement_id, kind, props, direction, start, end))
        return movement_id

    # -- row looks

    def chase(self, row: _Row, props: list[str], window: _Window, every: int,
              intensity: int, hold: int = 1) -> bool:
        """One prop per beat (or every other beat) across the row. ``hold`` keeps each
        prop lit for that many steps, so in loud parts the chase is fuller."""
        try:
            order, direction = self.direction_for(_Row(row.role, tuple(props), row.direction),
                                                  "chase")
        except _CannotHonor:
            return False
        beats = window.beats
        n = len(order)
        # Start where a full cycle would have started had the window begun earlier.
        index = (-window.offset) % (n * every)
        placed = False
        while index + (n - 1) * every < len(beats):
            steps = [index + i * every for i in range(n)]
            end = beats[steps[-1]] + _beat_length(window, steps[-1])
            start = beats[steps[0]]
            if end > window.end:
                break
            movement_id = self.movement("chase", order, direction, start, end)
            wipe = _sweep_for(direction)
            for pid, step in zip(order, steps, strict=True):
                length = _beat_length(window, step) * every * hold
                stop = min(beats[step] + length, end)
                # Each step flares and decays, leaving a short tail behind the chase.
                self.light(pid, window.section_index, beats[step], stop,
                           "fade" if self.soft or every > 1 else "on", intensity,
                           0 if every > 1 else TAIL, movement_id, sweep=wipe)
            placed = True
            index += n * every
        return placed

    def fill(self, row: _Row, props: list[str], window: _Window) -> bool:
        try:
            order, direction = self.direction_for(_Row(row.role, tuple(props), row.direction),
                                                  "fill")
        except _CannotHonor:
            return False
        placed = False
        for bar_start, bar_end in _bars(window):
            step = (bar_end - bar_start) // len(order)
            if step < 5:
                continue
            movement_id = self.movement("fill", order, direction, bar_start, bar_end)
            wipe = _sweep_for(direction)
            for i, pid in enumerate(order):
                self.light(pid, window.section_index, bar_start + i * step, bar_end,
                           movement=movement_id, sweep=wipe)
            placed = True
        return placed

    def steady(self, pid: str, window: _Window, intensity: int, kind: str = "on") -> None:
        self.light(pid, window.section_index, window.start, window.end, kind, intensity)

    def base(self, pid: str, window: _Window, intensity: int) -> None:
        """A base that stays lit but never sits still: each bar hits brighter on the
        downbeat, decays back over a beat, and holds."""
        top = min(100, intensity + 40)
        bars = [t for t in window.downbeats if window.start <= t < window.end - 10]
        cursor = window.start
        si = window.section_index
        for k, t in enumerate(bars):
            if t > cursor:
                self.light(pid, si, cursor, t, "on", intensity)
            end = bars[k + 1] if k + 1 < len(bars) else window.end
            beat = next((b for b in window.beats if b > t), end) - t
            flash = min(end, t + max(5, beat // 4))
            settle = min(end, t + max(10, beat))
            self.light(pid, si, t, flash, "on", top)
            if settle > flash:
                self.light(pid, si, flash, settle, "fade", top, intensity)
            if end > settle:
                self.light(pid, si, settle, end, "on", intensity)
            cursor = end
        if cursor < window.end:
            self.light(pid, si, cursor, window.end, "on", intensity)

    def fall(self, members: list[str], section_index: int, start: int, intensity: int,
             limit: int, motion: tuple[str, str] = ("fall", "top_to_bottom")) -> bool:
        """Light a line of props one after another (a column from the top down, or a
        row or cluster across): each holds, then fades out.

        The whole line is placed or none of it, so the movement always finishes.
        """
        step, hold, decay = self.style.fall
        spans = []
        for i, pid in enumerate(members):
            on = start + i * step
            spans.append((pid, on, on + hold, on + hold + decay))
        end = spans[-1][3]
        if end > limit:
            return False
        for pid, on, _, off in spans:
            for channel in self.channels(pid, section_index):
                if not self.canvas._free((pid, channel), on, off):
                    return False
        movement = (self.movement(motion[0], tuple(members), motion[1], start, end)
                    if len(members) > 1 else None)
        for pid, on, held, off in spans:
            self.light(pid, section_index, on, held, "on", intensity, movement=movement)
            self.light(pid, section_index, held, off, "fade", intensity, 0, movement=movement)
        return True

    def falls(self, window: _Window, columns: list[list[str]], times: list[int],
              intensity: int, reverse: bool = False,
              motion: tuple[str, str] = ("fall", "top_to_bottom"),
              bursts: list[str] | None = None) -> None:
        """At each time one line moves (a column falls, or a row or cluster ripples
        across); the lines take turns across the yard and back. Multi-segment props
        in ``bursts`` take their turn too, opening out segment by segment."""
        lines: list[list[str]] = [list(c) for c in columns if c]
        if motion[0] == "chase" and reverse:
            # Ripples alternate direction, like chases do.
            lines = [list(reversed(line)) for line in lines]
            motion = ("chase", "right_to_left" if motion[1] == "left_to_right"
                      else "left_to_right")
        turns: list[tuple[str, list[str]]] = [("line", line) for line in lines]
        turns += [("burst", [pid]) for pid in bursts or []]
        if not turns:
            return
        order = list(range(len(turns)))
        if reverse:
            order.reverse()
        cycle = order + order[-2:0:-1] if len(order) > 2 else order
        for time in times:
            kind, members = turns[cycle[self.fall_turn % len(cycle)]]
            placed = (self.burst(members[0], window.section_index, time, intensity, window.end)
                      if kind == "burst" else
                      self.fall(members, window.section_index, time, intensity, window.end,
                                motion))
            if placed:
                self.fall_turn += 1

    def burst(self, pid: str, section_index: int, start: int, intensity: int,
              limit: int) -> bool:
        """Open a multi-segment prop out segment by segment, in its channel order."""
        channels = self.channels(pid, section_index)
        step, hold, decay = self.style.fall
        spans = [(ch, start + i * step) for i, ch in enumerate(channels)]
        end = spans[-1][1] + hold + decay
        if end > limit or not all(self.canvas._free((pid, ch), on, on + hold + decay)
                                  for ch, on in spans):
            return False
        for ch, on in spans:
            color = self.color(pid, ch)
            self.canvas.put(pid, ch, on, on + hold, "on", intensity, color=color)
            self.canvas.put(pid, ch, on + hold, on + hold + decay, "fade", intensity, 0, color)
        return True

    def turn(self, pid: str, window: _Window, marks: list[int], intensity: int,
             reverse: bool = False) -> None:
        """Step through a multi-segment prop's channels, one step per mark, like a
        spinning tree; each segment overlaps the next."""
        allowed = list(self.constraints.channels[pid])
        if reverse:
            allowed.reverse()
        count = len(allowed)
        times = [m for m in marks if window.start <= m < window.end] + [window.end]
        width = min(self.style.spin_width, count - 1) if count >= 4 else 1
        first = window.offset
        for k in range(len(times) - 1):
            channel = allowed[(k + first) % count]
            end = times[min(k + width, len(times) - 1)]
            if end > times[k]:
                self.canvas.put(pid, channel, times[k], end, "on", intensity,
                                color=self.color(pid, channel))

    def hits(self, pid: str, window: _Window, spans: list[tuple[int, int]], intensity: int,
             every: int = 1, phase: int = 0, hold: int = 1) -> None:
        """Light on every ``every``-th span starting at ``phase``, holding ``hold`` spans,
        and fade (or cut) at the end."""
        for k in range(len(spans)):
            if (k - phase) % every:
                continue
            start = spans[k][0]
            end = spans[min(len(spans) - 1, k + hold - 1)][1]
            length = end - start
            # A soft hit decays before the next one, except in loud parts, which stay
            # full.
            loud = self.sections[window.section_index].level == HIGH
            stop = start + max(5, length * 3 // 4) if self.soft and not loud else end
            self.light(pid, window.section_index, start, min(window.end, stop),
                       "fade" if self.soft else "on", intensity, 0 if self.soft else None)

    def trade(self, members: list[str], window: _Window, spans: list[tuple[int, int]],
              intensity: int) -> None:
        """Look-alike props take turns, in order across the yard: each answers the one
        before it, so no two of them ever light at the same moments."""
        n = len(members)
        # In loud parts each prop holds longer, so more of the family is lit at once.
        level = self.sections[window.section_index].level
        hold = max(1, n // 2 + (1 if level == HIGH and n > 2 else 0) + (1 if self.peak else 0))
        hold = min(hold, n - 1) if n > 1 else hold
        for i, pid in enumerate(members):
            self.hits(pid, window, spans, intensity, every=n, phase=i, hold=hold)

    def breathe(self, members: list[str], window: _Window, spans: list[tuple[int, int]],
                intensity: int) -> None:
        """Each prop swells up and back down once per span; the props of a family start
        one after another, so the light rolls through them."""
        n = len(members)
        beats = list(window.beats)
        grid = sorted({*beats, *((x + y) // 2 for x, y in itertools.pairwise(beats))})
        for a, b in spans:
            length = b - a
            if length < 20:
                continue
            # Each prop joins the roll on the nearest beat or half beat, so the roll
            # moves with the music rather than between its notes.
            inside = [t for t in grid if a <= t < b - 10]
            for i, pid in enumerate(members):
                start = a + (length * i) // (2 * n) if n > 1 else a
                if inside:
                    wanted = start
                    start = min(inside, key=lambda t: (abs(t - wanted), t))
                # A family breathing as one swells over the whole span; in a roll
                # each prop swells for half of it, so part of the row is always
                # resting and the light visibly travels.
                end = b if n == 1 else min(b, start + max(20, length // 2))
                peak = start + max(5, (end - start) // 2)
                self.light(pid, window.section_index, start, peak, "fade",
                           max(1, intensity // 5), intensity)
                self.light(pid, window.section_index, peak, end, "fade", intensity, 0)

    def wave(self, row: _Row, members: list[str], window: _Window,
             spans: list[tuple[int, int]], intensity: int) -> bool:
        """A swell that travels along the row once per span."""
        try:
            order, _ = self.direction_for(_Row(row.role, tuple(members), row.direction),
                                          "chase")
        except _CannotHonor:
            return False
        self.breathe(list(order), window, spans, intensity)
        return bool(spans)

    def bounce(self, row: _Row, members: list[str], window: _Window, every: int,
               intensity: int, hold: int) -> bool:
        """A chase that runs across the row and back, turning round every bar."""
        moved = False
        for a, b in _bars(window):
            moved |= self.chase(row, members, _sub(window, a, min(b, window.end)),
                                every=every, intensity=intensity, hold=hold)
        return moved

    def fill_up(self, pid: str, window: _Window, spans: list[tuple[int, int]],
                intensity: int) -> None:
        """A multi-segment prop fills up across each span, a step on each sixteenth note
        (several segments a step on a short span), then clears."""
        channels = list(self.constraints.channels[pid])
        # Each segment steps on at least a sixteenth note, so the fill moves with the
        # music instead of flickering up in a few hundredths of a second.
        gaps = [y - x for x, y in itertools.pairwise(window.beats)]
        sixteenth = max(3, (sorted(gaps)[len(gaps) // 2] if gaps else 50) // 4)
        count = max(1, len(channels))
        for a, b in spans:
            # As many steps as the span has sixteenth notes (at most one per segment):
            # a tall tree fills a few segments at a time on a short span.
            steps = min(count, (b - a) // sixteenth)
            if steps < 2:
                continue
            step = (b - a) // steps
            for i, ch in enumerate(channels):
                self.canvas.put(pid, ch, a + (i * steps // count) * step, b, "on", intensity,
                                color=self.color(pid, ch))


class _CannotHonor(Exception):
    pass


# A multi-segment prop's segments start this far apart (centiseconds) in a wipe;
# hand-made shows wipe an arch quickly, so the hit still lands on the beat.
SWEEP_STEP = 4
# A falling column: each snowflake starts this long after the one above it,
# holds, then fades out (centiseconds).
FALL_STEP = 12
FALL_HOLD = 20
FALL_DECAY = 25
# Chase steps and alternating hits fade to this level rather than cutting off.
TAIL = 20


def _sweep_for(direction: str) -> str:
    return "back" if direction in {"right_to_left", "reverse_row_order"} else "forward"


def _look(planner: _Planner, window: _Window, rows: list[_Row], singles: list[str],
          active: set[str], variant: int, flip: bool) -> None:
    """One phrase of one section: each kind of prop plays the part the style gives it.

    The style chooses what each kind of prop does at this energy level and the
    musical grid it moves on (phrase, bar, every other beat, beat or half beat).
    Look-alike props never share one timeline: rows chase or take turns in order,
    and loose families (decorations, homemade trees, outlines) trade, breathe one
    after another, or ripple. ``variant`` picks the style's alternative for a part
    that comes back; ``flip`` turns spins and chases the other way.
    """
    level = planner.sections[window.section_index].level
    style = planner.style
    planner.soft = style.soft[level]
    gentle = style.brightness[level]
    hold = style.chase_hold[level]

    def every_for(grid: str) -> int:
        return {"half": 1, "sixteenth": 1, "beat": 1, "half_bar": 2, "kick": 1,
                "snare": 1}.get(
            grid, window.beats_per_bar)

    loose = list(singles)
    for row in rows:
        members = [pid for pid in row.props if pid in active]
        if not members:
            continue
        if len(members) == 1:
            loose.append(members[0])
            continue
        kind = {"arch": "arch_row", "outline": "outline_row"}.get(row.role, "row")
        motion, grid = style.part(kind).at(level, variant)
        marks = planner.marks(window, grid)
        spans = _spans(window, marks)
        # A chase on the half beat, the sixteenth or the drums steps on those, as if they
        # were beats.
        if grid in {"half", "sixteenth"}:
            stepping = dataclasses.replace(window, beats=tuple(marks),
                                           offset=window.offset * (2 if grid == "half" else 4))
        elif grid in {"kick", "snare"} and tuple(marks) != window.beats:
            stepping = dataclasses.replace(window, beats=tuple(marks), offset=0)
        else:
            stepping = window
        if motion == "chase":
            moved = planner.chase(row, members, stepping, every=every_for(grid),
                                  intensity=gentle, hold=hold)
        elif motion == "bounce":
            moved = planner.bounce(row, members, stepping, every_for(grid), gentle, hold)
        elif motion == "fill":
            moved = planner.fill(row, members, window)
        elif motion == "wave":
            moved = planner.wave(row, members, window, spans, gentle)
        else:
            planner.trade(members, window, spans, gentle)
            moved = True
        if not moved:
            # A required direction the row cannot run: its props take turns instead.
            planner.trade(members, window, _spans(window, list(window.beats)), gentle)

    snow = planner.snow
    columns = [[p for p in line if p in active] for line in snow.lines]
    in_columns = {p for line in snow.lines for p in line}
    bursts = [p for p in snow.loose if p in active and _multi_segment(planner, p)]
    families: dict[str, list[str]] = defaultdict(list)
    for pid in loose:
        if pid not in active or pid in in_columns:
            continue
        prop = planner.display.props[pid]
        channels = len(planner.constraints.channels[pid])
        multi = channels >= 3 and prop.color_kind != "color_per_channel"
        if prop.role == "mega_tree" or (multi and prop.role in {"icicles", "outline"}):
            motion, grid = style.part("mega_tree").at(level, variant)
            intensity = 60 if level == LOW else 100
            if motion == "rotate":
                planner.turn(pid, window, planner.marks(window, grid), intensity, reverse=flip)
            elif motion == "spiral":
                for k, (a, b) in enumerate(_bars(window)):
                    part = _sub(window, a, min(b, window.end))
                    planner.turn(pid, part, planner.marks(part, grid), intensity,
                                 reverse=(k % 2 == 1) != flip)
            elif motion == "fill_up":
                planner.fill_up(pid, window, _spans(window, planner.marks(window, grid)),
                                intensity)
            elif motion == "breathe":
                planner.breathe([pid], window, _spans(window, planner.marks(window, grid)),
                                intensity)
            else:
                planner.steady(pid, window, intensity, "twinkle")
        elif prop.role == "star":
            motion, _ = style.part("star").at(level, variant)
            if motion == "base":
                planner.base(pid, window, 60)
            else:
                planner.steady(pid, window, 100, "twinkle" if motion == "twinkle" else "on")
        elif prop.role == "singing_face":
            if level >= MID:
                planner.steady(pid, window, 100)
        elif prop.role == "snowflake":
            # A snowflake outside the formation: a multi-segment one opens out with the
            # others (below); a simple one twinkles.
            if pid not in bursts:
                # Loose snowflakes take turns like any family of look-alikes.
                families["snowflake"].append(pid)
        else:
            families[prop.role].append(pid)

    def across(pid: str) -> tuple[float, str]:
        center = planner.display.props[pid].center
        return (center[0] if center else 0.0, pid)

    for role, members in sorted(families.items()):
        members.sort(key=across)
        if flip:
            members.reverse()
        kind = "outline" if role == "outline" else "family"
        motion, grid = style.part(kind).at(level, variant)
        spans = _spans(window, planner.marks(window, grid))
        intensity = gentle if role != "unknown" else max(30, gentle - 10)
        if motion == "base":
            for pid in members:
                planner.base(pid, window, {LOW: 30, MID: 50, HIGH: 70}[level])
        elif motion == "twinkle":
            for pid in members:
                planner.steady(pid, window, {LOW: 40, MID: 60, HIGH: 80}[level], "twinkle")
        elif motion == "breathe":
            planner.breathe(members, window, spans, intensity)
        elif motion == "trade" and len(members) > 1:
            planner.trade(members, window, spans, intensity)
        else:
            # Pulse: each hit ripples through the family in order across the yard, a
            # sixteenth note apart; in a big family the next four answer every other
            # hit, so no two of them ever share a timeline.
            gaps = [y - x for x, y in itertools.pairwise(window.beats)]
            sixteenth = max(5, (sorted(gaps)[len(gaps) // 2] if gaps else 50) // 4)
            ranks = (_mirror_ranks(planner, members) if style.mirror and flip
                     else list(range(len(members))))
            for i, pid in zip(ranks, members, strict=True):
                shifted = [(min(b - 5, a + (i % 4) * sixteenth), b) for a, b in spans]
                if i < 4:
                    planner.hits(pid, window, shifted, intensity)
                else:
                    planner.hits(pid, window, shifted, intensity, every=2,
                                 phase=(i // 4 + i) % 2)
    columns = [c for c in columns if c]
    if columns or bursts:
        step = style.fall_every[level]
        if step == 0:
            times = [a for a, _ in _bars(window)]
        else:
            times = list(window.beats[(-window.offset) % step::step])
        planner.falls(window, columns, times, gentle, reverse=flip, motion=snow.movement,
                      bursts=bursts)


def _snow_bed(planner: _Planner, window: _Window, here: set[str],
              dark: list[tuple[int, int]]) -> None:
    """While the snowflakes are not leading, they keep falling gently in the
    background, one column after another on the style's beat."""
    every = planner.style.snow_every
    columns = [[p for p in line if p in here] for line in planner.snow.lines]
    columns = [c for c in columns if c]
    if every <= 0 or not columns or len(window.beats) < 2:
        return
    level = planner.sections[window.section_index].level
    if level < min(planner.style.beds_from, MID):
        return
    gaps = [y - x for x, y in itertools.pairwise(window.beats)]
    step = max(10, round(every * sorted(gaps)[len(gaps) // 2]))
    # Below the style's bed level the snow falls at half the pace.
    if level < planner.style.beds_from:
        step *= 2
    times = [t for t in range(window.beats[0], window.end - 10, step)
             if not any(a <= t < b for a, b in dark)]
    intensity = max(30, planner.style.brightness[level] * 7 // 10)
    planner.falls(window, columns, times, intensity, motion=planner.snow.movement)


def _multi_segment(planner: _Planner, pid: str) -> bool:
    prop = planner.display.props[pid]
    return (len(planner.constraints.channels[pid]) >= 2
            and prop.color_kind != "color_per_channel")



# ---------------------------------------------------------------- focus and handoffs

# Always-on base layer the leads play against. A face that is not singing holds
# with the base rather than taking a turn as a lead.
BASE_ROLES = frozenset({"star", "outline", "singing_face"})
# How many groups lead at once, by energy level; the finale uses every group.
LEADS = {LOW: 2, MID: 2, HIGH: 3}
# The centerpiece keeps playing through mid and loud parts instead of taking turns.
CENTERPIECE_ROLES = frozenset({"mega_tree"})
# The final fade-out lasts at most this long (centiseconds).
CLOSING_LENGTH = 400
# Parts that happen once and never repeat their look.
ONE_OFF_LABELS = frozenset({"intro", "outro", "finale"})
# Crash flash spacing and length, and how many high hits per beat make snowflakes
# fall on them, come from the show's style (style.py).
SPARKLE_LENGTH = 30
SPARKLE_SPACING = 40


@dataclass(frozen=True, slots=True)
class _Group:
    role: str
    props: tuple[str, ...]
    x: float


def _groups(display: Display, rows: list[_Row], singles: list[str]) -> list[_Group]:
    """Groups that take turns leading, ordered left to right across the yard."""
    groups: list[_Group] = []

    def center(props: list[str]) -> float:
        xs = [c[0] for c in (display.props[p].center for p in props) if c is not None]
        return sum(xs) / len(xs) if xs else 0.0

    for row in rows:
        groups.append(_Group(row.role, row.props, center(list(row.props))))
    by_role: dict[str, list[str]] = defaultdict(list)
    for pid in singles:
        role = display.props[pid].role
        if role in BASE_ROLES:
            continue
        if role == "mega_tree":
            groups.append(_Group(role, (pid,), center([pid])))
        else:
            by_role[role].append(pid)
    for role, props in sorted(by_role.items()):
        groups.append(_Group(role, tuple(props), center(props)))
    return sorted(groups, key=lambda g: (g.x, g.role))


def _lead_groups(groups: list[_Group], turn: int, level: int, everything: bool,
                 skip: _Group | None, extra: int = 0,
                 leads: tuple[int, int, int] | None = None) -> list[_Group]:
    candidates = [g for g in groups if g is not skip
                  and (g.role not in CENTERPIECE_ROLES or level == LOW)]
    if not candidates:
        return []
    if everything:
        return candidates
    count = min(len(candidates), (leads or (LEADS[LOW], LEADS[MID], LEADS[HIGH]))[level] + extra)
    start = turn % len(candidates)
    chosen = [candidates[(start + i) % len(candidates)] for i in range(count)]
    # Left to right, so a call comes from the left and the answer from the right.
    return sorted(chosen, key=lambda g: (g.x, g.role))


def _leads(groups: list[_Group], turn: int, level: int, everything: bool,
           skip: _Group | None, extra: int = 0,
           leads: tuple[int, int, int] | None = None) -> set[str]:
    return {p for g in _lead_groups(groups, turn, level, everything, skip, extra, leads)
            for p in g.props}


def _sparkle_group(groups: list[_Group]) -> _Group | None:
    for role in ("snowflake", "decor"):
        for group in groups:
            if group.role == role and len(group.props) >= 2:
                return group
    return None


def _hits_in(hits: list[int], window: _Window) -> list[int]:
    return [h for h in hits if window.start <= h < window.end]


def _sparkle(planner: _Planner, window: _Window, props: list[str], hits: list[int]) -> None:
    """Answer high-pitched hits: snowflake columns fall on them, taking turns, while
    other snowflakes twinkle; without columns, sparkle props flash a few at a time
    and fade."""
    if not props:
        return
    snow = planner.snow
    columns = [[p for p in line if p in props] for line in snow.lines]
    columns = [c for c in columns if c]
    bursts = [p for p in snow.loose if p in props and _multi_segment(planner, p)]
    if columns or bursts:
        # One fall per hit, but never closer together than a column takes to start
        # falling, so each fall reads.
        gaps = [y - x for x, y in itertools.pairwise(window.beats)]
        beat = sorted(gaps)[len(gaps) // 2] if gaps else 50
        spacing = max(SPARKLE_SPACING, round(planner.style.sparkle_every * beat))
        spaced: list[int] = []
        for hit in hits:
            if not spaced or hit - spaced[-1] >= spacing:
                spaced.append(hit)
        level = planner.sections[window.section_index].level
        planner.falls(window, columns, spaced, {LOW: 60, MID: 85, HIGH: 100}[level],
                      motion=snow.movement, bursts=bursts)
        # Other snowflakes glitter underneath, taking turns bar by bar.
        others = [pid for pid in props
                  if not any(pid in c for c in columns) and pid not in bursts]
        if len(others) > 1:
            planner.trade(others, window, _spans(window, [a for a, _ in _bars(window)]), 60)
        for pid in others[:1] if len(others) == 1 else []:
            planner.steady(pid, window, 60, "twinkle")
        return
    share = max(1, len(props) // 3)
    for index, hit in enumerate(hits):
        following = hits[index + 1] if index + 1 < len(hits) else window.end
        end = min(window.end, hit + SPARKLE_LENGTH, following)
        if end - hit < 3:
            continue
        for k in range(share):
            pid = props[(index * share + k) % len(props)]
            planner.light(pid, window.section_index, hit, end, "fade", 100, 0)

BARS_PER_PHRASE = 4
def _phrases(window: _Window, bars_per_phrase: int = BARS_PER_PHRASE) -> list[_Window]:
    """Phrases (four bars unless the style says otherwise) counted from the song's bar
    grid; short leftovers join a neighbor."""
    # Reconstruct missing bar starts after a hard stop using the preserved global
    # phase and meter, rather than collapsing the entire window into one phrase.
    bars = _bars(window)
    marks = [start for start, _ in bars]
    cuts = [window.start]
    # A pickup before the first bar belongs to the first phrase.
    for index in range(bars_per_phrase, len(marks), bars_per_phrase):
        cuts.append(marks[index])
    cuts.append(window.end)
    bar = bars[0][1] - bars[0][0] if bars else window.end - window.start
    # A leftover shorter than two bars is folded into the phrase before it.
    while len(cuts) > 2 and cuts[-1] - cuts[-2] < 2 * bar:
        del cuts[-2]
    phrases = []
    for a, b in itertools.pairwise(cuts):
        before = sum(1 for t in window.beats if t < a)
        phrases.append(_Window(window.section_index, a, b,
                               tuple(t for t in window.beats if a <= t < b),
                               tuple(t for t in window.downbeats if a <= t < b), False,
                               window.offset + before, window.beats_per_bar,
                               window.bar_phase, window.bar_offset + before))
    return phrases


def _same_part(first: PlannedSection, later: PlannedSection, music: _Music) -> bool:
    """Whether a later section is a return of an earlier one with the same label.

    A name from the music review is trusted. A guessed label (from loudness) only
    counts when both parts are at least two phrases long and about the same length,
    the way a second verse or chorus usually is.
    """
    if first.start_centisecond in music.labels or later.start_centisecond in music.labels:
        return True
    if first.part is not None and later.part is not None:
        return first.part == later.part
    a = first.end_centisecond - first.start_centisecond
    b = later.end_centisecond - later.start_centisecond
    bars = [y - x for x, y in itertools.pairwise(music.downbeats)]
    bar = sorted(bars)[len(bars) // 2] if bars else 200
    return min(a, b) >= 2 * BARS_PER_PHRASE * bar and abs(a - b) <= 0.25 * max(a, b)


def _accent(planner: _Planner, window: _Window, active: set[str]) -> int:
    """A louder section opens with everything it uses flashing and fading over a beat."""
    if not window.accent or not window.beats:
        return window.start
    end = min(window.end, window.start + _beat_length(window, 0))
    for pid in sorted(active):
        planner.light(pid, window.section_index, window.start, end, "fade", 100, 0)
    return end



# ---------------------------------------------------------------- harmony and lyrics

# During a bar that leaves the home harmony, everything but the showpiece drops to
# this share of its brightness.
DEPARTURE_LEVEL = 0.3


def _feature(display: Display, usable: set[str]) -> str | None:
    """The display's showpiece: a mega tree, else the prop with the most channels."""
    candidates = [display.props[p] for p in usable]
    trees = [p for p in candidates if p.role == "mega_tree"]
    if trees:
        return max(trees, key=lambda p: (p.channel_count, p.name)).prop_id
    big = [p for p in candidates if p.channel_count >= 3]
    return max(big, key=lambda p: (p.channel_count, p.name)).prop_id if big else None


# Words that name a kind of prop, and words in prop names that say nothing about it.
_ROLE_WORDS = {
    "tree": {"mega_tree", "mini_tree"}, "star": {"star"}, "snow": {"snowflake"},
    "snowflake": {"snowflake"}, "icicle": {"icicles"}, "arch": {"arch"},
}
_PLAIN_WORDS = frozenset({
    "the", "and", "for", "with", "left", "right", "front", "back", "top", "bottom", "big",
    "small", "mini", "mega", "light", "lights", "line", "lines", "outline", "prop", "set",
    "yard", "house", "string", "strings", "red", "green", "blue", "white", "multi",
    "color", "colour", "panel", "board", "pole", "on", "of", "a", "my",
})
# A prop is cued at most once in this long (centiseconds).
CUE_SPACING = 400


def _forms(word: str) -> set[str]:
    """A word and its singular (trees -> tree, snowmen -> snowman, boxes -> box)."""
    word = re.sub(r"[^a-z]", "", word.lower())
    forms = {word}
    if word.endswith("men") and len(word) > 4:
        forms.add(word[:-3] + "man")
    if word.endswith("es") and len(word) > 4:
        forms.add(word[:-2])
    if word.endswith("s") and len(word) > 3:
        forms.add(word[:-1])
    return {f for f in forms if len(f) >= 3}


def _lyric_cues(analysis: dict[str, Any], display: Display, usable: set[str],
                duration: int, extra: dict[str, set[str]] | None = None
                ) -> list[tuple[int, list[str]]]:
    """When a sung word names props ("tree", "star", or a word of a prop's own name),
    the time of the word and the props it names."""
    lyrics = analysis.get("lyrics")
    lines = lyrics.get("lines") if isinstance(lyrics, dict) else None
    if not isinstance(lines, list):
        return []
    names: dict[str, set[str]] = defaultdict(set)
    for pid in usable:
        prop = display.props[pid]
        for token in re.findall(r"[a-z]+", prop.name.lower()):
            if token not in _PLAIN_WORDS:
                for form in _forms(token):
                    names[form].add(pid)
        for word, roles in _ROLE_WORDS.items():
            if prop.role in roles:
                names[word].add(pid)
    for word, chosen in (extra or {}).items():
        for form in _forms(word):
            names[form].update(p for p in chosen if p in usable)
    spoken: list[tuple[int, str]] = []
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("start"), int | float):
            continue
        words = [w for w in line.get("words") or []
                 if isinstance(w, dict) and isinstance(w.get("start"), int | float)
                 and isinstance(w.get("text"), str)]
        if words:
            spoken.extend((_cs(float(w["start"])), w["text"]) for w in words)
        elif isinstance(line.get("text"), str):
            # Without word timings, a line's words count from its start.
            spoken.extend((_cs(float(line["start"])), w) for w in line["text"].split())
    last: dict[str, int] = {}
    cues: list[tuple[int, list[str]]] = []
    for time, word in sorted(spoken):
        if not 0 <= time < duration:
            continue
        props = sorted({p for form in _forms(word) for p in names.get(form, set())
                        if time - last.get(p, -CUE_SPACING) >= CUE_SPACING})
        if props:
            for p in props:
                last[p] = time
            cues.append((time, props))
    return cues


# ---------------------------------------------------------------- stabs

# Strong hits closer together than this are one stab.
STAB_SPACING = 15
# A stab this close to a flash already planned is left to the flash.
STAB_CLEAR = 8
# A light already on goes dark this long before a stab, so the stab reads.
STAB_DIP = 6


def _strong_onsets(analysis: dict[str, Any], top_share: float) -> list[tuple[int, float]]:
    """The song's strongest onsets (the top ``top_share`` by strength), with their
    strength as a share of the strongest."""
    found = [(_cs(float(o["time"])), float(o["strength"]))
             for o in analysis.get("analysis", {}).get("onsets", [])
             if isinstance(o, dict) and isinstance(o.get("time"), int | float)
             and isinstance(o.get("strength"), int | float)]
    if not found or top_share <= 0:
        return []
    ranked = sorted(strength for _, strength in found)
    cut = ranked[min(len(ranked) - 1, int(len(ranked) * (1 - top_share)))]
    top = ranked[-1] or 1.0
    return sorted((t, strength / top) for t, strength in found if strength >= cut)


def _stabs(planner: _Planner, analysis: dict[str, Any], windows: list[_Window],
           sections: list[Any], groups: list[_Group],
           active_in: Callable[[_Window], set[str]], taken: set[int], beat: int) -> list[int]:
    """Light a share of the yard on each of the song's strongest hits, a different set
    of groups each time; the very strongest light more, quiet parts less."""
    style = planner.style
    share, top_share, length = style.stabs
    if share <= 0 or not groups:
        return []
    stabbed: list[int] = []
    turn = 0
    for time, strength in _strong_onsets(analysis, top_share):
        home = next((w for w in windows if w.start + 5 <= time < w.end - 5), None)
        if home is None:
            continue
        if stabbed and time - stabbed[-1] < STAB_SPACING:
            continue
        if any(abs(time - t) <= STAB_CLEAR for t in taken):
            continue
        here = active_in(home)
        # Snowflakes only ever fall, top first, so they sit stabs out.
        live = [g for g in groups if g.role != "snowflake" and any(p in here for p in g.props)]
        if not live:
            continue
        # Quieter parts answer with less of the yard.
        level = sections[home.section_index].level
        want = min(1.0, share * (1.5 if strength >= 0.6 else 1.0)
                   * {LOW: 0.5, MID: 0.7}.get(level, 1.0))
        total = sum(len(g.props) for g in live)
        chosen: list[str] = []
        for k in range(len(live)):
            if len(chosen) >= want * total:
                break
            chosen.extend(p for p in live[(turn + k) % len(live)].props if p in here)
        turn += max(1, len(live) // 3)
        stop = min(home.end, time + min(length, max(8, beat // 2)))
        hit = 0
        for pid in chosen:
            for channel in planner.channels(pid, home.section_index):
                hit += _punch(planner.canvas, pid, channel, time, stop,
                              planner.color(pid, channel), dip=STAB_DIP,
                              fade=style.stab_fade)
        if hit:
            stabbed.append(time)
    return stabbed


# ---------------------------------------------------------------- the finale

# The closing hits: strong onsets this share of the song's strongest, at least this
# far apart, near the end and followed by a ring-out of at least RING_OUT.
FINAL_STRENGTH = 0.6
FINAL_SPACING = 60
FINAL_SEARCH = 2500
FINAL_GAP = 400
RING_OUT = 150


def _final_hits(analysis: dict[str, Any], music: _Music) -> list[int]:
    """The song's last two or three big hits (closing chords), if it ends on them."""
    found: list[tuple[int, float]] = []
    for onset in analysis.get("analysis", {}).get("onsets", []):
        if isinstance(onset, dict) and isinstance(onset.get("time"), int | float) and \
                isinstance(onset.get("strength"), int | float):
            found.append((_cs(float(onset["time"])), float(onset["strength"])))
    top = max((strength for _, strength in found), default=0.0)
    if top <= 0:
        return []
    window_start = music.duration - FINAL_SEARCH
    strong = sorted({t for t, strength in found if strength >= FINAL_STRENGTH * top
                     and window_start <= t <= music.duration - RING_OUT}
                    | {t for t in _times(analysis, "crashes")
                       if window_start <= t <= music.duration - RING_OUT})
    spaced: list[int] = []
    for t in strong:
        if not spaced or t - spaced[-1] >= FINAL_SPACING:
            spaced.append(t)
    hits = spaced[-3:]
    # A cadence: the hits come close together, then the sound rings out.
    while len(hits) > 1 and hits[1] - hits[0] > FINAL_GAP:
        hits = hits[1:]
    if len(hits) < 2 or any(b - a > FINAL_GAP for a, b in itertools.pairwise(hits)):
        return []
    return hits


def _finale(planner: _Planner, hits: list[int], props: list[str], keep: set[str]) -> None:
    """Stage the closing hits across the yard: the left side lights on the first, the
    right on the next, the whole display on the last; then it fades out from the
    edges inward."""
    canvas = planner.canvas
    end = max(e.end_centisecond for items in canvas.effects.values() for e in items) \
        if any(canvas.effects.values()) else hits[-1] + RING_OUT
    end = max(end, hits[-1] + RING_OUT)
    first = hits[0]
    # Movements still running at the first hit give way to it (whole, so none stops
    # partway), and everything else is cleared from there.
    cut = {m.movement_id for m in canvas.movements if m.end_centisecond > first}
    canvas.movements = [m for m in canvas.movements if m.movement_id not in cut]
    for key, effects in canvas.effects.items():
        canvas.effects[key] = [e for e in effects if e.movement_id not in cut]
    _darken(canvas, first, end, keep)
    staged = [p for p in props if p not in keep]
    if not staged:
        return
    xs = {p: (planner.display.props[p].center or (0.0, 0.0))[0] for p in staged}
    order = sorted(staged, key=lambda p: (xs[p], p))
    half = len(order) // 2
    left, right = order[:half], order[half:]
    center = (min(xs.values()) + max(xs.values())) / 2
    reach = max(abs(x - center) for x in xs.values()) or 1.0
    last = hits[-1]
    sides = [left, right] if len(hits) == 3 else [left]
    for side, hit in zip(sides, hits, strict=False):
        for pid in side:
            planner.light(pid, 0, hit, last, "on", 80)
    hold = min(100, (end - last) // 3)
    nearest = min(abs(x - center) for x in xs.values())
    reach = max(abs(x - center) for x in xs.values()) - nearest or 1.0
    for pid in staged:
        edge = (abs(xs[pid] - center) - nearest) / reach
        # Everything holds full, then fades out: the edges go dark first and the
        # middle of the yard last, at the very end.
        fade_end = end - round(edge * (end - last - hold) * 0.5)
        planner.light(pid, 0, last, last + hold, "on", 100)
        planner.light(pid, 0, last + hold, max(last + hold + 10, fade_end), "fade", 100, 0)


# ---------------------------------------------------------------- singing faces

_CLOSED = {"closed", "close", "shut", "rest", "down"}
_HALF = {"half", "mid", "middle", "partial", "semi"}
_OPEN = {"open", "full", "wide", "up"}
_ROUND = {"o", "oo", "ooh", "round"}
_BLINK = {"closed", "close", "shut", "blink"}
BLINK_EVERY = 300
BLINK_LENGTH = 15


@dataclass
class _Face:
    outline: list[str] = field(default_factory=list)
    mouths: dict[str, str] = field(default_factory=dict)
    eyes_open: list[str] = field(default_factory=list)
    eyes_closed: list[str] = field(default_factory=list)
    others: list[str] = field(default_factory=list)

    @property
    def members(self) -> set[str]:
        return {*self.outline, *self.mouths.values(), *self.eyes_open, *self.eyes_closed,
                *self.others}


def _faces(display: Display, rule_set: RuleSet, usable: set[str]) -> list[_Face]:
    """Singing faces built from separate props, with each part recognized by its name."""
    outline_words = rule_set.rules["face_outline_with_mouth"].params.get("outline_names", [])
    mouth_words = list({
        *rule_set.rules["face_outline_with_mouth"].params.get("mouth_names", []),
        *rule_set.rules["mouths_only_during_vocals"].params.get("mouth_names", []),
    })
    rest_words = rule_set.rules["mouths_only_during_vocals"].params.get("rest_names", [])
    seen: set[str] = set()
    faces: list[_Face] = []
    for prop in display.props.values():
        if prop.role != "singing_face" or prop.prop_id in seen:
            continue
        members = sorted({prop.prop_id, *prop.figure}, key=lambda p: display.props[p].name)
        seen.update(members)
        face = _Face()
        for pid in members:
            if pid not in usable:
                continue
            name = display.props[pid].name
            words = _words(name)
            if _named(name, mouth_words):
                shape = ("closed" if words & _CLOSED or _named(name, rest_words)
                         else "half" if words & _HALF
                         else "round" if words & _ROUND else "open")
                face.mouths.setdefault(shape, pid)
            elif words & {"eye", "eyes"}:
                (face.eyes_closed if words & _BLINK else face.eyes_open).append(pid)
            elif _named(name, outline_words):
                face.outline.append(pid)
            else:
                face.others.append(pid)
        if face.members:
            faces.append(face)
    return faces


def _rest_spans(sections: list[PlannedSection], regions: list[tuple[int, int]],
                stops: list[tuple[int, int]], face: _Face, constraints: _Constraints
                ) -> list[tuple[int, int, int]]:
    """Mid and high energy stretches with no singing and no hard stop."""
    spans: list[tuple[int, int, int]] = []
    for index, section in enumerate(sections):
        if section.level < MID or any(section.label.lower() in constraints.quiet.get(p, set())
                                      for p in face.members):
            continue
        pieces = [(section.start_centisecond, section.end_centisecond)]
        for a, b in [*regions, *stops]:
            next_pieces = []
            for s, e in pieces:
                if b <= s or a >= e:
                    next_pieces.append((s, e))
                    continue
                if s < a:
                    next_pieces.append((s, a))
                if b < e:
                    next_pieces.append((b, e))
            pieces = next_pieces
        spans.extend((s, e, index) for s, e in pieces if e - s >= 50)
    return spans


def display_has_mouths(display: Display, rule_set: RuleSet) -> bool:
    """Whether any singing face has a separate, sequenceable mouth prop."""
    usable = {p.prop_id for p in display.props.values() if p.sequenceable}
    return any(face.mouths for face in _faces(display, rule_set, usable))


def _vocal_spans(vocals: dict[str, Any], duration: int) -> tuple[
        list[tuple[int, int]], list[tuple[int, int, float]]]:
    regions = []
    for region in vocals.get("regions", []):
        a, b = _cs(float(region["start"])), min(duration, _cs(float(region["end"])))
        if b - a >= 10:
            regions.append((max(0, a), b))
    syllables = []
    for syllable in vocals.get("syllables", []):
        a, b = _cs(float(syllable["start"])), _cs(float(syllable["end"]))
        syllables.append((a, min(b, duration), float(syllable.get("strength", 0.5))))
    return regions, sorted(syllables)


def _sing(planner: _Planner, face: _Face, regions: list[tuple[int, int]],
          syllables: list[tuple[int, int, float]], section_at: Any) -> None:
    """Light a face while someone sings: outline on, mouth shapes on syllables, blinks."""
    shapes = face.mouths
    for start, end in regions:
        section = section_at(start)
        steady = [*face.outline, *face.others]
        for pid in steady:
            planner.light(pid, section, start, end)
        # Eyes stay open with a quick blink every few seconds.
        blinks = list(range(start + 100, end - 50, BLINK_EVERY)) if face.eyes_closed else []
        cursor = start
        for blink in blinks:
            for pid in face.eyes_open:
                planner.light(pid, section, cursor, blink)
            for pid in face.eyes_closed:
                planner.light(pid, section, blink, blink + BLINK_LENGTH)
            cursor = blink + BLINK_LENGTH
        for pid in face.eyes_open:
            planner.light(pid, section, cursor, end)
        if not shapes:
            continue
        inside = [(max(a, start), min(b, end), strength) for a, b, strength in syllables
                  if a < end and start < b]
        cursor = start
        for index, (a, b, strength) in enumerate(inside):
            a = max(a, cursor)
            if b - a < 5:
                continue
            if "closed" in shapes and a - cursor >= 5:
                planner.light(shapes["closed"], section, cursor, a)
            elif a - cursor < 5:
                # Too short to close the mouth: the opening starts a moment early, so
                # the face is never shown without a mouth.
                a = cursor
            if "round" in shapes and b - a >= 40 and index % 3 == 2:
                shape = "round"
            elif strength >= 0.6 and "open" in shapes:
                shape = "open"
            else:
                shape = next((s for s in ("half", "open", "round") if s in shapes), "closed")
            planner.light(shapes[shape], section, a, b)
            cursor = b
        if "closed" in shapes and end > cursor:
            planner.light(shapes["closed"], section, cursor, end)


def _rest(planner: _Planner, face: _Face, spans: list[tuple[int, int, int]]) -> None:
    """Between songs' vocal lines, a face holds still: outline, eyes, closed mouth."""
    parts = [*face.outline, *face.others, *face.eyes_open]
    if "closed" in face.mouths and face.outline:
        parts.append(face.mouths["closed"])
    for start, end, section in spans:
        for pid in parts:
            planner.light(pid, section, start, end)


def _joined(effects: list[Effect]) -> list[Effect]:
    """Join back-to-back holds with the same look, so a long hold is one effect in S6."""
    out: list[Effect] = []
    for effect in sorted(effects, key=lambda e: e.start_centisecond):
        previous = out[-1] if out else None
        if (
            previous is not None and effect.kind in {"on", "twinkle", "shimmer"}
            and previous.end_centisecond == effect.start_centisecond
            and (previous.kind, previous.start_intensity, previous.color)
            == (effect.kind, effect.start_intensity, effect.color)
            and previous.movement_id is None and effect.movement_id is None
        ):
            out[-1] = Effect(previous.prop_id, previous.channel_index,
                             previous.start_centisecond, effect.end_centisecond, previous.kind,
                             previous.start_intensity, previous.end_intensity, previous.color)
        else:
            out.append(effect)
    return out


# ---------------------------------------------------------------- quality

# Moments that light the whole yard at once.
# A chorus at the same loudness as a verse takes the other look.
CHORUS_LABELS = frozenset({"chorus", "refrain", "hook"})
VERSE_LABELS = frozenset({"verse", "pre-chorus"})
ACCENT_MOMENTS = frozenset({"crash", "return", "lift"})
# Swells into louder parts are at least this far apart (centiseconds).
SWELL_SPACING = 2500

# The song counts as quiet where it is this share of its loudest or less.
QUIET_ENERGY = 0.08
# Dead air is filled at this brightness: a calm base, not a new look.
CALM_LEVEL = 40


def _quiet_spans(music: _Music) -> list[tuple[int, int]]:
    """Where the song itself is silent or nearly so: before the first beat, after the
    last, hard stops, and stretches of very low energy."""
    beat = music.beats[1] - music.beats[0]
    spans = [(0, music.beats[0]), (music.beats[-1] + beat, music.duration), *music.stops]
    loudest = max((v for _, v in music.energy), default=0.0)
    start: int | None = None
    for time, value in music.energy:
        if loudest and value <= QUIET_ENERGY * loudest:
            start = time if start is None else start
        elif start is not None:
            spans.append((start, time))
            start = None
    if start is not None:
        spans.append((start, music.duration))
    return [(a, b) for a, b in spans if b > a]


def _music_marks(analysis: dict[str, Any], music: _Music,
                 sections: list[PlannedSection]) -> list[int]:
    """Times an effect can start on and look like it follows the music."""
    halves = [(a + b) // 2 for a, b in itertools.pairwise(music.beats)]
    marks = set(music.beats) | set(halves) | {s.start_centisecond for s in sections}
    marks |= {end for _, end in music.stops} | {0}
    for key in ("kicks", "snares", "onsets", "crashes", "high_hits"):
        marks |= set(_times(analysis, key))
    return sorted(marks)


# ---------------------------------------------------------------- glow

# Props that hit together on the beat and decay to a glow, and props that sparkle.
PULSE_ROLES = frozenset({"outline", "decor", "unknown", "mini_tree", "icicles",
                         "singing_face"})
BED_ROLES = frozenset({"arch", "mega_tree", "star"})
# Where the song is this quiet (share of its loudest), the glow goes dark: a quiet
# break reads as a blackout, not a dim yard.
GLOW_QUIET = 0.2
GLOW_QUIET_SPAN = 200


def _low_spans(music: _Music, share: float, minimum: int) -> list[tuple[int, int]]:
    loudest = max((v for _, v in music.energy), default=0.0)
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for time, value in music.energy:
        if loudest and value <= share * loudest:
            start = time if start is None else start
        elif start is not None:
            if time - start >= minimum:
                spans.append((start, time))
            start = None
    if start is not None and music.duration - start >= minimum:
        spans.append((start, music.duration))
    return spans


def _minus(gaps: list[tuple[int, int]], cut: list[tuple[int, int]]) -> list[tuple[int, int]]:
    for a, b in cut:
        pieces = []
        for x, y in gaps:
            if b <= x or a >= y:
                pieces.append((x, y))
                continue
            if x < a:
                pieces.append((x, a))
            if b < y:
                pieces.append((b, y))
        gaps = pieces
    return gaps


def _glow(planner: _Planner, canvas: _Canvas, window: _Window, props: list[str],
          spec: tuple[int, int], dark: list[tuple[int, int]],
          ramp: tuple[int, int] | None = None) -> None:
    """Fill the time a prop is not leading with the style's glow. ``ramp`` fades the
    glow in (0 to hold) or out (hold to 0) across the window instead."""
    hit, hold = spec
    beats = list(window.beats)
    level = planner.sections[window.section_index].level
    bars = [y - x for x, y in itertools.pairwise(window.downbeats)]
    bar = sorted(bars)[len(bars) // 2] if bars else 200
    for pid in props:
        role = planner.display.props[pid].role
        for channel in planner.channels(pid, window.section_index):
            key = (pid, channel)
            color = planner.color(pid, channel)
            for a, b in _minus(_free_gaps(canvas, key, window.start, window.end), dark):
                if b - a < 20:
                    continue
                if ramp is not None:
                    span = window.end - window.start
                    first, last = ramp
                    level_a = round(first + (last - first) * (a - window.start) / span)
                    level_b = round(first + (last - first) * (b - window.start) / span)
                    if max(level_a, level_b) > 0:
                        canvas.put(pid, channel, a, b, "fade", max(1, level_a), level_b, color)
                    continue
                if role in BED_ROLES:
                    # In the fuller parts, featured props rest on a texture through a
                    # long held stretch: a twinkle, a shimmer in loud parts. Short gaps
                    # between their moves, and quiet parts, stay dark, so the moves
                    # still read and the song still builds.
                    if level >= planner.style.beds_from and b - a >= 2 * bar:
                        count = planner.display.props[pid].channel_count
                        outer = role == "mega_tree" and count >= 4 and not (
                            count // 4 <= channel < count - count // 4)
                        if outer:
                            # A mega tree's outer channels carry low waves that
                            # decay each bar, under the center's texture.
                            _waves(canvas, pid, channel, a, b, window, hold, color)
                        else:
                            canvas.put(pid, channel, a, b,
                                       "shimmer" if level == HIGH else "twinkle", hold,
                                       color=color)
                    continue
                if hit <= hold or role not in PULSE_ROLES:
                    # A glow with no hit breathes gently, swelling once a bar.
                    bars = [t for t in window.downbeats if a <= t < b - 20]
                    cursor = a
                    for k, t in enumerate(bars):
                        if t > cursor:
                            canvas.put(pid, channel, cursor, t, "on", hold, color=color)
                        end = bars[k + 1] if k + 1 < len(bars) else b
                        middle = t + (end - t) // 2
                        top = min(100, hold + 20)
                        canvas.put(pid, channel, t, middle, "fade", hold, top, color)
                        canvas.put(pid, channel, middle, end, "fade", top, hold, color)
                        cursor = end
                    if cursor < b:
                        canvas.put(pid, channel, cursor, b, "on", hold, color=color)
                    continue
                # Hit on each beat (each half beat in loud parts, for styles that drive
                # that hard), decay to the glow by the next.
                pulses = beats if level < HIGH or not planner.style.glow_half_beats else sorted(
                    {*beats, *((x + y) // 2 for x, y in itertools.pairwise(beats))})
                if planner.style.glow_every > 1:
                    # A calmer glow hits every other beat, counted from the bar.
                    pulses = [t for t in pulses
                              if _beat_in_bar(window, t) % planner.style.glow_every == 0]
                marks = [t for t in pulses if a <= t < b - 10]
                cursor = a
                for k, t in enumerate(marks):
                    if t > cursor:
                        canvas.put(pid, channel, cursor, t, "on", hold, color=color)
                    end = marks[k + 1] if k + 1 < len(marks) else b
                    # A sixteenth at full, then the decay back to the glow.
                    flash = t + max(5, (end - t) // 4) if end - t >= 20 else end
                    canvas.put(pid, channel, t, flash, "on", hit, color=color)
                    if end > flash:
                        canvas.put(pid, channel, flash, end, "fade", max(hold + 1, hit * 4 // 5),
                                   hold, color)
                    cursor = end
                if cursor < b:
                    canvas.put(pid, channel, cursor, b, "on", hold, color=color)



# Props this close to the same distance from the middle of their family are a
# mirrored pair.
MIRROR_TOLERANCE = 0.08


def _mirror_ranks(planner: _Planner, members: list[str]) -> list[int]:
    """Each member's step in a ripple that starts in the middle of the family and runs
    out to both sides at once: props mirrored across the middle share a step."""
    xs = {pid: (planner.display.props[pid].center or (0.0, 0.0))[0] for pid in members}
    middle = (min(xs.values()) + max(xs.values())) / 2 if xs else 0.0
    order = sorted(members, key=lambda pid: (abs(xs[pid] - middle), xs[pid]))
    ranks: dict[str, int] = {}
    rank, tier = -1, None
    for pid in order:
        distance = abs(xs[pid] - middle)
        if tier is None or distance - tier > MIRROR_TOLERANCE:
            rank += 1
            tier = distance
        ranks[pid] = rank
    return [ranks[pid] for pid in members]


def _beat_in_bar(window: _Window, time: int) -> int:
    """How many beats into its bar a time falls (0 on the downbeat)."""
    bar = max((d for d in window.downbeats if d <= time), default=window.beats[0])
    return sum(1 for x in window.beats if bar <= x < time)


def _waves(canvas: _Canvas, pid: str, channel: int, a: int, b: int, window: _Window,
           level: int, color: str | None) -> None:
    """Low waves: from each downbeat the channel decays from ``level`` to a third of
    it by the next."""
    marks = [a] + [t for t in window.downbeats if a + 20 <= t < b - 20] + [b]
    low = max(1, level // 3)
    for x, y in itertools.pairwise(marks):
        canvas.put(pid, channel, x, y, "fade", level, low, color)


def _free_gaps(canvas: _Canvas, key: tuple[str, int], start: int,
               end: int) -> list[tuple[int, int]]:
    gaps = []
    cursor = start
    for e in sorted(canvas.effects[key], key=lambda e: e.start_centisecond):
        if e.end_centisecond <= cursor or e.start_centisecond >= end:
            continue
        if e.start_centisecond > cursor:
            gaps.append((cursor, e.start_centisecond))
        cursor = max(cursor, e.end_centisecond)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def _fill_dead_air(planner: _Planner, canvas: _Canvas, music: _Music,
                   windows: list[_Window], calm: Callable[[_Window], list[str]],
                   props: set[str], quiet: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Light a calm base wherever the song plays but the yard is dark. Returns the
    stretches it filled. Each fill starts and ends on a beat."""
    effects = [e for items in canvas.effects.values() for e in items]
    share = lit_share(effects, props, music.duration, step=10, weighted=False)
    dark = [s <= DEAD_SHARE and not any(a <= i * 10 < b for a, b in quiet)
            for i, s in enumerate(share)]
    filled: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate([*dark, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            a, b = start * 10, index * 10
            start = None
            if b - a < DEAD_SPAN:
                continue
            a = next((t for t in music.beats if t >= a), a)
            b = max((t for t in music.beats if t <= b), default=b)
            lit = False
            for window in windows:
                lo, hi = max(a, window.start), min(b, window.end)
                if hi - lo < 50:
                    continue
                for pid in calm(window):
                    for channel in planner.channels(pid, window.section_index):
                        for g0, g1 in _free_gaps(canvas, (pid, channel), lo, hi):
                            lit |= canvas.put(pid, channel, g0, g1, intensity=CALM_LEVEL,
                                              color=planner.color(pid, channel))
            if lit:
                filled.append((a, b))
    return filled


# ---------------------------------------------------------------- one grid


def _sixteenths(music: _Music, sections: list[PlannedSection]) -> list[int]:
    """The song's sixteenth notes (each beat in four), plus its section and stop
    edges: the one grid every effect starts and ends on."""
    marks = {0, music.duration}
    for a, b in itertools.pairwise(music.beats):
        marks.update(a + (b - a) * k // 4 for k in range(4))
    if music.beats:
        marks.add(music.beats[-1])
    for start, end in music.stops:
        marks.update((start, end))
    marks.update(s.start_centisecond for s in sections)
    return sorted(t for t in marks if 0 <= t <= music.duration)


def _to_grid(grid: list[int], time: int) -> int:
    i = bisect.bisect_left(grid, time)
    near = [grid[j] for j in (i - 1, i) if 0 <= j < len(grid)]
    return min(near, key=lambda t: (abs(t - time), t)) if near else time


def _on_one_grid(canvas: _Canvas, grid: list[int], skip: set[str]) -> None:
    """Move every effect onto the song's sixteenth notes, so props that move
    together start on exactly the same moment (as hand-made shows do) instead of a
    few hundredths apart. Lip-sync keeps the singer's own timing, and a movement keeps
    its own timing if snapping would change the order it reaches its props."""
    def snapped(e: Effect) -> Effect | None:
        a, b = _to_grid(grid, e.start_centisecond), _to_grid(grid, e.end_centisecond)
        return dataclasses.replace(e, start_centisecond=a, end_centisecond=b) if b > a else None

    keep_as_is: set[str] = set()
    tagged: dict[str, list[tuple[str, Effect]]] = defaultdict(list)
    for (pid, _), items in canvas.effects.items():
        for e in items:
            if e.movement_id is not None:
                tagged[e.movement_id].append((pid, e))
    for m in canvas.movements:
        firsts: dict[str, int] = {}
        before: dict[str, set[int]] = defaultdict(set)
        after: dict[str, set[int]] = defaultdict(set)
        vanishes = False
        for pid, e in tagged.get(m.movement_id, []):
            new = _to_grid(grid, e.start_centisecond)
            firsts[pid] = min(firsts.get(pid, new), new)
            before[pid].add(e.start_centisecond)
            after[pid].add(new)
            vanishes |= snapped(e) is None
        order = [firsts[p] for p in m.prop_ids if p in firsts]
        # A wipe across a prop's segments, or a chase across props, that the grid
        # would squash keeps its own timing.
        if vanishes or any(b <= a for a, b in itertools.pairwise(order)) or any(
                len(after[p]) < len(before[p]) for p in before):
            keep_as_is.add(m.movement_id)
    for key, items in canvas.effects.items():
        if key[0] in skip:
            continue
        moved: list[Effect] = []
        for e in items:
            if e.movement_id in keep_as_is:
                moved.append(e)
                continue
            placed = snapped(e)
            if placed is not None:
                moved.append(placed)
        moved.sort(key=lambda e: (e.start_centisecond, e.movement_id not in keep_as_is))
        # Snapping never crosses neighbours, but an effect can now run into the next
        # (or into a movement that kept its own timing): the movement wins, otherwise
        # the earlier effect ends where the next begins.
        kept: list[Effect] = []
        for e in moved:
            if kept and kept[-1].end_centisecond > e.start_centisecond:
                last = kept[-1]
                if last.movement_id in keep_as_is and e.movement_id not in keep_as_is:
                    if e.end_centisecond <= last.end_centisecond:
                        continue
                    e = dataclasses.replace(e, start_centisecond=last.end_centisecond)
                else:
                    kept.pop()
                    if e.start_centisecond > last.start_centisecond:
                        kept.append(dataclasses.replace(
                            last, end_centisecond=e.start_centisecond))
            kept.append(e)
        canvas.effects[key] = kept
    canvas.movements = [
        m if m.movement_id in keep_as_is else dataclasses.replace(
            m, start_centisecond=min(_to_grid(grid, m.start_centisecond), m.start_centisecond),
            end_centisecond=max(_to_grid(grid, m.end_centisecond), m.end_centisecond))
        for m in canvas.movements]


def plan_show(analysis: dict[str, Any], display: Display, rule_set: RuleSet,
              vocals: dict[str, Any] | None = None, style: Style | None = None) -> Plan:
    """Plan a show. ``vocals`` is a vocal analysis (see vocals.py); without it faces
    light like other props and their mouths stay dark."""
    music = _music(analysis)
    sections = _sections(music)
    windows = _windows(music, sections)
    constraints = _constraints(display, rule_set, vocals_known=vocals is not None)
    canvas = _Canvas(constraints.caps)
    style = style or get_style(None)
    planner = _Planner(display, constraints, sections, canvas, style=style,
                       kicks=_times(analysis, "kicks"), snares=_times(analysis, "snares"))
    notes = list(music.notes)
    notes.append(f"Style: {style.name}.")
    guidance = analysis.get("analysis", {}).get("beat_guidance")
    if isinstance(guidance, dict) and guidance.get("stretches"):
        notes.append(f"Beats in {len(guidance['stretches'])} singer-led stretch(es) were placed "
                     "with the vocals' help.")
    if music.labels:
        notes.append(f"{len(music.labels)} section name(s) come from the music review; the "
                     "others are guesses from loudness.")
    elif not any(section.part is not None for section in sections):
        notes.append("Section labels (intro, verse, chorus, finale, outro) are guesses from "
                     "loudness, not recognition.")

    keep_spans: dict[str, list[tuple[int, int]]] = {}
    for pid, during in constraints.keep_on.items():
        if during is None:
            keep_spans[pid] = [(0, music.duration)]
        else:
            wanted = {d.lower() for d in during}
            keep_spans[pid] = [(s.start_centisecond, s.end_centisecond) for s in sections
                               if s.label.lower() in wanted]
        for start, end in keep_spans[pid]:
            channel = planner.channels(pid, 0)[0]
            canvas.put(pid, channel, start, end, color=planner.color(pid, channel))

    usable = set(constraints.channels)
    if vocals is None:
        # Nobody is singing as far as we know: a face shows its resting mouth exactly
        # when its outline is on, never one without the other.
        for face in _faces(display, rule_set, usable):
            rest = face.mouths.get("closed")
            if face.outline and rest is not None and rest in usable:
                outline = face.outline[0]
                constraints.channels.pop(rest, None)
                usable.discard(rest)
                for channel in range(display.props[rest].channel_count):
                    constraints.copies[(outline, 0)].append((rest, channel))
    regions: list[tuple[int, int]] = []
    singing: set[str] = set()
    if vocals is not None:
        regions, syllables = _vocal_spans(vocals, music.duration)
        faces = _faces(display, rule_set, usable - set(keep_spans))

        def section_at(time: int) -> int:
            return next((i for i, sec in enumerate(sections)
                         if sec.start_centisecond <= time < sec.end_centisecond), 0)

        for face in faces:
            allowed_regions = [
                (a, b) for a, b in regions
                if not any(sections[section_at(a)].label.lower() in constraints.quiet.get(p, set())
                           for p in face.members)
            ]
            _sing(planner, face, allowed_regions, syllables, section_at)
            _rest(planner, face, _rest_spans(sections, regions, music.stops, face, constraints))
            singing |= face.members
        if not faces:
            notes.append("Vocals were analyzed, but the preview has no singing face to use them.")
        elif not regions:
            notes.append("No singing was found in the vocals, so the faces rest all song.")
        elif not any(face.mouths for face in faces):
            notes.append("No face has separate mouth props, so faces light while someone "
                         "sings but their mouths do not move.")
    rows, singles = _rows(display, usable - singing)
    groups = _groups(display, rows, singles)
    planner.snow = formation(display, {p for p in usable - singing
                                       if display.props[p].role == "snowflake"},
                             prefer="columns")
    base = {p for p in usable - singing if display.props[p].role in BASE_ROLES}
    sparkle = _sparkle_group(groups)
    hits = _times(analysis, "high_hits")
    # The song's own shape decides where the handoffs start, so two songs on the
    # same display do not open the same way. Still deterministic.
    shape = f"{music.duration}:{len(music.beats)}:" + ",".join(
        f"{s.start_centisecond}/{s.level}" for s in sections)
    turn = zlib.crc32(shape.encode("utf-8")) % max(1, len(groups))
    moments: list[tuple[str, int]] = []
    # Motifs: a part that comes back (a second chorus) repeats its first look.
    keys = [(s.label.lower(), s.level) for s in sections]
    last_of = {key: index for index, key in enumerate(keys)}
    motif_turn: dict[tuple[str, int], int] = {}
    motif_flip: dict[tuple[str, int], int] = {}
    motif_first: dict[tuple[str, int], int] = {}
    section_first: dict[int, int] = {}
    section_turn: dict[int, int] = {}
    section_phrase: dict[int, int] = defaultdict(int)
    section_extra: dict[int, int] = {}
    section_flip: dict[int, int] = {}
    # How many times this part has come round before: styles that vary repeats move
    # differently each time.
    occurrence: dict[int, int] = {}
    verse_levels = {s.level for s in sections if s.label.lower() in VERSE_LABELS}
    seen_key: dict[tuple[str, int], int] = defaultdict(int)

    def active_in(window: _Window) -> set[str]:
        label = sections[window.section_index].label.lower()
        return {
            pid for pid in usable - singing
            if label not in constraints.quiet.get(pid, set())
            and not any(a < window.end and window.start < b
                        for a, b in keep_spans.get(pid, []))
        }

    last_window = windows[-1] if windows else None
    final_hits = _final_hits(analysis, music)
    swells: list[_Window] = []
    drops: list[_Window] = []
    for window in windows:
        section = sections[window.section_index]
        label = section.label.lower()
        si = window.section_index
        if si not in section_turn:
            # Each part starts its chases and falls the same way, so a part that
            # returns keeps its handoffs; within a part they alternate as before.
            planner.fall_turn = 0
            planner.turns = {}
            key = keys[si]
            occurrence[si] = seen_key[key] if style.vary_repeats else 0
            # A chorus as loud as a verse takes the other look, so the two read
            # differently (where the style offers a choice at that loudness).
            if label in CHORUS_LABELS and section.level in verse_levels:
                occurrence[si] += 1
            seen_key[key] += 1
            if key in motif_turn and label not in ONE_OFF_LABELS and _same_part(
                    sections[motif_first[key]], section, music):
                section_turn[si] = motif_turn[key]
                section_flip[si] = motif_flip[key]
                section_first[si] = motif_first[key]
                section_extra[si] = 1 if section.level == HIGH and last_of[key] == si else 0
                moments.append(("repeat", section.start_centisecond))
                if seen_key[key] > 1 and style.vary_repeats:
                    moments.append(("variation", section.start_centisecond))
            else:
                section_turn[si] = turn
                section_flip[si] = si % 2
                section_first[si] = si
                motif_first.setdefault(key, si)
                section_extra[si] = 0
                motif_turn.setdefault(key, turn)
                motif_flip.setdefault(key, si % 2)
            if label == "bridge":
                # The bridge is heard once: other groups lead, moving the other way and
                # the other way round, so it stands apart from the verses and choruses.
                section_turn[si] += max(1, len(groups) // 2)
                section_flip[si] = 1 - section_flip[si]
                occurrence[si] = max(occurrence[si], 1)
                moments.append(("bridge", section.start_centisecond))
            # The show grows as the song goes: later mid and loud parts bring in up
            # to ``style.arc`` more lead groups.
            if section.level >= MID:
                progress = section.start_centisecond / max(1, music.duration)
                section_extra[si] += round(style.arc * progress)
        planner.peak = section.level == HIGH and si == max(
            (i for i, sec in enumerate(sections) if sec.level == HIGH), default=-1)
        active = active_in(window)
        upcoming = _leads(groups, section_turn[si] + section_phrase[si], section.level,
                          label == "finale", None, section_extra[si], style.leads)
        start = window.start
        if style.entry == "swell":
            # A swell into a louder part, but not one after another: a song that
            # changes parts often swells into the ones at least SWELL_SPACING apart.
            last = max((t for kind, t in moments if kind == "lift"), default=None)
            if window.accent and (last is None or window.start - last >= SWELL_SPACING):
                swells.append(window)
                moments.append(("lift", window.start))
        else:
            start = _accent(planner, window, {p for p in active if p in base or p in upcoming})
            if start > window.start:
                moments.append(("lift", window.start))
                if style.entry == "drop":
                    drops.append(window)
        end = window.end
        closing: int | None = None
        if window is last_window and si == len(sections) - 1 and not final_hits:
            final_bar = max((d for d in window.downbeats if d > start), default=None)
            if final_bar is not None and end - final_bar >= 100:
                # A long ringing tail after the last bar keeps playing until the
                # last few seconds, so the whole display is not on for long.
                closing = max(final_bar, end - CLOSING_LENGTH)
                end = closing
        # A repeated part plays as its first occurrence did (same colors and looks).
        body = _Window(section_first[si], start, end,
                       tuple(b for b in window.beats if start <= b < end),
                       tuple(d for d in window.downbeats if d < end), False,
                       window.offset + sum(1 for b in window.beats if b < start),
                       window.beats_per_bar, window.bar_phase,
                       window.bar_offset + sum(1 for b in window.beats if b < start))
        everything = label == "finale"
        for phrase in _phrases(body, style.phrase_bars):
            k = section_phrase[si]
            section_phrase[si] += 1
            turn += 1
            beats_here = max(1, len(phrase.beats))
            phrase_hits = _hits_in(hits, phrase)
            sparkling = (sparkle is not None
                         and len(phrase_hits) / beats_here >= style.sparkle_density)
            lead_groups = _lead_groups(groups, section_turn[si] + k, section.level, everything,
                                       sparkle if sparkling else None, section_extra[si],
                                       style.leads)
            centerpiece = {p for g in groups if g.role in CENTERPIECE_ROLES
                           and section.level >= MID for p in g.props}
            steady_part = {p for p in active if p in base or p in centerpiece}
            variant = occurrence[si]
            flip = (section_flip[si] + k) % 2 == 1
            bars = _bars(phrase)
            if (style.call_and_response and section.level == MID and not everything
                    and k % 2 == 1
                    and len(lead_groups) >= 2 and len(bars) >= 2):
                # Call and response: the left half of the leads plays a bar, the
                # right half answers the next.
                half = len(lead_groups) // 2
                sides = [{p for g in lead_groups[:half] for p in g.props},
                         {p for g in lead_groups[half:] for p in g.props}]
                for j, (a, b) in enumerate(bars):
                    b = min(b, phrase.end) if j < len(bars) - 1 else phrase.end
                    a = phrase.start if j == 0 else a
                    bar = _Window(phrase.section_index, a, b,
                                  tuple(t for t in phrase.beats if a <= t < b),
                                  tuple(t for t in phrase.downbeats if a <= t < b), False,
                                  phrase.offset + sum(1 for t in phrase.beats if t < a),
                                  phrase.beats_per_bar, phrase.bar_phase,
                                  phrase.bar_offset + sum(1 for t in phrase.beats if t < a))
                    _look(planner, bar, rows, singles,
                          steady_part | (sides[j % 2] & active), variant=variant, flip=flip)
                moments.append(("call_and_response", phrase.start))
            else:
                leads = {p for g in lead_groups for p in g.props}
                _look(planner, phrase, rows, singles, steady_part | (leads & active),
                      variant=variant, flip=flip)
            if sparkling and sparkle is not None:
                _sparkle(planner, phrase, [p for p in sparkle.props if p in active],
                         phrase_hits)
        if closing is not None:
            # The song's last bar: everything still in use fades out, the edges of the
            # yard first and the middle last.
            xs = {pid: (display.props[pid].center or (0.0, 0.0))[0] for pid in active}
            if xs:
                middle = (min(xs.values()) + max(xs.values())) / 2
                nearest = min(abs(x - middle) for x in xs.values())
                reach = max(abs(x - middle) for x in xs.values()) - nearest or 1.0
            for pid in sorted(active):
                # 0 for the prop nearest the middle (it fades to the very end), 1 at
                # the edges.
                edge = (abs(xs[pid] - middle) - nearest) / reach
                fade_end = window.end - round(edge * (window.end - closing) * 0.4)
                planner.light(pid, si, closing, max(closing + 10, fade_end), "fade", 100, 0)

    held = set(keep_spans) | singing
    # The glow: props that are not leading stay lit and move by brightness, hitting
    # together on the beat. Dark where the song goes quiet; it fades up through a
    # quiet intro and, when the song does not end on hits, fades out over the last
    # part. Nothing glows after the closing hits begin.
    dark = _low_spans(music, GLOW_QUIET, GLOW_QUIET_SPAN)
    if final_hits:
        dark.append((final_hits[0], music.duration))
    for window in windows:
        section = sections[window.section_index]
        spec = style.glow[section.level]
        if spec is None:
            continue
        ramp = None
        if window.section_index == 0 and section.label == "intro":
            ramp = (0, spec[1])
        elif window is last_window and not final_hits and section.level < HIGH:
            ramp = (spec[1], 0)
        props = sorted(p for p in active_in(window) - held
                       if display.props[p].role in PULSE_ROLES | BED_ROLES)
        _glow(planner, canvas, window, props, spec, dark, ramp)
        _snow_bed(planner, window, active_in(window) - held, dark)

    # Build-ups: the last phrase before a louder part rises from half brightness.
    for index, section in enumerate(sections[:-1]):
        if sections[index + 1].level <= section.level:
            continue
        bars_in = [d for d in music.downbeats
                   if section.start_centisecond <= d < section.end_centisecond]
        if len(bars_in) < BARS_PER_PHRASE + 1:
            continue
        rise = bars_in[-BARS_PER_PHRASE]
        _swell(canvas, rise, section.end_centisecond, low=style.build_from, exclude=held)
        moments.append(("build", rise))

    # Entering a louder part: a gentle style fades it in over its first bar; a
    # punchy one blacks out the beat before it, so the flash that opens it lands.
    for window in swells:
        bars_here = _bars(window)
        rise_end = bars_here[0][1] if bars_here else window.start + 200
        _swell(canvas, window.start, min(window.end, rise_end), low=0.15, exclude=held | base)
    for window in drops:
        before = [b for b in music.beats if b < window.start]
        if len(before) >= 2:
            _darken(canvas, before[-1], window.start, keep=held | base)
            moments.append(("drop", before[-1]))

    # A bar that leaves the song's home harmony (a borrowed chord, a key change): in a
    # mid or loud part, the yard drops low for the bar and the showpiece carries it.
    feature = _feature(display, usable - singing)
    bar_length = (sorted(b - a for a, b in itertools.pairwise(music.downbeats))
                  [len(music.downbeats) // 2 - 1] if len(music.downbeats) > 2 else 200)
    for time in _times(analysis, "harmonic_departures"):
        part = next((s for s in sections if s.start_centisecond <= time < s.end_centisecond),
                    None)
        if part is None or part.level < MID or (final_hits and time >= final_hits[0]):
            continue
        end = min(part.end_centisecond,
                  next((d for d in music.downbeats if d > time + 10), time + bar_length))
        _dim(canvas, time, end, DEPARTURE_LEVEL, held | ({feature} if feature else set()))
        moments.append(("departure", time))

    # Signature moments flash everything in use for a moment: cymbal crashes in
    # mid and loud parts, and the first beat back after a hard stop.
    stop_ends = {end for _, end in music.stops}
    flashes: list[tuple[str, int, _Window]] = []
    for crash in _times(analysis, "crashes") if style.flashes else []:
        home = next((w for w in windows if w.start + 25 <= crash < w.end - 10), None)
        if home is None or sections[home.section_index].level < MID:
            continue
        if flashes and crash - flashes[-1][1] < style.crash_spacing:
            continue
        flashes.append(("crash", crash, home))
    for window in windows:
        if (style.flashes and window.start in stop_ends and not window.accent
                and window.beats):
            flashes.append(("return", window.start, window))
    beat_gaps = [b - a for a, b in itertools.pairwise(music.beats)]
    beat = sorted(beat_gaps)[len(beat_gaps) // 2] if beat_gaps else 50
    for kind, time, window in sorted(flashes, key=lambda f: f[1]):
        stop = min(window.end, time + min(style.flash_length, max(10, beat)))
        flashed = 0
        for pid in sorted(active_in(window)):
            for channel in planner.channels(pid, window.section_index):
                flashed += _punch(canvas, pid, channel, time, stop, planner.color(pid, channel))
        if flashed:
            moments.append((kind, time))
    # Stabs: the song's strongest hits, on the beat or between, light a chunk of the
    # yard, taking turns group by group, so the lights play the song's accents and
    # not only its pulse.
    stabbed = _stabs(planner, analysis, windows, sections, groups, active_in,
                     {t for _, t in moments} | {t for _, t, _ in flashes}, beat)
    if stabbed:
        moments.append(("stabs", stabbed[0]))
    # Lyric cues: a prop the singer names lights on the word.
    for time, props in _lyric_cues(analysis, display, usable - held, music.duration,
                                   constraints.word_cues):
        if final_hits and time >= final_hits[0]:
            continue
        heard = next((w for w in windows if w.start <= time < w.end), None)
        if heard is None:
            continue
        stop = min(heard.end, time + beat)
        cued = 0
        for pid in props:
            if pid not in active_in(heard):
                continue
            for channel in planner.channels(pid, heard.section_index):
                cued += _punch(canvas, pid, channel, time, stop, planner.color(pid, channel))
        if cued:
            moments.append(("lyric_cue", time))
    if final_hits and last_window is not None:
        _finale(planner, final_hits, sorted(active_in(last_window)), held)
        moments.append(("finale_hits", final_hits[0]))
    # Where the song is silent, and where the rules ask every prop to stay dark.
    quiet = _quiet_spans(music) + [(w.start, w.end) for w in windows
                                   if not active_in(w) and not held]

    def calm(window: _Window) -> list[str]:
        here = active_in(window) - held
        steady = sorted(p for p in here if p in base)
        if steady:
            return steady
        if feature in here:
            return [feature] if feature else []
        return sorted(here)

    filled = _fill_dead_air(planner, canvas, music, windows, calm, usable, quiet)
    if filled:
        moments.extend(("calm_base", a) for a, _ in filled)
    # The grid is the sixteenth notes plus the stabs, which keep the song's own timing.
    _on_one_grid(canvas, sorted(set(_sixteenths(music, sections)) | set(stabbed)), singing)

    if moments:
        counts: dict[str, int] = defaultdict(int)
        for kind, _ in moments:
            counts[kind] += 1
        names = {"repeat": "repeated part(s) reuse their first look",
                 "lift": "louder part(s) open with an accent",
                 "drop": "dark beat(s) before a louder part",
                 "variation": "returning part(s) move a new way",
                 "finale_hits": "closing hits staged across the yard",
                 "departure": "unexpected chord(s) carried by the showpiece",
                 "lyric_cue": "lyric cue(s) light the prop the words name",
                 "call_and_response": "phrase(s) of call and response",
                 "build": "build-up(s) before a louder part",
                 "crash": "crash(es) flash the display",
                 "return": "return(s) from a stop flash the display",
                 "calm_base": "dark stretch(es) given a calm base",
                 "bridge": "bridge(s) led by other props, moving the other way"}
        notes.append("Arrangement: " + "; ".join(
            f"{counts[kind]} {names[kind]}" for kind in names if counts[kind]) + ".")

    for pid, (anchors, floor) in constraints.anchors.items():
        _anchor(canvas, pid, display.props[pid].channel_count, anchors, floor)
    for source, targets in constraints.copies.items():
        for pid, channel in targets:
            canvas.effects[(pid, channel)] = [
                dataclasses.replace(e, prop_id=pid, channel_index=channel, color=None,
                                    movement_id=None)
                for e in canvas.effects.get(source, [])]
    effects = tuple(sorted(
        (e for items in canvas.effects.values() for e in _joined(items)),
        key=lambda e: (e.start_centisecond, e.prop_id, e.channel_index),
    ))
    used = {e.prop_id for e in effects}
    notes.append(_effect_kinds(effects, canvas.movements))
    for pid in sorted(usable - used, key=lambda p: display.props[p].name):
        notes.append(f"{display.props[pid].name} had no part in this song's plan.")
    for pid, leader in sorted(constraints.followers.items(),
                              key=lambda item: display.props[item[0]].name):
        notes.append(f"{display.props[pid].name} is wired to the same circuit as {leader}, "
                     "so it shows the same light.")
    for _, kind, required in constraints.directions:
        if not any(m.direction == required for m in canvas.movements if m.kind == kind):
            notes.append(f"No {kind} could run {required.replace('_', ' ')} as required; those "
                         "props held steady instead.")
    choreography = Choreography(
        duration_centiseconds=music.duration,
        effects=effects,
        movements=tuple(canvas.movements),
        sections=tuple(Section(s.label, s.start_centisecond, s.end_centisecond)
                       for s in sections),
        hard_stops_centiseconds=tuple(start for start, _ in music.stops),
        vocal_regions=None if vocals is None else tuple(regions),
    )
    excused = [(t, t + max(beat, style.flash_length)) for kind, t in moments
               if kind in {"crash", "return", "lyric_cue", "lift"}]
    if final_hits:
        excused.append((final_hits[0] - 200, music.duration))
    phrase_spans = [(p.start, p.end) for w in windows for p in _phrases(w)]
    quality = check_quality(
        effects, music.duration, usable,
        {p: display.props[p].role for p in usable},
        [(s.start_centisecond, s.end_centisecond, s.level) for s in sections],
        _music_marks(analysis, music, sections), phrase_spans, quiet, excused, filled,
        canvas.movements, style.profile, style.name, beat,
        sum(1 for kind, _ in moments if kind in ACCENT_MOMENTS),
        {pid for targets in constraints.copies.values() for pid, _ in targets})
    notes.append(quality.summary())
    return Plan(
        choreography=choreography,
        sections=tuple(sections),
        used_props=tuple(sorted(display.props[p].name for p in used)),
        skipped_props=tuple(sorted(
            (SkippedProp(display.props[p].name, reason)
             for p, reason in constraints.excluded.items()),
            key=lambda s: s.name,
        )),
        notes=tuple(notes),
        moments=tuple(sorted(moments, key=lambda m: (m[1], m[0]))),
        quality=quality,
    )

