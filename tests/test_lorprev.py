from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse as safe_parse

import lor_sequence_builder.lorprev as lorprev_module
from lor_sequence_builder.lorprev import (
    MAX_LORPREV_BYTES,
    LorprevError,
    read_lorprev,
)
from tests.fixture_builders import write_synthetic_loredit

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
    assert model.display.attributes["Name"].value == "Synthetic Test Display"
    assert model.prop_views[0].tag == "PropViews"


def test_synthetic_revision_one_preview_preserves_full_prop_model(tmp_path: Path) -> None:
    # Runtime-generated fixture uses only fictional IDs, channel addresses, and names.
    root = ET.Element(
        "PreviewClass",
        {
            "id": "synthetic-display",
            "Name": "Synthetic S6 Revision 1 Fixture",
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
            "Icicles" if index == 15 else
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
            point_count = 42 if index <= 15 else 41
            for point_index in range(point_count):
                ET.SubElement(
                    shape,
                    "point",
                    {
                        "x": str(index / 100 + point_index / 10_000),
                        "y": str(0.5 + point_index / 100_000),
                    },
                )
    ET.SubElement(root, "PropViews")
    source = tmp_path / "synthetic_revision_1.lorprev"
    ET.ElementTree(root).write(source, encoding="utf-8", xml_declaration=True)

    model = read_lorprev(source)
    assert model.revision.value == "1"
    assert len(model.props) == 51
    assert len(model.channel_grid_entries) == 69
    assert len(model.geometry_points) == 1900
    assert model.unsupported_constructs == ()
    assert all(entry.source.locator.endswith("/@ChannelGrid") for entry in model.channel_grid_entries)
    assert model.channel_grid_entries[0].entry_index == 0
    assert model.channel_grid_entries[0].device_type == "LOR"
    assert model.channel_grid_entries[0].network == "Regular"
    assert model.channel_grid_entries[0].unit_id == "99"
    assert model.channel_grid_entries[0].circuit == "01"
    assert model.channel_grid_entries[0].raw_fields == (
        "Regular", "99", "01", "01", "0", "Multi"
    )
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


def test_dmx_channel_grid_is_interpreted_without_losing_raw_fields(tmp_path: Path) -> None:
    source = tmp_path / "dmx-channel-grid.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="dmx-prop" DeviceType="DMX" '
        'ChannelGrid="12,301,extra" /></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assignment = model.channel_grid_entries[0]
    assert assignment.device_type == "DMX"
    assert assignment.universe == "12"
    assert assignment.channel == "301"
    assert assignment.network is None
    assert assignment.unit_id is None
    assert assignment.raw_fields == ("12", "301", "extra")
    assert model.unsupported_constructs == ()


def test_incomplete_lor_channel_grid_is_preserved_and_reported(tmp_path: Path) -> None:
    source = tmp_path / "incomplete-lor-channel-grid.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="lor-prop" DeviceType="LOR" '
        'ChannelGrid="Regular,99" /></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert model.channel_grid_entries[0].raw_fields == ("Regular", "99")
    assert model.channel_grid_entries[0].network is None
    assert [item.kind for item in model.unsupported_constructs] == [
        "channel assignment"
    ]


def test_undetermined_device_type_is_supported_as_unassigned(tmp_path: Path) -> None:
    source = tmp_path / "undetermined-device.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="unknown-prop" '
        'DeviceType="Undetermined" /></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert model.unsupported_constructs == ()


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



def test_point_like_elements_outside_shape_are_not_interpreted_as_geometry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unrelated-point.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p">'
        '<shape><point x="1" y="2" /></shape>'
        '<ControllerClass><point x="99" y="100" /></ControllerClass>'
        '</PropClass></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert len(model.geometry_points) == 1
    assert model.geometry_points[0].x.value == "1"
    assert [node.tag for node in model.unrecognized_elements] == [
        "ControllerClass"
    ]


def test_nested_unrecognized_shape_is_not_interpreted_as_prop_geometry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unrelated-shape.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p">'
        '<shape><point x="1" y="2" /></shape>'
        '<ControllerClass><shape><point x="99" y="100" /></shape></ControllerClass>'
        '</PropClass></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert len(model.geometry_points) == 1
    assert model.geometry_points[0].x.value == "1"
    assert [node.tag for node in model.unrecognized_elements] == [
        "ControllerClass"
    ]


def test_incomplete_shape_geometry_point_fails_clearly(tmp_path: Path) -> None:
    source = tmp_path / "incomplete-point.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p">'
        '<shape><point x="1" /></shape></PropClass></PreviewClass>',
        encoding="utf-8",
    )

    with pytest.raises(LorprevError, match="both x and y attributes are required"):
        read_lorprev(source)


def test_preview_size_limit_is_enforced_while_reading(tmp_path: Path) -> None:
    source = tmp_path / "oversized.lorprev"
    source.write_bytes(b"x" * (MAX_LORPREV_BYTES + 1))

    with pytest.raises(LorprevError, match="20 MiB limit"):
        read_lorprev(source)

def test_synthetic_revision_56_preview_parses_native_prop_group(
    tmp_path: Path,
) -> None:
    template = write_synthetic_loredit(tmp_path / "synthetic-template.loredit")
    source = tmp_path / "synthetic-revision-56.lorprev"
    template_root = safe_parse(template).getroot()
    assert template_root is not None
    preview = template_root.find("PreviewClass")
    assert preview is not None
    ET.ElementTree(preview).write(source, encoding="utf-8", xml_declaration=True)

    model = read_lorprev(source)
    assert model.revision.value == "56"
    assert len(model.props) == 51
    assert len(model.groups) == 1

    group = model.groups[0]
    assert group.group_id is not None
    assert group.group_id.value == "synthetic-group-0001"
    assert group.name is not None and group.name.value == "Synthetic Fixture Group"
    assert group.arrangement is not None and group.arrangement.value == "Preview"
    assert len(group.members) == 5
    prop_names = {
        prop.attributes["id"].value: prop.attributes["Name"].value
        for prop in model.props
    }
    assert [
        prop_names[member.prop_id.value]
        for member in group.members
        if member.prop_id is not None
    ] == [
        "Synthetic Prop 11",
        "Synthetic Prop 10",
        "Synthetic Prop 09",
        "Synthetic Prop 08",
        "Synthetic Prop 07",
    ]
    assert all(
        member.orientation is not None and member.orientation.value == "normal"
        for member in group.members
    )
    assert all(
        member.top is not None and member.top.value == "0"
        for member in group.members
    )
    assert all(
        member.left is not None and member.left.value == "0"
        for member in group.members
    )
    assert group.source.locator == "/PreviewClass/PropGroup[0]"
    assert all(
        member.source.locator.startswith(group.source.locator + "/member[")
        for member in group.members
    )
    assert model.unsupported_constructs == ()
    assert model.unrecognized_top_level == ()


def test_empty_synthetic_preview_is_rejected_as_zero_prop_fixture(tmp_path: Path) -> None:
    source = tmp_path / "empty-preview.lorprev"
    source.write_text('<PreviewClass Revision="1" />', encoding="utf-8")
    with pytest.raises(LorprevError, match="zero PropClass"):
        read_lorprev(source)


def test_missing_preview_fails_with_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(LorprevError, match="Cannot access LORPREV file"):
        read_lorprev(tmp_path / "missing.lorprev")


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not xml",
        b"<Other />",
        b'<!DOCTYPE x [<!ENTITY e "boom">]><PreviewClass Revision="0" />',
        b'<PreviewClass Revision="0" />',
    ],
)
def test_invalid_or_unsafe_previews_fail(content: bytes, tmp_path: Path) -> None:
    source = tmp_path / "invalid.lorprev"
    source.write_bytes(content)
    with pytest.raises(LorprevError):
        read_lorprev(source)


