"""Audio feature extraction for Phase 4.

FFmpeg decodes and normalizes every input to mono 22.05 kHz signed 16-bit PCM;
librosa never opens a file. Rhythm and structure come from librosa signal
processing on the decoded samples. Every inferred event carries its method and
a heuristic confidence. Estimates are labelled as estimates: this is not
source separation or semantic music tagging.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import tempfile
import wave
from importlib import metadata
from pathlib import Path
from typing import IO, Any

import librosa
import numpy as np
import numpy.typing as npt

ANALYSIS_SCHEMA_VERSION = "2.0"
SAMPLE_RATE = 22_050
HOP_LENGTH = 512
FRAME_SAMPLES = round(SAMPLE_RATE * 0.05)
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_DURATION_SECONDS = 30 * 60
MIN_DURATION_SECONDS = 2.0
MAX_DECODED_SAMPLES = SAMPLE_RATE * MAX_DURATION_SECONDS
# Allow one second beyond the accepted duration so _read_samples can report
# the established duration-limit error instead of FFmpeg truncating at 30:00.
MAX_NORMALIZED_BYTES = (SAMPLE_RATE * (MAX_DURATION_SECONDS + 2) * 2) + 44
MIN_BPM = 60
MAX_BPM = 200
SUPPORTED_BEATS_PER_BAR = (3, 4)
# Explicit demuxer allowlist prevents playlist/container inputs from selecting
# arbitrary nested resources. Protocols are independently restricted below.
INPUT_DEMUXERS = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".aac": "aac",
    ".flac": "flac",
    ".ogg": "ogg",
    ".opus": "ogg",
    ".wma": "asf",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".m4a": "mov",
    ".m4b": "mov",
    ".mp4": "mov",
    ".mka": "matroska",
    ".mkv": "matroska",
    ".webm": "matroska",
    ".ape": "ape",
    ".wv": "wv",
}

# Structural segmentation tunables, chosen against owner-made section grids.
SECTION_KERNEL_BEATS = 16
SECTION_THRESHOLD = 0.5
SECTION_MIN_SPACING_BARS = 4
SECTION_LOUDNESS_SPAN_BEATS = 4
TEMPO_STABILITY_TOLERANCE = 0.04
# A beat must have onset strength nearby of at least this share of the median.
BEAT_SUPPORT_FRAMES = 4
BEAT_SUPPORT_RATIO = 0.2
# Below this harmonic-change margin the bar phase is treated as unknown.
DOWNBEAT_MIN_EVIDENCE = 0.1
# Fewer bars than this is too little evidence to infer the bar phase.
DOWNBEAT_MIN_BARS = 4
# Dense self-similarity recurrence matrices are quadratic in beat count. Above
# this limit, section detection falls back to its bounded loudness-change signal.
MAX_SECTION_RECURRENCE_BEATS = 2_000

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


class AudioAnalysisError(ValueError):
    """Raised when audio cannot be safely analyzed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize(path: Path, output: Path, input_demuxer: str | None = None) -> str:
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
    demuxer = input_demuxer or INPUT_DEMUXERS.get(path.suffix.lower())
    if demuxer is None or demuxer not in INPUT_DEMUXERS.values():
        supported = ", ".join(sorted(INPUT_DEMUXERS))
        raise AudioAnalysisError(
            f"Unsupported audio file extension {path.suffix!r}; supported extensions: {supported}"
        )
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file,pipe", "-f", demuxer, "-i", str(path.resolve()),
        "-t", str(MAX_DURATION_SECONDS + 1), "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav",
        "-fs", str(MAX_NORMALIZED_BYTES), str(output),
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
    try:
        normalized_size = output.stat().st_size
    except OSError as exc:
        raise AudioAnalysisError("FFmpeg did not create its normalized output") from exc
    if normalized_size > MAX_NORMALIZED_BYTES:
        raise AudioAnalysisError("Normalized audio exceeds the configured disk-space limit")
    return ffmpeg_version


