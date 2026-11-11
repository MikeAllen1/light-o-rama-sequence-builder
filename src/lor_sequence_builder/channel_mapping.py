"""One authoritative parser for native LOR ChannelGrid addresses.

ChannelGrid is positional: an entry's index is the native channel index. Empty
entries must never be compacted because doing so can silently target another
physical light.
"""
from __future__ import annotations

from dataclasses import dataclass

from lor_sequence_builder.lorprev import (
    MAX_CHANNEL_GRID_ENTRIES_PER_PROP,
)

SUPPORTED_DEVICE_TYPES = frozenset({"LOR"})
COLUMN_LAYOUT_TYPES = frozenset({"Single Color", "Multicolor_string_1_ch"})
COLOR_LAYOUT_TYPES = frozenset({"Channel_per_color"})


@dataclass(frozen=True, slots=True)
class ChannelAddress:
    """The physical controller address at one stable ChannelGrid position."""

    index: int
    network: str
    unit_id: str
    circuit: str


def parse_channel_grid(value: str | None) -> tuple[ChannelAddress, ...]:
    """Parse ChannelGrid without ever discarding or compacting a position."""
    if value is None or not value.strip():
        return ()
    entries = value.split(";")
    if len(entries) > MAX_CHANNEL_GRID_ENTRIES_PER_PROP:
        raise ValueError(
            f"ChannelGrid exceeds the {MAX_CHANNEL_GRID_ENTRIES_PER_PROP} entry limit"
        )
    parsed: list[ChannelAddress] = []
    for index, entry in enumerate(entries):
        if not entry.strip():
            raise ValueError(
                f"ChannelGrid entry {index} is empty; channel indices cannot be compacted"
            )
        fields = entry.split(",")
        if len(fields) < 3 or not all(field.strip() for field in fields[:3]):
            raise ValueError(
                f"ChannelGrid entry {index} lacks a complete LOR network, Unit ID, and circuit"
            )
        parsed.append(
            ChannelAddress(
                index=index,
                network=fields[0].strip(),
                unit_id=fields[1].strip(),
                circuit=fields[2].strip(),
            )
        )
    return tuple(parsed)


def channel_layout_problem(prop: object) -> str | None:
    """Why a preview prop cannot be represented by the verified native layout."""
    attributes = getattr(prop, "attrib", None)
    if not isinstance(attributes, dict):
        return "Prop does not expose XML attributes"
    device_type = attributes.get("DeviceType", "")
    if device_type not in SUPPORTED_DEVICE_TYPES:
        return f"DeviceType {device_type or '(missing)'} has no verified native channel layout"
    string_type = attributes.get("StringType", "Traditional")
    if string_type != "Traditional":
        return f"StringType {string_type!r} has no verified native channel layout"
    traditional_type = attributes.get("TraditionalType", "")
    if traditional_type not in COLUMN_LAYOUT_TYPES | COLOR_LAYOUT_TYPES:
        return (
            f"TraditionalType {traditional_type or '(missing)'} has no verified native "
            "channel layout"
        )
    try:
        addresses = parse_channel_grid(attributes.get("ChannelGrid"))
    except ValueError as exc:
        return str(exc)
    if not addresses:
        return "ChannelGrid has no controller assignments"
    return None
