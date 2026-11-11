from __future__ import annotations

import dataclasses
import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

import lor_sequence_builder.choreography as choreography_module

from lor_sequence_builder.choreography import (
    Choreography,
    ChoreographyError,
    Effect,
    Movement,
    Section,
    choreography_json,
    load_choreography,
    parse_choreography,
)
from lor_sequence_builder.rules import (
    RULE_SPECS,
    RuleProfileError,
    RuleReport,
    RuleSet,
    check_choreography,
    display_from_preview,
    load_rule_set,
)
from tests.display_builders import (
    DisplayBuilder,
    classic_yard,
    line_drawn_yard,
    roofline_house,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SONG = 3000  # 30 seconds


def _ids(display: DisplayBuilder) -> dict[str, str]:
    return {p.get("Name", ""): p.get("id", "") for p in display.element().findall("PropClass")}


def _check(
    display: DisplayBuilder, choreography: Choreography, rule_set: RuleSet | None = None
) -> RuleReport:
    return check_choreography(display.element(), choreography, rule_set or load_rule_set())


def _result(report: RuleReport, rule_id: str) -> tuple[str, list[str]]:
    result = next(r for r in report.results if r.rule_id == rule_id)
    return result.status, [f.describe() for f in result.findings]


def _on(prop_id: str, start: int, end: int, channel: int = 0, **extra: object) -> Effect:
    return Effect(prop_id, channel, start, end, **extra)  # type: ignore[arg-type]


def _profile(tmp_path: Path, text: str, name: str = "mine.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- profiles


def test_built_in_profile_configures_every_rule() -> None:
    rule_set = load_rule_set()
    assert rule_set.sources == ("default.yaml",)
    assert rule_set.rules.keys() == RULE_SPECS.keys()
    assert rule_set.rules["not_everything_at_once"].severity == "warning"
    assert all(rule_set.rules[r].severity == "error" for r in RULE_SPECS
               if r != "not_everything_at_once")


def test_example_profiles_are_valid() -> None:
    for name in ("rules-sample-a.yaml", "rules-sample-b.yaml"):
        rule_set = load_rule_set((EXAMPLES / name,))
        assert rule_set.sources == ("default.yaml", name)
        assert rule_set.requirements


def test_profiles_layer_in_order_and_later_wins(tmp_path: Path) -> None:
    first = _profile(tmp_path, """
schema_version: rules-1.0
rules:
  not_everything_at_once: {max_seconds: 12, severity: error}
  falls_go_down: {severity: warning}
requirements:
  - {id: star, type: keep_on, props: {names: [Tree Topper]}}
""", "first.yaml")
    second = _profile(tmp_path, """
schema_version: rules-1.0
rules:
  not_everything_at_once: {max_seconds: 20}
requirements:
  - {type: never_use, props: {role: mega_tree}}
""", "second.yaml")
    rule_set = load_rule_set((first, second))
    busy = rule_set.rules["not_everything_at_once"]
    # Only the keys a layer gives change; the rest come from the layer below.
    assert busy.params["max_seconds"] == 20.0
    assert busy.severity == "error"
    assert busy.params["max_share"] == 0.9
    assert rule_set.rules["falls_go_down"].severity == "warning"
    assert [r.requirement_id for r in rule_set.requirements] == ["star", "requirement-1"]
    assert [r.source for r in rule_set.requirements] == ["first.yaml", "second.yaml"]
    assert rule_set.to_dict()["sources"] == ["default.yaml", "first.yaml", "second.yaml"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("schema_version: rules-9\n", "schema_version must be 'rules-1.0'"),
        ("schema_version: rules-1.0\nrulez: {}\n", "unknown top-level key"),
        ("schema_version: rules-1.0\nrules: {no_such_rule: {severity: error}}\n",
         "rules.no_such_rule is not a known rule"),
        ("schema_version: rules-1.0\nrules: {falls_go_down: {speed: 3}}\n",
         "falls_go_down.speed is not a setting"),
        ("schema_version: rules-1.0\nrules: {falls_go_down: {severity: maybe}}\n",
         "severity must be one of error, warning, off"),
        ("schema_version: rules-1.0\nrules: {not_everything_at_once: {max_share: 2}}\n",
         "max_share must be at most 1"),
        ("schema_version: rules-1.0\nrules: {not_everything_at_once: {max_seconds: soon}}\n",
         "max_seconds must be a number"),
        ("schema_version: rules-1.0\nrules: {no_overlapping_effects: {severity: off}}\n",
         "cannot be relaxed"),
        ("schema_version: rules-1.0\nrules: {known_props_and_channels: {severity: warning}}\n",
         "cannot be relaxed"),
        (("schema_version: rules-1.0\nrules: {falls_go_down: {severity: off}}\n"
         "rules: {}\n"), "key 'rules' appears more than once"),
        ("schema_version: rules-1.0\nrequirements: [{type: dance, props: {all: true}}]\n",
         "type must be one of"),
        ("schema_version: rules-1.0\nrequirements: [{type: keep_on}]\n", "missing props"),
        ("schema_version: rules-1.0\nrequirements: [{type: colors_only, props: {all: true}}]\n",
         "missing colors"),
        ("schema_version: rules-1.0\nrequirements: [{type: keep_on, props: {role: wizard}}]\n",
         "role 'wizard' is not a known role"),
        (("schema_version: rules-1.0\nrequirements: [{type: keep_on, props: "
         "{role: arch, names: [x]}}]\n"), "must choose props one way"),
        (("schema_version: rules-1.0\nrequirements: [{type: max_intensity, props: {all: true}, "
         "max: 150}]\n"), "max must be at most 100"),
        (("schema_version: rules-1.0\nrequirements: [{type: never_use, props: {all: true}, "
         "colour: red}]\n"), "unknown field(s) colour"),
        (("schema_version: rules-1.0\nrequirements: [{type: move_direction, props: {all: true}, "
         "direction: sideways}]\n"), "direction must be one of"),
        (("schema_version: rules-1.0\nrequirements:\n  - {id: a, type: never_use, props: "
         "{all: true}}\n  - {id: a, type: never_use, props: {all: true}}\n"), "already used"),
        ("schema_version: rules-1.0\nrules: [1, 2]\n", "rules must be a mapping"),
        ("- just\n- a list\n", "must be a mapping"),
        ("schema_version: [unclosed\n", "not valid YAML"),
    ],
)
def test_invalid_profiles_fail_with_a_readable_message(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(RuleProfileError, match=None) as caught:
        load_rule_set((_profile(tmp_path, text),))
    assert message in str(caught.value)
    assert "mine.yaml" in str(caught.value)


def test_locked_rules_may_be_restated_as_errors(tmp_path: Path) -> None:
    path = _profile(tmp_path, "schema_version: rules-1.0\n"
                              "rules: {no_overlapping_effects: {severity: error}}\n")
    assert load_rule_set((path,)).rules["no_overlapping_effects"].severity == "error"


def test_profile_size_and_missing_file_are_reported(tmp_path: Path) -> None:
    big = _profile(tmp_path, "# " + "x" * (1024 * 1024) + "\n", "big.yaml")
    with pytest.raises(RuleProfileError, match="1 MiB"):
        load_rule_set((big,))
    with pytest.raises(RuleProfileError, match="Cannot read"):
        load_rule_set((tmp_path / "missing.yaml",))


# ---------------------------------------------------------------- timeline contract


def test_timeline_round_trips_and_rejects_bad_structure(tmp_path: Path) -> None:
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect("a", 0, 0, 50, "fade", 0, 100, "Red", "m1"),),
        movements=(Movement("m1", "chase", ("a",), "left_to_right", 0, 100),),
        sections=(Section("verse", 0, 1000),),
        hard_stops_centiseconds=(900,),
        vocal_regions=((10, 20),),
    )
    path = tmp_path / "t.json"
    path.write_text(choreography_json(timeline), encoding="utf-8")
    assert load_choreography(path) == timeline

    good = json.loads(choreography_json(timeline))
    mutations: list[tuple[Callable[[dict[str, Any]], object], str]] = [
        (lambda d: d.update(schema_version="x"), "Unsupported Timeline schema_version"),
        (lambda d: d["effects"][0].update(kind="strobe"), "effects[0].kind 'strobe'"),
        (lambda d: d["effects"][0].update(start_centisecond=1.5), "must be an integer"),
        (lambda d: d["effects"][0].update(volume=3), "unknown field(s) volume"),
        (lambda d: d["effects"][0].pop("prop_id"), "missing prop_id"),
        (lambda d: d["movements"][0].update(direction="up"), "direction 'up'"),
        (lambda d: d["movements"][0].update(prop_ids=[]), "at least one prop"),
        (lambda d: d.update(vocal_regions=[[1]]), "must be [start, end]"),
    ]
    for mutate, message in mutations:
        data = json.loads(json.dumps(good))
        mutate(data)
        with pytest.raises(ChoreographyError, match=None) as caught:
            parse_choreography(data)
        assert message in str(caught.value)
    path.write_text('{"schema_version": NaN}', encoding="utf-8")
    with pytest.raises(ChoreographyError, match="non-finite"):
        load_choreography(path)


