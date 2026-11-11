"""Check a choreography Timeline against the active rule set.

Every rule reports one of four outcomes:

- ``passed``: the rule applied and nothing broke it.
- ``failed``: one or more findings, each naming the prop, channel and time.
- ``not_applicable``: the display or the song has nothing the rule is about
  (no faces, no falls, no vocal analysis yet). This is never counted as passed.
- ``off``: a profile turned the rule off.

Rules never repair the choreography. Error findings stop the writer; warning
findings go in the report.
"""

from __future__ import annotations

import fnmatch
import itertools
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from lor_sequence_builder.choreography import Choreography, Effect, Movement, seconds
from lor_sequence_builder.classifier import (
    PropClassification,
    classify_preview,
    prop_center,
)
from lor_sequence_builder.new_sequence import channel_layout_problem
from lor_sequence_builder.rules.profile import (
    RULE_SPECS,
    Requirement,
    RuleSet,
    RuleSettings,
)

_ROW_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: str
    message: str
    prop_id: str | None = None
    prop_name: str | None = None
    channel_index: int | None = None
    centisecond: int | None = None

    def describe(self) -> str:
        where = []
        if self.prop_name is not None:
            where.append(self.prop_name)
        if self.channel_index is not None:
            where.append(f"channel {self.channel_index + 1}")
        if self.centisecond is not None:
            where.append(f"at {seconds(self.centisecond)}")
        prefix = f"{' '.join(where)}: " if where else ""
        return f"{prefix}{self.message}"


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    title: str
    severity: str
    status: str
    reason: str = ""
    findings: tuple[Finding, ...] = ()
    source: str = "default.yaml"


@dataclass(frozen=True, slots=True)
class RuleReport:
    results: tuple[RuleResult, ...]
    rule_set: RuleSet

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for r in self.results for f in r.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for r in self.results for f in r.findings if f.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for result in self.results:
            counts[result.status] += 1
        return {
            "ok": self.ok,
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                **{status: counts[status] for status in
                   ("passed", "failed", "not_applicable", "off")},
            },
            "results": [
                {
                    "rule_id": r.rule_id,
                    "title": r.title,
                    "severity": r.severity,
                    "status": r.status,
                    "reason": r.reason,
                    "source": r.source,
                    "findings": [
                        {
                            "severity": f.severity,
                            "message": f.message,
                            "prop_id": f.prop_id,
                            "prop_name": f.prop_name,
                            "channel_index": f.channel_index,
                            "centisecond": f.centisecond,
                            "time": None if f.centisecond is None else seconds(f.centisecond),
                        }
                        for f in r.findings
                    ],
                }
                for r in self.results
            ],
            "effective_profile": self.rule_set.to_dict(),
        }

    def format_text(self, max_findings_per_rule: int = 10) -> str:
        lines: list[str] = []
        for result in self.results:
            label = {
                "passed": "PASS",
                "failed": "FAIL" if result.severity == "error" else "WARN",
                "not_applicable": "N/A ",
                "off": "OFF ",
            }[result.status]
            line = f"{label} {result.rule_id}: {result.title}"
            if result.reason:
                line += f" ({result.reason})"
            lines.append(line)
            for finding in result.findings[:max_findings_per_rule]:
                lines.append(f"       - {finding.describe()}")
            hidden = len(result.findings) - max_findings_per_rule
            if hidden > 0:
                lines.append(f"       ... and {hidden} more (see the JSON report)")
        lines.append(
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)."
            + ("" if self.ok else " The sequence will not be written until errors are fixed.")
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class DisplayProp:
    prop_id: str
    name: str
    role: str
    channel_count: int
    color_kind: str
    channel_colors: tuple[str, ...]
    linked_to: str | None
    layout_problem: str | None
    center: tuple[float, float] | None
    direction: str
    group: str | None
    position_in_row: int | None
    row_size: int | None
    figure: tuple[str, ...] = field(default_factory=tuple)

    @property
    def sequenceable(self) -> bool:
        return self.linked_to is None and self.layout_problem is None


@dataclass(frozen=True, slots=True)
class Display:
    props: dict[str, DisplayProp]
    groups: dict[str, tuple[str, ...]]

    @property
    def sequenceable_channels(self) -> int:
        return sum(p.channel_count for p in self.props.values() if p.sequenceable)


