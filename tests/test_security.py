"""Only the workspace's own window can use the engine, and nothing a file or name contains
can make it misbehave."""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest

from lor_sequence_builder import progress, ui_server
from lor_sequence_builder.show_builder import file_stem
from tests.test_show_builder import _json, _post, server  # noqa: F401 - fixture


def _port(url: str) -> str:
    return str(urlsplit(url).port)


def test_localhost_is_the_same_computer(server: str) -> None:  # noqa: F811
    status, _ = _post(server + "/api/progress?key=x", b"{}", "application/json",
                      Host="localhost:" + _port(server))
    assert status == 200


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"},
    {"Origin": "http://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_other_sites_cannot_use_the_engine(server: str, headers: dict[str, str]) -> None:  # noqa: F811
    status, answer = _post(server + "/api/progress?key=x", b"{}", "application/json", **headers)
    assert status == 403 and answer["error"]


def test_pages_are_only_served_to_this_computer(server: str) -> None:  # noqa: F811
    with pytest.raises(HTTPError) as refused:
        urlopen(Request(server + "/", headers={"Host": "rebound.example"}), timeout=5)
    assert refused.value.code == 403
    with urlopen(server + "/", timeout=5) as page:
        assert page.headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert page.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]


def test_folders_are_never_listed() -> None:
    handler = object.__new__(ui_server.SequencerRequestHandler)
    sent: list[int] = []
    handler.send_error = lambda code, *_: sent.append(code)  # type: ignore[method-assign]
    assert handler.list_directory(".") is None and sent == [404]


def test_deeply_nested_json_is_refused_plainly(server: str) -> None:  # noqa: F811
    body = ("[" * 100_000 + "]" * 100_000).encode()
    status, answer = _post(server + "/api/show/requirements?token=x", body, "application/json")
    assert status == 400 and "JSON" in answer["error"]
    status, answer = _post(server + "/api/export", b'{"a":' * 50_000 + b"1" + b"}" * 50_000,
                           "application/json")
    assert status == 422


@pytest.mark.parametrize(("name", "stem"), [
    ("Jingle Bells.mp3", "Jingle Bells"),
    ("..\\..\\Windows\\evil.mp3", "evil"),
    ("../../etc/passwd", "passwd"),
    ('Rock: "Live" <1999>?.flac', "Rock_ _Live_ _1999__"),
    ("CON.mp3", "CON song"),
    ("nul", "nul song"),
    ("  .hidden. .mp3", "hidden"),
    ("", "song"),
    ("tab\there.mp3", "tab_here"),
])
def test_song_names_become_safe_windows_file_names(name: str, stem: str) -> None:
    assert file_stem(name) == stem
    assert len(file_stem("x" * 500 + ".mp3")) == 120


def test_heavy_jobs_wait_their_turn(server: str, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(ui_server, "_heavy", threading.BoundedSemaphore(1))

    def slow_test(token: str) -> dict[str, Any]:
        time.sleep(1.0)
        return {"ok": True}

    monkeypatch.setattr(ui_server.SHOWS, "display_test", slow_test)
    results: list[int] = []

    def run(key: str) -> None:
        status, _ = _json(f"{server}/api/show/test?token=t&progress={key}", {})
        results.append(status)

    started = time.monotonic()
    first = threading.Thread(target=run, args=("first0000000",))
    first.start()
    time.sleep(0.2)
    second = threading.Thread(target=run, args=("second000000",))
    second.start()
    time.sleep(0.3)
    assert progress.snapshot("second000000")["step"] == "Waiting for another song to finish first"
    first.join()
    second.join()
    assert results == [200, 200] and time.monotonic() - started >= 2.0


def test_the_session_token_never_reaches_the_log(server: str) -> None:  # noqa: F811
    from lor_sequence_builder import diagnostics

    _json(server + "/api/show/generate?token=SECRET-TOKEN-123", {})
    log = (diagnostics.log_folder() / "workspace.log").read_text(encoding="utf-8")
    assert "/api/show/generate answered" in log and "SECRET-TOKEN-123" not in log
    assert json.dumps({"ok": True})
