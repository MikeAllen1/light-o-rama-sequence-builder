"""Loopback-only browser workspace server and local audio-analysis endpoint."""

from __future__ import annotations

import argparse
import json
import tempfile
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from lor_sequence_builder.audio_analysis import (
    AudioAnalysisError,
    INPUT_DEMUXERS,
    MAX_INPUT_BYTES,
    analyze_audio,
)

_WEB_ROOT = Path(__file__).with_name("web")
_MAX_UPLOAD_BYTES = MAX_INPUT_BYTES


def _looks_like_mp3(data: bytes) -> bool:
    """Recognize common MP3 signatures so a mislabeled source can still be analyzed."""
    return data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
    )


class SequencerRequestHandler(SimpleHTTPRequestHandler):
    """Serve only packaged UI assets and accept bounded audio uploads for local analysis."""

    server_version = "LORSequencer/0.1"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(_WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_POST(self) -> None:
        """Analyze a selected local audio file; the upload is never persisted."""
        parsed = urlsplit(self.path)
        if parsed.path != "/api/analyze":
            self.send_error(404)
            return

        origin = self.headers.get("Origin")
        if origin:
            origin_url = urlsplit(origin)
            if origin_url.scheme != "http" or origin_url.netloc != self.headers.get("Host"):
                self.send_error(403, "Cross-origin requests are not accepted")
                return

        if self.headers.get_content_type() != "application/octet-stream":
            self.send_error(415, "Expected application/octet-stream")
            return

        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length <= 0:
            self.send_error(400, "A non-empty Content-Length is required")
            return
        if length > _MAX_UPLOAD_BYTES:
            self.send_error(413, "Audio exceeds the 200 MiB upload limit")
            return

        payload = self.rfile.read(length)
        if len(payload) != length:
            self.send_error(400, "Audio upload was incomplete")
            return

        supplied_name = unquote(self.headers.get("X-Audio-Filename", "audio.mp3"))
        suffix = Path(supplied_name).suffix.lower()
        warning: str | None = None
        if suffix == ".mp4" and _looks_like_mp3(payload):
            suffix = ".mp3"
            warning = (
                "The selected file is named .mp4 but contains an MP3 audio stream. "
                "It was analyzed as MP3; the original file was not changed."
            )
        if suffix not in INPUT_DEMUXERS:
            self.send_error(415, "Unsupported audio file extension")
            return

        query = parse_qs(parsed.query)
        meter_values = query.get("beats_per_bar", ["4"])
        if meter_values[0] not in {"3", "4"}:
            self.send_error(400, "beats_per_bar must be 3 or 4")
            return
        beats_per_bar = int(meter_values[0])

        try:
            with tempfile.TemporaryDirectory(prefix="lor-sequencer-ui-") as directory:
                folder = Path(directory)
                audio_path = folder / ("selected-audio" + suffix)
                json_path = folder / "analysis.json"
                plot_path = folder / "analysis.svg"
                audio_path.write_bytes(payload)
                report = analyze_audio(
                    audio_path,
                    json_path,
                    plot_path,
                    beats_per_bar=beats_per_bar,
                )
            self._send_json(200, {"report": report, "warning": warning})
        except AudioAnalysisError as exc:
            self._send_json(422, {"error": str(exc), "warning": warning})
        except OSError:
            self._send_json(500, {"error": "Local audio analysis could not complete"})

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the browser workspace on loopback; no desktop runtime is installed."""
    parser = argparse.ArgumentParser(
        prog="lor-sequence-ui",
        description="Open the local browser-based Light-O-Rama sequencing workspace.",
    )
    parser.add_argument("--port", type=int, default=8765, help="local HTTP port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    options = parser.parse_args(argv)
    if not 0 <= options.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not _WEB_ROOT.is_dir():
        parser.error("The packaged sequencing workspace assets are missing")

    server = ThreadingHTTPServer(("127.0.0.1", options.port), SequencerRequestHandler)
    server.daemon_threads = True
    address = server.server_address
    url = "http://127.0.0.1:" + str(address[1]) + "/"
    print("LOR Sequencing Workspace: " + url)
    print("Local only. Press Ctrl+C to stop.")
    if not options.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LOR Sequencing Workspace.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
