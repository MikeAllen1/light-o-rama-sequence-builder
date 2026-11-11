"""Orchestration for deterministic Phase 4 audio analysis.

The implementation is divided into focused modules:
- audio_io: stable input snapshots, FFmpeg normalization, and PCM decoding
- audio_features: onset, energy, stop, phrase, and section candidates
- audio_tempo: tempo and beat-grid confidence
- audio_plot: SVG diagnostics
"""

from __future__ import annotations

import json
import platform
import tempfile
from pathlib import Path
from typing import Any

from lor_sequence_builder.audio_common import (
    ANALYSIS_SCHEMA_VERSION,
    FRAME_CENTER_SECONDS,
    FRAME_SECONDS,
    FRAME_WINDOW_SECONDS,
    MAX_BPM,
    MAX_DURATION_SECONDS,
    MAX_INPUT_BYTES,
    MIN_BPM,
    MIN_DURATION_SECONDS,
    SAMPLE_RATE,
    AudioAnalysisError,
)
from lor_sequence_builder.audio_features import (
    _detect_onsets,
    _energy_curve,
    _hard_stops,
    _phrase_boundaries,
    _section_candidates,
)
from lor_sequence_builder.audio_io import _normalize, _read_features, _snapshot_source
from lor_sequence_builder.audio_plot import _svg_plot
from lor_sequence_builder.audio_tempo import _beat_grid_status, _estimate_tempo
from lor_sequence_builder.file_publish import publish_new_files


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
