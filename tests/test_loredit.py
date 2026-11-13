from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.loredit import (
    LoreditError,
    read_loredit,
    semantic_xml,
    write_loredit,
)
from tests.fixture_builders import write_synthetic_loredit


@pytest.fixture
def fixture_path(tmp_path: Path) -> Path:
    return write_synthetic_loredit(tmp_path / "synthetic-show.loredit")


def test_fixture_has_expected_observed_structure(fixture_path: Path) -> None:
    document = read_loredit(fixture_path)
    assert document.save_file_version == "15"
    assert document.total_centiseconds == 20_925
    sequence_props = document.root.findall("./SequenceProps/SeqProp")
    preview_ids = {
        prop.attrib["id"] for prop in document.root.findall("./PreviewClass/PropClass")
    }
    assert len(sequence_props) == 48
    assert all(prop.attrib["id"] in preview_ids for prop in sequence_props)
    assert len(document.root.findall("./TimingGrids/*")) == 8
    assert len(preview_ids) == 51
    effect_types = {
        effect.get("settings")
        for effect in document.root.findall("./SequenceProps/SeqProp/channel/effect")
    }
    assert {"INTENSITY", "TWINKLE", "SHIMMER"}.issubset(effect_types)


def test_semantic_round_trip_preserves_unknown_sequence_content(
    tmp_path: Path, fixture_path: Path
) -> None:
    output = tmp_path / "roundtrip.loredit"
    before = semantic_xml(fixture_path)
    document = read_loredit(fixture_path)
    write_loredit(document, output)
    assert semantic_xml(output) == before
    assert output.stat().st_size > 0


def test_writer_never_overwrites_source(tmp_path: Path, fixture_path: Path) -> None:
    source = tmp_path / "source.loredit"
    shutil.copyfile(fixture_path, source)
    original = source.read_bytes()
    document = read_loredit(source)
    with pytest.raises(LoreditError, match="overwrite the source"):
        write_loredit(document, source)
    assert source.read_bytes() == original


def test_writer_never_overwrites_existing_destination(
    tmp_path: Path, fixture_path: Path
) -> None:
    output = tmp_path / "existing.loredit"
    output.write_text("keep me", encoding="utf-8")
    with pytest.raises(LoreditError, match="already exists"):
        write_loredit(read_loredit(fixture_path), output)
    assert output.read_text(encoding="utf-8") == "keep me"


def test_writer_revalidates_document_before_creating_output(
    tmp_path: Path, fixture_path: Path
) -> None:
    document = read_loredit(fixture_path)
    sequence_props = document.root.find("SequenceProps")
    assert sequence_props is not None
    ET.SubElement(sequence_props, "SeqProp", {"id": "late-orphan"})
    output = tmp_path / "must-not-exist.loredit"
    with pytest.raises(LoreditError, match="missing from PreviewClass"):
        write_loredit(document, output)
    assert not output.exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("version", ["999", "16", "12", None])
def test_any_save_file_version_reads_and_writes(tmp_path: Path, version: str | None) -> None:
    attribute = "" if version is None else f' saveFileVersion="{version}"'
    source = tmp_path / "any.loredit"
    source.write_text(
        f'<sequence{attribute} totalCentiseconds="1">'
        '<PreviewClass id="p"/><SequenceProps/><TimingGrids/></sequence>',
        encoding="utf-8",
    )
    document = read_loredit(source)
    assert document.save_file_version == (version or "")
    copy = write_loredit(document, tmp_path / "copy.loredit")
    assert read_loredit(copy).save_file_version == (version or "")


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not xml",
        b"<other />",
        b'<!DOCTYPE x [<!ENTITY e "boom">]><sequence />',
        (
            b'<!DOCTYPE sequence><sequence saveFileVersion="15" totalCentiseconds="1">'
            b"<PreviewClass/><SequenceProps/><TimingGrids/></sequence>"
        ),
    ],
)
def test_invalid_or_unsafe_xml_fails(content: bytes, tmp_path: Path) -> None:
    source = tmp_path / "invalid.loredit"
    source.write_bytes(content)
    with pytest.raises(LoreditError):
        read_loredit(source)


