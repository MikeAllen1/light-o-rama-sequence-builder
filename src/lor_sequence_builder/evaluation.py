"""Score an audio-analysis report against timing grids in a reference sequence.

The reference is a native S6 sequence whose free timing grids were placed by a
person (beats, bars, sections). Only the hardened LOREDIT reader touches the
file; nothing is written back. Scores use standard event-matching F-measure:
an estimate counts as a hit when it lands within the tolerance of a reference
mark that no other estimate has already claimed.
"""
from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lor_sequence_builder.loredit import read_loredit

BEAT_TOLERANCE_SECONDS = 0.07
SECTION_TOLERANCE_SECONDS = 2.0
MAX_ANALYSIS_BYTES = 50 * 1024 * 1024


class EvaluationError(ValueError):
    """Raised when an analysis or reference grid cannot be evaluated."""


@dataclass(frozen=True, slots=True)
class MatchScore:
    """Event-matching result for one estimate list against one reference grid."""

    estimated: int
    reference: int
    hits: int
    tolerance_seconds: float

    @property
    def precision(self) -> float:
        return self.hits / self.estimated if self.estimated else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.reference if self.reference else 0.0

    @property
    def f_measure(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


def match_events(
    estimated: list[float], reference: list[float], tolerance: float
) -> MatchScore:
    """Greedy one-to-one matching of estimates to the nearest unused reference mark."""
    if tolerance <= 0:
        raise EvaluationError("Matching tolerance must be positive")
    ordered = sorted(reference)
    used: set[int] = set()
    hits = 0
    for value in sorted(estimated):
        index = bisect.bisect_left(ordered, value)
        best: int | None = None
        for candidate in range(max(0, index - 2), min(len(ordered), index + 2)):
            if candidate in used or abs(ordered[candidate] - value) > tolerance:
                continue
            if best is None or abs(ordered[candidate] - value) < abs(ordered[best] - value):
                best = candidate
        if best is not None:
            used.add(best)
            hits += 1
    return MatchScore(len(estimated), len(ordered), hits, tolerance)


def read_timing_grid(sequence_path: str | Path, grid_name: str) -> list[float]:
    """Return the marks (seconds) of a named free timing grid in a sequence."""
    document = read_loredit(sequence_path)
    matches = [
        grid for grid in document.root.findall("./TimingGrids/TimingGridFree")
        if grid.attrib.get("name") == grid_name
    ]
    if len(matches) > 1:
        raise EvaluationError(
            f"{len(matches)} free timing grids are named {grid_name!r}; rename one in the "
            "sequence so the reference is unambiguous"
        )
    if matches:
        marks: list[float] = []
        for timing in matches[0].findall("timing"):
            raw = timing.attrib.get("centisecond", "")
            try:
                marks.append(int(raw) / 100.0)
            except ValueError as exc:
                raise EvaluationError(
                    f"Timing grid {grid_name!r} has a non-integer centisecond {raw!r}"
                ) from exc
        return sorted(set(marks))
    available = sorted(
        grid.attrib.get("name", "")
        for grid in document.root.findall("./TimingGrids/TimingGridFree")
    )
    raise EvaluationError(
        f"Timing grid {grid_name!r} not found; free grids in this sequence: "
        + (", ".join(repr(name) for name in available) or "none")
    )


def _event_times(analysis: dict[str, Any], key: str) -> list[float]:
    events = analysis.get("analysis", {}).get(key, [])
    if not isinstance(events, list):
        raise EvaluationError(f"Analysis field {key!r} is not a list")
    times: list[float] = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("time"), int | float):
            raise EvaluationError(f"Analysis field {key!r} has an event without a numeric time")
        times.append(float(event["time"]))
    return times


def load_analysis(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_ANALYSIS_BYTES:
            raise EvaluationError("Analysis JSON exceeds the 50 MiB limit")
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"Cannot read analysis JSON: {source}") from exc
    if not isinstance(data, dict):
        raise EvaluationError("Analysis JSON must be an object")
    return data


def evaluate(
    analysis_path: str | Path,
    sequence_path: str | Path,
    beats_grid: str | None = None,
    bars_grid: str | None = None,
    sections_grid: str | None = None,
) -> dict[str, MatchScore]:
    """Score beats, downbeats, and section candidates against the named grids."""
    if beats_grid is None and bars_grid is None and sections_grid is None:
        raise EvaluationError("Name at least one timing grid to evaluate against")
    analysis = load_analysis(analysis_path)
    results: dict[str, MatchScore] = {}
    if beats_grid is not None:
        results["beats"] = match_events(
            _event_times(analysis, "beats"),
            read_timing_grid(sequence_path, beats_grid),
            BEAT_TOLERANCE_SECONDS,
        )
    if bars_grid is not None:
        results["downbeats"] = match_events(
            _event_times(analysis, "downbeats"),
            read_timing_grid(sequence_path, bars_grid),
            BEAT_TOLERANCE_SECONDS,
        )
    if sections_grid is not None:
        results["sections"] = match_events(
            _event_times(analysis, "section_candidates"),
            read_timing_grid(sequence_path, sections_grid),
            SECTION_TOLERANCE_SECONDS,
        )
    return results
