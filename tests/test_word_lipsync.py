"""Lip-sync from a WhisperX word file: the face sings the chosen singer's words."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.vocals import (
    VocalAnalysisError,
    load_vocals,
    singers,
    vocals_from_words,
)
from tests.test_planner import synthetic_analysis
from tests.test_wiring import wired_yard


def whisperx() -> dict[str, Any]:
    """An invented WhisperX result: SPEAKER_00 sings two lines, SPEAKER_01 one."""
    def line(start: float, text: str, speaker: str) -> dict[str, Any]:
        words, t = [], start
        for word in text.split():
            words.append({"word": word, "start": round(t, 2), "end": round(t + 0.4, 2),
                          "score": 0.9, "speaker": speaker})
            t += 0.5
        return {"start": start, "end": t, "text": text, "speaker": speaker, "words": words}

    return {"segments": [line(10.0, "you're a mean one mister grinch", "SPEAKER_00"),
                         line(20.0, "you really are a heel", "SPEAKER_00"),
                         line(30.0, "la la la", "SPEAKER_01")],
            "language": "en"}


def test_words_become_lines_and_syllables_for_the_chosen_singer() -> None:
    data = whisperx()
    assert singers(data) == [("SPEAKER_00", 11), ("SPEAKER_01", 3)]
    vocals = vocals_from_words(data)
    assert [(r["start"], r["end"]) for r in vocals["regions"]] == [(10.0, 12.9), (20.0, 22.4)]
    # "mister" has two syllables: two mouth openings inside the word.
    inside = [s for s in vocals["syllables"] if 12.0 <= s["start"] < 12.4]
    assert len(inside) == 2 and inside[0]["end"] < inside[1]["start"]
    other = vocals_from_words(data, "SPEAKER_01")
    assert [(r["start"], r["end"]) for r in other["regions"]] == [(30.0, 31.4)]
    with pytest.raises(VocalAnalysisError, match="no singer"):
        vocals_from_words(data, "SPEAKER_07")
    with pytest.raises(VocalAnalysisError, match="no timed words"):
        vocals_from_words({"segments": []})


def test_a_face_sings_from_a_word_file(tmp_path: Path) -> None:
    path = tmp_path / "grinch.json"
    path.write_text(json.dumps(whisperx()), encoding="utf-8")
    vocals = load_vocals(path)
    display = wired_yard()
    element = display.element()
    rules = load_rule_set()
    plan = plan_show(synthetic_analysis(duration=40.0), display_from_preview(element), rules,
                     vocals)
    assert check_choreography(element, plan.choreography, rules).ok
    up = display.prop_id("Santa Mustache Up")
    opened = [e for e in plan.choreography.effects if e.prop_id == up]
    # The mouth opens only on SPEAKER_00's words, never on SPEAKER_01's line.
    assert opened and all(1000 <= e.start_centisecond < 2300 for e in opened)


def test_new_show_takes_a_word_file(tmp_path: Path) -> None:
    from lor_sequence_builder.show_builder import ShowBuildError, ShowSessions
    from tests.test_planner import _preview

    sessions = ShowSessions()
    preview = _preview(tmp_path, wired_yard())
    started = sessions.start(preview.read_bytes(), "yard.lorprev")
    result = sessions.add_words(started["token"], json.dumps(whisperx()).encode())
    assert result == {"singers": [{"name": "SPEAKER_00", "words": 11},
                                  {"name": "SPEAKER_01", "words": 3}], "words": 14}
    with pytest.raises(ShowBuildError, match="not a word file"):
        sessions.add_words(started["token"], b'{"text": "hello"}')
    sessions.close()
