"""The display and style used last are kept for the next New show."""

from __future__ import annotations

from pathlib import Path

from lor_sequence_builder import last_display


def test_the_last_display_and_style_are_kept_and_replaced(tmp_path: Path) -> None:
    folder = tmp_path / "kept"
    assert last_display.describe(folder) == {}
    assert last_display.load_display(folder) is None
    last_display.remember_style("elegant", folder)
    assert last_display.describe(folder) == {"style": "elegant"}
    last_display.remember_display(b"<preview one/>", "C:/Shows/yard.lorprev", "Yard", folder)
    assert last_display.describe(folder) == {"file_name": "yard.lorprev", "display": "Yard",
                                             "style": "elegant"}
    assert last_display.load_display(folder) == (b"<preview one/>", "yard.lorprev")
    last_display.remember_display(b"<preview two/>", "other.lorprev", "Other", folder)
    assert last_display.load_display(folder) == (b"<preview two/>", "other.lorprev")
    assert last_display.describe(folder)["style"] == "elegant"
    last_display.forget(folder)
    assert last_display.describe(folder) == {}


def test_odd_input_is_ignored(tmp_path: Path) -> None:
    folder = tmp_path / "kept"
    last_display.remember_style("x" * 500, folder)
    assert last_display.describe(folder) == {}
    (folder).mkdir(exist_ok=True)
    (folder / "about.json").write_text("not json", encoding="utf-8")
    assert last_display.describe(folder) == {}
