from __future__ import annotations

import itertools
import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from lor_sequence_builder.audio_analysis import (
    AudioAnalysisError,
    _drop_unsupported_beats,
    analyze_audio,
)
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


def _rhythmic_track(path: Path, duration: float = 8.0, bpm: float = 120.0) -> None:
    """Create a basic kick/snare-like pulse with weaker offbeat accents."""
    rate = 11_025
    total = int(rate * duration)
    samples = [0] * total
    beat_seconds = 60.0 / bpm
    beat_index = 0
    beat_time = 0.3
    beat_amplitudes = (15_000, 6_000, 9_000, 6_000)

    events: list[tuple[float, int]] = []
    while beat_time + 0.03 < duration:
        events.append((beat_time, beat_amplitudes[beat_index % 4]))
        events.append((beat_time + beat_seconds / 2.0, 3_500))
        beat_index += 1
        beat_time = 0.3 + beat_index * beat_seconds

    for onset, amplitude in events:
        start = int(onset * rate)
        count = int(0.03 * rate)
        if start + count > total:
            continue
        for offset in range(count):
            envelope = min(1.0, offset / 30, (count - offset) / 30)
            samples[start + offset] = int(
                amplitude * envelope * math.sin(2.0 * math.pi * 880 * offset / rate)
            )

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
    assert report["schema_version"] == "2.0"
    assert report["configuration"]["frame_seconds"] == pytest.approx(1_102 / 22_050)
    assert report["configuration"]["hop_length"] == 512
    assert report["audio"]["normalized_sample_rate"] == 22_050
    assert report["tool_versions"]["librosa"] != "unknown"
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
    assert "downbeats" in svg
    assert "section candidates" in svg


def test_tempo_estimator_handles_syncopation_and_uneven_beat_accents(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "syncopated-120-bpm.wav"
    _rhythmic_track(audio, duration=12.0, bpm=120.0)

    report = analyze_audio(
        audio, tmp_path / "syncopated.json", tmp_path / "syncopated.svg",
        min_bpm=50, max_bpm=200,
    )

    tempo = report["analysis"]["tempo"]["bpm"]
    beats = [event["time"] for event in report["analysis"]["beats"]]
    assert tempo == pytest.approx(120.0, abs=5.0)
    assert beats[0] == pytest.approx(0.3, abs=0.15)
    assert len(beats) >= 16
    assert all(
        (right - left) == pytest.approx(60.0 / tempo, abs=0.08)
        for left, right in itertools.pairwise(beats)
    )


def test_competing_offbeat_accents_reduce_beat_grid_confidence(tmp_path: Path) -> None:
    """A louder offbeat must not be presented as a certain metrical phase."""
    import array

    audio = tmp_path / "offbeat-dominant.wav"
    rate = 11_025
    duration = 12.0
    samples = array.array("h", [0] * int(rate * duration))
    beat_seconds = 0.5
    event_time = 0.3
    event_index = 0
    while event_time + 0.04 < duration:
        amplitude = 4_000 if event_index % 2 == 0 else 15_000
        start = int(event_time * rate)
        count = int(0.03 * rate)
        for offset in range(count):
            envelope = min(1.0, offset / 30, (count - offset) / 30)
            samples[start + offset] = int(
                amplitude * envelope * math.sin(2.0 * math.pi * 880 * offset / rate)
            )
        event_index += 1
        event_time = 0.3 + event_index * beat_seconds / 2.0

    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())

    report = analyze_audio(
        audio, tmp_path / "offbeat.json", tmp_path / "offbeat.svg",
        min_bpm=100, max_bpm=140,
    )

    analysis = report["analysis"]
    assert analysis["tempo"]["bpm"] == pytest.approx(120.0, abs=5.0)
    assert analysis["beats"]
    # Strong events between the beats must lower beat-grid confidence well
    # below that of an unambiguous click track (which scores near 1.0).
    clean_audio = tmp_path / "clean.wav"
    _click_track(clean_audio, duration=12.0, bpm=120.0)
    clean = analyze_audio(clean_audio, tmp_path / "clean.json", tmp_path / "clean.svg")
    clean_confidence = clean["analysis"]["beats"][0]["confidence"]
    assert clean_confidence >= 0.9
    assert analysis["beats"][0]["confidence"] <= 0.5 * clean_confidence


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
    with pytest.raises(AudioAnalysisError, match="Unsupported audio file extension"):
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


