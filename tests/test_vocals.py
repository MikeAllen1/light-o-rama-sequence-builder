from __future__ import annotations

import itertools
import json
import sys
import types
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lor_sequence_builder.audio_analysis import SAMPLE_RATE
from lor_sequence_builder.cli import main
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.planner import display_has_mouths, plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.vocal_separation import SeparationError, separate_vocals
from lor_sequence_builder.vocals import (
    VocalAnalysisError,
    analyze_vocals,
    load_vocals,
    vocal_events,
)
from tests.display_builders import DisplayBuilder, classic_yard, line_drawn_yard, roofline_house
from tests.test_planner import synthetic_analysis

# Two sung phrases: (start, [(syllable offset, length)]), with silence between.
PHRASES = (
    (2.0, [(0.0, 0.3), (0.45, 0.25), (0.85, 0.5), (1.5, 0.3)]),
    (8.0, [(0.0, 0.4), (0.6, 0.3), (1.1, 0.3), (1.6, 0.6), (2.4, 0.3)]),
)


def sung_samples(duration: float = 12.0) -> np.ndarray:
    """A fictional 'voice': pitched syllables with vibrato and soft attacks."""
    rng = np.random.default_rng(3)
    out = rng.normal(0, 0.002, int(duration * SAMPLE_RATE))
    for start, syllables in PHRASES:
        for offset, length in syllables:
            n = int(length * SAMPLE_RATE)
            t = np.arange(n) / SAMPLE_RATE
            pitch = 220 * (1 + 0.01 * np.sin(2 * np.pi * 5 * t))
            tone = sum(np.sin(2 * np.pi * k * np.cumsum(pitch) / SAMPLE_RATE) / k
                       for k in (1, 2, 3))
            envelope = np.minimum(1, t / 0.02) * np.minimum(1, (length - t) / 0.06)
            i = int((start + offset) * SAMPLE_RATE)
            out[i:i + n] += 0.4 * tone * envelope
    return out.astype(np.float32)


