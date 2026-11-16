"""Pixel props: found in the display, a choice to light, written the way S6 stores them."""

from __future__ import annotations

import dataclasses
import itertools
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.channel_mapping import channel_layout_problem
from lor_sequence_builder.classifier import classify_preview
from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.pixels import OPTIONS, palette, pixel_count, plan_pixels, settings
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rgb import is_pixel
from lor_sequence_builder.rules import display_from_preview, load_rule_set
from lor_sequence_builder.rules.profile import Requirement, Selector
from lor_sequence_builder.sequence_writer import build_from_timeline
from lor_sequence_builder.style import get_style
from tests.display_builders import DisplayBuilder, roofline_house
from tests.test_planner import synthetic_analysis

# Settings strings copied from the S6 sequence the format comes from.
EVIDENCE = {
    "wash": "Mix_Average|0|0|full|20|lightorama_colorwash:FFFF0000,0;FF00FF00,1;FF0000FF,0;"
            "FFFFFF00,0;FFFFFFFF,0;FF000000,0:full,full,single_color|lightorama_none:FFFF0000,0;"
            "FF00FF00,0;FF0000FF,0;FFFFFF00,0;FFFFFFFF,0;FF000000,0:",
}


def with_pixels() -> DisplayBuilder:
    display = roofline_house()
    display.add("Pixel Mega Tree", "mega_tree", shape="Tree 180", channels=8,
                box=(0.6, 0.0, 0.25, 0.7), device="DMX", string_type="RGB",
                traditional="Channel_per_color", start="Bottom Left")
    display.add("Pixel Roof", "outline", shape="Lines-Connected", points=[(-0.8, 0.5), (0.4, 0.5)],
                device="DMX", string_type="RGB", traditional="Multicolor_string_1_ch",
                start="Left")
    root = display.element()
    for prop in root.findall("PropClass"):
        if prop.get("Name") == "Pixel Mega Tree":
            prop.set("ChannelGrid", ";".join(f"Regular,{32 + i},1,300,0," for i in range(8)))
        elif prop.get("Name") == "Pixel Roof":
            prop.set("ChannelGrid", "Regular,64,1,150,0,Red")
    return display


def _pixel_ids(display: DisplayBuilder) -> set[str]:
    return {display.prop_id("Pixel Mega Tree"), display.prop_id("Pixel Roof")}


def test_pixel_props_are_recognized_and_counted() -> None:
    preview = with_pixels().element()
    tree = next(p for p in preview.findall("PropClass") if p.get("Name") == "Pixel Mega Tree")
    roof = next(p for p in preview.findall("PropClass") if p.get("Name") == "Pixel Roof")
    assert is_pixel(dict(tree.attrib)) and is_pixel(dict(roof.attrib))
    assert pixel_count(dict(tree.attrib)) == 800 and pixel_count(dict(roof.attrib)) == 50
    assert channel_layout_problem(tree) is not None  # never sequenced as channels
    kinds = {c.name: c.color_capability.kind for c in classify_preview(preview)}
    assert kinds["Pixel Mega Tree"] == kinds["Pixel Roof"] == "pixel"


def test_settings_match_the_s6_format_exactly() -> None:
    assert settings("wash", ["green"]) == EVIDENCE["wash"]
    assert palette(["red", "white"]).split(";") == [
        "FFFF0000,1", "FF00FF00,0", "FF0000FF,0", "FFFFFF00,0", "FFFFFFFF,1", "FF000000,0"]
    assert palette(["gold"]).split(";")[0] == "FFFFB000,1"  # takes a free slot
    for key in OPTIONS:
        parts = settings(key, ["red"]).split("|")
        assert len(parts) == 7 and parts[0] == "Mix_Average" and parts[6].startswith(
            "lightorama_none:")


def _plan(display: DisplayBuilder, rules=None):  # type: ignore[no-untyped-def]
    preview = display.element()
    rules = rules or load_rule_set()
    shown = display_from_preview(preview)
    style = get_style("classic")
    analysis = synthetic_analysis(duration=40.0)
    plan = plan_show(analysis, shown, rules, style=style)
    downbeats = [round(float(b["time"]) * 100) for b in analysis["analysis"]["downbeats"]]
    pixels = plan_pixels(preview, shown, rules, plan.choreography, plan.sections, downbeats,
                         style.palette, style.phrase_bars)
    return preview, plan, pixels


def test_pixel_effects_follow_the_music_and_go_dark_with_the_show() -> None:
    display = with_pixels()
    _, plan, pixels = _plan(display)
    assert set(pixels.prop_ids) == _pixel_ids(display) and pixels.notes
    lit = [(e.start_centisecond, e.end_centisecond) for e in plan.choreography.effects]
    for prop_id in pixels.prop_ids:
        mine = sorted((e for e in pixels.effects if e.prop_id == prop_id),
                      key=lambda e: e.start_centisecond)
        assert len({e.effect for e in mine}) >= 3  # more than one idea
        for before, after in itertools.pairwise(mine):
            assert before.end_centisecond <= after.start_centisecond  # one at a time
        for effect in mine:
            # Never lit while the rest of the show is dark.
            assert any(a <= effect.start_centisecond + 60 and effect.start_centisecond < b + 60
                       for a, b in lit)
        assert mine[0].start_intensity == 0 and mine[-1].end_intensity == 0  # eased in and out
    # Louder parts are brighter.
    levels = {s.level for s in plan.sections}
    if len(levels) > 1:
        assert max(e.start_intensity for e in pixels.effects) == 100


