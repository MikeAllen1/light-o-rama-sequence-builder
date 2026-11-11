from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.evaluation import (
    EvaluationError,
    evaluate,
    load_analysis,
    match_events,
    read_timing_grid,
)
from tests.fixture_builders import write_synthetic_loredit

BEAT_MARKS_CS = (0, 48, 96, 156, 209, 264, 316)


def _sequence_with_named_grids(tmp_path: Path, *names: str) -> Path:
    """Synthetic sequence plus free timing grids; repeated names create ambiguity."""
    path = write_synthetic_loredit(tmp_path / "reference.loredit")
    tree = ET.parse(path)
    grids = tree.getroot().find("TimingGrids")
    assert grids is not None
    for name in names:
        grid = ET.SubElement(grids, "TimingGridFree", {"name": name})
        for centisecond in BEAT_MARKS_CS:
            ET.SubElement(grid, "timing", {"centisecond": str(centisecond)})
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def _analysis(tmp_path: Path, beats: list[float], downbeats: list[float] | None = None,
              sections: list[float] | None = None) -> Path:
    def events(times: list[float]) -> list[dict[str, object]]:
        return [{"time": time, "confidence": 1.0, "method": "test"} for time in times]

    path = tmp_path / "analysis.json"
    path.write_text(json.dumps({"schema_version": "2.0", "audio": {"duration_seconds": 30.0}, "analysis": {
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


def test_match_events_finds_maximum_cardinality_not_greedy_nearest() -> None:
    result = match_events([0.0, 0.09], [-0.09, 0.01], 0.10)
    assert result.hits == 2


def test_match_events_rejects_non_finite_values() -> None:
    with pytest.raises(EvaluationError, match="finite"):
        match_events([float("nan")], [1.0], 0.07)
    with pytest.raises(EvaluationError, match="finite"):
        match_events([1.0], [float("inf")], 0.07)
    with pytest.raises(EvaluationError, match="finite"):
        match_events([1.0], [1.0], float("inf"))


def test_match_events_handles_empty_inputs_and_bad_tolerance() -> None:
    assert match_events([], [1.0], 0.07).f_measure == 0.0
    assert match_events([1.0], [], 0.07).f_measure == 0.0
    with pytest.raises(EvaluationError, match="positive"):
        match_events([1.0], [1.0], 0.0)


def test_analysis_json_rejects_duplicate_object_keys_at_any_depth(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-analysis.json"
    path.write_text(
        '{"schema_version":"2.0","audio":{"duration_seconds":30},'
        '"analysis":{"beats":[{"time":1.0,"time":2.0}],'
        '"downbeats":[],"section_candidates":[]}}',
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match="duplicate object key 'time'"):
        load_analysis(path)


def test_read_timing_grid_returns_sorted_seconds(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    marks = read_timing_grid(sequence, "Beats")
    assert marks[:3] == [0.0, 0.48, 0.96]
    assert marks == sorted(marks)


def test_read_timing_grid_rejects_missing_and_ambiguous_names(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats", "Duplicate", "Duplicate")
    with pytest.raises(EvaluationError, match="not found.*'Beats'"):
        read_timing_grid(sequence, "Bars")
    with pytest.raises(EvaluationError, match="free timing grids are named"):
        read_timing_grid(sequence, "Duplicate")


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
    broken.write_text('{"schema_version":"2.0","audio":{"duration_seconds":10},"analysis":{"beats":[{"time":"soon"}],"downbeats":[],"section_candidates":[]}}', encoding="utf-8")
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


def test_load_analysis_rejects_unsupported_schema_and_non_finite_times(tmp_path: Path) -> None:
    path = tmp_path / "wrong-version.json"
    path.write_text(json.dumps({"schema_version": "1.3", "audio": {"duration_seconds": 5},
                                "analysis": {"beats": [], "downbeats": [],
                                             "section_candidates": []}}), encoding="utf-8")
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    with pytest.raises(EvaluationError, match="Unsupported analysis schema_version"):
        evaluate(path, sequence, beats_grid="Beats")

    path.write_text(json.dumps({"schema_version": "2.0", "audio": {"duration_seconds": 5},
                                "analysis": {"beats": [{"time": float("nan")}],
                                             "downbeats": [], "section_candidates": []}}),
                    encoding="utf-8")
    with pytest.raises(EvaluationError, match="invalid time"):
        evaluate(path, sequence, beats_grid="Beats")


def test_load_analysis_rejects_boolean_and_out_of_duration_timestamps(tmp_path: Path) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    path = tmp_path / "analysis.json"
    for invalid_time in (True, 31.0, -0.1):
        path.write_text(json.dumps({"schema_version": "2.0", "audio": {"duration_seconds": 30},
                                    "analysis": {"beats": [{"time": invalid_time}],
                                                 "downbeats": [], "section_candidates": []}}),
                        encoding="utf-8")
        with pytest.raises(EvaluationError):
            evaluate(path, sequence, beats_grid="Beats")

 
@pytest.mark.parametrize("centisecond", [-10, 20926])
def test_read_timing_grid_rejects_marks_outside_sequence_duration(
    tmp_path: Path, centisecond: int
) -> None:
    sequence = _sequence_with_named_grids(tmp_path, "Beats")
    tree = ET.parse(sequence)
    grid = tree.getroot().find("./TimingGrids/TimingGridFree")
    assert grid is not None
    timing = grid.find("timing")
    assert timing is not None
    timing.set("centisecond", str(centisecond))
    tree.write(sequence, encoding="utf-8", xml_declaration=True)
    with pytest.raises(EvaluationError, match="outside sequence duration"):
        read_timing_grid(sequence, "Beats")


def test_a_music_review_is_read_as_its_corrected_analysis(tmp_path: Path) -> None:
    from lor_sequence_builder.evaluation import EvaluationError, load_analysis
    from lor_sequence_builder.planner import _music, _sections

    bars = [{"time": float(t), "confidence": 1.0, "method": "review", "status": "confirmed"}
            for t in range(0, 60, 2)]
    beats = [{"time": t / 2, "confidence": 1.0, "method": "review"} for t in range(120)]
    analysis = {
        "schema_version": "2.0",
        "audio": {"duration_seconds": 60.0},
        "analysis": {
            "beats": beats, "downbeats": bars, "hard_stops": [],
            "energy": [{"time": float(t), "rms": 0.2 if t < 30 else 0.4, "method": "x"}
                       for t in range(60)],
            "section_candidates": [
                {"time": 20.1, "label": "Bridge", "status": "confirmed"},
                {"time": 40.0, "label": None},
            ],
        },
    }
    review = tmp_path / "song.review.json"
    review.write_text(json.dumps({"schema_version": "music-review-1.0", "meter": 4,
                                  "analysis": analysis, "lyrics": None}), encoding="utf-8")
    loaded = load_analysis(review)
    assert loaded == analysis
    labels = [section.label for section in _sections(_music(loaded))]
    assert labels[1] == "bridge"  # named in the review; the others are still guesses
    assert "bridge" not in (labels[0], labels[2])

    empty = tmp_path / "empty.review.json"
    empty.write_text(json.dumps({"schema_version": "music-review-1.0"}), encoding="utf-8")
    with pytest.raises(EvaluationError, match="no analysis"):
        load_analysis(empty)


def test_analysis_json_rejects_energy_events_without_timestamps(tmp_path: Path) -> None:
    path = _analysis(tmp_path, [1.0, 2.0])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["analysis"]["energy"] = [{"rms": 0.25, "method": "test"}]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(EvaluationError, match="invalid time"):
        load_analysis(path)
