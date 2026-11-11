from __future__ import annotations

import json
from pathlib import Path

import pytest

from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.cli import main
from lor_sequence_builder.evaluation import match_events
from tests.rubato_song import render
from tests.test_audio_analysis import _schema_violations
from tests.test_vocals import write_wav

SINGER_LED = (20.0, 50.0)


def _song(tmp_path: Path, seed: int, singer_led: bool) -> tuple[Path, Path, list[float]]:
    mix, voice, truth = render(seed=seed, singer_led=singer_led)
    return (write_wav(tmp_path / f"mix{seed}.wav", mix),
            write_wav(tmp_path / f"voice{seed}.wav", voice), truth)


def _beats(report: dict[str, object]) -> list[float]:
    analysis = report["analysis"]
    assert isinstance(analysis, dict)
    return [b["time"] for b in analysis["beats"]]


def _f(estimated: list[float], truth: list[float], start: float = 0, end: float = 1e9) -> float:
    return match_events([t for t in estimated if start <= t < end],
                        [t for t in truth if start <= t < end], 0.07).f_measure


@pytest.mark.parametrize("seed", [5, 6])
def test_vocals_fix_beats_where_the_band_follows_the_singer(tmp_path: Path, seed: int) -> None:
    mix, voice, truth = _song(tmp_path, seed, singer_led=True)
    plain = analyze_audio(mix, tmp_path / "plain.json", tmp_path / "plain.svg")
    guided = analyze_audio(mix, tmp_path / "guided.json", tmp_path / "guided.svg",
                           vocals_path=voice)
    before = _f(_beats(plain), truth, *SINGER_LED)
    after = _f(_beats(guided), truth, *SINGER_LED)
    assert before < 0.8
    assert after > 0.95
    assert _f(_beats(guided), truth) > _f(_beats(plain), truth)
    guidance = guided["analysis"]["beat_guidance"]
    assert guidance["stretches"] and guidance["source"] == voice.name
    # Only singer-led stretches changed: the steady opening is untouched.
    assert [t for t in _beats(guided) if t < 15] == [t for t in _beats(plain) if t < 15]
    methods = {b["method"] for b in guided["analysis"]["beats"]}
    assert "vocal_guided_dynamic_tempo_beat_tracker" in methods
    schema_path = Path(__file__).parents[1] / "docs" / "schemas" / "audio-analysis-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert _schema_violations(guided, schema, schema) == []


def test_vocals_leave_a_steady_song_alone(tmp_path: Path) -> None:
    mix, voice, truth = _song(tmp_path, 5, singer_led=False)
    plain = analyze_audio(mix, tmp_path / "plain.json", tmp_path / "plain.svg")
    guided = analyze_audio(mix, tmp_path / "guided.json", tmp_path / "guided.svg",
                           vocals_path=voice)
    assert _f(_beats(guided), truth) >= _f(_beats(plain), truth) - 0.005
    assert _f(_beats(guided), truth) > 0.98


def test_cli_analyze_audio_reports_vocal_guided_stretches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mix, voice, _ = _song(tmp_path, 7, singer_led=True)
    assert main(["analyze-audio", str(mix), "--vocals", str(voice),
                 "--output-json", str(tmp_path / "a.json"),
                 "--plot", str(tmp_path / "a.svg")]) == 0
    assert "Vocal-guided stretches: " in capsys.readouterr().out
