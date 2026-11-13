"""S4 (.lms) sequences: reading, display conversion, writing and generation.

Every file here is invented in code; no owner or vendor sequence is used.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.lms import (
    LmsEffect,
    LmsError,
    build_lms,
    color_name,
    display_from_lms,
    parse_lms,
    preview_bytes,
    read_lms,
    write_lms,
)
from lor_sequence_builder.lorprev import read_lorprev

RED, GREEN, WHITE = 255, 65280, 16777215


def s4_sequence(
    channels: Sequence[tuple[str, int | None, str | None, str | None, str | None]] = (
        ("Arch 1", RED, "LOR", "1", "1"),
        ("Arch 2", RED, "LOR", "1", "2"),
        ("Arch 3", RED, "LOR", "1", "3"),
        ("Mini Tree 1", GREEN, "LOR", "1", "4"),
        ("Mini Tree 2", GREEN, "LOR", "1", "5"),
        ("Roof Line", WHITE, "LOR", "2", "1"),
        ("Spare", None, None, None, None),
    ),
    *,
    version: str = "14",
    groups: Sequence[tuple[str, Sequence[int]]] = (("Arches", (0, 1, 2)),
                                                  ("Trees", (3, 4))),
    nested: bool = True,
    animation: bool = True,
) -> bytes:
    """A small fictional S4 sequence, shaped like the S4 Sequencer saves them."""
    root = ET.Element("sequence", {"saveFileVersion": version, "author": "Someone",
                                   "createdAt": "1/1/2020 1:00:00 PM",
                                   "musicFilename": "Old Song.mp3", "videoUsage": "2"})
    container = ET.SubElement(root, "channels")
    for index, (name, color, device, unit, circuit) in enumerate(channels):
        attributes = {"name": name, "centiseconds": "1000", "savedIndex": str(index)}
        if color is not None:
            attributes["color"] = str(color)
        if device is not None:
            attributes["deviceType"] = device
        if unit is not None:
            attributes["unit"] = unit
        if circuit is not None:
            attributes["circuit"] = circuit
        channel = ET.SubElement(container, "channel", attributes)
        ET.SubElement(channel, "effect", {"type": "intensity", "startCentisecond": "0",
                                          "endCentisecond": "50", "intensity": "100"})
    next_index = len(channels)
    group_indices = []
    for name, members in groups:
        group = ET.SubElement(container, "channelGroupList", {
            "totalCentiseconds": "1000", "name": name, "savedIndex": str(next_index)})
        holder = ET.SubElement(group, "channelGroups")
        for member in members:
            ET.SubElement(holder, "channelGroup", {"savedIndex": str(member)})
        group_indices.append(next_index)
        next_index += 1
    if nested and len(group_indices) >= 2:
        group = ET.SubElement(container, "channelGroupList", {
            "totalCentiseconds": "1000", "name": "Everything", "savedIndex": str(next_index)})
        holder = ET.SubElement(group, "channelGroups")
        for member in group_indices:
            ET.SubElement(holder, "channelGroup", {"savedIndex": str(member)})
    grids = ET.SubElement(root, "timingGrids")
    ET.SubElement(grids, "timingGrid", {"saveID": "0", "name": "Fixed Grid: 0.10",
                                        "type": "fixed", "spacing": "10"})
    free = ET.SubElement(grids, "timingGrid", {"saveID": "1", "name": "Beats",
                                               "type": "freeform"})
    ET.SubElement(free, "timing", {"centisecond": "250"})
    tracks = ET.SubElement(root, "tracks")
    track = ET.SubElement(tracks, "track", {"totalCentiseconds": "1000", "timingGrid": "1"})
    refs = ET.SubElement(track, "channels")
    for index in range(len(channels)):
        ET.SubElement(refs, "channel", {"savedIndex": str(index)})
    loops = ET.SubElement(track, "loopLevels")
    ET.SubElement(loops, "loopLevel")
    if animation:
        grid = ET.SubElement(root, "animation", {"rows": "10", "columns": "20",
                                                 "image": ""})
        for index in range(len(channels) - 1):
            row = ET.SubElement(grid, "row", {"index": str(index)})
            ET.SubElement(row, "column", {"index": str(index * 2), "channel": str(index)})
    return b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\r\n' + ET.tostring(root)


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_reads_channels_addresses_and_groups(tmp_path: Path) -> None:
    document = read_lms(_write(tmp_path / "show.lms", s4_sequence()))
    assert document.save_file_version == "14"
    assert [c.name for c in document.channels][:2] == ["Arch 1", "Arch 2"]
    assert (document.channels[5].unit, document.channels[5].circuit) == ("2", "1")
    assert not document.channels[6].is_lor
    assert [g.name for g in document.groups] == ["Arches", "Trees", "Everything"]
    assert document.total_centiseconds == 1000


@pytest.mark.parametrize("version", ["9", "13", "15", "20"])
def test_any_save_file_version_reads(version: str) -> None:
    document = parse_lms(s4_sequence(version=version))
    assert len(document.channels) == 7
    assert document.save_file_version == version


@pytest.mark.parametrize(("content", "message"), [
    (b"", "empty"),
    (b"<sequence saveFileVersion='14'/>", "no channels"),
    (b"<lights/>", "not a Light-O-Rama sequence"),
    (b"<!DOCTYPE x [<!ENTITY a 'b'>]><sequence saveFileVersion='14'/>", "not a readable"),
    (b"<sequence saveFileVersion='15'><PreviewClass/></sequence>", "S5/S6"),
])
def test_rejects_unsafe_or_unsupported_files(content: bytes, message: str) -> None:
    with pytest.raises(LmsError, match=message):
        parse_lms(content)


def test_rejects_duplicate_identities_and_addresses() -> None:
    duplicate_address = s4_sequence((("A", RED, "LOR", "1", "1"), ("B", RED, "LOR", "1", "1")),
                                    groups=())
    with pytest.raises(LmsError, match="share unit 1 circuit 1"):
        parse_lms(duplicate_address)
    broken_group = s4_sequence(groups=(("Ghosts", (0, 99)),), nested=False)
    with pytest.raises(LmsError, match="savedIndex 99"):
        parse_lms(broken_group)
    deep = b"<sequence saveFileVersion='14'>" + b"<a>" * 100 + b"</a>" * 100 + b"</sequence>"
    with pytest.raises(LmsError, match="nested"):
        parse_lms(deep)


def test_display_is_one_prop_per_lor_channel_with_verbatim_addresses(tmp_path: Path) -> None:
    document = parse_lms(s4_sequence())
    display = display_from_lms(document, "My S4 Yard")
    assert len(display.prop_channels) == 6
    assert display.excluded == (("Spare", "no controller assigned"),)
    preview = _write(tmp_path / "display.lorprev", preview_bytes(display))
    model = read_lorprev(preview)
    assert not model.unsupported_constructs
    grids = {prop.attributes["Name"].value: prop.attributes["ChannelGrid"].value
             for prop in model.props}
    assert grids["Roof Line"] == "Regular,2,1,1,0,White"
    assert grids["Arch 1"] == "Regular,1,1,1,0,Red"
    groups = {group.name.value: len(group.members) for group in model.groups
              if group.name is not None}
    # The nested group flattens to its channels.
    assert groups == {"Arches": 3, "Trees": 2, "Everything": 5}
    arch = next(p for p in model.props if p.attributes["Name"].value == "Arch 1")
    assert arch.children[0].attributes["OffsetX"].value  # placed from the S4 visualizer


def test_colors_map_to_named_lor_colors() -> None:
    assert [color_name(v) for v in (RED, GREEN, 16711680, WHITE, 65535, 33023, None)] == [
        "Red", "Green", "Blue", "White", "Yellow", "Orange", "White"]


def test_written_lms_keeps_the_template_and_replaces_only_the_song(tmp_path: Path) -> None:
    template = parse_lms(s4_sequence())
    content = build_lms(template, [
        LmsEffect(0, "on", 0, 100, 100, 100),
        LmsEffect(0, "fade", 100, 300, 100, 0),
        LmsEffect(5, "twinkle", 50, 80, 60, 60),
    ], 2000, "New Song.mp3", section_starts=[0, 800, 1500])
    root = ET.fromstring(content)
    assert root.attrib == {"saveFileVersion": "14", "musicFilename": "New Song.mp3",
                           "videoUsage": "2"}
    channels = root.find("channels")
    assert channels is not None
    first = channels.findall("channel")[0]
    assert [e.attrib for e in first.findall("effect")] == [
        {"type": "intensity", "startCentisecond": "0", "endCentisecond": "100",
         "intensity": "100"},
        {"type": "intensity", "startCentisecond": "100", "endCentisecond": "300",
         "startIntensity": "100", "endIntensity": "0"},
    ]
    assert channels.findall("channel")[5].find("effect") is not None
    assert all(c.get("centiseconds") == "2000" for c in channels.findall("channel"))
    assert [c.get("unit") for c in channels.findall("channel")] == [
        "1", "1", "1", "1", "1", "2", None]
    timings = [t.get("centisecond") for t in root.iterfind("timingGrids/timingGrid/timing")]
    assert timings == ["800", "1500"]  # old beats removed; sections added
    assert root.find("tracks/track/loopLevels/loopLevel") is None
    assert content.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\r\n')
    output = write_lms(tmp_path / "new.lms", content)
    with pytest.raises(LmsError, match="already exists"):
        write_lms(output, content)


@pytest.mark.parametrize("effect", [
    LmsEffect(99, "on", 0, 10, 100, 100),
    LmsEffect(0, "spin", 0, 10, 100, 100),
    LmsEffect(0, "on", 0, 5000, 100, 100),
    LmsEffect(0, "on", 0, 10, 140, 140),
])
def test_writer_refuses_impossible_effects(effect: LmsEffect) -> None:
    with pytest.raises(LmsError):
        build_lms(parse_lms(s4_sequence()), [effect], 2000, "Song.mp3")


def test_writer_refuses_overlaps() -> None:
    with pytest.raises(LmsError, match="overlap"):
        build_lms(parse_lms(s4_sequence()), [LmsEffect(0, "on", 0, 100, 100, 100),
                                             LmsEffect(0, "on", 50, 150, 100, 100)],
                  2000, "Song.mp3")


def test_generate_builds_an_s4_show_from_an_s4_sequence(tmp_path: Path) -> None:
    from tests.test_audio_analysis import _rhythmic_track

    display = _write(tmp_path / "My Yard.lms", s4_sequence())
    song = tmp_path / "song.wav"
    _rhythmic_track(song, duration=12.0)
    output = tmp_path / "out" / "Show.lms"
    code = main(["generate", "--preview", str(display), "--audio", str(song),
                 "--output", str(output), "--no-vocals", "--no-ask"])
    assert code == 0
    show = read_lms(output)
    assert [c.name for c in show.channels] == [c.name for c in read_lms(display).channels]
    assert sum(c.effect_count for c in show.channels) > 0
    assert show.channels[6].effect_count == 0  # the unassigned channel is left dark
    assert show.root.get("musicFilename") == "song.wav"
    assert (tmp_path / "out" / "Show.rules.json").is_file()
    assert display.read_bytes() == s4_sequence()  # the source is never modified


def test_generate_refuses_mismatched_extensions(tmp_path: Path) -> None:
    display = _write(tmp_path / "yard.lms", s4_sequence())
    analysis = tmp_path / "a.json"
    analysis.write_text("{}", encoding="utf-8")
    code = main(["generate", "--preview", str(display), "--analysis", str(analysis),
                 "--output", str(tmp_path / "Show.loredit"), "--no-vocals", "--no-ask"])
    assert code != 0
