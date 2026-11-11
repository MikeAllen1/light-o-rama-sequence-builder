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

Singing-face mouths are never animated here; that needs vocal analysis
(Phase 8). Everything is deterministic: the same inputs give the same plan.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from lor_sequence_builder.choreography import Choreography, Effect, Movement, Section
from lor_sequence_builder.rules import RuleSet, select_props
from lor_sequence_builder.rules.engine import Display, DisplayProp

LOW, MID, HIGH = 0, 1, 2
LEVEL_NAMES = ("low", "mid", "high")
FALLBACK_BPM = 120
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


def _music(analysis: dict[str, Any]) -> _Music:
    try:
        duration = _cs(float(analysis["audio"]["duration_seconds"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanningError("Analysis is missing the audio duration") from exc
    if duration <= 0:
        raise PlanningError("Analysis has no audio duration")
    notes: list[str] = []
    beats = [b for b in _times(analysis, "beats") if 0 <= b < duration]
    if len(beats) < 8:
        step = round(6000 / FALLBACK_BPM)
        beats = list(range(0, duration, step))
        notes.append(f"No usable beat grid; planned on a steady {FALLBACK_BPM} BPM grid instead.")
    beat_set = set(beats)
    downbeats = [d for d in _times(analysis, "downbeats") if d in beat_set]
    if len(downbeats) < 2:
        downbeats = beats[::4]
        notes.append("No usable bar starts; assumed a bar every four beats.")
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
    return _Music(duration, beats, downbeats, energy, starts, stops, notes)


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
    low, high = min(raw), max(raw)
    relative = [(v - low) / (high - low) if high > low else 0.5 for v in raw]
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
        sections.append(PlannedSection(label, level, start, end, rel))
    return sections


@dataclass(frozen=True, slots=True)
class _Window:
    """Part of a section between hard stops. Motion lives inside one window."""

    section_index: int
    start: int
    end: int
    beats: tuple[int, ...]
    downbeats: tuple[int, ...]
    accent: bool


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


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _named(name: str, words: list[str]) -> bool:
    found = _words(name)
    return any(_words(word) <= found for word in words)


def _constraints(display: Display, rule_set: RuleSet) -> _Constraints:
    c = _Constraints()
    mouth_words = list({
        *rule_set.rules["face_outline_with_mouth"].params.get("mouth_names", []),
        *rule_set.rules["mouths_only_during_vocals"].params.get("mouth_names", []),
    })
    for prop in display.props.values():
        if prop.linked_to is not None:
            master = display.props.get(prop.linked_to)
            c.excluded[prop.prop_id] = (
                f"driven by its master prop {master.name if master else '(missing)'}")
        elif prop.layout_problem is not None:
            c.excluded[prop.prop_id] = f"cannot be sequenced yet: {prop.layout_problem}"
        elif prop.role == "singing_face" and _named(prop.name, mouth_words):
            c.excluded[prop.prop_id] = "mouth animation needs vocal analysis (Phase 8)"
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
        if req.type == "move_direction":
            c.directions.append((set(chosen), req.params.get("movement", "chase"),
                                 req.params["direction"]))
    for pid in c.excluded:
        c.channels.pop(pid, None)
        c.keep_on.pop(pid, None)
    return c


@dataclass(frozen=True, slots=True)
class _Row:
    role: str
    props: tuple[str, ...]
    direction: str


def _rows(display: Display, usable: set[str]) -> tuple[list[_Row], list[str]]:
    keyed: dict[tuple[str, str | None, int | None], list[DisplayProp]] = defaultdict(list)
    for prop in display.props.values():
        if prop.prop_id in usable and prop.position_in_row is not None:
            keyed[(prop.role, prop.group, prop.row_size)].append(prop)
    rows: list[_Row] = []
    in_rows: set[str] = set()
    for (role, _, _), members in sorted(keyed.items(), key=lambda kv: str(kv[0])):
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


def _beat_length(window: _Window, index: int) -> int:
    beats = window.beats
    if index + 1 < len(beats):
        return beats[index + 1] - beats[index]
    if len(beats) >= 2:
        return min(beats[-1] - beats[-2], window.end - beats[index])
    return window.end - beats[index]


def _bars(window: _Window) -> list[tuple[int, int]]:
    marks = list(window.downbeats) or list(window.beats[::4])
    bars = [(a, b) for a, b in itertools.pairwise(marks)]
    if marks and window.end - marks[-1] >= 50:
        typical = bars[-1][1] - bars[-1][0] if bars else window.end - marks[-1]
        bars.append((marks[-1], min(window.end, marks[-1] + typical)))
    return bars


@dataclass
class _Planner:
    display: Display
    constraints: _Constraints
    sections: list[PlannedSection]
    canvas: _Canvas
    movement_counter: int = 0

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
              movement: str | None = None) -> bool:
        placed = False
        for ch in self.channels(pid, section_index):
            placed |= self.canvas.put(pid, ch, start, end, kind, intensity, end_intensity,
                                      self.color(pid, ch), movement)
        return placed

    def direction_for(self, row: _Row, kind: str, flip: bool) -> tuple[tuple[str, ...], str]:
        props, natural = row.props, row.direction
        for chosen, movement_kind, required in self.constraints.directions:
            if movement_kind == kind and set(props) <= chosen:
                if required == natural:
                    return props, natural
                if required == _OPPOSITE.get(natural):
                    return tuple(reversed(props)), required
                raise _CannotHonor(required)
        if flip:
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
              intensity: int, flip: bool) -> bool:
        try:
            order, direction = self.direction_for(_Row(row.role, tuple(props), row.direction),
                                                  "chase", flip)
        except _CannotHonor:
            return False
        beats = window.beats
        n = len(order)
        index = 0
        placed = False
        while index + (n - 1) * every < len(beats):
            steps = [index + i * every for i in range(n)]
            end = beats[steps[-1]] + _beat_length(window, steps[-1])
            start = beats[steps[0]]
            if end > window.end:
                break
            movement_id = self.movement("chase", order, direction, start, end)
            for pid, step in zip(order, steps, strict=True):
                length = _beat_length(window, step) * every
                stop = min(beats[step] + length, end)
                self.light(pid, window.section_index, beats[step], stop,
                           "fade" if every > 1 else "on", intensity,
                           0 if every > 1 else None, movement_id)
            placed = True
            index += n * every
        return placed

    def fill(self, row: _Row, props: list[str], window: _Window, flip: bool) -> bool:
        try:
            order, direction = self.direction_for(_Row(row.role, tuple(props), row.direction),
                                                  "fill", flip)
        except _CannotHonor:
            return False
        placed = False
        for bar_start, bar_end in _bars(window):
            step = (bar_end - bar_start) // len(order)
            if step < 5:
                continue
            movement_id = self.movement("fill", order, direction, bar_start, bar_end)
            for i, pid in enumerate(order):
                self.light(pid, window.section_index, bar_start + i * step, bar_end,
                           movement=movement_id)
            placed = True
        return placed

    def alternate(self, props: list[str], window: _Window) -> None:
        for b, beat in enumerate(window.beats):
            for i, pid in enumerate(props):
                if i % 2 == b % 2:
                    self.light(pid, window.section_index, beat,
                               beat + _beat_length(window, b), intensity=90)

    def pulse(self, pid: str, window: _Window, marks: str = "beats", intensity: int = 100
              ) -> None:
        if marks == "beats":
            times = list(window.beats)
        else:
            times = [a for a, _ in _bars(window)]
        for i, t in enumerate(times):
            following = times[i + 1] if i + 1 < len(times) else window.end
            length = max(5, (following - t) // 2)
            self.light(pid, window.section_index, t, min(window.end, t + length),
                       intensity=intensity)

    def steady(self, pid: str, window: _Window, intensity: int, kind: str = "on") -> None:
        self.light(pid, window.section_index, window.start, window.end, kind, intensity)

    def rotate(self, pid: str, window: _Window, intensity: int, per_beat: int) -> None:
        """Step through a multi-segment prop's channels in order, like a spinning tree."""
        allowed = self.constraints.channels[pid]
        count = len(allowed)
        times: list[int] = []
        for b, beat in enumerate(window.beats):
            length = _beat_length(window, b)
            times.extend(beat + (length * k) // per_beat for k in range(per_beat))
        times.append(window.end)
        width = 2 if count >= 4 else 1
        for k in range(len(times) - 1):
            channel = allowed[k % count]
            end = times[min(k + width, len(times) - 1)]
            self.canvas.put(pid, channel, times[k], end, "on", intensity,
                            color=self.color(pid, channel))


class _CannotHonor(Exception):
    pass


def _look(planner: _Planner, window: _Window, rows: list[_Row], singles: list[str],
          active: set[str]) -> None:
    section = planner.sections[window.section_index]
    level = section.level
    flip = (window.section_index % 2) == 1

    for row in rows:
        members = [pid for pid in row.props if pid in active]
        if not members:
            continue
        if len(members) == 1:
            singles = [*singles, members[0]]
            continue
        moved = True
        if row.role == "mini_tree":
            if level == MID:
                planner.alternate(members, window)
            elif level == HIGH:
                for pid in members:
                    planner.pulse(pid, window)
        elif row.role == "arch":
            if level == LOW:
                moved = planner.chase(row, members, window, every=2, intensity=80, flip=flip)
            elif level == MID:
                moved = planner.chase(row, members, window, every=1, intensity=100, flip=flip)
            else:
                moved = planner.fill(row, members, window, flip=flip)
        elif level == LOW:
            for pid in members:
                planner.steady(pid, window, 60)
        elif level == MID:
            moved = planner.chase(row, members, window, every=1, intensity=100, flip=flip)
        else:
            moved = planner.fill(row, members, window, flip=flip)
        if not moved:
            for pid in members:
                planner.steady(pid, window, 60 if level == LOW else 90)

    for pid in singles:
        if pid not in active:
            continue
        prop = planner.display.props[pid]
        channels = len(planner.constraints.channels[pid])
        multi = channels >= 3 and prop.color_kind != "color_per_channel"
        if prop.role == "mega_tree" or (multi and prop.role in {"icicles", "outline"}):
            speed = {LOW: 1, MID: 1, HIGH: 2}[level]
            planner.rotate(pid, window, {LOW: 60, MID: 100, HIGH: 100}[level], speed)
        elif prop.role == "star":
            if level == HIGH:
                planner.steady(pid, window, 100, "twinkle")
            else:
                planner.steady(pid, window, 100)
        elif prop.role == "snowflake":
            if level == MID:
                planner.pulse(pid, window, "bars")
            elif level == HIGH:
                planner.steady(pid, window, 100, "twinkle")
        elif prop.role == "outline":
            if level == HIGH:
                planner.pulse(pid, window)
            else:
                planner.steady(pid, window, 50 if level == LOW else 80)
        elif prop.role == "singing_face":
            if level >= MID:
                planner.steady(pid, window, 100)
        elif prop.role == "decor":
            if level == HIGH:
                planner.pulse(pid, window, "bars")
            else:
                planner.steady(pid, window, 70 if level == LOW else 100)
        elif level >= MID:
            planner.steady(pid, window, 60 if level == MID else 80)


def _accent(planner: _Planner, window: _Window, active: set[str]) -> int:
    """A louder section opens with everything it uses flashing and fading over a beat."""
    if not window.accent or not window.beats:
        return window.start
    end = min(window.end, window.start + _beat_length(window, 0))
    for pid in sorted(active):
        planner.light(pid, window.section_index, window.start, end, "fade", 100, 0)
    return end


def plan_show(analysis: dict[str, Any], display: Display, rule_set: RuleSet) -> Plan:
    music = _music(analysis)
    sections = _sections(music)
    windows = _windows(music, sections)
    constraints = _constraints(display, rule_set)
    canvas = _Canvas(constraints.caps)
    planner = _Planner(display, constraints, sections, canvas)
    notes = list(music.notes)
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
    rows, singles = _rows(display, usable)
    for window in windows:
        label = sections[window.section_index].label.lower()
        active = {
            pid for pid in usable
            if label not in constraints.quiet.get(pid, set())
            and not any(a < window.end and window.start < b
                        for a, b in keep_spans.get(pid, []))
        }
        start = _accent(planner, window, active)
        body = _Window(window.section_index, start, window.end,
                       tuple(b for b in window.beats if b >= start),
                       tuple(d for d in window.downbeats if d >= start), False)
        _look(planner, body, rows, singles, active)

    effects = tuple(sorted(
        (e for items in canvas.effects.values() for e in items),
        key=lambda e: (e.start_centisecond, e.prop_id, e.channel_index),
    ))
    used = {e.prop_id for e in effects}
    for pid in sorted(usable - used, key=lambda p: display.props[p].name):
        notes.append(f"{display.props[pid].name} had no part in this song's plan.")
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
        vocal_regions=None,
    )
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
    )