def _read_samples(wav_path: Path) -> tuple[npt.NDArray[np.float32], float]:
    try:
        with wave.open(str(wav_path), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames_total = source.getnframes()
            duration = frames_total / rate if rate else 0.0
            if channels != 1 or width != 2 or rate != SAMPLE_RATE:
                raise AudioAnalysisError(
                    f"Normalized audio must be mono 16-bit PCM at {SAMPLE_RATE} Hz"
                )
            if duration < MIN_DURATION_SECONDS:
                raise AudioAnalysisError("Audio must be at least 2 seconds long")
            if duration > MAX_DURATION_SECONDS or frames_total > MAX_DECODED_SAMPLES:
                raise AudioAnalysisError("Audio exceeds the 30-minute analysis limit")
            raw = source.readframes(frames_total)
    except (OSError, wave.Error) as exc:
        raise AudioAnalysisError(f"Cannot read normalized PCM audio: {exc}") from exc
    pcm = np.frombuffer(raw[: len(raw) - (len(raw) % 2)], dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0), duration


def _frame_rms(samples: npt.NDArray[np.float32]) -> list[float]:
    usable = len(samples) - (len(samples) % FRAME_SAMPLES)
    frames = samples[:usable].astype(np.float64).reshape(-1, FRAME_SAMPLES)
    values = np.sqrt(np.mean(frames * frames, axis=1))
    if usable < len(samples):
        tail = samples[usable:].astype(np.float64)
        values = np.append(values, math.sqrt(float(np.mean(tail * tail))))
    return [float(value) for value in values]


def _frames_to_times(frames: IntArray | FloatArray) -> FloatArray:
    return np.asarray(
        librosa.frames_to_time(frames, sr=SAMPLE_RATE, hop_length=HOP_LENGTH),
        dtype=np.float64,
    )


def _onset_envelope(samples: npt.NDArray[np.float32]) -> FloatArray:
    return np.asarray(
        librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH),
        dtype=np.float64,
    )


def _has_pulse(envelope: FloatArray) -> bool:
    """Reject audio with no transient structure (silence, steady tones)."""
    if envelope.size < 8:
        return False
    peak = float(np.max(envelope))
    if peak <= 1e-3:
        return False
    # A pulse needs repeated strong transients standing well above the median.
    median = float(np.median(envelope))
    strong = int(np.count_nonzero(envelope > max(median * 4.0, peak * 0.25)))
    return strong >= 4


def _detect_onsets(envelope: FloatArray) -> list[dict[str, Any]]:
    frames = np.asarray(
        librosa.onset.onset_detect(
            onset_envelope=envelope, sr=SAMPLE_RATE, hop_length=HOP_LENGTH, units="frames"
        ),
        dtype=np.int64,
    )
    if frames.size == 0:
        return []
    peak = float(np.max(envelope)) or 1.0
    times = _frames_to_times(frames)
    return [
        {
            "time": round(float(time), 3),
            "strength": round(float(envelope[frame]), 6),
            "confidence": round(min(1.0, float(envelope[frame]) / peak), 4),
            "method": "librosa_onset_detect_on_spectral_flux_envelope",
        }
        for frame, time in zip(frames, times, strict=True)
    ]


HIGH_BAND_HZ = 5000.0


def _high_hits(samples: npt.NDArray[np.float32]) -> list[dict[str, Any]]:
    """Hits in the high frequencies: tambourine, sleigh bells, hi-hats, shakers."""
    envelope = np.asarray(
        librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
                                     fmin=HIGH_BAND_HZ, n_mels=32),
        dtype=np.float64,
    )
    frames = np.asarray(
        librosa.onset.onset_detect(onset_envelope=envelope, sr=SAMPLE_RATE,
                                   hop_length=HOP_LENGTH, units="frames"),
        dtype=np.int64,
    )
    if frames.size == 0:
        return []
    reference = float(np.percentile(envelope[frames], 90)) or 1.0
    events = []
    for frame, time in zip(frames, _frames_to_times(frames), strict=True):
        strength = float(envelope[frame]) / reference
        if strength >= 0.35:
            events.append({
                "time": round(float(time), 3),
                "confidence": round(min(1.0, strength), 4),
                "method": "librosa_onset_detect_above_5khz",
            })
    return events


