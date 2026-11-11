from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.loredit import read_loredit, write_loredit
from lor_sequence_builder.new_sequence import (
    FreeTimingGrid,
    NewSequenceError,
    build_new_sequence,
)
from lor_sequence_builder.pulse import PulseGenerationError, build_pulse_sequence
from tests.fixture_builders import write_synthetic_loredit

EXPECTED_TOP_LEVEL = [
    "PreviewClass", "BeatChannels", "Subsequences", "SequenceProps", "ArchivedProps",
    "RgbAggregates", "TimingGrids", "BeatView", "PropViews", "MotionPaks", "pictures",
]


def _synthetic_preview(tmp_path: Path) -> ET.Element:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sequence = write_synthetic_loredit(tmp_path / "source.loredit")
    preview = ET.parse(sequence).getroot().find("PreviewClass")
    assert preview is not None
    return preview


def _preview_file(tmp_path: Path, preview: ET.Element) -> Path:
    path = tmp_path / "display.lorprev"
    ET.ElementTree(preview).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_new_sequence_has_the_native_section_skeleton(tmp_path: Path) -> None:
    preview = _synthetic_preview(tmp_path)
    root = build_new_sequence(preview, 12_000, "Show\\song.mp3").document.root

    assert root.tag == "sequence"
    assert [child.tag for child in root] == EXPECTED_TOP_LEVEL
    assert root.get("saveFileVersion") == "15"
    assert root.get("totalCentiseconds") == "12000"
    assert root.get("musicFilename") == "Show\\song.mp3"
    fixed = root.findall("./TimingGrids/TimingGridFixed")
    assert [dict(grid.attrib) for grid in fixed] == [{"name": "Fixed Grid: 0.05", "spacing": "5"}]
    assert root.find("BeatChannels") is not None
    assert root.find("BeatChannels").get("MaxDisplayedRows") == "10"  # type: ignore[union-attr]
    assert not root.findall(".//effect")
    embedded = root.find("PreviewClass")
    assert embedded is not None
    assert ET.tostring(embedded) == ET.tostring(preview)


def test_sequence_props_follow_preview_order_and_channel_layouts(tmp_path: Path) -> None:
    preview = _synthetic_preview(tmp_path)
    built = build_new_sequence(preview, 12_000, "song.mp3")
    sequence_props = built.document.root.findall("./SequenceProps/SeqProp")

    supported = [
        prop for prop in preview.findall("PropClass") if prop.get("DeviceType") == "LOR"
    ]
    assert [sp.get("id") for sp in sequence_props] == [p.get("id") for p in supported]
    for prop, sequence_prop in zip(supported, sequence_props, strict=True):
        assert sequence_prop.get("name") == prop.get("Name")
        assert sequence_prop.get("EnablePixelChannels") == "0"
        count = len([entry for entry in prop.get("ChannelGrid", "").split(";") if entry])
        coordinates = [
            (channel.get("row"), channel.get("col"), channel.get("color"))
            for channel in sequence_prop.findall("channel")
        ]
        if prop.get("TraditionalType") == "Channel_per_color":
            assert coordinates == [("0", "0", str(i)) for i in range(count)]
        else:
            assert coordinates == [("0", str(i), "0") for i in range(count)]

    # The synthetic display's AC, DC, and DMX props have no verified layout.
    reasons = {item.prop_id: item.reason for item in built.excluded_props}
    assert set(reasons) == {
        p.get("id") for p in preview.findall("PropClass") if p.get("DeviceType") != "LOR"
    }
    assert all("no verified native channel layout" in reason for reason in reasons.values())


def test_props_linked_to_a_master_get_no_sequence_prop(tmp_path: Path) -> None:
    preview = _synthetic_preview(tmp_path)
    props = preview.findall("PropClass")
    linked = props[1]
    linked.set("MasterPropId", props[0].get("id", ""))

    built = build_new_sequence(preview, 12_000, "song.mp3")

    ids = [sp.get("id") for sp in built.document.root.findall("./SequenceProps/SeqProp")]
    assert linked.get("id") not in ids
    assert linked.get("id") not in {item.prop_id for item in built.excluded_props}

    preview_path = _preview_file(tmp_path, preview)
    result = build_pulse_sequence(
        preview_path, None, tmp_path / "linked.loredit", tmp_path / "linked.json", bpm=120,
        total_centiseconds=500, music_filename="song.mp3",
    )
    reasons = {item.prop_id: item.reason for item in result.excluded_props}
    assert "Linked to master prop" in reasons[linked.get("id", "")]


def test_new_sequence_is_deterministic_and_input_sensitive(tmp_path: Path) -> None:
    preview = _synthetic_preview(tmp_path)
    first = build_new_sequence(preview, 12_000, "song.mp3").document.root
    second = build_new_sequence(preview, 12_000, "song.mp3").document.root
    longer = build_new_sequence(preview, 12_001, "song.mp3").document.root

    assert ET.tostring(first) == ET.tostring(second)
    assert first.get("id") != longer.get("id")


