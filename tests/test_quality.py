"""The quality check run on every show: it catches what passing the rules does not."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import lor_sequence_builder.planner as planner_module
from lor_sequence_builder.choreography import Effect, Movement
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.quality import QualityReport, check
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import STYLES, get_style
from tests.display_builders import classic_yard, family_yard
from tests.test_audio_analysis import _rhythmic_track
from tests.test_planner import _preview, synthetic_analysis

BEATS = list(range(0, 6000, 50))
PROPS = {f"p{i}" for i in range(4)}
ROLES = {p: "arch" for p in PROPS}
SECTIONS = [(0, 3000, 0), (3000, 6000, 2)]
PHRASES = [(a, a + 800) for a in range(0, 6000, 800)]


def on(pid: str, start: int, end: int, channel: int = 0, intensity: int = 100,
       movement: str | None = None) -> Effect:
    return Effect(pid, channel, start, end, "on", intensity, intensity, None, movement)


def run(effects: list[Effect], **kw: Any) -> QualityReport:
    return check(effects, 6000, PROPS, ROLES, SECTIONS, BEATS, PHRASES, **kw)


def status(report: QualityReport, name: str) -> str:
    return next(f.status for f in report.findings if f.check == name)


def lively() -> list[Effect]:
    """A new prop each beat, in an order that keeps changing: quiet half sparse, loud
    half fuller."""
    effects = []
    for k, t in enumerate(BEATS):
        pid = f"p{(k + k // 5) % 4}"
        effects.append(on(pid, t, t + (40 if t < 3000 else 50)))
        if t >= 3000:
            effects.append(on(f"p{(k + k // 5 + 2) % 4}", t, t + 50, channel=1))
    return effects


def test_a_lively_show_passes_every_check() -> None:
    report = run(lively())
    assert {f.status for f in report.findings} == {"good"}, report.findings
    assert report.score == 100
    assert report.summary() == "Quality check: 100/100; nothing to fix."


def test_everything_lit_for_a_long_time_is_too_much() -> None:
    effects = [on(p, 1000, 2000) for p in PROPS] + lively()[:10]
    report = run(effects)
    assert status(report, "too_much_at_once") == "note"
    assert report.findings[0].at == (1000,)
    # The finale may light the whole yard.
    assert status(run(effects, excused=[(900, 2100)]), "too_much_at_once") == "good"


def test_darkness_while_the_song_plays_is_dead_air() -> None:
    effects = [e for e in lively() if not 2000 <= e.start_centisecond < 2600]
    report = run(effects)
    assert status(report, "dead_air") == "note"
    assert report.measures["dead_air_seconds"] >= 5
    # Silence in the song itself is not dead air.
    assert status(run(effects, quiet=[(1990, 2610)]), "dead_air") == "good"


def test_look_alikes_moving_together_are_lockstep() -> None:
    effects = [e for k, t in enumerate(BEATS) for e in (
        on("p0", t, t + 30), on("p1", t, t + 30), on(f"p{2 + k % 2}", t, t + 30))]
    report = run(effects)
    assert status(report, "lockstep") == "note"
    assert report.measures["lockstep_pairs"] == 1
    # Different kinds of prop may move together.
    roles = {**ROLES, "p1": "mega_tree"}
    mixed = check(effects, 6000, PROPS, roles, SECTIONS, BEATS, PHRASES)
    assert status(mixed, "lockstep") == "good"


def test_loud_parts_that_light_no_more_than_quiet_ones_are_flat() -> None:
    flat = [on(f"p{k % 4}", t, t + 50) for k, t in enumerate(BEATS)]
    assert status(run(flat), "flat_energy") == "note"
    assert status(run(lively()), "flat_energy") == "good"


def test_the_same_look_phrase_after_phrase_is_repetitive() -> None:
    same = [on(f"p{(t // 50) % 4}", t, t + 40) for t in BEATS]
    report = run(same)
    assert status(report, "repetition") == "note"
    assert report.measures["longest_same_look"] >= 3


def test_effects_off_the_beat_are_off_the_music() -> None:
    off = [on(f"p{k % 4}", t + 23, t + 45) for k, t in enumerate(BEATS)]
    report = run(off)
    assert status(report, "on_the_music") == "note"
    assert report.measures["on_music"] < 0.1
    # The steps of a chase divide the beat on purpose; the chase counts once, at its start.
    steps = [on(f"p{i}", 100 + 12 * i, 112 + 12 * i, movement="m1") for i in range(4)]
    chase = Movement("m1", "chase", tuple(sorted(PROPS)), "left_to_right", 100, 148)
    assert run(steps, movements=[chase]).measures["on_music"] == 1.0
    # A tree stepping segment by segment while it is lit is one start.
    spin = [on("p0", 200 + 10 * i, 230 + 10 * i, channel=i) for i in range(5)]
    assert run(spin).measures["on_music"] == 1.0


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_planned_show_carries_its_quality_check(style: str) -> None:
    display = family_yard()
    element = display.element()
    parsed = display_from_preview(element)
    plan = plan_show(synthetic_analysis(), parsed, load_rule_set(), style=get_style(style))
    assert plan.quality is not None
    assert plan.quality.score >= 85
    assert status(plan.quality, "dead_air") == "good"
    assert status(plan.quality, "lockstep") == "good"
    assert status(plan.quality, "flat_energy") == "good"
    assert any(n.startswith("Quality check:") for n in plan.notes)
    as_dict = plan.to_dict()["quality"]
    assert as_dict["score"] == plan.quality.score
    assert {f["check"] for f in as_dict["findings"]} >= {"dead_air", "on_the_music"}


def test_dark_stretches_get_a_calm_base(monkeypatch: pytest.MonkeyPatch) -> None:
    # A planner that leaves every phrase dark: the check lights a calm base under the
    # song, starting and ending on beats, and says so.
    monkeypatch.setattr(planner_module, "_look", lambda *args, **kwargs: None)
    display = classic_yard()
    element = display.element()
    parsed = display_from_preview(element)
    rules = load_rule_set()
    analysis = synthetic_analysis(stops=((30.0, 2.0),))
    plan = plan_show(analysis, parsed, rules, style=get_style("classic"))
    assert plan.quality is not None
    assert status(plan.quality, "dead_air") == "fixed"
    assert any(kind == "calm_base" for kind, _ in plan.moments)
    # (The calm base holds for beats at a time; a stepped glow's short holds after
    # its hits are not part of it.)
    calm = [e for e in plan.choreography.effects
            if e.start_intensity == planner_module.CALM_LEVEL
            and e.end_centisecond - e.start_centisecond >= 100]
    assert calm
    beats = {round(b["time"] * 100) for b in analysis["analysis"]["beats"]}
    assert all(e.start_centisecond in beats for e in calm)
    # The hard stop stays dark.
    assert not any(e.start_centisecond < 3200 and e.end_centisecond > 3000
                   for e in calm)
    assert check_choreography(element, plan.choreography, rules).ok


def test_the_report_shows_the_quality_check(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    audio = tmp_path / "song.wav"
    _rhythmic_track(audio, duration=20.0)
    show = generate_show(preview, tmp_path / "show.loredit", load_rule_set(),
                         audio_path=audio, separate=False)
    html = show.summary_path.read_text(encoding="utf-8")
    assert "Quality check: " in html and "Dead air" in html and "On the music" in html
