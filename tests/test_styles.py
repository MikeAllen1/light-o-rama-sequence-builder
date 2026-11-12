"""Show styles: classic, energetic and elegant on the same song and display."""

from __future__ import annotations

from typing import Any

import pytest

from lor_sequence_builder.planner import Plan, plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import STYLES, get_style
from tests.display_builders import ALL_DISPLAYS, classic_yard
from tests.test_planner import SONG_FORM, synthetic_analysis


def _song() -> dict[str, Any]:
    analysis = synthetic_analysis(duration=96.0, sections=SONG_FORM, stops=((56.0, 1.0),))
    analysis["analysis"]["crashes"] = [{"time": t, "confidence": 0.8, "method": "test"}
                                       for t in (34.0, 38.5, 40.5, 66.0, 70.25)]
    analysis["analysis"]["high_hits"] = [{"time": round(32.25 + 0.5 * i, 3), "confidence": 0.9,
                                          "method": "test"} for i in range(30)]
    return analysis


def _plan(builder: Any, style: str) -> Plan:
    display = builder()
    return plan_show(_song(), display_from_preview(display.element()), load_rule_set(),
                     style=get_style(style))


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


def test_styles_have_their_own_character() -> None:
    classic, energetic, elegant = (_plan(classic_yard, s)
                                   for s in ("classic", "energetic", "elegant"))
    assert _lit(energetic) > _lit(classic) > _lit(elegant)

    def flashes(plan: Plan) -> int:
        return sum(1 for kind, _ in plan.moments if kind in {"crash", "return"})

    assert flashes(energetic) > flashes(classic) > 0 == flashes(elegant)
    assert not any(kind == "call_and_response" for kind, _ in elegant.moments)
    # Elegant fades: its chases never cut off sharply.
    chased = {pid for m in elegant.choreography.movements if m.kind == "chase"
              for pid in m.prop_ids}
    assert chased and all(e.kind != "on" for e in elegant.choreography.effects
                          if e.prop_id in chased and e.movement_id is not None)
    # The same style twice is the same show.
    assert _plan(classic_yard, "energetic").choreography == energetic.choreography


def test_an_unknown_style_is_refused() -> None:
    with pytest.raises(ValueError, match="classic, energetic, elegant"):
        get_style("disco")
    assert get_style(None).key == "classic"
