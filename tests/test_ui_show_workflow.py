from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from lor_sequence_builder.ui_server import SequencerRequestHandler

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def workspace_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_address[1]) + "/"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_new_show_actions_never_offer_stale_results_or_playlists(
    workspace_url: str,
) -> None:
    summary = {
        "token": "display-one",
        "display": "Intent Test Yard",
        "props": [{"name": "Tree", "role": "tree", "sequenceable": True, "reason": None}],
        "kinds": [{"role": "tree", "label": "tree", "count": 1, "plural": "trees"}],
        "groups": [],
        "faces": False,
        "can_separate_vocals": False,
        "can_translate": False,
        "styles": [
            {"key": "classic", "name": "Classic", "description": "Balanced"},
            {"key": "elegant", "name": "Elegant", "description": "Calm"},
        ],
        "default_style": "classic",
        "requirements": [],
        "raw_requirements": [],
    }
    test_calls = 0

    def respond(route: object, body: dict[str, object], status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))  # type: ignore[attr-defined]

    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/api/show/start*", lambda route: respond(route, summary))
        audio_calls = 0

        def analyze_audio(route: object) -> None:
            nonlocal audio_calls
            audio_calls += 1
            if audio_calls == 2:
                respond(route, {"error": "simulated audio failure"}, 422)
            else:
                respond(route, {
                    "report": {
                        "audio": {"duration_seconds": 3.0},
                        "analysis": {"tempo": {"bpm": 120}, "section_candidates": []},
                    }
                })

        page.route("**/api/show/audio*", analyze_audio)
        page.route("**/api/show/generate*", lambda route: respond(route, {
            "rules_ok": True,
            "file_name": "song (generated).loredit",
            "sequence": "<sequence />",
            "picture": "<svg xmlns='http://www.w3.org/2000/svg' />",
            "summary": "<!doctype html><title>Test</title>",
            "report": "Passed",
            "sections": [{"label": "Verse", "level": "Low"}],
            "used": ["Tree"],
            "skipped": [],
            "notes": [],
        }))
        page.route("**/api/show/batch-clear*", lambda route: respond(route, {"cleared": True}))
        page.route("**/api/show/batch?*", lambda route: respond(route, {
            "ok": True, "duration": 3.0, "parts": 2, "props": 1,
        }))
        page.route("**/api/show/batch-zip*", lambda route: respond(route, {
            "zip": "", "zip_name": "Intent Test Yard shows.zip", "count": 1,
        }))

        def display_test(route: object) -> None:
            nonlocal test_calls
            test_calls += 1
            if test_calls == 1:
                respond(route, {
                    "schedule": [{"start": 0.5, "end": 1.0, "what": "Tree"}],
                    "sequence": "<sequence />", "file_name": "test.loredit",
                    "sound": "", "sound_name": "test.wav", "zip": "", "zip_name": "test.zip",
                })
            else:
                respond(route, {"error": "simulated test failure"}, 422)

        page.route("**/api/show/test*", display_test)
        try:
            page.goto(workspace_url, wait_until="networkidle")
            page.locator("#newShowButton").click()
            preview = Path(__file__).parent / "fixtures" / "synthetic_display.lorprev"
            page.locator("#showDisplayFile").set_input_files(str(preview))
            page.get_by_text("Intent Test Yard", exact=False).wait_for()

            page.locator("#showSongFile").set_input_files({
                "name": "song.wav", "mimeType": "audio/wav", "buffer": b"fake audio",
            })
            page.locator("#songStatus").filter(has_text="song.wav").wait_for()
            page.locator("#showSongFile").set_input_files({
                "name": "replacement.wav", "mimeType": "audio/wav", "buffer": b"bad audio",
            })
            page.locator("#songStatus").filter(has_text="simulated audio failure").wait_for()
            assert "song.wav" in page.locator("#songStatus").inner_text()
            assert page.locator("#musicFilename").input_value() == "song.wav"
            assert not page.locator("#generateShow").is_disabled()

            # Changing meter must reanalyze the retained song before generation.
            page.locator("#meterSelect").select_option("3")
            page.locator("#songStatus.good").filter(has_text="song.wav").wait_for()
            assert not page.locator("#generateShow").is_disabled()
            page.locator("#generateShow").click()
            page.locator("#generateStatus").filter(has_text="Every rule passed").wait_for()
            assert not page.locator("#saveGenerated").is_disabled()

            page.locator('input[name="showStyle"][value="elegant"]').check()
            assert page.locator("#saveGenerated").is_disabled()
            assert page.locator("#openGenerated").is_disabled()
            assert page.locator("#reportGenerated").is_disabled()
            assert page.locator("#pictureGenerated").is_disabled()

            page.locator("#makeTest").click()
            page.locator("#testStatus").filter(has_text="Ready:").wait_for()
            assert not page.locator("#watchTest").is_disabled()
            page.locator("#makeTest").click()
            page.locator("#testStatus").filter(has_text="simulated test failure").wait_for()
            assert page.locator("#watchTest").is_disabled()
            assert page.locator("#saveTest").is_disabled()

            page.locator("#batchFiles").set_input_files([
                {"name": "one.wav", "mimeType": "audio/wav", "buffer": b"one"},
            ])
            page.locator("#batchStatus").filter(has_text="Building 1 of 1").wait_for()
            page.locator("#batchStatus").filter(has_text="1 of 1 shows built").wait_for()
            assert not page.locator("#saveBatch").is_disabled()
            page.locator('input[name="showStyle"][value="classic"]').check()
            assert page.locator("#saveBatch").is_disabled()

            # A completed playlist belongs to the display it was built for.
            page.locator("#batchFiles").set_input_files([
                {"name": "two.wav", "mimeType": "audio/wav", "buffer": b"two"},
            ])
            page.locator("#batchStatus").filter(has_text="Building 1 of 1").wait_for()
            page.locator("#batchStatus").filter(has_text="1 of 1 shows built").wait_for()
            assert not page.locator("#saveBatch").is_disabled()
            summary["token"] = "display-two"
            page.locator("#showDisplayFile").set_input_files(str(preview))
            page.get_by_text("Intent Test Yard", exact=False).wait_for()
            assert page.locator("#saveBatch").is_disabled()
        finally:
            browser.close()
