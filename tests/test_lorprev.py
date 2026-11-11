from __future__ import annotations

import base64
import gzip
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
    assert len(model.channel_grid_entries) == 2
    assert model.channel_grid_entries[0].raw_fields == ("1",)
    assert model.channel_grid_entries[0].entry_index == 0
    assert len(model.geometry_points) == 4
    assert model.unsupported_constructs == ()
    assert model.geometry_points[0].x.value == "0"
    assert model.geometry_points[0].y.locator.endswith("/@y")
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
    assert len(model.channel_grid_entries) == 69
    assert len(model.geometry_points) == 46
    assert model.unsupported_constructs == ()
    assert all(entry.source.locator.endswith("/@ChannelGrid") for entry in model.channel_grid_entries)
    assert model.channel_grid_entries[0].entry_index == 0
    assert model.channel_grid_entries[31].entry_index == 15
    assert all(point.x.file == str(source) and point.y.file == str(source) for point in model.geometry_points)
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


def test_s6_exported_revision_one_golden_fixture_preserves_all_source_data(
    tmp_path: Path,
) -> None:
    # The committed fixture is a gzip transport wrapper around the sanitized S6 XML export.
    fixture = FIXTURES / "s6_revision_1_export.lorprev.gz"
    source = tmp_path / "s6_revision_1_export.lorprev"
    compressed = base64.b64decode(fixture.read_bytes(), validate=True)
    source.write_bytes(gzip.decompress(compressed))

    model = read_lorprev(source)
    assert model.revision.value == "1"
    assert len(model.props) == 51
    assert len(model.geometry_points) == 1900
    assert all(point.x.file == str(source) and point.y.file == str(source) for point in model.geometry_points)
    assert len(model.scenes) == 1
    assert len(model.prop_views) == 1
    assert model.prop_views[0].tag == "PropViews"
    assert sum(p.attributes["BulbShape"].value == "Square" for p in model.props) == 46
    assert sum(p.attributes["BulbShape"].value == "Hexagon" for p in model.props) == 5
    assert {p.children[0].attributes["ShapeName"].value for p in model.props} == {
        "Lines-Connected", "Lines-Unconnected", "Arch", "Star", "Tree 180", "Icicles"
    }
    assert sum(
        len(p.children[0].children) for p in model.props
    ) == 1900
    assert sum(
        p.attributes["TraditionalType"].value == "Channel_per_color"
        for p in model.props
    ) == 8
    assert all(
        value.file == str(source)
        for prop in model.props
        for value in prop.attributes.values()
    )
    assert all(
        value.locator.startswith("/PreviewClass/PropClass[")
        for prop in model.props
        for value in prop.attributes.values()
    )
    assert model.display.attributes["Name"].value == "Synthetic S6 Export Fixture"
    assert model.scenes[0].attributes["Name"].value == "Synthetic Test Scene"


def test_unknown_prop_device_values_are_reported_with_source_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsupported-device.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p" Name="Test" '
        'DeviceType="UnknownController" TraditionalType="PixelString" />'
        '</PreviewClass>',
        encoding="utf-8",
    )
    model = read_lorprev(source)
    assert [item.kind for item in model.unsupported_constructs] == [
        "device type", "traditional prop type"
    ]
    assert model.unsupported_constructs[0].source.value == "UnknownController"
    assert model.unsupported_constructs[0].source.file == str(source)
    assert model.unsupported_constructs[0].source.locator.endswith("/@DeviceType")
    assert model.unsupported_constructs[1].source.value == "PixelString"


def test_unknown_top_level_construct_is_preserved_and_reported(tmp_path: Path) -> None:
    source = tmp_path / "unknown.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p" />'
        '<FutureDeviceClass id="future" /></PreviewClass>',
        encoding="utf-8",
    )
    model = read_lorprev(source)
    assert len(model.unrecognized_top_level) == 1
    assert model.unrecognized_top_level[0].tag == "FutureDeviceClass"
    assert model.unrecognized_top_level[0].attributes["id"].value == "future"


def test_unrecognized_nested_controller_and_group_elements_are_reported_with_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nested-unknown-structures.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p">'
        '<ControllerClass id="controller-1" Name="Synthetic Controller">'
        '<NetworkGroup id="group-1" Name="Synthetic Group" />'
        '</ControllerClass></PropClass></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert [node.tag for node in model.unrecognized_elements] == [
        "ControllerClass", "NetworkGroup"
    ]
    controller, group = model.unrecognized_elements
    assert controller.attributes["id"].value == "controller-1"
    assert controller.attributes["id"].file == str(source)
    assert controller.attributes["id"].locator.endswith("/@id")
    assert group.attributes["Name"].value == "Synthetic Group"
    assert group.locator.endswith("/NetworkGroup[0]")


def test_raw_element_preserves_mixed_text_and_child_tail(tmp_path: Path) -> None:
    source = tmp_path / "mixed-content.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p">before'
        '<shape>inside</shape>after</PropClass></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    prop = model.props[0]
    assert prop.text == "before"
    assert prop.children[0].text == "inside"
    assert prop.children[0].tail == "after"


def test_excessive_xml_nesting_fails_with_actionable_error(tmp_path: Path) -> None:
    source = tmp_path / "deeply-nested.lorprev"
    depth = 300
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p">'
        + "<nested>" * depth
        + "</nested>" * depth
        + "</PropClass></PreviewClass>",
        encoding="utf-8",
    )

    with pytest.raises(LorprevError, match="nesting exceeds the maximum depth"):
        read_lorprev(source)


def test_owner_supplied_default_preview_is_rejected_as_zero_prop_fixture() -> None:
    with pytest.raises(LorprevError, match="zero PropClass"):
        read_lorprev(FIXTURES / "default_empty.lorprev")


def test_missing_preview_fails_with_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(LorprevError, match="Cannot access LORPREV file"):
        read_lorprev(tmp_path / "missing.lorprev")


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