def test_missing_prop_id_is_reported_without_discarding_prop(tmp_path: Path) -> None:
    source = tmp_path / "missing-prop-id.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass Name="No ID" />'
        '</PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert len(model.props) == 1
    assert [item.kind for item in model.unsupported_constructs] == ["prop identity"]
    assert model.unsupported_constructs[0].source.locator.endswith("/@id")
    assert "missing a non-empty id" in model.unsupported_constructs[0].detail


def test_duplicate_prop_ids_are_reported_without_discarding_source_props(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplicate-prop-id.lorprev"
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="duplicate" Name="First" />'
        '<PropClass id="duplicate" Name="Second" /></PreviewClass>',
        encoding="utf-8",
    )

    model = read_lorprev(source)
    assert len(model.props) == 2
    assert [prop.attributes["Name"].value for prop in model.props] == ["First", "Second"]
    assert [item.kind for item in model.unsupported_constructs] == ["prop identity"]
    assert model.unsupported_constructs[0].source.value == "duplicate"
    assert model.unsupported_constructs[0].source.locator.endswith("/@id")


def test_xml_element_count_limit_is_enforced_during_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "too-many-elements.lorprev"
    monkeypatch.setattr(lorprev_module, "MAX_LORPREV_ELEMENTS", 5)
    source.write_text(
        '<PreviewClass Revision="1"><PropClass id="p" />'
        '<Unknown /><Unknown /><Unknown /><Unknown /></PreviewClass>',
        encoding="utf-8",
    )

    with pytest.raises(LorprevError, match="maximum element count of 5"):
        read_lorprev(source)


@pytest.mark.parametrize("revision", ["2", "12", "58", "999"])
def test_any_edit_revision_is_accepted_and_recorded(tmp_path: Path, revision: str) -> None:
    # Revision is an edit counter, not a format version; it must never gate parsing.
    source = tmp_path / "edited.lorprev"
    source.write_text(
        f'<PreviewClass id="x" Name="Edited" Revision="{revision}">'
        '<PropClass id="p" Name="Test" /></PreviewClass>',
        encoding="utf-8",
    )
    model = read_lorprev(source)
    assert model.revision is not None
    assert model.revision.value == revision
    assert model.revision.locator == "/PreviewClass/@Revision"
    assert len(model.props) == 1


def test_missing_revision_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "no_revision.lorprev"
    source.write_text(
        '<PreviewClass id="x" Name="No Revision">'
        '<PropClass id="p" Name="Test" /></PreviewClass>',
        encoding="utf-8",
    )
    model = read_lorprev(source)
    assert model.revision is None
    assert len(model.props) == 1