# ---------------------------------------------------------------- built-in rules


def test_a_clean_timeline_passes_and_inapplicable_rules_say_why() -> None:
    display = classic_yard()
    ids = _ids(display)
    arches = [ids[f"Arch {i}"] for i in range(1, 5)]
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=tuple(
            _on(pid, 100 + 25 * i, 200 + 25 * i, movement_id="chase")
            for i, pid in enumerate(arches)
        ) + (_on(ids["Mega Tree"], 500, 900, 3, kind="fade", start_intensity=0),),
        movements=(Movement("chase", "chase", tuple(arches), "left_to_right", 100, 300),),
    )
    report = _check(display, timeline)
    assert report.ok, report.format_text()
    statuses = {r.rule_id: r.status for r in report.results}
    assert statuses["movements_complete"] == "passed"
    assert statuses["chases_follow_layout"] == "passed"
    for rule_id, why in (
        ("falls_go_down", "no falling effects"),
        ("face_outline_with_mouth", "both a separate outline and mouth"),
        ("mouths_only_during_vocals", "no singing-face mouth"),
        ("motion_stops_at_hard_stops", "no hard stops"),
        ("single_color_only_where_possible", "no effect asks for a specific color"),
    ):
        result = next(r for r in report.results if r.rule_id == rule_id)
        assert result.status == "not_applicable"
        assert why in result.reason
    assert "N/A  falls_go_down" in report.format_text()