def display_from_preview(preview: ET.Element) -> Display:
    """Everything the rules need to know about the display, from the preview alone."""
    classifications = classify_preview(preview)
    elements = {p.get("id", ""): p for p in preview.findall("PropClass")}
    name_to_ids: dict[str, list[str]] = defaultdict(list)
    for c in classifications:
        name_to_ids[c.name].append(c.prop_id)
    props: dict[str, DisplayProp] = {}
    for c in classifications:
        element = elements[c.prop_id]
        props[c.prop_id] = DisplayProp(
            prop_id=c.prop_id,
            name=c.name,
            role=c.role,
            channel_count=c.channel_count,
            color_kind=c.color_capability.kind,
            channel_colors=_channel_colors(c),
            linked_to=c.linked_to,
            layout_problem=channel_layout_problem(element),
            center=prop_center(element),
            direction=c.direction,
            group=c.group,
            position_in_row=c.position_in_row,
            row_size=c.row_size,
            figure=tuple(
                pid for name in c.figure for pid in name_to_ids.get(name, [])
                if len(name_to_ids[name]) == 1
            ),
        )
    group_members: dict[str, list[str]] = defaultdict(list)
    for group in preview.findall("PropGroup"):
        name = group.get("Name", "")
        if name:
            # A display name is the public selector key. Preserve every matching
            # group's members rather than silently replacing earlier groups.
            group_members[name].extend(m.get("id", "") for m in group.findall("member"))
    groups = {name: tuple(dict.fromkeys(ids)) for name, ids in group_members.items()}
    return Display(props, groups)


def _channel_colors(c: PropClassification) -> tuple[str, ...]:
    colors = c.color_capability.colors
    if c.color_capability.kind == "color_per_channel":
        return tuple(colors[i] if i < len(colors) else "" for i in range(c.channel_count))
    if c.color_capability.kind == "single_color" and colors:
        return (colors[0],) * c.channel_count
    return ("",) * c.channel_count


# ---------------------------------------------------------------- helpers


def _lit(effect: Effect) -> bool:
    return max(effect.start_intensity, effect.end_intensity) > 0


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _first_gap(covered: list[tuple[int, int]], start: int, end: int) -> int | None:
    """First centisecond in [start, end) that ``covered`` does not cover."""
    cursor = start
    for a, b in covered:
        if b <= cursor:
            continue
        if a > cursor:
            return cursor
        cursor = b
        if cursor >= end:
            return None
    return cursor if cursor < end else None


def _subtract(
    spans: list[tuple[int, int]], remove: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in spans:
        pieces = [(start, end)]
        for a, b in remove:
            next_pieces: list[tuple[int, int]] = []
            for s, e in pieces:
                if b <= s or a >= e:
                    next_pieces.append((s, e))
                    continue
                if s < a:
                    next_pieces.append((s, a))
                if b < e:
                    next_pieces.append((b, e))
            pieces = next_pieces
        result.extend(pieces)
    return result


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _named(name: str, words: list[str]) -> bool:
    found = _words(name)
    return any(set(_words(word)) <= found for word in words)


@dataclass
class _Context:
    display: Display
    choreography: Choreography
    settings: RuleSettings
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        message: str,
        effect: Effect | None = None,
        prop_id: str | None = None,
        centisecond: int | None = None,
        channel_index: int | None = None,
    ) -> None:
        pid = effect.prop_id if effect is not None else prop_id
        prop = self.display.props.get(pid) if pid is not None else None
        self.findings.append(Finding(
            rule_id=self.settings.rule_id,
            severity=self.settings.severity,
            message=message,
            prop_id=pid,
            prop_name=prop.name if prop is not None else pid,
            channel_index=effect.channel_index if effect is not None else channel_index,
            centisecond=(
                centisecond if centisecond is not None
                else effect.start_centisecond if effect is not None else None
            ),
        ))

    def valid_effects(self) -> list[Effect]:
        """Effects that point at a real, sequenceable channel and a sane time span."""
        out = []
        for e in self.choreography.effects:
            prop = self.display.props.get(e.prop_id)
            if (
                prop is not None and prop.sequenceable
                and 0 <= e.channel_index < prop.channel_count
                and e.start_centisecond < e.end_centisecond
            ):
                out.append(e)
        return out

    def lit_by_prop(self) -> dict[str, list[tuple[int, int]]]:
        spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for e in self.valid_effects():
            if _lit(e):
                spans[e.prop_id].append((e.start_centisecond, e.end_centisecond))
        return {pid: _merge(items) for pid, items in spans.items()}


