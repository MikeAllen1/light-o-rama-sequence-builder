"""The 10-second display test: every prop lights in a fixed order, and it passes the rules."""

from __future__ import annotations

import base64
import io
import json
import wave
import zipfile
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.display_test import SOUND_NAME, build_display_test
from lor_sequence_builder.loredit import effect_timing_problems, read_loredit
from tests.display_builders import ALL_DISPLAYS, classic_yard, unsupported_hardware
from tests.test_planner import _preview
from tests.test_show_builder import _json, _post, server  # noqa: F401 - fixture

BUILDERS = [b for b in ALL_DISPLAYS if b is not unsupported_hardware]


def _effects(path: Path) -> dict[str, list[tuple[int, int, int]]]:
    """Per prop name: (channel, start, end) of every effect."""
    root = read_loredit(path).root
    found: dict[str, list[tuple[int, int, int]]] = {}
    for prop in root.findall("SequenceProps/SeqProp"):
        for index, channel in enumerate(prop.findall("channel")):
            for effect in channel.findall("effect"):
                found.setdefault(prop.attrib["name"], []).append(
                    (index, int(effect.attrib["startCentisecond"]),
                     int(effect.attrib["endCentisecond"])))
    return found


@pytest.mark.parametrize("builder", BUILDERS, ids=lambda b: b.__name__)
def test_every_display_gets_a_test_that_passes_the_rules(builder: Any, tmp_path: Path) -> None:
    test = build_display_test(_preview(tmp_path, builder()), tmp_path / "test")
    assert test.report.ok, test.report.format_text()
    document = read_loredit(test.sequence_path)
    assert document.root.attrib["musicFilename"] == SOUND_NAME
    assert int(document.root.attrib["totalCentiseconds"]) == 1000
    assert effect_timing_problems(document) == []
    with wave.open(str(test.sound_path)) as sound:
        assert round(sound.getnframes() / sound.getframerate()) == 10


def test_the_test_lights_kinds_then_sweeps_then_everything(tmp_path: Path) -> None:
    test = build_display_test(_preview(tmp_path, classic_yard()), tmp_path / "test")
    steps = [what.split(":")[0] for _, _, what in test.schedule]
    assert steps == ["arches", "mini trees", "mega trees", "singing faces",
                     "sweep from left to right", "everything on, then fade out"]
    effects = _effects(test.sequence_path)
    # The mega tree's 16 channels come on one after another, in channel order.
    tree = sorted(e for e in effects["Mega Tree"] if e[1] < 650)
    assert [c for c, _, _ in tree] == list(range(16))
    assert all(a[1] < b[1] for a, b in pairwise(tree))
    # The sweep runs left to right: Arch 1 before Arch 4 before the mega tree.
    sweep = {name: min(s for _, s, _ in found if 650 <= s < 900)
             for name, found in effects.items() if any(650 <= s < 900 for _, s, _ in found)}
    assert sweep["Arch 1"] < sweep["Arch 4"] < sweep["Mega Tree"]
    # Every sequenced prop is on together at 9.0 s.
    assert all(any(s <= 900 < e for _, s, e in found) for found in effects.values())
    notes = test.notes_path.read_text(encoding="utf-8")
    assert "Copy 'LOR Display Test.wav' into S6's audio folder" in notes
    assert "arches: Arch 1, Arch 2, Arch 3, Arch 4" in notes
    assert "Tree Topper" in notes  # follows the mega tree, so it is not in the test


def test_a_face_steps_through_its_mouths_with_the_outline_on(tmp_path: Path) -> None:
    from tests.display_builders import line_drawn_yard

    test = build_display_test(_preview(tmp_path, line_drawn_yard()), tmp_path / "test")
    assert test.report.ok, test.report.format_text()
    effects = _effects(test.sequence_path)
    mouths = {name: found for name, found in effects.items() if "mouth" in name.lower()}
    assert len(mouths) >= 2
    spans = sorted((s, e) for found in mouths.values() for _, s, e in found if s < 650)
    assert all(a[1] <= b[0] for a, b in pairwise(spans))  # one at a time


def test_the_cli_writes_the_test(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    preview = _preview(tmp_path, classic_yard())
    assert main(["display-test", "--preview", str(preview), "--output",
                 str(tmp_path / "t")]) == 0
    assert "copy it into S6's audio folder" in capsys.readouterr().out
    assert main(["display-test", "--preview", str(preview), "--output",
                 str(tmp_path / "t")]) == 2


def test_new_show_makes_a_test_to_save_and_watch(server: str, tmp_path: Path) -> None:  # noqa: F811
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    status, started = _post(server + "/api/show/start?name=yard.lorprev", preview,
                            "application/xml")
    assert status == 200
    status, test = _json(f"{server}/api/show/test?token={started['token']}", {})
    assert status == 200, test
    names = zipfile.ZipFile(io.BytesIO(base64.b64decode(test["zip"]))).namelist()
    assert set(names) == {test["file_name"], SOUND_NAME, test["file_name"].replace(
        ".loredit", " - what to watch.txt")}
    assert test["schedule"][0]["what"].startswith("arches")
    assert json.dumps(test)  # all plain JSON
