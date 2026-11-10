from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder.lorprev import (
    LorprevError,
    UnsupportedLorprevRevisionError,
    read_lorprev,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_synthetic_preview_preserves_props_geometry_and_provenance() -> None:
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


def test_uploaded_default_preview_is_rejected_as_zero_prop_fixture(
    tmp_path: Path,
) -> None:
    # The owner-provided Default.lorprev is a native empty preview, not a display fixture.
    # Its safe structural content is represented in the test by an equivalent minimal file.
    empty = tmp_path / "empty.lorprev"
    empty.write_text(
        '<PreviewClass id="fixture" Name="Default" Revision="0">'
        '<Scene id="scene" Name="Scene 1" /><PropViews /></PreviewClass>',
        encoding="utf-8",
    )
    with pytest.raises(LorprevError, match="zero PropClass"):
        read_lorprev(empty)


def test_unsupported_revision_fails_clearly(tmp_path: Path) -> None:
    source = tmp_path / "future.lorprev"
    source.write_text(
        '<PreviewClass id="x" Name="Future" Revision="999">'
        '<PropClass id="p" Name="Test" /></PreviewClass>',
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedLorprevRevisionError, match="verified revision is 0"):
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
