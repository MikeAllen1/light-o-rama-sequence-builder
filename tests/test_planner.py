from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.choreography import Choreography, choreography_json
from lor_sequence_builder.cli import main
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.planner import HIGH, LOW, MID, Plan, plan_show
from lor_sequence_builder.rules import (
    RuleReport,
    RuleSet,
    check_choreography,
    display_from_preview,
    load_rule_set,
)
from lor_sequence_builder.sequence_writer import SequenceWriteError
from tests.display_builders import (
    ALL_DISPLAYS,
    DisplayBuilder,
    classic_yard,
    line_drawn_yard,
    roofline_house,
)
from tests.test_audio_analysis import _rhythmic_track

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def synthetic_analysis(
    duration: float = 60.0,
    bpm: float = 120.0,
    sections: tuple[tuple[float, float], ...] = ((0.0, 0.1), (16.0, 0.3), (32.0, 0.9),
                                                 (48.0, 0.5)),
    stops: tuple[tuple[float, float], ...] = (),
    beats: bool = True,
) -> dict[str, Any]:
    """A fictional analysis report: steady beats, sections at the given loudness."""
    beat = 60.0 / bpm
    times = [round(i * beat, 3) for i in range(int(duration / beat))] if beats else []
    loud = [(start, rms) for start, rms in sections]

    def rms_at(t: float) -> float:
        for start, stop_length in stops:
            if start <= t < start + stop_length:
                return 0.0
        return [rms for start, rms in loud if start <= t][-1]

    return {
        "schema_version": "2.0",
        "audio": {"file_name": "Fictional Song.wav", "duration_seconds": duration},
        "analysis": {
            "tempo": {"bpm": bpm if beats else None},
            "beats": [{"time": t, "confidence": 0.9} for t in times],
            "downbeats": [{"time": t, "confidence": 0.8} for t in times[::4]],
            "onsets": [],
            "energy": [{"time": round(i * 0.5, 2), "rms": rms_at(i * 0.5)}
                       for i in range(int(duration * 2))],
            "phrase_boundaries": [],
            "section_candidates": [{"time": start} for start, _ in sections[1:]],
            "hard_stops": [{"time": start, "silence_duration": length}
                           for start, length in stops],
        },
    }


def _plan(display: DisplayBuilder, analysis: dict[str, Any] | None = None,
          rule_set: RuleSet | None = None) -> tuple[Plan, RuleReport]:
    rules = rule_set or load_rule_set()
    preview = display.element()
    plan = plan_show(analysis or synthetic_analysis(), display_from_preview(preview), rules)
    return plan, check_choreography(preview, plan.choreography, rules)


def _ids(display: DisplayBuilder) -> dict[str, str]:
    return {p.get("Name", ""): p.get("id", "") for p in display.element().findall("PropClass")}


def _lit_time(choreography: Choreography, start: int, end: int) -> int:
    return sum(max(0, min(e.end_centisecond, end) - max(e.start_centisecond, start))
               for e in choreography.effects)


@pytest.mark.parametrize("make", ALL_DISPLAYS, ids=lambda f: f.__name__)
def test_every_fictional_display_gets_a_plan_that_passes_the_rules(
    make: Callable[[], DisplayBuilder],
) -> None:
    display = make()
    plan, report = _plan(display)
    assert report.ok, report.format_text()
    sequenceable = [p for p in display_from_preview(display.element()).props.values()
                    if p.sequenceable]
    if sequenceable:
        assert plan.choreography.effects
    else:
        # Nothing this version can sequence: an empty plan, every prop explained.
        assert not plan.choreography.effects
        assert len(plan.skipped_props) == len(display.expected)


