from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from lor_sequence_builder.ui_server import SequencerRequestHandler
from tests.test_ui_editing import sequence_text

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


def test_uncertain_requirement_update_requires_display_resync(workspace_url: str) -> None:
    summary = {
        "token": "display-one",
        "display": "Requirement Resync Yard",
        "props": [{"name": "Tree", "role": "tree", "sequenceable": True, "reason": None}],
        "kinds": [{"role": "tree", "label": "tree", "count": 1, "plural": "trees"}],
        "groups": [],
        "faces": False,
        "can_separate_vocals": False,
        "can_translate": False,
        "styles": [{"key": "classic", "name": "Classic", "description": "Balanced"}],
        "default_style": "classic",
        "requirements": [],
        "raw_requirements": [],
    }
    saved_requirements: list[dict[str, object]] = []
    start_calls = 0

    def respond(route: object, body: dict[str, object]) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))  # type: ignore[attr-defined]

    def start_display(route: object) -> None:
        nonlocal start_calls
        start_calls += 1
        current = dict(summary)
        current["token"] = f"display-{start_calls}"
        current["display"] = "Requirement Resync Yard" + (" (resynced)" if start_calls > 1 else "")
        current["raw_requirements"] = list(saved_requirements)
        current["requirements"] = ["Never use Tree"] if saved_requirements else []
        respond(route, current)

    def lose_requirements_response(route: object) -> None:
        payload = json.loads(route.request.post_data)  # type: ignore[attr-defined]
        saved_requirements[:] = payload["requirements"]
        route.abort()  # type: ignore[attr-defined]

    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/api/show/start*", start_display)
        page.route("**/api/show/requirements?*", lose_requirements_response)
        page.goto(workspace_url)
        page.locator("#welcomeNewShow").click()
        display_file = {
            "name": "yard.lorprev", "mimeType": "application/xml", "buffer": b"<preview/>",
        }
        page.locator("#showDisplayFile").set_input_files(display_file)
        page.locator("#displayStatus").filter(has_text="Requirement Resync Yard").wait_for()

        page.locator("#requirementKind").select_option("never_use")
        page.locator('#requirementPicker input[value="name:Tree"]').check()
        page.locator("#addRequirement").click()
        page.locator("#requirementStatus").filter(
            has_text="Re-select the display to resync"
        ).wait_for(timeout=10000)
        assert saved_requirements == [{"type": "never_use", "props": {"names": ["Tree"]}}]
        assert page.locator("#addRequirement").is_disabled()
        assert page.locator("#showDisplayFile").is_enabled()

        # A new display session reloads the persisted profile and clears uncertainty.
        page.locator("#showDisplayFile").set_input_files(display_file)
        page.locator("#displayStatus").filter(has_text="Requirement Resync Yard (resynced)").wait_for()
        assert page.locator("#requirementList li").count() == 1
        assert "Never use Tree" in page.locator("#requirementList li").inner_text()
        assert page.locator("#addRequirement").is_enabled()
        browser.close()


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
    sequence_xml = sequence_text()

    def respond(route: object, body: dict[str, object], status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))  # type: ignore[attr-defined]

    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/api/show/start*", lambda route: respond(route, summary))
        page.route("**/api/show/requirements*", lambda route: respond(route, {"stale": True}))
        audio_calls = 0

        def analyze_audio(route: object) -> None:
            nonlocal audio_calls
            audio_calls += 1
            if audio_calls == 2:
                respond(route, {"error": "simulated audio failure"}, 422)
            elif audio_calls == 3:
                respond(route, {"error": "simulated uncertain upload"}, 500)
            elif audio_calls == 5:
                respond(route, {
                    "error": "This New Show was put away after a long break. Load the display again."
                }, 422)
            else:
                respond(route, {
                    "report": {
                        "audio": {"duration_seconds": 3.0},
                        "analysis": {"tempo": {"bpm": 120}, "section_candidates": []},
                    }
                })

        page.route("**/api/show/audio*", analyze_audio)
        fail_next_generation = False

        def generate_show(route: object) -> None:
            nonlocal fail_next_generation
            if fail_next_generation:
                fail_next_generation = False
                respond(route, {"error": "simulated generation failure"}, 500)
            else:
                respond(route, {
                    "rules_ok": True,
                    "file_name": "song (generated).loredit",
                    "sequence": sequence_xml,
                    "picture": "<svg xmlns='http://www.w3.org/2000/svg' />",
                    "summary": "<!doctype html><title>Test</title>",
                    "report": "Passed",
                    "sections": [{"label": "Verse", "level": "Low"}],
                    "used": ["Tree"],
                    "skipped": [],
                    "notes": [],
                })

        page.route("**/api/show/generate*", generate_show)
        fail_next_batch_clear = False
        fail_next_batch_clear_abort = False
        batch_clear_calls = 0
        batch_song_calls = 0
        fail_next_batch_song_abort = False

        def clear_batch(route: object) -> None:
            nonlocal fail_next_batch_clear, fail_next_batch_clear_abort, batch_clear_calls
            batch_clear_calls += 1
            if fail_next_batch_clear_abort:
                fail_next_batch_clear_abort = False
                route.abort("failed")  # type: ignore[attr-defined]
            elif fail_next_batch_clear:
                fail_next_batch_clear = False
                respond(route, {"error": "simulated reset failure"}, 500)
            else:
                respond(route, {"cleared": True})

        page.route("**/api/show/batch-clear*", clear_batch)

        def build_batch_song(route: object) -> None:
            nonlocal batch_song_calls, fail_next_batch_song_abort
            batch_song_calls += 1
            if fail_next_batch_song_abort:
                fail_next_batch_song_abort = False
                route.abort("failed")  # type: ignore[attr-defined]
            else:
                respond(route, {"ok": True, "duration": 3.0, "parts": 2, "props": 1})

        page.route("**/api/show/batch?*", build_batch_song)
        page.route("**/api/show/batch-zip*", lambda route: route.fulfill(
            status=200,
            content_type="application/zip",
            headers={"Content-Disposition":
                     "attachment; filename=shows.zip; filename*=UTF-8''Intent%20Test%20Yard%20shows.zip"},
            body=b"PK\x05\x06" + bytes(18),
        ))

        def display_test(route: object) -> None:
            nonlocal test_calls
            test_calls += 1
            if test_calls == 1:
                respond(route, {
                    "schedule": [{"start": 0.5, "end": 1.0, "what": "Tree"}],
                    "sequence": sequence_xml, "file_name": "test.loredit",
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

            # An empty brightness field must not be interpreted as 0%.
            page.locator("#requirementKind").select_option("max_intensity")
            page.locator('#requirementPicker input[value="role:tree"]').check()
            page.locator("#requirementMax").fill("")
            page.locator("#addRequirement").click()
            assert "steps of 5" in page.locator("#requirementStatus").inner_text()

            page.locator("#showSongFile").set_input_files({
                "name": "song.wav", "mimeType": "audio/wav", "buffer": b"fake audio",
            })
            page.locator("#songStatus.good").filter(has_text="song.wav").wait_for()
            page.locator("#showSongFile").set_input_files({
                "name": "replacement.wav", "mimeType": "audio/wav", "buffer": b"bad audio",
            })
            page.locator("#songStatus").filter(has_text="simulated audio failure").wait_for()
            assert "song.wav" in page.locator("#songStatus").inner_text()
            assert page.locator("#musicFilename").input_value() == "song.wav"
            assert not page.locator("#generateShow").is_disabled()

            # A lost/failed server response may arrive after the server committed
            # the upload, so the old analysis must not be used to generate blindly.
            page.locator("#showSongFile").set_input_files({
                "name": "uncertain.wav", "mimeType": "audio/wav", "buffer": b"uncertain audio",
            })
            page.locator("#songStatus").filter(has_text="simulated uncertain upload").wait_for()
            assert "server may have accepted" in page.locator("#songStatus").inner_text()
            assert page.locator("#generateShow").is_disabled()
            page.locator("#showSongFile").set_input_files({
                "name": "x" * 201 + ".wav", "mimeType": "audio/wav", "buffer": b"too long",
            })
            page.locator("#songStatus").filter(has_text="200 characters or fewer").wait_for()
            assert "server may have accepted" in page.locator("#songStatus").inner_text()
            assert page.locator("#generateShow").is_disabled()
            page.locator("#showSongFile").set_input_files({
                "name": "song.wav", "mimeType": "audio/wav", "buffer": b"fake audio",
            })
            page.locator("#songStatus.good").filter(has_text="song.wav").wait_for()
            assert not page.locator("#generateShow").is_disabled()

            # An expired server session is also uncertain even though it returns 422.
            page.locator("#showSongFile").set_input_files({
                "name": "song.wav", "mimeType": "audio/wav", "buffer": b"fake audio",
            })
            page.locator("#songStatus").filter(has_text="put away after a long break").wait_for()
            assert "server may have accepted" in page.locator("#songStatus").inner_text()
            assert page.locator("#generateShow").is_disabled()
            page.locator("#showSongFile").set_input_files({
                "name": "song.wav", "mimeType": "audio/wav", "buffer": b"fake audio",
            })
            page.locator("#songStatus.good").filter(has_text="song.wav").wait_for()
            assert not page.locator("#generateShow").is_disabled()

            # Changing meter must reanalyze the retained song before generation.
            page.locator("#meterSelect").select_option("3")
            page.locator("#songStatus.good").filter(has_text="song.wav").wait_for()
            assert not page.locator("#generateShow").is_disabled()
            page.locator("#generateShow").click()
            page.locator("#generateStatus").filter(has_text="Every rule passed").wait_for()
            assert not page.locator("#saveGenerated").is_disabled()

            # Opening a generated sequence must not replace the editor if its audio
            # cannot be decoded. This mocked upload is deliberately not a real WAV.
            page.locator("#openGenerated").click()
            page.wait_for_function(
                "() => document.querySelector('#generateStatus').textContent.includes(" +
                "'audio could not be loaded')"
            )
            assert page.locator("#newShow").is_visible()
            assert page.locator("#editor").is_hidden()

            fail_next_generation = True
            page.locator("#generateShow").click()
            page.locator("#generateStatus").filter(has_text="simulated generation failure").wait_for()
            assert "previous valid show is still available" in page.locator("#generateStatus").inner_text()
            assert not page.locator("#saveGenerated").is_disabled()

            page.locator('input[name="showStyle"][value="elegant"]').check()
            assert page.locator("#saveGenerated").is_disabled()
            assert page.locator("#openGenerated").is_disabled()
            assert page.locator("#reportGenerated").is_disabled()
            assert page.locator("#pictureGenerated").is_disabled()

            page.locator("#makeTest").click()
            page.locator("#testStatus").filter(has_text="Ready:").wait_for()
            assert not page.locator("#watchTest").is_disabled()

            # The display-test fixture has no sound bytes; watching it must fail
            # without replacing the current editor sequence.
            page.locator("#watchTest").click()
            page.locator("#testStatus").filter(
                has_text="display-test audio could not be loaded"
            ).wait_for(timeout=10000)
            assert page.locator("#newShow").is_visible()
            assert page.locator("#editor").is_hidden()

            page.locator("#makeTest").click()
            page.locator("#testStatus").filter(has_text="simulated test failure").wait_for()
            assert not page.locator("#watchTest").is_disabled()
            assert not page.locator("#saveTest").is_disabled()
            assert "previous display test is still available" in page.locator("#testStatus").inner_text()
            with page.expect_download() as retained_test:
                page.locator("#saveTest").click()
            assert retained_test.value.suggested_filename == "test.zip"

            page.locator("#batchFiles").set_input_files([
                {"name": "duplicate.wav", "mimeType": "audio/wav", "buffer": b"one"},
                {"name": "DUPLICATE.wav", "mimeType": "audio/wav", "buffer": b"two"},
            ])
            page.locator("#batchStatus").filter(has_text="duplicate audio filenames").wait_for()
            assert page.locator("#batchList").inner_text() == ""

            page.locator("#batchFiles").set_input_files([
                {"name": "one.wav", "mimeType": "audio/wav", "buffer": b"one"},
            ])
            page.locator("#batchStatus").filter(has_text="Building 1 of 1").wait_for()
            page.locator("#batchStatus").filter(has_text="1 of 1 shows built").wait_for()
            assert not page.locator("#saveBatch").is_disabled()
            previous_playlist_rows = page.locator("#batchList").inner_text()

            # An over-limit selection must be rejected before the previous batch
            # is cleared or any song is uploaded.
            oversized = [
                {"name": f"Song {index:02d}.wav", "mimeType": "audio/wav", "buffer": b"audio"}
                for index in range(41)
            ]
            page.locator("#batchFiles").set_input_files(oversized)
            page.locator("#batchStatus").filter(has_text="at most 40 songs").wait_for()
            assert page.locator("#batchList").inner_text() == previous_playlist_rows
            assert not page.locator("#saveBatch").is_disabled()
            assert batch_clear_calls == 1
            assert batch_song_calls == 1

            fail_next_batch_clear = True
            page.locator("#batchFiles").set_input_files([
                {"name": "replacement.wav", "mimeType": "audio/wav", "buffer": b"replacement"},
            ])
            page.locator("#batchStatus").filter(has_text="simulated reset failure").wait_for()
            assert batch_clear_calls == 2
            assert batch_song_calls == 1
            assert page.locator("#batchList").inner_text() == previous_playlist_rows
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
            with page.expect_download() as download_info:
                page.locator("#saveBatch").click()
            assert download_info.value.suggested_filename == "Intent Test Yard shows.zip"

            # A lost reset response must not leave the UI claiming the old playlist is usable.
            fail_next_batch_clear_abort = True
            page.locator("#batchFiles").set_input_files([
                {"name": "reset-uncertain.wav", "mimeType": "audio/wav", "buffer": b"uncertain"},
            ])
            page.locator("#batchStatus").filter(has_text="playlist state is uncertain").wait_for()
            assert page.locator("#saveBatch").is_disabled()

            # A lost song response may mean the server committed the show. Stop
            # instead of presenting a partial or misleading playlist as downloadable.
            fail_next_batch_song_abort = True
            page.locator("#batchFiles").set_input_files([
                {"name": "uncertain.wav", "mimeType": "audio/wav", "buffer": b"uncertain"},
                {"name": "not-attempted.wav", "mimeType": "audio/wav", "buffer": b"later"},
            ])
            page.locator("#batchList li").filter(
                has_text="uncertain.wav: upload outcome is uncertain"
            ).wait_for()
            assert page.locator("#batchList li").filter(
                has_text="not-attempted.wav: not attempted"
            ).count() == 1
            assert page.locator("#saveBatch").is_disabled()

            assert not page.locator("#meterSelect").is_disabled()

            # A stale requirements response means another session revision may be active.
            # (The form still holds the blank brightness from the check above.)
            page.locator("#requirementKind").select_option("never_use")
            page.locator('#requirementPicker input[value="role:tree"]').check()
            page.locator("#addRequirement").click()
            page.locator("#requirementStatus").filter(
                has_text="newer requirements revision"
            ).wait_for()
            assert page.locator("#generateShow").is_disabled()
            assert page.locator("#addRequirement").is_disabled()
            assert not page.locator("#showDisplayFile").is_disabled()

            summary["token"] = "display-two"
            summary["props"] = [{"name": "Linked Prop", "role": "tree",
                                 "sequenceable": False, "reason": "linked to another prop"}]
            summary["kinds"] = []
            summary["faces"] = True
            summary["can_separate_vocals"] = False
            page.locator("#showDisplayFile").set_input_files(str(preview))
            page.locator("#displayStatus").filter(has_text="nothing it can sequence").wait_for()
            assert page.locator("#saveBatch").is_disabled()
            assert page.locator("#showSongFile").is_disabled()
            assert page.locator("#makeTest").is_disabled()
            assert page.locator("#batchFiles").is_disabled()
            assert page.locator("#singFaces").is_disabled()
            assert not page.locator("#singFaces").is_checked()
        finally:
            browser.close()
