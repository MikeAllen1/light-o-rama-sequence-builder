"""Read-only structural inspection for Light-O-Rama LOREDIT XML files.

The inspector reports format structure without exposing song metadata, author names,
local media paths, or preview background paths. It does not modify sequence files.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
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
