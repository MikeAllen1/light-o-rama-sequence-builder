"""An invented pop song with a known form, synthesized for tests: verses, choruses
and a bridge that differ in chords, sound and loudness, as real songs' parts do."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

BEAT = 0.5  # 120 BPM, so a bar is two seconds
NOTES = {"C": 261.63, "D": 293.66, "Eb": 311.13, "E": 329.63, "F": 349.23, "G": 392.0,
         "Ab": 415.3, "A": 440.0, "Bb": 466.16, "B": 493.88}
CHORDS = {"C": ("C", "E", "G"), "Am": ("A", "C", "E"), "F": ("F", "A", "C"),
          "G": ("G", "B", "D"), "Dm": ("D", "F", "A"), "Em": ("E", "G", "B"),
          "Eb": ("Eb", "G", "Bb"), "Bb": ("Bb", "D", "F"), "Ab": ("Ab", "C", "Eb")}
# (part, bars, chords cycled bar by bar, loudness, drums)
FORM = (
    ("intro", 4, ("C", "G"), 0.25, False),
    ("verse", 8, ("Am", "F", "C", "G"), 0.45, True),
    ("chorus", 8, ("F", "G", "C", "C"), 0.9, True),
    ("verse", 8, ("Am", "F", "C", "G"), 0.45, True),
    ("chorus", 8, ("F", "G", "C", "C"), 0.9, True),
    ("bridge", 8, ("Eb", "Bb", "Ab", "Bb"), 0.6, False),
    ("chorus", 8, ("F", "G", "C", "C"), 1.0, True),
    ("outro", 4, ("C", "C"), 0.3, False),
)


def part_starts() -> list[tuple[str, float]]:
    starts, bar = [], 0
    for name, bars, *_ in FORM:
        starts.append((name, bar * 4 * BEAT))
        bar += bars
    return starts


def write_song(path: Path) -> None:
    rate = 22050
    total = sum(bars for _, bars, *_ in FORM)
    samples = np.zeros(int(rate * BEAT * 4 * total) + rate)
    rng = np.random.default_rng(7)
    t_kick = np.arange(int(0.15 * rate)) / rate
    kick = np.sin(2 * np.pi * (60 + 60 * np.exp(-t_kick * 30)) * t_kick) * np.exp(-t_kick * 25)
    t_hat = np.arange(int(0.05 * rate)) / rate
    hat = rng.standard_normal(t_hat.size) * np.exp(-t_hat * 80)
    bar_length = int(4 * BEAT * rate)
    t = np.arange(bar_length) / rate
    bar = 0
    for name, bars, chords, loud, drums in FORM:
        for k in range(bars):
            start = bar * bar_length
            chord = CHORDS[chords[k % len(chords)]]
            tone = np.zeros(bar_length)
            for note in chord:
                f = NOTES[note]
                tone += np.sin(2 * np.pi * f * t)
                if name in {"chorus"}:  # a brighter sound in the choruses
                    tone += 0.5 * np.sin(2 * np.pi * 2 * f * t) + 0.3 * np.sin(2 * np.pi * 3 * f * t)
            bass = np.sin(2 * np.pi * NOTES[chord[0]] / 2 * t)
            samples[start:start + bar_length] += loud * (0.12 * tone + 0.15 * bass)
            for b in range(8):
                # The band keeps time throughout; the kick drum plays only in the
                # verses and choruses.
                at = start + int(b * BEAT / 2 * rate)
                if drums and b % 4 == 0:
                    samples[at:at + kick.size] += loud * 0.9 * kick
                samples[at:at + hat.size] += loud * (0.15 if drums else 0.25) * hat
            bar += 1
    samples = samples / np.max(np.abs(samples)) * 0.8
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((samples * 32767).astype("<i2").tobytes())
