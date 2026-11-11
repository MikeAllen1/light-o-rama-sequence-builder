"""A fictional singer-led song with known beat times, for beat-placement tests.

Steady drums open and close the song. In the middle, the drums drop out and the
band follows the singer: the tempo drifts slowly (like rubato), only soft chords
mark the beats, and the voice sings on most beats plus some swung offbeats.
Every beat time is known exactly, so placement can be scored.
"""

from __future__ import annotations

import numpy as np

RATE = 22_050


def beat_times(duration: float = 70.0, singer_led: bool = True
               ) -> tuple[list[float], tuple[float, float]]:
    """Return every true beat time, and the (start, end) of the singer-led middle."""
    times = [0.5]
    middle = (20.0, 50.0)
    while times[-1] < duration - 1.0:
        t = times[-1]
        if singer_led and middle[0] <= t < middle[1]:
            # 110 BPM drifting down to about 88 and back up, smoothly.
            phase = (t - middle[0]) / (middle[1] - middle[0])
            bpm = 110 - 22 * np.sin(np.pi * phase)
        else:
            bpm = 110.0
        times.append(t + 60.0 / bpm)
    return times, middle


def _tone(freq: float, length: float, level: float) -> np.ndarray:
    t = np.arange(int(length * RATE)) / RATE
    wave = sum(np.sin(2 * np.pi * freq * k * t) / k for k in (1, 2, 3))
    return level * wave * np.exp(-t / (length / 2.5))


def render(duration: float = 70.0, seed: int = 5, singer_led: bool = True
           ) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """(full mix, vocals only, true beat times). With ``singer_led=False`` the drums
    and tempo stay steady all song while the voice still sings in the middle."""
    rng = np.random.default_rng(seed)
    beats, (start, end) = beat_times(duration, singer_led)
    mix = rng.normal(0, 0.003, int(duration * RATE))
    voice = np.zeros_like(mix)

    def add(target: np.ndarray, at: float, sound: np.ndarray) -> None:
        i = int(at * RATE)
        n = min(sound.size, target.size - i)
        if n > 0:
            target[i:i + n] += sound[:n]

    chords = (196.0, 220.0, 174.6, 246.9)
    for index, t in enumerate(beats):
        led_here = singer_led and start <= t < end
        gap = beats[index + 1] - t if index + 1 < len(beats) else 0.5
        if not led_here:
            n = int(0.12 * RATE)
            env = np.exp(-np.arange(n) / (0.02 * RATE))
            add(mix, t, 0.8 * env * np.sin(2 * np.pi * 55 * np.arange(n) / RATE))
            if index % 2:
                add(mix, t, 0.4 * env * rng.uniform(-1, 1, n))
            m = int(0.03 * RATE)
            add(mix, t + gap / 2, 0.12 * rng.uniform(-1, 1, m) * np.exp(-np.arange(m) / 100))
        else:
            # Soft chord on each beat, much quieter than the drums.
            add(mix, t, _tone(chords[(index // 4) % 4], gap * 0.9, 0.08))
        # The singer: most beats, sometimes a swung note two-thirds of the way through.
        if start - 4 <= t < end + 4 and rng.random() < 0.85:
            pitch = 330.0 * 2 ** (rng.integers(0, 7) / 12)
            length = gap * (0.62 if rng.random() < 0.3 else 0.85)
            add(voice, t, _vibrato(pitch, length, 0.35))
            if length < gap * 0.7:
                add(voice, t + gap * 0.67, _vibrato(pitch * 1.12, gap * 0.28, 0.3))
    mix += voice
    peak = max(1e-9, float(np.max(np.abs(mix))))
    return (mix / peak * 0.9).astype(np.float32), (voice / peak * 0.9).astype(np.float32), beats


def _vibrato(freq: float, length: float, level: float) -> np.ndarray:
    t = np.arange(int(length * RATE)) / RATE
    pitch = freq * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(pitch) / RATE
    wave = np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)
    envelope = np.minimum(1, t / 0.025) * np.minimum(1, (length - t) / 0.05)
    return np.asarray(level * wave * envelope, dtype=np.float64)
