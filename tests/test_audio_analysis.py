from __future__ import annotations

import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from lor_sequence_builder.audio_analysis import AudioAnalysisError, analyze_audio
from lor_sequence_builder.cli import main


def _click_track(path: Path, duration: float = 8.0, bpm: float = 120.0) -> None:
    rate = 11_025
    total = int(rate * duration)
    samples = [0] * total
    beat = 60.0 / bpm
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
    assert report["configuration"]["frame_seconds"] == pytest.approx(551 / 11_025)
    assert report["audio"]["duration_seconds"] == pytest.approx(8.0, abs=0.1)
    assert analysis["tempo"]["bpm"] == pytest.approx(120.0, abs=3.0)
    assert len(analysis["beats"]) >= 10
    assert analysis["beats"][0]["time"] == pytest.approx(0.25, abs=0.12)
    assert len(analysis["downbeats"]) >= 2
    assert analysis["downbeats"][0]["time"] == pytest.approx(0.25, abs=0.12)
    assert analysis["downbeats"][1]["time"] == pytest.approx(2.25, abs=0.15)
    assert len(analysis["onsets"]) >= 8
    assert all(0.0 <= event["confidence"] <= 1.0 for event in analysis["onsets"])
    assert all(event["method"] for event in analysis["beats"])
    assert all(event["method"] for event in analysis["downbeats"])
    assert all(event["method"] for event in analysis["onsets"])
    assert all(point["method"] == "root_mean_square_amplitude" for point in analysis["energy"])
    assert analysis["hard_stops"][0]["method"]
    assert report["tool_versions"]["ffmpeg"].startswith("ffmpeg version")
    assert analysis["hard_stops"]
    assert analysis["hard_stops"][0]["time"] == pytest.approx(5.8, abs=0.2)
    assert analysis["energy"]
    assert analysis["phrase_boundaries"]
    assert report_path.is_file()
    assert report_path.read_text(encoding="utf-8").startswith("{")
    assert plot_path.is_file()
    svg = plot_path.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "provisional downbeats" in svg
    assert "energy transitions" in svg


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
    help_text = capsys.readouterr().out
    assert "output-json" in help_text
    assert "min-bpm" in help_text


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


def test_energy_transition_produces_unlabelled_section_candidate(tmp_path: Path) -> None:
    import array

    audio = tmp_path / "energy-transition.wav"
    rate = 11_025
    samples = array.array("h")
    for index in range(rate * 20):
        amplitude = 2_000 if index < rate * 10 else 16_000
        samples.append(int(amplitude * math.sin(2 * math.pi * 220 * index / rate)))
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())

    report = analyze_audio(audio, tmp_path / "energy.json", tmp_path / "energy.svg")

    candidates = report["analysis"]["section_candidates"]
    assert candidates
    assert candidates[0]["time"] == pytest.approx(10.0, abs=1.0)
    assert candidates[0]["label"] is None


def test_tempo_bounds_are_configurable_and_validated(tmp_path: Path) -> None:
    audio = tmp_path / "configured.wav"
    _click_track(audio)

    report = analyze_audio(
        audio, tmp_path / "configured.json", tmp_path / "configured.svg",
        min_bpm=100, max_bpm=140,
    )

    assert report["configuration"]["minimum_bpm"] == 100
    assert report["configuration"]["maximum_bpm"] == 140
    assert report["analysis"]["tempo"]["bpm"] == pytest.approx(120.0, abs=3.0)

    with pytest.raises(AudioAnalysisError, match="Tempo bounds"):
        analyze_audio(
            audio, tmp_path / "invalid.json", tmp_path / "invalid.svg",
            min_bpm=150, max_bpm=100,
        )



def test_constant_tone_does_not_invent_periodic_beats(tmp_path: Path) -> None:
    import array

    audio = tmp_path / "constant-tone.wav"
    samples = array.array("h", (
        int(8_000 * math.sin(2 * math.pi * 440 * index / 11_025))
        for index in range(11_025 * 5)
    ))
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(11_025)
        output.writeframes(samples.tobytes())

    report = analyze_audio(audio, tmp_path / "tone.json", tmp_path / "tone.svg")

    assert report["analysis"]["tempo"]["bpm"] is None
    assert report["analysis"]["beats"] == []
    assert report["analysis"]["downbeats"] == []


def test_analysis_json_records_provenance_and_runtime_configuration(tmp_path: Path) -> None:
    audio = tmp_path / "provenance.wav"
    _click_track(audio)

    report = analyze_audio(
        audio, tmp_path / "provenance.json", tmp_path / "provenance.svg",
        min_bpm=100, max_bpm=140,
    )

    assert report["tool_versions"]["ffmpeg"]
    assert report["tool_versions"]["python"]
    assert report["analysis"]["provenance"]
    assert report["configuration"]["minimum_bpm"] == 100
    assert report["configuration"]["maximum_bpm"] == 140
    assert report["analysis"]["phrase_boundaries"][0]["method"]



def test_analyzer_recovers_a_different_known_tempo(tmp_path: Path) -> None:
    audio = tmp_path / "known-90-bpm.wav"
    _click_track(audio, duration=12.0, bpm=90.0)

    report = analyze_audio(
        audio, tmp_path / "ninety.json", tmp_path / "ninety.svg",
        min_bpm=70, max_bpm=130,
    )

    assert report["analysis"]["tempo"]["bpm"] == pytest.approx(90.0, abs=3.0)
    beat_times = [event["time"] for event in report["analysis"]["beats"]]
    assert beat_times[0] == pytest.approx(0.25, abs=0.15)
    assert beat_times[1] - beat_times[0] == pytest.approx(2 / 3, abs=0.08)



