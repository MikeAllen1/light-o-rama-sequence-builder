"""Wiring the planner must respect on any display: circuits shared by two props,
props that light whole, and faces that always show exactly one mouth."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from lor_sequence_builder.choreography import Effect
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import STYLES, get_style
from tests.display_builders import DisplayBuilder, classic_yard
from tests.test_planner import synthetic_analysis


def wired_yard() -> DisplayBuilder:
    """A yard whose roofline is plugged into the mega tree's last circuit, with
    two-color mini arches (left white, right green) and a Santa with a mustache."""
    d = DisplayBuilder("Fictional Wired Yard")
    d.add("Mega Tree", "mega_tree", shape="Tree 180", channels=16,
          traditional="Multicolor_string_1_ch", colors=("Red", "White"), unit="21",
          box=(0.4, -0.05, 0.17, 0.4), parm1=16, start="Bottom Left")
    roof = d.add("Roof Line", "outline", shape="Line", channels=1, unit="22",
                 box=(-0.2, 0.4, 0.6, 0.02), colors=("White",))
    element = d.root.find(f"PropClass[@id='{roof}']")
    assert element is not None
    element.set("ChannelGrid", "Regular,21,16,16,0,White")  # the tree's channel 16
    for i in range(3):
        d.add(f"Mini Arch {i + 1}", "arch", shape="Arch", channels=2,
              traditional="Channel_per_color", colors=("White", "Green"), unit="23",
              box=(-0.8 + 0.2 * i, -0.3, 0.08, 0.07), start="Left")
    d.add("Santa Outline", "singing_face", shape="Square", channels=1, unit="24",
          box=(0.0, 0.0, 0.1, 0.1), colors=("White",))
    d.add("Santa Mustache Up", "singing_face", shape="Square", channels=1, unit="24",
          box=(0.0, -0.02, 0.04, 0.02), colors=("White",))
    d.add("Santa Mustache Down", "singing_face", shape="Square", channels=1, unit="24",
          box=(0.0, -0.03, 0.04, 0.02), colors=("White",))
    d.group("Santa", ["Santa Outline", "Santa Mustache Up", "Santa Mustache Down"])
    for i in range(4):
        d.add(f"Pillar {i + 1}", "outline", shape="Line", channels=1, unit="25",
              box=(-0.6 + 0.3 * i, 0.1, 0.02, 0.2))
    return d


def _whole(tmp_path: Path) -> Path:
    path = tmp_path / "whole.yaml"
    path.write_text("schema_version: rules-1.0\nrequirements:\n  - type: light_whole\n"
                    "    props: {names: [Mini Arch 1, Mini Arch 2, Mini Arch 3]}\n",
                    encoding="utf-8")
    return path


def _light(plan: object, pid: str, channel: int) -> list[int]:
    """The channel's brightness every twentieth of a second."""
    effects = [e for e in plan.choreography.effects  # type: ignore[attr-defined]
               if e.prop_id == pid and e.channel_index == channel]
    levels = []
    for t in range(0, plan.choreography.duration_centiseconds, 5):  # type: ignore[attr-defined]
        e = next((e for e in effects if e.start_centisecond <= t < e.end_centisecond), None)
        levels.append(0 if e is None else e.start_intensity + (
            e.end_intensity - e.start_intensity) * (t - e.start_centisecond)
            // (e.end_centisecond - e.start_centisecond))
    return levels


@pytest.mark.parametrize("style", sorted(STYLES))
def test_shared_circuits_whole_props_and_faces_on_any_style(tmp_path: Path, style: str) -> None:
    display = wired_yard()
    element = display.element()
    rules = load_rule_set((_whole(tmp_path),))
    parsed = display_from_preview(element)
    outlets = [{(parsed.props[p].name, c) for p, c in outlet}
               for outlet in parsed.shared_outlets()]
    assert outlets == [{("Mega Tree", 15), ("Roof Line", 0)}]
    plan = plan_show(synthetic_analysis(), parsed, rules, style=get_style(style))
    assert check_choreography(element, plan.choreography, rules).ok
    tree, roof = display.prop_id("Mega Tree"), display.prop_id("Roof Line")
    # The roofline is the tree's sixteenth channel: always the same light.
    assert _light(plan, roof, 0) == _light(plan, tree, 15)
    assert any("Roof Line is wired to the same circuit as Mega Tree" in n for n in plan.notes)
    # Each mini arch lights whole, never one side alone.
    for i in range(3):
        arch = display.prop_id(f"Mini Arch {i + 1}")
        assert _light(plan, arch, 0) == _light(plan, arch, 1) and any(_light(plan, arch, 0))
    # Without vocals Santa shows his resting mustache exactly when he is lit.
    outline = display.prop_id("Santa Outline")
    down, up = display.prop_id("Santa Mustache Down"), display.prop_id("Santa Mustache Up")
    assert _light(plan, outline, 0) == _light(plan, down, 0) and any(_light(plan, down, 0))
    assert not any(_light(plan, up, 0))


def test_the_rules_catch_each_wiring_mistake(tmp_path: Path) -> None:
    display = wired_yard()
    element = display.element()
    rules = load_rule_set((_whole(tmp_path),))
    plan = plan_show(synthetic_analysis(), display_from_preview(element), rules)
    effects = list(plan.choreography.effects)
    roof, arch = display.prop_id("Roof Line"), display.prop_id("Mini Arch 1")
    outline = display.prop_id("Santa Outline")
    down, up = display.prop_id("Santa Mustache Down"), display.prop_id("Santa Mustache Up")

    def broken(change: list[Effect]) -> set[str]:
        choreography = dataclasses.replace(plan.choreography, effects=tuple(change))
        report = check_choreography(element, choreography, rules)
        return {f.rule_id for f in (*report.errors, *report.warnings)}

    # The roofline sent something the tree's channel 16 did not.
    assert "shared_outlets_match" in broken(
        [e for e in effects if e.prop_id != roof] + [Effect(roof, 0, 100, 150)])
    # One side of a mini arch alone.
    assert any(r.startswith("req") or "whole" in r for r in broken(
        [e for e in effects if not (e.prop_id == arch and e.channel_index == 1)]))
    # Santa's outline with no mustache, and both mustaches at once.
    assert "face_parts_together" in broken([e for e in effects if e.prop_id != down])
    assert "face_parts_together" in broken(
        effects + [Effect(up, 0, e.start_centisecond, e.end_centisecond)
                   for e in effects if e.prop_id == down][:1])
    assert outline


def test_displays_without_shared_circuits_are_unchanged() -> None:
    assert display_from_preview(classic_yard().element()).shared_outlets() == []