# Each check returns None when it applied, or a reason it was not applicable.
_Check = Callable[[_Context], str | None]


# ---------------------------------------------------------------- built-in rules


def _effects_well_formed(ctx: _Context) -> str | None:
    duration = ctx.choreography.duration_centiseconds
    if duration <= 0:
        ctx.add(f"Timeline duration must be positive, found {duration}")
    for e in ctx.choreography.effects:
        if e.start_centisecond < 0:
            ctx.add("Effect starts before the song does", e)
        if e.end_centisecond > duration:
            ctx.add(f"Effect ends at {seconds(e.end_centisecond)}, after the song ends "
                    f"at {seconds(duration)}", e)
        if e.end_centisecond <= e.start_centisecond:
            ctx.add("Effect ends before it starts or has no length", e)
        for label, value in (("start", e.start_intensity), ("end", e.end_intensity)):
            if not 0 <= value <= 100:
                ctx.add(f"Effect {label} intensity {value} is outside 0-100", e)
        if e.kind != "fade" and e.start_intensity != e.end_intensity:
            ctx.add(f"A {e.kind} effect holds one intensity; use a fade to change it", e)
        if e.kind == "fade" and e.start_intensity == e.end_intensity:
            ctx.add("A fade must change intensity; use an on effect to hold one", e)
    seen_movement_ids: set[str] = set()
    duplicate_movement_ids: set[str] = set()
    for movement in ctx.choreography.movements:
        movement_id = movement.movement_id
        if movement_id in seen_movement_ids:
            duplicate_movement_ids.add(movement_id)
        else:
            seen_movement_ids.add(movement_id)
    for movement_id in sorted(duplicate_movement_ids):
        ctx.add(f"Movement id {movement_id!r} is used more than once")
    for m in ctx.choreography.movements:
        if not 0 <= m.start_centisecond < m.end_centisecond <= duration:
            ctx.add(f"Movement {m.movement_id!r} must start before it ends, inside the song",
                    centisecond=m.start_centisecond)
    for s in ctx.choreography.sections:
        if not 0 <= s.start_centisecond < s.end_centisecond <= duration:
            ctx.add(f"Section {s.label!r} must start before it ends, inside the song",
                    centisecond=s.start_centisecond)
    for stop in ctx.choreography.hard_stops_centiseconds:
        if not 0 <= stop <= duration:
            ctx.add("Hard stop is outside the song", centisecond=stop)
    for start, end in ctx.choreography.vocal_regions or ():
        if not 0 <= start < end <= duration:
            ctx.add("Vocal region must start before it ends, inside the song", centisecond=start)
    return None


def _known_props_and_channels(ctx: _Context) -> str | None:
    for e in ctx.choreography.effects:
        prop = ctx.display.props.get(e.prop_id)
        if prop is None:
            ctx.add(f"Prop id {e.prop_id!r} is not in the preview", e)
        elif prop.linked_to is not None:
            master = ctx.display.props.get(prop.linked_to)
            master_name = master.name if master is not None else prop.linked_to
            ctx.add(
                f"This prop is driven by its master prop {master_name}; put the effect on "
                "the master",
                e,
            )
        elif prop.layout_problem is not None:
            ctx.add(f"This prop cannot be sequenced yet: {prop.layout_problem}", e)
        elif not 0 <= e.channel_index < prop.channel_count:
            ctx.add(
                f"Channel {e.channel_index + 1} does not exist; this prop has "
                f"{prop.channel_count} channel(s)",
                e,
            )
    for m in ctx.choreography.movements:
        for pid in m.prop_ids:
            prop = ctx.display.props.get(pid)
            if prop is None or not prop.sequenceable:
                ctx.add(f"Movement {m.movement_id!r} uses a prop that cannot be sequenced",
                        prop_id=pid, centisecond=m.start_centisecond)
    return None


def _no_overlapping_effects(ctx: _Context) -> str | None:
    by_channel: dict[tuple[str, int], list[Effect]] = defaultdict(list)
    for e in ctx.choreography.effects:
        by_channel[(e.prop_id, e.channel_index)].append(e)
    for effects in by_channel.values():
        ordered = sorted(effects, key=lambda e: (e.start_centisecond, e.end_centisecond))
        latest_end = -math.inf
        latest: Effect | None = None
        for e in ordered:
            if latest is not None and e.start_centisecond < latest_end:
                ctx.add(
                    f"Overlaps another effect on this channel that runs until "
                    f"{seconds(int(latest_end))}",
                    e,
                )
            if e.end_centisecond > latest_end:
                latest_end, latest = e.end_centisecond, e
    return None


