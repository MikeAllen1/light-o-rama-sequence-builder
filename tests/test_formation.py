"""Formations read from the preview, and snowflakes moving by theirs, on invented yards."""

from __future__ import annotations

import itertools
import random

import pytest

from lor_sequence_builder.formation import formation
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rules import (
    check_choreography,
    display_from_preview,
    load_rule_set,
)
from tests.display_builders import DisplayBuilder
from tests.test_planner import synthetic_analysis


def _flakes(name: str, spots: list[tuple[float, float]], channels: int = 1) -> DisplayBuilder:
    display = DisplayBuilder(name)
    for i, (x, y) in enumerate(spots, start=1):
        display.add(f"Flake {i}", "snowflake", shape="Snowflake", channels=channels,
                    colors=("White",), box=(x, y, 0.05, 0.05), unit=str(20 + i))
    return display


def _names(display: DisplayBuilder, lines: tuple[tuple[str, ...], ...]) -> list[list[str]]:
    props = display_from_preview(display.element()).props
    return [[props[p].name for p in line] for line in lines]


def _read(display: DisplayBuilder, prefer: str = "columns") -> tuple[str, list[list[str]]]:
    shown = display_from_preview(display.element())
    found = formation(shown, set(shown.props), prefer)
    return found.kind, _names(display, found.lines)


def test_stacked_snowflakes_are_columns_read_top_to_bottom() -> None:
    spots = [(x, y) for x in (-0.5, 0.4) for y in (0.1, 0.3, 0.2)]
    kind, lines = _read(_flakes("Columns", spots))
    assert kind == "columns"
    assert lines == [["Flake 2", "Flake 3", "Flake 1"], ["Flake 5", "Flake 6", "Flake 4"]]


def test_snowflakes_along_a_porch_are_a_row() -> None:
    kind, lines = _read(_flakes("Porch", [(x / 10, 0.2) for x in (5, -3, 1, -1, 3)]))
    assert kind == "rows"
    assert lines == [["Flake 2", "Flake 4", "Flake 3", "Flake 5", "Flake 1"]]


def test_a_grid_follows_what_the_props_do() -> None:
    spots = [(x / 5, y / 5) for x in range(3) for y in range(3)]
    assert _read(_flakes("Grid", spots), prefer="columns")[0] == "columns"
    assert _read(_flakes("Grid", spots), prefer="rows")[0] == "rows"


def test_little_groups_are_clusters_and_scattered_props_sweep_across() -> None:
    groups = [(-0.7, 0.3), (0.0, -0.2), (0.6, 0.4)]
    spots = [(gx + dx, gy + dy) for gx, gy in groups
             for dx, dy in ((0.0, 0.0), (0.06, 0.03), (0.03, -0.05))]
    kind, lines = _read(_flakes("Windows", spots))
    assert kind == "clusters" and len(lines) == 3 and all(len(line) == 3 for line in lines)
    kind, lines = _read(_flakes("Scatter", [(-0.8, 0.1), (0.5, -0.4), (-0.1, 0.6), (0.9, 0.2)]))
    assert kind == "scatter"
    assert lines == [["Flake 1", "Flake 3", "Flake 2", "Flake 4"]]


def _hits_song() -> dict[str, object]:
    analysis = synthetic_analysis(duration=32.0, sections=((0.0, 0.5),))
    hits = [round(0.25 + 0.5 * i, 3) for i in range(60)]
    analysis["analysis"]["high_hits"] = [{"time": t, "confidence": 0.9, "method": "test"}
                                         for t in hits]
    return analysis


def test_a_row_of_snowflakes_ripples_across_and_passes_the_rules() -> None:
    display = _flakes("Porch", [(x / 10, 0.2) for x in range(-6, 7, 2)])
    rules = load_rule_set()
    shown = display_from_preview(display.element())
    plan = plan_show(_hits_song(), shown, rules)
    report = check_choreography(display.element(), plan.choreography, rules)
    assert report.ok, report.format_text()
    moves = [m for m in plan.choreography.movements if m.prop_ids and len(m.prop_ids) == 7]
    assert len(moves) >= 20 and {m.kind for m in moves} == {"chase"}
    assert {m.direction for m in moves} <= {"left_to_right", "right_to_left"}


