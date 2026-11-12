from __future__ import annotations

import itertools
import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.choreography import Choreography, choreography_json
from lor_sequence_builder.cli import main
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.planner import HIGH, LOW, MID, Plan, PlanningError, _music, plan_show
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
        "configuration": {"beats_per_bar": 4},
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
        ("intro", LOW), ("verse", MID), ("chorus", HIGH), ("outro", MID),
    ]
    assert [s.start_centisecond for s in plan.sections] == [0, 1600, 3200, 4800]
    # Louder sections light more of the display than quiet ones.
    timeline = plan.choreography
    quiet = _lit_time(timeline, 1600, 3200)
    loud = _lit_time(timeline, 3200, 4800)
    assert loud > 1.3 * quiet
    statuses = {r.rule_id: r.status for r in report.results}
    assert statuses["movements_complete"] == "passed"
    assert statuses["chases_follow_layout"] == "passed"
    assert any("guesses from loudness" in note for note in plan.notes)


def test_section_labels_reflect_their_place_and_energy() -> None:
    analysis = synthetic_analysis(sections=((0.0, 0.1), (10.0, 0.9), (20.0, 0.2),
                                            (50.0, 0.95)))
    plan, _ = _plan(classic_yard(), analysis)
    assert [s.label for s in plan.sections] == ["intro", "chorus", "verse", "finale"]


def _arches_only() -> DisplayBuilder:
    display = DisplayBuilder("Fictional Arch Row")
    names = [f"Arch {i}" for i in range(1, 5)]
    for i, name in enumerate(names):
        display.add(name, "arch", shape="Arch", box=(-0.8 + 0.2 * i, -0.3, 0.08, 0.07),
                    unit="80")
    display.group("Arches", names)
    return display


def test_arches_chase_in_their_preview_order_and_mirror_between_sections() -> None:
    display = _arches_only()
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
    # Without vocals the mouth never opens; the closed mouth may rest with the face.
    assert ids["Mouth Open"] not in lit
    assert ids["Mouth Closed"] in lit
    assert ids["Face Outline"] in lit
    skipped = {s.name: s.reason for s in plan.skipped_props}
    assert "no vocals for this song" in skipped["Mouth Open"]
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


def test_missing_downbeats_respect_the_analyzer_meter() -> None:
    analysis = synthetic_analysis(duration=30.0, bpm=120.0, sections=((0, 0.5),))
    analysis["configuration"]["beats_per_bar"] = 3
    analysis["analysis"]["downbeats"] = []
    music = _music(analysis)
    assert music.downbeats == music.beats[::3]
    assert "assumed a bar every 3 beats" in music.notes[0]


def test_integral_float_meter_from_external_analysis_is_normalized() -> None:
    analysis = synthetic_analysis(duration=30.0, bpm=120.0, sections=((0, 0.5),))
    analysis["configuration"]["beats_per_bar"] = 3.0
    analysis["analysis"]["downbeats"] = []
    music = _music(analysis)
    assert music.beats_per_bar == 3
    assert music.downbeats == music.beats[::3]


def test_a_song_without_a_detected_beat_grid_is_rejected() -> None:
    with pytest.raises(PlanningError, match="will not invent a tempo"):
        _plan(classic_yard(), synthetic_analysis(beats=False, sections=((0, 0.5),)))


def test_a_single_downbeat_preserves_its_phase_when_reconstructing_bars() -> None:
    analysis = synthetic_analysis(duration=12.0, bpm=120.0)
    analysis["configuration"]["beats_per_bar"] = 3
    analysis["analysis"]["downbeats"] = [analysis["analysis"]["beats"][1]]
    music = _music(analysis)
    assert music.downbeats == [beat for i, beat in enumerate(music.beats) if i % 3 == 1]
    assert music.bar_phase == 1