def _movement_effects(ctx: _Context) -> dict[str, list[Effect]]:
    tagged: dict[str, list[Effect]] = defaultdict(list)
    for e in ctx.valid_effects():
        if e.movement_id is not None:
            tagged[e.movement_id].append(e)
    return tagged


def _movements_complete(ctx: _Context) -> str | None:
    movements = {m.movement_id: m for m in ctx.choreography.movements}
    tagged = _movement_effects(ctx)
    for movement_id, effects in tagged.items():
        if movement_id not in movements:
            ctx.add(f"Effect belongs to movement {movement_id!r}, which is not defined",
                    effects[0])
    if not movements:
        return "the Timeline has no movements"
    for m in movements.values():
        effects = tagged.get(m.movement_id, [])
        firsts: dict[str, int] = {}
        for e in effects:
            if e.prop_id not in m.prop_ids:
                ctx.add(f"Effect is tagged with movement {m.movement_id!r} but its prop is not "
                        "part of that movement", e)
            elif not (m.start_centisecond <= e.start_centisecond
                      and e.end_centisecond <= m.end_centisecond):
                ctx.add(f"Effect runs outside movement {m.movement_id!r} "
                        f"({seconds(m.start_centisecond)}-{seconds(m.end_centisecond)})", e)
            firsts[e.prop_id] = min(firsts.get(e.prop_id, e.start_centisecond),
                                    e.start_centisecond)
        missing = [pid for pid in m.prop_ids if pid not in firsts]
        for pid in missing:
            ctx.add(f"The {m.kind} {m.movement_id!r} never reaches this prop, so it stops "
                    "partway", prop_id=pid, centisecond=m.start_centisecond)
        reached = [firsts[pid] for pid in m.prop_ids if pid in firsts]
        for index, (before, after) in enumerate(itertools.pairwise(reached)):
            if after < before:
                pid = [p for p in m.prop_ids if p in firsts][index + 1]
                ctx.add(f"The {m.kind} {m.movement_id!r} reaches this prop before the one "
                        "listed ahead of it", prop_id=pid, centisecond=after)
    return None


def _ordered(values: list[float], increasing: bool) -> bool:
    pairs = itertools.pairwise(values)
    if increasing:
        return all(b > a + _ROW_TOLERANCE for a, b in pairs)
    return all(b < a - _ROW_TOLERANCE for a, b in pairs)


def _chases_follow_layout(ctx: _Context) -> str | None:
    moves = [m for m in ctx.choreography.movements
             if m.kind in {"chase", "fill"} and len(m.prop_ids) > 1]
    if not moves:
        return "the Timeline has no chases or fills across several props"
    for m in moves:
        props = [ctx.display.props.get(pid) for pid in m.prop_ids]
        if any(p is None for p in props):
            continue
        known = [p for p in props if p is not None]
        if m.direction in {"row_order", "reverse_row_order"}:
            positions = [p.position_in_row for p in known]
            if any(pos is None for pos in positions) or len(
                {(p.group, p.row_size, p.role) for p in known}
            ) != 1:
                ctx.add(f"The {m.kind} {m.movement_id!r} follows row order, but its props are "
                        "not one row in the preview", prop_id=m.prop_ids[0],
                        centisecond=m.start_centisecond)
            elif not _ordered([float(p or 0) for p in positions],
                              m.direction == "row_order"):
                ctx.add(f"The {m.kind} {m.movement_id!r} skips around instead of following "
                        "the row in order", prop_id=m.prop_ids[0],
                        centisecond=m.start_centisecond)
            continue
        centers = [p.center for p in known]
        if any(c is None for c in centers):
            ctx.add(f"Cannot check the {m.kind} {m.movement_id!r}: a prop has no position in "
                    "the preview", prop_id=m.prop_ids[0], centisecond=m.start_centisecond)
            continue
        axis = 0 if m.direction in {"left_to_right", "right_to_left"} else 1
        values = [c[axis] for c in centers if c is not None]
        increasing = m.direction in {"left_to_right", "bottom_to_top"}
        if not _ordered(values, increasing):
            ctx.add(f"The {m.kind} {m.movement_id!r} says {m.direction.replace('_', ' ')}, but "
                    "its props are not in that order in the preview", prop_id=m.prop_ids[0],
                    centisecond=m.start_centisecond)
    return None


