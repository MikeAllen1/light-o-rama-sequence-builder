from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lor_sequence_builder.ui_server import (
    SequencerRequestHandler,
    _WEB_ROOT,
    _looks_like_mp3,
)


@pytest.fixture
def local_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(server.server_address[1])
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_browser_workspace_is_packaged_and_served_with_security_headers(
    local_server: str,
) -> None:
    assert (_WEB_ROOT / "index.html").is_file()
    with urlopen(local_server + "/", timeout=3) as response:
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "Content-Security-Policy" in response.headers
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        assert "X-Content-Type-Options" in response.headers
        assert "LOR SEQUENCER" in body


def test_audio_analysis_endpoint_rejects_cross_origin_requests(local_server: str) -> None:
    request = Request(
        local_server + "/api/analyze",
        data=b"not-a-real-audio-file",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Audio-Filename": "song.mp3",
            "Origin": "http://attacker.example",
        },
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=3)
    assert error.value.code == 403


def test_audio_analysis_endpoint_rejects_unsupported_extensions(local_server: str) -> None:
    request = Request(
        local_server + "/api/analyze",
        data=b"not-a-real-audio-file",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Audio-Filename": "payload.exe",
        },
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=3)
    assert error.value.code == 415


def test_mp3_signature_detection_handles_id3_and_mpeg_frames() -> None:
    assert _looks_like_mp3(bytes([73, 68, 51, 3, 0, 0]))
    assert _looks_like_mp3(bytes([255, 251, 180, 64]))
    assert not _looks_like_mp3(bytes([0, 0, 0, 24]) + b"ftypmp42")