def test_three_four_bar_fallback_stays_aligned_after_a_window_split() -> None:
    from lor_sequence_builder.planner import _bars, _Window

    window = _Window(
        0, 50, 500, tuple(range(50, 500, 50)), (), False,
        offset=0, beats_per_bar=3, bar_phase=0, bar_offset=1,
    )
    assert _bars(window) == [(150, 300), (300, 450), (450, 500)]


@pytest.mark.parametrize("downbeats", [(), (0,)])
def test_three_four_phrases_reconstruct_missing_downbeats_after_a_stop(
    downbeats: tuple[int, ...],
) -> None:
    from lor_sequence_builder.planner import _phrases, _Window

    window = _Window(
        0, 0, 1800, tuple(range(0, 1800, 50)), downbeats, False,
        offset=0, beats_per_bar=3, bar_phase=0, bar_offset=0,
    )
    phrases = _phrases(window)
    assert [(phrase.start, phrase.end) for phrase in phrases] == [
        (0, 600), (600, 1200), (1200, 1800),
    ]


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
    for name in ("show.loredit", "show.timeline.json", "show.plan.json", "show.plan.svg",
                 "show.rules.json",
                 "show.analysis.json", "show.analysis.svg"):
        assert (tmp_path / name).exists(), name
    assert read_loredit(tmp_path / "show.loredit").root.attrib["musicFilename"] == "beat.wav"


def test_each_kind_of_prop_keeps_its_part_through_the_song() -> None:
    display = _arches_only()
    analysis = synthetic_analysis(duration=64.0,
                                  sections=((0.0, 0.1), (8.0, 0.95), (40.0, 0.3)))
    plan, report = _plan(display, analysis)
    assert report.ok
    # Arches always chase on the beat, quiet or loud: never a different pattern.
    kinds = {m.kind for m in plan.choreography.movements}
    assert kinds == {"chase"}
    beats = {round(t["time"] * 100) for t in analysis["analysis"]["beats"]}
    assert all(m.start_centisecond in beats for m in plan.choreography.movements)
    # Loud parts are fuller: two arches lit at once instead of one.
    loud = [e for e in plan.choreography.effects if 1000 <= e.start_centisecond < 3800]
    quiet = [e for e in plan.choreography.effects if 4100 <= e.start_centisecond < 6200]
    def mean_length(effects: list[Any]) -> float:
        return float(sum(e.end_centisecond - e.start_centisecond for e in effects)) / len(effects)

    assert mean_length(loud) > 1.5 * mean_length(quiet) / 2


def test_the_intro_starts_focused_and_the_song_ends_with_a_fade() -> None:
    display = roofline_house()
    analysis = synthetic_analysis(duration=60.0, sections=((0.0, 0.1), (24.0, 0.9)))
    plan, report = _plan(display, analysis)
    assert report.ok, report.format_text()
    props = display_from_preview(display.element()).props
    first_phrase = {props[e.prop_id].role for e in plan.choreography.effects
                    if e.start_centisecond < 800}
    assert len(first_phrase - {"star", "outline"}) <= 2
    ending = [e for e in plan.choreography.effects if e.end_centisecond == 6000]
    assert ending and all(e.kind == "fade" and e.end_intensity == 0 for e in ending)


def test_back_to_back_holds_become_one_effect() -> None:
    display = roofline_house()
    ids = _ids(display)
    plan, _ = _plan(display, synthetic_analysis(duration=48.0, sections=((0.0, 0.5),)))
    holds = sorted((e for e in plan.choreography.effects
                    if e.prop_id == ids["Upper Roof"] and e.channel_index == 0),
                   key=lambda e: e.start_centisecond)
    assert holds
    # Several phrases hold the roof at the same level; S6 gets one long effect, not many.
    assert any(e.end_centisecond - e.start_centisecond > 800 for e in holds)
    for a, b in itertools.pairwise(holds):
        assert not (a.end_centisecond == b.start_centisecond and a.kind == b.kind == "on"
                    and a.start_intensity == b.start_intensity)


