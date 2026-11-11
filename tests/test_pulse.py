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
    preview = tree.getroot().find("PreviewClass")
    assert preview is not None
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