def test_sections_follow_the_song_energy() -> None:
    plan, report = _plan(classic_yard())
    assert [(s.label, s.level) for s in plan.sections] == [
        ("intro", LOW), ("verse", LOW), ("chorus", HIGH), ("outro", MID),
    ]
    assert [s.start_centisecond for s in plan.sections] == [0, 1600, 3200, 4800]
    # Louder sections light more of the display than quiet ones.
    timeline = plan.choreography
    quiet = _lit_time(timeline, 1600, 3200)
    loud = _lit_time(timeline, 3200, 4800)
    assert loud > 1.5 * quiet
    statuses = {r.rule_id: r.status for r in report.results}
    assert statuses["movements_complete"] == "passed"
    assert statuses["chases_follow_layout"] == "passed"
    assert any("guesses from loudness" in note for note in plan.notes)


def test_section_labels_reflect_their_place_and_energy() -> None:
    analysis = synthetic_analysis(sections=((0.0, 0.1), (12.0, 0.9), (30.0, 0.2),
                                            (45.0, 0.95)))
    plan, _ = _plan(classic_yard(), analysis)
    assert [s.label for s in plan.sections] == ["intro", "chorus", "verse", "finale"]


def test_arches_chase_in_their_preview_order_and_mirror_between_sections() -> None:
    display = classic_yard()
    ids = _ids(display)
    arches = tuple(ids[f"Arch {i}"] for i in range(1, 5))
    plan, _ = _plan(display)
    chases = [m for m in plan.choreography.movements if m.kind == "chase"
              and set(m.prop_ids) == set(arches)]
    assert chases
    directions = {m.direction for m in chases}
    assert directions == {"left_to_right", "right_to_left"}
    for movement in chases:
        expected = arches if movement.direction == "left_to_right" else arches[::-1]
        assert movement.prop_ids == expected
    fills = [m for m in plan.choreography.movements if m.kind == "fill"]
    assert fills and all(set(m.prop_ids) == set(arches) for m in fills)


def test_nothing_moves_through_a_hard_stop() -> None:
    analysis = synthetic_analysis(stops=((40.0, 2.0),))
    plan, report = _plan(classic_yard(), analysis)
    assert report.ok, report.format_text()
    assert plan.choreography.hard_stops_centiseconds == (4000,)
    assert _lit_time(plan.choreography, 4000, 4200) == 0
    assert next(r for r in report.results
                if r.rule_id == "motion_stops_at_hard_stops").status == "passed"


def test_mouths_stay_still_until_vocals_exist() -> None:
    display = line_drawn_yard()
    ids = _ids(display)
    plan, report = _plan(display)
    lit = {e.prop_id for e in plan.choreography.effects}
    assert ids["Mouth Open"] not in lit and ids["Mouth Closed"] not in lit
    assert ids["Face Outline"] in lit
    skipped = {s.name: s.reason for s in plan.skipped_props}
    assert "vocal analysis" in skipped["Mouth Open"]
    assert "driven by its master prop" in skipped["Face Eyes"]
    assert report.ok


def test_requirements_shape_the_plan(tmp_path: Path) -> None:
    display = classic_yard()
    ids = _ids(display)
    profile = tmp_path / "mine.yaml"
    profile.write_text("""schema_version: rules-1.0
requirements:
  - {id: no-minis, type: never_use, props: {role: mini_tree}}
  - {id: soft-tree, type: max_intensity, props: {role: mega_tree}, max: 40}
  - {id: arches-rtl, type: move_direction, props: {group: Arches}, direction: right_to_left}
  - {id: santa-on, type: keep_on, props: {names: [Santa]}}
  - {id: santa-green, type: colors_only, props: {names: [Santa]}, colors: [Green]}
""", encoding="utf-8")
    rule_set = load_rule_set((profile,))
    plan, report = _plan(display, rule_set=rule_set)
    assert report.ok, report.format_text()
    effects = plan.choreography.effects
    minis = {ids[f"Mini Tree {i}"] for i in range(1, 5)}
    assert not [e for e in effects if e.prop_id in minis]
    assert max(e.start_intensity for e in effects if e.prop_id == ids["Mega Tree"]) == 40
    chases = [m for m in plan.choreography.movements if m.kind == "chase"]
    assert chases and {m.direction for m in chases} == {"right_to_left"}
    santa = [e for e in effects if e.prop_id == ids["Santa"]]
    assert [(e.channel_index, e.start_centisecond, e.end_centisecond) for e in santa] == [
        (2, 0, plan.choreography.duration_centiseconds)]
    skipped = {s.name: s.reason for s in plan.skipped_props}
    assert "never used" in skipped["Mini Tree 1"]


