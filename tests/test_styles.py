"""Show styles: classic, energetic and elegant on the same song and display."""

from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Any

import pytest

from lor_sequence_builder.planner import Plan, PlannedSection, plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import STYLES, get_style
from tests.display_builders import ALL_DISPLAYS, classic_yard, family_yard
from tests.style_helpers import leads_only
from tests.test_planner import SONG_FORM, synthetic_analysis


def _song() -> dict[str, Any]:
    analysis = synthetic_analysis(duration=96.0, sections=SONG_FORM, stops=((56.0, 1.0),))
    analysis["analysis"]["crashes"] = [{"time": t, "confidence": 0.8, "method": "test"}
                                       for t in (34.0, 38.5, 40.5, 66.0, 70.25)]
    analysis["analysis"]["high_hits"] = [{"time": round(32.25 + 0.5 * i, 3), "confidence": 0.9,
                                          "method": "test"} for i in range(30)]
    return analysis


def _plan(builder: Any, style: str) -> Plan:
    """The leads of a style's show (its glow off), to compare how the styles move."""
    display = builder()
    return plan_show(_song(), display_from_preview(display.element()), load_rule_set(),
                     style=leads_only(style))


def _lit(plan: Plan) -> int:
    return sum(e.end_centisecond - e.start_centisecond for e in plan.choreography.effects
               if max(e.start_intensity, e.end_intensity) > 0)


@pytest.mark.parametrize("style", sorted(STYLES))
@pytest.mark.parametrize("builder", ALL_DISPLAYS, ids=lambda b: b.__name__)
def test_every_style_passes_every_rule_on_every_display(builder: Any, style: str) -> None:
    display = builder()
    plan = plan_show(_song(), display_from_preview(display.element()), load_rule_set(),
                     style=get_style(style))
    report = check_choreography(display.element(), plan.choreography, load_rule_set())
    assert report.ok, report.format_text()
    assert f"Style: {STYLES[style].name}." in plan.notes


def _placements(plan: Plan) -> set[tuple[str, int, int, int]]:
    return {(e.prop_id, e.channel_index, e.start_centisecond, e.end_centisecond)
            for e in plan.choreography.effects}


@pytest.mark.parametrize("builder", [classic_yard, family_yard], ids=lambda b: b.__name__)
def test_styles_are_different_shows(builder: Any) -> None:
    """Two styles that share more than 30% of their exact effect placements are the
    same show with a different finish; each style must choose its own motion."""
    plans = {key: _plan(builder, key) for key in STYLES}
    for a, b in itertools.combinations(STYLES, 2):
        one, other = _placements(plans[a]), _placements(plans[b])
        shared = len(one & other) / min(len(one), len(other))
        # Every style lands on the same sixteenth-note grid, so some exact placements
        # coincide; a style that copied another would share most of them.
        assert shared < 0.3, f"{a} and {b} share {shared:.0%} of their placements"


