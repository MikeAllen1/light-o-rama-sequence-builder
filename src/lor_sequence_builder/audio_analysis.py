"""Deterministic first-pass audio feature extraction for Phase 4.

The analyzer normalizes input through FFmpeg to mono 11.025 kHz PCM WAV, then
uses bounded, dependency-free signal processing. Estimates are intentionally
labelled as estimates; this is not source separation or semantic music tagging.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any

ANALYSIS_SCHEMA_VERSION = "1.0"
SAMPLE_RATE = 11_025
FRAME_SAMPLES = round(SAMPLE_RATE * 0.05)
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_DURATION_SECONDS = 30 * 60
MIN_DURATION_SECONDS = 2.0
MAX_DECODED_SAMPLES = SAMPLE_RATE * MAX_DURATION_SECONDS
MIN_BPM = 60
MAX_BPM = 200


class AudioAnalysisError(ValueError):
    """Raised when audio cannot be safely analyzed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize(path: Path, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioAnalysisError(
            "FFmpeg is required for audio decoding; install FFmpeg and ensure it is on PATH"
        )
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path), "-t", str(MAX_DURATION_SECONDS + 1), "-map", "0:a:0", "-vn", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(output),
    ]
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True,
            timeout=MAX_DURATION_SECONDS + 120,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioAnalysisError("FFmpeg audio normalization exceeded its time limit") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-500:]
        raise AudioAnalysisError(f"FFmpeg could not decode the audio: {detail}")


def _read_features(wav_path: Path) -> tuple[list[float], list[float], float]:
    try:
        with wave.open(str(wav_path), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames_total = source.getnframes()
            duration = frames_total / rate if rate else 0.0
            if channels != 1 or width != 2 or rate != SAMPLE_RATE:
                raise AudioAnalysisError("Normalized audio must be mono 16-bit PCM at 11025 Hz")
            if duration < MIN_DURATION_SECONDS:
                raise AudioAnalysisError("Audio must be at least 2 seconds long")
            if duration > MAX_DURATION_SECONDS or frames_total > MAX_DECODED_SAMPLES:
                raise AudioAnalysisError("Audio exceeds the 30-minute analysis limit")
            window = FRAME_SAMPLES
            rms_values: list[float] = []
            previous_energy = 0.0
            flux_values: list[float] = []
            while True:
                raw = source.readframes(window)
                if not raw:
                    break
                samples = array("h")
                samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
                if not samples:
                    continue
                if struct.pack("=h", 1) != struct.pack("<h", 1):
                    samples.byteswap()
                mean_square = math.fsum(float(sample) * sample for sample in samples) / len(samples)
                rms = math.sqrt(mean_square) / 32768.0
                energy = rms * rms
                rms_values.append(rms)
                flux_values.append(max(0.0, energy - previous_energy))
                previous_energy = energy
    except (OSError, wave.Error) as exc:
        raise AudioAnalysisError(f"Cannot read normalized PCM audio: {exc}") from exc
    return rms_values, flux_values, duration


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _detect_onsets(flux: list[float]) -> list[dict[str, float]]:
    if len(flux) < 3:
        return []
    baseline = _median(flux)
    deviations = [abs(value - baseline) for value in flux]
    mad = _median(deviations)
    maximum = max(flux)
    threshold = max(baseline + 3.0 * mad, maximum * 0.08, 1e-8)
    peaks: list[dict[str, float]] = []
    for index in range(1, len(flux) - 1):
        value = flux[index]
        if value >= threshold and value >= flux[index - 1] and value > flux[index + 1]:
            peaks.append({
                "time": round(index * FRAME_SECONDS, 3),
                "strength": round(value, 8),
                "confidence": round(min(1.0, value / maximum), 4),
            })
    return peaks


def _estimate_tempo(
    flux: list[float], min_bpm: int, max_bpm: int
) -> tuple[float | None, float, int | None, int | None]:
    if len(flux) < 40:
        return None, 0.0, None, None
    # Autocorrelation of onset strength; frame spacing is 50 ms.
    mean = math.fsum(flux) / len(flux)
    centered = [value - mean for value in flux]
    candidates: list[tuple[float, int]] = []
    for lag in range(
        round(60.0 / max_bpm / FRAME_SECONDS),
        round(60.0 / min_bpm / FRAME_SECONDS) + 1,
    ):
        overlap = len(centered) - lag
        if overlap <= 0:
            continue
        score = math.fsum(centered[i] * centered[i + lag] for i in range(overlap))
        score /= max(1, overlap)
        candidates.append((score, lag))
    if not candidates:
        return None, 0.0, None, None
    best_score = max(score for score, _ in candidates)
    if best_score <= 1e-12:
        return None, 0.0, None, None
    # Prefer the faster candidate when tempo aliases (for example 60/120 BPM)
    # have nearly equal autocorrelation. The confidence still reflects the best score.
    best_lag = min(
        lag for score, lag in candidates
        if score >= best_score * 0.98
    )
    positive = [score for score, _ in candidates if score > 0]
    mean_score = math.fsum(positive) / len(positive) if positive else 0.0
    confidence = max(0.0, min(1.0, (best_score - mean_score) / (abs(best_score) + 1e-12)))
    bpm = 60.0 / (best_lag * FRAME_SECONDS)
    # Phase maximizes onset strength sampled at the candidate beat period.
    period = best_lag
    phase_scores = [
        math.fsum(flux[index] for index in range(phase, len(flux), period))
        for phase in range(period)
    ]
    phase = max(range(period), key=lambda item: phase_scores[item])
    return round(bpm, 2), round(confidence, 4), best_lag, phase


def _energy_curve(rms: list[float]) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    frames_per_second = round(1.0 / FRAME_SECONDS)
    for start in range(0, len(rms), frames_per_second):
        chunk = rms[start:start + frames_per_second]
        if chunk:
            result.append({
                "time": round(start * FRAME_SECONDS, 2),
                "rms": round(math.sqrt(math.fsum(value * value for value in chunk) / len(chunk)), 6),
            })
    return result


def _hard_stops(
    rms: list[float], minimum_silence_seconds: float = 0.75
) -> list[dict[str, float]]:
    threshold = max(1e-5, max(rms, default=0.0) * 0.025)
    required_frames = max(1, round(minimum_silence_seconds / FRAME_SECONDS))
    stops: list[dict[str, float]] = []
    index = 1
    while index < len(rms):
        if rms[index] <= threshold and rms[index - 1] > threshold:
            end = index
            while end < len(rms) and rms[end] <= threshold:
                end += 1
            if end - index >= required_frames:
                stops.append({
                    "time": round(index * FRAME_SECONDS, 3),
                    "silence_duration": round((end - index) * FRAME_SECONDS, 3),
                    "confidence": 0.8,
                })
            index = end
        else:
            index += 1
    return stops


def _phrase_boundaries(
    duration: float, bpm: float | None, phase_frames: int | None, beat_lag: int | None
) -> list[dict[str, Any]]:
    if bpm is None or beat_lag is None or phase_frames is None:
        return []
    beat_seconds = beat_lag * FRAME_SECONDS
    phrase_seconds = beat_seconds * 16
    first_beat = phase_frames * FRAME_SECONDS
    result: list[dict[str, Any]] = []
    index = 0
    time = first_beat
    while time < duration:
        result.append({
            "time": round(time, 3),
            "kind": "estimated_16_beat_phrase",
            "confidence": 0.35,
            "basis": "fixed 16-beat grouping from estimated tempo; not semantic section recognition",
        })
        index += 1
        time = first_beat + index * phrase_seconds
    return result


def _section_candidates(energy: list[dict[str, float]]) -> list[dict[str, Any]]:
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
            })
    return result

