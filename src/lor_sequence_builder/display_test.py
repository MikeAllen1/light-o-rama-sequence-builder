"""A 10-second display test: confirm every prop is wired and plays before a full show.

The test lights the display in a fixed, predictable order, so anything dark or out
of place in the yard points straight at a wiring or setup problem:

1. 0.0 to 0.5 s: dark.
2. 0.5 to 6.5 s: one kind of prop at a time (outlines, icicles, arches, mini trees,
   mega trees, stars, snowflakes, faces, decorations, other props). A prop with
   several channels lights them one after another in channel order, so a strand
   wired backwards or a dead channel shows. A singing face shows its outline and
   steps through each mouth shape.
3. 6.5 to 9.0 s: a sweep across the yard from left to right, one prop after another
   in their preview positions.
4. 9.0 to 10.0 s: everything on, then a fade out.

It comes with ``LOR Display Test.wav``, a short sound with a tick at each step, so
S6 plays it like any show: put the sound in S6's audio folder. A text file lists
when each prop should light. The test passes the same rules as every show.
"""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from lor_sequence_builder.choreography import Choreography, Effect, Section
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.planner import _faces
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.rules import RuleReport, display_from_preview, load_rule_set
from lor_sequence_builder.rules.engine import Display
from lor_sequence_builder.sequence_writer import build_from_timeline

TEST_CENTISECONDS = 1000
SOUND_NAME = "LOR Display Test.wav"
KIND_ORDER = ("outline", "icicles", "arch", "mini_tree", "mega_tree", "star", "snowflake",
              "singing_face", "decor", "unknown")
KIND_WORDS = {
    "outline": "outlines", "icicles": "icicles", "arch": "arches", "mini_tree": "mini trees",
    "mega_tree": "mega trees", "star": "stars", "snowflake": "snowflakes",
    "singing_face": "singing faces", "decor": "decorations", "unknown": "other props",
}
_KINDS = (50, 650)
_SWEEP = (650, 900)
_ALL = (900, 960)
_RATE = 22_050


@dataclass
class DisplayTest:
    sequence_path: Path
    sound_path: Path
    notes_path: Path
    report: RuleReport
    schedule: list[tuple[int, int, str]] = field(default_factory=list)


def _time(cs: int) -> str:
    return f"{cs // 100}.{cs % 100:02d} s"