def test_malformed_effects_are_errors_with_prop_channel_and_time() -> None:
    display = classic_yard()
    ids = _ids(display)
    arch = ids["Arch 1"]
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(
            _on(arch, 2900, 3100),
            _on(arch, 500, 400),
            _on(arch, 10, 20, start_intensity=120, end_intensity=120),
            _on(arch, 30, 40, start_intensity=0, end_intensity=50),
            _on(arch, 50, 60, kind="fade"),
        ),
    )
    report = _check(display, timeline)
    status, findings = _result(report, "effects_well_formed")
    assert status == "failed" and not report.ok
    assert "Arch 1 channel 1 at 0:29.00: Effect ends at 0:31.00, after the song ends" in findings[0]
    assert any("ends before it starts" in f for f in findings)
    assert any("intensity 120 is outside 0-100" in f for f in findings)
    assert any("use a fade to change it" in f for f in findings)
    assert any("A fade must change intensity" in f for f in findings)
    assert "The sequence will not be written" in report.format_text()


def test_effects_must_use_real_sequenceable_channels() -> None:
    display = classic_yard()
    ids = _ids(display)
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(
            _on("no-such-prop", 0, 10),
            _on(ids["Arch 1"], 0, 10, channel=1),
            _on(ids["Tree Topper"], 0, 10),
        ),
    )
    _, findings = _result(_check(display, timeline), "known_props_and_channels")
    assert "not in the preview" in findings[0]
    assert "Arch 1 channel 2 at 0:00.00: Channel 2 does not exist" in findings[1]
    assert "driven by its master prop Mega Tree" in findings[2]


def test_overlapping_effects_on_one_channel_are_errors() -> None:
    display = classic_yard()
    mega = _ids(display)["Mega Tree"]
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(_on(mega, 0, 500, 2), _on(mega, 400, 600, 2), _on(mega, 400, 600, 3),
                 _on(mega, 500, 700, 2)),
    )
    status, findings = _result(_check(display, timeline), "no_overlapping_effects")
    assert status == "failed"
    assert findings == [
        ("Mega Tree channel 3 at 0:04.00: Overlaps another effect on this channel that runs "
        "until 0:05.00"),
        ("Mega Tree channel 3 at 0:05.00: Overlaps another effect on this channel that runs "
        "until 0:06.00"),
    ]


def test_movements_must_reach_every_prop_in_order() -> None:
    display = classic_yard()
    ids = _ids(display)
    arches = tuple(ids[f"Arch {i}"] for i in range(1, 5))
    stops_partway = Choreography(
        duration_centiseconds=SONG,
        effects=(
            _on(arches[0], 100, 150, movement_id="c"),
            _on(arches[2], 120, 160, movement_id="c"),
            _on(arches[1], 140, 180, movement_id="c"),
            _on(arches[1], 900, 950, movement_id="ghost"),
        ),
        movements=(Movement("c", "chase", arches, "left_to_right", 100, 400),),
    )
    _, findings = _result(_check(display, stops_partway), "movements_complete")
    assert findings == [
        "Arch 2 channel 1 at 0:09.00: Effect belongs to movement 'ghost', which is not defined",
        "Arch 4 at 0:01.00: The chase 'c' never reaches this prop, so it stops partway",
        "Arch 3 at 0:01.20: The chase 'c' reaches this prop before the one listed ahead of it",
    ]