def write_wav(path: Path, samples: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def test_vocal_regions_and_syllables_follow_the_singing() -> None:
    events = vocal_events(sung_samples(), 12.0)
    regions = [(r["start"], r["end"]) for r in events["regions"]]
    assert len(regions) == 2
    for (start, syllables), (a, b) in zip(PHRASES, regions, strict=True):
        last_offset, last_length = syllables[-1]
        assert abs(a - start) < 0.08
        assert abs(b - (start + last_offset + last_length)) < 0.15
    starts = [s["start"] for s in events["syllables"]]
    expected = [start + offset for start, syllables in PHRASES for offset, _ in syllables]
    assert len(starts) == len(expected)
    # Onsets are backtracked to where the voice starts to rise, so a mouth may open
    # up to a tenth of a second early, never late.
    assert all(-0.1 < a - b < 0.03 for a, b in zip(starts, expected, strict=True))
    assert all(0 < s["strength"] <= 1 and s["end"] > s["start"] for s in events["syllables"])


def test_silence_has_no_vocals() -> None:
    assert vocal_events(np.zeros(SAMPLE_RATE * 4, dtype=np.float32), 4.0) == {
        "regions": [], "syllables": []}


def test_analyze_vocals_writes_a_report_once(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "voice.wav", sung_samples())
    report = analyze_vocals(source, tmp_path / "v.json", "test")
    assert report["schema_version"] == "vocals-1.0" and len(report["regions"]) == 2
    assert load_vocals(tmp_path / "v.json")["source"] == "test"
    with pytest.raises(VocalAnalysisError, match="overwrite"):
        analyze_vocals(source, tmp_path / "v.json", "test")
    (tmp_path / "bad.json").write_text('{"schema_version": "x"}', encoding="utf-8")
    with pytest.raises(VocalAnalysisError, match="Unsupported"):
        load_vocals(tmp_path / "bad.json")


def full_face() -> DisplayBuilder:
    """A fictional face drawn as separate props, each part its own channel."""
    d = DisplayBuilder("Fictional Face")
    lines = "Lines-Connected"
    ring = [(0.5 + 0.1 * np.cos(a), 0.1 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 13)]
    d.add("Face Outline", "singing_face", shape=lines, points=[(float(x), float(y))
                                                               for x, y in ring], unit="40")
    for name, y in (("Mouth Closed", -0.05), ("Mouth Half", -0.045), ("Mouth Open", -0.04),
                    ("Mouth O", -0.035)):
        d.add(name, "singing_face", shape=lines, unit="40",
              points=[(0.47, y), (0.5, y - 0.01), (0.53, y)])
    d.add("Eyes Open", "singing_face", shape=lines, unit="40",
          points=[(0.46, 0.03), (0.48, 0.035), (0.52, 0.035), (0.54, 0.03)])
    d.add("Eyes Closed", "singing_face", shape=lines, unit="40",
          points=[(0.46, 0.03), (0.5, 0.02), (0.54, 0.03)])
    d.add("Yard Arch", "arch", shape="Arch", box=(-0.5, -0.4, 0.1, 0.08), unit="41")
    return d


def _vocals() -> dict[str, Any]:
    return {"schema_version": "vocals-1.0", **vocal_events(sung_samples(), 12.0)}


def _plan(display: DisplayBuilder, vocals: dict[str, Any] | None) -> Any:
    rules = load_rule_set()
    root = display.element()
    plan = plan_show(synthetic_analysis(duration=12.0, sections=((0.0, 0.5),)),
                     display_from_preview(root), rules, vocals)
    return plan, check_choreography(root, plan.choreography, rules)


def test_a_face_sings_with_shapes_blinks_and_its_outline() -> None:
    display = full_face()
    ids = {p.get("Name", ""): p.get("id", "") for p in display.element().findall("PropClass")}
    plan, report = _plan(display, _vocals())
    assert report.ok, report.format_text()
    statuses = {r.rule_id: r.status for r in report.results}
    assert statuses["face_outline_with_mouth"] == "passed"
    assert statuses["mouths_only_during_vocals"] == "passed"
    timeline = plan.choreography
    assert timeline.vocal_regions is not None and len(timeline.vocal_regions) == 2
    mouths = {ids[n]: n for n in ("Mouth Closed", "Mouth Half", "Mouth Open", "Mouth O")}
    mouth_effects = sorted((e for e in timeline.effects if e.prop_id in mouths),
                           key=lambda e: e.start_centisecond)
    used_shapes = {mouths[e.prop_id] for e in mouth_effects}
    assert {"Mouth Closed", "Mouth Open"} <= used_shapes and len(used_shapes) >= 3
    # Exactly one mouth at a time.
    for a, b in itertools.pairwise(mouth_effects):
        assert a.end_centisecond <= b.start_centisecond
    # Before the singing and between phrases the face holds still: outline, open
    # eyes and the closed mouth, never an open mouth.
    moving = {ids[n] for n in ("Mouth Half", "Mouth Open", "Mouth O")}
    resting = [e for e in timeline.effects if e.start_centisecond < 190
               or 500 < e.start_centisecond < 790]
    assert not [e for e in resting if e.prop_id in moving]
    assert {ids["Face Outline"], ids["Mouth Closed"]} <= {e.prop_id for e in resting}
    blinks = [e for e in timeline.effects if e.prop_id == ids["Eyes Closed"]]
    assert blinks and all(e.end_centisecond - e.start_centisecond == 15 for e in blinks)
    # The rest of the display still gets its normal look.
    assert any(e.prop_id == ids["Yard Arch"] for e in timeline.effects)


def test_faces_from_the_line_drawn_yard_sing_and_pass_the_rules() -> None:
    _, report = _plan(line_drawn_yard(), _vocals())
    assert report.ok, report.format_text()
    assert {r.rule_id: r.status for r in report.results}["mouths_only_during_vocals"] == \
        "passed"


def test_vocals_without_faces_or_singing_say_so() -> None:
    plan, _ = _plan(roofline_house(), _vocals())
    assert any("no singing face" in n for n in plan.notes)
    # A face drawn as one prop lights while someone sings, but has no mouth to move.
    plan, report = _plan(classic_yard(), _vocals())
    assert report.ok and any("no face has separate mouth props" in n.lower()
                             for n in plan.notes)
    silent = {"schema_version": "vocals-1.0", "regions": [], "syllables": []}
    plan, report = _plan(full_face(), silent)
    assert report.ok
    assert any("faces rest all song" in n for n in plan.notes)
    assert display_has_mouths(display_from_preview(full_face().element()), load_rule_set())
    assert not display_has_mouths(display_from_preview(classic_yard().element()),
                                  load_rule_set())


def _song(tmp_path: Path) -> Path:
    from tests.test_audio_analysis import _rhythmic_track

    path = tmp_path / "song.wav"
    _rhythmic_track(path, duration=12.0)
    return path


def _preview(tmp_path: Path, display: DisplayBuilder) -> Path:
    path = tmp_path / "face.lorprev"
    ET.ElementTree(display.element()).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_generate_uses_a_supplied_vocals_file(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    preview = _preview(tmp_path, full_face())
    vocals = write_wav(tmp_path / "voice.wav", sung_samples())
    assert main(["generate", "--preview", str(preview), "--audio", str(_song(tmp_path)),
                 "--vocals", str(vocals), "--output", str(tmp_path / "show.loredit"),
                 "--no-ask"]) == 0
    out = capsys.readouterr().out
    assert "Vocals:" in out and "0 error(s)" in out
    saved = json.loads((tmp_path / "show.vocals.json").read_text(encoding="utf-8"))
    assert saved["source"] == "supplied vocals file" and len(saved["regions"]) == 2
    timeline = json.loads((tmp_path / "show.timeline.json").read_text(encoding="utf-8"))
    assert len(timeline["vocal_regions"]) == 2
    # The saved analysis can be reused instead of the audio.
    assert main(["generate", "--preview", str(preview), "--audio", str(_song(tmp_path)),
                 "--vocals", str(tmp_path / "show.vocals.json"),
                 "--output", str(tmp_path / "again.loredit"), "--no-ask"]) == 0


def test_without_vocals_or_the_add_on_mouths_stay_still(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lor_sequence_builder.generate.separation_available", lambda: False)
    show = generate_show(_preview(tmp_path, full_face()), tmp_path / "show.loredit",
                         load_rule_set(), audio_path=_song(tmp_path))
    assert show.vocals_path is None
    assert show.vocals_note is not None and "--vocals" in show.vocals_note
    assert show.plan.choreography.vocal_regions is None


def test_separation_is_used_automatically_when_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = sung_samples()

    class FakeSeparator:
        def __init__(self, output_dir: str, **_: object) -> None:
            self.output_dir = Path(output_dir)

        def load_model(self, model_filename: str) -> None:
            assert model_filename.endswith(".onnx")

        def separate(self, audio: str) -> list[str]:
            write_wav(self.output_dir / "x_(Vocals)_model.wav", voice)
            write_wav(self.output_dir / "x_(Instrumental)_model.wav", voice * 0)
            return ["x_(Instrumental)_model.wav", "x_(Vocals)_model.wav"]

    package = types.ModuleType("audio_separator")
    module = types.ModuleType("audio_separator.separator")
    module.Separator = FakeSeparator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "audio_separator", package)
    monkeypatch.setitem(sys.modules, "audio_separator.separator", module)
    monkeypatch.setattr("lor_sequence_builder.generate.separation_available", lambda: True)
    monkeypatch.setattr("lor_sequence_builder.vocal_separation.separation_available",
                        lambda: True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    messages: list[str] = []
    show = generate_show(_preview(tmp_path, full_face()), tmp_path / "show.loredit",
                         load_rule_set(), audio_path=_song(tmp_path), progress=messages.append)
    assert (tmp_path / "show.vocals.wav").exists()
    assert show.vocals_path == tmp_path / "show.vocals.json"
    assert show.report.ok and any("Splitting the vocals" in m for m in messages)
    with pytest.raises(SeparationError, match="overwrite"):
        separate_vocals(_song(tmp_path), tmp_path / "show.vocals.wav")


def test_separation_explains_how_to_get_it(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lor_sequence_builder.vocal_separation.separation_available",
                        lambda: False)
    with pytest.raises(SeparationError, match="uv sync --extra vocals"):
        separate_vocals(tmp_path / "song.wav", tmp_path / "v.wav")


def test_a_mustache_face_sings_with_up_open_and_down_resting() -> None:
    d = DisplayBuilder("Fictional Snowman Face")
    ring = [(0.5 + 0.1 * np.cos(a), 0.1 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 13)]
    d.add("Snowman Face Outline", "singing_face", shape="Lines-Connected", unit="60",
          points=[(float(x), float(y)) for x, y in ring])
    for name, y in (("Snowman Mustache Down", -0.05), ("Snowman Mustache Up", -0.03)):
        d.add(name, "singing_face", shape="Lines-Connected", unit="60",
              points=[(0.46, y), (0.5, y + 0.01), (0.54, y)])
    ids = {p.get("Name", ""): p.get("id", "") for p in d.element().findall("PropClass")}
    plan, report = _plan(d, _vocals())
    assert report.ok, report.format_text()
    statuses = {r.rule_id: r.status for r in report.results}
    assert statuses["mouths_only_during_vocals"] == "passed"
    up = [e for e in plan.choreography.effects if e.prop_id == ids["Snowman Mustache Up"]]
    down = [e for e in plan.choreography.effects if e.prop_id == ids["Snowman Mustache Down"]]
    assert len(up) >= 5 and down
    regions = plan.choreography.vocal_regions or ()
    assert all(any(a <= e.start_centisecond and e.end_centisecond <= b for a, b in regions)
               for e in up)
    # The resting mustache also shows before anyone sings.
    assert any(e.start_centisecond < 190 for e in down)


@pytest.mark.parametrize("events", [
    [None],
    [{}],
    [{"start": 1.0, "end": 2.0}],
    [{"start": 2.0, "end": 1.0, "strength": 0.5}],
    [{"start": 0.0, "end": 13.0, "strength": 0.5}],
    [{"start": 0.0, "end": 1.0, "strength": float("nan")}],
    [{"start": 0.0, "end": 1.0, "strength": 1.1}],
])
def test_load_vocals_rejects_malformed_syllable_events(tmp_path: Path, events: list[Any]) -> None:
    path = tmp_path / "vocals.json"
    path.write_text(json.dumps({
        "schema_version": "vocals-1.0", "duration_seconds": 12.0,
        "regions": [], "syllables": events,
    }), encoding="utf-8")
    with pytest.raises(VocalAnalysisError):
        load_vocals(path)


@pytest.mark.parametrize("regions", [[None], [{}], [{"start": 2, "end": 1}]])
def test_load_vocals_rejects_malformed_regions(tmp_path: Path, regions: list[Any]) -> None:
    path = tmp_path / "vocals.json"
    path.write_text(json.dumps({
        "schema_version": "vocals-1.0", "duration_seconds": 12.0,
        "regions": regions, "syllables": [],
    }), encoding="utf-8")
    with pytest.raises(VocalAnalysisError):
        load_vocals(path)