def _plan(display: Display) -> tuple[Choreography, list[tuple[int, int, str]], list[int]]:
    rules = load_rule_set()
    usable = {pid for pid, p in display.props.items() if p.sequenceable}
    faces = _faces(display, rules, usable)
    mouths = {pid for face in faces for pid in face.mouths.values()}
    effects: list[Effect] = []
    schedule: list[tuple[int, int, str]] = []
    ticks: list[int] = []
    vocal_regions: list[tuple[int, int]] = []

    def light(pid: str, start: int, end: int, level: int = 100) -> None:
        prop = display.props[pid]
        for channel in range(prop.channel_count):
            effects.append(Effect(pid, channel, start, end, "on", level, level, None, None))

    def wipe(pid: str, start: int, end: int) -> None:
        """Channels light one after another in order and stay on: shows wiring order."""
        count = display.props[pid].channel_count
        step = min(15, max(1, (end - start) * 6 // 10 // max(1, count)))
        for channel in range(count):
            effects.append(Effect(pid, channel, start + channel * step, end, "on", 100, 100,
                                  None, None))

    kinds = [kind for kind in KIND_ORDER
             if any(p.role == kind and p.prop_id in usable for p in display.props.values())]
    slot = (_KINDS[1] - _KINDS[0]) // max(1, len(kinds))
    for index, kind in enumerate(kinds):
        start = _KINDS[0] + index * slot
        end = start + slot - 10
        ticks.append(start)
        members = sorted((p for p in display.props.values()
                          if p.role == kind and p.prop_id in usable), key=lambda p: p.name)
        if kind == "singing_face":
            for face in faces:
                for pid in face.members - set(face.mouths.values()):
                    wipe(pid, start, end)
                shapes = list(face.mouths.values())
                if shapes:
                    vocal_regions.append((start, end))
                    width = (end - start) // len(shapes)
                    for k, pid in enumerate(shapes):
                        light(pid, start + k * width, start + (k + 1) * width)
            names = [p.name for p in members]
        else:
            for prop in members:
                wipe(prop.prop_id, start, end)
            names = [p.name for p in members]
        schedule.append((start, end, f"{KIND_WORDS[kind]}: {', '.join(names)}"))

    # Left to right across the yard; mouths stay with their face test.
    placed = sorted((p for p in display.props.values()
                     if p.prop_id in usable and p.prop_id not in mouths),
                    key=lambda p: (p.center is None, p.center[0] if p.center else 0.0, p.name))
    if placed:
        step = max(4, (_SWEEP[1] - _SWEEP[0]) // len(placed))
        ticks.append(_SWEEP[0])
        for k, prop in enumerate(placed):
            start = _SWEEP[0] + min(k * step, _SWEEP[1] - _SWEEP[0] - 10)
            light(prop.prop_id, start, min(_SWEEP[1], start + max(20, 2 * step)))
        schedule.append((_SWEEP[0], _SWEEP[1], "sweep from left to right: "
                         + ", ".join(p.name for p in placed)))
        ticks.append(_ALL[0])
        for prop in placed:
            light(prop.prop_id, _ALL[0], _ALL[1])
            for channel in range(prop.channel_count):
                effects.append(Effect(prop.prop_id, channel, _ALL[1], TEST_CENTISECONDS - 5,
                                      "fade", 100, 0, None, None))
        schedule.append((_ALL[0], TEST_CENTISECONDS, "everything on, then fade out"))
    sections = (Section("test", 0, TEST_CENTISECONDS),)
    return (Choreography(TEST_CENTISECONDS, tuple(effects), (), sections, (),
                         tuple(vocal_regions)), schedule, ticks)


def test_sound(path: Path, ticks: list[int]) -> Path:
    """Ten seconds of sound: a tick at each step, a rising glide for the sweep."""
    total = int(TEST_CENTISECONDS / 100 * _RATE)
    song = np.zeros(total)
    for at in ticks:
        start = int(at / 100 * _RATE)
        n = min(int(0.12 * _RATE), total - start)
        k = np.arange(n) / _RATE
        song[start:start + n] += 0.5 * np.sin(2 * math.pi * 880 * k) * np.exp(-k / 0.03)
    a, b = int(_SWEEP[0] / 100 * _RATE), int(_SWEEP[1] / 100 * _RATE)
    k = np.arange(b - a) / _RATE
    frequency = 330 + 330 * k / k[-1]
    song[a:b] += 0.15 * np.sin(2 * math.pi * np.cumsum(frequency) / _RATE)
    c = int(_ALL[0] / 100 * _RATE)
    k = np.arange(total - c) / _RATE
    chord = sum(np.sin(2 * math.pi * f * k) for f in (523.25, 659.25, 783.99))
    song[c:] += 0.2 * chord * np.exp(-k / 0.5)
    data = (song / np.max(np.abs(song)) * 0.7 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(_RATE)
        stream.writeframes(data.tobytes())
    return path


def build_display_test(preview_path: str | Path, folder: str | Path,
                       name: str = "Display Test") -> DisplayTest:
    """Write ``<name>.loredit``, the sound and the notes into ``folder`` (new or empty)."""
    target = Path(folder)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Choose an empty or new folder for the display test: {target}")
    target.mkdir(parents=True, exist_ok=True)
    preview = preview_element(read_lorprev(preview_path))
    display = display_from_preview(preview)
    choreography, schedule, ticks = _plan(display)
    sound = test_sound(target / SOUND_NAME, ticks)
    written = build_from_timeline(preview_path, choreography, load_rule_set(), SOUND_NAME,
                                  target / f"{name}.loredit", target / f"{name}.rules.json")
    skipped = sorted(p.name for p in display.props.values() if not p.sequenceable)
    lines = [
        f"{name}: a 10-second display test",
        "",
        f"1. Copy '{SOUND_NAME}' into S6's audio folder, so the sequence finds its sound.",
        f"2. Open '{name}.loredit' in the S6 Sequencer and play it with the display connected.",
        "3. Watch the yard. Each line below says what should light and when; anything dark",
        "   or out of order points at wiring, a controller address, or the preview.",
        "",
        "0.00 s  dark",
        *(f"{_time(a)} to {_time(b)}  {what}" for a, b, what in schedule),
        "",
        "Props with several channels light them one after another in channel order:",
        "a strand that lights in the wrong order is wired or numbered backwards.",
    ]
    if skipped:
        lines += ["", "Not in the test (they cannot be sequenced, for example pixel or DMX "
                  "props, or props driven by another prop): " + ", ".join(skipped)]
    notes = target / f"{name} - what to watch.txt"
    notes.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")
    return DisplayTest(written.sequence_path, sound, notes, written.report, schedule)