def test_a_multi_segment_snowflake_opens_out_segment_by_segment() -> None:
    display = _flakes("Big Flake", [(0.0, 0.2)], channels=3)
    rules = load_rule_set()
    shown = display_from_preview(display.element())
    plan = plan_show(_hits_song(), shown, rules)
    assert check_choreography(display.element(), plan.choreography, rules).ok
    starts: dict[int, list[int]] = {}
    for effect in plan.choreography.effects:
        if effect.kind == "on":
            starts.setdefault(effect.channel_index, []).append(effect.start_centisecond)
    assert sorted(starts) == [0, 1, 2]
    # Each burst: channel 0 first, then 1, then 2, a short step apart.
    for first, second, third in itertools.islice(zip(*(starts[c] for c in range(3)),
                                                     strict=False), 20):
        assert first < second < third and third - first <= 30


KINDS = (
    ("arch", "Arch", "Single Color", ("Red",)),
    ("mini_tree", "Tree 180", "Multicolor_string_1_ch", ("Red", "Green")),
    ("snowflake", "Snowflake", "Single Color", ("White",)),
    ("star", "Star", "Single Color", ("Yellow",)),
)


def _layout(rng: random.Random, count: int) -> list[tuple[float, float]]:
    """Positions for ``count`` props: a row, a column or two, little groups, or scattered."""
    shape = rng.choice(["row", "columns", "clusters", "scatter"])
    x0, y0 = rng.uniform(-0.8, 0.2), rng.uniform(-0.6, 0.4)
    if shape == "row":
        return [(x0 + 0.12 * i, y0 + rng.uniform(-0.005, 0.005)) for i in range(count)]
    if shape == "columns":
        return [(x0 + 0.3 * (i % 2) + rng.uniform(-0.005, 0.005), y0 - 0.1 * (i // 2))
                for i in range(count)]
    if shape == "clusters":
        return [(x0 + 0.4 * (i // 3) + 0.05 * (i % 3), y0 + 0.04 * (i % 2))
                for i in range(count)]
    return [(rng.uniform(-0.9, 0.9), rng.uniform(-0.8, 0.8)) for _ in range(count)]


def test_random_invented_yards_plan_without_breaking_a_rule() -> None:
    """Not every yard looks like the owner's: random layouts, counts and segments."""
    rules = load_rule_set()
    planned = 0
    for seed in range(12):
        rng = random.Random(seed)
        display = DisplayBuilder(f"Random Yard {seed}")
        unit = 20
        for role, shape, traditional, colors in KINDS:
            count = rng.choice([0, 1, 2, 3, 5, 6])
            for i, (x, y) in enumerate(_layout(rng, count)):
                unit += 1
                display.add(f"{role} {i + 1}", role, shape=shape,
                            channels=rng.choice([1, 1, 2, 3]) if role == "snowflake" else 1,
                            traditional=traditional, colors=colors, unit=str(unit),
                            box=(x, y, 0.05, 0.05))
        if not display.element().findall("PropClass"):
            continue
        analysis = _hits_song()
        plan = plan_show(analysis, display_from_preview(display.element()), rules)
        report = check_choreography(display.element(), plan.choreography, rules)
        assert report.ok, f"seed {seed}: {report.format_text()}"
        assert plan.choreography.effects
        planned += 1
    assert planned >= 10



def test_formation_spatial_work_scales_without_all_pairs_comparisons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import lor_sequence_builder.formation as module

    rng = random.Random(41)
    props = {}
    for index in range(2500):
        prop_id = f"p{index}"
        props[prop_id] = SimpleNamespace(
            prop_id=prop_id,
            center=(rng.uniform(-100, 100), rng.uniform(-100, 100)),
        )
    calls = 0
    original = module.math.dist

    def counted(left: tuple[float, float], right: tuple[float, float]) -> float:
        nonlocal calls
        calls += 1
        return original(left, right)

    monkeypatch.setattr(module.math, "dist", counted)
    result = module.formation(SimpleNamespace(props=props), set(props))
    assert result.kind in {"clusters", "scatter", "rows", "columns"}
    assert calls < 250_000