def _svg_plot(
    path: Path, duration: float, energy: list[dict[str, float]],
    beats: list[float], onsets: list[dict[str, float]], stops: list[dict[str, float]]
) -> None:
    width, height = 1400, 520
    left, right, top, bottom = 70, 20, 35, 55
    plot_width, plot_height = width - left - right, height - top - bottom
    max_energy = max((point["rms"] for point in energy), default=1.0) or 1.0
    points = []
    for point in energy:
        x = left + point["time"] / duration * plot_width
        y = top + plot_height - point["rms"] / max_energy * plot_height
        points.append(f"{x:.1f},{y:.1f}")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="70" y="22" font-family="sans-serif" font-size="16">Audio analysis: RMS energy, beats, onsets, hard stops</text>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{width-right}" y2="{top + plot_height}" stroke="#333"/>',
    ]
    if points:
        parts.append(f'<polyline fill="none" stroke="#2767a8" stroke-width="2" points="{" ".join(points)}"/>')
    for beat in beats:
        x = left + beat / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#2b8a3e" opacity=".28"/>')
    for onset in onsets:
        x = left + onset["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top+plot_height-12}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#d97706"/>')
    for stop in stops:
        x = left + stop["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#c92a2a" stroke-width="2"/>')
    for tick in range(0, math.ceil(duration) + 1, max(1, math.ceil(duration / 12))):
        x = left + tick / duration * plot_width
        parts.append(f'<text x="{x:.1f}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="11">{tick}s</text>')
    parts.extend([
        '<text x="70" y="500" font-family="sans-serif" font-size="11">Blue: RMS energy | Green: estimated beats | Amber: detected onsets | Red: hard-stop candidates</text>',
        '</svg>',
    ])
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(parts))


def analyze_audio(
    audio_path: str | Path,
    json_output: str | Path,
    plot_output: str | Path,
    min_bpm: int = MIN_BPM,
    max_bpm: int = MAX_BPM,
) -> dict[str, Any]:
    """Analyze audio and write a versioned JSON report and an SVG diagnostic plot."""
    source = Path(audio_path)
    json_path = Path(json_output)
    plot_path = Path(plot_output)
    try:
        if not 30 <= min_bpm < max_bpm <= 300:
            raise AudioAnalysisError("Tempo bounds must satisfy 30 <= min BPM < max BPM <= 300")
        if not source.is_file():
            raise AudioAnalysisError(f"Audio input is not a regular file: {source}")
        size = source.stat().st_size
        if size <= 0 or size > MAX_INPUT_BYTES:
            raise AudioAnalysisError("Audio file must be non-empty and no larger than 200 MiB")
        resolved = {source.resolve(), json_path.resolve(), plot_path.resolve()}
        if len(resolved) != 3:
            raise AudioAnalysisError("Input, JSON output, and plot output must be different paths")
        if json_path.exists() or plot_path.exists():
            raise AudioAnalysisError("Refusing to overwrite an existing analysis output")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lor-audio-") as directory:
            normalized = Path(directory) / "normalized.wav"
            _normalize(source, normalized)
            rms, flux, duration = _read_features(normalized)
        onsets = _detect_onsets(flux)
        bpm, tempo_confidence, lag, phase = _estimate_tempo(flux, min_bpm, max_bpm)
        beat_times: list[float] = []
        downbeats: list[float] = []
        if lag is not None and phase is not None and bpm is not None:
            period = lag * FRAME_SECONDS
            time = phase * FRAME_SECONDS
            index = 0
            while time < duration:
                rounded = round(time, 3)
                beat_times.append(rounded)
                if index % 4 == 0:
                    downbeats.append(rounded)
                time += period
                index += 1
        energy = _energy_curve(rms)
        minimum_stop_silence = max(0.75, (60.0 / bpm) * 1.5) if bpm else 0.75
        stops = _hard_stops(rms, minimum_stop_silence)
        phrases = _phrase_boundaries(duration, bpm, phase, lag)
        sections = _section_candidates(energy)
        report: dict[str, Any] = {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "audio": {
                "file_name": source.name,
                "sha256": _sha256(source),
                "duration_seconds": round(duration, 3),
                "normalized_sample_rate": SAMPLE_RATE,
                "channels": 1,
                "sample_format": "signed 16-bit PCM",
            },
            "configuration": {
                "frame_seconds": FRAME_SECONDS,
                "minimum_bpm": min_bpm,
                "maximum_bpm": max_bpm,
                "minimum_duration_seconds": MIN_DURATION_SECONDS,
                "maximum_duration_seconds": MAX_DURATION_SECONDS,
                "maximum_input_bytes": MAX_INPUT_BYTES,
                "confidence_values": "heuristic and uncalibrated",
            },
            "analysis": {
                "method": "FFmpeg normalization + deterministic RMS/positive-energy-flux/autocorrelation",
                "limitations": [
                    "Tempo is a single global estimate; tempo changes are not modeled.",
                    "Downbeats assume the first detected beat is beat one and group every four beats.",
                    "Phrase boundaries are fixed 16-beat candidates, not semantic phrase detection.",
                    "Section candidates are energy transitions only; verse/chorus labels are not inferred.",
                    "Onsets are spectral-unaware positive energy-flux peaks and may miss soft or overlapping events.",
                    "Hard stops are sustained near-silence candidates and may include intentional pauses.",
                ],
                "tempo": {
                    "bpm": bpm,
                    "confidence": tempo_confidence,
                    "method": "onset-envelope autocorrelation",
                },
                "beats": [{"time": value, "confidence": tempo_confidence} for value in beat_times],
                "downbeats": [{"time": value, "confidence": round(tempo_confidence * 0.7, 4)}
                              for value in downbeats],
                "onsets": onsets,
                "energy": energy,
                "phrase_boundaries": phrases,
                "section_candidates": sections,
                "hard_stops": stops,
            },
        }
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        with json_path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        try:
            _svg_plot(plot_path, duration, energy, beat_times, onsets, stops)
        except OSError:
            json_path.unlink(missing_ok=True)
            raise
        return report
    except OSError as exc:
        raise AudioAnalysisError(f"Audio analysis I/O failure: {exc}") from exc
