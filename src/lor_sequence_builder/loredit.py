"""Read-only structural inspection for Light-O-Rama LOREDIT XML files.

The inspector reports format structure without exposing song metadata, author names,
local media paths, or preview background paths. It does not modify sequence files.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


class LoreditError(ValueError):
    """Raised when a LOREDIT file cannot be parsed as XML."""


def _local_name(tag: str) -> str:
    """Remove an optional XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    """Find a direct child by its local XML name."""
    return next((item for item in element if _local_name(item.tag) == name), None)


def inspect_loredit(path: str | Path) -> dict[str, Any]:
    """Return a structural summary without returning personal metadata or paths."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Sequence file not found: {source}")

    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise LoreditError(f"Invalid XML in {source}: {exc}") from exc
    except OSError as exc:
        raise LoreditError(f"Unable to read {source}: {exc}") from exc

    counts = Counter(_local_name(element.tag) for element in root.iter())
    safe_root_attributes = {
        key: root.attrib[key]
        for key in ("saveFileVersion", "AppVersion", "totalCentiseconds")
        if key in root.attrib
    }

    preview = _child(root, "PreviewClass")
    preview_props = [] if preview is None else [
        {
            "id": item.get("id"),
            "name": item.get("Name"),
            "device_type": item.get("DeviceType"),
            "channel_grid": item.get("ChannelGrid"),
            "traditional_type": item.get("TraditionalType"),
        }
        for item in preview
        if _local_name(item.tag) == "PropClass"
    ]
    preview_ids = {item["id"] for item in preview_props if item["id"]}

    sequence_section = _child(root, "SequenceProps")
    sequence_props = [] if sequence_section is None else [
        item for item in sequence_section
        if _local_name(item.tag) == "SeqProp"
    ]
    prop_summaries: list[dict[str, Any]] = []
    effect_settings: Counter[str] = Counter()
    effect_attribute_keys: Counter[str] = Counter()
    channel_count = 0
    effect_count = 0

    for prop in sequence_props:
        channels = [
            item for item in prop
            if _local_name(item.tag) == "channel"
        ]
        channel_count += len(channels)
        prop_effects = 0
        for channel in channels:
            for effect in channel:
                if _local_name(effect.tag) != "effect":
                    continue
                prop_effects += 1
                effect_count += 1
                effect_settings[effect.get("settings", "(missing)")] += 1
                effect_attribute_keys.update(effect.attrib.keys())

        prop_summaries.append({
            "id": prop.get("id"),
            "name": prop.get("name"),
            "channel_count": len(channels),
            "effect_count": prop_effects,
            "has_preview_definition": prop.get("id") in preview_ids,
        })

    timing_section = _child(root, "TimingGrids")
    timing_grids = [] if timing_section is None else [
        {
            "element": _local_name(grid.tag),
            "name": grid.get("name"),
            "spacing": grid.get("spacing"),
            "timing_count": sum(
                1 for item in grid.iter()
                if _local_name(item.tag) == "timing"
            ),
        }
        for grid in timing_section
    ]

    return {
        "file": source.name,
        "size_bytes": source.stat().st_size,
        "root_element": _local_name(root.tag),
        "format_metadata": safe_root_attributes,
        "element_counts": dict(sorted(counts.items())),
        "top_level_elements": [_local_name(child.tag) for child in root],
        "preview_prop_count": len(preview_props),
        "sequence_prop_count": len(sequence_props),
        "channel_count": channel_count,
        "effect_count": effect_count,
        "effect_settings": dict(sorted(effect_settings.items())),
        "effect_attribute_keys": dict(sorted(effect_attribute_keys.items())),
        "timing_grids": timing_grids,
        "props": prop_summaries,
    }



def _parse_int(value: str | None) -> int | None:
    """Parse an optional integer attribute without guessing a default."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def extract_display(path: str | Path) -> dict[str, Any]:
    """Extract reusable prop and group mapping data from an S6 sequence.

    Scene background paths, song metadata, and other machine-specific metadata
    are deliberately excluded. The original PreviewClass XML is not rewritten.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Sequence file not found: {source}")

    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise LoreditError(f"Invalid XML in {source}: {exc}") from exc
    except OSError as exc:
        raise LoreditError(f"Unable to read {source}: {exc}") from exc

    preview = _child(root, "PreviewClass")
    sequence_section = _child(root, "SequenceProps")

    sequence_by_id: dict[str, ET.Element] = {}
    sequence_props = [] if sequence_section is None else [
        item for item in sequence_section
        if _local_name(item.tag) == "SeqProp"
    ]
    for sequence_prop in sequence_props:
        prop_id = sequence_prop.get("id")
        if prop_id:
            sequence_by_id[prop_id] = sequence_prop

    props: list[dict[str, Any]] = []
    if preview is not None:
        for preview_prop in preview:
            if _local_name(preview_prop.tag) != "PropClass":
                continue

            prop_id = preview_prop.get("id")
            sequence_prop = sequence_by_id.get(prop_id or "")
            channels = [] if sequence_prop is None else [
                {
                    "row": channel.get("row"),
                    "col": channel.get("col"),
                    "color": channel.get("color"),
                }
                for channel in sequence_prop
                if _local_name(channel.tag) == "channel"
            ]
            colors = [
                color.strip()
                for color in (preview_prop.get("TraditionalColors") or "").split(",")
                if color.strip()
            ]
            props.append({
                "id": prop_id,
                "name": preview_prop.get("Name"),
                "device_type": preview_prop.get("DeviceType"),
                "channel_grid": preview_prop.get("ChannelGrid"),
                "traditional_type": preview_prop.get("TraditionalType"),
                "traditional_colors": colors,
                "rgb_order": preview_prop.get("RgbOrder"),
                "string_type": preview_prop.get("StringType"),
                "individual_channels": (
                    (preview_prop.get("IndividualChannels") or "").lower() == "true"
                ),
                "max_channels": _parse_int(preview_prop.get("MaxChannels")),
                "master_prop_id": preview_prop.get("MasterPropId") or None,
                "shape_count": sum(
                    1 for child in preview_prop
                    if _local_name(child.tag) == "shape"
                ),
                "sequence_channel_count": len(channels),
                "sequence_channels": channels,
                "has_sequence_data": sequence_prop is not None,
            })

    groups: list[dict[str, Any]] = []
    if preview is not None:
        for group in preview:
            if _local_name(group.tag) != "PropGroup":
                continue
            groups.append({
                "id": group.get("id"),
                "name": group.get("Name"),
                "arrangement": group.get("Arrangement"),
                "members": [
                    member.get("id")
                    for member in group
                    if _local_name(member.tag) == "member" and member.get("id")
                ],
            })

    preview_ids = {prop["id"] for prop in props if prop["id"]}
    unmapped_sequence_props = [
        {
            "id": prop.get("id"),
            "name": prop.get("name"),
            "channel_count": sum(
                1 for child in prop
                if _local_name(child.tag) == "channel"
            ),
        }
        for prop in sequence_props
        if prop.get("id") not in preview_ids
    ]

    return {
        "preview_prop_count": len(props),
        "sequence_prop_count": len(sequence_props),
        "group_count": len(groups),
        "props": props,
        "groups": groups,
        "unmapped_sequence_props": unmapped_sequence_props,
        "notes": [
            "This is a mapping summary, not a lossless preview export.",
            "The original PreviewClass XML must be preserved for future native S6 writing.",
            "Scene background paths and machine-specific metadata are intentionally omitted.",
        ],
    }
