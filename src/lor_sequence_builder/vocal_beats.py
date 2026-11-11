"""Vocal-guided beat placement for stretches where the band follows the singer.

The Phase 4 beat tracker assumes one steady tempo and listens to the full mix.
In rubato or loosely swung, singer-led passages the drums drop out or wander,
and onsets in the mix cannot separate beats from swung notes. The singer's
note onsets can: in those passages the band places its beats where the singer
places the words.

How it works:

1. Blend the mix's onset strength with the vocals' onset strength.
2. Estimate the tempo frame by frame from that blend, folded to the same
   octave as the song's tempo and smoothed over a few seconds, so it can drift
   with the singer but not jump.
3. Track beats on the blend with that drifting tempo.
4. Only inside passages where someone is singing, compare the original and
   the vocal-guided beats window by window. Use the vocal-guided beats only
   where they line up with the music better (higher on-beat versus off-beat
   contrast). Everywhere else the original beats stay exactly as they were, so
   steady songs are not changed.
"""

from __future__ import annotations

import itertools
from typing import Any

import librosa
import numpy as np
import numpy.typing as npt

from lor_sequence_builder.audio_analysis import HOP_LENGTH, SAMPLE_RATE

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

VOCAL_WEIGHT = 1.0
TEMPO_SMOOTHING_SECONDS = 3.0
# Breaths and short pauses inside one sung passage.
PASSAGE_GAP_SECONDS = 4.0
WINDOW_SECONDS = 6.0
WINDOW_STEP_SECONDS = 1.5
# Vocal-guided beats must line up better than the original by at least this much.
MARGIN = 0.02


def _times(frames: IntArray) -> FloatArray:
    return np.asarray(librosa.frames_to_time(frames, sr=SAMPLE_RATE, hop_length=HOP_LENGTH),
                      dtype=np.float64)


def _contrast(times: FloatArray, envelope: FloatArray, start: float, end: float) -> float:
    frames = [int(t * SAMPLE_RATE / HOP_LENGTH) for t in times if start <= t < end]
    frames = [f for f in frames if f < envelope.size]
    if len(frames) < 3:
        return -1.0
    on = float(np.mean(envelope[frames]))
    middles = [(a + b) // 2 for a, b in itertools.pairwise(frames)]
    off = float(np.mean(envelope[middles]))
    return (on - off) / (on + off + 1e-12)


def _passages(regions: list[dict[str, Any]]) -> list[tuple[float, float]]:
    passages: list[tuple[float, float]] = []
    for region in regions:
        start, end = float(region["start"]), float(region["end"])
        if passages and start - passages[-1][1] < PASSAGE_GAP_SECONDS:
            passages[-1] = (passages[-1][0], end)
        else:
            passages.append((start, end))
    return passages


def vocal_guided_beats(
    mix_envelope: FloatArray,
    vocal_samples: npt.NDArray[np.float32],
    beat_frames: IntArray,
    bpm: float,
    vocal_regions: list[dict[str, Any]],
) -> tuple[IntArray, list[tuple[float, float]]]:
    """Return beat frames with singer-led stretches re-placed, and those stretches."""
    if beat_frames.size < 4 or not vocal_regions or bpm <= 0:
        return beat_frames, []
    vocal_envelope = np.asarray(
        librosa.onset.onset_strength(y=vocal_samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH),
        dtype=np.float64,
    )
    size = min(mix_envelope.size, vocal_envelope.size)
    if size < 16:
        return beat_frames, []
    mix = mix_envelope[:size]
    voice = vocal_envelope[:size]
    blend = (mix / (np.percentile(mix, 95) + 1e-9)
             + VOCAL_WEIGHT * voice / (np.percentile(voice, 95) + 1e-9))

    local = np.asarray(
        librosa.feature.tempo(onset_envelope=blend, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
                              aggregate=None, max_tempo=float(max(200.0, bpm * 1.5))),
        dtype=np.float64,
    )[:size]
    local = np.where(np.isfinite(local) & (local > 0), local, bpm)
    # Fold every estimate into the song's own tempo octave, then smooth.
    while np.any(local > bpm * 1.41):
        local = np.where(local > bpm * 1.41, local / 2, local)
    while np.any(local < bpm / 1.41):
        local = np.where(local < bpm / 1.41, local * 2, local)
    width = int(TEMPO_SMOOTHING_SECONDS * SAMPLE_RATE / HOP_LENGTH) | 1
    padded = np.pad(local, width // 2, mode="edge")
    local = np.median(np.lib.stride_tricks.sliding_window_view(padded, width), axis=1)
    if local.size < size:
        local = np.pad(local, (0, size - local.size), mode="edge")

    _, guided_any = librosa.beat.beat_track(
        onset_envelope=blend, sr=SAMPLE_RATE, hop_length=HOP_LENGTH, bpm=local,
        units="frames", trim=False,
    )
    guided = np.asarray(guided_any, dtype=np.int64)
    original_times = _times(beat_frames)
    guided_times = _times(guided)

    chosen: list[tuple[float, float]] = []
    for start, end in _passages(vocal_regions):
        cursor = start
        while cursor < end:
            stop = min(end, cursor + WINDOW_SECONDS)
            if (_contrast(guided_times, blend, cursor, stop)
                    > _contrast(original_times, blend, cursor, stop) + MARGIN):
                if chosen and cursor <= chosen[-1][1]:
                    chosen[-1] = (chosen[-1][0], max(chosen[-1][1], stop))
                else:
                    chosen.append((cursor, stop))
            cursor += WINDOW_STEP_SECONDS
    if not chosen:
        return beat_frames, []

    def inside(t: float) -> bool:
        return any(a <= t < b for a, b in chosen)

    kept = [f for f, t in zip(beat_frames, original_times, strict=True) if not inside(t)]
    added = [f for f, t in zip(guided, guided_times, strict=True) if inside(t)]
    merged = np.asarray(sorted({int(f) for f in (*kept, *added)}), dtype=np.int64)
    # Drop a beat that lands too close to its neighbor where the two grids meet.
    period = 60.0 / bpm * SAMPLE_RATE / HOP_LENGTH
    cleaned = [int(merged[0])]
    for frame in merged[1:]:
        if frame - cleaned[-1] >= 0.4 * period:
            cleaned.append(int(frame))
    return np.asarray(cleaned, dtype=np.int64), [(round(a, 3), round(b, 3)) for a, b in chosen]
