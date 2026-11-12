"""Kicks, snares, unexpected chords and lyric cues: found in the song, used in the show.

Every song here is synthesized in the test; every display is fictional.
"""

from __future__ import annotations

import collections
import json
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.cli import main
from lor_sequence_builder.evaluation import load_analysis
from lor_sequence_builder.planner import Plan, plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import get_style
from tests.display_builders import family_yard
from tests.test_lms import s4_sequence
from tests.test_planner import synthetic_analysis

BEAT = 0.5  # 120 BPM
AB_BARS = (12, 13)


def drum_song(path: Path, bars: int = 24) -> None:
    """Kick on beats one and three, snare on two and four, chords C F G C, and two
    bars of A-flat, a chord outside the key."""
    rate = 22050
    beat = BEAT
    samples = np.zeros(int(rate * beat * 4 * bars) + rate)
    rng = np.random.default_rng(1)
    t_kick = np.arange(int(0.15 * rate)) / rate
    kick = np.sin(2 * np.pi * (60 + 60 * np.exp(-t_kick * 30)) * t_kick) * np.exp(-t_kick * 25)
    t_snare = np.arange(int(0.12 * rate)) / rate
    noise = rng.standard_normal(t_snare.size)
    bright = noise - np.convolve(noise, np.ones(8) / 8, mode="same")
    snare = np.convolve(bright, np.ones(3) / 3, mode="same") * np.exp(-t_snare * 35)
    chords = {"C": (261.63, 329.63, 392.0, 523.25), "F": (349.23, 440.0, 523.25, 698.46),
              "G": (392.0, 493.88, 587.33, 783.99), "Ab": (415.3, 523.25, 622.25, 830.61)}
    progression = ["C", "F", "G", "C"]
    for bar in range(bars):
        start, length = int(bar * 4 * beat * rate), int(4 * beat * rate)
        name = "Ab" if bar in AB_BARS else progression[bar % 4]
        t = np.arange(length) / rate
        samples[start:start + length] += 0.08 * sum(np.sin(2 * np.pi * f * t)
                                                    for f in chords[name])
        for b in range(4):
            at = int((bar * 4 + b) * beat * rate)
            if b in (0, 2):
                samples[at:at + kick.size] += 0.9 * kick
            else:
                samples[at:at + snare.size] += 0.5 * snare
    samples = samples / np.max(np.abs(samples)) * 0.8
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((samples * 32767).astype("<i2").tobytes())


