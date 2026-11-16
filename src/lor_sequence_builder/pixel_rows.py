"""Motion-effect rows on a pixel prop's SeqProp (see pixels.py for the evidence)."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Protocol

TRACK_NAMES = ("Effects 01", "Effects 02")


class _Effect(Protocol):
    @property
    def prop_id(self) -> str: ...
    @property
    def start_centisecond(self) -> int: ...
    def element(self) -> ET.Element: ...


def track_ids(prop_id: str) -> tuple[str, ...]:
    """Stable ids for a prop's motion-effect rows."""
    return tuple(str(uuid.uuid5(uuid.NAMESPACE_URL, f"lor-pixel-row|{prop_id}|{name}"))
                 for name in TRACK_NAMES)


def add_pixel_rows(sequence_prop: ET.Element) -> None:
    """Give a pixel prop's SeqProp its motion-effect rows (empty)."""
    sequence_prop.set("OverlayMotionRows", "1")
    for track_id, name in zip(track_ids(sequence_prop.get("id", "")), TRACK_NAMES,
                              strict=True):
        ET.SubElement(sequence_prop, "track", {"id": track_id, "name": name})


def write_pixel_effects(root: ET.Element, effects: Iterable[_Effect]) -> int:
    """Put the effects on their props' first motion-effect row; returns how many."""
    rows = {}
    for seq_prop in root.findall("SequenceProps/SeqProp"):
        track = seq_prop.find("track")
        if track is not None:
            rows[seq_prop.get("id", "")] = track
    written = 0
    for effect in sorted(effects, key=lambda e: (e.prop_id, e.start_centisecond)):
        track = rows.get(effect.prop_id)
        if track is None:
            continue
        track.append(effect.element())
        written += 1
    return written
