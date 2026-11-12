"""The workspace's More menu: optional review and singing-timing files.

Uses the invented sequence and analysis from the other workspace tests.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.test_ui_editing import sequence_text, workspace  # noqa: F401
from tests.test_ui_review import analysis_report

playwright_api = pytest.importorskip("playwright.sync_api")


def _state(page: Any, item: str) -> tuple[bool, str]:
    label = page.locator(f"#{item}Label")
    return (page.locator(f"#{item}").is_disabled(), str(label.get_attribute("title")))


def test_more_menu_explains_and_enables_its_files(workspace: str) -> None:  # noqa: F811
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        try:
            page.goto(workspace, wait_until="networkidle")
            menu = page.locator("#moreMenu")
            assert menu.is_hidden()
            page.locator("#moreButton").click()
            assert menu.is_visible()
            assert page.locator("#moreButton").get_attribute("aria-expanded") == "true"
            # Nothing is open yet: both wait, and say what to open first.
            assert _state(page, "analysisFile") == (True, "Open a sequence first.")
            assert _state(page, "vocalsFile")[0]
            assert "Open the song" in _state(page, "vocalsFile")[1]
            page.keyboard.press("Escape")
            assert menu.is_hidden()
            assert page.evaluate("document.activeElement.id") == "moreButton"

            page.locator("#sequenceFile").set_input_files(
                {"name": "menu-test.loredit", "mimeType": "text/xml",
                 "buffer": sequence_text().encode("utf-8")})
            page.locator("#editor").wait_for(state="visible")
            disabled, tip = _state(page, "analysisFile")
            assert not disabled and ".review.json" in tip
            assert _state(page, "vocalsFile")[0]  # still needs the song or its timing

            # A singing timing file chosen as a review is pointed to the right item.
            page.locator("#analysisFile").set_input_files(
                {"name": "song.vocals.json", "mimeType": "application/json",
                 "buffer": json.dumps({"schema_version": "vocals-1.0"}).encode("utf-8")})
            page.locator("#analysisMessage").filter(has_text="Open singing timing").wait_for()

            page.locator("#analysisFile").set_input_files(
                {"name": "song.analysis.json", "mimeType": "application/json",
                 "buffer": json.dumps(analysis_report()).encode("utf-8")})
            page.locator("#markerLabels").filter(has_text="Beat candidates").wait_for()
            disabled, tip = _state(page, "vocalsFile")
            assert not disabled and ".vocals.json" in tip

            # And a review chosen as singing timing is pointed back.
            page.locator("#vocalsFile").set_input_files(
                {"name": "song.analysis.json", "mimeType": "application/json",
                 "buffer": json.dumps(analysis_report()).encode("utf-8")})
            page.locator("#analysisMessage").filter(has_text="Open music review").wait_for()

            # Clicking elsewhere closes the menu.
            page.locator("#moreButton").click()
            assert menu.is_visible()
            page.locator("#sequenceTitle").click()
            assert menu.is_hidden()
        finally:
            browser.close()
