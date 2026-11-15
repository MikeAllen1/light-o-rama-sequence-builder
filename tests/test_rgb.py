"""RGB (S6 "DumbRGB") props: layout, colors, writing and reading back."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.channel_mapping import channel_layout_problem, native_channel_count
from lor_sequence_builder.classifier import classify_preview
from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.planner import plan_show
from lor_sequence_builder.rgb import BLACK, argb, color_name, from_argb
from lor_sequence_builder.rules import check_choreography, display_from_preview, load_rule_set
from lor_sequence_builder.sequence_writer import build_from_timeline
from lor_sequence_builder.style import get_style
from lor_sequence_builder.style_learning import sequence_effects
from tests.display_builders import DisplayBuilder, roofline_house
from tests.test_planner import synthetic_analysis


def with_floods(count: int = 3) -> DisplayBuilder:
    display = roofline_house()
    for i in range(count):
        display.add(f"RGB Flood {i + 1}", "decor", shape="Bulbs", channels=3,
                    traditional="Channel_per_color", colors=("Red", "Green", "Blue"),
                    string_type="DumbRGB", unit="30", points=[(-0.6 + 0.6 * i, -0.3)])
    return display


def test_colors_are_stored_the_way_s6_stores_them() -> None:
    # Values from an owner's own S6 sequence with RGB floods.
    assert argb("blue", 100) == -16776961
    assert argb("green", 100) == -16711936
    assert argb("purple", 100) == -5242192
    assert argb("white", 100) == -1
    assert argb("red", 0) == BLACK == -16777216
    assert from_argb(-16776961) == ((0, 0, 255), 100)
    assert from_argb(argb("red", 60)) == ((153, 0, 0), 60)
    assert color_name(" Ice_Blue ") == "ice blue" and color_name("aqua") == "cyan"
    assert color_name("plaid") is None


def test_an_rgb_prop_is_one_channel_of_any_color() -> None:
    preview = with_floods(1).element()
    flood = next(p for p in preview.findall("PropClass") if p.get("StringType") == "DumbRGB")
    assert channel_layout_problem(flood) is None
    assert native_channel_count(dict(flood.attrib)) == 1
    two = dict(flood.attrib, ChannelGrid="Regular,30,1,1,0,Red;Regular,30,2,2,0,Green")
    assert "three circuits" in (channel_layout_problem(ET.Element("PropClass", two)) or "")
    classified = next(c for c in classify_preview(preview) if c.name == "RGB Flood 1")
    assert classified.role == "decor" and classified.channel_count == 1
    assert classified.color_capability.kind == "rgb"
    assert classified.sequencing_support == "supported"


def test_shows_color_rgb_props_and_write_s6_colors(tmp_path: Path) -> None:
    display = with_floods(3)
    preview = display.element()
    rules = load_rule_set()
    plan = plan_show(synthetic_analysis(duration=40.0), display_from_preview(preview), rules,
                     style=get_style("classic"))
    assert check_choreography(preview, plan.choreography, rules).ok
    floods = {display.prop_id(f"RGB Flood {i + 1}") for i in range(3)}
    on_floods = [e for e in plan.choreography.effects if e.prop_id in floods]
    assert on_floods and {e.channel_index for e in on_floods} == {0}
    colors = {e.color for e in on_floods}
    assert colors <= set(get_style("classic").palette) and len(colors) >= 2

    source = tmp_path / "yard.lorprev"
    ET.ElementTree(preview).write(source, encoding="utf-8", xml_declaration=True)
    out = tmp_path / "show.loredit"
    build_from_timeline(source, plan.choreography, rules, "song.mp3", out,
                        tmp_path / "show.report.json")
    root = read_loredit(out).root
    for prop in root.iter("SeqProp"):
        if prop.get("id") not in floods:
            continue
        channels = prop.findall("channel")
        assert [c.attrib for c in channels] == [{"row": "0", "col": "0", "color": "0"}]
        for effect in channels[0]:
            assert effect.get("settings") in {"INTENSITY", "SHIMMER"}
            values = [int(effect.get(k) or 0) for k in ("intensity", "startIntensity", "endIntensity")
                      if effect.get(k) is not None]
            assert values and all(v < 0 for v in values)  # opaque ARGB, never a percent
    # Reading the show back sees the floods' brightness, not their color codes.
    lits, _ = sequence_effects(root, s4=False)
    assert any(lit.channel.split("/")[0] in floods and lit.peak > 0 for lit in lits)


def test_a_requirement_limits_the_colors_of_rgb_props(tmp_path: Path) -> None:
    display = with_floods(2)
    preview = display.element()
    profile = tmp_path / "profile.yaml"
    profile.write_text("""schema_version: rules-1.0
