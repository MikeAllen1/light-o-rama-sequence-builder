"""Tempo and beat-grid estimation helpers for audio analysis."""
from __future__ import annotations

import math


def _estimate_tempo(
    flux: list[float], min_bpm: int, max_bpm: int, frame_seconds: float
) -> tuple[float | None, float, float | None, int | None, float, list[dict[str, float]]]:
    if len(flux) < 40:
        return None, 0.0, None, None, 0.0, []
    # Autocorrelation of onset strength; frame hop is 10 ms.
    mean = math.fsum(flux) / len(flux)
    centered = [value - mean for value in flux]
    candidates: list[tuple[float, int]] = []
    for lag in range(
        round(60.0 / max_bpm / frame_seconds),
        round(60.0 / min_bpm / frame_seconds) + 1,
    ):
        overlap = len(centered) - lag
        if overlap <= 0:
            continue
        score = math.fsum(centered[i] * centered[i + lag] for i in range(overlap))
        score /= max(1, overlap)
        candidates.append((score, lag))
    if not candidates:
        return None, 0.0, None, None, 0.0, []
    best_score = max(score for score, _ in candidates)
    variance = math.fsum(value * value for value in centered) / len(centered)
    # Reject weak periodic ripple, such as the window-boundary variation of a
    # steady tone. A candidate must explain a meaningful share of flux variance.
    if best_score <= max(1e-12, variance * 0.01):
        return None, 0.0, None, None, 0.0, []
    # Autocorrelation has octave/subdivision aliases: the strongest peak can
    # represent a slower metrical level (for example, half-time). Prefer the
    # shortest local peak retaining a substantial share of the strongest
    # correlation. This is a deliberate tempo-prior heuristic, not meter
    # detection; real music can still produce half/double-time ambiguity.
    scores_by_lag = {lag: score for score, lag in candidates}
    local_peaks = [
        lag for score, lag in candidates
        if score >= scores_by_lag.get(lag - 1, float("-inf"))
        and score >= scores_by_lag.get(lag + 1, float("-inf"))
        and score >= best_score * 0.50
    ]
    best_lag = min(local_peaks) if local_peaks else max(candidates)[1]
    # Keep distinct periodicity peaks visible: autocorrelation alone cannot
    # determine which metrical level a listener would count as the beat.
    ranked_peaks = sorted(local_peaks, key=lambda lag: scores_by_lag[lag], reverse=True)
    # The selected tempo must always be visible, even when it is not among the
    # six strongest correlation peaks because the alias heuristic chose it.
    candidate_lags = [best_lag, *[lag for lag in ranked_peaks if lag != best_lag][:5]]
    tempo_candidates = [
        {
            "bpm": round(60.0 / (candidate_lag * frame_seconds), 2),
            "relative_score": round(max(0.0, scores_by_lag[candidate_lag]) / best_score, 4),
        }
        for candidate_lag in candidate_lags
    ]
    # Parabolic interpolation around the discrete correlation peak reduces
    # BPM quantization error for tempos whose beat period is not an integer
    # number of 50 ms analysis frames.
    left_score = scores_by_lag.get(best_lag - 1)
    center_score = scores_by_lag.get(best_lag)
    right_score = scores_by_lag.get(best_lag + 1)
    refined_lag = float(best_lag)
    if left_score is not None and right_score is not None and center_score is not None:
        denominator = left_score - 2.0 * center_score + right_score
        if denominator < -1e-12:
            offset = 0.5 * (left_score - right_score) / denominator
            if abs(offset) <= 0.5:
                refined_lag += offset
    if tempo_candidates:
        tempo_candidates[0]["bpm"] = round(60.0 / (refined_lag * frame_seconds), 2)
    positive = [score for score, _ in candidates if score > 0]
    mean_score = math.fsum(positive) / len(positive) if positive else 0.0
    confidence = max(0.0, min(1.0, (best_score - mean_score) / (abs(best_score) + 1e-12)))
    bpm = 60.0 / (refined_lag * frame_seconds)
    # A peak at the configured search boundary is censored evidence: a stronger
    # candidate may exist just outside the requested range. Do not report it
    # with ordinary confidence.
    if bpm <= min_bpm + 1.5 or bpm >= max_bpm - 1.5:
        confidence = min(confidence, 0.1)
    # Phase maximizes onset strength sampled at the candidate beat period.
    period = best_lag
    phase_scores = [
        math.fsum(flux[index] for index in range(phase, len(flux), period))
        for phase in range(period)
    ]
    phase = max(range(period), key=lambda item: phase_scores[item])
    # Adjacent frame offsets often represent the same transient smeared across
    # neighboring analysis windows. Compare the winning phase with the strongest
    # genuinely separate phase, not merely the second-highest adjacent frame.
    separation = max(2, round(period * 0.2))
    alternatives = [
        score for offset, score in enumerate(phase_scores)
        if min((offset - phase) % period, (phase - offset) % period) >= separation
    ]
    half_period_phase = (phase + max(1, round(period / 2))) % period
    alternate_score = max(
        max(alternatives, default=0.0), phase_scores[half_period_phase]
    )
    winning_score = phase_scores[phase]
    alternate_ratio = alternate_score / (winning_score + 1e-12)
    # A meaningful accent halfway between candidate beats may be an offbeat
    # or subdivision. Autocorrelation cannot decide which accent is metrical,
    # so confidence falls to zero when that competing phase reaches 10% of the
    # winning phase instead of confidently selecting the louder accent.
    phase_confidence = max(0.0, min(1.0, 1.0 - alternate_ratio / 0.10))
    return round(bpm, 2), round(confidence, 4), refined_lag, phase, round(phase_confidence, 4), tempo_candidates


def _beat_grid_status(
    has_beats: bool, tempo_confidence: float, phase_confidence: float
) -> str:
    if not has_beats:
        return "unavailable"
    if tempo_confidence * phase_confidence < 0.2:
        return "ambiguous"
    return "provisional"


