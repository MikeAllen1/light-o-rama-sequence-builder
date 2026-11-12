"""Speed-ups that must not change results, and housekeeping that keeps the program quick."""

from __future__ import annotations

import os
import time
from pathlib import Path

import librosa
import numpy as np

from lor_sequence_builder import audio_analysis
from lor_sequence_builder.audio_analysis import (
    HIGH_BAND_HZ,
    HOP_LENGTH,
    SAMPLE_RATE,
    _high_hits,
    _onset_envelope,
    _Spectra,
)
from lor_sequence_builder.diagnostics import sweep_leftovers


def _music(seconds: float = 6.0) -> np.ndarray:
    rng = np.random.default_rng(7)
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    song = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.02 * rng.standard_normal(t.size)
    for beat in np.arange(0, seconds, 0.5):
        start = int(beat * SAMPLE_RATE)
        song[start:start + 600] += np.exp(-np.arange(600) / 90.0)[: song.size - start]
    return song.astype(np.float32)


def test_the_shared_spectrum_gives_exactly_what_librosa_gives() -> None:
    samples = _music()
    spectra = _Spectra(samples)
    direct = librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    assert np.array_equal(_onset_envelope(spectra), direct.astype(np.float64))
    high = librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH,
                                        fmin=HIGH_BAND_HZ, n_mels=32)
    shared = librosa.onset.onset_strength(S=spectra.log_mel(HIGH_BAND_HZ, 32), sr=SAMPLE_RATE,
                                          hop_length=HOP_LENGTH)
    assert np.array_equal(shared, high)
    assert _high_hits(spectra) == _high_hits(samples)
    mfcc = librosa.feature.mfcc(y=samples, sr=SAMPLE_RATE, hop_length=HOP_LENGTH, n_mfcc=13)
    assert np.allclose(librosa.feature.mfcc(S=spectra.log_mel(), sr=SAMPLE_RATE, n_mfcc=13), mfcc)
    assert spectra.mel() is spectra.mel()  # worked out once


def test_warm_up_runs_once_and_never_raises() -> None:
    audio_analysis._warmed.clear()
    assert audio_analysis.warm_up() is True
    started = time.perf_counter()
    assert audio_analysis.warm_up() is True
    assert time.perf_counter() - started < 0.01


def test_only_old_leftovers_of_this_program_are_swept(tmp_path: Path) -> None:
    old = tmp_path / "lor-new-show-abc"
    fresh = tmp_path / "lor-audio-xyz"
    other = tmp_path / "someone-elses-folder"
    for folder in (old, fresh, other):
        folder.mkdir()
        (folder / "file.txt").write_text("x", encoding="utf-8")
    day_ago = time.time() - 2 * 24 * 60 * 60
    os.utime(old, (day_ago, day_ago))
    os.utime(other, (day_ago, day_ago))
    assert sweep_leftovers(folder=tmp_path) == 1
    assert not old.exists() and fresh.exists() and other.exists()
    assert sweep_leftovers(folder=tmp_path / "missing") == 0