def test_transient_heavy_noisy_audio_remains_bounded_and_finite(tmp_path: Path) -> None:
    import array
    import random

    audio = tmp_path / "noisy-transients.wav"
    rate = 11_025
    rng = random.Random(20261110)
    samples = array.array("h", (
        rng.randint(-900, 900) for _ in range(rate * 6)
    ))
    for onset in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
        start = int(onset * rate)
        for offset in range(220):
            samples[start + offset] = int(
                12_000 * math.sin(2 * math.pi * 1_200 * offset / rate)
            )
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())

    report = analyze_audio(audio, tmp_path / "noise.json", tmp_path / "noise.svg")

    assert report["audio"]["duration_seconds"] == pytest.approx(6.0, abs=0.1)
    assert report["analysis"]["energy"]
    assert all(
        0.0 <= event["time"] <= 6.0
        and 0.0 <= event["confidence"] <= 1.0
        for event in report["analysis"]["onsets"]
    )
    assert report["analysis"]["tempo"]["bpm"] is None or (
        30 <= report["analysis"]["tempo"]["bpm"] <= 300
    )



def test_analysis_schema_documents_the_emitted_v1_contract() -> None:
    import json

    schema_path = Path(__file__).parents[1] / "docs" / "schemas" / "audio-analysis-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert set(schema["required"]) == {
        "schema_version", "audio", "tool_versions", "configuration", "analysis"
    }
    analysis_required = set(schema["properties"]["analysis"]["required"])
    assert analysis_required == {
        "method", "provenance", "limitations", "tempo", "beats", "downbeats",
        "onsets", "energy", "phrase_boundaries", "section_candidates", "hard_stops",
    }



def test_analyzer_accepts_mp3_input_and_recovers_tempo(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "FFmpeg is a required test/runtime dependency"
    source = tmp_path / "source.wav"
    audio = tmp_path / "song.mp3"
    _click_track(source, duration=8.0, bpm=120.0)
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:a:0", "-c:a", "libmp3lame",
            "-q:a", "3", str(audio),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    report = analyze_audio(
        audio, tmp_path / "mp3.json", tmp_path / "mp3.svg",
        min_bpm=100, max_bpm=140,
    )

    assert report["audio"]["duration_seconds"] == pytest.approx(8.0, abs=0.2)
    assert report["analysis"]["tempo"]["bpm"] == pytest.approx(120.0, abs=5.0)
    assert len(report["audio"]["sha256"]) == 64
    assert (tmp_path / "mp3.svg").is_file()


def test_default_tempo_range_does_not_double_a_90_bpm_track(tmp_path: Path) -> None:
    audio = tmp_path / "known-90-bpm-default-range.wav"
    _click_track(audio, duration=12.0, bpm=90.0)

    report = analyze_audio(
        audio, tmp_path / "ninety-default.json", tmp_path / "ninety-default.svg"
    )

    assert report["analysis"]["tempo"]["bpm"] == pytest.approx(90.0, abs=4.0)
    beat_times = [event["time"] for event in report["analysis"]["beats"]]
    assert len(beat_times) >= 10
    assert beat_times[1] - beat_times[0] == pytest.approx(2 / 3, abs=0.08)



def test_analyzer_rejects_audio_shorter_than_two_seconds(tmp_path: Path) -> None:
    audio = tmp_path / "too-short.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(11_025)
        output.writeframes(b"\x00\x00" * 11_025)

    with pytest.raises(AudioAnalysisError, match="at least 2 seconds"):
        analyze_audio(audio, tmp_path / "short.json", tmp_path / "short.svg")


def test_analyzer_rejects_input_over_200_mib_before_decoding(tmp_path: Path) -> None:
    audio = tmp_path / "oversized.bin"
    with audio.open("wb") as output:
        output.truncate(200 * 1024 * 1024 + 1)

    with pytest.raises(AudioAnalysisError, match="200 MiB"):
        analyze_audio(audio, tmp_path / "large.json", tmp_path / "large.svg")


def test_analyzer_rejects_audio_over_30_minutes(tmp_path: Path) -> None:
    audio = tmp_path / "over-limit.wav"
    silence = b"\x00\x00" * 11_025
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(11_025)
        for _ in range(1_801):
            output.writeframesraw(silence)

    with pytest.raises(AudioAnalysisError, match="30-minute analysis limit"):
        analyze_audio(audio, tmp_path / "long.json", tmp_path / "long.svg")



@pytest.mark.parametrize("bpm", [60.0, 75.0, 100.0, 140.0, 180.0])
def test_tempo_estimator_handles_a_range_of_common_tempos(
    tmp_path: Path, bpm: float
) -> None:
    audio = tmp_path / f"known-{int(bpm)}-bpm.wav"
    _click_track(audio, duration=12.0, bpm=bpm)

    report = analyze_audio(
        audio, tmp_path / f"{int(bpm)}.json", tmp_path / f"{int(bpm)}.svg",
        min_bpm=50, max_bpm=200,
    )

    estimated = report["analysis"]["tempo"]["bpm"]
    assert estimated == pytest.approx(bpm, abs=max(3.0, bpm * 0.035))
    beat_times = [event["time"] for event in report["analysis"]["beats"]]
    assert len(beat_times) >= int(8 * bpm / 60)
    assert all(
        (right - left) == pytest.approx(60.0 / estimated, abs=0.08)
        for left, right in zip(beat_times, beat_times[1:])
    )
