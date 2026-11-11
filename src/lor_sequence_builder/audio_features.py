"""Signal-domain feature extraction after audio normalization."""

from __future__ import annotations

import math
from typing import Any

from lor_sequence_builder.audio_common import FRAME_CENTER_SECONDS, FRAME_SECONDS

def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _detect_onsets(flux: list[float]) -> list[dict[str, Any]]:
    if len(flux) < 3:
        return []
    baseline = _median(flux)
    deviations = [abs(value - baseline) for value in flux]
    mad = _median(deviations)
    maximum = max(flux)
    threshold = max(baseline + 3.0 * mad, maximum * 0.08, 1e-8)
    peaks: list[dict[str, Any]] = []
    for index in range(1, len(flux) - 1):
        value = flux[index]
        if value >= threshold and value >= flux[index - 1] and value > flux[index + 1]:
            peaks.append({
                "time": round(index * FRAME_SECONDS + FRAME_CENTER_SECONDS, 3),
                "strength": round(value, 8),
                "confidence": round(min(1.0, value / maximum), 4),
                "method": "local_peak_in_positive_frame_energy_flux",
            })
    return peaks


def _energy_curve(rms: list[float]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    frames_per_second = round(1.0 / FRAME_SECONDS)
    for start in range(0, len(rms), frames_per_second):
        chunk = rms[start:start + frames_per_second]
        if chunk:
            result.append({
                "time": round(start * FRAME_SECONDS, 2),
                "rms": round(math.sqrt(math.fsum(value * value for value in chunk) / len(chunk)), 6),
                "method": "root_mean_square_amplitude",
            })
    return result


def _hard_stops(
    rms: list[float], minimum_silence_seconds: float = 0.75
) -> list[dict[str, Any]]:
    threshold = max(1e-5, max(rms, default=0.0) * 0.025)
    required_frames = max(1, round(minimum_silence_seconds / FRAME_SECONDS))
    stops: list[dict[str, Any]] = []
    # An entirely silent file has no transition to report. For a non-silent
    # track, however, leading silence is a valid candidate and must not be
    # skipped merely because there is no preceding loud frame.
    if max(rms, default=0.0) <= 1e-5:
        return stops
    index = 0
    while index < len(rms):
        is_silence_start = rms[index] <= threshold and (
            index == 0 or rms[index - 1] > threshold
        )
        if is_silence_start:
            end = index
            while end < len(rms) and rms[end] <= threshold:
                end += 1
            if end - index >= required_frames:
                stops.append({
                    "time": round(index * FRAME_SECONDS, 3),
                    "silence_duration": round((end - index) * FRAME_SECONDS, 3),
                    "confidence": 0.8,
                    "method": (
                        "leading_near_silence_relative_to_track_peak"
                        if index == 0
                        else "sustained_near_silence_relative_to_track_peak"
                    ),
                })
            index = end
        else:
            index += 1
    return stops


def _phrase_boundaries(
    duration: float, bpm: float | None, phase_frames: int | None, beat_lag: float | None
) -> list[dict[str, Any]]:
    if bpm is None or beat_lag is None or phase_frames is None:
        return []
    beat_seconds = beat_lag * FRAME_SECONDS
    phrase_seconds = beat_seconds * 16
    first_beat = phase_frames * FRAME_SECONDS + FRAME_CENTER_SECONDS
    result: list[dict[str, Any]] = []
    index = 0
    time = first_beat
    while time < duration:
        result.append({
            "time": round(time, 3),
            "kind": "estimated_16_beat_phrase",
            "confidence": 0.35,
            "basis": "fixed 16-beat grouping from estimated tempo; not semantic section recognition",
            "method": "estimated_global_tempo_grid",
        })
        index += 1
        time = first_beat + index * phrase_seconds
    return result


def _section_candidates(energy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Compare broad context windows, then localize the candidate to the strongest
    # adjacent one-second energy change. Never assign verse/chorus labels.
    result: list[dict[str, Any]] = []
    for index in range(8, len(energy) - 8):
        before = [point["rms"] for point in energy[index - 8:index]]
        after = [point["rms"] for point in energy[index:index + 8]]
        left = math.fsum(before) / len(before)
        right = math.fsum(after) / len(after)
        denominator = max(left, right, 1e-6)
        change = abs(right - left) / denominator
        if change < 0.55:
            continue
        local_start = max(1, index - 7)
        local_end = min(len(energy) - 1, index + 8)
        transition_index = max(
            range(local_start, local_end),
            key=lambda item: abs(
                energy[item]["rms"] - energy[item - 1]["rms"]
            ) / max(energy[item]["rms"], energy[item - 1]["rms"], 1e-6),
        )
        transition_time = energy[transition_index]["time"]
        if not result or transition_time - result[-1]["time"] >= 8.0:
            result.append({
                "time": transition_time,
                "kind": "energy_transition_candidate",
                "relative_change": round(change, 4),
                "confidence": round(min(0.75, 0.35 + change * 0.25), 3),
                "label": None,
                "method": "relative_change_in_rolling_rms_energy",
            })
    return result
