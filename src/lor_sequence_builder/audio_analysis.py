"""Deterministic first-pass audio feature extraction for Phase 4.

The analyzer normalizes input through FFmpeg to mono 11.025 kHz PCM WAV, then
uses bounded, dependency-free signal processing. Estimates are intentionally
labelled as estimates; this is not source separation or semantic music tagging.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import shutil
import struct
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any

from lor_sequence_builder.audio_plot import _svg_plot
from lor_sequence_builder.audio_tempo import _beat_grid_status, _estimate_tempo
from lor_sequence_builder.file_publish import publish_new_files

ANALYSIS_SCHEMA_VERSION = "1.3"
SAMPLE_RATE = 11_025
FRAME_HOP_SAMPLES = round(SAMPLE_RATE * 0.01)
FRAME_WINDOW_SAMPLES = round(SAMPLE_RATE * 0.05)
FRAME_SECONDS = FRAME_HOP_SAMPLES / SAMPLE_RATE
FRAME_WINDOW_SECONDS = FRAME_WINDOW_SAMPLES / SAMPLE_RATE
FRAME_CENTER_SECONDS = FRAME_WINDOW_SECONDS / 2.0
MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_DURATION_SECONDS = 30 * 60
MIN_DURATION_SECONDS = 2.0
MAX_DECODED_SAMPLES = SAMPLE_RATE * MAX_DURATION_SECONDS
MAX_FFMPEG_SECONDS = 300
INPUT_FORMATS = {
    ".aac": "aac",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".flac": "flac",
    ".m4a": "mov",
    ".mp3": "mp3",
    ".mp4": "mov",
    ".ogg": "ogg",
    ".wav": "wav",
    ".wma": "asf",
}
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


def _snapshot_source(source: Path, destination: Path) -> str:
    """Copy and hash the exact bytes that FFmpeg will analyze."""
    digest = hashlib.sha256()
    total_bytes = 0
    try:
        with source.open("rb") as input_stream, destination.open("xb") as snapshot:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                total_bytes += len(block)
                if total_bytes > MAX_INPUT_BYTES:
                    raise AudioAnalysisError(
                        "Audio file must be non-empty and no larger than 200 MiB"
                    )
                digest.update(block)
                snapshot.write(block)
    except OSError as exc:
        raise AudioAnalysisError(f"Could not create a stable audio input snapshot: {exc}") from exc
    if total_bytes == 0:
        raise AudioAnalysisError("Audio input is empty")
    return digest.hexdigest()


def _normalize(path: Path, output: Path) -> str:
    input_format = INPUT_FORMATS.get(path.suffix.lower())
    if input_format is None:
        raise AudioAnalysisError(
            f"Unsupported audio extension {path.suffix!r}; use a supported audio file type"
        )
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioAnalysisError(
            "FFmpeg is required for audio decoding; install FFmpeg and ensure it is on PATH"
        )
    try:
        version_result = subprocess.run(
            [ffmpeg, "-version"], check=False, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioAnalysisError("Could not determine the installed FFmpeg version") from exc
    if version_result.returncode != 0 or not version_result.stdout:
        raise AudioAnalysisError("Could not determine the installed FFmpeg version")
    ffmpeg_version = version_result.stdout.splitlines()[0].strip()
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file",
        "-f", input_format,
        "-i", str(path.resolve()), "-t", str(MAX_DURATION_SECONDS + 1), "-map", "0:a:0", "-vn", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(output),
    ]
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True,
            timeout=MAX_FFMPEG_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioAnalysisError("FFmpeg audio normalization exceeded its time limit") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-500:]
        raise AudioAnalysisError(f"FFmpeg could not decode the audio: {detail}")
    return ffmpeg_version


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
            samples = array("h")
            samples.frombytes(source.readframes(frames_total))
            if struct.pack("=h", 1) != struct.pack("<h", 1):
                samples.byteswap()
            window = FRAME_WINDOW_SAMPLES
            hop = FRAME_HOP_SAMPLES
            if len(samples) < window:
                raise AudioAnalysisError("Normalized audio is shorter than one analysis window")
            window_energy = math.fsum(
                float(samples[index]) * samples[index] for index in range(window)
            )
            rms_values: list[float] = []
            flux_values: list[float] = []
            previous_energy = 0.0
            start = 0
            while start + window <= len(samples):
                mean_square = max(0.0, window_energy) / window
                rms = math.sqrt(mean_square) / 32768.0
                energy = rms * rms
                rms_values.append(rms)
                flux_values.append(max(0.0, energy - previous_energy))
                previous_energy = energy
                next_start = start + hop
                if next_start + window > len(samples):
                    break
                # Update the overlapping window in O(hop) rather than
                # recalculating every 50 ms window from all its samples.
                for index in range(start, next_start):
                    sample = samples[index]
                    window_energy -= float(sample) * sample
                for index in range(start + window, next_start + window):
                    sample = samples[index]
                    window_energy += float(sample) * sample
                start = next_start
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
            work_dir = Path(directory)
            snapshot = work_dir / f"input{source.suffix.lower()}"
            source_sha256 = _snapshot_source(source, snapshot)
            normalized = work_dir / "normalized.wav"
            ffmpeg_version = _normalize(snapshot, normalized)
            rms, flux, duration = _read_features(normalized)
        onsets = _detect_onsets(flux)
        bpm, tempo_confidence, lag, phase, phase_confidence, tempo_candidates = _estimate_tempo(
            flux, min_bpm, max_bpm, FRAME_SECONDS
        )
        beat_times: list[float] = []
        downbeats: list[float] = []
        if lag is not None and phase is not None and bpm is not None:
            period = lag * FRAME_SECONDS
            time = phase * FRAME_SECONDS + FRAME_CENTER_SECONDS
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
        beat_grid_status = _beat_grid_status(
            bool(beat_times), tempo_confidence, phase_confidence
        )
        report: dict[str, Any] = {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "audio": {
                "file_name": source.name,
                "sha256": source_sha256,
                "duration_seconds": round(duration, 3),
                "normalized_sample_rate": SAMPLE_RATE,
                "channels": 1,
                "sample_format": "signed 16-bit PCM",
            },
            "tool_versions": {
                "analyzer_schema": ANALYSIS_SCHEMA_VERSION,
                "ffmpeg": ffmpeg_version,
                "python": platform.python_version(),
            },
            "configuration": {
                "frame_seconds": FRAME_SECONDS,
                "frame_window_seconds": FRAME_WINDOW_SECONDS,
                "minimum_bpm": min_bpm,
                "maximum_bpm": max_bpm,
                "minimum_duration_seconds": MIN_DURATION_SECONDS,
                "maximum_duration_seconds": MAX_DURATION_SECONDS,
                "maximum_input_bytes": MAX_INPUT_BYTES,
                "confidence_values": "heuristic and uncalibrated",
            },
            "analysis": {
                "method": "FFmpeg normalization + deterministic RMS/positive-energy-flux/autocorrelation",
                "provenance": "All timestamps are relative to the decoded audio stream start; RMS and positive energy flux use 551-sample (approximately 50 ms) windows every 110 samples (approximately 10 ms), with transient and beat timestamps centered on the analysis window.",
                "limitations": [
                    "Tempo is a single global estimate; tempo changes are not modeled.",
                    "Strong repeating accents, syncopation, and subdivisions can create half-time or double-time ambiguity; candidate peaks are exposed but not musically ranked.",
                    "Beat-grid status is provisional only: unavailable means no grid was produced; ambiguous means tempo-confidence multiplied by phase-confidence is below 0.20; provisional does not mean musically verified.",
                    "Beat phase is selected from repeating onset energy; meaningful energy halfway between candidate beats reduces phase confidence because autocorrelation cannot determine whether the stronger accent is the metrical beat or an offbeat.",
                    "Downbeats assume the first detected beat is beat one and group every four beats.",
                    "Phrase boundaries are fixed 16-beat candidates, not semantic phrase detection.",
                    "Section candidates are energy transitions only; verse/chorus labels are not inferred.",
                    "Onsets are spectral-unaware positive energy-flux peaks from overlapping 50 ms windows on a 10 ms hop; timestamps are window-centered and remain approximate, not sample-accurate musical attacks.",
                    "The 10 ms hop improves timing resolution but does not by itself validate a 30 ms lighting lead; real-song alignment still requires listening and comparison with finished sequences.",
                    "Hard stops are sustained near-silence candidates and may include intentional pauses.",
                ],
                "beat_grid_status": beat_grid_status,
                "tempo": {
                    "bpm": bpm,
                    "confidence": tempo_confidence,
                    "method": "onset-envelope autocorrelation with explicit periodicity candidates",
                    "candidates": tempo_candidates,
                },
                "beats": [
                    {"time": value, "confidence": round(tempo_confidence * phase_confidence, 4),
                     "method": "global_onset_envelope_autocorrelation_grid_with_phase_separation"}
                    for value in beat_times
                ],
                "downbeats": [
                    {"time": value, "confidence": round(
                        tempo_confidence * phase_confidence * 0.7, 4
                     ),
                     "method": "provisional_first_beat_plus_four_beat_meter_assumption"}
                    for value in downbeats
                ],
                "onsets": onsets,
                "energy": energy,
                "phrase_boundaries": phrases,
                "section_candidates": sections,
                "hard_stops": stops,
            },
        }
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        try:
            with tempfile.TemporaryDirectory(
                prefix=".lor-analysis-json-", dir=json_path.parent
            ) as json_directory, tempfile.TemporaryDirectory(
                prefix=".lor-analysis-plot-", dir=plot_path.parent
            ) as plot_directory:
                json_temp = Path(json_directory) / "analysis.json"
                plot_temp = Path(plot_directory) / "analysis.svg"
                json_temp.write_text(serialized, encoding="utf-8")
                _svg_plot(
                    plot_temp, duration, energy, beat_times, downbeats, onsets, sections, stops
                )
                publish_new_files([(json_temp, json_path), (plot_temp, plot_path)])
        except FileExistsError as exc:
            raise AudioAnalysisError("Refusing to overwrite an existing analysis output") from exc
        return report
    except OSError as exc:
        raise AudioAnalysisError(f"Audio analysis I/O failure: {exc}") from exc
