from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.lorprev import (
    LorprevError,
    UnsupportedLorprevRevisionError,
    read_lorprev,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_synthetic_revision_zero_preview_preserves_geometry_and_provenance() -> None:
    model = read_lorprev(FIXTURES / "synthetic_display.lorprev")
    assert model.revision.value == "0"
    assert len(model.props) == 2
    assert model.props[0].attributes["Name"].value == "Test Roofline"
    assert model.props[0].attributes["ChannelGrid"].value == "1"
    assert model.props[1].children[0].tag == "shape"
    assert model.props[1].children[0].children[0].attributes["x"].value == "0"
    assert model.props[0].attributes["Name"].locator.endswith("/@Name")
    assert model.scenes[0].attributes["Name"].value == "Synthetic Scene"
    assert model.prop_views[0].tag == "PropViews"


def test_synthetic_revision_one_preview_preserves_full_prop_model(tmp_path: Path) -> None:
    # Runtime-generated fixture uses only fictional IDs, channel addresses, and names.
    root = ET.Element(
        "PreviewClass",
        {
            "id": "synthetic-display",
            "Name": "Synthetic Revision 1 Fixture",
            "Revision": "1",
            "LastSelectedSceneId": "synthetic-scene",
        },
    )
    ET.SubElement(root, "Scene", {"id": "synthetic-scene", "Name": "Synthetic Scene"})
    for index in range(1, 52):
        is_hexagon = 7 <= index <= 11
        channel_per_color = is_hexagon or index >= 49
        multi = index in {1, 2, 3, 4, 17, 30, 40, 41, 42, 43}
        channel_grid = f"Regular,99,{index:02d},01,0,{'Multi' if multi else 'White'}"
        if index >= 49:
            channel_grid += f";Regular,99,{index:02d},02,0,Green"
        if index == 17:
            channel_grid = ";".join(
                f"Regular,99,{index:02d},{channel:02d},0,Multi"
                for channel in range(1, 17)
            )
        prop = ET.SubElement(
            root,
            "PropClass",
            {
                "id": f"synthetic-prop-{index:02d}",
                "Name": f"Synthetic Prop {index:02d}",
                "DeviceType": "LOR",
                "BulbShape": "Hexagon" if is_hexagon else "Square",
                "ChannelGrid": channel_grid,
                "TraditionalType": (
                    "Channel_per_color" if channel_per_color else "Multicolor_string_1_ch"
                ),
                "IndividualChannels": "True" if channel_per_color else "False",
                "MaxChannels": "512" if is_hexagon else "16",
                "MasterPropId": "synthetic-prop-09" if index in {10, 11} else "",
            },
        )
        shape_name = (
            "Star" if index == 14 else
            "Tree 180" if index == 17 else
            "Arch" if index >= 49 else
            "Lines-Unconnected" if index % 2 == 0 else
            "Lines-Connected"
        )
        shape = ET.SubElement(prop, "shape", {"ShapeName": shape_name})
        if index in {14, 17, 49, 50, 51}:
            shape.attrib.update(
                {"OffsetX": "0", "OffsetY": "0.1", "ScaleX": "0.05",
                 "ScaleY": "0.07", "Radians": "0"}
            )
        else:
            ET.SubElement(shape, "point", {"x": str(index / 100), "y": "0.5"})
    ET.SubElement(root, "PropViews")
    source = tmp_path / "synthetic_revision_1.lorprev"
    ET.ElementTree(root).write(source, encoding="utf-8", xml_declaration=True)

    model = read_lorprev(source)
    assert model.revision.value == "1"
    assert len(model.props) == 51
    assert sum(p.attributes["BulbShape"].value == "Square" for p in model.props) == 46
    assert sum(p.attributes["BulbShape"].value == "Hexagon" for p in model.props) == 5
    assert model.props[0].attributes["ChannelGrid"].value == "Regular,99,01,01,0,Multi"
    assert model.props[16].attributes["ChannelGrid"].value.count(";") == 15
    assert model.props[9].attributes["MasterPropId"].value == "synthetic-prop-09"
    assert model.props[10].attributes["MasterPropId"].value == "synthetic-prop-09"
    assert model.props[8].children[0].tag == "shape"
    assert model.scenes[0].attributes["Name"].value == "Synthetic Scene"
    assert model.prop_views[0].tag == "PropViews"
    assert model.props[0].attributes["Name"].file == str(source)
    assert model.props[0].attributes["Name"].locator.endswith("/@Name")


def test_owner_supplied_default_preview_is_rejected_as_zero_prop_fixture() -> None:
    with pytest.raises(LorprevError, match="zero PropClass"):
        read_lorprev(FIXTURES / "default_empty.lorprev")


def test_unsupported_revision_fails_clearly(tmp_path: Path) -> None:
    source = tmp_path / "future.lorprev"
    source.write_text(
        '<PreviewClass id="x" Name="Future" Revision="999">'
        '<PropClass id="p" Name="Test" /></PreviewClass>',
        encoding="utf-8",
    )
    with pytest.raises(
        UnsupportedLorprevRevisionError,
        match="verified revisions are 0, 1",
    ):
        read_lorprev(source)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not xml",
        b"<Other />",
        b'<!DOCTYPE x [<!ENTITY e "boom">]><PreviewClass Revision="0" />',
        b'<PreviewClass Revision="0" />',
        b'<PreviewClass><PropClass id="p" /></PreviewClass>',
    ],
)
def test_invalid_or_unsafe_previews_fail(content: bytes, tmp_path: Path) -> None:
    source = tmp_path / "invalid.lorprev"
    source.write_bytes(content)
    with pytest.raises(LorprevError):
        read_lorprev(source)
