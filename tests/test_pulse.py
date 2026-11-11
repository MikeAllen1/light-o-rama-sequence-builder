from __future__ import annotations

import gzip
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.pulse import PulseGenerationError, build_pulse_sequence

FIXTURE = Path(__file__).parent / "fixtures" / "basic_show.loredit.gz"


@pytest.fixture
def matching_inputs(tmp_path: Path) -> tuple[Path, Path]:
    template = tmp_path / "template.loredit"
    with gzip.open(FIXTURE, "rb") as source, template.open("wb") as target:
        shutil.copyfileobj(source, target)

    tree = ET.parse(template)
    root = tree.getroot()
    preview = root.find("PreviewClass")
    sequence_props = root.find("SequenceProps")
    assert preview is not None
    assert sequence_props is not None
    # The compact source fixture has three preview-only props with no SeqProp.
    # Build a deliberately matched test display from the exact prop IDs that
    # already have native sequence-channel records; no channel IDs are invented.
    sequence_ids = {
        prop.get("id") for prop in sequence_props.findall("SeqProp")
    }
    for prop in list(preview.findall("PropClass")):
        if prop.get("id") not in sequence_ids:
            preview.remove(prop)
    preview_path = tmp_path / "display.lorprev"
    ET.ElementTree(preview).write(preview_path, encoding="utf-8", xml_declaration=True)
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
    assert output.exists()
    assert timeline.exists()


def test_supported_prop_without_native_channel_mapping_fails_closed(
    tmp_path: Path, matching_inputs: tuple[Path, Path]
) -> None:
    preview, template = matching_inputs
    tree = ET.parse(preview)
    preview_props = tree.getroot().findall("PropClass")
    supported = next(
        prop
        for prop in preview_props
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

    with pytest.raises(PulseGenerationError, match=f"Supported prop {prop_id!r}"):
        build_pulse_sequence(
            preview, template, tmp_path / "missing-channel.loredit",
            tmp_path / "missing-channel.json", bpm=120
        )
    assert not (tmp_path / "missing-channel.loredit").exists()
    assert not (tmp_path / "missing-channel.json").exists()


def test_supported_prop_with_incomplete_native_channel_fails_closed(
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

    with pytest.raises(PulseGenerationError, match="missing row, col, or color"):
        build_pulse_sequence(
            preview, template, tmp_path / "incomplete-channel.loredit",
            tmp_path / "incomplete-channel.json", bpm=120
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