def test_cli_reports_reduced_beat_grid_confidence(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from lor_sequence_builder import cli

    report = {
        "audio": {"duration_seconds": 8.0},
        "analysis": {
            "tempo": {"bpm": 120.0, "confidence": 0.9},
            "beats": [{"confidence": 0.2}, {"confidence": 0.4}],
            "downbeats": [],
            "onsets": [],
            "section_candidates": [],
            "hard_stops": [],
        },
    }
    monkeypatch.setattr(cli, "analyze_audio", lambda *args, **kwargs: report)

    result = cli.main([
        "analyze-audio", "song.wav", "--output-json", "song.json", "--plot", "song.svg"
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "Estimated tempo: 120.0 BPM (confidence 0.9)" in output
    assert "Beat grid confidence: 0.3000" in output


def test_hard_stop_detection_includes_leading_silence_but_not_silent_files() -> None:
    from lor_sequence_builder.audio_analysis import _hard_stops

    leading_silence = [0.0] * 20 + [0.2] * 40 + [0.0] * 20
    stops = _hard_stops(leading_silence)

    assert len(stops) == 2
    assert stops[0]["time"] == 0.0
    assert stops[0]["method"] == "leading_near_silence_relative_to_track_peak"
    assert stops[0]["silence_duration"] == pytest.approx(1.0)
    assert stops[1]["time"] == pytest.approx(3.0, abs=0.01)
    assert _hard_stops([0.0] * 100) == []


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



def _schema_violations(value: object, schema: dict[str, object], root: dict[str, object],
                       path: str = "$") -> list[str]:
    """Check required keys, closed objects, consts, enums, and nested items."""
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        definitions = root["$defs"]
        assert isinstance(definitions, dict)
        return _schema_violations(value, definitions[name], root, path)
    problems: list[str] = []
    if "const" in schema and value != schema["const"]:
        problems.append(f"{path}: {value!r} != {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:  # type: ignore[operator]
        problems.append(f"{path}: {value!r} not in {schema['enum']!r}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        assert isinstance(properties, dict)
        for key in schema.get("required", []):  # type: ignore[attr-defined]
            if key not in value:
                problems.append(f"{path}: missing {key!r}")
        if schema.get("additionalProperties") is False:
            problems.extend(f"{path}: unexpected {key!r}" for key in value if key not in properties)
        for key, child in value.items():
            if key in properties:
                problems.extend(_schema_violations(child, properties[key], root, f"{path}.{key}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            problems.extend(
                _schema_violations(child, schema["items"], root, f"{path}[{index}]")  # type: ignore[arg-type]
            )
    return problems


def test_emitted_report_matches_the_v2_schema_contract(tmp_path: Path) -> None:
    import json

    schema_path = Path(__file__).parents[1] / "docs" / "schemas" / "audio-analysis-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == "2.0"

    audio = tmp_path / "contract.wav"
    _chord_song(
        audio,
        [[C_MAJOR, A_MINOR, F_MAJOR, G_MAJOR], [E_MAJOR, D_MINOR, E_MAJOR, D_MINOR]],
        bars_per_part=10,
    )
    report = analyze_audio(audio, tmp_path / "contract.json", tmp_path / "contract.svg")
    written = json.loads((tmp_path / "contract.json").read_text(encoding="utf-8"))

    assert written == report
    assert _schema_violations(report, schema, schema) == []

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
    # Nine clicks fall before the track goes silent at 6 seconds.
    assert len(beat_times) >= 8
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
    # _click_track places clicks from 0.25 s until 6 s, then leaves silence.
    clicks = [0.25 + i * 60.0 / bpm for i in range(400) if 0.25 + i * 60.0 / bpm + 0.04 < 6.0]
    assert len(beat_times) >= len(clicks) - 1
    assert max(beat_times) < 6.3, "beats must not be invented in trailing silence"
    assert all(
        (right - left) == pytest.approx(60.0 / estimated, abs=0.08)
        for left, right in itertools.pairwise(beat_times)
    )



def test_analysis_does_not_publish_json_when_plot_generation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lor_sequence_builder import audio_analysis

    audio = tmp_path / "atomic.wav"
    json_path = tmp_path / "atomic.json"
    plot_path = tmp_path / "atomic.svg"
    _click_track(audio)

    def fail_plot(*args: object, **kwargs: object) -> None:
        raise OSError("simulated SVG write failure")

    monkeypatch.setattr(audio_analysis, "_svg_plot", fail_plot)

    with pytest.raises(AudioAnalysisError, match="simulated SVG write failure"):
        analyze_audio(audio, json_path, plot_path)

    assert not json_path.exists()
    assert not plot_path.exists()
    assert not list(tmp_path.glob(".atomic.*.tmp"))



def test_concurrent_plot_creation_does_not_leave_partial_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "race.wav"
    json_path = tmp_path / "race.json"
    plot_path = tmp_path / "race.svg"
    _click_track(audio)

    import os

    real_link = os.link
    link_calls = 0

    def create_competing_plot(source: str | Path, destination: str | Path) -> None:
        nonlocal link_calls
        link_calls += 1
        if link_calls == 2:
            Path(destination).write_text("another process won", encoding="utf-8")
            raise FileExistsError("simulated concurrent output creation")
        real_link(source, destination)

    monkeypatch.setattr(os, "link", create_competing_plot)

    with pytest.raises(AudioAnalysisError, match="overwrite"):
        analyze_audio(audio, json_path, plot_path)

    assert link_calls == 2
    assert not json_path.exists()
    assert plot_path.read_text(encoding="utf-8") == "another process won"
    assert not list(tmp_path.glob(".race.*.tmp"))


def _write_float_wav(path: Path, samples: list[float], rate: int = 22_050) -> None:
    import array

    peak = max(1e-9, max(abs(value) for value in samples))
    scaled = array.array("h", (int(20_000 * value / peak) for value in samples))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(scaled.tobytes())


def _chord_song(
    path: Path,
    progressions: list[list[tuple[float, ...]]],
    bars_per_part: int,
    pickup_beats: int = 1,
    bpm: float = 120.0,
    beats_per_bar: int = 4,
) -> float:
    """Clicks on every beat with chords that change exactly on each downbeat.

    Returns the time of the first downbeat (after the pickup beats).
    """
    rate = 22_050
    beat = 60.0 / bpm
    start = 0.5
    total_beats = pickup_beats + beats_per_bar * bars_per_part * len(progressions)
    samples = [0.0] * int(rate * (start + (total_beats + 1) * beat))
    for index in range(total_beats):
        onset = start + index * beat
        bar = (index - pickup_beats) // beats_per_bar
        part = max(0, bar) // bars_per_part
        chords = progressions[min(part, len(progressions) - 1)]
        chord = chords[max(0, bar) % len(chords)]
        loudness = 1.0 if part == 0 else 1.8
        first = int(onset * rate)
        for offset in range(int(beat * rate)):
            time = offset / rate
            value = sum(math.sin(2 * math.pi * f * time) for f in chord) * 0.25 * loudness
            if time < 0.03:
                value += 0.9 * math.sin(2 * math.pi * 1_500 * time)
            if first + offset < len(samples):
                samples[first + offset] = value
    _write_float_wav(path, samples)
    return start + pickup_beats * beat


C_MAJOR = (261.6, 329.6, 392.0)
A_MINOR = (220.0, 261.6, 329.6)
F_MAJOR = (174.6, 220.0, 261.6)
G_MAJOR = (196.0, 246.9, 293.7)
E_MAJOR = (164.8, 207.7, 246.9)
D_MINOR = (146.8, 174.6, 220.0)


def test_downbeats_follow_harmony_changes_not_the_first_beat(tmp_path: Path) -> None:
    audio = tmp_path / "pickup.wav"
    first_downbeat = _chord_song(
        audio, [[C_MAJOR, A_MINOR, F_MAJOR, G_MAJOR]], bars_per_part=12, pickup_beats=1
    )

    report = analyze_audio(audio, tmp_path / "pickup.json", tmp_path / "pickup.svg")

    downbeats = [event["time"] for event in report["analysis"]["downbeats"]]
    assert report["analysis"]["downbeats"][0]["confidence"] >= 0.1
    # The pickup beat at 0.5 s must not be called bar one.
    assert all(abs(time - 0.5) > 0.1 for time in downbeats[:1])
    bar_seconds = 2.0
    assert all(
        min(abs((time - first_downbeat) % bar_seconds), bar_seconds - (time - first_downbeat) % bar_seconds) < 0.1
        for time in downbeats
    )


def test_structural_change_is_reported_as_unlabelled_section_candidate(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "two-parts.wav"
    _chord_song(
        audio,
        [[C_MAJOR, A_MINOR, F_MAJOR, G_MAJOR], [E_MAJOR, D_MINOR, E_MAJOR, D_MINOR]],
        bars_per_part=10,
        pickup_beats=0,
    )
    change_time = 0.5 + 10 * 4 * 0.5

    report = analyze_audio(audio, tmp_path / "parts.json", tmp_path / "parts.svg")

    structural = [
        candidate for candidate in report["analysis"]["section_candidates"]
        if candidate["kind"] == "structural_change_candidate"
    ]
    assert structural
    assert min(abs(candidate["time"] - change_time) for candidate in structural) <= 2.0
    assert all(candidate["label"] is None for candidate in structural)


def test_beat_sync_columns_line_up_with_beat_indices() -> None:
    import numpy as np

    from lor_sequence_builder.audio_analysis import _beat_sync

    frames = np.arange(40, dtype=np.float64)[None, :]
    late_start = _beat_sync(frames, np.array([5, 10, 15], dtype=np.int64))
    zero_start = _beat_sync(frames, np.array([0, 5, 10, 15], dtype=np.int64))
    # Column i averages beat i up to the next beat; the last beat spans one period.
    assert late_start.tolist() == [[7.0, 12.0, 17.0]]
    assert zero_start.tolist() == [[2.0, 7.0, 12.0, 17.0]]


def test_waltz_downbeats_follow_three_beat_bars(tmp_path: Path) -> None:
    audio = tmp_path / "waltz.wav"
    first_downbeat = _chord_song(
        audio, [[C_MAJOR, A_MINOR, F_MAJOR, G_MAJOR]], bars_per_part=16,
        pickup_beats=1, beats_per_bar=3,
    )

    report = analyze_audio(
        audio, tmp_path / "waltz.json", tmp_path / "waltz.svg", beats_per_bar=3
    )

    assert report["configuration"]["beats_per_bar"] == 3
    downbeats = [event["time"] for event in report["analysis"]["downbeats"]]
    bar_seconds = 1.5
    offsets = [(time - first_downbeat) % bar_seconds for time in downbeats]
    assert all(min(offset, bar_seconds - offset) < 0.1 for offset in offsets)


def test_unsupported_beats_per_bar_is_rejected(tmp_path: Path) -> None:
    audio = tmp_path / "click.wav"
    _click_track(audio)
    with pytest.raises(AudioAnalysisError, match="3 or 4"):
        analyze_audio(audio, tmp_path / "bad.json", tmp_path / "bad.svg", beats_per_bar=5)


@pytest.mark.parametrize("bpm", [113.0, 120.0, 150.0, 162.0])
def test_tempo_stays_exact_over_a_long_steady_track(tmp_path: Path, bpm: float) -> None:
    """Frame quantization must not accumulate into a tempo bias over minutes."""
    rate = 22_050
    duration = 90.0
    beat = 60.0 / bpm
    samples = [0.0] * int(rate * duration)
    onset = 0.25
    while onset + 0.03 < duration:
        start = int(onset * rate)
        for offset in range(int(0.03 * rate)):
            samples[start + offset] = math.sin(2 * math.pi * 1_500 * offset / rate)
        onset += beat
    audio = tmp_path / "long-click.wav"
    _write_float_wav(audio, samples)

    report = analyze_audio(audio, tmp_path / "long.json", tmp_path / "long.svg")

    assert report["analysis"]["tempo"]["bpm"] == pytest.approx(bpm, abs=0.3)


def test_beat_filter_does_not_keep_zero_support_grid_positions() -> None:
    import numpy as np

    envelope = np.zeros(100, dtype=np.float64)
    envelope[[10, 20, 30, 40]] = 1.0
    frames = np.asarray([10, 20, 30, 40, 50, 60, 70], dtype=np.int64)

    kept = _drop_unsupported_beats(envelope, frames)

    assert kept.tolist() == [10, 20, 30, 40]


def test_beat_filter_returns_empty_when_no_candidate_has_support() -> None:
    import numpy as np

    kept = _drop_unsupported_beats(
        np.zeros(100, dtype=np.float64),
        np.asarray([10, 20, 30, 40], dtype=np.int64),
    )
    assert kept.size == 0


def test_ffmpeg_normalization_restricts_protocol_and_demuxer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from lor_sequence_builder import audio_analysis

    calls: list[list[str]] = []
    monkeypatch.setattr(audio_analysis.shutil, "which", lambda _: "ffmpeg")

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        calls.append(command)
        if "-version" in command:
            return SimpleNamespace(returncode=0, stdout="ffmpeg version test", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(audio_analysis.subprocess, "run", fake_run)
    audio_analysis._normalize(tmp_path / "sample.wav", tmp_path / "normalized.wav")

    decode = calls[1]
    assert decode[decode.index("-protocol_whitelist") + 1] == "file,pipe"
    assert decode[decode.index("-f") + 1] == "wav"


def test_ffmpeg_normalization_rejects_unknown_demuxer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from lor_sequence_builder import audio_analysis

    monkeypatch.setattr(audio_analysis.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(
        audio_analysis.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="ffmpeg version test", stderr=""
        ),
    )
    with pytest.raises(AudioAnalysisError, match="Unsupported audio file extension"):
        audio_analysis._normalize(tmp_path / "playlist.m3u", tmp_path / "normalized.wav")