def _falls_go_down(ctx: _Context) -> str | None:
    falls = [m for m in ctx.choreography.movements if m.kind == "fall"]
    if not falls:
        return "the Timeline has no falling effects"
    tagged = _movement_effects(ctx)
    for m in falls:
        if m.direction != "top_to_bottom":
            ctx.add(f"Fall {m.movement_id!r} runs {m.direction.replace('_', ' ')}; falls run "
                    "top to bottom", prop_id=m.prop_ids[0], centisecond=m.start_centisecond)
            continue
        props = [ctx.display.props.get(pid) for pid in m.prop_ids]
        if any(p is None for p in props):
            continue
        known = [p for p in props if p is not None]
        if len(known) > 1:
            centers = [p.center for p in known]
            if any(c is None for c in centers):
                ctx.add(f"Cannot check fall {m.movement_id!r}: a prop has no position in the "
                        "preview", prop_id=m.prop_ids[0], centisecond=m.start_centisecond)
            elif not _ordered([c[1] for c in centers if c is not None], increasing=False):
                ctx.add(f"Fall {m.movement_id!r} does not go from the highest prop to the "
                        "lowest", prop_id=m.prop_ids[0], centisecond=m.start_centisecond)
            continue
        prop = known[0]
        firsts: dict[int, int] = {}
        for e in tagged.get(m.movement_id, []):
            firsts[e.channel_index] = min(firsts.get(e.channel_index, e.start_centisecond),
                                          e.start_centisecond)
        if len(firsts) < 2:
            continue
        if prop.direction in {"left_to_right", "right_to_left"}:
            ctx.add(
                f"This prop's segments run {prop.direction.replace('_', ' ')}, so they cannot "
                "show a fall; use a chase", prop_id=prop.prop_id,
                centisecond=m.start_centisecond,
            )
            continue
        if prop.direction not in {"top_to_bottom", "bottom_to_top"}:
            ctx.add(
                "Cannot tell which end of this prop is the top; set its string start "
                "location in the S6 Preview Editor", prop_id=prop.prop_id,
                centisecond=m.start_centisecond,
            )
            continue
        order = [firsts[i] for i in sorted(firsts)]
        if prop.direction == "bottom_to_top":
            order.reverse()
        if any(b < a for a, b in itertools.pairwise(order)):
            ctx.add(f"Fall {m.movement_id!r} lights this prop's segments from the bottom up",
                    prop_id=prop.prop_id, centisecond=m.start_centisecond)
    return None


def _faces(ctx: _Context) -> list[set[str]]:
    seen: set[str] = set()
    faces: list[set[str]] = []
    for prop in ctx.display.props.values():
        if prop.role != "singing_face" or prop.prop_id in seen:
            continue
        members = {prop.prop_id, *prop.figure}
        seen |= members
        faces.append(members)
    return faces


def _effects_on(ctx: _Context, prop_ids: set[str]) -> list[Effect]:
    return [e for e in ctx.valid_effects() if e.prop_id in prop_ids and _lit(e)]


def _face_outline_with_mouth(ctx: _Context) -> str | None:
    faces = _faces(ctx)
    if not faces:
        return "the preview has no singing faces"
    outline_words = ctx.settings.params["outline_names"]
    mouth_words = ctx.settings.params["mouth_names"]
    applied = False
    for face in faces:
        mouths = {p for p in face if _named(ctx.display.props[p].name, mouth_words)}
        outlines = {p for p in face - mouths if _named(ctx.display.props[p].name, outline_words)}
        if not mouths or not outlines:
            continue
        applied = True
        lit = _merge((e.start_centisecond, e.end_centisecond)
                     for e in _effects_on(ctx, outlines))
        for e in _effects_on(ctx, mouths):
            gap = _first_gap(lit, e.start_centisecond, e.end_centisecond)
            if gap is not None:
                outline_names = ", ".join(sorted(ctx.display.props[p].name for p in outlines))
                ctx.add(f"Mouth is on while the face outline ({outline_names}) is off",
                        e, centisecond=gap)
    if not applied:
        return "no face in the preview has both a separate outline and mouth prop"
    return None