def test_new_sequence_round_trips_through_the_native_reader(tmp_path: Path) -> None:
    preview = _synthetic_preview(tmp_path)
    built = build_new_sequence(
        preview, 12_000, "song.mp3",
        timing_grids=(FreeTimingGrid("Beats", (50, 0, 100, 50)),),
    )
    output = write_loredit(built.document, tmp_path / "new.loredit")

    reread = read_loredit(output)

    assert reread.total_centiseconds == 12_000
    grid = reread.root.find("./TimingGrids/TimingGridFree")
    assert grid is not None and grid.get("name") == "Beats"
    assert [t.get("centisecond") for t in grid.findall("timing")] == ["0", "50", "100"]


@pytest.mark.parametrize(
    ("duration", "music", "message"),
    [
        (0, "song.mp3", "duration"),
        (30 * 60 * 100 + 1, "song.mp3", "duration"),
        (100, "  ", "audio file name"),
        (100, "bad\nname.mp3", "control characters"),
    ],
)
def test_new_sequence_rejects_invalid_settings(
    tmp_path: Path, duration: int, music: str, message: str
) -> None:
    preview = _synthetic_preview(tmp_path)
    with pytest.raises(NewSequenceError, match=message):
        build_new_sequence(preview, duration, music)


def test_new_sequence_rejects_bad_previews_and_grids(tmp_path: Path) -> None:
    preview = _synthetic_preview(tmp_path)
    with pytest.raises(NewSequenceError, match="PreviewClass"):
        build_new_sequence(ET.Element("sequence"), 100, "song.mp3")
    with pytest.raises(NewSequenceError, match="unique"):
        build_new_sequence(
            preview, 100, "song.mp3",
            timing_grids=(FreeTimingGrid("Beats", ()), FreeTimingGrid("Beats", ())),
        )
    with pytest.raises(NewSequenceError, match="outside the sequence"):
        build_new_sequence(preview, 100, "song.mp3", timing_grids=(FreeTimingGrid("B", (101,)),))
    duplicate = _synthetic_preview(tmp_path / "dup")
    props = duplicate.findall("PropClass")
    props[1].set("id", props[0].get("id", ""))
    with pytest.raises(NewSequenceError, match="duplicate"):
        build_new_sequence(duplicate, 100, "song.mp3")
    unsupported = _synthetic_preview(tmp_path / "unsupported")
    for prop in unsupported.findall("PropClass"):
        prop.set("DeviceType", "DMX")
    with pytest.raises(NewSequenceError, match="No preview prop"):
        build_new_sequence(unsupported, 100, "song.mp3")


def test_pulse_builds_from_preview_alone(tmp_path: Path) -> None:
    preview_path = _preview_file(tmp_path, _synthetic_preview(tmp_path))
    output = tmp_path / "pulse.loredit"
    timeline = tmp_path / "pulse.timeline.json"

    result = build_pulse_sequence(
        preview_path, None, output, timeline, bpm=120,
        total_centiseconds=1_000, music_filename="Show\\song.mp3",
    )

    document = read_loredit(output)
    assert document.root.get("musicFilename") == "Show\\song.mp3"
    assert result.beat_count == 20
    assert result.supported_prop_count == 48
    assert {item.reason for item in result.excluded_props}
    effects = document.root.findall(".//effect")
    assert len(effects) == result.event_count > 0
    assert json.loads(timeline.read_text(encoding="utf-8"))["bpm"] == 120


def test_pulse_without_template_requires_duration_and_audio(tmp_path: Path) -> None:
    preview_path = _preview_file(tmp_path, _synthetic_preview(tmp_path))
    with pytest.raises(PulseGenerationError, match="duration and an audio file name"):
        build_pulse_sequence(
            preview_path, None, tmp_path / "a.loredit", tmp_path / "a.json", bpm=120,
            total_centiseconds=1_000,
        )
    template = write_synthetic_loredit(tmp_path / "template.loredit")
    with pytest.raises(PulseGenerationError, match="come from the template"):
        build_pulse_sequence(
            preview_path, template, tmp_path / "b.loredit", tmp_path / "b.json", bpm=120,
            total_centiseconds=1_000, music_filename="song.mp3",
        )
    assert not (tmp_path / "a.loredit").exists()
    assert not (tmp_path / "b.loredit").exists()


def test_cli_pulse_builds_without_a_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preview_path = _preview_file(tmp_path, _synthetic_preview(tmp_path))
    code = main([
        "pulse", "--preview", str(preview_path), "--bpm", "100",
        "--duration-seconds", "12.5", "--music-filename", "song.mp3",
        "--output", str(tmp_path / "cli.loredit"),
        "--timeline-output", str(tmp_path / "cli.timeline.json"),
    ])

    assert code == 0
    assert read_loredit(tmp_path / "cli.loredit").total_centiseconds == 1_250
    assert "Excluded props:" in capsys.readouterr().out
