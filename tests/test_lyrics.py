from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from lor_sequence_builder.audio_analysis import SAMPLE_RATE, _crashes, _high_hits, analyze_audio
from lor_sequence_builder.cli import main
from lor_sequence_builder.lyrics import (
    LyricsError,
    import_lyrics,
    parse_lyrics_text,
    transcribe_lyrics,
    write_lyrics,
)

LRC = "[ar:Fictional]\n[00:01.50]First line\n[00:04.00][00:20.00]Repeated chorus\n[00:08.25]Last\n"
SRT = """1
00:00:01,500 --> 00:00:03,200
First line

2
00:00:04,000 --> 00:00:06,000
<i>Second</i> line
"""
VTT = "WEBVTT\n\n00:01.500 --> 00:03.200\nFirst line\n\n00:04.000 --> 00:06.000\nSecond line\n"


def test_lrc_lines_get_their_times_and_repeats() -> None:
    doc = parse_lyrics_text(LRC, "song.lrc")
    starts = [(line["start"], line["text"]) for line in doc["lines"]]
    assert starts == [(1.5, "First line"), (4.0, "Repeated chorus"), (8.25, "Last"),
                      (20.0, "Repeated chorus")]
    assert doc["lines"][0]["end"] == 4.0  # runs until the next line
    assert all(line["verified"] for line in doc["lines"])  # the text is the user's own
    assert (doc["schema_version"], doc["source"], doc["origin"]) == (
        "lyrics-1.0", "imported", "lrc")


@pytest.mark.parametrize(("text", "origin"), [(SRT, "srt"), (VTT, "vtt")])
def test_srt_and_vtt_cues(text: str, origin: str) -> None:
    doc = parse_lyrics_text(text, "song")
    assert doc["origin"] == origin
    assert [(line["start"], line["end"], line["text"]) for line in doc["lines"]] == [
        (1.5, 3.2, "First line"), (4.0, 6.0, "Second line")]


def test_text_without_timing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LyricsError, match="no LRC time tags"):
        parse_lyrics_text("just words\nno times\n", "plain.txt")
    big = tmp_path / "big.lrc"
    big.write_text("[00:01.00]x\n" * 300_000, encoding="utf-8")
    with pytest.raises(LyricsError, match="2 MiB"):
        import_lyrics(big)