def test_plan_picture_draws_every_used_prop_and_section() -> None:
    from lor_sequence_builder.plan_preview import plan_svg

    display = classic_yard()
    plan, _ = _plan(display, synthetic_analysis(stops=((40.0, 2.0),)))
    svg = plan_svg(plan, display_from_preview(display.element()), "Fictional <yard>")
    ET.fromstring(svg)  # well-formed
    assert "Fictional &lt;yard&gt;" in svg
    for name in plan.used_props:
        assert f">{name}</text>" in svg
    for section in plan.sections:
        assert f">{section.label} <tspan" in svg
    assert 'stroke="#ff5d5d"' in svg


def test_a_big_display_and_a_full_song_plan_quickly() -> None:
    import time

    display = DisplayBuilder("Big Fictional Yard")
    names = [f"Arch {i}" for i in range(12)]
    for i, name in enumerate(names):
        display.add(name, "arch", shape="Arch", box=(-0.9 + 0.1 * i, -0.6, 0.06, 0.05),
                    unit="30")
    display.group("Arches", names)
    for i in range(16):
        display.add(f"Mini Tree {i}", "mini_tree", shape="Tree 180",
                    traditional="Multicolor_string_1_ch", colors=("Red", "Green"),
                    box=(-0.9 + 0.11 * i, -0.4, 0.04, 0.08), unit="31")
    display.add("Mega Tree", "mega_tree", shape="Tree 180", channels=32,
                traditional="Multicolor_string_1_ch", colors=("Red", "Green"),
                box=(0.5, 0.1, 0.3, 0.6), unit="32", start="Left")
    levels = (0.1, 0.3, 0.6, 0.9, 0.4, 0.95, 0.2, 0.5, 0.9, 0.6, 0.95, 0.3)
    analysis = synthetic_analysis(
        duration=240.0, bpm=140.0,
        sections=tuple((20.0 * i, level) for i, level in enumerate(levels)),
        stops=((150.0, 1.5),),
    )
    started = time.perf_counter()
    plan, report = _plan(display, analysis)
    elapsed = time.perf_counter() - started
    assert report.ok, report.format_text()
    assert len(plan.choreography.effects) > 5000
    assert elapsed < 30


def test_phrases_count_from_the_first_bar_and_absorb_short_leftovers() -> None:
    from lor_sequence_builder.planner import _phrases, _Window

    beats = tuple(range(50, 1700, 50))
    window = _Window(0, 0, 1700, beats, beats[::4], False)
    # Bars every 2 s starting at 0.5 s: phrases start at the 5th bar; the 0.5 s tail
    # after the last full phrase is folded in rather than left as a scrap.
    cuts = [(p.start, p.end) for p in _phrases(window)]
    assert cuts == [(0, 850), (850, 1700)]


@pytest.mark.parametrize("seed", range(25))
def test_any_song_shape_plans_without_breaking_a_rule(seed: int) -> None:
    import random

    rng = random.Random(seed)
    duration = rng.choice([8.0, 12.0, 30.0, 95.0, 240.0])
    starts = sorted({0.0, *(round(rng.uniform(0.5, duration - 0.5), 2)
                            for _ in range(rng.randint(0, 10)))})
    stops = tuple(sorted({(round(rng.uniform(1, duration - 1), 2), round(rng.uniform(0.3, 4), 2))
                          for _ in range(rng.randint(0, 4))}))
    analysis = synthetic_analysis(
        duration=duration, bpm=rng.choice([50.0, 96.0, 120.0, 180.0, 210.0]),
        sections=tuple((s, rng.random()) for s in starts), stops=stops,
        beats=True,
    )
    if rng.random() < 0.3:  # waltz time
        analysis["configuration"]["beats_per_bar"] = 3
        analysis["analysis"]["downbeats"] = analysis["analysis"]["beats"][::3]
    if not analysis["analysis"]["beats"]:
        with pytest.raises(PlanningError, match="will not invent a tempo"):
            _plan(ALL_DISPLAYS[0](), analysis)
        return
    for make in ALL_DISPLAYS:
        _, report = _plan(make(), analysis)
        assert report.ok, f"{make.__name__}: {report.format_text()}"