def test_chases_follow_the_layout_of_the_preview() -> None:
    display = classic_yard()
    ids = _ids(display)
    arches = [ids[f"Arch {i}"] for i in range(1, 5)]
    trees = [ids[f"Mini Tree {i}"] for i in range(1, 5)]

    def chase(props: list[str], direction: str) -> Choreography:
        return Choreography(
            duration_centiseconds=SONG,
            effects=tuple(_on(p, 100 + 10 * i, 105 + 10 * i, movement_id="c")
                          for i, p in enumerate(props)),
            movements=(Movement("c", "chase", tuple(props), direction, 100, 200),),
        )

    assert _result(_check(display, chase(arches, "row_order")), "chases_follow_layout")[0] == \
        "passed"
    assert _result(_check(display, chase(arches[::-1], "reverse_row_order")),
                   "chases_follow_layout")[0] == "passed"
    assert _result(_check(display, chase(arches[::-1], "right_to_left")),
                   "chases_follow_layout")[0] == "passed"
    _, findings = _result(_check(display, chase(arches[::-1], "left_to_right")),
                          "chases_follow_layout")
    assert "says left to right, but its props are not in that order" in findings[0]
    shuffled = [arches[0], arches[2], arches[1], arches[3]]
    _, findings = _result(_check(display, chase(shuffled, "row_order")), "chases_follow_layout")
    assert "skips around" in findings[0]
    _, findings = _result(_check(display, chase(arches[:2] + trees[:2], "row_order")),
                          "chases_follow_layout")
    assert "not one row" in findings[0]


def test_falls_run_top_to_bottom() -> None:
    display = line_drawn_yard()
    ids = _ids(display)
    flakes = tuple(ids[f"Snowflake {i}"] for i in range(1, 7))  # highest first

    def fall(props: tuple[str, ...], direction: str = "top_to_bottom") -> Choreography:
        return Choreography(
            duration_centiseconds=SONG,
            effects=tuple(_on(p, 100 + 10 * i, 105 + 10 * i, movement_id="f")
                          for i, p in enumerate(props)),
            movements=(Movement("f", "fall", props, direction, 100, 200),),
        )

    assert _result(_check(display, fall(flakes)), "falls_go_down")[0] == "passed"
    _, findings = _result(_check(display, fall(flakes[::-1])), "falls_go_down")
    assert "does not go from the highest prop to the lowest" in findings[0]
    _, findings = _result(_check(display, fall(flakes[::-1], "bottom_to_top")), "falls_go_down")
    assert "falls run top to bottom" in findings[0]

    house = roofline_house()
    icicles = _ids(house)["Front Icicles"]
    sideways = Choreography(
        duration_centiseconds=SONG,
        effects=tuple(_on(icicles, 100 + 10 * c, 110 + 10 * c, c, movement_id="f")
                      for c in range(4)),
        movements=(Movement("f", "fall", (icicles,), "top_to_bottom", 100, 200),),
    )
    _, findings = _result(_check(house, sideways), "falls_go_down")
    assert "segments run left to right, so they cannot show a fall" in findings[0]


def test_a_vertical_prop_falls_from_its_top_segment(tmp_path: Path) -> None:
    for start, ok_order in (("Top", [0, 1, 2]), ("Bottom", [2, 1, 0])):
        display = DisplayBuilder(f"Vertical {start}")
        drop = display.add("Drop", "outline", shape="Lines-Connected", channels=3,
                           points=[(0.0, 0.5), (0.0, -0.5)], start=start)
        for order, expected in ((ok_order, "passed"), (ok_order[::-1], "failed")):
            timeline = Choreography(
                duration_centiseconds=SONG,
                effects=tuple(_on(drop, 100 + 10 * i, 105 + 10 * i, ch, movement_id="f")
                              for i, ch in enumerate(order)),
                movements=(Movement("f", "fall", (drop,), "top_to_bottom", 100, 200),),
            )
            assert _result(_check(display, timeline), "falls_go_down")[0] == expected


def test_face_outline_rule_applies_only_when_the_face_has_an_outline() -> None:
    display = line_drawn_yard()
    ids = _ids(display)
    mouth, outline = ids["Mouth Open"], ids["Face Outline"]
    dark_outline = Choreography(
        duration_centiseconds=SONG,
        effects=(_on(outline, 100, 200), _on(mouth, 150, 300)),
    )
    _, findings = _result(_check(display, dark_outline), "face_outline_with_mouth")
    assert findings == [("Mouth Open channel 1 at 0:02.00: Mouth is on while the face outline "
                        "(Face Outline) is off")]
    lit_outline = dataclasses.replace(
        dark_outline, effects=(_on(outline, 100, 400), _on(mouth, 150, 300))
    )
    assert _result(_check(display, lit_outline), "face_outline_with_mouth")[0] == "passed"

    # A face drawn as one prop has no separate outline: the rule does not apply.
    yard = classic_yard()
    santa = _ids(yard)["Santa"]
    one_prop = Choreography(duration_centiseconds=SONG, effects=(_on(santa, 0, 100, 1),))
    status, _ = _result(_check(yard, one_prop), "face_outline_with_mouth")
    assert status == "not_applicable"
    # No face at all.
    house = roofline_house()
    status, _ = _result(
        _check(house, Choreography(duration_centiseconds=SONG, effects=())),
        "face_outline_with_mouth",
    )
    assert status == "not_applicable"


