from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.pulse import (
    PulseGenerationError,
    _write_timeline_temp,
    build_pulse_sequence,
)
from tests.fixture_builders import write_synthetic_loredit


def independent_inputs(tmp_path: Path) -> tuple[Path, Path]:
    preview_path = tmp_path / "independent.lorprev"
    template_path = write_synthetic_loredit(
        tmp_path / "independent-template.loredit"
    )
    template_tree = ET.parse(template_path)
    template_root = template_tree.getroot()
    preview_root = template_root.find("PreviewClass")
    assert preview_root is not None
    first_prop = preview_root.find("PropClass")
    assert first_prop is not None
    shape = ET.SubElement(first_prop, "shape", {"ShapeName": "Synthetic Shape"})
    ET.SubElement(shape, "point", {"x": "0", "y": "0"})
    template_tree.write(template_path, encoding="utf-8", xml_declaration=True)
    ET.ElementTree(preview_root).write(
        preview_path, encoding="utf-8", xml_declaration=True
    )
    return preview_path, template_path


@pytest.fixture
def matching_inputs(tmp_path: Path) -> tuple[Path, Path]:
    template = write_synthetic_loredit(tmp_path / "template.loredit")
    tree = ET.parse(template)
    root = tree.getroot()
    preview = root.find("PreviewClass")
    sequence_props = root.find("SequenceProps")
    assert preview is not None
    assert sequence_props is not None
    # Keep only preview props with native sequence records, plus one explicit
    # unsupported declaration to exercise the exclusion/reporting path.
    sequence_ids = {
        prop.get("id") for prop in sequence_props.findall("SeqProp")
    }
    for prop in list(preview.findall("PropClass")):
        if prop.get("id") not in sequence_ids:
            preview.remove(prop)
    first_prop = preview.find("PropClass")
    assert first_prop is not None
    first_prop.set("TraditionalType", "Unsupported Fixture Type")
    tree.write(template, encoding="utf-8", xml_declaration=True)
    preview_path = tmp_path / "display.lorprev"
    ET.ElementTree(preview).write(
        preview_path, encoding="utf-8", xml_declaration=True
    )
    return preview_path, template