def test_two_rows_of_the_same_size_stay_separate_and_face_groups_are_not_rows() -> None:
    display = DisplayBuilder("Two Fictional Rows")
    for i in range(3):
        display.add(f"Low Arch {i + 1}", "arch", shape="Arch", channels=2,
                    box=(-0.9 + 0.06 * i, -0.2, 0.05, 0.04), unit="50")
        display.add(f"High Arch {i + 1}", "arch", shape="Arch", channels=4,
                    box=(0.4 + 0.16 * i, -0.37, 0.12, 0.1), unit="51")
    ring = [(0.1 + 0.05 * math.cos(a), 0.05 * math.sin(a))
            for a in (k * math.pi / 6 for k in range(13))]
    names = ("Face Outline", "Face Mouth Open", "Face Mouth Closed")
    for name in names:
        display.add(name, "singing_face", shape="Lines-Connected", points=ring, unit="52")
    display.group("Face", names)
    props = display_from_preview(display.element()).props
    low = {props[p].row_id for p in props if props[p].name.startswith("Low")}
    high = {props[p].row_id for p in props if props[p].name.startswith("High")}
    assert len(low) == len(high) == 1 and low != high
    plan, report = _plan(display)
    assert report.ok, report.format_text()
    for movement in plan.choreography.movements:
        rows = {props[p].row_id for p in movement.prop_ids}
        assert len(rows) == 1
        assert all(props[p].role == "arch" for p in movement.prop_ids)


def test_multi_segment_arches_wipe_across_their_segments() -> None:
    display = DisplayBuilder("Segmented Fictional Arches")
    for i in range(4):
        display.add(f"Segment Arch {i + 1}", "arch", shape="Arch", channels=4,
                    box=(-0.6 + 0.3 * i, -0.3, 0.2, 0.15), unit="70")
    plan, report = _plan(display)
    assert report.ok, report.format_text()
    chase = next(m for m in plan.choreography.movements if m.kind == "chase")
    first = chase.prop_ids[0]
    starts = sorted((e.start_centisecond, e.channel_index) for e in plan.choreography.effects
                    if e.movement_id == chase.movement_id and e.prop_id == first)
    assert len({s for s, _ in starts}) == 4  # each segment starts a little later
    expected = [0, 1, 2, 3] if chase.direction == "left_to_right" else [3, 2, 1, 0]
    assert [c for _, c in starts] == expected


def _lit_groups(plan: Plan, display: DisplayBuilder, start: int, end: int) -> set[str]:
    props = display_from_preview(display.element()).props
    return {props[e.prop_id].role for e in plan.choreography.effects
            if e.start_centisecond < end and start < e.end_centisecond
            and props[e.prop_id].role not in {"star", "outline"}}


def test_quiet_parts_have_few_leads_that_hand_off_and_answer_every_beat() -> None:
    display = classic_yard()
    analysis = synthetic_analysis(duration=64.0, sections=((0.0, 0.1), (40.0, 0.9)))
    plan, report = _plan(display, analysis)
    assert report.ok, report.format_text()
    # The quiet first section: two groups lead at a time (8 s phrases at 120 BPM).
    leads = [_lit_groups(plan, display, a + 50, a + 750) for a in range(0, 3200, 800)]
    assert all(1 <= len(lead) <= 2 for lead in leads)
    assert len({frozenset(lead) for lead in leads}) >= 3  # it passes across the yard
    # Something answers every beat, even in the quiet part.
    starts = {e.start_centisecond for e in plan.choreography.effects}
    beats = [round(t["time"] * 100) for t in analysis["analysis"]["beats"]
             if t["time"] < 32]
    assert all(any(abs(s - b) <= 1 for s in starts) for b in beats)