CRASH_LOUDNESS_PERCENTILE = 97
CRASH_JUMP = 2.0
CRASH_RING = 0.55
CRASH_SPACING = 1.0


def _crashes(samples: npt.NDArray[np.float32], hits: list[dict[str, Any]]
             ) -> list[dict[str, Any]]:
    """Cymbal crash candidates: loud high-frequency hits that ring on afterwards.

    A hi-hat or tambourine hit dies away within a tenth of a second; a crash
    cymbal keeps ringing. Each high hit is kept when the high band jumps well
    above what came just before, is among the loudest high-band moments in the
    song, and is still at least 55% of that peak a quarter to half a second
    later. Crashes closer than a second apart count once.
    """
    if not hits:
        return []
    mel = librosa.feature.melspectrogram(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
                                         fmin=HIGH_BAND_HZ, n_mels=32)
    energy = np.asarray(np.sqrt(np.sum(mel, axis=0)), dtype=np.float64)
    if energy.size == 0:
        return []
    loud = float(np.percentile(energy, CRASH_LOUDNESS_PERCENTILE)) or 1.0
    per_second = SAMPLE_RATE / HOP_LENGTH
    events: list[dict[str, Any]] = []
    for hit in hits:
        frame = int(float(hit["time"]) * per_second)
        if frame >= energy.size:
            continue
        peak = float(np.max(energy[frame:frame + max(1, int(0.05 * per_second))]))
        before = energy[max(0, frame - int(0.3 * per_second)):max(1, frame - 1)]
        after = energy[frame + int(0.25 * per_second):frame + int(0.5 * per_second)]
        if after.size == 0 or before.size == 0:
            continue
        prior = float(np.mean(before))
        sustain = float(np.mean(after))
        if peak >= loud and peak >= CRASH_JUMP * prior and sustain >= CRASH_RING * peak:
            if events and float(hit["time"]) - float(events[-1]["time"]) < CRASH_SPACING:
                continue
            events.append({
                "time": hit["time"],
                "confidence": round(min(1.0, sustain / peak), 4),
                "method": "high_band_hit_with_sustained_ring",
            })
    return events


