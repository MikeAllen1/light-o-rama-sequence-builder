from __future__ import annotations

from pathlib import Path
import gzip
import shutil

import pytest

from lor_sequence_builder.loredit import (
    LoreditError,
    UnsupportedLoreditVersionError,
    read_loredit,
    semantic_xml,
    write_loredit,
)

FIXTURE_GZIP = Path(__file__).parent / "fixtures" / "basic_show.loredit.gz"


@pytest.fixture
def fixture_path(tmp_path: Path) -> Path:
    fixture = tmp_path / "basic_show.loredit"
    with gzip.open(FIXTURE_GZIP, "rb") as source, fixture.open("wb") as target:
        shutil.copyfileobj(source, target)
    return fixture


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


def test_unsupported_version_fails_clearly(tmp_path: Path) -> None:
    source = tmp_path / "future.loredit"
    source.write_text(
        '<sequence saveFileVersion="999" totalCentiseconds="1">'
        "<SequenceProps/><TimingGrids/></sequence>",
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedLoreditVersionError, match="verified version is 15"):
        read_loredit(source)


@pytest.mark.parametrize(
    "content",
    [b"", b"not xml", b"<other />", b'<!DOCTYPE x [<!ENTITY e "boom">]><sequence />'],
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
        b'<sequence saveFileVersion="15" totalCentiseconds="1">'
        b'<SequenceProps/><TimingGrids/></sequence>',
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
    import xml.etree.ElementTree as ET

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