def test_the_finale_brings_everything_in() -> None:
    display = classic_yard()
    analysis = synthetic_analysis(duration=60.0,
                                  sections=((0.0, 0.2), (20.0, 0.5), (40.0, 0.95)))
    plan, _ = _plan(display, analysis)
    assert plan.sections[-1].label == "finale"
    assert _lit_groups(plan, display, 4100, 5500) >= {"arch", "mini_tree", "mega_tree"}


def _falling_flakes() -> DisplayBuilder:
    """Two columns of three snowflakes, plus a row of arches and a mega tree."""
    display = DisplayBuilder("Fictional Falling Snow")
    for c, x in enumerate((-0.6, 0.5)):
        for r in range(3):
            display.add(f"Flake {c + 1}{r + 1}", "snowflake", shape="Snowflake", channels=1,
                        colors=("White",), box=(x, 0.4 - 0.12 * r, 0.06, 0.06), unit="30")
    names = [f"Arch {i}" for i in range(1, 5)]
    for i, name in enumerate(names):
        display.add(name, "arch", shape="Arch", box=(-0.8 + 0.4 * i, -0.3, 0.12, 0.1),
                    unit="80")
    return display


def test_high_pitched_hits_make_snowflakes_fall_down_their_columns() -> None:
    display = _falling_flakes()
    ids = _ids(display)
    analysis = synthetic_analysis(duration=32.0, sections=((0.0, 0.5),))
    hits = [round(0.25 + 0.5 * i, 3) for i in range(60)]  # a tambourine on the offbeats
    analysis["analysis"]["high_hits"] = [{"time": t, "confidence": 0.9, "method": "test"}
                                         for t in hits]
    plan, report = _plan(display, analysis)
    assert report.ok, report.format_text()
    falls = [m for m in plan.choreography.movements if m.kind == "fall"]
    columns = {tuple(ids[f"Flake {c}{r}"] for r in (1, 2, 3)) for c in (1, 2)}
    assert len(falls) >= 40
    assert {m.prop_ids for m in falls} == columns  # top to bottom, a whole column each
    hit_times = {round(t * 100) for t in hits}
    assert all(m.start_centisecond in hit_times for m in falls)
    # The columns take turns instead of the same one falling every time.
    assert all(a.prop_ids != b.prop_ids for a, b in itertools.pairwise(falls[:10]))
    # Each snowflake holds, then fades out: no bare on-off pops.
    flake_ids = {pid for column in columns for pid in column}
    flakes = [e for e in plan.choreography.effects if e.prop_id in flake_ids]
    assert {e.kind for e in flakes} == {"on", "fade"}
    assert all(e.end_intensity == 0 for e in flakes if e.kind == "fade")


def test_arches_are_one_row_even_when_another_prop_is_drawn_over_one() -> None:
    display = _falling_flakes()
    display.add("Toy Train", "decor", shape="Train", box=(0.0, -0.3, 0.1, 0.06), unit="30")
    props = display_from_preview(display.element()).props
    arches = [p for p in props.values() if p.role == "arch"]
    assert len({p.row_id for p in arches}) == 1 and None not in {p.row_id for p in arches}


# ---------------------------------------------------------------- Planner v2

SONG_FORM = ((0.0, 0.1), (16.0, 0.5), (32.0, 0.9), (48.0, 0.5), (64.0, 0.9), (80.0, 0.1))


def _roles_lit(plan: Plan, display: DisplayBuilder, start: int, end: int) -> set[str]:
    props = display_from_preview(display.element()).props
    return {props[e.prop_id].role for e in plan.choreography.effects
            if e.start_centisecond < end and start < e.end_centisecond
            and props[e.prop_id].role not in {"star", "outline", "mega_tree"}}


def _shape(plan: Plan, start: int, end: int) -> set[tuple[Any, ...]]:
    """Effects in a span, timed from its start, for comparing two parts."""
    return {(e.prop_id, e.channel_index, e.start_centisecond - start, e.kind,
             e.start_intensity, e.end_intensity)
            for e in plan.choreography.effects
            if start + 100 <= e.start_centisecond < end}