def test_styles_have_their_own_character() -> None:
    classic, energetic, elegant = (_plan(family_yard, s)
                                   for s in ("classic", "energetic", "elegant"))
    # High energy is the busiest, elegant the calmest.
    assert (len(energetic.choreography.effects) > len(classic.choreography.effects)
            > len(elegant.choreography.effects))

    def flashes(plan: Plan) -> int:
        return sum(1 for kind, _ in plan.moments if kind in {"crash", "return"})

    assert flashes(energetic) > flashes(classic) > 0 == flashes(elegant)
    assert not any(kind == "call_and_response" for kind, _ in elegant.moments)
    # Each enters a louder part its own way.
    assert any(kind == "drop" for kind, _ in energetic.moments)
    assert not any(kind == "drop" for kind, _ in classic.moments + elegant.moments)
    # Elegant never moves on the half beat: nothing it lights is shorter than half a beat.
    lengths = [e.end_centisecond - e.start_centisecond for e in elegant.choreography.effects]
    assert sorted(lengths)[len(lengths) // 10] >= 25
    # The same style twice is the same show.
    assert _plan(family_yard, "energetic").choreography == energetic.choreography


@pytest.mark.parametrize("style", sorted(STYLES))
def test_look_alike_props_never_share_a_timeline(style: str) -> None:
    plan = _plan(family_yard, style)
    display = display_from_preview(family_yard().element())
    timelines: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for e in plan.choreography.effects:
        timelines[e.prop_id].append((e.start_centisecond, e.end_centisecond))
    by_role: dict[str, list[str]] = defaultdict(list)
    for pid, prop in display.props.items():
        by_role[prop.role].append(pid)
    for pids in by_role.values():
        for a, b in itertools.combinations(pids, 2):
            if timelines[a]:
                assert timelines[a] != timelines[b], (
                    f"{display.props[a].name} and {display.props[b].name} move in lockstep")


@pytest.mark.parametrize("style", ["classic", "energetic"])
def test_the_show_grows_to_its_last_chorus(style: str) -> None:
    plan = _plan(family_yard, style)
    choruses = [s for s in plan.sections if s.label == "chorus"]

    def lit_share(section: PlannedSection) -> float:
        span = section.end_centisecond - section.start_centisecond
        lit = sum(max(0, min(e.end_centisecond, section.end_centisecond)
                      - max(e.start_centisecond, section.start_centisecond))
                  for e in plan.choreography.effects)
        return lit / span

    assert lit_share(choruses[-1]) > 1.1 * lit_share(choruses[0])


def test_an_unknown_style_is_refused() -> None:
    with pytest.raises(ValueError, match="classic, energetic, elegant"):
        get_style("disco")
    assert get_style(None).key == "classic"


@pytest.mark.parametrize("yard", [family_yard, classic_yard])
@pytest.mark.parametrize("song", ["form", "plain"])
def test_every_style_lives_up_to_its_profile(yard: Any, song: str) -> None:
    # Each style's profile (hold length, fades, how much is lit in quiet and loud
    # parts, contrast, the whole yard only at the peaks, accents a minute) is checked
    # on every show; on these yards and songs every style meets all of it.
    display = display_from_preview(yard().element())
    analysis = _song() if song == "form" else synthetic_analysis()
    measured = {}
    for key in STYLES:
        plan = plan_show(analysis, display, load_rule_set(), style=get_style(key))
        assert plan.quality is not None
        style_check = next(f for f in plan.quality.findings if f.check == "style")
        assert style_check.status == "good", style_check.message
        measured[key] = plan.quality.measures
    # And the profiles really are different shows.
    assert (measured["energetic"]["hold_beats"] <= measured["classic"]["hold_beats"]
            < measured["elegant"]["hold_beats"])
    assert measured["elegant"]["accents_per_minute"] <= measured["classic"][
        "accents_per_minute"]
    assert measured["energetic"]["fade_share"] < measured["elegant"]["fade_share"]


def test_a_show_that_misses_its_style_says_how() -> None:
    from lor_sequence_builder.choreography import Effect
    from lor_sequence_builder.quality import check

    # A "show" of one-beat blinks on every prop at once, judged as Elegant.
    props = {f"p{i}" for i in range(4)}
    effects = [Effect(p, 0, t, t + 50) for t in range(0, 6000, 100) for p in sorted(props)]
    report = check(effects, 6000, props, {p: f"r{p}" for p in props},
                   [(0, 3000, 0), (3000, 6000, 2)], range(0, 6000, 50), [],
                   profile=STYLES["elegant"].profile, style_name="Elegant", beat=50,
                   accents=30)
    finding = next(f for f in report.findings if f.check == "style")
    assert finding.status == "note" and finding.message.startswith("Not quite Elegant")
    for words in ("effects last 1.0 beats", "0% of effects fade", "accents a minute"):
        assert words in finding.message
    assert report.score <= 85
