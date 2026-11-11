"""Score an audio-analysis report against timing grids in a reference sequence.

The reference is a native S6 sequence whose free timing grids were placed by a
person (beats, bars, sections). Only the hardened LOREDIT reader touches the
file; nothing is written back. Scores use standard event-matching F-measure:
an estimate counts as a hit when it lands within the tolerance of a reference
mark that no other estimate has already claimed.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lor_sequence_builder.loredit import read_loredit

BEAT_TOLERANCE_SECONDS = 0.07
SECTION_TOLERANCE_SECONDS = 2.0
MAX_ANALYSIS_BYTES = 50 * 1024 * 1024
REVIEW_SCHEMA_VERSION = "music-review-1.0"
ANALYSIS_SCHEMA_VERSION = "2.0"


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
    """Maximum-cardinality one-to-one matching for a fixed time tolerance.

    With sorted event times and a symmetric fixed tolerance, matching the
    earliest compatible pair cannot reduce the number of later matches. This
    two-pointer algorithm therefore finds the maximum number of valid hits
    without the order-dependent failures of nearest-neighbour greedy matching.
    """
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise EvaluationError("Matching tolerance must be finite and positive")
    if any(not math.isfinite(value) for value in (*estimated, *reference)):
        raise EvaluationError("Event times must all be finite numbers")
    ordered_estimated = sorted(estimated)
    ordered_reference = sorted(reference)
    estimate_index = 0
    reference_index = 0
    hits = 0
    while estimate_index < len(ordered_estimated) and reference_index < len(ordered_reference):
        estimate = ordered_estimated[estimate_index]
        mark = ordered_reference[reference_index]
        if estimate < mark - tolerance:
            estimate_index += 1
        elif mark < estimate - tolerance:
            reference_index += 1
        else:
            hits += 1
            estimate_index += 1
            reference_index += 1
    return MatchScore(len(ordered_estimated), len(ordered_reference), hits, tolerance)


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
                centisecond = int(raw)
            except ValueError as exc:
                raise EvaluationError(
                    f"Timing grid {grid_name!r} has a non-integer centisecond {raw!r}"
                ) from exc
            if not 0 <= centisecond <= document.total_centiseconds:
                raise EvaluationError(
                    f"Timing grid {grid_name!r} has centisecond {centisecond} "
                    f"outside sequence duration 0-{document.total_centiseconds}"
                )
            marks.append(centisecond / 100.0)
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
    payload = analysis.get("analysis")
    if not isinstance(payload, dict):
        raise EvaluationError("Analysis JSON is missing its analysis object")
    events = payload.get(key)
    if not isinstance(events, list):
        raise EvaluationError(f"Analysis field {key!r} is not a list")
    duration = analysis["audio"]["duration_seconds"]
    times: list[float] = []
    for event in events:
        if not isinstance(event, dict):
            raise EvaluationError(f"Analysis field {key!r} contains a non-object event")
        raw_time = event.get("time")
        if isinstance(raw_time, bool) or not isinstance(raw_time, int | float):
            raise EvaluationError(f"Analysis field {key!r} has an event without a numeric time")
        value = float(raw_time)
        if not math.isfinite(value) or value < 0 or value > duration:
            raise EvaluationError(
                f"Analysis field {key!r} contains an invalid time outside the audio duration"
            )
        times.append(value)
    return times


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON names instead of silently retaining the last value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationError(f"Analysis JSON contains duplicate object key {key!r}")
        result[key] = value
    return result


def load_analysis(path: str | Path) -> dict[str, Any]:
    """Read an analysis JSON, or the corrected analysis inside a music review."""
    source = Path(path)
    try:
        if source.stat().st_size > MAX_ANALYSIS_BYTES:
            raise EvaluationError("Analysis JSON exceeds the 50 MiB limit")
        data = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"Cannot read analysis JSON: {source}") from exc
    if not isinstance(data, dict):
        raise EvaluationError("Analysis JSON must be an object")
    if data.get("schema_version") == REVIEW_SCHEMA_VERSION:
        # A music review saved by the workspace wraps the corrected analysis.
        data = data.get("analysis")
        if not isinstance(data, dict):
            raise EvaluationError("Music review JSON has no analysis object")
    if data.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
        raise EvaluationError(
            f"Unsupported analysis schema_version {data.get('schema_version')!r}; "
            f"expected {ANALYSIS_SCHEMA_VERSION!r}"
        )
    audio = data.get("audio")
    if not isinstance(audio, dict):
        raise EvaluationError("Analysis JSON is missing its audio object")
    duration = audio.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not math.isfinite(float(duration))
        or float(duration) <= 0
    ):
        raise EvaluationError("Analysis JSON has an invalid audio duration_seconds value")
    payload = data.get("analysis")
    if not isinstance(payload, dict):
        raise EvaluationError("Analysis JSON is missing its analysis object")
    for key in ("beats", "downbeats", "section_candidates"):
        events = payload.get(key)
        if not isinstance(events, list):
            raise EvaluationError(f"Analysis JSON field {key!r} must be a list")
        for event in events:
            if not isinstance(event, dict):
                raise EvaluationError(
                    f"Analysis JSON field {key!r} contains a non-object event"
                )
            raw_time = event.get("time")
            if isinstance(raw_time, bool) or not isinstance(raw_time, int | float):
                raise EvaluationError(
                    f"Analysis field {key!r} has an event without a numeric time"
                )
            if (not math.isfinite(float(raw_time))
                    or not 0 <= float(raw_time) <= float(duration)):
                raise EvaluationError(
                    f"Analysis field {key!r} contains an invalid time outside the audio duration"
                )

    energy = payload.get("energy")
    if energy is not None:
        if not isinstance(energy, list):
            raise EvaluationError("Analysis JSON field 'energy' must be a list")
        for event in energy:
            if not isinstance(event, dict):
                raise EvaluationError("Analysis JSON energy contains a non-object event")
            for field in ("time", "rms"):
                value = event.get(field)
                if (isinstance(value, bool) or not isinstance(value, int | float)
                        or not math.isfinite(float(value))):
                    raise EvaluationError(
                        f"Analysis JSON energy event has an invalid or missing {field!r}"
                    )
            if not 0 <= float(event["time"]) <= float(duration) or float(event["rms"]) < 0:
                raise EvaluationError("Analysis JSON energy event has an out-of-range value")
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
