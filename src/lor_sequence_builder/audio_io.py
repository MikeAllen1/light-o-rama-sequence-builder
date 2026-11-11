"""Stable input snapshots, FFmpeg normalization, and PCM feature reading."""

from __future__ import annotations

import hashlib
import math
import shutil
import struct
import subprocess
import wave
from array import array
from pathlib import Path

from lor_sequence_builder.audio_common import (
    FRAME_HOP_SAMPLES,
    FRAME_WINDOW_SAMPLES,
    INPUT_FORMATS,
    MAX_DECODED_SAMPLES,
    MAX_DURATION_SECONDS,
    MAX_FFMPEG_SECONDS,
    MAX_INPUT_BYTES,
    MIN_DURATION_SECONDS,
    SAMPLE_RATE,
    AudioAnalysisError,
)


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
        version_result = subprocess.run(  # noqa: S603 - fixed executable and constant arguments
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
        "-i", str(path.resolve()),
        "-t", str(MAX_DURATION_SECONDS + 1),
        "-map", "0:a:0",
        "-vn",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        "-f", "wav",
        str(output),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable and validated argument list
            command,
            check=False,
            capture_output=True,
            text=True,
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
