from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from lor_sequence_builder.audio_analysis import AudioAnalysisError, analyze_audio
from lor_sequence_builder.cli import main


def _click_track(path: Path, duration: float = 8.0) -> None:
    rate = 11_025
    total = int(rate * duration)
    samples = [0] * total
    beat = 0.5
    onset = 0.25
    index = 0
    while onset + 0.04 < 6.0:
        start = int(onset * rate)
        count = int(0.04 * rate)
        for offset in range(count):
            envelope = min(1.0, offset / 40, (count - offset) / 40)
            samples[start + offset] = int(
                18_000 * envelope * math.sin(2.0 * math.pi * 880 * offset / rate)
            )
        index += 1
        onset = 0.25 + index * beat
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        import array

        output.writeframes(array.array("h", samples).tobytes())


def test_analyze_audio_detects_tempo_beats_onsets_and_hard_stop(tmp_path: Path) -> None:
    audio = tmp_path / "known-120-bpm.wav"
    report_path = tmp_path / "analysis.json"
    plot_path = tmp_path / "analysis.svg"
    _click_track(audio)

    report = analyze_audio(audio, report_path, plot_path)

    analysis = report["analysis"]
    assert report["schema_version"] == "1.0"
    assert report["audio"]["duration_seconds"] == pytest.approx(8.0, abs=0.1)
    assert analysis["tempo"]["bpm"] == pytest.approx(120.0, abs=3.0)
    assert len(analysis["beats"]) >= 10
    assert len(analysis["downbeats"]) >= 2
    assert len(analysis["onsets"]) >= 8
    assert analysis["hard_stops"]
    assert analysis["hard_stops"][0]["time"] == pytest.approx(5.8, abs=0.2)
    assert analysis["energy"]
    assert analysis["phrase_boundaries"]
    assert report_path.is_file()
    assert plot_path.is_file()
    assert "<svg" in plot_path.read_text(encoding="utf-8")


def test_analysis_refuses_to_overwrite_outputs(tmp_path: Path) -> None:
    audio = tmp_path / "known.wav"
    _click_track(audio)
    report_path = tmp_path / "existing.json"
    plot_path = tmp_path / "plot.svg"
    report_path.write_text("keep", encoding="utf-8")

    with pytest.raises(AudioAnalysisError, match="overwrite"):
        analyze_audio(audio, report_path, plot_path)

    assert report_path.read_text(encoding="utf-8") == "keep"


def test_analysis_rejects_invalid_audio(tmp_path: Path) -> None:
    audio = tmp_path / "not-audio.bin"
    audio.write_bytes(b"not audio")
    with pytest.raises(AudioAnalysisError, match="FFmpeg could not decode"):
        analyze_audio(audio, tmp_path / "out.json", tmp_path / "out.svg")


def test_analysis_rejects_output_aliasing_input(tmp_path: Path) -> None:
    audio = tmp_path / "source.wav"
    _click_track(audio)
    with pytest.raises(AudioAnalysisError, match="different paths"):
        analyze_audio(audio, audio, tmp_path / "plot.svg")


def test_cli_exposes_audio_analysis_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-audio", "--help"])
    assert exc_info.value.code == 0
    assert "output-json" in capsys.readouterr().out


def test_silence_does_not_fabricate_a_tempo(tmp_path: Path) -> None:
    audio = tmp_path / "silence.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(11_025)
        output.writeframes(b"\x00\x00" * (11_025 * 3))

    report = analyze_audio(audio, tmp_path / "silence.json", tmp_path / "silence.svg")

    assert report["analysis"]["tempo"]["bpm"] is None
    assert report["analysis"]["beats"] == []
    assert report["analysis"]["downbeats"] == []