def test_quiet_sections_and_examples_are_honored() -> None:
    display = roofline_house()
    ids = _ids(display)
    rule_set = load_rule_set((EXAMPLES / "rules-sample-b.yaml",))
    plan, report = _plan(display, rule_set=rule_set)
    assert report.ok, report.format_text()
    verses = [s for s in plan.sections if s.label == "verse"]
    assert verses
    outlines = {ids[n] for n in ("Upper Roof", "Lower Gutter", "C9 Strand")}
    for verse in verses:
        assert not [e for e in plan.choreography.effects if e.prop_id in outlines
                    and e.start_centisecond < verse.end_centisecond
                    and verse.start_centisecond < e.end_centisecond]
    assert not [e for e in plan.choreography.effects
                if e.prop_id in {ids[f"Window {i}"] for i in range(1, 4)}]


def test_planning_is_deterministic() -> None:
    first, _ = _plan(classic_yard())
    second, _ = _plan(classic_yard())
    assert choreography_json(first.choreography) == choreography_json(second.choreography)


def test_a_song_without_beats_still_gets_a_plan() -> None:
    plan, report = _plan(classic_yard(), synthetic_analysis(beats=False, sections=((0, 0.5),)))
    assert report.ok
    assert any("steady 120 BPM grid" in note for note in plan.notes)
    assert any("split every 8 bars" in note for note in plan.notes)


def _preview(tmp_path: Path, display: DisplayBuilder) -> Path:
    path = tmp_path / "yard.lorprev"
    ET.ElementTree(display.element()).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_generate_writes_the_sequence_and_everything_behind_it(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    analysis = tmp_path / "song.json"
    analysis.write_text(json.dumps(synthetic_analysis()), encoding="utf-8")
    output = tmp_path / "out" / "show.loredit"
    show = generate_show(preview, output, load_rule_set(), analysis_path=analysis)
    assert show.report.ok
    document = read_loredit(output)
    assert document.root.attrib["musicFilename"] == "Fictional Song.wav"
    assert document.total_centiseconds == 6000
    effects = document.root.findall("./SequenceProps/SeqProp/channel/effect")
    assert len(effects) == len(show.plan.choreography.effects)
    plan = json.loads(show.plan_path.read_text(encoding="utf-8"))
    assert plan["rules"]["errors"] == 0
    assert plan["sections"][0]["label"] == "intro"
    assert json.loads(show.timeline_path.read_text(encoding="utf-8"))["schema_version"] == \
        "choreography-1.0"
    with pytest.raises(SequenceWriteError, match="already exists"):
        generate_show(preview, output, load_rule_set(), analysis_path=analysis)


def test_cli_generate_from_audio(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    preview = _preview(tmp_path, classic_yard())
    audio = tmp_path / "beat.wav"
    _rhythmic_track(audio, duration=20.0)
    assert main(["generate", "--preview", str(preview), "--audio", str(audio),
                 "--output", str(tmp_path / "show.loredit"), "--no-ask"]) == 0
    out = capsys.readouterr().out
    assert "Sections:" in out and "Sequence:" in out and "Analysis:" in out
    for name in ("show.loredit", "show.timeline.json", "show.plan.json", "show.rules.json",
                 "show.analysis.json", "show.analysis.svg"):
        assert (tmp_path / name).exists(), name
    assert read_loredit(tmp_path / "show.loredit").root.attrib["musicFilename"] == "beat.wav"
