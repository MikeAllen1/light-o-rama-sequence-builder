
"""Versioned, deterministic Timeline contract for generated sequences."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class TimelineChannel:
    """A native channel plus its verified preview controller-address mapping."""

    prop_id: str
    channel_index: int
    preview_channel_index: int
    network: str
    unit_id: str
    circuit: str
    row: str
    col: str
    color: str


@dataclass(frozen=True, slots=True)
class PulseEvent:
    """One bounded intensity pulse on a native channel."""

    start_centisecond: int
    end_centisecond: int
    beat_index: int
    channel: TimelineChannel


@dataclass(frozen=True, slots=True)
class ExcludedProp:
    """A preview prop not pulsed, with an explicit reason."""

    prop_id: str
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class Timeline:
    """Deterministic, versioned event plan independent of native LOR XML."""

    schema_version: str
    timebase: str
    preview_xml_sha256: str
    template_xml_sha256: str
    bpm: float
    duration_centiseconds: int
    pulse_duration_centiseconds: int
    beat_positions_centiseconds: tuple[int, ...]
    supported_prop_ids: tuple[str, ...]
    excluded_props: tuple[ExcludedProp, ...]
    events: tuple[PulseEvent, ...]


def timeline_json(timeline: Timeline) -> str:
    """Serialize a Timeline deterministically for reproducible artifacts."""
    return json.dumps(asdict(timeline), indent=2, sort_keys=True) + "\n"