def test_profiles_can_name_face_parts(tmp_path: Path) -> None:
    display = line_drawn_yard()
    ids = _ids(display)
    profile = _profile(tmp_path, "schema_version: rules-1.0\nrules:\n"
                                 "  face_outline_with_mouth: {outline_names: [mouth closed]}\n")
    timeline = Choreography(duration_centiseconds=SONG,
                            effects=(_on(ids["Mouth Open"], 100, 200),))
    _, findings = _result(_check(display, timeline, load_rule_set((profile,))),
                          "face_outline_with_mouth")
    # "Mouth Closed" also says mouth, so it stays a mouth part, not an outline.
    assert findings == []


def test_mouths_move_only_during_vocals_once_vocals_are_known() -> None:
    display = line_drawn_yard()
    ids = _ids(display)
    effects = (_on(ids["Face Outline"], 0, 1000), _on(ids["Mouth Open"], 450, 600))
    unknown = Choreography(duration_centiseconds=SONG, effects=effects)
    status = next(r for r in _check(display, unknown).results
                  if r.rule_id == "mouths_only_during_vocals")
    assert (status.status, status.reason) == (
        "not_applicable", "vocals were not analyzed for this song yet")
    sung = dataclasses.replace(unknown, vocal_regions=((400, 500),))
    _, findings = _result(_check(display, sung), "mouths_only_during_vocals")
    assert findings == ["Mouth Open channel 1 at 0:05.00: Mouth moves while nobody is singing"]
    assert _result(_check(display, dataclasses.replace(unknown, vocal_regions=((400, 700),))),
                   "mouths_only_during_vocals")[0] == "passed"


def test_specific_colors_only_on_props_that_can_show_them() -> None:
    display = classic_yard()
    ids = _ids(display)
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(
            _on(ids["Mini Tree 1"], 0, 100, color="Green"),
            _on(ids["Santa"], 0, 100, 1, color="Red"),
            _on(ids["Santa"], 0, 100, 2, color="Red"),
            _on(ids["Arch 1"], 0, 100, color="red"),
        ),
    )
    _, findings = _result(_check(display, timeline), "single_color_only_where_possible")
    assert findings == [
        ("Mini Tree 1 channel 1 at 0:00.00: Asks for Green, but all colors on this strand share "
        "one circuit, so no single color can be shown alone"),
        "Santa channel 3 at 0:00.00: Asks for Red, but this channel is Green",
    ]


def test_motion_stops_at_hard_stops() -> None:
    display = classic_yard()
    ids = _ids(display)
    arches = tuple(ids[f"Arch {i}"] for i in range(1, 5))
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=tuple(_on(p, 100 + 50 * i, 150 + 50 * i, movement_id="c")
                      for i, p in enumerate(arches)),
        movements=(Movement("c", "chase", arches, "left_to_right", 100, 300),),
        hard_stops_centiseconds=(220,),
    )
    _, findings = _result(_check(display, timeline), "motion_stops_at_hard_stops")
    assert findings == ["Arch 1 at 0:02.20: The chase 'c' keeps moving through the hard stop"]
    after = dataclasses.replace(timeline, hard_stops_centiseconds=(300,))
    assert _result(_check(display, after), "motion_stops_at_hard_stops")[0] == "passed"


def test_everything_on_at_once_is_a_warning_outside_the_finale() -> None:
    display = roofline_house()
    ids = _ids(display)
    channels = [(pid, c) for name, pid in ids.items()
                for c in range({"Upper Roof": 2, "Lower Gutter": 2, "Front Icicles": 4}
                               .get(name, 1))]
    blast = tuple(_on(pid, 0, 1500, c) for pid, c in channels)
    timeline = Choreography(duration_centiseconds=SONG, effects=blast)
    report = _check(display, timeline)
    status, findings = _result(report, "not_everything_at_once")
    assert status == "failed" and report.ok  # a warning does not block the sequence
    assert findings == [("at 0:00.00: 90% or more of the display is on for 15.0 s "
                        "(limit 8.0 s); let some props rest")]
    finale = dataclasses.replace(timeline, sections=(Section("Finale", 0, 1500),))
    assert _result(_check(display, finale), "not_everything_at_once")[0] == "passed"
    # A profile can make it an error.
    rule_set = load_rule_set((EXAMPLES / "rules-sample-b.yaml",))
    assert not _check(display, timeline, rule_set).ok


def test_a_rule_turned_off_is_reported_as_off(tmp_path: Path) -> None:
    profile = _profile(tmp_path, "schema_version: rules-1.0\n"
                                 "rules: {not_everything_at_once: {severity: off}}\n")
    report = _check(roofline_house(), Choreography(duration_centiseconds=SONG, effects=()),
                    load_rule_set((profile,)))
    assert _result(report, "not_everything_at_once")[0] == "off"


