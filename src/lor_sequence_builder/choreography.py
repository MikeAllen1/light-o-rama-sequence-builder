"""Versioned choreography Timeline: the planner's decisions, as data.

The planner (Phase 7) produces this; the rules engine checks it; only a Timeline
that passes the rules reaches the writer. It contains no LOR XML. Every effect
names a preview prop by its stable id and a channel by its index in that prop's
ChannelGrid, and all times are integer centiseconds, the unit S6 stores.

Loading checks structure only (types, required fields, known effect kinds).
Whether the choreography is *allowed* (overlaps, completed movements, faces,
colors) is the rules engine's job, so those problems come back as readable rule
findings rather than load errors.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "choreography-1.0"
EFFECT_KINDS = ("on", "fade", "twinkle", "shimmer")
MOVEMENT_KINDS = ("chase", "fill", "fall")
MOVEMENT_DIRECTIONS = (
    "left_to_right",
    "right_to_left",
    "top_to_bottom",
    "bottom_to_top",
    "row_order",
    "reverse_row_order",
)
MAX_TIMELINE_BYTES = 50 * 1024 * 1024
MAX_EFFECTS = 500_000


class ChoreographyError(ValueError):
    """Raised when a choreography Timeline is structurally malformed."""


@dataclass(frozen=True, slots=True)
class Effect:
    """One effect on one native channel.

    ``on``, ``twinkle`` and ``shimmer`` hold one intensity (start equals end);
    ``fade`` ramps from ``start_intensity`` to ``end_intensity``. ``color`` is
    what the planner meant to show, if a specific color matters; the rules check
    that the prop can actually show it alone.
    """

    prop_id: str
    channel_index: int
    start_centisecond: int
    end_centisecond: int
    kind: str = "on"
    start_intensity: int = 100
    end_intensity: int = 100
    color: str | None = None
    movement_id: str | None = None


@dataclass(frozen=True, slots=True)
class Movement:
    """A motion across props or segments that must complete in order."""

    movement_id: str
    kind: str
    prop_ids: tuple[str, ...]
    direction: str
    start_centisecond: int
    end_centisecond: int


@dataclass(frozen=True, slots=True)
class Section:
    label: str
    start_centisecond: int
    end_centisecond: int


@dataclass(frozen=True, slots=True)
class Choreography:
    duration_centiseconds: int
    effects: tuple[Effect, ...]
    movements: tuple[Movement, ...] = ()
    sections: tuple[Section, ...] = ()
    hard_stops_centiseconds: tuple[int, ...] = ()
    # None means vocals were not analyzed; an empty tuple means no vocals.
    vocal_regions: tuple[tuple[int, int], ...] | None = None
    schema_version: str = field(default=SCHEMA_VERSION)


def choreography_json(choreography: Choreography) -> str:
    """Serialize deterministically."""
    data = asdict(choreography)
    if choreography.vocal_regions is not None:
        data["vocal_regions"] = [list(region) for region in choreography.vocal_regions]
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _where(path: str) -> str:
    return f"Timeline {path}"


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChoreographyError(f"{_where(path)} must be an integer")
    return int(value)


def _str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChoreographyError(f"{_where(path)} must be a non-empty string")
    return value


def _object(value: Any, path: str, required: set[str], optional: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ChoreographyError(f"{_where(path)} must be an object")
    missing = required - value.keys()
    if missing:
        raise ChoreographyError(f"{_where(path)} is missing {', '.join(sorted(missing))}")
    unknown = value.keys() - required - optional
    if unknown:
        raise ChoreographyError(f"{_where(path)} has unknown field(s) {', '.join(sorted(unknown))}")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ChoreographyError(f"{_where(path)} must be a list")
    return value


def _effect(raw: Any, path: str) -> Effect:
    data = _object(
        raw,
        path,
        {"prop_id", "channel_index", "start_centisecond", "end_centisecond"},
        {"kind", "start_intensity", "end_intensity", "color", "movement_id"},
    )
    kind = data.get("kind", "on")
    if kind not in EFFECT_KINDS:
        raise ChoreographyError(
            f"{_where(path)}.kind {kind!r} is not one of {', '.join(EFFECT_KINDS)}"
        )
    color = data.get("color")
    movement = data.get("movement_id")
    return Effect(
        prop_id=_str(data["prop_id"], f"{path}.prop_id"),
        channel_index=_int(data["channel_index"], f"{path}.channel_index"),
        start_centisecond=_int(data["start_centisecond"], f"{path}.start_centisecond"),
        end_centisecond=_int(data["end_centisecond"], f"{path}.end_centisecond"),
        kind=kind,
        start_intensity=_int(data.get("start_intensity", 100), f"{path}.start_intensity"),
        end_intensity=_int(data.get("end_intensity", 100), f"{path}.end_intensity"),
        color=None if color is None else _str(color, f"{path}.color"),
        movement_id=None if movement is None else _str(movement, f"{path}.movement_id"),
    )


def _movement(raw: Any, path: str) -> Movement:
    data = _object(
        raw,
        path,
        {"movement_id", "kind", "prop_ids", "direction", "start_centisecond", "end_centisecond"},
        set(),
    )
    if data["kind"] not in MOVEMENT_KINDS:
        raise ChoreographyError(
            f"{_where(path)}.kind {data['kind']!r} is not one of {', '.join(MOVEMENT_KINDS)}"
        )
    if data["direction"] not in MOVEMENT_DIRECTIONS:
        raise ChoreographyError(
            f"{_where(path)}.direction {data['direction']!r} is not one of "
            + ", ".join(MOVEMENT_DIRECTIONS)
        )
    prop_ids = tuple(
        _str(item, f"{path}.prop_ids[{i}]")
        for i, item in enumerate(_list(data["prop_ids"], f"{path}.prop_ids"))
    )
    if not prop_ids:
        raise ChoreographyError(f"{_where(path)}.prop_ids must name at least one prop")
    return Movement(
        movement_id=_str(data["movement_id"], f"{path}.movement_id"),
        kind=data["kind"],
        prop_ids=prop_ids,
        direction=data["direction"],
        start_centisecond=_int(data["start_centisecond"], f"{path}.start_centisecond"),
        end_centisecond=_int(data["end_centisecond"], f"{path}.end_centisecond"),
    )


def _span(raw: Any, path: str) -> tuple[int, int]:
    items = _list(raw, path)
    if len(items) != 2:
        raise ChoreographyError(f"{_where(path)} must be [start, end]")
    return _int(items[0], f"{path}[0]"), _int(items[1], f"{path}[1]")


def parse_choreography(data: Any) -> Choreography:
    """Build a Choreography from decoded JSON, checking structure only."""
    root = _object(
        data,
        "root",
        {"schema_version", "duration_centiseconds", "effects"},
        {"movements", "sections", "hard_stops_centiseconds", "vocal_regions"},
    )
    if root["schema_version"] != SCHEMA_VERSION:
        raise ChoreographyError(
            f"Unsupported Timeline schema_version {root['schema_version']!r}; "
            f"expected {SCHEMA_VERSION!r}"
        )
    raw_effects = _list(root["effects"], "effects")
    if len(raw_effects) > MAX_EFFECTS:
        raise ChoreographyError(f"Timeline has more than {MAX_EFFECTS} effects")
    sections = []
    for i, raw in enumerate(_list(root.get("sections", []), "sections")):
        section = _object(raw, f"sections[{i}]", {"label", "start_centisecond", "end_centisecond"},
                          set())
        sections.append(Section(
            _str(section["label"], f"sections[{i}].label"),
            _int(section["start_centisecond"], f"sections[{i}].start_centisecond"),
            _int(section["end_centisecond"], f"sections[{i}].end_centisecond"),
        ))
    vocals_raw = root.get("vocal_regions")
    vocals = (
        None if vocals_raw is None
        else tuple(_span(r, f"vocal_regions[{i}]")
                   for i, r in enumerate(_list(vocals_raw, "vocal_regions")))
    )
    return Choreography(
        duration_centiseconds=_int(root["duration_centiseconds"], "duration_centiseconds"),
        effects=tuple(_effect(raw, f"effects[{i}]") for i, raw in enumerate(raw_effects)),
        movements=tuple(
            _movement(raw, f"movements[{i}]")
            for i, raw in enumerate(_list(root.get("movements", []), "movements"))
        ),
        sections=tuple(sections),
        hard_stops_centiseconds=tuple(
            _int(v, f"hard_stops_centiseconds[{i}]")
            for i, v in enumerate(_list(root.get("hard_stops_centiseconds", []),
                                        "hard_stops_centiseconds"))
        ),
        vocal_regions=vocals,
    )


def _reject_constant(value: str) -> Any:
    raise ChoreographyError(f"Timeline contains a non-finite number {value!r}")


def load_choreography(path: str | Path) -> Choreography:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_TIMELINE_BYTES:
            raise ChoreographyError("Timeline JSON exceeds the 50 MiB limit")
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ChoreographyError(f"Cannot read Timeline JSON: {source}") from exc
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ChoreographyError(f"Timeline JSON is not valid JSON: {exc}") from exc
    return parse_choreography(data)


def seconds(centiseconds: int) -> str:
    """Format a centisecond time the way S6 shows it (m:ss.cc)."""
    sign = "-" if centiseconds < 0 else ""
    value = abs(centiseconds)
    return f"{sign}{value // 6000}:{(value // 100) % 60:02d}.{value % 100:02d}"