def test_requirements_apply_to_pixel_props() -> None:
    display = with_pixels()
    rules = load_rule_set()
    keep_dark = Requirement("no-roof", "never_use", Selector(names=("Pixel Roof",)), "error", {},
                            "", "test")
    dim = Requirement("dim-tree", "max_intensity", Selector(names=("Pixel Mega Tree",)), "error",
                      {"max": 40}, "", "test")
    gold = Requirement("gold-tree", "colors_only", Selector(names=("Pixel Mega Tree",)), "error",
                       {"colors": ["gold"]}, "", "test")
    _, _, pixels = _plan(display, dataclasses.replace(
        rules, requirements=(*rules.requirements, keep_dark, dim, gold)))
    assert pixels.prop_ids == (display.prop_id("Pixel Mega Tree"),)
    assert ("Pixel Roof", "requirement 'no-roof': never used") in pixels.skipped
    assert max(e.start_intensity for e in pixels.effects) <= 40
    assert {c for e in pixels.effects for c in e.colors} == {"gold"}


def test_pixel_effects_are_written_on_motion_rows(tmp_path: Path) -> None:
    display = with_pixels()
    preview, plan, pixels = _plan(display)
    source = tmp_path / "yard.lorprev"
    ET.ElementTree(preview).write(source, encoding="utf-8", xml_declaration=True)
    out = tmp_path / "show.loredit"
    build_from_timeline(source, plan.choreography, load_rule_set(), "song.mp3", out,
                        tmp_path / "show.report.json", pixel_effects=pixels.effects)
    root = read_loredit(out).root
    by_id = {p.get("id"): p for p in root.iter("SeqProp")}
    for prop_id in _pixel_ids(display):
        prop = by_id[prop_id]
        assert prop.get("OverlayMotionRows") == "1" and prop.find("channel") is None
        rows = prop.findall("track")
        assert [r.get("name") for r in rows] == ["Effects 01", "Effects 02"]
        written = rows[0].findall("effect")
        assert len(written) == sum(1 for e in pixels.effects if e.prop_id == prop_id)
        assert all(e.get("settings", "").startswith("Mix_Average|0|0|full|20|lightorama_")
                   for e in written)
        assert not rows[1].findall("effect")


def test_without_the_choice_pixel_props_stay_out(tmp_path: Path) -> None:
    display = with_pixels()
    preview, plan, _ = _plan(display)
    source = tmp_path / "yard.lorprev"
    ET.ElementTree(preview).write(source, encoding="utf-8", xml_declaration=True)
    out = tmp_path / "show.loredit"
    build_from_timeline(source, plan.choreography, load_rule_set(), "song.mp3", out,
                        tmp_path / "show.report.json")
    ids = {p.get("id") for p in read_loredit(out).root.iter("SeqProp")}
    assert not ids & _pixel_ids(display)


def test_the_workspace_plays_pixel_effects(tmp_path: Path) -> None:
    import threading
    from http.server import ThreadingHTTPServer

    from lor_sequence_builder.ui_server import SequencerRequestHandler

    playwright_api = pytest.importorskip("playwright.sync_api")
    display = with_pixels()
    preview, plan, pixels = _plan(display)
    source = tmp_path / "yard.lorprev"
    ET.ElementTree(preview).write(source, encoding="utf-8", xml_declaration=True)
    show = tmp_path / "show.loredit"
    build_from_timeline(source, plan.choreography, load_rule_set(), "song.mp3", show,
                        tmp_path / "show.report.json", pixel_effects=pixels.effects)
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/", wait_until="networkidle")
            page.locator("#sequenceFile").set_input_files(str(show))
            page.locator("#editor").wait_for(state="visible")
            labels = page.locator(".track-label.motion")
            assert labels.count() == 4  # two rows on each pixel prop
            assert "pixel effects" in labels.first.inner_text()
            page.locator("#yardButton").click()
            canvas = page.locator("#yardCanvas")
            box = page.locator("#tracksCanvas").bounding_box()
            assert box is not None
            width = float(page.locator("#tracksCanvas").evaluate(
                "(c) => c.width / (window.devicePixelRatio || 1)"))
            lit = 0
            for second in (6, 14, 20, 26, 34):
                page.mouse.click(box["x"] + second * width / 48.0, box["y"] + 30)
                lit = max(lit, int(canvas.get_attribute("data-pixels-lit") or 0))
            assert lit >= 1
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_new_show_offers_pixels_only_when_the_display_has_them(tmp_path: Path) -> None:
    from lor_sequence_builder.show_builder import ShowSessions

    sessions = ShowSessions()
    try:
        with_pixel = with_pixels().element()
        plain = roofline_house().element()
        summaries = []
        for name, preview in (("pixels.lorprev", with_pixel), ("plain.lorprev", plain)):
            path = tmp_path / name
            ET.ElementTree(preview).write(path, encoding="utf-8", xml_declaration=True)
            summaries.append(sessions.start(path.read_bytes(), name))
        assert summaries[0]["pixels"] == 2
        assert summaries[1]["pixels"] == 0
    finally:
        sessions.close()
