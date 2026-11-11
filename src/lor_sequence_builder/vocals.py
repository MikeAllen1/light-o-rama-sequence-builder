"""Find where someone is singing, and where each syllable lands, in a vocals-only track.

The input is an isolated vocal track: one the user supplies, or one split out of
the song by the optional separation add-on (``vocal_separation.py``). Working
on vocals alone is what makes this tractable; in a full mix the drums and
instruments would drown out the voice.

- Vocal regions are stretches where the voice is clearly present, measured
  against the track's own loud parts. Short gaps (breaths) are bridged and
  very short blips (bleed from other instruments) are dropped.
- Syllables are vocal onsets inside those regions. Each lasts until the next
  syllable or until the voice fades, and carries a strength from its loudness
  so the planner can open the mouth wider on stronger syllables.

Everything is a heuristic over loudness and onsets; there is no speech or
lyric recognition. The report says so.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from lor_sequence_builder.artifacts import write_new_text_atomically
from lor_sequence_builder.audio_analysis import SAMPLE_RATE, AudioAnalysisError, decode_audio

VOCALS_SCHEMA_VERSION = "vocals-1.0"
HOP = 512
FRAME = 2048
# Voice counts as present at this fraction of the track's loud level (about -24 dB).
PRESENCE = 0.063
BRIDGE_SECONDS = 0.35
MIN_REGION_SECONDS = 0.3
MIN_SYLLABLE_SECONDS = 0.08
# Between syllables the voice falls below this share of the previous peak.
DIP = 0.55
# A syllable reaches at least this share of the track's loud level.
ONSET_LEVEL = 0.2
MAX_SYLLABLE_SECONDS = 1.5


class VocalAnalysisError(ValueError):
    """Raised when a vocal track cannot be analyzed."""


def _regions(active: np.ndarray, times: np.ndarray, duration: float) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    start: float | None = None
    step = HOP / SAMPLE_RATE
    for flag, time in zip(active, times, strict=True):
        if flag and start is None:
            start = float(time)
        elif not flag and start is not None:
            spans.append((start, float(time)))
            start = None
    if start is not None:
        spans.append((start, duration))
    bridged: list[tuple[float, float]] = []
    for a, b in spans:
        if bridged and a - bridged[-1][1] <= BRIDGE_SECONDS:
            bridged[-1] = (bridged[-1][0], b)
        else:
            bridged.append((a, b))
    return [(a, min(duration, b + step)) for a, b in bridged if b - a >= MIN_REGION_SECONDS]


def vocal_events(samples: np.ndarray, duration: float) -> dict[str, Any]:
    """Vocal regions and syllables from vocals-only samples at SAMPLE_RATE."""
    if samples.size < FRAME:
        return {"regions": [], "syllables": []}
    rms = librosa.feature.rms(y=samples, frame_length=FRAME, hop_length=HOP)[0]
    times = librosa.frames_to_time(np.arange(rms.size), sr=SAMPLE_RATE, hop_length=HOP)
    loud = float(np.percentile(rms, 95))
    if loud <= 1e-4:
        return {"regions": [], "syllables": []}
    floor = loud * PRESENCE
    smoothed = np.convolve(rms, np.ones(3) / 3, mode="same")
    regions = _regions(smoothed > floor, times, duration)

    envelope = librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE, hop_length=HOP)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=envelope, sr=SAMPLE_RATE, hop_length=HOP, backtrack=True, units="frames"
    )
    onset_times = [float(t) for t in librosa.frames_to_time(onset_frames, sr=SAMPLE_RATE,
                                                            hop_length=HOP)]
    syllables: list[dict[str, float]] = []
    for start, end in regions:
        candidates = sorted(t for t in onset_times if start < t < end - MIN_SYLLABLE_SECONDS)
        merged: list[float] = [start]
        for t in candidates:
            if t - merged[-1] < MIN_SYLLABLE_SECONDS:
                continue
            # A new syllable needs the voice to dip first; onsets inside one held
            # note (vibrato, a change of vowel color) do not count.
            a = int(merged[-1] * SAMPLE_RATE / HOP)
            b = max(a + 1, int(t * SAMPLE_RATE / HOP) + 1)
            span = rms[a:b]
            peak_at = int(np.argmax(span))
            ahead = rms[b - 1:b - 1 + int(0.12 * SAMPLE_RATE / HOP) + 1]
            # ...and it has to be a real note, not a flicker in a fading tail.
            if span[peak_at:].min() <= DIP * span[peak_at] and ahead.size and \
                    float(ahead.max()) >= ONSET_LEVEL * loud:
                merged.append(t)
        for index, s in enumerate(merged):
            limit = merged[index + 1] if index + 1 < len(merged) else end
            first = int(s * SAMPLE_RATE / HOP)
            last = max(first + 1, int(limit * SAMPLE_RATE / HOP))
            segment = rms[first:last]
            if segment.size == 0:
                continue
            peak = float(segment.max())
            # The syllable holds until the voice falls to half its peak.
            below = np.nonzero(segment[int(np.argmax(segment)):] < peak * 0.5)[0]
            stop = limit
            if below.size:
                stop = min(limit, s + (int(np.argmax(segment)) + int(below[0])) * HOP / SAMPLE_RATE)
            stop = min(stop, s + MAX_SYLLABLE_SECONDS)
            if stop - s < MIN_SYLLABLE_SECONDS:
                stop = min(limit, s + MIN_SYLLABLE_SECONDS)
            syllables.append({
                "start": round(s, 3),
                "end": round(stop, 3),
                "strength": round(min(1.0, peak / loud), 3),
            })
    return {
        "regions": [{"start": round(a, 3), "end": round(b, 3)} for a, b in regions],
        "syllables": syllables,
    }


def analyze_vocals(vocal_path: str | Path, json_output: str | Path, source: str) -> dict[str, Any]:
    """Analyze a vocals-only track and write a versioned JSON report (never overwriting)."""
    output = Path(json_output)
    if output.exists():
        raise VocalAnalysisError(f"Refusing to overwrite an existing vocal analysis: {output}")
    try:
        samples, duration = decode_audio(vocal_path)
    except AudioAnalysisError as exc:
        raise VocalAnalysisError(str(exc)) from exc
    events = vocal_events(samples, duration)
    report = {
        "schema_version": VOCALS_SCHEMA_VERSION,
        "source": source,
        "file_name": Path(vocal_path).name,
        "duration_seconds": round(duration, 3),
        "method": "loudness presence and onset detection on a vocals-only track",
        "limitations": [
            "Regions and syllables come from loudness and onsets; words are not recognized.",
            ("Separated vocals can carry bleed from other instruments, which may add short "
            "false syllables."),
        ],
        **events,
    }
    try:
        write_new_text_atomically(output, json.dumps(report, indent=2) + "\n")
    except OSError as exc:
        raise VocalAnalysisError(f"Cannot write vocal analysis: {output}") from exc
    return report


MAX_VOCALS_JSON_BYTES = 5 * 1024 * 1024
MAX_VOCAL_EVENTS = 100_000


def load_vocals(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_VOCALS_JSON_BYTES:
            raise VocalAnalysisError("Vocal analysis JSON exceeds the 5 MiB limit")
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VocalAnalysisError(f"Cannot read vocal analysis: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != VOCALS_SCHEMA_VERSION:
        raise VocalAnalysisError(f"Unsupported vocal analysis; expected {VOCALS_SCHEMA_VERSION}")
    duration = data.get("duration_seconds")
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(float(duration)) or not 0 < float(duration) <= 1800):
        raise VocalAnalysisError("Vocal analysis has an invalid duration_seconds value")
    for key in ("regions", "syllables"):
        events = data.get(key)
        if not isinstance(events, list) or len(events) > MAX_VOCAL_EVENTS:
            raise VocalAnalysisError(
                f"Vocal analysis field {key!r} must be a list of at most "
                f"{MAX_VOCAL_EVENTS} events"
            )
        for event in events:
            if not isinstance(event, dict):
                raise VocalAnalysisError(f"Vocal analysis field {key!r} contains a non-object")
            start, end = event.get("start"), event.get("end")
            if (isinstance(start, bool) or isinstance(end, bool)
                    or not isinstance(start, int | float) or not isinstance(end, int | float)
                    or not math.isfinite(float(start)) or not math.isfinite(float(end))
                    or start < 0 or end <= start or end > float(duration) + 1):
                raise VocalAnalysisError(
                    f"Vocal analysis field {key!r} contains invalid event boundaries"
                )
            if key == "syllables":
                strength = event.get("strength")
                if (isinstance(strength, bool) or not isinstance(strength, int | float)
                        or not math.isfinite(float(strength)) or not 0 <= strength <= 1):
                    raise VocalAnalysisError("Vocal syllable strength must be between 0 and 1")
    return data
