"""Loopback-only browser workspace server and local audio-analysis endpoint."""

from __future__ import annotations

import argparse
import json
import tempfile
import webbrowser
from collections.abc import Sequence
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from lor_sequence_builder import __version__
from lor_sequence_builder.audio_analysis import (
    INPUT_DEMUXERS,
    MAX_INPUT_BYTES,
    AudioAnalysisError,
    analyze_audio,
)
from lor_sequence_builder.loredit import (
    MAX_LOREDIT_BYTES,
    LoreditError,
    effect_timing_problems,
    read_loredit,
)
from lor_sequence_builder.lorprev import MAX_LORPREV_BYTES
from lor_sequence_builder.show_builder import ShowBuildError, ShowSessions

_WEB_ROOT = Path(__file__).with_name("web")
_MAX_UPLOAD_BYTES = MAX_INPUT_BYTES
_MAX_EXPORT_BYTES = 4 * MAX_LOREDIT_BYTES + 1024 * 1024
_MAX_JSON_BYTES = 256 * 1024
# Shows being built from the browser (preview, song, requirements, generate).
SHOWS = ShowSessions()
_SHOW_STEPS = {"/api/show/start", "/api/show/audio", "/api/show/requirements",
               "/api/show/generate", "/api/show/test", "/api/show/batch",
               "/api/show/batch-zip", "/api/show/batch-clear"}


def _looks_like_mp3(data: bytes) -> bool:
    """Recognize common MP3 signatures."""
    return data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
    )


def check_edited_sequence(payload: bytes, original_payload: bytes | None = None) -> dict[str, Any]:
    """Validate an edited sequence from the browser before it is downloaded.

    The same safe reader used for every LOREDIT input checks the XML, the save-file
    version and the prop references; then every effect's timing is checked. Nothing
    is kept on disk.
    """
    with tempfile.TemporaryDirectory(prefix="lor-sequencer-export-") as directory:
        path = Path(directory) / "edited.loredit"
        path.write_bytes(payload)
        document = read_loredit(path)
        original = None
        if original_payload is not None:
            original_path = Path(directory) / "original.loredit"
            original_path.write_bytes(original_payload)
            original = read_loredit(original_path)
    problems = effect_timing_problems(document, original=original)
    if problems:
        raise LoreditError("The edited sequence has timing problems: " + "; ".join(problems))
    root = document.root
    channels = root.findall("SequenceProps/SeqProp/channel")
    return {
        "ok": True,
        "channels": len(channels),
        "effects": sum(len(channel.findall("effect")) for channel in channels),
    }


def _detect_audio_suffix(payload: bytes) -> str | None:
    """Identify a supported container from its bytes, never from a client filename."""
    if payload.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return ".wav"
    if payload.startswith(b"fLaC"):
        return ".flac"
    if payload.startswith(b"OggS"):
        return ".ogg"
    if len(payload) >= 2 and payload[0] == 0xFF and (payload[1] & 0xF6) == 0xF0:
        return ".aac"
    if _looks_like_mp3(payload):
        return ".mp3"
    if payload.startswith(b"FORM") and payload[8:12] in {b"AIFF", b"AIFC"}:
        return ".aiff"
    if payload.startswith(b"\x1a\x45\xdf\xa3"):
        return ".mkv"
    if payload.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"):
        return ".wma"
    if payload.startswith(b"MAC "):
        return ".ape"
    if payload.startswith(b"wvpk"):
        return ".wv"
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        brand = payload[8:12]
        if brand == b"M4A ":
            return ".m4a"
        if brand == b"M4B ":
            return ".m4b"
        return ".mp4"
    return None


