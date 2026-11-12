"""Leaving the workspace: its Close button, and the window asking before it quits."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from lor_sequence_builder import desktop
from tests.test_ui_editing import sequence_text, workspace  # noqa: F401

playwright_api = pytest.importorskip("playwright.sync_api")


def test_close_returns_to_the_start_page_and_guards_unsaved_edits(
    workspace: str,  # noqa: F811
) -> None:
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        try:
            page.goto(workspace, wait_until="networkidle")
            text = sequence_text().encode("utf-8")
            page.locator("#sequenceFile").set_input_files(
                {"name": "close-test.loredit", "mimeType": "text/xml", "buffer": text})
            page.locator("#editor").wait_for(state="visible")
            page.locator("#closeWorkspace").click()
            page.locator("#welcome").wait_for(state="visible")
            assert page.locator("#editor").is_hidden()

            # With an unsaved edit, Close asks; cancelling keeps the work open.
            page.locator("#sequenceFile").set_input_files(
                {"name": "close-test.loredit", "mimeType": "text/xml", "buffer": text})
            page.locator("#editor").wait_for(state="visible")
            page.locator("#zoomSlider").evaluate(
                """(element) => { element.value = "40";
                    element.dispatchEvent(new Event("input", { bubbles: true })); }""")
            # The invented sequence has a Bush effect from 5.00 to 6.00 s on row 7.
            page.locator("#tracksCanvas").click(position={"x": 5.5 * 40, "y": 7 * 22 + 11})
            page.keyboard.press("Delete")
            assert "unexported" in page.locator("#editStatus").inner_text().lower()
            asked: list[str] = []
            def decline(dialog: Any) -> None:
                asked.append(dialog.message)
                dialog.dismiss()

            page.once("dialog", decline)
            page.locator("#closeWorkspace").click()
            assert asked and "discard the unsaved edits" in asked[0]
            assert page.locator("#editor").is_visible()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#closeWorkspace").click()
            page.locator("#welcome").wait_for(state="visible")
            # Nothing unsaved is left behind to stop the window from closing.
            assert page.evaluate("""() => {
                const event = new Event("beforeunload", { cancelable: true });
                window.dispatchEvent(event);
                return event.defaultPrevented;
            }""") is False
        finally:
            browser.close()


def test_the_window_asks_before_quitting(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    fake = types.ModuleType("webview")
    fake.settings = {}  # type: ignore[attr-defined]
    fake.create_window = lambda *args, **kwargs: calls.update(window=kwargs)  # type: ignore[attr-defined]
    fake.start = lambda **kwargs: calls.update(start=kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webview", fake)
    assert desktop._open_window("http://127.0.0.1:1/") is True
    assert calls["window"]["confirm_close"] is True
    assert calls["start"]["localization"]["global.quitConfirmation"] == "Quit LOR Sequencer?"