@pytest.mark.parametrize(
    "content",
    [
        b'<sequence saveFileVersion="15" totalCentiseconds="1"><TimingGrids/></sequence>',
        b'<sequence saveFileVersion="15" totalCentiseconds="1"><SequenceProps/></sequence>',
        (
            b'<sequence saveFileVersion="15" totalCentiseconds="1">'
            b'<SequenceProps/><TimingGrids/></sequence>'
        ),
    ],
)
def test_missing_required_sections_fail(content: bytes, tmp_path: Path) -> None:
    source = tmp_path / "missing-section.loredit"
    source.write_bytes(content)
    with pytest.raises(LoreditError):
        read_loredit(source)


def test_sequence_prop_missing_from_preview_is_rejected(
    tmp_path: Path, fixture_path: Path
) -> None:
    source = tmp_path / "orphan.loredit"
    tree = ET.parse(fixture_path)
    sequence_props = tree.getroot().find("SequenceProps")
    assert sequence_props is not None
    ET.SubElement(
        sequence_props,
        "SeqProp",
        {"id": "orphan-prop-id", "name": "Orphan Prop"},
    )
    tree.write(source, encoding="utf-8", xml_declaration=True)

    with pytest.raises(LoreditError, match="missing from PreviewClass"):
        read_loredit(source)



def test_sequence_prop_may_reference_native_preview_group_id(
    tmp_path: Path, fixture_path: Path
) -> None:
    source = tmp_path / "group-sequence-prop.loredit"
    tree = ET.parse(fixture_path)
    preview = tree.getroot().find("PreviewClass")
    sequence_props = tree.getroot().find("SequenceProps")
    assert preview is not None
    assert sequence_props is not None
    group_id = "native-preview-group-id"
    ET.SubElement(preview, "PropGroup", {"id": group_id, "Name": "Fixture Group"})
    ET.SubElement(sequence_props, "SeqProp", {"id": group_id, "name": "Fixture Group"})
    tree.write(source, encoding="utf-8", xml_declaration=True)

    document = read_loredit(source)
    assert document.root.find(f"./SequenceProps/SeqProp[@id='{group_id}']") is not None


def test_reader_rejects_excessive_xml_nesting(tmp_path: Path) -> None:
    source = tmp_path / "deep.loredit"
    nested = "<nested>" * 256 + "</nested>" * 256
    source.write_text(
        '<sequence saveFileVersion="15" totalCentiseconds="1">'
        + nested
        + "<PreviewClass/><SequenceProps/><TimingGrids/></sequence>",
        encoding="utf-8",
    )
    with pytest.raises(LoreditError, match="nesting depth"):
        read_loredit(source)


def test_reader_rejects_excessive_xml_element_count(tmp_path: Path) -> None:
    source = tmp_path / "many-elements.loredit"
    source.write_text(
        '<sequence saveFileVersion="15" totalCentiseconds="1">'
        + "<extension/>" * 100_000
        + "<PreviewClass/><SequenceProps/><TimingGrids/></sequence>",
        encoding="utf-8",
    )
    with pytest.raises(LoreditError, match="element limit"):
        read_loredit(source)


@pytest.mark.parametrize("duplicate_kind", ["prop", "group", "sequence_prop"])
def test_reader_rejects_duplicate_native_identities(
    tmp_path: Path, fixture_path: Path, duplicate_kind: str
) -> None:
    source = tmp_path / f"duplicate-{duplicate_kind}.loredit"
    tree = ET.parse(fixture_path)
    root = tree.getroot()
    preview = root.find("PreviewClass")
    sequence_props = root.find("SequenceProps")
    assert preview is not None and sequence_props is not None

    if duplicate_kind == "prop":
        props = preview.findall("PropClass")
        props[1].set("id", props[0].get("id", ""))
    elif duplicate_kind == "group":
        group = ET.SubElement(preview, "PropGroup", {"id": "duplicate-group-id"})
        props = preview.findall("PropClass")
        props[0].set("id", group.get("id", ""))
    else:
        props = sequence_props.findall("SeqProp")
        duplicate = ET.fromstring(ET.tostring(props[0]))
        sequence_props.append(duplicate)

    tree.write(source, encoding="utf-8", xml_declaration=True)
    with pytest.raises(LoreditError, match="duplicate"):
        read_loredit(source)
