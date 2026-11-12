"""Learning a style from sequences someone made by hand. Every sequence here is invented."""

from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lor_sequence_builder import style_learning
from lor_sequence_builder.cli import main
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.style import HIGH, LOW, MID, STYLES, get_style
from lor_sequence_builder.style_learning import (
    Lit,
    StyleLearningError,
    combine,
    from_json,
    learn,
    measure,
    measure_effects,
    nearest,
    style_from_habits,
    to_json,
)
from lor_sequence_builder.ui_server import SequencerRequestHandler
from tests.display_builders import classic_yard, family_yard
from tests.test_lms import s4_sequence
from tests.test_planner import _preview, synthetic_analysis

BEAT = 50
SONG = 6000
NAMES = [f"Secret Prop {i}" for i in range(8)]

# One effect: (channel, start, end, settings, start intensity, end intensity).
Hand = list[tuple[int, int, int, str, int, int]]


def punchy() -> Hand:
    """Quick full-brightness hits on the half beat, cut off sharp, a few at a time."""
    return [(k % 8, t, t + BEAT // 2, "INTENSITY", 100, 100)
            for k, t in enumerate(range(0, SONG, BEAT // 2))] + [
            (c, t, t + BEAT // 2, "INTENSITY", 100, 100)
            for t in range(0, SONG, 8 * BEAT) for c in range(8)]


def flowing() -> Hand:
    """Long soft fades over two bars, never above 60%."""
    effects: Hand = []
    for c in range(8):
        for t in range(c * 2 * BEAT, SONG - 8 * BEAT, 16 * BEAT):
            effects.append((c, t, t + 4 * BEAT, "INTENSITY", 0, 60))
            effects.append((c, t + 4 * BEAT, t + 8 * BEAT, "INTENSITY", 60, 0))
    return effects


def twinkly() -> Hand:
    """Steady beat hits, with stars twinkling under them."""
    return [(k % 6, t, t + BEAT, "INTENSITY", 100, 100)
            for k, t in enumerate(range(0, SONG, BEAT))] + [
            (6 + k % 2, t, t + 4 * BEAT, "TWINKLE", 80, 80)
            for k, t in enumerate(range(0, SONG, 4 * BEAT))]


def write_loredit(path: Path, effects: Hand, grid: bool = True) -> Path:
    root = ET.Element("sequence", {"saveFileVersion": "15", "totalCentiseconds": str(SONG)})
    preview = ET.SubElement(root, "PreviewClass", {"id": "preview", "Name": "Invented Yard"})
    for index, name in enumerate(NAMES):
        ET.SubElement(preview, "PropClass", {"id": f"p{index}", "Name": name})
    props = ET.SubElement(root, "SequenceProps")
    channels = []
    for index, name in enumerate(NAMES):
        prop = ET.SubElement(props, "SeqProp", {"id": f"p{index}", "name": name})
        channels.append(ET.SubElement(prop, "channel"))
    for channel, start, end, settings, first, last in sorted(effects, key=lambda e: e[:2]):
        attributes = {"startCentisecond": str(start), "endCentisecond": str(end),
                      "settings": settings}
        if first == last:
            attributes["intensity"] = str(first)
        else:
            attributes |= {"startIntensity": str(first), "endIntensity": str(last)}
        ET.SubElement(channels[channel], "effect", attributes)
    grids = ET.SubElement(root, "TimingGrids")
    if grid:
        free = ET.SubElement(grids, "TimingGridFree", {"name": "My beats"})
        for t in range(0, SONG, BEAT):
            ET.SubElement(free, "timing", {"centisecond": str(t)})
    path.write_bytes(ET.tostring(root))
    return path


def test_a_quick_punchy_sequencer_gets_a_quick_punchy_style(tmp_path: Path) -> None:
    habits = measure(write_loredit(tmp_path / "Rock Song.loredit", punchy()))
    assert habits.beat == BEAT and habits.beat_from_grid
    assert habits.hold_beats < 0.75 and habits.fade_share == 0
    style, changes = style_from_habits(habits, "Dad's style")
    assert nearest(habits) == "energetic"
    assert style.key == "mine:dad-s-style" and style.name == "Dad's style"
    assert style.soft == (False, False, False) and style.flashes
    assert any("Starts from High energy" in c for c in changes)


def test_a_slow_soft_sequencer_gets_a_slow_soft_style(tmp_path: Path) -> None:
    habits = measure(write_loredit(tmp_path / "Ballad.loredit", flowing()))
    assert habits.hold_beats == 4 and habits.fade_share == 1 and habits.brightness == 60
    style, changes = style_from_habits(habits)
    assert nearest(habits) == "elegant"
    assert style.soft == (True, True, True)
    # The loud parts peak at the brightness this person uses.
    assert style.brightness[HIGH] == 60 and style.brightness[LOW] < style.brightness[MID]
    # Lights that stay on much longer than Elegant's move on slower grids.
    assert STYLES["elegant"].part("family").grid[MID] == "bar"
    assert style.part("family").grid[MID] == "phrase"
    assert "Peaks at 60% brightness." in changes


def test_twinkles_are_learned(tmp_path: Path) -> None:
    style, habits, changes = learn([write_loredit(tmp_path / "Twinkle.loredit", twinkly())])
    assert habits.twinkle_share > 0.1
    assert style.part("star").motion == ("twinkle", "twinkle", "twinkle")
    assert style.part("outline").motion[LOW] == "twinkle"
    assert any("Twinkles" in c for c in changes)


def test_the_beat_comes_from_effects_when_there_is_no_timing_grid(tmp_path: Path) -> None:
    habits = measure(write_loredit(tmp_path / "No grid.loredit", twinkly(), grid=False))
    assert habits.beat == BEAT and not habits.beat_from_grid


def test_s4_sequences_can_be_learned_from(tmp_path: Path) -> None:
    root = ET.fromstring(s4_sequence())
    channels = root.findall("channels/channel")
    for channel in channels:
        for effect in channel.findall("effect"):
            channel.remove(effect)
    for c, start, end, settings, first, last in flowing():
        if c >= len(channels):
            continue
        attributes = {"type": "twinkle" if settings == "TWINKLE" else "intensity",
                      "startCentisecond": str(start), "endCentisecond": str(end),
                      "startIntensity": str(first), "endIntensity": str(last)}
        ET.SubElement(channels[c], "effect", attributes)
    path = tmp_path / "Old Show.lms"
    path.write_bytes(ET.tostring(root))
    habits = measure(path)
    assert habits.fade_share == 1 and nearest(habits) == "elegant"


def test_several_sequences_are_weighted_by_their_effects(tmp_path: Path) -> None:
    a = measure(write_loredit(tmp_path / "a.loredit", punchy()))
    b = measure(write_loredit(tmp_path / "b.loredit", flowing()))
    both = combine([a, b])
    assert both.sequences == 2 and both.effects == a.effects + b.effects
    assert a.fade_share < both.fade_share < b.fade_share
    assert both.fade_share == pytest.approx(b.effects / both.effects)


@pytest.mark.parametrize("problem,message", [
    ("few", "too few effects"), ("suffix", "learn from .loredit"),
    ("broken", "Invalid or unsafe"),
])
def test_unusable_sequences_are_refused_plainly(tmp_path: Path, problem: str,
                                                message: str) -> None:
    if problem == "few":
        path = write_loredit(tmp_path / "short.loredit", punchy()[:5])
    elif problem == "suffix":
        path = tmp_path / "song.mp3"
        path.write_bytes(b"ID3")
    else:
        path = tmp_path / "broken.loredit"
        path.write_text("<sequence", encoding="utf-8")
    with pytest.raises(StyleLearningError, match=message):
        measure(path)


def _plan_lits(plan: object) -> list[Lit]:
    return [Lit(f"{e.prop_id}/{e.channel_index}", e.start_centisecond, e.end_centisecond,
                 "twinkle" if e.kind in {"twinkle", "shimmer"} else
                 "fade" if e.kind == "fade" else "on",
                 max(e.start_intensity, e.end_intensity))
            for e in plan.choreography.effects]  # type: ignore[attr-defined]


@pytest.mark.parametrize("yard", [family_yard, classic_yard])
def test_each_built_in_style_is_recognized_from_its_own_shows(
        yard: Callable[[], object]) -> None:
    # The signatures the learner compares against are what the built-in styles'
    # own shows measure: learning from one of them finds that style.
    display = display_from_preview(yard().element())  # type: ignore[attr-defined]
    analysis = synthetic_analysis()
    beats = [round(b["time"] * 100) for b in analysis["analysis"]["beats"]]
    for key in STYLES:
        plan = plan_show(analysis, display, load_rule_set(), style=get_style(key))
        lits = _plan_lits(plan)
        habits = measure_effects(lits, len({lit.channel for lit in lits}), beats)
        assert nearest(habits) == key


def test_a_style_file_holds_only_measurements(tmp_path: Path) -> None:
    style, habits, _ = learn([write_loredit(tmp_path / "Ballad.loredit", flowing())],
                             "Porch style")
    text = to_json(style, habits, nearest(habits))
    # Nothing of the sequence itself: no prop names, no file names.
    assert not any(name in text for name in NAMES) and "Ballad" not in text
    again, same = from_json(text)
    assert again == style and same.to_dict() == habits.to_dict()
    data = json.loads(text)
    data["habits"]["brightness"] = 900
    with pytest.raises(StyleLearningError, match="out of range"):
        from_json(json.dumps(data))
    with pytest.raises(StyleLearningError, match="Not a learned style"):
        from_json('{"schema": "other"}')
    with pytest.raises(StyleLearningError, match="too large"):
        from_json(" " * (style_learning.MAX_STYLE_BYTES + 1))


def test_kept_styles_are_listed_used_and_removed(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(style_learning, "styles_folder", lambda: tmp_path / "styles")
    style, habits, _ = learn([write_loredit(tmp_path / "a.loredit", punchy())], "Garage")
    key = style_learning.save(style, habits)
    assert key == "mine:garage"
    assert [s.name for s in style_learning.saved()] == ["Garage"]
    assert get_style("mine:garage") == style
    display = display_from_preview(classic_yard().element())
    plan = plan_show(synthetic_analysis(), display, load_rule_set(), style=get_style(key))
    assert check_choreography(classic_yard().element(), plan.choreography, load_rule_set()).ok
    style_learning.remove_saved(key)
    assert style_learning.saved() == []
    with pytest.raises(ValueError, match="removed"):
        get_style("mine:garage")
    for bad in ("mine:../escape", "mine:", "garage"):
        with pytest.raises(StyleLearningError):
            style_learning.load_saved(bad)


def test_learn_style_and_generate_with_it_on_the_command_line(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sequence = write_loredit(tmp_path / "Mine.loredit", flowing())
    style_file = tmp_path / "porch.json"
    assert main(["learn-style", str(sequence), "--name", "Porch", "--output",
                 str(style_file)]) == 0
    out = capsys.readouterr().out
    assert "Learned 'Porch' from 1 sequence(s)" in out and "Starts from Elegant" in out
    assert main(["learn-style", str(sequence), "--output", str(style_file)]) == 2
    analysis = tmp_path / "song.analysis.json"
    analysis.write_text(json.dumps(synthetic_analysis()), encoding="utf-8")
    preview = _preview(tmp_path, classic_yard())
    assert main(["generate", "--preview", str(preview), "--analysis", str(analysis),
                 "--output", str(tmp_path / "show.loredit"), "--music-filename", "song.mp3",
                 "--style-file", str(style_file), "--no-ask"]) == 0
    assert "Style: Porch." in (tmp_path / "show.plan.json").read_text(encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["generate", "--preview", str(preview), "--analysis", str(analysis),
                 "--output", str(tmp_path / "other.loredit"), "--music-filename", "song.mp3",
                 "--style-file", str(bad), "--no-ask"]) == 2


@pytest.fixture
def local_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setattr(style_learning, "styles_folder", lambda: tmp_path / "styles")
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(server.server_address[1])
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def _post(url: str, data: bytes, kind: str) -> dict[str, object]:
    request = Request(url, data=data, headers={"Content-Type": kind}, method="POST")
    with urlopen(request, timeout=10) as response:
        result: dict[str, object] = json.loads(response.read())
        return result


def test_the_app_learns_keeps_and_removes_a_style(local_server: str, tmp_path: Path) -> None:
    habits = []
    for name, effects in (("One.loredit", punchy()), ("Two.loredit", twinkly())):
        content = write_loredit(tmp_path / name, effects).read_bytes()
        result = _post(f"{local_server}/api/style/measure?name={name}", content,
                       "application/octet-stream")
        assert result["file"] == name
        habits.append(result["habits"])
    kept = _post(f"{local_server}/api/style/keep",
                 json.dumps({"name": "Front yard", "habits": habits}).encode(),
                 "application/json")
    assert kept["style"] == {**get_style("mine:front-yard").to_dict(), "learned": True}
    keys = [s["key"] for s in kept["styles"]]  # type: ignore[attr-defined]
    assert keys == [*STYLES, "mine:front-yard"]
    listed = _post(f"{local_server}/api/style/list", b"{}", "application/json")
    assert listed["styles"] == kept["styles"]
    removed = _post(f"{local_server}/api/style/remove",
                    json.dumps({"key": "mine:front-yard"}).encode(), "application/json")
    assert [s["key"] for s in removed["styles"]] == list(STYLES)  # type: ignore[attr-defined]
    with pytest.raises(HTTPError) as refused:
        _post(f"{local_server}/api/style/measure?name=notes.txt", b"hello",
              "application/octet-stream")
    assert refused.value.code == 422
    with pytest.raises(HTTPError) as tampered:
        _post(f"{local_server}/api/style/keep",
              json.dumps({"name": "x", "habits": [{"beat": 1}]}).encode(), "application/json")
    assert tampered.value.code == 422


def test_new_show_learns_a_style_from_chosen_sequences(local_server: str,
                                                        tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    summary = {
        "token": "learn-token", "display": "Learning Yard",
        "props": [{"name": "Tree", "role": "tree", "sequenceable": True, "reason": None}],
        "kinds": [{"role": "tree", "label": "tree", "count": 1, "plural": "trees"}],
        "groups": [], "faces": False, "can_separate_vocals": False, "can_translate": False,
        "styles": [{**STYLES[k].to_dict(), "learned": False} for k in STYLES],
        "default_style": "classic", "requirements": [], "raw_requirements": [],
    }
    files = [{"name": name, "mimeType": "application/octet-stream",
              "buffer": write_loredit(tmp_path / name, effects).read_bytes()}
             for name, effects in (("Ballad.loredit", flowing()),
                                   ("Notes.loredit", punchy()[:3]))]
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/api/show/start*", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(summary)))
        page.goto(local_server + "/")
        page.locator("#welcomeNewShow").click()
        page.locator("#showDisplayFile").set_input_files(
            {"name": "yard.lorprev", "mimeType": "application/xml", "buffer": b"<preview/>"})
        page.locator("#displayStatus").filter(has_text="Learning Yard").wait_for()
        page.locator("#learnStyleName").fill("Porch lights")
        page.locator("#learnStyleFiles").set_input_files(files)
        status = page.locator("#learnStatus")
        status.filter(has_text="Learned").wait_for()
        text = status.inner_text()
        assert "Porch lights" in text and "Starts from Elegant" in text
        assert "Skipped" in text and "too few effects" in text
        chosen = page.locator('input[name="showStyle"]:checked')
        assert chosen.get_attribute("value") == "mine:porch-lights"
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Remove the style Porch lights").click()
        status.filter(has_text="Removed").wait_for()
        assert page.locator('input[name="showStyle"]').count() == len(STYLES)
        assert page.locator('input[name="showStyle"]:checked').get_attribute(
            "value") == "classic"
        browser.close()