@pytest.fixture(scope="module")
def drum_analysis(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("drums")
    drum_song(folder / "drums.wav")
    analyze_audio(folder / "drums.wav", folder / "drums.analysis.json", folder / "drums.svg")
    return load_analysis(folder / "drums.analysis.json")


def _beat_in_bar(times: list[float]) -> collections.Counter[int]:
    return collections.Counter(round(t / BEAT) % 4 for t in times)


def test_kicks_snares_and_the_unexpected_chord_are_found(drum_analysis: dict[str, Any]
                                                         ) -> None:
    found = drum_analysis["analysis"]
    kicks = [e["time"] for e in found["kicks"]]
    snares = [e["time"] for e in found["snares"]]
    # Nearly every kick on one or three, nearly every snare on two or four.
    assert len(kicks) >= 40 and sum(_beat_in_bar(kicks)[b] for b in (0, 2)) >= 0.95 * len(kicks)
    assert len(snares) >= 40 and sum(_beat_in_bar(snares)[b] for b in (1, 3)) >= 0.9 * len(snares)
    departures = [e["time"] for e in found["harmonic_departures"]]
    assert [round(t / (4 * BEAT)) for t in departures] == list(AB_BARS)


def _plan(analysis: dict[str, Any], style: str = "classic") -> Plan:
    display = family_yard()
    plan = plan_show(analysis, display_from_preview(display.element()), load_rule_set(),
                     style=get_style(style))
    report = check_choreography(display.element(), plan.choreography, load_rule_set())
    assert report.ok, report.format_text()
    return plan


def _names() -> dict[str, str]:
    display = display_from_preview(family_yard().element())
    return {pid: prop.name for pid, prop in display.props.items()}


def _song_with(**events: list[float]) -> dict[str, Any]:
    analysis = synthetic_analysis(duration=64.0, sections=((0.0, 0.1), (16.0, 0.5),
                                                           (32.0, 0.9), (48.0, 0.5)))
    for key, times in events.items():
        analysis["analysis"][key] = [{"time": t, "strength": 1.0, "confidence": 0.9,
                                      "method": "test"} for t in times]
    return analysis


def test_pillars_follow_the_kick_and_decorations_answer_the_snare() -> None:
    # A kick pattern that is not the beat: one, the "and" of two, and three.
    kicks = [bar * 2.0 + offset for bar in range(32) for offset in (0.0, 0.75, 1.0)]
    snares = [bar * 2.0 + offset for bar in range(32) for offset in (0.5, 1.5)]
    plan = _plan(_song_with(kicks=kicks, snares=snares))
    names = _names()
    kick_cs = {round(t * 100) for t in kicks}
    snare_cs = {round(t * 100) for t in snares}
    loud = [e for e in plan.choreography.effects if 1600 <= e.start_centisecond < 4800]
    pillars = [e.start_centisecond for e in loud if names[e.prop_id].startswith("Pillar")]
    assert pillars and sum(t in kick_cs for t in pillars) >= 0.9 * len(pillars)
    assert any(t % 50 for t in pillars)  # the off-beat kick is used
    decor = [e.start_centisecond for e in loud
             if names[e.prop_id].startswith(("Reindeer", "Snowman"))]
    assert decor and sum(t in snare_cs for t in decor) >= 0.6 * len(decor)


def test_without_drums_the_beat_stands_in() -> None:
    plan = _plan(_song_with())
    names = _names()
    beats = {round(i * BEAT * 100) for i in range(200)}
    pillars = [e.start_centisecond for e in plan.choreography.effects
               if names[e.prop_id].startswith("Pillar") and 1600 <= e.start_centisecond < 4800]
    assert pillars and all(t in beats for t in pillars)


def test_an_unexpected_chord_drops_the_yard_and_the_showpiece_carries_it() -> None:
    plan = _plan(_song_with(harmonic_departures=[40.0]))
    names = _names()
    assert ("departure", 4000) in plan.moments
    during = [e for e in plan.choreography.effects
              if 4000 <= e.start_centisecond and e.end_centisecond <= 4200]
    tree = [e for e in during if names[e.prop_id] == "Mega Tree"]
    rest = [e for e in during if names[e.prop_id] not in {"Mega Tree", "Star"}]
    assert tree and max(max(e.start_intensity, e.end_intensity) for e in tree) == 100
    assert rest and max(max(e.start_intensity, e.end_intensity) for e in rest) <= 30


def _lyrics(*lines: tuple[float, str]) -> dict[str, Any]:
    return {"schema_version": "lyrics-1.0", "source": "imported", "origin": "test",
            "lines": [{"start": start, "end": start + 3.0, "text": text, "words": [],
                       "verified": True} for start, text in lines]}


def test_props_the_singer_names_light_on_the_word() -> None:
    analysis = _song_with()
    analysis["lyrics"] = _lyrics((20.25, "Under the tree"), (24.25, "Build a snowman"),
                                 (26.25, "Build a snowman"), (36.75, "All the reindeer sing"))
    plan = _plan(analysis)
    names = _names()
    cues = [t for kind, t in plan.moments if kind == "lyric_cue"]
    assert cues == [2025, 2425, 3675]  # the second snowman line is too soon after the first

    def flashed(time: int) -> set[str]:
        return {names[e.prop_id] for e in plan.choreography.effects
                if e.start_centisecond == time and e.kind == "fade" and e.end_intensity == 0}

    assert {"Mega Tree", "Homemade Tree 1", "Homemade Tree 2"} <= flashed(2025)
    assert {"Snowman 1", "Snowman 2", "Snowman 3"} <= flashed(2425)
    assert {"Reindeer Left", "Reindeer Right"} <= flashed(3675)


def test_lyrics_come_from_a_music_review_or_a_lyrics_file(tmp_path: Path) -> None:
    analysis = _song_with()
    review = {"schema_version": "music-review-1.0", "analysis": analysis,
              "lyrics": _lyrics((20.25, "Under the tree"))}
    path = tmp_path / "song.review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    loaded = load_analysis(path)
    assert loaded["lyrics"]["lines"][0]["text"] == "Under the tree"

    preview = tmp_path / "yard.lorprev"
    preview.write_bytes(ET.tostring(family_yard().element(), xml_declaration=True,
                                    encoding="utf-8"))
    (tmp_path / "a.json").write_text(json.dumps(analysis), encoding="utf-8")
    (tmp_path / "song.lrc").write_text("[00:20.25]Under the tree\n", encoding="utf-8")
    code = main(["generate", "--preview", str(preview), "--analysis", str(tmp_path / "a.json"),
                 "--lyrics", str(tmp_path / "song.lrc"), "--output",
                 str(tmp_path / "out" / "Show.loredit"), "--no-vocals", "--no-ask"])
    assert code == 0
    plan = json.loads((tmp_path / "out" / "Show.plan.json").read_text(encoding="utf-8"))
    assert {"kind": "lyric_cue", "centisecond": 2025} in plan["moments"]


def test_a_playlist_for_an_s4_display_makes_s4_shows(tmp_path: Path) -> None:
    from tests.test_audio_analysis import _rhythmic_track

    display = tmp_path / "Yard.lms"
    display.write_bytes(s4_sequence())
    songs = tmp_path / "Playlist"
    songs.mkdir()
    _rhythmic_track(songs / "One.wav", duration=10.0)
    code = main(["generate-batch", "--preview", str(display), "--songs", str(songs),
                 "--output", str(tmp_path / "Shows")])
    assert code == 0
    assert (tmp_path / "Shows" / "One.lms").is_file()


def test_a_piece_of_a_fade_that_does_not_change_holds_instead() -> None:
    from lor_sequence_builder.choreography import Effect
    from lor_sequence_builder.planner import _piece

    fade = Effect("p", 0, 0, 1000, "fade", 100, 0, None, None)
    assert _piece(fade, 500, 505).kind in {"on", "fade"}
    flat = Effect("p", 0, 0, 1000, "fade", 50, 49, None, None)
    piece = _piece(flat, 100, 110)
    assert piece.start_intensity == piece.end_intensity and piece.kind == "on"


@pytest.mark.parametrize("seed", range(12))
def test_drums_chords_and_lyrics_never_break_a_rule(seed: int) -> None:
    from tests.display_builders import ALL_DISPLAYS

    rng = np.random.default_rng(seed)
    duration = float(rng.integers(40, 90))
    starts = sorted({0.0, *(float(x) for x in rng.choice(np.arange(8, duration - 8, 2.0),
                                                         size=3, replace=False))})
    analysis = synthetic_analysis(
        duration=duration, bpm=float(rng.integers(80, 160)),
        sections=tuple((s, float(rng.uniform(0.1, 1.0))) for s in starts))
    for key, count in (("kicks", 120), ("snares", 90), ("harmonic_departures", 3)):
        times = sorted(float(t) for t in rng.uniform(0, duration, size=count))
        analysis["analysis"][key] = [{"time": round(t, 3), "strength": 1.0,
                                      "confidence": 0.9, "method": "test"} for t in times]
    analysis["analysis"]["onsets"] = [{"time": round(t, 2), "strength": float(s)}
                                      for t, s in zip(np.arange(0.5, duration - 1, 0.5),
                                                      rng.uniform(0.2, 1.0, 400), strict=False)]
    words = ["tree", "star", "snowman", "reindeer", "arch", "snow", "pillar", "the", "light"]
    analysis["lyrics"] = _lyrics(*((round(float(t), 2), " ".join(rng.choice(words, size=3)))
                                   for t in sorted(rng.uniform(0, duration - 3, size=10))))
    for builder in ALL_DISPLAYS:
        display = builder()
        for style in ("classic", "energetic", "elegant"):
            plan = plan_show(analysis, display_from_preview(display.element()),
                             load_rule_set(), style=get_style(style))
            report = check_choreography(display.element(), plan.choreography, load_rule_set())
            assert report.ok, f"{builder.__name__} {style}: {report.format_text()}"