def _mouths_only_during_vocals(ctx: _Context) -> str | None:
    mouth_words = ctx.settings.params["mouth_names"]
    mouths = {
        pid for face in _faces(ctx) for pid in face
        if _named(ctx.display.props[pid].name, mouth_words)
    }
    if not mouths:
        return "the preview has no singing-face mouth props"
    if ctx.choreography.vocal_regions is None:
        return "vocals were not analyzed for this song yet"
    vocals = _merge(ctx.choreography.vocal_regions)
    for e in _effects_on(ctx, mouths):
        gap = _first_gap(vocals, e.start_centisecond, e.end_centisecond)
        if gap is not None:
            ctx.add("Mouth moves while nobody is singing", e, centisecond=gap)
    return None


def _single_color_only_where_possible(ctx: _Context) -> str | None:
    colored = [e for e in ctx.valid_effects() if e.color is not None]
    if not colored:
        return "no effect asks for a specific color"
    for e in colored:
        prop = ctx.display.props[e.prop_id]
        wanted = (e.color or "").strip().lower()
        if prop.color_kind == "combined_colors":
            ctx.add(f"Asks for {e.color}, but all colors on this strand share one circuit, "
                    "so no single color can be shown alone", e)
        elif prop.color_kind in {"single_color", "color_per_channel"}:
            actual = prop.channel_colors[e.channel_index]
            if actual and actual.strip().lower() != wanted:
                ctx.add(f"Asks for {e.color}, but this channel is {actual}", e)
        else:
            ctx.add(f"Asks for {e.color}, but this prop's colors are not known", e)
    return None


def _motion_stops_at_hard_stops(ctx: _Context) -> str | None:
    stops = sorted(set(ctx.choreography.hard_stops_centiseconds))
    if not stops:
        return "the song has no hard stops"
    if not ctx.choreography.movements:
        return "the Timeline has no movements"
    tagged = _movement_effects(ctx)
    for m in ctx.choreography.movements:
        for stop in stops:
            if m.start_centisecond < stop < m.end_centisecond:
                ctx.add(f"The {m.kind} {m.movement_id!r} keeps moving through the hard stop",
                        prop_id=m.prop_ids[0], centisecond=stop)
                continue
            for e in tagged.get(m.movement_id, []):
                if e.start_centisecond < stop < e.end_centisecond:
                    ctx.add(f"Movement {m.movement_id!r} is still running through the "
                            f"hard stop at {seconds(stop)}", e, centisecond=stop)
    return None


def _not_everything_at_once(ctx: _Context) -> str | None:
    total = ctx.display.sequenceable_channels
    effects = [e for e in ctx.valid_effects() if _lit(e)]
    if not effects:
        return "the Timeline has no lit effects"
    params = ctx.settings.params
    needed = max(1, math.ceil(params["max_share"] * total))
    limit = round(params["max_seconds"] * 100)
    by_channel: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for e in effects:
        by_channel[(e.prop_id, e.channel_index)].append((e.start_centisecond, e.end_centisecond))
    changes: dict[int, int] = defaultdict(int)
    for spans in by_channel.values():
        for start, end in _merge(spans):
            changes[start] += 1
            changes[end] -= 1
    busy: list[tuple[int, int]] = []
    active = 0
    started: int | None = None
    for time in sorted(changes):
        active += changes[time]
        if active >= needed and started is None:
            started = time
        elif active < needed and started is not None:
            busy.append((started, time))
            started = None
    allowed_labels = {label.lower() for label in params["allow_sections"]}
    allowed = [(s.start_centisecond, s.end_centisecond) for s in ctx.choreography.sections
               if s.label.lower() in allowed_labels]
    for start, end in _subtract(_merge(busy), _merge(allowed)):
        if end - start > limit:
            ctx.add(
                f"{params['max_share']:.0%} or more of the display is on for "
                f"{(end - start) / 100:.1f} s (limit {limit / 100:.1f} s); let some props rest",
                centisecond=start,
            )
    return None


_BUILT_IN: dict[str, _Check] = {
    "effects_well_formed": _effects_well_formed,
    "known_props_and_channels": _known_props_and_channels,
    "no_overlapping_effects": _no_overlapping_effects,
    "movements_complete": _movements_complete,
    "chases_follow_layout": _chases_follow_layout,
    "falls_go_down": _falls_go_down,
    "face_outline_with_mouth": _face_outline_with_mouth,
    "mouths_only_during_vocals": _mouths_only_during_vocals,
    "single_color_only_where_possible": _single_color_only_where_possible,
    "motion_stops_at_hard_stops": _motion_stops_at_hard_stops,
    "not_everything_at_once": _not_everything_at_once,
}
assert _BUILT_IN.keys() == RULE_SPECS.keys()