requirements:
  - {id: blue-only, type: colors_only, props: {names: [RGB Flood 1, RGB Flood 2]},
     colors: [Blue, Ice Blue]}
""", encoding="utf-8")
    rules = load_rule_set((profile,))
    plan = plan_show(synthetic_analysis(duration=30.0), display_from_preview(preview), rules,
                     style=get_style("classic"))
    report = check_choreography(preview, plan.choreography, rules)
    assert report.ok, report.format_text()
    floods = {display.prop_id("RGB Flood 1"), display.prop_id("RGB Flood 2")}
    shown = {e.color for e in plan.choreography.effects if e.prop_id in floods}
    assert shown and shown <= {"blue", "ice blue"}


@pytest.mark.parametrize("style", ["energetic", "elegant"])
def test_every_style_colors_rgb_props(style: str) -> None:
    display = with_floods(2)
    preview = display.element()
    rules = load_rule_set()
    plan = plan_show(synthetic_analysis(duration=30.0), display_from_preview(preview), rules,
                     style=get_style(style))
    assert check_choreography(preview, plan.choreography, rules).ok
    colors = {e.color for e in plan.choreography.effects if "RGB Flood" in
              display_from_preview(preview).props[e.prop_id].name}
    assert colors and colors <= set(get_style(style).palette)


def test_the_display_test_shows_each_rgb_circuit(tmp_path: Path) -> None:
    from lor_sequence_builder.display_test import build_display_test

    source = tmp_path / "yard.lorprev"
    ET.ElementTree(with_floods(1).element()).write(source, encoding="utf-8",
                                                   xml_declaration=True)
    test = build_display_test(source, tmp_path / "test")
    root = read_loredit(test.sequence_path).root
    flood = next(p for p in root.iter("SeqProp") if p.get("name") == "RGB Flood 1")
    shown = [from_argb(int(e.get("intensity") or e.get("startIntensity") or 0))[0]
             for e in flood.iter("effect")]
    for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)):
        assert color in shown


def test_the_workspace_shows_rgb_props_in_their_colors(tmp_path: Path) -> None:
    import threading
    from http.server import ThreadingHTTPServer

    from lor_sequence_builder.ui_server import SequencerRequestHandler

    playwright_api = pytest.importorskip("playwright.sync_api")
    display = with_floods(3)
    preview = display.element()
    rules = load_rule_set()
    plan = plan_show(synthetic_analysis(duration=40.0), display_from_preview(preview), rules,
                     style=get_style("classic"))
    source = tmp_path / "yard.lorprev"
    ET.ElementTree(preview).write(source, encoding="utf-8", xml_declaration=True)
    show = tmp_path / "show.loredit"
    build_from_timeline(source, plan.choreography, rules, "song.mp3", show,
                        tmp_path / "show.report.json")
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
            page.locator("#yardButton").click()
            canvas = page.locator("#yardCanvas")
            box = page.locator("#tracksCanvas").bounding_box()
            assert box is not None
            width = float(page.locator("#tracksCanvas").evaluate(
                "(c) => c.width / (window.devicePixelRatio || 1)"))
            seen: set[str] = set()
            for second in (6, 14, 20, 26, 34):
                page.mouse.click(box["x"] + second * width / 48.0, box["y"] + 30)
                seen.update((canvas.get_attribute("data-rgb-colors") or "").split())
            # The floods light in real colors (not the plain bulb color).
            assert seen & {"rgb(255,0,0)", "rgb(0,255,0)", "rgb(255,255,255)",
                           "rgb(255,176,0)"}, seen
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
