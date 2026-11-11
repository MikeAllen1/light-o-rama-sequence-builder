from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.evaluation import (
    EvaluationError,
    evaluate,
    match_events,
    read_timing_grid,
)

FIXTURE_GZIP = Path(__file__).parent / "fixtures" / "basic_show.loredit.gz"
SANITIZED_GRID = 'TimingGridFree name="Fixture Timing Grid"'


def _sequence_with_named_grids(tmp_path: Path, *names: str) -> Path:
    """Copy the fixture, renaming its first free grids (all share a sanitized name)."""
    with gzip.open(FIXTURE_GZIP, "rb") as source:
        text = source.read().decode("utf-8")
    for name in names:
        assert SANITIZED_GRID in text
        text = text.replace(SANITIZED_GRID, f'TimingGridFree name="{name}"', 1)
    path = tmp_path / "reference.loredit"
    path.write_text(text, encoding="utf-8")
    return path


def _analysis(tmp_path: Path, beats: list[float], downbeats: list[float] | None = None,
              sections: list[float] | None = None) -> Path:
    def events(times: list[float]) -> list[dict[str, object]]:
        return [{"time": time, "confidence": 1.0, "method": "test"} for time in times]

    path = tmp_path / "analysis.json"
    path.write_text(json.dumps({"analysis": {
        "beats": events(beats),
        "downbeats": events(downbeats or []),
        "section_candidates": events(sections or []),
    }}), encoding="utf-8")
    return path


def test_match_events_counts_one_to_one_hits_within_tolerance() -> None:
    result = match_events([1.0, 1.02, 2.05, 9.0], [1.0, 2.0, 3.0], 0.07)
    # 1.0 and 1.02 compete for the same mark; only one may claim it.
    assert result.hits == 2
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(2 / 3)
    assert result.f_measure == pytest.approx(2 * 0.5 * (2 / 3) / (0.5 + 2 / 3))


def test_match_events_handles_empty_inputs_and_bad_tolerance() -> None:
    assert match_events([], [1.0], 0.07).f_measure == 0.0
    assert match_events([1.0], [], 0.07).f_measure == 0.0
    with pytest.raises(EvaluationError, match="positive"):
        match_events([1.0], [1.0], 0.0)


def test_read_timing_grid_returns_sorted_seconds(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    marks = read_timing_grid(sequence, "Beats")
    assert marks[:3] == [0.0, 0.48, 0.96]
    assert marks == sorted(marks)


def test_read_timing_grid_rejects_missing_and_ambiguous_names(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    with pytest.raises(EvaluationError, match="not found.*'Beats'"):
        read_timing_grid(sequence, "Bars")
    with pytest.raises(EvaluationError, match="free timing grids are named"):
        read_timing_grid(sequence, "Fixture Timing Grid")


def test_evaluate_scores_each_requested_grid(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats", "Bars")
    reference = read_timing_grid(sequence, "Beats")
    analysis = _analysis(tmp_path, beats=[mark + 0.03 for mark in reference])

    results = evaluate(analysis, sequence, beats_grid="Beats")

    assert set(results) == {"beats"}
    assert results["beats"].f_measure == pytest.approx(1.0)


def test_evaluate_requires_a_grid_and_valid_analysis(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    analysis = _analysis(tmp_path, beats=[0.0])
    with pytest.raises(EvaluationError, match="at least one timing grid"):
        evaluate(analysis, sequence)
    broken = tmp_path / "broken.json"
    broken.write_text('{"analysis": {"beats": [{"time": "soon"}]}}', encoding="utf-8")
    with pytest.raises(EvaluationError, match="numeric time"):
        evaluate(broken, sequence, beats_grid="Beats")


def test_evaluate_never_modifies_the_reference_sequence(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    before = sequence.read_bytes()
    evaluate(_analysis(tmp_path, beats=[0.0, 0.48]), sequence, beats_grid="Beats")
    assert sequence.read_bytes() == before


def test_cli_evaluate_analysis_prints_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    reference = read_timing_grid(sequence, "Beats")
    analysis = _analysis(tmp_path, beats=reference)

    code = main([
        "evaluate-analysis", "--analysis", str(analysis), "--sequence", str(sequence),
        "--beats-grid", "Beats",
    ])

    assert code == 0
    assert "beats:" in capsys.readouterr().out


def test_cli_evaluate_analysis_reports_missing_grid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    code = main([
        "evaluate-analysis", "--analysis", str(_analysis(tmp_path, beats=[0.0])),
        "--sequence", str(sequence), "--bars-grid", "Bars",
    ])
    assert code == 2
    assert "not found" in capsys.readouterr().err
