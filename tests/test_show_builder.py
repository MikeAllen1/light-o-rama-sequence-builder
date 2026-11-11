"""Building a new show through the workspace server, on an invented yard and song."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lor_sequence_builder import show_builder
from lor_sequence_builder.loredit import effect_timing_problems, read_loredit
from lor_sequence_builder.ui_server import SequencerRequestHandler
from tests.display_builders import classic_yard
from tests.test_audio_analysis import _rhythmic_track
from tests.test_planner import _preview


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    # Remembered requirements go to a private folder for the test.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(httpd.server_address[1])
    httpd.shutdown()
    thread.join(timeout=2)
    httpd.server_close()


def _post(url: str, body: bytes, kind: str, **headers: str) -> tuple[int, dict[str, Any]]:
    request = Request(url, data=body, method="POST", headers={"Content-Type": kind, **headers})
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        text = error.read()
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, {}


def _json(url: str, value: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return _post(url, json.dumps(value).encode("utf-8"), "application/json")


def test_a_show_is_built_step_by_step_and_requirements_are_remembered(
    server: str, tmp_path: Path,
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    status, started = _post(server + "/api/show/start?name=yard.lorprev", preview,
                            "application/xml")
    assert status == 200, started
    token = started["token"]
    assert {k["role"] for k in started["kinds"]} >= {"arch", "mini_tree", "mega_tree"}
    # The face has no separate mouth props, so there is nothing to sing.
    assert started["faces"] is False and started["can_translate"] is False
    assert started["requirements"] == []

    # Generating before the song is refused with a plain reason.
    status, refused = _json(f"{server}/api/show/generate?token={token}", {})
    assert status == 422 and "Add the song" in refused["error"]

    audio = tmp_path / "beat.wav"
    _rhythmic_track(audio, duration=20.0)
    status, analyzed = _post(f"{server}/api/show/audio?token={token}&name=beat.wav",
                             audio.read_bytes(), "application/octet-stream")
    assert status == 200 and analyzed["report"]["analysis"]["beats"]

    status, set_ = _json(f"{server}/api/show/requirements?token={token}", {"requirements": [
        {"type": "never_use", "props": {"names": ["Mini Tree 1"]}},
        {"type": "keep_on", "props": {"names": ["No Such Prop"]}},
    ]})
    assert status == 200
    assert len(set_["requirements"]) == 1 and "Mini Tree 1" in set_["requirements"][0]
    assert any("No Such Prop" in problem for problem in set_["problems"])
    status, refused = _json(f"{server}/api/show/requirements?token={token}",
                            {"text": "keep the star on"})
    assert status == 422 and "translator" in refused["error"]

    status, show = _json(f"{server}/api/show/generate?token={token}",
                         {"music_filename": "Songs\\beat.wav", "sing": True})
    assert status == 200, show
    assert show["rules_ok"] and show["file_name"] == "beat (generated).loredit"
    assert show["picture"].startswith("<svg") and show["sections"]
    saved = tmp_path / "out.loredit"
    saved.write_text(show["sequence"], encoding="utf-8")
    document = read_loredit(saved)
    assert document.root.attrib["musicFilename"] == "Songs\\beat.wav"
    assert effect_timing_problems(document) == []
    names = {p.attrib["id"]: p.attrib["name"]
             for p in document.root.findall("SequenceProps/SeqProp")}
    lit = {names[p.attrib["id"]] for p in document.root.findall("SequenceProps/SeqProp")
           if p.find("channel/effect") is not None}
    assert "Mini Tree 1" not in lit and "Mini Tree 2" in lit

    # The same display opened again remembers its requirements.
    status, again = _post(server + "/api/show/start?name=yard.lorprev", preview,
                          "application/xml")
    assert status == 200 and len(again["requirements"]) == 1


def test_show_steps_refuse_bad_requests(server: str) -> None:
    assert _post(server + "/api/show/start", b"<nope/>", "application/xml")[0] == 422
    assert _post(server + "/api/show/start", b"x", "text/plain")[0] == 415
    assert _json(server + "/api/show/generate?token=missing", {})[0] == 422
    assert _post(server + "/api/show/start", b"<x/>", "application/xml",
                 Origin="http://attacker.example")[0] == 403
    status, _ = _post(server + "/api/show/requirements?token=x", b"[1]", "application/json")
    assert status == 400


def test_sessions_are_bounded_and_cleaned_up(tmp_path: Path) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    tokens = [sessions.start(preview, "yard.lorprev")["token"]
              for _ in range(show_builder.MAX_SESSIONS + 2)]
    folders = [sessions.get(t).path for t in tokens[-show_builder.MAX_SESSIONS:]]
    with pytest.raises(show_builder.ShowBuildError):
        sessions.get(tokens[0])
    sessions.close()
    assert not any(folder.exists() for folder in folders)


def test_the_workspace_builds_opens_and_saves_a_new_show(server: str, tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    preview = _preview(tmp_path, classic_yard())
    audio = tmp_path / "beat.wav"
    _rhythmic_track(audio, duration=20.0)
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        try:
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#welcomeNewShow").click()
            page.locator("#showDisplayFile").set_input_files(str(preview))
            page.locator("#displayStatus.good").wait_for(timeout=20000)
            assert "arches" in page.locator("#displayStatus").inner_text()
            page.locator("#showSongFile").set_input_files(str(audio))
            page.locator("#songStatus.good").wait_for(timeout=60000)
            assert "BPM" in page.locator("#songStatus").inner_text()
            assert page.locator("#musicFilename").input_value() == "beat.wav"

            page.locator("#requirementKind").select_option("never_use")
            page.locator("#requirementProps").select_option("name:Mini Tree 1")
            page.locator("#addRequirement").click()
            page.locator("#requirementList li").first.wait_for()
            assert "Mini Tree 1" in page.locator("#requirementList").inner_text()

            page.locator("#generateShow").click()
            page.locator("#generateStatus.good").wait_for(timeout=60000)
            assert "Every rule passed" in page.locator("#generateStatus").inner_text()
            page.locator("#openGenerated").click()
            page.locator("#editor").wait_for(state="visible")
            assert page.locator("#exportButton").inner_text() == "Save sequence"
            assert int(page.locator("#effectStat").inner_text().replace(",", "")) > 50
            page.locator("#markerLabels").filter(has_text="Beat candidates").wait_for(
                timeout=20000)
            with page.expect_download() as saved:
                page.locator("#exportButton").click()
            assert saved.value.suggested_filename == "beat (generated).loredit"
            target = tmp_path / "saved.loredit"
            saved.value.save_as(target)
        finally:
            browser.close()
    document = read_loredit(target)
    assert document.root.attrib["musicFilename"] == "beat.wav"
    assert effect_timing_problems(document) == []


def test_session_expiration_is_enforced_when_a_token_is_used(tmp_path: Path) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    folder = session.path
    session.last_used = time.monotonic() - show_builder.SESSION_SECONDS - 1
    with pytest.raises(show_builder.ShowBuildError, match="expired"):
        sessions.get(token)
    assert not folder.exists()


def test_session_cleanup_defers_folder_removal_until_active_work_finishes(
    tmp_path: Path,
) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    folder = session.path
    started = threading.Event()
    release = threading.Event()

    def active_operation() -> None:
        with sessions.locked(token):
            started.set()
            assert release.wait(timeout=2)

    worker = threading.Thread(target=active_operation)
    worker.start()
    assert started.wait(timeout=2)
    sessions.close()
    assert folder.exists()
    release.set()
    worker.join(timeout=2)
    assert not folder.exists()


def test_failed_audio_replacement_preserves_the_previous_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    old_folder = session.path / "audio-old"
    old_folder.mkdir()
    old_audio = old_folder / "song.wav"
    old_analysis = old_folder / "song.analysis.json"
    old_audio.write_bytes(b"previous audio")
    old_analysis.write_text('{"previous": true}', encoding="utf-8")
    session.audio_path = old_audio
    session.analysis_path = old_analysis
    session.audio_name = "previous.wav"

    def fail_analysis(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(show_builder, "analyze_audio", fail_analysis)
    with pytest.raises(RuntimeError, match="synthetic analysis failure"):
        sessions.add_audio(token, b"replacement", ".wav", "wav", "new.wav", 4,
                           request_id=1)
    assert session.audio_path == old_audio and session.analysis_path == old_analysis
    assert old_audio.read_bytes() == b"previous audio"
    assert old_analysis.read_text(encoding="utf-8") == '{"previous": true}'
    assert not list(session.path.glob("audio-*"))[1:]  # failed staging folder was removed
    sessions.close()


def test_stale_audio_requests_cannot_replace_a_newer_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]

    def fake_analysis(audio: Path, analysis: Path, plot: Path, **kwargs: Any) -> dict[str, Any]:
        analysis.write_text('{"fake": true}', encoding="utf-8")
        return {"audio": audio.name}

    monkeypatch.setattr(show_builder, "analyze_audio", fake_analysis)
    newest = sessions.add_audio(token, b"new", ".wav", "wav", "new.wav", 4, request_id=2)
    stale = sessions.add_audio(token, b"old", ".wav", "wav", "old.wav", 4, request_id=1)
    session = sessions.get(token)
    assert newest == {"audio": "song.wav"}
    assert stale == {"stale": True}
    assert session.audio_path is not None and session.audio_path.read_bytes() == b"new"
    sessions.close()


def test_generation_rejects_string_booleans(tmp_path: Path) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]
    with pytest.raises(show_builder.ShowBuildError, match="JSON boolean"):
        sessions.generate(token, {"sing": "false"})
    sessions.close()


def test_stale_requirement_updates_cannot_overwrite_a_newer_submission(
    tmp_path: Path,
) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]
    newest = sessions.set_requirements(token, {"requirements": []}, request_id=2)
    stale = sessions.set_requirements(token, {"requirements": []}, request_id=1)
    assert newest["requirements"] == []
    assert stale == {"stale": True}
    sessions.close()
