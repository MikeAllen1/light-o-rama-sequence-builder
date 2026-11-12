"""Building a new show through the workspace server, on an invented yard and song."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import zipfile
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lor_sequence_builder import show_builder
from lor_sequence_builder.loredit import effect_timing_problems, read_loredit
from lor_sequence_builder.ui_server import SHOWS, SequencerRequestHandler
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

    status, refused = _json(f"{server}/api/show/generate?token={token}",
                            {"music_filename": "x" * 261, "sing": False,
                             "style": "energetic"})
    assert status == 422 and "260 characters or fewer" in refused["error"]

    status, show = _json(f"{server}/api/show/generate?token={token}",
                         {"music_filename": "Songs\\beat.wav", "sing": True,
                          "style": "energetic"})
    assert status == 200, show
    assert show["rules_ok"] and show["file_name"] == "beat (generated).loredit"
    assert show["picture"].startswith("<svg") and show["sections"]
    assert show["summary"].startswith("<!doctype html>") and "Check in the yard" in show["summary"]
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
    assert len(again["raw_requirements"]) == 1
    assert again["raw_requirements"][0]["type"] == "never_use"


def test_requirement_persistence_failure_does_not_publish_session_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    started = sessions.start(preview, "yard.lorprev")
    token = started["token"]

    def fail_persist(session: Any, requirements: Any) -> None:
        raise OSError("disk is unavailable")

    monkeypatch.setattr(sessions, "_remember", fail_persist)
    with pytest.raises(OSError, match="disk is unavailable"):
        sessions.set_requirements(token, {"requirements": [
            {"type": "never_use", "props": {"names": ["Mini Tree 1"]}},
        ]}, request_id=1)

    session = sessions.get(token)
    assert session.requirements == ()
    assert session.requirements_revision == 0
    sessions.close()


def test_batch_song_rejects_duplicate_audio_names_case_insensitively(
    tmp_path: Path,
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    session.batch.append({
        "stem": "song", "file_name": "song.wav", "ok": False,
    })

    with pytest.raises(show_builder.ShowBuildError, match="already contains a song"):
        sessions.batch_song(token, b"audio", ".wav", "ffmpeg", "SONG.WAV", 4, None)

    assert len(session.batch) == 1
    assert not (session.path / "batch").exists()
    sessions.close()


def test_song_upload_rejects_names_that_would_be_truncated(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    token = sessions.start(preview, "yard.lorprev")["token"]
    long_name = "x" * 201 + ".wav"

    with pytest.raises(show_builder.ShowBuildError, match="200 characters"):
        sessions.add_audio(token, b"audio", ".wav", "ffmpeg", long_name, 4)
    with pytest.raises(show_builder.ShowBuildError, match="200 characters"):
        sessions.batch_song(token, b"audio", ".wav", "ffmpeg", long_name, 4, None)

    session = sessions.get(token)
    assert session.audio_path is None
    assert session.analysis_path is None
    assert session.audio_revision == 0
    assert session.batch == []
    sessions.close()


def test_batch_publish_failure_removes_partial_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    token = sessions.start(preview, "yard.lorprev")["token"]

    def fake_analyze(audio: Path, report: Path, picture: Path, **kwargs: Any) -> dict[str, Any]:
        report.write_text("{}", encoding="utf-8")
        return {"audio": {"duration_seconds": 10.0}}

    def fake_generate(preview_path: Path, output: Path, rule_set: Any, **kwargs: Any) -> Any:
        output.write_text("<sequence />", encoding="utf-8")
        summary = output.with_suffix(".report.html")
        summary.write_text("<html>report</html>", encoding="utf-8")
        return SimpleNamespace(
            sequence_path=output,
            summary_path=summary,
            plan=SimpleNamespace(sections=(1, 2), used_props=("Tree",)),
        )

    monkeypatch.setattr(show_builder, "analyze_audio", fake_analyze)
    monkeypatch.setattr(show_builder, "load_rule_set", lambda profiles: object())
    monkeypatch.setattr(show_builder, "generate_show", fake_generate)
    real_link = show_builder.os.link
    link_calls = 0

    def fail_second_link(source: Path, target: Path) -> None:
        nonlocal link_calls
        link_calls += 1
        if link_calls == 2:
            raise OSError("simulated report publish failure")
        real_link(source, target)

    monkeypatch.setattr(show_builder.os, "link", fail_second_link)
    with pytest.raises(OSError, match="simulated report publish failure"):
        sessions.batch_song(token, b"audio", ".wav", "ffmpeg", "song.wav", 4, None)

    session = sessions.get(token)
    assert session.batch == []
    assert list((session.path / "batch").iterdir()) == []
    sessions.close()


def test_batch_song_rejects_archive_overflow_before_publishing_new_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    done = session.path / "batch"
    done.mkdir()
    existing_show = done / "Existing (generated).loredit"
    existing_report = done / "Existing (generated).report.html"
    existing_show.write_bytes(b"x" * 80)
    existing_report.write_bytes(b"")
    session.batch.append({
        "ok": True, "stem": "Existing", "file_name": "existing.wav",
        "show": existing_show.name,
    })

    def fake_analyze(audio: Path, report: Path, picture: Path, **kwargs: Any) -> dict[str, Any]:
        report.write_text("{}", encoding="utf-8")
        return {"audio": {"duration_seconds": 10.0}}

    def fake_generate(preview_path: Path, output: Path, rule_set: Any, **kwargs: Any) -> Any:
        output.write_bytes(b"y" * 30)
        summary = output.with_suffix(".report.html")
        summary.write_bytes(b"z" * 10)
        return SimpleNamespace(
            sequence_path=output,
            summary_path=summary,
            plan=SimpleNamespace(sections=(1,), used_props=("Tree",)),
        )

    monkeypatch.setattr(show_builder, "MAX_BATCH_ARCHIVE_BYTES", 100)
    monkeypatch.setattr(show_builder, "analyze_audio", fake_analyze)
    monkeypatch.setattr(show_builder, "load_rule_set", lambda profiles: object())
    monkeypatch.setattr(show_builder, "generate_show", fake_generate)

    with pytest.raises(show_builder.ShowBuildError, match="100 MiB playlist download limit"):
        sessions.batch_song(token, b"audio", ".wav", "ffmpeg", "new.wav", 4, None)

    assert session.batch == [{
        "ok": True, "stem": "Existing", "file_name": "existing.wav",
        "show": existing_show.name,
    }]
    assert existing_show.read_bytes() == b"x" * 80
    assert existing_report.is_file()
    assert not (done / "New (generated).loredit").exists()
    assert not (done / "New (generated).report.html").exists()
    sessions.close()


def test_batch_song_refuses_to_exceed_the_playlist_archive_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    token = sessions.start(preview, "yard.lorprev")["token"]

    def fake_analyze(audio: Path, report: Path, picture: Path, **kwargs: Any) -> dict[str, Any]:
        report.write_text("{}", encoding="utf-8")
        return {"audio": {"duration_seconds": 10.0}}

    def fake_generate(preview_path: Path, output: Path, rule_set: Any, **kwargs: Any) -> Any:
        output.write_text("<sequence />", encoding="utf-8")
        summary = output.with_suffix(".report.html")
        summary.write_text("<html>report</html>", encoding="utf-8")
        return SimpleNamespace(
            sequence_path=output,
            summary_path=summary,
            plan=SimpleNamespace(sections=(1,), used_props=("Tree",)),
        )

    monkeypatch.setattr(show_builder, "analyze_audio", fake_analyze)
    monkeypatch.setattr(show_builder, "load_rule_set", lambda profiles: object())
    monkeypatch.setattr(show_builder, "generate_show", fake_generate)
    monkeypatch.setattr(show_builder, "MAX_BATCH_ARCHIVE_BYTES", 10)

    with pytest.raises(show_builder.ShowBuildError, match="exceed the 100 MiB playlist download limit"):
        sessions.batch_song(token, b"audio", ".wav", "ffmpeg", "large.wav", 4, None)

    session = sessions.get(token)
    assert session.batch == []
    assert list((session.path / "batch").iterdir()) == []
    sessions.close()


def test_batch_zip_rejects_oversized_archive_before_allocating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    done = session.path / "batch"
    done.mkdir()
    (done / "large.loredit").write_bytes(b"x" * 8)
    (done / "large (generated).report.html").write_bytes(b"y" * 8)
    session.batch.append({
        "ok": True, "show": "large.loredit", "stem": "large", "file_name": "large.wav",
    })
    monkeypatch.setattr(show_builder, "MAX_BATCH_ARCHIVE_BYTES", 10)

    with pytest.raises(show_builder.ShowBuildError, match="100 MiB download limit"):
        sessions.batch_zip(token)

    sessions.close()


def test_batch_download_open_failure_returns_error_before_zip_headers(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = SHOWS.start(preview, "yard.lorprev")["token"]
    session = SHOWS.get(token)
    done = session.path / "batch"
    done.mkdir()
    (done / "Song (generated).loredit").write_text("<sequence/>", encoding="utf-8")
    (done / "Song (generated).report.html").write_text("<html/>", encoding="utf-8")
    session.batch.append({
        "ok": True, "stem": "Song", "file_name": "Song.wav",
        "show": "Song (generated).loredit",
    })

    original_open = Path.open
    archive_paths: list[Path] = []

    def refuse_batch_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name.startswith("lor-batch-"):
            archive_paths.append(path)
            raise PermissionError("synthetic archive-open failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse_batch_open)
    request = Request(
        server + "/api/show/batch-zip?token=" + token,
        data=b"{}", method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=10)
        assert error.value.code == 500
        assert json.loads(error.value.read())["error"]
        assert len(archive_paths) == 1
        assert not archive_paths[0].exists()
    finally:
        with SHOWS._lock:
            SHOWS._drop(token)


def test_batch_clear_failure_keeps_the_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    started = sessions.start(preview, "yard.lorprev")
    token = started["token"]
    session = sessions.get(token)
    done = session.path / "batch"
    done.mkdir()
    (done / "old-show.loredit").write_text("old", encoding="utf-8")
    session.batch.append({"ok": True, "show": "old-show.loredit"})

    def fail_rename(source: Path, destination: Path) -> None:
        raise OSError("directory is locked")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_rename)
        with pytest.raises(OSError, match="directory is locked"):
            sessions.batch_clear(token)

    assert session.batch == [{"ok": True, "show": "old-show.loredit"}]
    assert (done / "old-show.loredit").is_file()
    sessions.close()


def test_partial_retired_batch_cleanup_cannot_damage_the_active_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    sessions = show_builder.ShowSessions()
    started = sessions.start(preview, "yard.lorprev")
    token = started["token"]
    session = sessions.get(token)
    done = session.path / "batch"
    done.mkdir()
    old_show = done / "old-show.loredit"
    old_show.write_text("old", encoding="utf-8")
    session.batch.append({"ok": True, "show": old_show.name})

    def partially_remove(path: Path, *args: Any, **kwargs: Any) -> None:
        # Simulate Windows deleting some artifacts before a locked file stops rmtree.
        next(path.iterdir()).unlink()
        raise OSError("one retired file is locked")

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", partially_remove)
        assert sessions.batch_clear(token) == {"cleared": True}

    assert session.batch == []
    assert not done.exists()
    retired = list(session.path.glob("batch-reset-*"))
    assert len(retired) == 1
    assert retired[0].is_dir()
    sessions.close()


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
            # The landing page's yard is drawn and animates.
            page.locator("#heroYard[data-bar]").wait_for(state="attached", timeout=10000)
            page.locator('#heroYard:not([data-bar="0"])').wait_for(state="attached", timeout=10000)
            page.locator("#welcomeNewShow").click()
            page.locator("#showDisplayFile").set_input_files(str(preview))
            page.locator("#displayStatus.good").wait_for(timeout=20000)
            assert "arches" in page.locator("#displayStatus").inner_text()
            page.locator("#makeTest").click()
            page.locator("#testStatus.good").wait_for(timeout=30000)
            with page.expect_download() as test_files:
                page.locator("#saveTest").click()
            assert test_files.value.suggested_filename.endswith("display test.zip")
            page.locator("#showSongFile").set_input_files(str(audio))
            page.locator("#songStatus.good").wait_for(timeout=60000)
            assert "BPM" in page.locator("#songStatus").inner_text()
            assert page.locator("#musicFilename").input_value() == "beat.wav"
            assert "S6 will look for beat.wav" in page.locator("#musicNote").inner_text()
            page.locator("#musicFilename").fill("Beat.mp3")
            assert "your song file is beat.wav" in page.locator("#musicNote.warn").inner_text()
            page.locator("#musicFilename").fill("beat.mp3")
            assert "ending differs" in page.locator("#musicNote.warn").inner_text()
            page.locator("#musicFilename").fill("beat.wav")

            page.locator("#requirementKind").select_option("never_use")
            page.locator("#requirementProps").select_option("name:Mini Tree 1")
            page.locator("#addRequirement").click()
            page.locator("#requirementList li").first.wait_for()
            assert "Mini Tree 1" in page.locator("#requirementList").inner_text()

            assert page.locator('input[name="showStyle"]:checked').get_attribute("value") \
                == "classic"
            page.locator('input[name="showStyle"][value="elegant"]').check()
            page.locator("#yardButton").click()  # nothing to play yet: says what to do
            assert "Generate a show first" in page.locator("#generateStatus").inner_text()
            page.locator("#generateShow").click()
            page.locator("#generateStatus.good").wait_for(timeout=60000)
            assert "Every rule passed" in page.locator("#generateStatus").inner_text()
            assert "A 0:20 show." in page.locator("#generateStatus").inner_text()
            with page.expect_download() as show_file:
                page.locator("#saveGenerated").click()
            assert show_file.value.suggested_filename == "beat (generated).loredit"
            page.locator("#reportGenerated").click()
            page.frame_locator("#viewerFrame").get_by_text("Check in the yard").wait_for()
            with page.expect_download() as report_file:
                page.locator("#viewerSave").click()
            assert report_file.value.suggested_filename == "beat (generated).report.html"
            page.keyboard.press("Escape")
            assert page.locator("#viewer").is_hidden()
            page.locator("#pictureGenerated").click()
            page.frame_locator("#viewerFrame").locator("svg").wait_for()
            page.locator("#viewerClose").click()
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


def test_batch_zip_is_streamed_as_a_file_download(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Windows can refuse to delete a file briefly after it has been streamed.
    # That cleanup failure must not turn the successful download into an HTTP 500.
    path_type = type(tmp_path)
    original_unlink = path_type.unlink
    failed_cleanup: list[Path] = []

    def refuse_batch_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name.startswith("lor-batch-"):
            failed_cleanup.append(path)
            raise PermissionError("synthetic file-in-use failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "unlink", refuse_batch_cleanup)
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    started = SHOWS.start(preview, "yard.lorprev")
    token = started["token"]
    session = SHOWS.get(token)
    done = session.path / "batch"
    done.mkdir()
    (done / "Song (generated).loredit").write_text("<sequence/>", encoding="utf-8")
    (done / "Song (generated).report.html").write_text("<html/>", encoding="utf-8")
    session.batch.append({
        "stem": "Song", "file_name": "Song.wav", "ok": True,
        "show": "Song (generated).loredit",
    })
    try:
        request = Request(
            server + "/api/show/batch-zip?token=" + token,
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            payload = response.read()
            assert response.status == 200
            assert response.headers.get_content_type() == "application/zip"
            assert "Fictional%20Classic%20Yard%20shows.zip" in response.headers["Content-Disposition"]
        archive = BytesIO(payload)
        assert zipfile.is_zipfile(archive)
        archive.seek(0)
        with zipfile.ZipFile(archive) as zipped:
            assert set(zipped.namelist()) == {
                "Song (generated).loredit",
                "Song (generated).report.html",
                "Batch - read me.txt",
            }
        assert len(failed_cleanup) == 1
        assert failed_cleanup[0].is_file()
        original_unlink(failed_cleanup[0], missing_ok=True)
    finally:
        with SHOWS._lock:
            SHOWS._drop(token)


def test_batch_download_open_failure_returns_error_before_zip_headers(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    started = SHOWS.start(preview, "yard.lorprev")
    token = started["token"]
    session = SHOWS.get(token)
    done = session.path / "batch"
    done.mkdir()
    (done / "Song (generated).loredit").write_text("<sequence/>", encoding="utf-8")
    (done / "Song (generated).report.html").write_text("<html/>", encoding="utf-8")
    session.batch.append({
        "stem": "Song", "file_name": "Song.wav", "ok": True,
        "show": "Song (generated).loredit",
    })

    original_open = Path.open

    def refuse_batch_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name.startswith("lor-batch-"):
            raise PermissionError("synthetic archive-open failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse_batch_open)
    request = Request(
        server + "/api/show/batch-zip?token=" + token,
        data=b"{}", method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=10)
        assert error.value.code == 500
        payload = json.loads(error.value.read())
        assert payload["error"]
    finally:
        with SHOWS._lock:
            SHOWS._drop(token)



def test_session_expiration_is_enforced_when_a_token_is_used(tmp_path: Path) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    token = sessions.start(preview, "yard.lorprev")["token"]
    session = sessions.get(token)
    folder = session.path
    session.last_used = time.monotonic() - show_builder.SESSION_SECONDS - 1
    with pytest.raises(show_builder.ShowBuildError, match="put away after a long break"):
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
    close_started = threading.Event()
    close_finished = threading.Event()

    def active_operation() -> None:
        with sessions.locked(token):
            started.set()
            assert release.wait(timeout=5)

    def close_sessions() -> None:
        close_started.set()
        sessions.close()
        close_finished.set()

    worker = threading.Thread(target=active_operation)
    worker.start()
    assert started.wait(timeout=2)
    closer = threading.Thread(target=close_sessions)
    closer.start()
    assert close_started.wait(timeout=2)
    assert not close_finished.wait(timeout=0.1)
    assert folder.exists()
    release.set()
    worker.join(timeout=2)
    closer.join(timeout=2)
    assert not worker.is_alive() and not closer.is_alive()
    assert close_finished.is_set()
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


def test_session_eviction_waits_for_an_active_operation(tmp_path: Path) -> None:
    sessions = show_builder.ShowSessions()
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    tokens = [sessions.start(preview, "yard.lorprev")["token"]
              for _ in range(show_builder.MAX_SESSIONS)]
    active_path = sessions.get(tokens[0]).path
    started = threading.Event()
    finished = threading.Event()

    def expire_sessions() -> None:
        with sessions._lock:
            started.set()
            sessions._expire()
        finished.set()

    worker: threading.Thread | None = None
    try:
        with sessions.locked(tokens[0]) as active:
            # Make this active session the next eviction candidate.
            active.last_used = 0
            worker = threading.Thread(target=expire_sessions)
            worker.start()
            assert started.wait(timeout=2)
            assert not finished.wait(timeout=0.1)
            assert active_path.exists()
        assert worker is not None
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert finished.is_set()
        assert not active_path.exists()
    finally:
        if worker is not None and worker.is_alive():
            worker.join(timeout=2)
        sessions.close()


def test_an_unknown_style_is_refused_by_the_server(server: str, tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard()).read_bytes()
    status, started = _post(server + "/api/show/start", preview, "application/xml")
    assert status == 200 and [s["key"] for s in started["styles"]] == [
        "classic", "energetic", "elegant"]
    status, refused = _json(f"{server}/api/show/generate?token={started['token']}",
                            {"style": "disco"})
    assert status == 422 and "Unknown style" in refused["error"]
