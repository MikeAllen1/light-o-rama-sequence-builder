"""S4 (.lms) in the app: New show with an S4 display, and editing an .lms.

The sequences are invented in code (tests/test_lms.py); no real show is used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lor_sequence_builder.lms import parse_lms
from lor_sequence_builder.ui_server import SHOWS, check_edited_sequence
from tests.test_audio_analysis import _rhythmic_track
from tests.test_lms import s4_sequence
from tests.test_show_builder import _json, _post, server  # noqa: F401
from tests.test_ui_editing import workspace  # noqa: F401

playwright_api = pytest.importorskip("playwright.sync_api")


def test_new_show_with_an_s4_display_makes_an_s4_show(
    server: str, tmp_path: Path,  # noqa: F811
) -> None:
    status, started = _post(server + "/api/show/start?name=My%20Yard.lms", s4_sequence(),
                            "application/xml")
    assert status == 200, started
    token = started["token"]
    try:
        assert started["display"] == "My Yard"
        names = {prop["name"] for prop in started["props"]}
        assert {"Arch 1", "Mini Tree 2", "Roof Line"} <= names
        song = tmp_path / "Song.wav"
        _rhythmic_track(song, duration=12.0)
        status, added = _post(server + f"/api/show/audio?token={token}&name=Song.wav",
                              song.read_bytes(), "application/octet-stream")
        assert status == 200, added
        status, built = _post(server + f"/api/show/generate?token={token}",
                              json.dumps({}).encode(), "application/json")
        assert status == 200, built
        assert built["rules_ok"]
        assert built["file_name"] == "Song (generated).lms"
        show = parse_lms(built["sequence"].encode("utf-8"))
        assert [c.unit for c in show.channels] == [c.unit for c in parse_lms(s4_sequence()).channels]
        assert sum(c.effect_count for c in show.channels) > 0
        status, test = _post(server + f"/api/show/test?token={token}", b"{}",
                             "application/json")
        assert status >= 400 and "S4" in str(test)
    finally:
        with SHOWS._lock:
            SHOWS._drop(token)


def test_bad_s4_display_is_explained(server: str) -> None:  # noqa: F811
    status, answer = _post(server + "/api/show/start?name=Broken.lms",
                           b"<sequence saveFileVersion='14'/>", "application/xml")
    assert status >= 400
    assert "S4 sequences (.lms)" in json.dumps(answer)


def test_edited_lms_must_keep_its_channels() -> None:
    original = s4_sequence()
    assert check_edited_sequence(original, original)["channels"] == 7
    renamed = original.replace(b'name="Arch 1"', b'name="Arch One"')
    with pytest.raises(ValueError, match="changed its channels"):
        check_edited_sequence(renamed, original)
    overlapping = original.replace(b'endCentisecond="50"', b'endCentisecond="5000"', 1)
    with pytest.raises(ValueError, match="outside the song"):
        check_edited_sequence(overlapping, original)


def test_an_lms_opens_edits_and_exports_as_s4(workspace: str, tmp_path: Path) -> None:  # noqa: F811
    original = s4_sequence()
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        try:
            page.goto(workspace, wait_until="networkidle")
            page.locator("#sequenceFile").set_input_files(
                {"name": "My Yard.lms", "mimeType": "text/xml", "buffer": original})
            page.locator("#editor").wait_for(state="visible")
            assert page.locator("#propStat").inner_text() == "7"
            assert page.locator("#effectStat").inner_text() == "7"
            labels = page.locator("#trackLabels").inner_text()
            assert "Arches" in labels and "Roof Line" in labels

            # Unchanged export gives back the same bytes, named as S4.
            with page.expect_download() as unchanged:
                page.locator("#exportButton").click()
            assert unchanged.value.suggested_filename == "My Yard (edited).lms"
            assert Path(unchanged.value.path()).read_bytes() == original

            # Edit the first effect into a fade; it is written back as an S4 effect.
            # Rows: the "Arches" group, then the Arch 1 prop, then its channel.
            page.locator("#zoomSlider").evaluate(
                """(element) => { element.value = "40";
                    element.dispatchEvent(new Event("input", { bubbles: true })); }""")
            page.locator("#tracksCanvas").click(position={"x": 10, "y": 2 * 22 + 11})
            assert "INTENSITY" in page.locator("#inspectorContent").inner_text()
            page.locator("#editFade").check()
            page.locator("#editStartIntensity").fill("100")
            page.locator("#editEndIntensity").fill("0")
            page.locator("#editApply").click()
            assert "Changed 1 effect(s)" in page.locator("#analysisMessage").inner_text()
            with page.expect_download() as edited:
                page.locator("#exportButton").click()
            saved = Path(edited.value.path()).read_bytes()
            document = parse_lms(saved)
            effects = [e.attrib for e in document.root.iterfind("channels/channel/effect")]
            assert {"type": "intensity", "startCentisecond": "0", "endCentisecond": "50",
                    "startIntensity": "100", "endIntensity": "0"} in effects
            assert not any("settings" in effect for effect in effects)
            assert b"\r\n" in saved
        finally:
            browser.close()
