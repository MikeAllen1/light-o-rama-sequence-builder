"""Audio analysis for timing candidates used by the sequence planner.

Beat and onset results are suggestions, not guaranteed musical annotations. Users
must be able to review and edit timing before effects are generated.
"""

from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any


class AudioAnalysisError(ValueError):
    """Raised when an audio file cannot be analyzed."""


def _interval_summary(times_ms: list[int]) -> dict[str, float | None]:
    """Summarize beat spacing without claiming that the estimate is correct."""
    if len(times_ms) < 2:
        return {
            "median_interval_ms": None,
            "interval_regularity": 0.0,
        }

    intervals = [
        float(right - left)
        for left, right in zip(times_ms, times_ms[1:])
        if right > left
    ]
    if not intervals:
        return {
            "median_interval_ms": None,
            "interval_regularity": 0.0,
        }

    center = median(intervals)
    mean = sum(intervals) / len(intervals)
    variance = sum((value - mean) ** 2 for value in intervals) / len(intervals)
    coefficient_of_variation = (variance**0.5 / mean) if mean else 1.0
    return {
        "median_interval_ms": round(center, 2),
        "interval_regularity": round(max(0.0, 1.0 - coefficient_of_variation), 4),
    }


def analyze_audio(path: str | Path, sample_rate: int = 22050) -> dict[str, Any]:
    """Analyze an audio file and return editable beat, onset, and energy candidates.

    Requires the optional `audio` dependency group (`pip install .[audio]`).
    The source path is intentionally not included in the returned data.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Audio file not found: {source}")

    try:
        import librosa
    except ImportError as exc:
        raise AudioAnalysisError(
            "Audio analysis requires librosa. Install it with: "
            "python -m pip install -e '.[audio]'"
        ) from exc

    try:
        signal, actual_sample_rate = librosa.load(
            str(source),
            sr=sample_rate,
            mono=True,
        )
        if signal.size == 0:
            raise AudioAnalysisError("The audio file contains no samples.")

        duration_ms = round((len(signal) / actual_sample_rate) * 1000)
        tempo, beat_frames = librosa.beat.beat_track(
            y=signal,
            sr=actual_sample_rate,
            units="frames",
            trim=False,
        )
        tempo_values = getattr(tempo, "tolist", lambda: tempo)()
        if isinstance(tempo_values, list):
            tempo_bpm = float(tempo_values[0]) if tempo_values else 0.0
        else:
            tempo_bpm = float(tempo_values)

        beat_times_ms = [
            round(value * 1000)
            for value in librosa.frames_to_time(
                beat_frames,
                sr=actual_sample_rate,
            )
            if value >= 0
        ]
        onset_frames = librosa.onset.onset_detect(
            y=signal,
            sr=actual_sample_rate,
            units="frames",
            backtrack=False,
        )
        onset_times_ms = [
            round(value * 1000)
            for value in librosa.frames_to_time(
                onset_frames,
                sr=actual_sample_rate,
            )
            if value >= 0
        ]

        rms = librosa.feature.rms(
            y=signal,
            frame_length=2048,
            hop_length=actual_sample_rate,
        )[0]
        max_rms = float(rms.max()) if rms.size else 0.0
        energy_by_second = [
            round(float(value / max_rms), 4) if max_rms else 0.0
            for value in rms
        ]
    except AudioAnalysisError:
        raise
    except Exception as exc:
        raise AudioAnalysisError(f"Unable to analyze audio file: {exc}") from exc

    interval_summary = _interval_summary(beat_times_ms)
    return {
        "audio_file": source.name,
        "duration_ms": duration_ms,
        "sample_rate": actual_sample_rate,
        "tempo_bpm": round(tempo_bpm, 2),
        "beat_count": len(beat_times_ms),
        "beat_times_ms": beat_times_ms,
        "onset_count": len(onset_times_ms),
        "onset_times_ms": onset_times_ms,
        "energy_by_second": energy_by_second,
        **interval_summary,
        "notes": [
            "Tempo and beat times are algorithmic candidates, not verified musical truth.",
            "No time signature or downbeat positions are inferred.",
            "Review and edit timing markers before generating lighting effects.",
        ],
    }