class SequencerRequestHandler(SimpleHTTPRequestHandler):
    """Serve only packaged UI assets and accept bounded audio uploads for local analysis."""

    server_version = "LORSequencer/" + __version__

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
        """Analyze audio, check an edited sequence, or build a new show."""
        parsed = urlsplit(self.path)
        if parsed.path not in {"/api/analyze", "/api/export", "/api/update", "/api/log",
                               "/api/diagnostics", *_SHOW_STEPS}:
            self.send_error(404)
            return
        if not self._is_same_origin():
            return
        if parsed.path in {"/api/log", "/api/diagnostics"}:
            self._diagnostics(parsed.path)
            return
        if parsed.path == "/api/update":
            from lor_sequence_builder.update_check import check_for_update

            self._send_json(200, check_for_update())
            return
        if parsed.path == "/api/export":
            self._check_export()
            return
        if parsed.path in _SHOW_STEPS:
            self._show_step(parsed.path, parse_qs(parsed.query))
            return
        self._analyze(parsed.query)

    def _show_step(self, path: str, query: dict[str, list[str]]) -> None:
        token = query.get("token", [""])[0]
        try:
            if path == "/api/show/start":
                payload = self._read_body("application/xml", MAX_LORPREV_BYTES, "Preview")
                if payload is None:
                    return
                name = query.get("name", ["display.lorprev"])[0][:200]
                self._send_json(200, SHOWS.start(payload, name))
            elif path == "/api/show/batch":
                payload = self._read_body("application/octet-stream", _MAX_UPLOAD_BYTES,
                                          "Audio")
                if payload is None:
                    return
                suffix = _detect_audio_suffix(payload)
                if suffix is None or suffix not in INPUT_DEMUXERS:
                    self.send_error(415, "Unsupported or unrecognized audio container")
                    return
                meter = query.get("beats_per_bar", ["4"])[0]
                if meter not in {"3", "4"}:
                    self.send_error(400, "beats_per_bar must be 3 or 4")
                    return
                style = query.get("style", [""])[0] or None
                self._send_json(200, SHOWS.batch_song(
                    token, payload, suffix, INPUT_DEMUXERS[suffix],
                    query.get("name", ["song"])[0][:200], int(meter), style))
            elif path == "/api/show/audio":
                payload = self._read_body("application/octet-stream", _MAX_UPLOAD_BYTES,
                                          "Audio")
                if payload is None:
                    return
                suffix = _detect_audio_suffix(payload)
                if suffix is None or suffix not in INPUT_DEMUXERS:
                    self.send_error(415, "Unsupported or unrecognized audio container")
                    return
                meter = query.get("beats_per_bar", ["4"])[0]
                if meter not in {"3", "4"}:
                    self.send_error(400, "beats_per_bar must be 3 or 4")
                    return
                request_id = None
                if "request_id" in query:
                    try:
                        request_id = int(query["request_id"][0])
                    except (ValueError, IndexError):
                        self.send_error(400, "request_id must be a positive integer")
                        return
                    if request_id < 1:
                        self.send_error(400, "request_id must be a positive integer")
                        return
                report = SHOWS.add_audio(token, payload, suffix, INPUT_DEMUXERS[suffix],
                                         query.get("name", ["song"])[0][:200], int(meter),
                                         request_id=request_id)
                self._send_json(200, {"stale": True} if report.get("stale") else
                                {"report": report})
            else:
                body = self._read_json()
                if body is None:
                    return
                if path == "/api/show/requirements":
                    request_id = None
                    if "request_id" in query:
                        try:
                            request_id = int(query["request_id"][0])
                        except (ValueError, IndexError):
                            self.send_error(400, "request_id must be a positive integer")
                            return
                        if request_id < 1:
                            self.send_error(400, "request_id must be a positive integer")
                            return
                    result = SHOWS.set_requirements(token, body, request_id=request_id)
                    self._send_json(200, result)
                elif path == "/api/show/batch-zip":
                    self._send_json(200, SHOWS.batch_zip(token))
                elif path == "/api/show/batch-clear":
                    self._send_json(200, SHOWS.batch_clear(token))
                elif path == "/api/show/test":
                    self._send_json(200, SHOWS.display_test(token))
                else:
                    self._send_json(200, SHOWS.generate(token, body))
        except (ShowBuildError, AudioAnalysisError, ValueError, RuntimeError) as exc:
            self._send_json(422, {"error": str(exc)})
        except OSError:
            self._send_json(500, {"error": "The show could not be built on this computer"})

    def _read_json(self) -> dict[str, Any] | None:
        payload = self._read_body("application/json", _MAX_JSON_BYTES, "Request")
        if payload is None:
            return None
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "Expected a JSON object")
            return None
        if not isinstance(body, dict):
            self.send_error(400, "Expected a JSON object")
            return None
        return body

    def _is_same_origin(self) -> bool:
        expected_host = "127.0.0.1:" + str(cast(ThreadingHTTPServer, self.server).server_port)
        request_host = self.headers.get("Host")
        if request_host != expected_host:
            self.send_error(403, "Requests must use the loopback workspace host")
            return False
        origin = self.headers.get("Origin")
        if origin:
            origin_url = urlsplit(origin)
            if origin_url.scheme != "http" or origin_url.netloc != expected_host:
                self.send_error(403, "Cross-origin requests are not accepted")
                return False
        return True

    def _read_body(self, content_type: str, limit: int, what: str) -> bytes | None:
        if self.headers.get_content_type() != content_type:
            self.send_error(415, "Expected " + content_type)
            return None
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length <= 0:
            self.send_error(400, "A non-empty Content-Length is required")
            return None
        if length > limit:
            self.send_error(413, f"{what} exceeds the {limit // (1024 * 1024)} MiB upload limit")
            return None
        payload = self.rfile.read(length)
        if len(payload) != length:
            self.send_error(400, f"{what} upload was incomplete")
            return None
        return payload

    def _check_export(self) -> None:
        payload = self._read_body("application/json", _MAX_EXPORT_BYTES, "Sequence export")
        if payload is None:
            return
        try:
            request = json.loads(payload)
            if not isinstance(request, dict):
                raise LoreditError("Sequence export request must be an object")
            edited = request.get("edited")
            original = request.get("original")
            if (not isinstance(edited, str) or not isinstance(original, str)
                    or len(edited.encode("utf-8")) > MAX_LOREDIT_BYTES
                    or len(original.encode("utf-8")) > MAX_LOREDIT_BYTES):
                raise LoreditError("Sequence export must include bounded original and edited XML")
            self._send_json(200, check_edited_sequence(
                edited.encode("utf-8"), original.encode("utf-8")
            ))
        except (LoreditError, UnicodeError, ValueError, TypeError) as exc:
            self._send_json(422, {"error": str(exc) or "Invalid sequence export request"})
        except OSError:
            self._send_json(500, {"error": "The edited sequence could not be checked"})

    def _analyze(self, query_text: str) -> None:
        payload = self._read_body("application/octet-stream", _MAX_UPLOAD_BYTES, "Audio")
        if payload is None:
            return

        suffix = _detect_audio_suffix(payload)
        if suffix is None or suffix not in INPUT_DEMUXERS:
            self.send_error(415, "Unsupported or unrecognized audio container")
            return
        warning = None

        query = parse_qs(query_text)
        meter_values = query.get("beats_per_bar", ["4"])
        if meter_values[0] not in {"3", "4"}:
            self.send_error(400, "beats_per_bar must be 3 or 4")
            return
        beats_per_bar = int(meter_values[0])

        try:
            with tempfile.TemporaryDirectory(prefix="lor-sequencer-ui-") as directory:
                folder = Path(directory)
                audio_path = folder / "selected-audio.input"
                json_path = folder / "analysis.json"
                plot_path = folder / "analysis.svg"
                audio_path.write_bytes(payload)
                report = analyze_audio(
                    audio_path,
                    json_path,
                    plot_path,
                    beats_per_bar=beats_per_bar,
                    input_demuxer=INPUT_DEMUXERS[suffix],
                )
            self._send_json(200, {"report": report, "warning": warning})
        except AudioAnalysisError as exc:
            self._send_json(422, {"error": str(exc), "warning": warning})
        except OSError:
            self._send_json(500, {"error": "Local audio analysis could not complete"})

    def _diagnostics(self, path: str) -> None:
        from lor_sequence_builder.diagnostics import report, write_log

        body = self._read_json()
        if body is None:
            return
        if path == "/api/log":
            where = str(body.get("where", ""))[:200]
            write_log("page", f"{str(body.get('message', ''))[:1500]} ({where})")
            self._send_json(200, {"ok": True})
            return
        steps = body.get("steps")
        clean = [str(step) for step in steps[:100]] if isinstance(steps, list) else []
        self._send_json(200, {"text": report(str(body.get("browser", "")), clean)})

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        if status >= 400:
            from lor_sequence_builder.diagnostics import write_log

            write_log("server", f"{urlsplit(self.path).path} answered {status}: "
                      f"{str(payload.get('error', ''))[:500]}")
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
        SHOWS.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
