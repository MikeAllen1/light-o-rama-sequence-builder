"""Problems end in plain words that say what to do: in the page, the engine, the command
line and the desktop app. Bugs are logged with a reference instead of a traceback."""

from __future__ import annotations

import errno
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from lor_sequence_builder import cli, desktop, diagnostics, ui_server
from lor_sequence_builder.diagnostics import friendly
from lor_sequence_builder.ui_server import SequencerRequestHandler
from tests.display_builders import classic_yard
from tests.test_planner import _preview
from tests.test_show_builder import _json, _post, server  # noqa: F401 - fixture


def _bug(*_: Any, **__: Any) -> Any:
    raise KeyError("missing_part")


@pytest.mark.parametrize(("error", "words"), [
    (OSError(errno.ENOSPC, "No space left on device"), "disk is full"),
    (PermissionError(errno.EACCES, "Permission denied", "/x/Song.loredit"),
     "use a file (Song.loredit). Close any other program"),
    (FileNotFoundError(errno.ENOENT, "No such file", "/x/yard.lorprev"),
     "missing (yard.lorprev)"),
    (MemoryError(), "ran out of memory"),
])
def test_computer_problems_get_plain_words(error: BaseException, words: str) -> None:
    assert words in friendly(error)


def test_refusals_answer_in_json_with_plain_words(server: str,  # noqa: F811
                                                  tmp_path: Path) -> None:
    status, started = _post(server + "/api/show/start?name=yard.lorprev",
                            _preview(tmp_path, classic_yard()).read_bytes(), "application/xml")
    token = started["token"]
    status, refused = _post(f"{server}/api/show/audio?token={token}", b"not a song at all",
                            "application/octet-stream")
    assert status == 415 and "does not look like a song" in refused["error"]
    status, refused = _post(f"{server}/api/show/audio?token={token}", b"",
                            "application/octet-stream")
    assert status == 400 and "file is empty" in refused["error"]
    status, refused = _json(server + "/api/nothing-here", {})
    assert status == 404 and "no such step" in refused["error"]


def test_files_that_do_not_exist_still_get_a_normal_page(server: str) -> None:  # noqa: F811
    with pytest.raises(HTTPError) as missing:
        urlopen(server + "/no-such-file.js", timeout=3)
    assert missing.value.code == 404
    assert "text/html" in missing.value.headers.get("Content-Type", "")


def test_a_bug_answers_with_a_reference_and_is_logged(server: str,  # noqa: F811
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_server.SHOWS, "generate", _bug)
    status, answer = _json(server + "/api/show/generate?token=anything", {})
    assert status == 500
    assert "not with your files" in answer["error"] and answer["reference"] in answer["error"]
    log = (diagnostics.log_folder() / "workspace.log").read_text(encoding="utf-8")
    assert f"{answer['reference']} in /api/show/generate: KeyError" in log
    assert "Traceback" in log and "missing_part" in log


def test_a_file_problem_in_a_step_names_the_cause(server: str,  # noqa: F811
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    def locked(*_: Any, **__: Any) -> Any:
        raise PermissionError(errno.EACCES, "Permission denied", "/x/show.loredit")

    monkeypatch.setattr(ui_server.SHOWS, "generate", locked)
    status, answer = _json(server + "/api/show/generate?token=anything", {})
    assert status == 500 and "show.loredit" in answer["error"]


def test_the_command_line_never_shows_a_traceback(monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "_main", _bug)
    assert cli.main(["generate"]) == 1
    error = capsys.readouterr().err
    assert "something went wrong inside the program (reference" in error
    assert "Traceback" not in error and "diagnostics" in error
    with pytest.raises(KeyError):
        cli.main(["generate", "--debug"])

    def stopped(_: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_main", stopped)
    assert cli.main(["generate"]) == 130


def test_the_command_line_explains_file_problems(tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["inspect", str(tmp_path / "gone.loredit")]) == 2
    error = capsys.readouterr().err
    assert error.startswith("error: Cannot access LOREDIT file") and "Traceback" not in error


def test_diagnostics_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["diagnostics"]) == 0
    assert "Checks:" in capsys.readouterr().out


def test_the_desktop_app_says_why_it_could_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[str] = []
    monkeypatch.setattr(desktop, "_tell", told.append)

    def busy(_: Any) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(desktop, "_main", busy)
    assert desktop.main([]) == 1
    assert "could not start" in told[0] and "disk is full" in told[0]
    assert "workspace.log" in told[0]


def test_the_page_says_when_the_engine_stopped(tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(httpd.server_address[1])
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url + "/", wait_until="networkidle")
            page.locator("#welcomeNewShow").click()
            httpd.shutdown()
            httpd.server_close()
            page.locator("#showDisplayFile").set_input_files(
                str(_preview(tmp_path, classic_yard())))
            page.locator("#displayStatus.error").wait_for(timeout=10000)
            assert "engine is not answering" in page.locator("#displayStatus").inner_text()
        finally:
            browser.close()


def test_the_page_shows_a_bug_reference(server: str,  # noqa: F811
                                        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(ui_server.SHOWS, "start", _bug)
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#welcomeNewShow").click()
            page.locator("#showDisplayFile").set_input_files(
                str(_preview(tmp_path, classic_yard())))
            page.locator("#displayStatus.error").wait_for(timeout=10000)
            text = page.locator("#displayStatus").inner_text()
            assert "not with your files" in text and "reference" in text
        finally:
            browser.close()
