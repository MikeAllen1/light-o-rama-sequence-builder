"""Browser music review: correct markers, name sections, fix lyrics, fit a tempo map, save.

Uses an invented sequence and invented analysis; nothing here comes from a real song.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.evaluation import load_analysis
from lor_sequence_builder.planner import _music, _sections
from lor_sequence_builder.ui_server import SequencerRequestHandler
from tests.test_audio_analysis import _schema_violations
from tests.test_ui_editing import sequence_text

playwright_api = pytest.importorskip("playwright.sync_api")

LANE = 22
PPS = 40


def _event(time: float, method: str = "test estimate") -> dict[str, Any]:
    return {"time": time, "confidence": 0.6, "method": method}


def analysis_report() -> dict[str, Any]:
    # A loose beat grid: the beats between 2 s and 10 s wander, as in a rubato verse.
    beats = [_event(t / 2) for t in range(4)]
    beats += [_event(round(2 + i * 0.5 + (0.07 if i % 2 else -0.05), 3)) for i in range(16)]
    beats[4] = _event(2.0)
    beats += [_event(t / 2) for t in range(20, 20 * 2)]
    return {
        "schema_version": "2.0",
        "audio": {"duration_seconds": 20.0},
        "analysis": {
            "method": "test", "provenance": "synthetic test fixture", "limitations": [],
            "tempo": {"bpm": 120, "confidence": 0.5, "method": "test"},
            "beats": beats,
            "downbeats": [_event(float(t)) for t in range(0, 20, 2)],
            "onsets": [{"time": 8.0, "strength": 1.0, "confidence": 0.9, "method": "test"}],
            "energy": [{"time": float(t), "rms": 0.1 + t / 100, "method": "test"}
                       for t in range(20)],
            "phrase_boundaries": [],
            "section_candidates": [{"time": 8.0, "kind": "structural_change_candidate",
                                    "relative_change": 0.4, "confidence": 0.5, "label": None,
                                    "method": "test"}],
            "hard_stops": [],
            "high_hits": [_event(1.25)],
            "crashes": [_event(8.03)],
        },
    }


@pytest.fixture
def workspace() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(server.server_address[1]) + "/"
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_music_review_corrects_and_saves(workspace: str, tmp_path: Path) -> None:
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        try:
            page.goto(workspace, wait_until="networkidle")
            page.locator("#sequenceFile").set_input_files(
                {"name": "review-test.loredit", "mimeType": "text/xml",
                 "buffer": sequence_text().encode("utf-8")})
            page.locator("#editor").wait_for(state="visible")
            page.locator("#analysisFile").set_input_files(
                {"name": "a.json", "mimeType": "application/json",
                 "buffer": json.dumps(analysis_report()).encode("utf-8")})
            page.locator("#lyricsFile").set_input_files(
                {"name": "song.lrc", "mimeType": "text/plain",
                 "buffer": b"[00:02.00]Hello lights\n[00:06.00]Second line\n[00:09.00]End\n"})
            page.locator("#markerLabels").filter(has_text="Lyrics").wait_for()
            page.locator("#zoomSlider").evaluate(
                f"""(element) => {{ element.value = "{PPS}";
                    element.dispatchEvent(new Event("input", {{ bubbles: true }})); }}""")

            def at(seconds: float, label: str) -> tuple[float, float]:
                labels = page.locator("#markerLabels > div").all_inner_texts()
                lane = next(i for i, text in enumerate(labels) if text.startswith(label))
                box = page.locator("#markersCanvas").bounding_box()
                assert box is not None
                return box["x"] + seconds * PPS, box["y"] + lane * LANE + LANE / 2

            def banner() -> str:
                return str(page.locator("#analysisMessage").inner_text())

            def inspector() -> str:
                return str(page.locator("#inspectorContent").inner_text())

            # Drag the crash onto the beat at 8.5 s; the beat grid snaps it there.
            start = at(8.03, "Cymbal crash")
            end = at(8.47, "Cymbal crash")
            page.mouse.move(*start)
            page.mouse.down()
            page.mouse.move(end[0], end[1], steps=4)
            page.mouse.up()
            assert "Moved a crash to 0:08.50" in banner()
            assert "confirmed by you" in inspector()

            # Delete a beat, then add a high hit by double-clicking (it snaps to 4.0 s).
            page.mouse.click(*at(3.5, "Beat candidates"))
            assert "automatic estimate" in inspector()
            page.keyboard.press("Delete")
            assert "Deleted a beat" in banner()
            page.mouse.dblclick(*at(4.12, "High-pitched hits"))
            assert "Added a high hit at 0:04.00" in banner()

            # Name the section.
            page.mouse.click(*at(8.0, "Section candidates"))
            page.locator("#reviewLabel").select_option("Chorus")
            page.locator("#reviewApply").click()
            assert "Changed a section" in banner()

            # Correct a lyric line's words, and confirm another with Enter.
            page.mouse.click(*at(3.0, "Lyrics"))
            assert "Hello lights" in inspector()
            page.locator("#reviewText").fill("Hello  bright lights ")
            page.locator("#reviewApply").click()
            assert "Changed a lyric line" in banner()
            page.mouse.click(*at(9.5, "Lyrics"))
            # Imported lyrics are the user's own text, so they arrive confirmed.
            assert "confirmed by you" in inspector()

            # Tempo map: confirm the bars at 2 s and 10 s, then fit evenly between them.
            for seconds in (10.0, 2.0):
                page.mouse.click(*at(seconds, "Downbeat candidates"))
                page.locator("#reviewConfirm").click()
                assert "Confirmed a bar" in banner()
            assert page.locator("#fitBars").input_value() == "4"
            page.locator("#fitBarsButton").click()
            assert "Fitted 4 bar(s) of 4 between 0:02.00 and 0:10.00: 120.0 BPM" in banner()
            page.keyboard.press("Control+z")
            assert "Undid: Fitted" in banner()
            page.keyboard.press("Control+y")
            assert "Redid: Fitted" in banner()
            assert "unsaved music review" in page.locator("#editStatus").inner_text()
            assert "✓" in page.locator("#markerLabels").inner_text()

            with page.expect_download() as saved:
                page.locator("#saveReviewButton").click()
            assert saved.value.suggested_filename == "review-test.review.json"
            review_path = tmp_path / "review-test.review.json"
            saved.value.save_as(review_path)

            # Reopening the review restores it, and fresh audio analysis never replaces it.
            page.reload(wait_until="networkidle")
            page.locator("#sequenceFile").set_input_files(
                {"name": "review-test.loredit", "mimeType": "text/xml",
                 "buffer": sequence_text().encode("utf-8")})
            page.locator("#editor").wait_for(state="visible")
            page.locator("#analysisFile").set_input_files(str(review_path))
            page.locator("#analysisMessage").filter(has_text="Loaded music review").wait_for()
            assert "of 3 lyric lines confirmed" in banner()
            assert "Lyrics" in page.locator("#markerLabels").inner_text()
        finally:
            browser.close()

    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["schema_version"] == "music-review-1.0" and review["meter"] == 4
    report = review["analysis"]
    schema = json.loads((Path(__file__).parents[1] / "docs" / "schemas" /
                         "audio-analysis-v2.schema.json").read_text(encoding="utf-8"))
    # The invented fixture has no tool versions; its corrected lanes must still fit.
    assert _schema_violations(report["analysis"], schema["properties"]["analysis"], schema) == []
    analysis = report["analysis"]
    assert analysis["crashes"] == [{"time": 8.5, "confidence": 0.6, "method": "test estimate",
                                    "status": "confirmed"}]
    assert [h["time"] for h in analysis["high_hits"]] == [1.25, 4.0]
    assert analysis["section_candidates"][0]["label"] == "Chorus"
    between = [b for b in analysis["beats"] if 2.0 <= b["time"] <= 10.0]
    assert [b["time"] for b in between] == [2 + i * 0.5 for i in range(17)]
    assert {b["status"] for b in between[1:-1]} == {"fitted"}
    bars = [d for d in analysis["downbeats"] if 2.0 <= d["time"] <= 10.0]
    assert [(d["time"], d.get("status")) for d in bars] == [
        (2.0, "confirmed"), (4.0, "fitted"), (6.0, "fitted"), (8.0, "fitted"), (10.0, "confirmed")]
    lyrics = review["lyrics"]["lines"]
    assert lyrics[0]["text"] == "Hello bright lights" and lyrics[0]["verified"] is True
    counts = review["counts"]
    assert counts["fitted"] == 18 and counts["lyric_lines_confirmed"] == 3

    # The generator reads the review in place of an analysis, and names the section.
    loaded = load_analysis(review_path)
    assert loaded["analysis"]["crashes"][0]["time"] == 8.5
    sections = _sections(_music(loaded))
    assert any(section.label == "chorus" for section in sections)


def test_lyrics_loader_rejects_malformed_word_objects(workspace: str) -> None:
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(workspace, wait_until="networkidle")
            malformed = {
                "schema_version": "lyrics-1.0",
                "source": "transcribed",
                "lines": [{
                    "start": 1.0, "end": 2.0, "text": "hello",
                    "words": [None],
                }],
            }
            page.locator("#lyricsFile").set_input_files({
                "name": "malformed.lyrics.json",
                "mimeType": "application/json",
                "buffer": json.dumps(malformed).encode("utf-8"),
            })
            assert "invalid word event" in page.locator("#analysisMessage").inner_text()
            assert "Loaded 1 lyric lines" not in page.locator("#analysisMessage").inner_text()
        finally:
            browser.close()
