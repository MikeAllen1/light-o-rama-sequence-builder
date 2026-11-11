"""Runtime-generated, wholly synthetic Light-O-Rama XML used by tests.

No user-owned sequence or preview exports are stored in the repository.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def write_synthetic_loredit(path: Path, preview_revision: str = "56") -> Path:
    """Write a small synthetic v15 sequence with 51 preview props and 48 SeqProps."""
    root = ET.Element(
        "sequence",
        {
            "saveFileVersion": "15",
            "totalCentiseconds": "20925",
            "version": "S6 synthetic test fixture",
        },
    )
    preview = ET.SubElement(
        root,
        "PreviewClass",
        {
            "id": "synthetic-preview-0001",
            "Name": "Synthetic Test Display",
            "Revision": preview_revision,
            "EmbedBackgrounds": "False",
            "LastSelectedSceneId": "synthetic-scene-0001",
        },
    )
    ET.SubElement(
        preview,
        "Scene",
        {"id": "synthetic-scene-0001", "Name": "Synthetic Test Scene"},
    )

    sequence_props: list[tuple[str, int, str]] = []
    for index in range(1, 52):
        prop_id = f"synthetic-prop-{index:02d}"
        is_sequence_prop = index <= 48
        is_per_color = index == 48
        channel_count = 2 if index <= 32 or is_per_color else 1
        traditional_type = (
            "Channel_per_color"
            if is_per_color
            else "Multicolor_string_1_ch"
            if index <= 47
            else "Single Color"
        )
        device_type = "LOR" if is_sequence_prop else ("AC", "DC", "DMX")[index - 49]
        channel_grid = ";".join(
            f"Regular,99,{index:02d},{channel_index + 1:02d},0,White"
            for channel_index in range(channel_count)
        )
        ET.SubElement(
            preview,
            "PropClass",
            {
                "id": prop_id,
                "Name": f"Synthetic Prop {index:02d}",
                "DeviceType": device_type,
                "TraditionalType": traditional_type,
                "BulbShape": "Square",
                "ChannelGrid": channel_grid,
                "IndividualChannels": "False",
                "MaxChannels": str(channel_count),
            },
        )
        if is_sequence_prop:
            sequence_props.append((prop_id, channel_count, traditional_type))

    group = ET.SubElement(
        preview,
        "PropGroup",
        {
            "id": "synthetic-group-0001",
            "Name": "Synthetic Fixture Group",
            "Arrangement": "Preview",
        },
    )
    for index in (11, 10, 9, 8, 7):
        ET.SubElement(
            group,
            "member",
            {
                "id": f"synthetic-prop-{index:02d}",
                "orientation": "normal",
                "top": "0",
                "left": "0",
            },
        )

    sequence_section = ET.SubElement(root, "SequenceProps")
    effect_settings = ("INTENSITY", "TWINKLE", "SHIMMER")
    effect_index = 0
    for prop_id, channel_count, traditional_type in sequence_props:
        sequence_prop = ET.SubElement(
            sequence_section,
            "SeqProp",
            {"id": prop_id, "name": prop_id.replace("-", " ").title()},
        )
        for channel_index in range(channel_count):
            color = str(channel_index) if traditional_type == "Channel_per_color" else "0"
            col = "0" if traditional_type == "Channel_per_color" else str(channel_index)
            channel = ET.SubElement(
                sequence_prop,
                "channel",
                {"row": "0", "col": col, "color": color},
            )
            if effect_index < len(effect_settings):
                ET.SubElement(
                    channel,
                    "effect",
                    {
                        "settings": effect_settings[effect_index],
                        "startCentisecond": "0",
                        "endCentisecond": "10",
                        "intensity": "100",
                    },
                )
                effect_index += 1

    timing_grids = ET.SubElement(root, "TimingGrids")
    for index in range(8):
        ET.SubElement(
            timing_grids,
            "TimingGrid",
            {"id": f"synthetic-timing-{index + 1:02d}", "name": f"Grid {index + 1}"},
        )

    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path