# ---------------------------------------------------------------- requirements


def _requirements(tmp_path: Path, body: str) -> RuleSet:
    return load_rule_set((_profile(tmp_path, "schema_version: rules-1.0\nrequirements:\n"
                                             + body),))


def test_requirement_keep_on(tmp_path: Path) -> None:
    display = roofline_house()
    flake = _ids(display)["Big Flake"]
    rule_set = _requirements(tmp_path, "  - {id: flake, type: keep_on, props: "
                                       "{names: [big flake]}, during: [chorus]}\n")
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(_on(flake, 1000, 1500),),
        sections=(Section("chorus", 1000, 2000),),
    )
    _, findings = _result(_check(display, timeline, rule_set), "flake")
    assert findings == ["Big Flake channel 1 at 0:15.00: Should stay on but goes dark"]
    covered = dataclasses.replace(timeline, effects=(_on(flake, 900, 2100),))
    assert _result(_check(display, covered, rule_set), "flake")[0] == "passed"
    no_chorus = dataclasses.replace(timeline, sections=())
    assert _result(_check(display, no_chorus, rule_set), "flake")[0] == "not_applicable"


def test_requirement_never_use_and_quiet_during(tmp_path: Path) -> None:
    display = roofline_house()
    ids = _ids(display)
    rule_set = load_rule_set((EXAMPLES / "rules-sample-b.yaml",))
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(_on(ids["Window 2"], 0, 100), _on(ids["Upper Roof"], 450, 600, 1),
                 _on(ids["Big Flake"], 0, 3000)),
        sections=(Section("verse", 500, 1000), Section("chorus", 1000, 2000)),
    )
    report = _check(display, timeline, rule_set)
    assert _result(report, "windows-never-flash")[1] == [
        "Window 2 channel 1 at 0:00.00: Should never be used"]
    assert _result(report, "quiet-verses-roof")[1] == [
        "Upper Roof channel 2 at 0:05.00: Should be dark during this section"]
    assert _result(report, "flake-on-in-chorus")[0] == "passed"
    assert not report.ok


def test_requirement_colors_only_and_max_intensity(tmp_path: Path) -> None:
    display = classic_yard()
    ids = _ids(display)
    rule_set = load_rule_set((EXAMPLES / "rules-sample-a.yaml",))
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(_on(ids["Arch 1"], 0, 100), _on(ids["Mega Tree"], 0, 100, 5),
                 _on(ids["Mega Tree"], 200, 300, 5, start_intensity=80, end_intensity=80)),
    )
    report = _check(display, timeline, rule_set)
    assert _result(report, "arches-white")[1] == [
        "Arch 1 channel 1 at 0:00.00: Shows red; allowed: White"]
    _status, findings = _result(report, "gentle-mega-tree")
    assert findings == ["Mega Tree channel 6 at 0:00.00: Reaches 100% intensity; limit is 80%"]
    result = next(r for r in report.results if r.rule_id == "gentle-mega-tree")
    assert result.severity == "warning"
    # The star is linked to the mega tree, so "keep it on" cannot be checked on the star itself.
    star = next(r for r in report.results if r.rule_id == "star-always-on")
    assert star.severity == "warning" and "driven by Mega Tree" in star.findings[0].message


def test_requirement_colors_only_cannot_limit_a_combined_strand(tmp_path: Path) -> None:
    display = classic_yard()
    tree = _ids(display)["Mini Tree 2"]
    rule_set = _requirements(tmp_path, "  - {id: green, type: colors_only, props: "
                                       "{role: mini_tree}, colors: [Green]}\n")
    timeline = Choreography(duration_centiseconds=SONG, effects=(_on(tree, 0, 100),))
    _, findings = _result(_check(display, timeline, rule_set), "green")
    assert "share one circuit, so it cannot be limited to Green" in findings[0]


def test_requirement_move_direction(tmp_path: Path) -> None:
    display = classic_yard()
    ids = _ids(display)
    arches = tuple(ids[f"Arch {i}"] for i in range(4, 0, -1))
    rule_set = load_rule_set((EXAMPLES / "rules-sample-a.yaml",))
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=tuple(_on(p, 100 + 10 * i, 105 + 10 * i, movement_id="c")
                      for i, p in enumerate(arches)),
        movements=(Movement("c", "chase", arches, "right_to_left", 100, 200),),
    )
    report = _check(display, timeline, rule_set)
    assert _result(report, "arches-chase-left-to-right")[1] == [
        "Arch 4 at 0:01.00: The chase 'c' runs right to left; it should run left to right"]


def test_a_requirement_that_matches_nothing_is_a_warning(tmp_path: Path) -> None:
    rule_set = _requirements(tmp_path, "  - {id: typo, type: never_use, props: "
                                       "{names: [Mega Tre]}}\n")
    report = _check(classic_yard(), Choreography(duration_centiseconds=SONG, effects=()),
                    rule_set)
    result = next(r for r in report.results if r.rule_id == "typo")
    assert (result.status, result.severity) == ("failed", "warning")
    assert "matches no prop" in result.findings[0].message
    assert report.ok