def test_pulse_pipeline_writes_native_sequence_and_versioned_timeline(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    output = tmp_path / "pulse.loredit"
    timeline_path = tmp_path / "pulse.timeline.json"

    result = build_pulse_sequence(preview, template, output, timeline_path, bpm=120)

    assert output.exists()
    assert timeline_path.exists()
    assert result.sequence_path == output
    assert result.timeline_path == timeline_path
    assert result.supported_prop_count > 0
    assert result.excluded_prop_count > 0
    assert result.beat_count == 419
    assert result.event_count > 0

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert timeline["schema_version"] == "1.0"
    assert timeline["timebase"] == "integer centiseconds from sequence start"
    assert timeline["bpm"] == 120
    assert len(timeline["preview_xml_sha256"]) == 64
    assert len(timeline["template_xml_sha256"]) == 64
    assert timeline["beat_positions_centiseconds"][:4] == [0, 50, 100, 150]
    assert len(timeline["events"]) == result.event_count
    assert all(
        event["channel"]["preview_channel_index"] == event["channel"]["channel_index"]
        and event["channel"]["network"]
        and event["channel"]["unit_id"]
        and event["channel"]["circuit"]
        for event in timeline["events"]
    )
    channel_refs = {
        (event["channel"]["prop_id"], event["channel"]["channel_index"])
        for event in timeline["events"]
    }
    event_refs = {
        (event["beat_index"], event["channel"]["prop_id"], event["channel"]["channel_index"])
        for event in timeline["events"]
    }
    assert len(event_refs) == len(timeline["events"])
    assert len(timeline["events"]) == len(timeline["beat_positions_centiseconds"]) * len(channel_refs)
    assert all(
        event["start_centisecond"]
        == timeline["beat_positions_centiseconds"][event["beat_index"]]
        for event in timeline["events"]
    )
    assert len(timeline["supported_prop_ids"]) == result.supported_prop_count
    assert len(timeline["excluded_props"]) == result.excluded_prop_count

    generated = read_loredit(output)
    effects = generated.root.findall("./SequenceProps/SeqProp/channel/effect")
    assert len(effects) == result.event_count
    assert all(effect.attrib["settings"] == "INTENSITY" for effect in effects)
    assert all(effect.attrib["intensity"] == "100" for effect in effects)
    assert all(int(effect.attrib["endCentisecond"]) <= generated.total_centiseconds for effect in effects)


def test_pulse_timeline_is_deterministic_for_identical_inputs(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    first = tmp_path / "first.loredit"
    first_timeline = tmp_path / "first.json"
    second = tmp_path / "second.loredit"
    second_timeline = tmp_path / "second.json"

    build_pulse_sequence(preview, template, first, first_timeline, bpm=137)
    build_pulse_sequence(preview, template, second, second_timeline, bpm=137)

    assert first_timeline.read_bytes() == second_timeline.read_bytes()


def test_preview_template_identity_mismatch_fails_before_output(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    tree = ET.parse(preview)
    prop = tree.getroot().find("PropClass")
    assert prop is not None
    prop.set("id", "not-a-template-prop")
    tree.write(preview, encoding="utf-8", xml_declaration=True)

    output = tmp_path / "mismatch.loredit"
    timeline_path = tmp_path / "mismatch.json"
    with pytest.raises(PulseGenerationError, match="prop IDs do not match exactly"):
        build_pulse_sequence(preview, template, output, timeline_path, bpm=120)
    assert not output.exists()
    assert not timeline_path.exists()


@pytest.mark.parametrize("bpm", [0, 29, 301, -120])
def test_invalid_bpm_fails_before_output(
    tmp_path: Path, matching_inputs: tuple[Path, Path], bpm: int
) -> None:
    preview, template = matching_inputs
    with pytest.raises(PulseGenerationError, match="BPM must be an integer"):
        build_pulse_sequence(
            preview, template, tmp_path / "invalid.loredit", tmp_path / "invalid.json", bpm
        )


def test_existing_output_is_never_overwritten(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    output = tmp_path / "existing.loredit"
    timeline_path = tmp_path / "new.json"
    output.write_text("preserve me", encoding="utf-8")

    with pytest.raises(PulseGenerationError, match="already exists"):
        build_pulse_sequence(preview, template, output, timeline_path, bpm=120)

    assert output.read_text(encoding="utf-8") == "preserve me"
    assert not timeline_path.exists()


def test_sequence_and_timeline_outputs_must_not_alias_inputs(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    with pytest.raises(PulseGenerationError, match="must not alias the preview"):
        build_pulse_sequence(
            preview, template, preview, tmp_path / "alias.json", bpm=120
        )


def test_pulse_cli_builds_sequence_and_timeline(
    tmp_path: Path, matching_inputs: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from lor_sequence_builder.cli import main

    preview, template = matching_inputs
    output = tmp_path / "cli.loredit"
    timeline = tmp_path / "cli.json"

    assert main(
        [
            "pulse",
            "--preview",
            str(preview),
            "--template",
            str(template),
            "--bpm",
            "120",
            "--output",
            str(output),
            "--timeline-output",
            str(timeline),
        ]
    ) == 0
    captured = capsys.readouterr().out
    assert "Supported props:" in captured
    assert "Pulse events:" in captured
    assert "Excluded prop " in captured
    assert output.exists()
    assert timeline.exists()


def test_prop_without_native_sequence_mapping_is_explicitly_excluded(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    tree = ET.parse(preview)
    supported = next(
        prop
        for prop in tree.getroot().findall("PropClass")
        if prop.get("DeviceType") == "LOR"
        and prop.get("TraditionalType") in {"Single Color", "Multicolor_string_1_ch"}
    )
    prop_id = supported.get("id")
    assert prop_id is not None

    sequence_tree = ET.parse(template)
    sequence_props = sequence_tree.getroot().find("SequenceProps")
    assert sequence_props is not None
    sequence_prop = sequence_props.find(f"SeqProp[@id='{prop_id}']")
    assert sequence_prop is not None
    sequence_props.remove(sequence_prop)
    sequence_tree.write(template, encoding="utf-8", xml_declaration=True)

    output = tmp_path / "missing-channel.loredit"
    timeline_path = tmp_path / "missing-channel.json"
    result = build_pulse_sequence(preview, template, output, timeline_path, bpm=120)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    excluded = next(item for item in timeline["excluded_props"] if item["prop_id"] == prop_id)
    assert "No matching native SeqProp" in excluded["reason"]
    assert prop_id not in timeline["supported_prop_ids"]
    assert all(event["channel"]["prop_id"] != prop_id for event in timeline["events"])
    assert result.excluded_prop_count == len(timeline["excluded_props"])
    assert output.exists()


def test_incomplete_native_channel_is_explicitly_excluded(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    sequence_tree = ET.parse(template)
    sequence_props = sequence_tree.getroot().find("SequenceProps")
    assert sequence_props is not None
    preview_tree = ET.parse(preview)
    supported = next(
        prop
        for prop in preview_tree.getroot().findall("PropClass")
        if prop.get("DeviceType") == "LOR"
        and prop.get("TraditionalType") in {"Single Color", "Multicolor_string_1_ch"}
    )
    prop_id = supported.get("id")
    assert prop_id is not None
    sequence_prop = sequence_props.find(f"SeqProp[@id='{prop_id}']")
    assert sequence_prop is not None
    channel = sequence_prop.find("channel")
    assert channel is not None
    channel.attrib.pop("color", None)
    sequence_tree.write(template, encoding="utf-8", xml_declaration=True)

    output = tmp_path / "incomplete-channel.loredit"
    timeline_path = tmp_path / "incomplete-channel.json"
    build_pulse_sequence(preview, template, output, timeline_path, bpm=120)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    excluded = next(item for item in timeline["excluded_props"] if item["prop_id"] == prop_id)
    assert "missing row, col, or color" in excluded["reason"]
    assert prop_id not in timeline["supported_prop_ids"]


@pytest.mark.parametrize("device_type", ["AC", "DC"])
def test_ac_and_dc_device_types_are_recognized_but_explicitly_excluded(
    tmp_path: Path, matching_inputs: tuple[Path, Path], device_type: str
) -> None:
    preview, template = matching_inputs
    preview_tree = ET.parse(preview)
    template_tree = ET.parse(template)
    preview_prop = next(
        prop
        for prop in preview_tree.getroot().findall("PropClass")
        if prop.get("DeviceType") == "LOR"
        and prop.get("TraditionalType") == "Multicolor_string_1_ch"
    )
    prop_id = preview_prop.get("id")
    assert prop_id is not None
    preview_prop.set("DeviceType", device_type)
    embedded = template_tree.getroot().find("PreviewClass")
    assert embedded is not None
    template_prop = embedded.find(f"PropClass[@id='{prop_id}']")
    assert template_prop is not None
    template_prop.set("DeviceType", device_type)
    preview_tree.write(preview, encoding="utf-8", xml_declaration=True)
    template_tree.write(template, encoding="utf-8", xml_declaration=True)

    output = tmp_path / f"legacy-{device_type.lower()}.loredit"
    timeline_path = tmp_path / f"legacy-{device_type.lower()}.json"
    build_pulse_sequence(preview, template, output, timeline_path, bpm=120)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    excluded = next(item for item in timeline["excluded_props"] if item["prop_id"] == prop_id)
    assert "legacy AC/DC native channel mapping is not verified" in excluded["reason"]
    assert prop_id not in timeline["supported_prop_ids"]


def test_channelgrid_address_count_must_match_native_channel_count(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    preview_tree = ET.parse(preview)
    template_tree = ET.parse(template)
    prop = next(
        item
        for item in preview_tree.getroot().findall("PropClass")
        if item.get("DeviceType") == "LOR"
        and item.get("TraditionalType") == "Multicolor_string_1_ch"
    )
    prop_id = prop.get("id")
    assert prop_id is not None
    prop.set("ChannelGrid", prop.get("ChannelGrid", "") + ";Regular,99,99,99,0,White")
    embedded = template_tree.getroot().find("PreviewClass")
    assert embedded is not None
    template_prop = embedded.find(f"PropClass[@id='{prop_id}']")
    assert template_prop is not None
    template_prop.set("ChannelGrid", prop.get("ChannelGrid", ""))
    preview_tree.write(preview, encoding="utf-8", xml_declaration=True)
    template_tree.write(template, encoding="utf-8", xml_declaration=True)

    output = tmp_path / "ambiguous-channel-map.loredit"
    timeline_path = tmp_path / "ambiguous-channel-map.json"
    build_pulse_sequence(preview, template, output, timeline_path, bpm=120)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    excluded = next(item for item in timeline["excluded_props"] if item["prop_id"] == prop_id)
    assert "Ambiguous physical mapping" in excluded["reason"]
    assert prop_id not in timeline["supported_prop_ids"]


def test_independent_s6_preview_and_native_template_prove_channel_mapping(
    tmp_path: Path,
) -> None:
    preview, template = independent_inputs(tmp_path)
    preview_root = ET.parse(preview).getroot()
    template_root = read_loredit(template).root
    assert preview_root.get("Revision") == "56"
    embedded_preview = template_root.find("PreviewClass")
    assert embedded_preview is not None
    assert embedded_preview.get("Revision") == "56"
    assert len(preview_root.findall("PropClass")) == 51
    assert len(preview_root.findall("PropGroup")) == 1

    output = tmp_path / "independent-generated.loredit"
    timeline_path = tmp_path / "independent-generated.json"
    result = build_pulse_sequence(preview, template, output, timeline_path, bpm=120)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    assert result.supported_prop_count == 48
    assert result.excluded_prop_count == 3
    assert result.event_count == 81 * result.beat_count
    assert len(timeline["events"]) == result.event_count

    preview_props = {
        prop.get("id"): prop for prop in preview_root.findall("PropClass")
    }
    sequence_props = {
        prop.get("id"): prop
        for prop in template_root.findall("./SequenceProps/SeqProp")
    }
    for event in timeline["events"]:
        channel = event["channel"]
        prop = preview_props[channel["prop_id"]]
        grid = prop.get("ChannelGrid", "").split(";")
        address = grid[channel["preview_channel_index"]].split(",")
        native = sequence_props[channel["prop_id"]].findall("channel")[
            channel["channel_index"]
        ]
        assert channel["network"] == address[0]
        assert channel["unit_id"] == address[1]
        assert channel["circuit"] == address[2]
        traditional_type = prop.get("TraditionalType")
        assert channel["row"] == native.get("row") == "0"
        if traditional_type == "Channel_per_color":
            assert channel["col"] == native.get("col") == "0"
            assert channel["color"] == native.get("color") == str(channel["channel_index"])
        else:
            assert channel["col"] == native.get("col") == str(channel["channel_index"])
            assert channel["color"] == native.get("color")
    generated = read_loredit(output)
    assert len(generated.root.findall("./SequenceProps/SeqProp/channel/effect")) == result.event_count
    per_color_events = [
        event for event in timeline["events"]
        if preview_props[event["channel"]["prop_id"]].get("TraditionalType") == "Channel_per_color"
    ]
    assert per_color_events
    assert any(event["channel"]["color"] == "1" for event in per_color_events)


def test_geometry_mismatch_between_independent_preview_and_template_is_rejected(
    tmp_path: Path,
) -> None:
    preview, template = independent_inputs(tmp_path)
    tree = ET.parse(preview)
    point = tree.getroot().find("./PropClass/shape/point")
    assert point is not None
    point.set("x", str(float(point.get("x", "0")) + 0.01))
    tree.write(preview, encoding="utf-8", xml_declaration=True)

    with pytest.raises(PulseGenerationError, match="mismatched preview data"):
        build_pulse_sequence(
            preview, template, tmp_path / "geometry-mismatch.loredit",
            tmp_path / "geometry-mismatch.json", bpm=120
        )


def test_prop_group_relationship_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    preview, template = independent_inputs(tmp_path)
    tree = ET.parse(preview)
    group = tree.getroot().find("PropGroup")
    assert group is not None
    member = group.find("member")
    assert member is not None
    other_prop = tree.getroot().findall("PropClass")[0]
    member.set("id", other_prop.get("id", ""))
    tree.write(preview, encoding="utf-8", xml_declaration=True)

    with pytest.raises(PulseGenerationError, match="PropGroup relationships"):
        build_pulse_sequence(
            preview, template, tmp_path / "group-mismatch.loredit",
            tmp_path / "group-mismatch.json", bpm=120
        )


def test_pulse_duration_cannot_exceed_beat_interval(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    with pytest.raises(PulseGenerationError, match="must not exceed"):
        build_pulse_sequence(
            preview, template, tmp_path / "too-long.loredit",
            tmp_path / "too-long.json", bpm=300, pulse_duration_centiseconds=21
        )


def test_timeline_lists_unsupported_props_with_reasons(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    output = tmp_path / "unsupported-report.loredit"
    timeline_path = tmp_path / "unsupported-report.json"
    build_pulse_sequence(preview, template, output, timeline_path, bpm=120)

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert timeline["excluded_props"]
    assert all(item["prop_id"] and item["reason"] for item in timeline["excluded_props"])


def test_non_integer_bpm_is_rejected(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    with pytest.raises(PulseGenerationError, match="BPM must be an integer"):
        build_pulse_sequence(
            preview, template, tmp_path / "fractional.loredit",
            tmp_path / "fractional.json", bpm=120.5  # type: ignore[arg-type]
        )


def test_unreasonably_long_template_is_rejected_before_beat_allocation(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    tree = ET.parse(template)
    tree.getroot().set("totalCentiseconds", "999999999999")
    tree.write(template, encoding="utf-8", xml_declaration=True)

    with pytest.raises(PulseGenerationError, match="more than 50000 beats"):
        build_pulse_sequence(
            preview, template, tmp_path / "too-long.loredit",
            tmp_path / "too-long.json", bpm=120
        )
    assert not (tmp_path / "too-long.loredit").exists()
    assert not (tmp_path / "too-long.json").exists()


def test_preview_template_channel_declarations_must_match(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    tree = ET.parse(preview)
    prop = next(
        item
        for item in tree.getroot().findall("PropClass")
        if item.get("DeviceType") == "LOR"
        and item.get("TraditionalType") in {"Single Color", "Multicolor_string_1_ch"}
    )
    prop_id = prop.get("id")
    assert prop_id is not None
    prop.set("ChannelGrid", "Different,99,99,99,0,White")
    tree.write(preview, encoding="utf-8", xml_declaration=True)

    with pytest.raises(PulseGenerationError, match="mismatched preview data"):
        build_pulse_sequence(
            preview, template, tmp_path / "channel-mismatch.loredit",
            tmp_path / "channel-mismatch.json", bpm=120
        )
    assert not (tmp_path / "channel-mismatch.loredit").exists()
    assert not (tmp_path / "channel-mismatch.json").exists()


def test_display_with_no_supported_props_fails_before_output(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    preview_tree = ET.parse(preview)
    template_tree = ET.parse(template)
    for root in (preview_tree.getroot(), template_tree.getroot()):
        preview_class = root if root.tag == "PreviewClass" else root.find("PreviewClass")
        assert preview_class is not None
        for prop in preview_class.findall("PropClass"):
            prop.set("TraditionalType", "Unsupported Fixture Type")
    preview_tree.write(preview, encoding="utf-8", xml_declaration=True)
    template_tree.write(template, encoding="utf-8", xml_declaration=True)

    output = tmp_path / "unsupported-only.loredit"
    timeline = tmp_path / "unsupported-only.json"
    with pytest.raises(PulseGenerationError, match="No props qualify"):
        build_pulse_sequence(preview, template, output, timeline, bpm=120)
    assert not output.exists()
    assert not timeline.exists()



def test_timeline_temp_is_written_through_reserved_handle(tmp_path: Path) -> None:
    temporary = _write_timeline_temp(
        tmp_path, prefix=".sequence.", suffix=".tmp", content='{"safe": true}'
    )
    try:
        assert temporary.exists()
        assert temporary.read_text(encoding="utf-8") == '{"safe": true}'
    finally:
        temporary.unlink(missing_ok=True)
