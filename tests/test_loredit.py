from pathlib import Path

import pytest

from lor_sequence_builder.loredit import LoreditError, inspect_loredit


def test_inspect_loredit_xml(tmp_path: Path):
    sample = tmp_path / "sample.loredit"
    sample.write_text(
        '<?xml version="1.0"?><Sequence><Props/><Effects><Effect/></Effects></Sequence>',
        encoding="utf-8",
    )

    result = inspect_loredit(sample)

    assert result["root_element"] == "Sequence"
    assert result["element_counts"]["Effect"] == 1
    assert result["top_level_elements"] == ["Props", "Effects"]


def test_invalid_xml_is_rejected(tmp_path: Path):
    sample = tmp_path / "broken.loredit"
    sample.write_text("<Sequence>", encoding="utf-8")

    with pytest.raises(LoreditError):
        inspect_loredit(sample)
