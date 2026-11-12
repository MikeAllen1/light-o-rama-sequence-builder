"""The workspace log and the diagnostics report people paste when asking for help."""

from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder import __version__, diagnostics
from lor_sequence_builder.diagnostics import report, scrub, write_log
from tests.test_show_builder import _json, server  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _fresh_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostics, "_written", 0)


def test_home_paths_and_the_user_name_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/home/someone")))
    monkeypatch.setattr("getpass.getuser", lambda: "someone")
    assert scrub("/home/someone/Music/song.mp3 by someone") == "~/Music/song.mp3 by <user>"


def test_the_log_stays_small_and_one_line_per_entry(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "logs"
    monkeypatch.setattr(diagnostics, "MAX_LOG_BYTES", 200)
    for n in range(10):
        write_log("page", f"problem {n}\nsecond line", folder)
    current = (folder / "workspace.log").read_text(encoding="utf-8").splitlines()
    assert current and all("second line" in line for line in current)  # newlines folded
    assert (folder / "workspace.log.1").exists()
    assert len("\n".join(current).encode()) < 400


def test_the_log_is_capped_per_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostics, "MAX_ENTRIES_PER_RUN", 3)
    for n in range(5):
        write_log("page", f"entry {n}", tmp_path)
    assert len((tmp_path / "workspace.log").read_text(encoding="utf-8").splitlines()) == 3


def test_the_report_has_the_version_checks_steps_and_logs(tmp_path: Path) -> None:
    write_log("page", "Plan picture failed", tmp_path)
    (tmp_path / "desktop.log").write_text("window started\n", encoding="utf-8")
    text = report("Mozilla/5.0 Edg/142", ["22:01:05 click pictureGenerated"], tmp_path)
    assert f"LOR Sequencer {__version__}" in text and "Edg/142" in text
    assert "Checks:" in text and "Python" in text
    assert "click pictureGenerated" in text
    assert "Plan picture failed" in text and "window started" in text


def test_the_workspace_logs_refusals_and_gives_a_report(server: str) -> None:  # noqa: F811
    status, _ = _json(server + "/api/show/generate?token=nope", {})
    assert status >= 400
    status, _ = _json(server + "/api/log", {"message": "TypeError: x is null", "where": "app.js:9"})
    assert status == 200
    status, result = _json(server + "/api/diagnostics",
                           {"browser": "test", "steps": ["click makeTest"]})
    assert status == 200
    assert "/api/show/generate answered" in result["text"]
    assert "TypeError: x is null (app.js:9)" in result["text"]
    assert "click makeTest" in result["text"]


def test_copy_diagnostics_on_the_start_page(server: str) -> None:  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#welcomeNewShow").click()
            page.locator("#closeNewShow").click()
            page.locator("#copyDiagnostics").click()
            frame = page.frame_locator("#viewerFrame")
            frame.get_by_text("Last steps in the workspace").wait_for()
            assert "click welcomeNewShow" in frame.locator("pre").inner_text()
            assert "Diagnostics" in page.locator("#viewerTitle").inner_text()
        finally:
            browser.close()
