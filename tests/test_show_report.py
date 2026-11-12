"""The readable show report written next to every generated sequence."""

from __future__ import annotations

from pathlib import Path

from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.rules import load_rule_set
from tests.display_builders import DisplayBuilder, classic_yard
from tests.test_audio_analysis import _rhythmic_track
from tests.test_planner import _preview


def test_every_generated_show_explains_itself(tmp_path: Path) -> None:
    display = classic_yard()
    # A pixel prop it cannot sequence, and a name that must be shown as text.
    display.add("Pixel <b>Tree</b>", "decor", shape="Tree", channels=1, unit="77",
                device="DMX", string_type="RGB", box=(0.7, 0.6, 0.1, 0.1))
    preview = _preview(tmp_path, display)
    profile = tmp_path / "requirements.yaml"
    profile.write_text("schema_version: rules-1.0\nrequirements:\n"
                       "  - type: never_use\n    props: {names: [Mini Tree 1]}\n",
                       encoding="utf-8")
    audio = tmp_path / "song.wav"
    _rhythmic_track(audio, duration=20.0)
    show = generate_show(preview, tmp_path / "show.loredit", load_rule_set((profile,)),
                         audio_path=audio, separate=False)
    html = show.summary_path.read_text(encoding="utf-8")
    assert show.summary_path.name == "show.report.html"
    assert "<script" not in html.lower() and "Pixel &lt;b&gt;Tree&lt;/b&gt;" in html
    assert "Every rule passed" in html
    assert "Check in the yard" in html and "song.wav" in html
    assert "spin or wipe in the direction they are drawn" in html  # the mega tree
    assert "Chases should run along each row" in html
    # Not sequenced, left dark (by a requirement), and used are all accounted for.
    assert "Not sequenced" in html and "Left dark" in html and "Used" in html
    assert "Mini Tree 1" in html and "never" in html.lower()
    for heading in ("The song", "Your props", "Your requirements", "Rules"):
        assert f">{heading}<" in html


def test_a_display_with_doubtful_props_asks_for_a_look(tmp_path: Path) -> None:
    display = DisplayBuilder("Odd Yard")
    for i in range(3):
        display.add(f"Thing {i + 1}", "unknown", shape="Line", channels=1, unit=str(30 + i),
                    box=(-0.5 + 0.4 * i, 0.0, 0.1, 0.05))
    preview = _preview(tmp_path, display)
    audio = tmp_path / "song.wav"
    _rhythmic_track(audio, duration=20.0)
    show = generate_show(preview, tmp_path / "odd.loredit", load_rule_set(),
                         audio_path=audio, separate=False)
    html = show.summary_path.read_text(encoding="utf-8")
    assert "could not tell what these are" in html and "Thing 1" in html
