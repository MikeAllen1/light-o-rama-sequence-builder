"""Naming a song's parts by what repeats: verses, choruses and the bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.evaluation import load_analysis
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import get_style
from tests.display_builders import classic_yard, family_yard
from tests.song_forms import part_starts, write_song
from tests.test_planner import synthetic_analysis


@pytest.fixture(scope="module")
def song(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("form")
    write_song(folder / "song.wav")
    analyze_audio(folder / "song.wav", folder / "song.analysis.json", folder / "song.svg")
    return load_analysis(folder / "song.analysis.json")


def test_bars_are_described_by_harmony_and_tone(song: dict[str, Any]) -> None:
    bars = song["analysis"]["bar_signatures"]
    assert len(bars) >= 50
    assert all(len(b["chroma"]) == 12 and len(b["timbre"]) == 6 for b in bars)


def test_verses_choruses_and_the_bridge_are_found(song: dict[str, Any]) -> None:
    plan = plan_show(song, display_from_preview(classic_yard().element()), load_rule_set(),
                     style=get_style("classic"))
    found = [(s.label, round(s.start_centisecond / 100)) for s in plan.sections]
    truth = [(name, round(start)) for name, start in part_starts()]
    assert found == truth, found
    # Parts that return share a number; the bridge has its own.
    parts = {s.label: set() for s in plan.sections}
    for s in plan.sections:
        parts[s.label].add(s.part)
    assert len(parts["chorus"]) == 1 and len(parts["verse"]) == 1
    assert parts["bridge"] - parts["chorus"] - parts["verse"]
    assert any(n.startswith("Section names come from which parts") for n in plan.notes)


def _with_form(names: list[str]) -> dict[str, Any]:
    """A fictional analysis whose bars sound like the named parts (one per 8 bars)."""
    sound = {"verse": [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0], "chorus": [0, 0, 1, 0, 1, 1, 0, 0,
             1, 0, 0, 0], "bridge": [0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1],
             "intro": [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]}
    loud = {"intro": 0.15, "verse": 0.4, "chorus": 0.9, "bridge": 0.55}
    sections = tuple((16.0 * i, loud[n]) for i, n in enumerate(names))
    analysis = synthetic_analysis(duration=16.0 * len(names), sections=sections)
    bars = []
    for i, name in enumerate(names):
        for k in range(8):
            chroma = [v + 0.05 * ((k + j) % 3) for j, v in enumerate(sound[name])]
            bars.append({"time": 16.0 * i + 2.0 * k, "chroma": chroma,
                         "timbre": [0.5 if name == "chorus" else -0.2] * 6})
    analysis["analysis"]["bar_signatures"] = bars
    analysis["analysis"]["section_candidates"] = [{"time": 16.0 * i} for i in
                                                  range(1, len(names))]
    return analysis


def test_parts_come_from_bar_signatures_and_the_bridge_stands_apart() -> None:
    names = ["intro", "verse", "chorus", "verse", "chorus", "bridge", "chorus", "chorus"]
    display = classic_yard()
    analysis = _with_form(names)
    plan = plan_show(analysis, display_from_preview(display.element()), load_rule_set(),
                     style=get_style("classic"))
    assert [s.label for s in plan.sections][:7] == names[:7]
    assert check_choreography(display.element(), plan.choreography, load_rule_set()).ok
    bridge = next(s for s in plan.sections if s.label == "bridge")
    assert ("bridge", bridge.start_centisecond) in plan.moments
    # The returning chorus repeats its look.
    assert ("repeat", 6400) in plan.moments


def test_without_bar_signatures_the_loudness_names_stand() -> None:
    plan = plan_show(synthetic_analysis(), display_from_preview(family_yard().element()),
                     load_rule_set())
    assert all(s.part is None for s in plan.sections)
    assert any("guesses from loudness" in n for n in plan.notes)


def test_bar_signatures_are_checked_when_an_analysis_is_loaded(tmp_path: Path) -> None:
    from lor_sequence_builder.evaluation import EvaluationError

    analysis = _with_form(["intro", "verse", "chorus", "verse"])
    analysis["analysis"]["bar_signatures"][0]["chroma"] = [1, 2]
    path = tmp_path / "a.json"
    path.write_text(json.dumps(analysis), encoding="utf-8")
    with pytest.raises(EvaluationError, match="bar signature"):
        load_analysis(path)