def test_a_part_that_comes_back_repeats_its_look_and_the_last_chorus_lifts() -> None:
    display = classic_yard()
    plan, report = _plan(display, synthetic_analysis(duration=96.0, sections=SONG_FORM))
    assert report.ok, report.format_text()
    assert [s.label for s in plan.sections] == ["intro", "verse", "chorus", "verse", "chorus",
                                                "outro"]
    first, second = _shape(plan, 1600, 3200), _shape(plan, 4800, 6400)
    assert len(first & second) >= 0.9 * len(first)  # the second verse repeats the first
    assert ("repeat", 4800) in plan.moments and ("repeat", 6400) in plan.moments

    # The last chorus brings in one more lead group than the first (on a display with
    # more groups than a loud part normally uses).
    yard = line_drawn_yard()
    plan, report = _plan(yard, synthetic_analysis(duration=96.0, sections=SONG_FORM))
    assert report.ok, report.format_text()

    def lit(start: int, end: int) -> int:
        return len({e.prop_id for e in plan.choreography.effects
                    if start <= e.start_centisecond < end})

    assert lit(6450, 7150) > lit(3250, 3950)


def test_mid_parts_trade_bars_in_call_and_response() -> None:
    display = classic_yard()
    plan, report = _plan(display, synthetic_analysis(duration=96.0, sections=SONG_FORM))
    assert report.ok, report.format_text()
    assert ("call_and_response", 2400) in plan.moments
    bars = [_roles_lit(plan, display, a + 20, a + 180) for a in range(2400, 3200, 200)]
    assert bars[0] != bars[1] and bars[0] == bars[2] and bars[1] == bars[3]


def test_the_phrase_before_a_louder_part_builds_up() -> None:
    display = classic_yard()
    plan, _ = _plan(display, synthetic_analysis(duration=96.0, sections=SONG_FORM))
    assert ("build", 2400) in plan.moments

    def brightness(start: int, end: int) -> float:
        values = [max(e.start_intensity, e.end_intensity) for e in plan.choreography.effects
                  if start <= e.start_centisecond < end]
        return sum(values) / len(values)

    assert brightness(2400, 2600) < 0.8 * brightness(3000, 3200)


def test_crashes_and_returns_from_a_stop_flash_the_display() -> None:
    display = classic_yard()
    analysis = synthetic_analysis(duration=96.0, sections=SONG_FORM, stops=((56.0, 1.0),))
    analysis["analysis"]["crashes"] = [{"time": t, "confidence": 0.8, "method": "test"}
                                       for t in (40.5, 41.0, 70.25, 5.0)]
    plan, report = _plan(display, analysis)
    assert report.ok, report.format_text()
    kinds = [m for m in plan.moments if m[0] in {"crash", "return"}]
    # 41.0 is too close to 40.5, and 5.0 is in the quiet intro.
    assert kinds == [("crash", 4050), ("return", 5700), ("crash", 7025)]
    flashing = {e.prop_id for e in plan.choreography.effects
                if e.start_centisecond == 4050 and e.kind == "fade" and e.end_intensity == 0}
    assert len(flashing) >= 8
    assert "crash(es) flash the display" in " ".join(plan.notes)
    assert plan.to_dict()["moments"][0]["kind"]


def test_two_songs_on_one_display_get_different_shows() -> None:
    display = classic_yard()
    one, _ = _plan(display, synthetic_analysis(duration=96.0, sections=SONG_FORM))
    other, _ = _plan(display, synthetic_analysis(
        duration=96.0, bpm=96.0,
        sections=((0.0, 0.3), (12.0, 0.9), (40.0, 0.2), (60.0, 0.6), (76.0, 0.95))))
    a = {(e.prop_id, e.start_centisecond) for e in one.choreography.effects}
    b = {(e.prop_id, e.start_centisecond) for e in other.choreography.effects}
    assert len(a & b) / len(a | b) < 0.3
    # The same song twice is the same show.
    again, _ = _plan(display, synthetic_analysis(duration=96.0, sections=SONG_FORM))
    assert again.choreography == one.choreography
