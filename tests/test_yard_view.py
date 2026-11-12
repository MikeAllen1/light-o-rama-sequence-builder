"""The yard view draws the display from the sequence's own preview and lights it."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from lor_sequence_builder.demo import build_demo
from lor_sequence_builder.ui_server import SequencerRequestHandler

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def workspace() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(server.server_address[1]) + "/"
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_the_yard_view_lights_the_demo_show(workspace: str, tmp_path: Path) -> None:
    show = build_demo(tmp_path / "demo")
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        try:
            page.goto(workspace, wait_until="networkidle")
            page.locator("#sequenceFile").set_input_files(str(show.sequence_path))
            page.locator("#editor").wait_for(state="visible")
            assert page.locator("#yardPanel").is_hidden()
            page.locator("#yardButton").click()
            canvas = page.locator("#yardCanvas")
            assert canvas.get_attribute("data-props") == "18"  # every prop in the demo yard
            bounds = [float(v) for v in (canvas.get_attribute("data-bounds") or "").split(",")]
            assert bounds[0] < -0.9 and bounds[3] > 0.9  # the house outline is drawn
            quiet = int(canvas.get_attribute("data-lit") or "0")  # at the very start
            # Click into the loud middle of the song on the tracks: the yard lights up.
            box = page.locator("#tracksCanvas").bounding_box()
            assert box is not None
            seconds_per_pixel = 48.0 / float(page.locator("#tracksCanvas").evaluate(
                "(c) => c.width / (window.devicePixelRatio || 1)"))
            page.mouse.click(box["x"] + 30.0 / seconds_per_pixel, box["y"] + 30)
            assert int(canvas.get_attribute("data-lit") or "0") > quiet + 3
            assert "channel(s) lit" in page.locator("#yardStatus").inner_text()
            page.locator("#yardButton").click()
            assert page.locator("#yardPanel").is_hidden()
        finally:
            browser.close()