def test_report_json_carries_findings_and_the_effective_profile() -> None:
    display = classic_yard()
    mega = _ids(display)["Mega Tree"]
    report = _check(display, Choreography(
        duration_centiseconds=SONG, effects=(_on(mega, 0, 50), _on(mega, 10, 60))))
    data = report.to_dict()
    json.dumps(data)
    assert data["ok"] is False
    assert data["summary"]["errors"] == 1
    finding = next(r for r in data["results"] if r["rule_id"] == "no_overlapping_effects")[
        "findings"][0]
    assert (finding["prop_name"], finding["channel_index"], finding["time"]) == (
        "Mega Tree", 0, "0:00.10")
    assert data["effective_profile"]["sources"] == ["default.yaml"]


def test_checking_never_modifies_the_timeline() -> None:
    display = classic_yard()
    timeline = Choreography(duration_centiseconds=SONG,
                            effects=(_on(_ids(display)["Arch 1"], 0, 9999),))
    before = choreography_json(timeline)
    _check(display, timeline)
    assert choreography_json(timeline) == before

 
@pytest.mark.parametrize("value", [".nan", ".inf", "-.inf"])
def test_profile_rejects_non_finite_rule_values(tmp_path: Path, value: str) -> None:
    profile = _profile(tmp_path, "schema_version: rules-1.0\nrules:\n"
                                 f"  not_everything_at_once: {{max_share: {value}}}\n")
    with pytest.raises(RuleProfileError, match="finite number"):
        load_rule_set((profile,))


@pytest.mark.parametrize("kind", ["[keep_on]", "{bad: value}"])
def test_requirement_type_must_be_text(tmp_path: Path, kind: str) -> None:
    profile = _profile(tmp_path, "schema_version: rules-1.0\nrequirements:\n"
                                 f"  - type: {kind}\n    props: {{all: true}}\n")
    with pytest.raises(RuleProfileError, match=r"requirements\[0\]\.type"):
        load_rule_set((profile,))


def test_timeline_movement_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(choreography_module, "MAX_MOVEMENTS", 1)
    data = {
        "schema_version": "choreography-1.0",
        "duration_centiseconds": SONG,
        "effects": [],
        "movements": [
            {"movement_id": f"m{i}", "kind": "chase", "prop_ids": ["a"],
             "direction": "left_to_right", "start_centisecond": 0,
             "end_centisecond": 100}
            for i in range(2)
        ],
    }
    with pytest.raises(ChoreographyError, match="more than 1 movements"):
        parse_choreography(data)


def test_duplicate_movement_ids_are_reported() -> None:
    display = classic_yard()
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(),
        movements=(
            Movement("duplicate", "chase", ("a",), "left_to_right", 0, 100),
            Movement("duplicate", "chase", ("b",), "left_to_right", 100, 200),
        ),
    )
    report = _check(display, timeline)
    _, findings = _result(report, "effects_well_formed")
    assert any("Movement id 'duplicate' is used more than once" in item
               for item in findings)


def test_direct_choreography_objects_reject_unknown_effect_and_movement_values() -> None:
    display = classic_yard()
    invalid_effect = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect(_ids(display)["Arch 1"], 0, 0, 100, kind="laser"),),
    )
    _, effect_findings = _result(_check(display, invalid_effect), "effects_well_formed")
    assert any("Effect kind 'laser' is not supported" in item for item in effect_findings)

    invalid_movement = Choreography(
        duration_centiseconds=SONG,
        effects=(),
        movements=(Movement("bad", "teleport", (_ids(display)["Arch 1"],),
                            "diagonal", 0, 100),),
    )
    _, movement_findings = _result(
        _check(display, invalid_movement), "effects_well_formed"
    )
    assert any("unsupported kind 'teleport'" in item for item in movement_findings)
    assert any("unsupported direction 'diagonal'" in item for item in movement_findings)


