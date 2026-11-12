"""Everything can be done from the keyboard and read by a screen reader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.display_builders import classic_yard
from tests.test_planner import _preview
from tests.test_show_builder import server  # noqa: F401 - fixture

sync_api = pytest.importorskip("playwright.sync_api")


def _serious(page: Any) -> list[str]:
    axe_module = pytest.importorskip("axe_playwright_python.sync_playwright")
    found = axe_module.Axe().run(page).response["violations"]
    return [f"{v['id']}: {v['help']} {[n['target'] for n in v['nodes']][:3]}"
            for v in found if v["impact"] in {"serious", "critical"}
            or v["id"] in {"heading-order", "page-has-heading-one"}]


def _editor(page: Any, server_url: str, tmp_path: Path) -> None:
    from lor_sequence_builder.demo import build_demo

    show = build_demo(tmp_path / "demo")
    page.goto(server_url + "/", wait_until="networkidle")
    page.locator("#welcomeSequenceFile").set_input_files(str(show.sequence_path))
    page.locator("#editor").wait_for(state="visible")
    page.locator("#audioFile").set_input_files(str(tmp_path / "demo" / "Demo Song.wav"))
    for _ in range(100):
        if page.evaluate("document.getElementById('audioPlayer').duration > 0"):
            break
        page.wait_for_timeout(100)


def test_no_serious_problems_on_any_screen(server: str, tmp_path: Path) -> None:  # noqa: F811
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(server + "/", wait_until="networkidle")
            assert _serious(page) == [], "start page"
            page.locator("#welcomeNewShow").click()
            page.locator("#showDisplayFile").set_input_files(str(_preview(tmp_path,
                                                                          classic_yard())))
            page.locator("#displayStatus.good").wait_for(timeout=20000)
            assert _serious(page) == [], "new show"
            _editor(page, server, tmp_path)
            page.locator("#yardButton").click()
            assert _serious(page) == [], "editor"
        finally:
            browser.close()


def test_every_file_picker_can_be_reached_from_the_keyboard(server: str) -> None:  # noqa: F811
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(server + "/", wait_until="networkidle")
            reachable = page.evaluate("""() => Array.from(
                document.querySelectorAll('input[type=file]')).map((input) => {
                  const style = getComputedStyle(input);
                  return [input.id, style.display !== 'none' && style.visibility !== 'hidden'];
                })""")
            assert len(reachable) >= 8
            assert [name for name, ok in reachable if not ok] == []
            # Tab from the top reaches "Build a show", then the sequence picker.
            order = []
            for _ in range(40):
                page.keyboard.press("Tab")
                order.append(page.evaluate("document.activeElement.id"))
            assert "welcomeNewShow" in order and "welcomeSequenceFile" in order
            assert order.index("welcomeNewShow") < order.index("welcomeSequenceFile")
        finally:
            browser.close()


def test_playback_shortcuts(server: str, tmp_path: Path) -> None:  # noqa: F811
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            _editor(page, server, tmp_path)
            page.locator("#canvasViewport").focus()
            now = "document.getElementById('audioPlayer').currentTime"
            start = page.evaluate(now)
            page.keyboard.press("l")
            page.keyboard.press("l")
            assert page.evaluate(now) == pytest.approx(start + 10)
            page.keyboard.press("j")
            assert page.evaluate(now) == pytest.approx(start + 5)
            page.keyboard.press("Home")
            assert page.evaluate("document.getElementById('audioPlayer').currentTime") == 0
            page.keyboard.press("y")
            assert page.locator("#yardPanel").is_visible()
            page.keyboard.press("y")
            assert page.locator("#yardPanel").is_hidden()
        finally:
            browser.close()


def test_the_window_keeps_and_returns_focus(server: str) -> None:  # noqa: F811
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#showShortcuts").focus()
            page.keyboard.press("Enter")
            page.locator("#viewer").wait_for(state="visible")
            assert page.evaluate("document.activeElement.id") == "viewerClose"
            assert "Play or pause" in page.frame_locator("#viewerFrame").locator("pre").inner_text()
            seen = set()
            for _ in range(6):
                page.keyboard.press("Tab")
                seen.add(page.evaluate("document.activeElement.id"))
            assert seen <= {"viewerSave", "viewerClose", "viewerFrame"}
            page.keyboard.press("Escape")
            assert page.locator("#viewer").is_hidden()
            assert page.evaluate("document.activeElement.id") == "showShortcuts"
        finally:
            browser.close()


def test_status_lines_are_announced() -> None:
    html = (Path(__file__).resolve().parents[1] / "src" / "lor_sequence_builder" / "web"
            / "index.html").read_text(encoding="utf-8")
    assert html.count('class="step-status" role="status" aria-live="polite"') >= 6
    assert '<h1 id="newShowTitle">' in html and 'id="editorTitle"' in html