# ---------------------------------------------------------------- requirements


def select_props(display: Display, requirement: Requirement) -> tuple[list[str], list[str]]:
    """Return (sequenceable prop ids chosen, notes about chosen props that are not)."""
    selector = requirement.props
    chosen: list[str] = []
    for prop in display.props.values():
        if selector.all:
            hit = True
        elif selector.role is not None:
            hit = prop.role == selector.role
        elif selector.group is not None:
            hit = prop.prop_id in display.groups.get(selector.group, ())
        else:
            hit = any(fnmatch.fnmatchcase(prop.name.lower(), pattern.lower())
                      for pattern in selector.names)
        if hit:
            chosen.append(prop.prop_id)
    notes = []
    usable = []
    for pid in chosen:
        prop = display.props[pid]
        if prop.linked_to is not None:
            master = display.props.get(prop.linked_to)
            notes.append(f"{prop.name} is driven by {master.name if master else 'its master'}")
        elif prop.layout_problem is not None:
            if not selector.all:
                notes.append(f"{prop.name} cannot be sequenced yet")
        else:
            usable.append(pid)
    return usable, notes


def _section_windows(ctx: _Context, labels: list[str]) -> list[tuple[int, int]]:
    wanted = {label.lower() for label in labels}
    return _merge((s.start_centisecond, s.end_centisecond) for s in ctx.choreography.sections
                  if s.label.lower() in wanted)


def _keep_on(ctx: _Context, req: Requirement, props: list[str]) -> str | None:
    during = req.params.get("during")
    if during:
        windows = _section_windows(ctx, during)
        if not windows:
            return "the Timeline has no section named " + ", ".join(repr(d) for d in during)
    else:
        windows = [(0, ctx.choreography.duration_centiseconds)]
    effects = _effects_on(ctx, set(props))
    for pid in props:
        prop = ctx.display.props[pid]
        if prop.color_kind == "color_per_channel":
            # Any one color lit counts as on.
            groups = [list(range(prop.channel_count))]
        else:
            groups = [[i] for i in range(prop.channel_count)]
        for channels in groups:
            lit = _merge((e.start_centisecond, e.end_centisecond) for e in effects
                         if e.prop_id == pid and e.channel_index in channels)
            for start, end in windows:
                gap = _first_gap(lit, start, end)
                if gap is not None:
                    ctx.add("Should stay on but goes dark", prop_id=pid, centisecond=gap,
                            channel_index=channels[0] if len(channels) == 1 else None)
                    break
    return None


def _never_use(ctx: _Context, req: Requirement, props: list[str]) -> str | None:
    for e in _effects_on(ctx, set(props)):
        ctx.add("Should never be used", e)
    return None


def _colors_only(ctx: _Context, req: Requirement, props: list[str]) -> str | None:
    allowed = {c.strip().lower() for c in req.params["colors"]}
    for e in _effects_on(ctx, set(props)):
        prop = ctx.display.props[e.prop_id]
        if prop.color_kind == "combined_colors":
            ctx.add("All colors on this strand share one circuit, so it cannot be limited to "
                    + ", ".join(req.params["colors"]), e)
            continue
        actual = prop.channel_colors[e.channel_index].strip().lower()
        shown = (e.color or actual).strip().lower()
        if shown not in allowed:
            ctx.add(f"Shows {shown or 'an unknown color'}; allowed: "
                    + ", ".join(req.params["colors"]), e)
    return None


def _max_intensity(ctx: _Context, req: Requirement, props: list[str]) -> str | None:
    limit = req.params["max"]
    for e in _effects_on(ctx, set(props)):
        peak = max(e.start_intensity, e.end_intensity)
        if peak > limit:
            ctx.add(f"Reaches {peak}% intensity; limit is {limit}%", e)
    return None


def _quiet_during(ctx: _Context, req: Requirement, props: list[str]) -> str | None:
    windows = _section_windows(ctx, req.params["sections"])
    if not windows:
        return "the Timeline has no section named " + ", ".join(
            repr(s) for s in req.params["sections"])
    for e in _effects_on(ctx, set(props)):
        for start, end in windows:
            if e.start_centisecond < end and start < e.end_centisecond:
                ctx.add("Should be dark during this section", e,
                        centisecond=max(start, e.start_centisecond))
                break
    return None