class FakeModel:
    """Stands in for the speech recognizer: two lines with word timings."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: np.ndarray, **options: Any) -> tuple[list[Any], None]:
        self.calls.append({"samples": audio.size, **options})

        def word(start: float, end: float, text: str, p: float) -> SimpleNamespace:
            return SimpleNamespace(start=start, end=end, word=" " + text, probability=p)

        return [
            SimpleNamespace(start=0.4, end=1.6, text=" Deck the halls",
                            words=[word(0.4, 0.7, "Deck", 0.9), word(0.7, 0.9, "the", 0.8),
                                   word(0.9, 1.6, "halls", 0.6)]),
            SimpleNamespace(start=2.0, end=2.8, text=" fa la la", words=[]),
        ], None


def _tone(path: Path, seconds: float = 3.0) -> Path:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    data = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(data.tobytes())
    return path


def test_transcribed_lyrics_are_never_presented_as_verified(tmp_path: Path) -> None:
    model = FakeModel()
    doc = transcribe_lyrics(_tone(tmp_path / "vocals.wav"), "base.en", model=model)
    assert model.calls[0]["word_timestamps"] is True
    assert model.calls[0]["samples"] == 3 * 16_000
    assert doc["source"] == "transcribed" and doc["model"] == "base.en"
    assert [line["text"] for line in doc["lines"]] == ["Deck the halls", "fa la la"]
    assert all(not line["verified"] for line in doc["lines"])
    words = doc["lines"][0]["words"]
    assert [(w["text"], w["start"], w["verified"]) for w in words] == [
        ("Deck", 0.4, False), ("the", 0.7, False), ("halls", 0.9, False)]
    assert any("mishears" in item for item in doc["limitations"])
    path = write_lyrics(doc, tmp_path / "song.lyrics.json")
    assert json.loads(path.read_text(encoding="utf-8"))["lines"][1]["text"] == "fa la la"
    with pytest.raises(LyricsError, match="overwrite"):
        write_lyrics(doc, path)


def test_transcription_explains_the_add_on(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lor_sequence_builder.lyrics.transcription_available", lambda: False)
    with pytest.raises(LyricsError, match="uv sync --extra lyrics"):
        transcribe_lyrics(_tone(tmp_path / "v.wav"))


def test_cli_imports_lyrics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "song.lrc"
    source.write_text(LRC, encoding="utf-8")
    assert main(["lyrics", "--import", str(source), "--output",
                 str(tmp_path / "song.lyrics.json")]) == 0
    assert "Lyric lines: 4 (imported)" in capsys.readouterr().out
    plain = tmp_path / "plain.txt"
    plain.write_text("no timing", encoding="utf-8")
    assert main(["lyrics", "--import", str(plain), "--output", str(tmp_path / "x.json")]) == 2


def _burst(length: float, ring: float, rng: np.random.Generator) -> np.ndarray:
    """High-passed noise burst: a short decay is a hi-hat, a long one a crash."""
    n = int(length * SAMPLE_RATE)
    noise = rng.uniform(-1, 1, n)
    noise = np.diff(np.diff(noise, prepend=0), prepend=0)  # tilt toward high frequencies
    envelope = np.exp(-np.arange(n) / (ring * SAMPLE_RATE))
    return np.asarray(noise * envelope, dtype=np.float64)


def test_crashes_ring_on_and_hi_hats_do_not() -> None:
    rng = np.random.default_rng(4)
    song = np.zeros(int(12 * SAMPLE_RATE))
    for i in range(48):  # a hi-hat on every eighth note
        start = int((0.25 * i) * SAMPLE_RATE)
        hat = _burst(0.08, 0.015, rng) * 0.3
        song[start:start + hat.size] += hat
    for at in (3.0, 9.0):  # two crashes
        start = int(at * SAMPLE_RATE)
        crash = _burst(2.0, 0.9, rng) * 0.9
        song[start:start + crash.size] += crash[: song.size - start]
    samples = np.asarray(song / np.max(np.abs(song)), dtype=np.float32)
    hits = _high_hits(samples)
    assert len(hits) >= 25  # most hi-hats; a ringing crash masks a few
    crashes = [round(float(e["time"]), 1) for e in _crashes(samples, hits)]
    assert crashes and all(any(abs(c - at) < 0.1 for at in (3.0, 9.0)) for c in crashes)
    assert len(crashes) <= 2


def test_tempo_curve_follows_a_tempo_change(tmp_path: Path) -> None:
    """Clicks at 100 BPM for 20 s, then 130 BPM: the curve shows both."""
    times = list(np.arange(0.5, 20, 60 / 100)) + list(np.arange(20, 40, 60 / 130))
    song = np.zeros(int(41 * SAMPLE_RATE))
    click = np.sin(2 * np.pi * 1000 * np.arange(400) / SAMPLE_RATE) * np.exp(
        -np.arange(400) / 60)
    for t in times:
        start = int(t * SAMPLE_RATE)
        song[start:start + click.size] += click
    path = tmp_path / "change.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes((song / np.max(np.abs(song)) * 0.8 * 32767).astype("<i2").tobytes())
    report = analyze_audio(path, tmp_path / "a.json", tmp_path / "a.svg")
    curve = {round(p["time"]): p["bpm"] for p in report["analysis"]["tempo_curve"]}
    early = [bpm for t, bpm in curve.items() if 6 <= t <= 14]
    late = [bpm for t, bpm in curve.items() if 26 <= t <= 34]
    ratio = float(np.median(late)) / float(np.median(early))
    assert abs(ratio - 1.3) < 0.08