def test_timeline_json_rejects_duplicate_object_keys_at_any_depth(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":"choreography-1.0","duration_centiseconds":100,'
        '"effects":[{"prop_id":"a","channel_index":0,"start_centisecond":0,'
        '"end_centisecond":10,"prop_id":"b"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ChoreographyError, match="duplicate object key 'prop_id'"):
        load_choreography(path)



def test_profile_rejects_non_string_requirement_keys(tmp_path: Path) -> None:
    path = _profile(
        tmp_path,
        "schema_version: rules-1.0\n"
        "requirements:\n"
        "  - type: never_use\n"
        "    props: {all: true}\n"
        "    7: value\n",
    )

    with pytest.raises(RuleProfileError, match=r"requirements\[0\].*field names must be text"):
        load_rule_set((path,))


def test_profile_rejects_unhashable_yaml_mapping_keys(tmp_path: Path) -> None:
    path = _profile(
        tmp_path,
        "schema_version: rules-1.0\nrules:\n  ? [not, a, scalar, key]\n  : value\n",
    )
    with pytest.raises(RuleProfileError, match="mapping keys must be scalar/hashable"):
        load_rule_set((path,))




def test_direct_choreography_rejects_malformed_numeric_fields_cleanly() -> None:
    display = classic_yard()
    with pytest.raises(ChoreographyError, match="duration_centiseconds must be an integer"):
        _check(display, Choreography(duration_centiseconds=cast(int, "1200"), effects=()))

    with pytest.raises(ChoreographyError, match="duration_centiseconds must be an integer"):
        _check(display, Choreography(duration_centiseconds=cast(int, True), effects=()))

    invalid_intensity = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect(_ids(display)["Arch 1"], 0, 0, 100,
                        start_intensity=cast(int, "high")),),
    )
    with pytest.raises(ChoreographyError, match=r"effects\[0\].start_intensity must be an integer"):
        _check(display, invalid_intensity)

    invalid_timestamp = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect(_ids(display)["Arch 1"], 0,
                        cast(int, "0"), 100),),
    )
    with pytest.raises(ChoreographyError, match=r"effects\[0\].start_centisecond must be an integer"):
        _check(display, invalid_timestamp)

    invalid_channel = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect(_ids(display)["Arch 1"], cast(int, "0"), 0, 100),),
    )
    with pytest.raises(ChoreographyError, match=r"effects\[0\].channel_index must be an integer"):
        _check(display, invalid_channel)

    invalid_end = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect(_ids(display)["Arch 1"], 0, 0, cast(int, "100")),),
    )
    with pytest.raises(ChoreographyError, match=r"effects\[0\].end_centisecond must be an integer"):
        _check(display, invalid_end)

    invalid_end_intensity = Choreography(
        duration_centiseconds=SONG,
        effects=(Effect(_ids(display)["Arch 1"], 0, 0, 100,
                        end_intensity=cast(int, True)),),
    )
    with pytest.raises(ChoreographyError, match=r"effects\[0\].end_intensity must be an integer"):
        _check(display, invalid_end_intensity)



def test_direct_movement_with_no_props_fails_without_crashing() -> None:
    display = classic_yard()
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(),
        movements=(Movement("empty-fall", "fall", (), "left_to_right", 0, 100),),
    )
    report = _check(display, timeline)
    _, findings = _result(report, "effects_well_formed")
    assert not report.ok
    assert any("Movement 'empty-fall' must contain at least one prop" in item
               for item in findings)



def test_direct_movement_with_non_integer_time_fails_validation() -> None:
    display = classic_yard()
    timeline = Choreography(
        duration_centiseconds=SONG,
        effects=(),
        movements=(Movement("bad-time", "chase", (_ids(display)["Arch 1"],),
                            "left_to_right", True, 100),),
    )

    report = _check(display, timeline)
    _, findings = _result(report, "effects_well_formed")

    assert not report.ok
    assert any("start and end times must be integers" in item for item in findings)



@pytest.mark.parametrize(
    ("duration", "field"),
    [("1200", "duration_centiseconds"), (True, "duration_centiseconds")],
)
def test_direct_choreography_rejects_invalid_duration_types(
    duration: object, field: str
) -> None:
    display = classic_yard()
    timeline = Choreography(
        duration_centiseconds=cast(Any, duration),
        effects=(),
    )
    with pytest.raises(ChoreographyError, match=field):
        _check(display, timeline)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("channel_index", True),
        ("start_centisecond", "0"),
        ("end_centisecond", "100"),
        ("start_intensity", "high"),
        ("end_intensity", False),
    ],
)
def test_direct_effect_rejects_invalid_numeric_field_types(
    field: str, value: object
) -> None:
    display = classic_yard()
    effect = Effect(_ids(display)["Arch 1"], 0, 0, 100)
    effect = dataclasses.replace(effect, **{field: cast(Any, value)})
    timeline = Choreography(duration_centiseconds=SONG, effects=(effect,))
    with pytest.raises(ChoreographyError, match=field):
        _check(display, timeline)


def test_duplicate_group_names_union_members_for_name_selectors() -> None:
    builder = classic_yard()
    root = builder.element()
    duplicate = ET.SubElement(
        root, "PropGroup", {"id": "second-arches-group", "Name": "Arches"}
    )
    mini_tree_id = _ids(builder)["Mini Tree 1"]
    ET.SubElement(duplicate, "member", {"id": mini_tree_id})

    display = display_from_preview(root)

    expected = {
        _ids(builder)[f"Arch {index}"] for index in range(1, 5)
    } | {mini_tree_id}
    assert set(display.groups["Arches"]) == expected
