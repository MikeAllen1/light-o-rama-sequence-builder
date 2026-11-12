"""People can see what the program is doing during long steps, and how far along it is."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder import progress, ui_server
from lor_sequence_builder.audio_analysis import analyze_audio
from tests.display_builders import classic_yard
from tests.test_audio_analysis import _rhythmic_track
from tests.test_planner import _preview
from tests.test_show_builder import _json, server  # noqa: F401 - fixture

KEY = "abcdef0123456789"


def test_steps_are_reported_only_while_tracking() -> None:
    progress.step("Not tracked")  # no effect outside tracking
    assert progress.snapshot(KEY) == {"known": False}
    with progress.tracking(KEY):
        progress.step("Finding the beats", 0.4)
        progress.step("Back to an earlier step", 0.2)  # the bar never goes backwards
        state = progress.snapshot(KEY)
        assert state["step"] == "Back to an earlier step" and state["fraction"] == 0.4
        assert not state["done"]
    assert progress.snapshot(KEY)["done"] and progress.snapshot(KEY)["fraction"] == 1.0


def test_only_safe_keys_are_tracked() -> None:
    with progress.tracking("../../etc"):
        progress.step("Ignored", 0.5)
    assert progress.snapshot("../../etc") == {"known": False}


def test_song_analysis_reports_its_steps(tmp_path: Path) -> None:
    song = tmp_path / "song.wav"
    _rhythmic_track(song, duration=12.0)
    seen: list[str] = []
    original = progress.step

    def spy(name: str, fraction: float | None = None, slow: bool = False) -> None:
        seen.append(name)
        original(name, fraction, slow)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(progress, "step", spy)
        with progress.tracking("song00000001"):
            analyze_audio(song, tmp_path / "a.json", tmp_path / "a.svg")
    assert seen[0] == "Reading the song" and "Finding the beats" in seen
    assert seen[-1] == "Saving what it found"


def test_the_workspace_shows_what_is_happening(server: str, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                                               tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    real_generate = ui_server.SHOWS.generate

    def slow_generate(token: str, body: dict[str, Any]) -> dict[str, Any]:
        progress.step("Planning the show", 0.3)
        time.sleep(1.5)
        progress.step("Checking the rules and writing the sequence", 0.6)
        time.sleep(1.0)
        return real_generate(token, body)

    monkeypatch.setattr(ui_server.SHOWS, "generate", slow_generate)
    song = tmp_path / "beat.wav"
    _rhythmic_track(song, duration=20.0)
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#welcomeNewShow").click()
            page.locator("#showDisplayFile").set_input_files(str(_preview(tmp_path,
                                                                          classic_yard())))
            page.locator("#displayStatus.good").wait_for(timeout=20000)
            page.locator("#showSongFile").set_input_files(str(song))
            page.locator("#songStatus.good").wait_for(timeout=60000)
            page.locator("#generateShow").click()
            bar = page.locator("#generateStatusProgress")
            bar.wait_for(state="visible", timeout=5000)
            page.get_by_text("Planning the show…").wait_for(timeout=5000)
            assert int(bar.get_attribute("aria-valuenow") or 0) >= 30
            page.locator("#generateStatus.good").wait_for(timeout=60000)
            assert bar.is_hidden()
        finally:
            browser.close()
