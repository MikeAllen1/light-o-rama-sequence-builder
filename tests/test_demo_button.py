"""One click on the start page shows what the program does, on an invented yard."""

from __future__ import annotations

import pytest

from lor_sequence_builder import demo
from tests.test_show_builder import _json, server  # noqa: F401 - fixture


def test_the_engine_builds_the_demo_once(server: str, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(demo, "_demo_cache", {})
    status, first = _json(server + "/api/demo", {})
    assert status == 200 and first["rules_ok"]
    assert first["file_name"] == "Demo Song.loredit" and "<sequence" in first["sequence"]
    assert first["analysis"]["analysis"]["beats"]
    built = []
    monkeypatch.setattr(demo, "build_demo", lambda *_: built.append(1))
    status, second = _json(server + "/api/demo", {})
    assert status == 200 and second["sequence"] == first["sequence"] and not built


def test_watch_a_demo_opens_the_yard_view(server: str) -> None:  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#watchDemo").click()
            page.locator("#editor").wait_for(state="visible", timeout=60000)
            page.locator("#yardPanel").wait_for(state="visible", timeout=10000)
            page.get_by_text("The demo: an invented yard and song").wait_for(timeout=30000)
            assert int(page.locator("#yardCanvas").get_attribute("data-props") or 0) >= 10
            duration = page.locator("#audioPlayer").evaluate("audio => audio.duration")
            assert duration > 40  # the demo song is loaded and ready to play
            assert page.locator("#watchDemo").is_enabled()
            # Close leaves the demo for the start page; the program keeps running.
            page.locator("#closeWorkspace").click()
            page.locator("#welcome").wait_for(state="visible")
            assert page.locator("#editor").is_hidden()
            assert page.locator("#audioPlayer").evaluate("audio => audio.paused")
            page.locator("#watchDemo").click()  # and the demo opens again
            page.locator("#editor").wait_for(state="visible", timeout=60000)
        finally:
            browser.close()