def _move_direction(ctx: _Context, req: Requirement, props: list[str]) -> str | None:
    kind = req.params.get("movement", "chase")
    chosen = set(props)
    moves: list[Movement] = [m for m in ctx.choreography.movements
                             if m.kind == kind and set(m.prop_ids) <= chosen]
    if not moves:
        return f"the Timeline has no {kind} across these props"
    for m in moves:
        if m.direction != req.params["direction"]:
            ctx.add(f"The {kind} {m.movement_id!r} runs {m.direction.replace('_', ' ')}; it "
                    f"should run {req.params['direction'].replace('_', ' ')}",
                    prop_id=m.prop_ids[0], centisecond=m.start_centisecond)
    return None


_REQUIREMENTS: dict[str, Callable[[_Context, Requirement, list[str]], str | None]] = {
    "keep_on": _keep_on,
    "never_use": _never_use,
    "colors_only": _colors_only,
    "max_intensity": _max_intensity,
    "quiet_during": _quiet_during,
    "move_direction": _move_direction,
}


def describe_requirement(req: Requirement) -> str:
    words = {
        "keep_on": "stay on" + (f" during {', '.join(req.params['during'])}"
                                if req.params.get("during") else ""),
        "never_use": "are never used",
        "colors_only": "show only " + ", ".join(req.params.get("colors", [])),
        "max_intensity": f"stay at or below {req.params.get('max')}%",
        "quiet_during": "stay dark during " + ", ".join(req.params.get("sections", [])),
        "move_direction": f"{req.params.get('movement', 'chase')} "
                          f"{str(req.params.get('direction', '')).replace('_', ' ')}",
    }[req.type]
    chosen = req.props.describe()
    title = f"{chosen[:1].upper()}{chosen[1:]} {words}"
    return f"{title}: {req.note}" if req.note else title


# ---------------------------------------------------------------- entry point


def check_choreography(
    preview: ET.Element, choreography: Choreography, rule_set: RuleSet
) -> RuleReport:
    """Run every built-in rule and requirement; never modifies the choreography."""
    display = display_from_preview(preview)
    results: list[RuleResult] = []
    for rule_id, check in _BUILT_IN.items():
        settings = rule_set.rules[rule_id]
        spec = RULE_SPECS[rule_id]
        if settings.severity == "off":
            results.append(RuleResult(rule_id, spec.title, "off", "off",
                                      "turned off by a profile"))
            continue
        ctx = _Context(display, choreography, settings)
        reason = check(ctx)
        results.append(_result(rule_id, spec.title, settings.severity, reason, ctx,
                                "default.yaml"))
    for req in rule_set.requirements:
        title = describe_requirement(req)
        if req.severity == "off":
            results.append(RuleResult(req.requirement_id, title, "off", "off",
                                      "turned off by a profile", source=req.source))
            continue
        settings = RuleSettings(req.requirement_id, req.severity, req.params)
        ctx = _Context(display, choreography, settings)
        props, notes = select_props(display, req)
        if not props:
            reason = "it matches no prop that can be sequenced in this preview"
            if notes:
                reason += " (" + "; ".join(notes) + ")"
            ctx.findings.append(Finding(req.requirement_id, "warning",
                                        f"Requirement {req.requirement_id!r} {reason}"))
            results.append(RuleResult(req.requirement_id, title, "warning", "failed",
                                      "", tuple(ctx.findings), req.source))
            continue
        reason = _REQUIREMENTS[req.type](ctx, req, props)
        result = _result(req.requirement_id, title, req.severity, reason, ctx, req.source)
        if notes:
            extra = "; ".join(notes)
            result = RuleResult(result.rule_id, result.title, result.severity, result.status,
                                f"{result.reason}; {extra}" if result.reason else extra,
                                result.findings, result.source)
        results.append(result)
    return RuleReport(tuple(results), rule_set)


def _result(
    rule_id: str, title: str, severity: str, reason: str | None, ctx: _Context, source: str
) -> RuleResult:
    if ctx.findings:
        return RuleResult(rule_id, title, severity, "failed", "", tuple(ctx.findings), source)
    if reason is not None:
        return RuleResult(rule_id, title, severity, "not_applicable", reason, (), source)
    return RuleResult(rule_id, title, severity, "passed", "", (), source)