def _tempo_curve(envelope: FloatArray, bpm: float | None) -> list[dict[str, Any]]:
    """Local tempo once per second, so tempo changes are visible, not hidden in one BPM."""
    if bpm is None or envelope.size < 16:
        return []
    local = np.asarray(
        librosa.feature.tempo(onset_envelope=envelope, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
                              aggregate=None, max_tempo=300.0),
        dtype=np.float64,
    )
    local = np.where(np.isfinite(local) & (local > 0), local, bpm)
    # Fold each estimate to the song tempo's octave, then smooth over 4 seconds.
    folded = local.copy()
    for _ in range(4):
        folded = np.where(folded > bpm * 1.41, folded / 2, folded)
        folded = np.where(folded < bpm / 1.41, folded * 2, folded)
    width = int(4 * SAMPLE_RATE / HOP_LENGTH) | 1
    padded = np.pad(folded, width // 2, mode="edge")
    smooth = np.median(np.lib.stride_tricks.sliding_window_view(padded, width), axis=1)
    per_second = SAMPLE_RATE / HOP_LENGTH
    return [
        {"time": float(second), "bpm": round(float(smooth[int(second * per_second)]), 2)}
        for second in range(int(smooth.size / per_second))
    ]


def _fit_tempo_bounds(bpm: float, min_bpm: int, max_bpm: int) -> float | None:
    """Return an octave-equivalent tempo inside the requested range, if one exists."""
    if not math.isfinite(bpm) or bpm <= 0:
        return None
    while bpm < min_bpm and bpm * 2 <= max_bpm:
        bpm *= 2
    while bpm > max_bpm and bpm / 2 >= min_bpm:
        bpm /= 2
    return bpm if min_bpm <= bpm <= max_bpm else None


def _drop_unsupported_beats(envelope: FloatArray, frames: IntArray) -> IntArray:
    """Remove grid-filler beats with no transient nearby (lead-in or trailing silence)."""
    if frames.size == 0:
        return frames
    support = np.array(
        [float(np.max(envelope[max(0, f - BEAT_SUPPORT_FRAMES):f + BEAT_SUPPORT_FRAMES + 1]))
         for f in frames],
        dtype=np.float64,
    )
    positive_support = support[support > 1e-8]
    if positive_support.size == 0:
        return np.zeros(0, dtype=np.int64)
    floor = float(np.median(positive_support)) * BEAT_SUPPORT_RATIO
    # A zero median must never turn the threshold into zero: that would retain
    # unsupported grid positions throughout silence.
    return frames[(support > 1e-8) & (support >= floor)]


def _track_beats(
    envelope: FloatArray, min_bpm: int, max_bpm: int
) -> tuple[float | None, IntArray, float, float]:
    """Return (bpm, beat frames, tempo stability, beat-grid contrast)."""
    empty = np.zeros(0, dtype=np.int64)
    if not _has_pulse(envelope):
        return None, empty, 0.0, 0.0
    global_tempo = float(
        np.atleast_1d(
            librosa.feature.tempo(
                onset_envelope=envelope, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
                max_tempo=float(max_bpm),
            )
        )[0]
    )
    if not math.isfinite(global_tempo) or global_tempo <= 0:
        return None, empty, 0.0, 0.0
    fitted_global_tempo = _fit_tempo_bounds(global_tempo, min_bpm, max_bpm)
    if fitted_global_tempo is None:
        return None, empty, 0.0, 0.0
    global_tempo = fitted_global_tempo
    _, frames_any = librosa.beat.beat_track(
        onset_envelope=envelope, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
        bpm=global_tempo, units="frames", trim=False,
    )
    frames = _drop_unsupported_beats(envelope, np.asarray(frames_any, dtype=np.int64))
    if frames.size < 4:
        return None, empty, 0.0, 0.0
    # Fit one period across all beats: frame quantization makes individual
    # intervals alternate, so a least-squares slope beats a median interval.
    times = _frames_to_times(frames)
    rough_period = float(np.median(np.diff(times)))
    # Number beats gap by gap. Dividing elapsed time by a frame-quantized median
    # period misnumbers beats late in long songs and biases the fitted tempo.
    steps = np.maximum(1.0, np.round(np.diff(times) / rough_period))
    beat_numbers = np.concatenate(([0.0], np.cumsum(steps)))
    period = float(np.polyfit(beat_numbers, times, 1)[0])
    if not math.isfinite(period) or period <= 0:
        return None, empty, 0.0, 0.0
    fitted_bpm = _fit_tempo_bounds(60.0 / period, min_bpm, max_bpm)
    if fitted_bpm is None:
        return None, empty, 0.0, 0.0
    bpm = fitted_bpm

    # Tempo stability: share of local tempo estimates agreeing with the global
    # tempo (or its half/double, which describe the same pulse).
    local = np.asarray(
        librosa.feature.tempo(
            onset_envelope=envelope, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
            max_tempo=float(max_bpm), aggregate=None,
        ),
        dtype=np.float64,
    )
    agree = np.zeros(local.shape, dtype=bool)
    for factor in (0.5, 1.0, 2.0):
        target = bpm * factor
        agree |= np.abs(local - target) <= target * TEMPO_STABILITY_TOLERANCE
    stability = float(np.mean(agree)) if local.size else 0.0

    # Beat-grid contrast: onset strength on the beats versus halfway between.
    on_beat = float(np.mean(envelope[frames]))
    midpoints = ((frames[:-1] + frames[1:]) // 2).astype(np.int64)
    off_beat = float(np.mean(envelope[midpoints]))
    contrast = max(0.0, (on_beat - off_beat) / (on_beat + off_beat + 1e-12))
    return round(bpm, 2), frames, round(stability, 4), round(contrast, 4)


def _beat_sync(features: Any, beat_frames: IntArray, aggregate: Any = None) -> FloatArray:
    """Aggregate frame features per beat, with column i covering beat i up to beat i+1.

    librosa.util.sync adds a leading column for audio before the first beat when
    the first beat is not frame 0; anchoring at frame 0 and dropping that column
    keeps column indices equal to beat indices.
    """
    frames = [int(f) for f in beat_frames]
    # Close the final beat after one typical beat length so its column does not
    # absorb an outro or trailing silence.
    period = int(np.median(np.diff(frames))) if len(frames) > 1 else 1
    boundaries = [0, *[f for f in frames if f > 0], frames[-1] + max(1, period)]
    synced = np.asarray(
        librosa.util.sync(features, boundaries, aggregate=aggregate or np.mean),
        dtype=np.float64,
    )
    if frames[0] > 0:
        synced = synced[:, 1:]
    return synced[:, : len(frames)]


def _beat_chroma(samples: npt.NDArray[np.float32], beat_frames: IntArray) -> FloatArray:
    chroma = librosa.feature.chroma_cqt(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    return _beat_sync(chroma, beat_frames, aggregate=np.median)


def _downbeat_phase(
    beat_chroma: FloatArray, beat_count: int, beats_per_bar: int = 4
) -> tuple[int, float]:
    """Pick the bar phase where harmony changes most for the given beats per bar."""
    if beat_count < DOWNBEAT_MIN_BARS * beats_per_bar or beat_chroma.shape[1] < 2:
        return 0, 0.0
    change = np.r_[0.0, np.linalg.norm(np.diff(beat_chroma, axis=1), axis=0)][:beat_count]
    # Median per bar position: real bar structure repeats; one odd beat should not decide.
    scores = [
        float(np.median(change[phase::beats_per_bar])) for phase in range(beats_per_bar)
    ]
    phase = int(np.argmax(scores))
    ordered = sorted(scores)
    confidence = (ordered[-1] - ordered[-2]) / ordered[-1] if ordered[-1] > 1e-12 else 0.0
    if confidence < DOWNBEAT_MIN_EVIDENCE:
        # No harmonic evidence for any bar phase: default to the first beat.
        return 0, round(max(0.0, confidence), 4)
    return phase, round(min(1.0, confidence), 4)


def _checkerboard_novelty(recurrence: FloatArray, half_width: int) -> FloatArray:
    size = 2 * half_width
    positions = np.arange(size, dtype=np.float64) - (size - 1) / 2.0
    taper = np.exp(-0.5 * (positions / (half_width / 2.0)) ** 2)
    signs = np.kron(np.array([[1.0, -1.0], [-1.0, 1.0]]), np.ones((half_width, half_width)))
    kernel = signs * np.outer(taper, taper)
    padded = np.pad(recurrence, half_width)
    count = recurrence.shape[0]
    return np.array(
        [float(np.sum(padded[i:i + size, i:i + size] * kernel)) for i in range(count)],
        dtype=np.float64,
    )


def _section_recurrence_novelty(features: FloatArray) -> FloatArray:
    """Compute self-similarity novelty only when its dense matrix is bounded."""
    beat_count = features.shape[1]
    if beat_count > MAX_SECTION_RECURRENCE_BEATS:
        return np.zeros(beat_count, dtype=np.float64)
    recurrence = np.asarray(
        librosa.segment.recurrence_matrix(features, mode="affinity", sym=True, width=3),
        dtype=np.float64,
    )
    return np.maximum(_checkerboard_novelty(recurrence, SECTION_KERNEL_BEATS), 0.0)


def _structural_sections(
    samples: npt.NDArray[np.float32],
    beat_frames: IntArray,
    beat_chroma: FloatArray,
    downbeat_indices: IntArray,
) -> list[tuple[int, float]]:
    """Return (beat index, score) for structural change candidates at downbeats."""
    beat_count = len(beat_frames)
    if beat_count < SECTION_KERNEL_BEATS * 2 or downbeat_indices.size < 3:
        return []
    mfcc = librosa.feature.mfcc(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH, n_mfcc=13)
    features = np.vstack([
        np.asarray(librosa.util.normalize(beat_chroma, axis=0), dtype=np.float64),
        np.asarray(
            librosa.util.normalize(_beat_sync(mfcc, beat_frames), axis=1),
            dtype=np.float64,
        ),
    ])
    novelty = _section_recurrence_novelty(features)[:beat_count]
    rms = np.asarray(librosa.feature.rms(y=samples, hop_length=HOP_LENGTH), dtype=np.float64)
    loudness = _beat_sync(np.log1p(rms * 100.0), beat_frames)[0]
    loudness_change = np.zeros(beat_count, dtype=np.float64)
    span = min(SECTION_LOUDNESS_SPAN_BEATS, loudness.size // 2)
    if span > 0 and loudness.size > 2 * span:
        delta = np.abs(loudness[2 * span:] - loudness[:-2 * span])
        loudness_change[span:span + delta.size] = delta[: beat_count - span]
    score = novelty / (float(np.percentile(novelty, 95)) + 1e-12)
    score = score + loudness_change / (float(np.percentile(loudness_change, 95)) + 1e-12)
    candidate_scores = score[downbeat_indices]
    # Only strict local maxima can be boundaries; then keep the strongest peaks
    # at least SECTION_MIN_SPACING_BARS apart.
    padded = np.r_[-np.inf, candidate_scores, -np.inf]
    peaks = [
        i for i in range(len(candidate_scores))
        if candidate_scores[i] >= SECTION_THRESHOLD
        and padded[i + 1] > padded[i] and padded[i + 1] >= padded[i + 2]
    ]
    chosen: list[int] = []
    for position in sorted(peaks, key=lambda i: (-candidate_scores[i], i)):
        if all(abs(position - other) >= SECTION_MIN_SPACING_BARS for other in chosen):
            chosen.append(position)
    chosen.sort()
    return [
        (int(downbeat_indices[position]), float(candidate_scores[position]))
        for position in chosen
    ]


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

def _svg_plot(
    stream: IO[str],
    duration: float,
    energy: list[dict[str, Any]],
    beats: list[float],
    downbeats: list[float],
    onsets: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    stops: list[dict[str, Any]],
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
    for downbeat in downbeats:
        x = left + downbeat / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#7048e8" stroke-width="2" opacity=".65"/>')
    for onset in onsets:
        x = left + onset["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top+plot_height-12}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#d97706"/>')
    for section in sections:
        x = left + section["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#0c8599" stroke-dasharray="4 4"/>')
    for stop in stops:
        x = left + stop["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#c92a2a" stroke-width="2"/>')
    for tick in range(0, math.ceil(duration) + 1, max(1, math.ceil(duration / 12))):
        x = left + tick / duration * plot_width
        parts.append(f'<text x="{x:.1f}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="11">{tick}s</text>')
    parts.extend([
        '<text x="70" y="500" font-family="sans-serif" font-size="11">Blue: RMS energy | Green: beats | Purple: downbeats | Amber: onsets | Teal: section candidates | Red: hard stops</text>',
        '</svg>',
    ])
    # Write through the NamedTemporaryFile handle; never close and reopen a
    # reserved path in a potentially shared output directory.
    stream.write("\n".join(parts))
    stream.flush()
    os.fsync(stream.fileno())


def _phrase_boundaries(downbeats: list[float], bar_confidence: float) -> list[dict[str, Any]]:
    return [
        {
            "time": time,
            "kind": "estimated_4_bar_phrase",
            "confidence": round(0.5 * bar_confidence, 4),
            "basis": "every fourth detected downbeat; not semantic phrase detection",
            "method": "four_bar_grouping_of_detected_downbeats",
        }
        for time in downbeats[::4]
    ]


def _merge_sections(
    structural: list[dict[str, Any]], energy: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(structural)
    for candidate in energy:
        if all(abs(candidate["time"] - other["time"]) >= 4.0 for other in structural):
            merged.append(candidate)
    return sorted(merged, key=lambda item: item["time"])


def _library_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def analyze_audio(
    audio_path: str | Path,
    json_output: str | Path,
    plot_output: str | Path,
    min_bpm: int = MIN_BPM,
    max_bpm: int = MAX_BPM,
    beats_per_bar: int = 4,
    input_demuxer: str | None = None,
    vocals_path: str | Path | None = None,
) -> dict[str, Any]:
    """Analyze audio and write a versioned JSON report and an SVG diagnostic plot.

    With ``vocals_path`` (a vocals-only track of the same song), beats in
    singer-led stretches are placed with the singer's help (see vocal_beats.py).
    """
    source = Path(audio_path)
    json_path = Path(json_output)
    plot_path = Path(plot_output)
    try:
        if not 30 <= min_bpm < max_bpm <= 300:
            raise AudioAnalysisError("Tempo bounds must satisfy 30 <= min BPM < max BPM <= 300")
        if beats_per_bar not in SUPPORTED_BEATS_PER_BAR:
            raise AudioAnalysisError("Beats per bar must be 3 or 4")
        if input_demuxer is not None and input_demuxer not in INPUT_DEMUXERS.values():
            raise AudioAnalysisError("Unsupported explicit audio container")
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
            ffmpeg_version = _normalize(source, normalized, input_demuxer)
            samples, duration = _read_samples(normalized)

        rms = _frame_rms(samples)
        envelope = _onset_envelope(samples)
        onsets = _detect_onsets(envelope)
        high_hits = _high_hits(samples)
        bpm, beat_frames, tempo_stability, beat_contrast = _track_beats(
            envelope, min_bpm, max_bpm
        )
        guidance: dict[str, Any] | None = None
        guided: list[tuple[float, float]] = []
        if vocals_path is not None and bpm is not None:
            from lor_sequence_builder.vocal_beats import vocal_guided_beats
            from lor_sequence_builder.vocals import vocal_events

            vocal_samples, vocal_duration = decode_audio(vocals_path)
            events = vocal_events(vocal_samples, vocal_duration)
            beat_frames, guided = vocal_guided_beats(
                envelope, vocal_samples, beat_frames, bpm, events["regions"]
            )
            guidance = {
                "source": Path(vocals_path).name,
                "method": "vocal-guided dynamic-tempo beat tracking in singer-led stretches",
                "stretches": [{"start": a, "end": b} for a, b in guided],
            }
        beat_times = [round(float(t), 3) for t in _frames_to_times(beat_frames)]
        beat_confidence = round(beat_contrast, 4)

        downbeats: list[float] = []
        bar_confidence = 0.0
        structural: list[dict[str, Any]] = []
        if bpm is not None and len(beat_times) >= 2 * beats_per_bar:
            beat_chroma = _beat_chroma(samples, beat_frames)
            phase, bar_confidence = _downbeat_phase(beat_chroma, len(beat_times), beats_per_bar)
            downbeat_indices = np.arange(phase, len(beat_times), beats_per_bar, dtype=np.int64)
            downbeats = [beat_times[int(i)] for i in downbeat_indices]
            for beat_index, score in _structural_sections(
                samples, beat_frames, beat_chroma, downbeat_indices
            ):
                structural.append({
                    "time": beat_times[beat_index],
                    "kind": "structural_change_candidate",
                    "relative_change": round(score, 4),
                    "confidence": round(min(0.75, 0.25 + 0.15 * score), 3),
                    "label": None,
                    "method": "self_similarity_novelty_plus_loudness_change_at_downbeats",
                })

        energy = _energy_curve(rms)
        minimum_stop_silence = max(0.75, (60.0 / bpm) * 1.5) if bpm else 0.75
        stops = _hard_stops(rms, minimum_stop_silence)
        phrases = _phrase_boundaries(downbeats, bar_confidence)
        sections = _merge_sections(structural, _section_candidates(energy))
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
            "tool_versions": {
                "analyzer_schema": ANALYSIS_SCHEMA_VERSION,
                "ffmpeg": ffmpeg_version,
                "python": platform.python_version(),
                "librosa": _library_version("librosa"),
                "numpy": _library_version("numpy"),
            },
            "configuration": {
                "frame_seconds": FRAME_SECONDS,
                "hop_length": HOP_LENGTH,
                "minimum_bpm": min_bpm,
                "maximum_bpm": max_bpm,
                "beats_per_bar": beats_per_bar,
                "minimum_duration_seconds": MIN_DURATION_SECONDS,
                "maximum_duration_seconds": MAX_DURATION_SECONDS,
                "maximum_input_bytes": MAX_INPUT_BYTES,
                "confidence_values": "heuristic and uncalibrated",
            },
            "analysis": {
                "method": "FFmpeg normalization + librosa onset, beat, chroma, and self-similarity analysis",
                "provenance": (
                    f"All timestamps are relative to the decoded audio stream start; spectral "
                    f"features use {HOP_LENGTH}-sample hops and energy frames use "
                    f"{FRAME_SAMPLES}-sample windows at {SAMPLE_RATE} Hz."
                ),
                "limitations": [
                    "Beat tracking assumes one dominant tempo; tempo stability reports how much of the song agrees with it.",
                    "Half-time and double-time readings describe the same pulse and cannot always be told apart.",
                    "Downbeats use the configured beats per bar (3 or 4, default 4; meter is not detected) and choose the bar phase where harmony changes most.",
                    "Phrase boundaries group every four detected bars; they are not semantic phrase detection.",
                    "Section candidates are structural or energy changes; verse/chorus labels are not inferred, and section placement is partly a matter of taste.",
                    "Hard stops are sustained near-silence candidates and may include intentional pauses.",
                    "Vocals are not separated or detected.",
                ],
                "tempo": {
                    "bpm": bpm,
                    "confidence": tempo_stability,
                    "method": "librosa_global_tempo_with_local_tempo_agreement",
                },
                "beats": [
                    {"time": value, "confidence": beat_confidence,
                     "method": (
                         "vocal_guided_dynamic_tempo_beat_tracker"
                         if any(a <= value < b for a, b in guided)
                         else "librosa_dynamic_programming_beat_tracker"
                     )}
                    for value in beat_times
                ],
                "downbeats": [
                    {"time": value, "confidence": bar_confidence,
                     "method": "bar_phase_from_beat_synchronous_chroma_change"}
                    for value in downbeats
                ],
                "onsets": onsets,
                "high_hits": high_hits,
                "crashes": _crashes(samples, high_hits),
                "tempo_curve": _tempo_curve(envelope, bpm),
                "energy": energy,
                "phrase_boundaries": phrases,
                "section_candidates": sections,
                "hard_stops": stops,
                **({"beat_guidance": guidance} if guidance is not None else {}),
            },
        }
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        # Build both artifacts beside their destinations, then publish with
        # atomic no-overwrite links. If either publication fails, remove the
        # other so callers never receive a half-published report/plot pair.
        json_temp: Path | None = None
        plot_temp: Path | None = None
        json_published = False
        plot_published = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=json_path.parent,
                prefix=f".{json_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                json_temp = Path(stream.name)
                stream.write(serialized)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=plot_path.parent,
                prefix=f".{plot_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                plot_temp = Path(stream.name)
                _svg_plot(stream.file, duration, energy, beat_times, downbeats, onsets, sections, stops)
            os.link(json_temp, json_path)
            json_published = True
            os.link(plot_temp, plot_path)
            plot_published = True
        except FileExistsError as exc:
            raise AudioAnalysisError("Refusing to overwrite an existing analysis output") from exc
        finally:
            if json_temp is not None:
                json_temp.unlink(missing_ok=True)
            if plot_temp is not None:
                plot_temp.unlink(missing_ok=True)
            if json_published and not plot_published:
                json_path.unlink(missing_ok=True)
        return report
    except OSError as exc:
        raise AudioAnalysisError(f"Audio analysis I/O failure: {exc}") from exc


def decode_audio(audio_path: str | Path) -> tuple[npt.NDArray[np.float32], float]:
    """Decode any supported audio file to mono samples at SAMPLE_RATE, with its duration."""
    source = Path(audio_path)
    if not source.is_file():
        raise AudioAnalysisError(f"Audio input is not a regular file: {source}")
    size = source.stat().st_size
    if size <= 0 or size > MAX_INPUT_BYTES:
        raise AudioAnalysisError("Audio file must be non-empty and no larger than 200 MiB")
    with tempfile.TemporaryDirectory(prefix="lor-decode-") as folder:
        normalized = Path(folder) / "normalized.wav"
        _normalize(source, normalized)
        return _read_samples(normalized)
