"""Loopback-only browser workspace server and local audio-analysis endpoint."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import webbrowser
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, quote, urlsplit

from lor_sequence_builder import __version__, progress, recent_shows
from lor_sequence_builder.audio_analysis import (
    INPUT_DEMUXERS,
    MAX_INPUT_BYTES,
    AudioAnalysisError,
    analyze_audio,
)
from lor_sequence_builder.diagnostics import friendly
from lor_sequence_builder.lms import MAX_LMS_BYTES, LmsDocument, LmsError, parse_lms
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
    if _is_s4(payload):
        return _check_edited_lms(payload, original_payload)
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


def _is_s4(payload: bytes) -> bool:
    """An S4 sequence: version 14 with a flat channel list instead of SequenceProps."""
    head = payload[:4096]
    return b'saveFileVersion="14"' in head and b"<SequenceProps" not in payload


def _lms_channel_identity(document: LmsDocument) -> list[tuple[object, ...]]:
    return [(c.saved_index, c.name, c.device_type, c.network, c.unit, c.circuit)
            for c in document.channels]


def _check_edited_lms(payload: bytes, original_payload: bytes | None) -> dict[str, Any]:
    """An edited S4 sequence must keep every channel and address; effects must not
    overlap or run past the end."""
    document = parse_lms(payload, "The edited sequence")
    if original_payload is not None:
        original = parse_lms(original_payload, "The original sequence")
        if _lms_channel_identity(document) != _lms_channel_identity(original):
            raise LmsError("The edited sequence changed its channels; only effects can change")
    duration = document.total_centiseconds
    problems: list[str] = []
    for channel in document.root.iterfind("channels/channel"):
        last_end = 0
        spans = sorted((int(e.get("startCentisecond", "0")), int(e.get("endCentisecond", "0")))
                       for e in channel.findall("effect"))
        for start, end in spans:
            if end <= start or end > duration:
                problems.append(f"{channel.get('name')}: an effect is outside the song")
            elif start < last_end:
                problems.append(f"{channel.get('name')}: effects overlap")
            last_end = max(last_end, end)
    if problems:
        raise LmsError("The edited sequence has timing problems: " + "; ".join(problems[:10]))
    return {"ok": True, "channels": len(document.channels),
            "effects": sum(c.effect_count for c in document.channels)}


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


# Song analysis and show building use a lot of memory; at most two run at once and
# the rest wait their turn (and say so) instead of running the computer out of memory.
HEAVY_AT_ONCE = 2
_HEAVY_STEPS = {"/api/analyze", "/api/show/audio", "/api/show/generate", "/api/show/batch",
                "/api/show/batch-zip", "/api/show/test", "/api/demo"}
_heavy = threading.BoundedSemaphore(HEAVY_AT_ONCE)


@contextmanager
def _heavy_turn(path: str) -> Iterator[None]:
    if path not in _HEAVY_STEPS:
        yield
        return
    if not _heavy.acquire(blocking=False):
        progress.step("Waiting for another song to finish first")
        _heavy.acquire()
    try:
        yield
    finally:
        _heavy.release()


_RECENT = {"/api/recent", "/api/recent/open", "/api/recent/remove", "/api/recent/clear"}
# Learning a style from the user's own sequences: measure one file, keep a style from
# the measurements, list or remove kept styles. Nothing is sent anywhere.
_STYLES = {"/api/style/measure", "/api/style/keep", "/api/style/list", "/api/style/remove"}
# A preview the program was started with (right-click "Build a show", or --preview),
# handed to the page once so New show opens with it.
_startup_lock = threading.Lock()
_startup: dict[str, Any] = {}


def offer_preview(path: str | Path) -> str:
    """Remember a preview to open in New show; returns the address suffix that asks the
    page for it. Raises ValueError with plain words when the file cannot be used."""
    source = Path(path)
    if source.suffix.lower() != ".lorprev" or not source.is_file():
        raise ValueError(f"{source.name} is not an S5/S6 preview (.lorprev) file")
    if source.stat().st_size > MAX_LORPREV_BYTES:
        raise ValueError(f"{source.name} is larger than a preview can be")
    data = source.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source.name} is not a readable S5/S6 preview") from exc
    with _startup_lock:
        _startup.clear()
        _startup.update(name=source.name, text=text)
    return "?start=preview"


def _take_startup() -> dict[str, Any]:
    with _startup_lock:
        found = dict(_startup)
        _startup.clear()
    return {"preview": found or None}


_NOT_AUDIO = ("That file does not look like a song this program can read. Use an MP3, M4A, "
              "WAV, FLAC or OGG file.")
_PLAIN_ERRORS = {
    400: "The program sent itself a request it could not understand. Reload the page and try "
         "again.",
    403: "Only this program's own window can use its engine.",
    404: "This program has no such step.",
    413: "That file is too large for the program.",
    415: "That kind of file cannot be used here.",
}


class SequencerRequestHandler(SimpleHTTPRequestHandler):
    """Serve only packaged UI assets and accept bounded audio uploads for local analysis."""

    server_version = "LORSequencer/" + __version__

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(_WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def send_error(self, code: int, message: str | None = None,
                   explain: str | None = None) -> None:
        """API refusals answer in JSON with plain words the page can show; files keep the
        standard error page."""
        if not urlsplit(self.path).path.startswith("/api/"):
            super().send_error(code, message, explain)
            return
        self._send_json(code, {"error": message or _PLAIN_ERRORS.get(
            code, "The program could not do that step.")})

    def do_POST(self) -> None:
        """Analyze audio, check an edited sequence, or build a new show; never drop the
        connection on a bug, so the page can say what happened."""
        self._body_read = False
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page went away; nothing to answer
        except Exception as error:  # noqa: BLE001 - every bug gets a logged, plain answer
            from lor_sequence_builder.diagnostics import log_unexpected, unexpected_message

            reference = log_unexpected(error, urlsplit(self.path).path)
            try:
                self._send_json(500, {"error": unexpected_message(reference),
                                      "reference": reference})
            except OSError:
                pass
        finally:
            self._drain_body()

    def _drain_body(self) -> None:
        """Read whatever the page sent that the answer did not need. Closing with it
        still unread makes the operating system reset the connection, and the page
        would see "connection reset" instead of the answer it was just sent."""
        if getattr(self, "_body_read", True):
            return
        self._body_read = True
        try:
            remaining = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if remaining > _MAX_UPLOAD_BYTES:
            self.close_connection = True
            return
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    def _post(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path not in {"/api/analyze", "/api/export", "/api/update", "/api/log",
                               "/api/diagnostics", "/api/progress", "/api/startup",
                               "/api/demo", *_RECENT, *_STYLES, *_SHOW_STEPS}:
            self.send_error(404, "This program has no such step.")
            return
        if not self._is_same_origin():
            return
        if parsed.path == "/api/progress":
            key = parse_qs(parsed.query).get("key", [""])[0]
            self._send_json(200, progress.snapshot(key) if progress.valid_key(key)
                            else {"known": False})
            return
        if parsed.path in {"/api/log", "/api/diagnostics"}:
            self._diagnostics(parsed.path)
            return
        if parsed.path == "/api/update":
            from lor_sequence_builder.update_check import check_for_update

            self._send_json(200, check_for_update())
            return
        if parsed.path in _RECENT:
            self._recent(parsed.path)
            return
        if parsed.path in _STYLES:
            self._style(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path == "/api/startup":
            self._send_json(200, _take_startup())
            return
        if parsed.path == "/api/export":
            self._check_export()
            return
        tracked = parse_qs(parsed.query).get("progress", [""])[0] or None
        with progress.tracking(tracked), _heavy_turn(parsed.path):
            if parsed.path == "/api/demo":
                from lor_sequence_builder.demo import demo_payload

                progress.step("Building a show for the demo yard", 0.1)
                self._send_json(200, demo_payload())
                return
            if parsed.path in _SHOW_STEPS:
                self._show_step(parsed.path, parse_qs(parsed.query))
                return
            self._analyze(parsed.query)

    def _recent(self, path: str) -> None:
        body = self._read_json()
        if body is None:
            return
        try:
            if path == "/api/recent":
                self._send_json(200, {"shows": recent_shows.listing()})
            elif path == "/api/recent/open":
                self._send_json(200, recent_shows.load(body.get("id", "")))
            elif path == "/api/recent/remove":
                recent_shows.remove(body.get("id", ""))
                self._send_json(200, {"removed": True})
            else:
                self._send_json(200, {"removed": recent_shows.clear()})
        except recent_shows.RecentShowError as exc:
            self._send_json(404, {"error": str(exc)})
        except OSError as exc:
            self._send_json(500, {"error": friendly(exc)})

    def _style(self, path: str, query: dict[str, list[str]]) -> None:
        from lor_sequence_builder import style_learning
        from lor_sequence_builder.show_builder import all_styles

        try:
            if path == "/api/style/measure":
                name = Path(query.get("name", ["sequence.loredit"])[0][:200]).name
                limit = MAX_LMS_BYTES if name.lower().endswith(".lms") else MAX_LOREDIT_BYTES
                payload = self._read_body("application/octet-stream", limit, "Sequence")
                if payload is None:
                    return
                habits = style_learning.measure_bytes(payload, name)
                self._send_json(200, {"file": name, "habits": habits.to_dict()})
                return
            body = self._read_json()
            if body is None:
                return
            if path == "/api/style/keep":
                measured = body.get("habits")
                style_name = body.get("name")
                if (not isinstance(measured, list) or not measured or len(measured) > 50
                        or not isinstance(style_name, str)):
                    self._send_json(422, {"error": "Measure one to 50 sequences first."})
                    return
                habits = style_learning.combine(
                    [style_learning.Habits.from_dict(h) for h in measured])
                style, changes = style_learning.style_from_habits(habits, style_name)
                style_learning.save(style, habits)
                self._send_json(200, {"style": {**style.to_dict(), "learned": True},
                                      "changes": changes, "styles": all_styles()})
            elif path == "/api/style/remove":
                key = body.get("key")
                if not isinstance(key, str):
                    self._send_json(422, {"error": "Which style?"})
                    return
                style_learning.remove_saved(key)
                self._send_json(200, {"styles": all_styles()})
            else:
                self._send_json(200, {"styles": all_styles()})
        except style_learning.StyleLearningError as exc:
            self._send_json(422, {"error": str(exc)})
        except OSError as exc:
            self._send_json(500, {"error": friendly(exc)})

    def _show_step(self, path: str, query: dict[str, list[str]]) -> None:
        token = query.get("token", [""])[0]
        try:
            if path == "/api/show/start":
                name = query.get("name", ["display.lorprev"])[0][:200]
                limit = MAX_LMS_BYTES if name.lower().endswith(".lms") else MAX_LORPREV_BYTES
                payload = self._read_body("application/xml", limit, "Display")
                if payload is None:
                    return
                self._send_json(200, SHOWS.start(payload, name))
            elif path == "/api/show/batch":
                payload = self._read_body("application/octet-stream", _MAX_UPLOAD_BYTES,
                                          "Audio")
                if payload is None:
                    return
                suffix = _detect_audio_suffix(payload)
                if suffix is None or suffix not in INPUT_DEMUXERS:
                    self.send_error(415, _NOT_AUDIO)
                    return
                meter = query.get("beats_per_bar", ["4"])[0]
                if meter not in {"3", "4"}:
                    self.send_error(400, "beats_per_bar must be 3 or 4")
                    return
                style = query.get("style", [""])[0] or None
                self._send_json(200, SHOWS.batch_song(
                    token, payload, suffix, INPUT_DEMUXERS[suffix],
                    query.get("name", ["song"])[0], int(meter), style))
            elif path == "/api/show/audio":
                payload = self._read_body("application/octet-stream", _MAX_UPLOAD_BYTES,
                                          "Audio")
                if payload is None:
                    return
                suffix = _detect_audio_suffix(payload)
                if suffix is None or suffix not in INPUT_DEMUXERS:
                    self.send_error(415, _NOT_AUDIO)
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
                                         query.get("name", ["song"])[0], int(meter),
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
                    result = SHOWS.batch_zip(token)
                    self._send_download_file(
                        Path(result["zip_path"]), result["zip_name"], "application/zip"
                    )
                elif path == "/api/show/batch-clear":
                    self._send_json(200, SHOWS.batch_clear(token))
                elif path == "/api/show/test":
                    self._send_json(200, SHOWS.display_test(token))
                else:
                    self._send_json(200, SHOWS.generate(token, body))
        except (ShowBuildError, AudioAnalysisError, ValueError, RuntimeError) as exc:
            self._send_json(422, {"error": str(exc)})
        except (OSError, MemoryError) as exc:
            self._send_json(500, {"error": friendly(exc)})

    def _read_json(self) -> dict[str, Any] | None:
        payload = self._read_body("application/json", _MAX_JSON_BYTES, "Request")
        if payload is None:
            return None
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            self.send_error(400, "Expected a JSON object")
            return None
        if not isinstance(body, dict):
            self.send_error(400, "Expected a JSON object")
            return None
        return body

    def _hosts(self) -> set[str]:
        """The two names this computer's own window can use for the workspace."""
        port = str(cast(ThreadingHTTPServer, self.server).server_port)
        return {"127.0.0.1:" + port, "localhost:" + port}

    def _is_same_origin(self) -> bool:
        """Only the workspace's own page may use the engine: the Host must be this
        computer (no DNS rebinding), and the Origin and Fetch-Site, when the browser
        sends them, must say the request came from the workspace itself."""
        hosts = self._hosts()
        if self.headers.get("Host") not in hosts:
            self.send_error(403, "Requests must use the loopback workspace host")
            return False
        origin = self.headers.get("Origin")
        if origin:
            origin_url = urlsplit(origin)
            # localhost and 127.0.0.1 are both valid workspace entry points,
            # but they are distinct browser origins. Do not let one alias
            # authorize a request whose Host names the other.
            if origin_url.scheme != "http" or origin_url.netloc != self.headers.get("Host"):
                self.send_error(403, "Cross-origin requests are not accepted")
                return False
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in {"same-origin", "none"}:
            self.send_error(403, "Cross-origin requests are not accepted")
            return False
        return True

    def do_GET(self) -> None:
        if self.headers.get("Host") not in self._hosts():
            self.send_error(403, "This workspace only answers its own window")
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.headers.get("Host") not in self._hosts():
            self.send_error(403, "This workspace only answers its own window")
            return
        super().do_HEAD()

    def list_directory(self, path: str | os.PathLike[str]) -> Any:
        """The workspace never lists its folders."""
        self.send_error(404, "Not found")
        return None

    def _read_body(self, content_type: str, limit: int, what: str) -> bytes | None:
        if getattr(self, "_body_read", False):
            raise RuntimeError("The request body was already read")
        if self.headers.get_content_type() != content_type:
            self.send_error(415, "Expected " + content_type)
            return None
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length <= 0:
            self.send_error(400, f"The {what.lower()} file is empty. Choose it again.")
            return None
        if length > limit:
            self.send_error(413, f"That {what.lower()} file is larger than the "
                                 f"{limit // (1024 * 1024)} MB this program accepts.")
            return None
        self._body_read = True
        payload = self.rfile.read(length)
        if len(payload) != length:
            self.send_error(400, f"The {what.lower()} file did not arrive in full. Choose it again.")
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
        except (LoreditError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
            self._send_json(422, {"error": str(exc) or "Invalid sequence export request"})
        except (OSError, MemoryError) as exc:
            self._send_json(500, {"error": "The edited sequence could not be checked. "
                                  + friendly(exc)})

    def _analyze(self, query_text: str) -> None:
        payload = self._read_body("application/octet-stream", _MAX_UPLOAD_BYTES, "Audio")
        if payload is None:
            return

        suffix = _detect_audio_suffix(payload)
        if suffix is None or suffix not in INPUT_DEMUXERS:
            self.send_error(415, _NOT_AUDIO)
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
        except (OSError, MemoryError) as exc:
            self._send_json(500, {"error": "The song could not be analyzed. " + friendly(exc)})

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

    def _send_download_file(self, path: Path, name: str, content_type: str) -> None:
        """Stream a generated file to the client and remove its temporary copy."""
        response_started = False
        try:
            # Open before sending headers so a missing/unreadable file can still
            # produce the route's normal JSON error response.
            with path.open("rb") as source:
                size = os.fstat(source.fileno()).st_size
                fallback = name.encode("ascii", "ignore").decode("ascii").replace('"', "")
                response_started = True
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(name)}',
                )
                self.end_headers()
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        except OSError as exc:
            if not response_started:
                raise
            # Never append a JSON error after a ZIP response has started.
            from lor_sequence_builder.diagnostics import write_log

            write_log("server", f"Batch archive stream ended early: {exc}")
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                from lor_sequence_builder.diagnostics import write_log

                write_log("server", f"Could not remove downloaded batch archive: {exc}")

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
    parser.add_argument("--preview", metavar="LORPREV",
                        help="open New show with this S6 preview already chosen")
    options = parser.parse_args(argv)
    if not 0 <= options.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not _WEB_ROOT.is_dir():
        parser.error("The packaged sequencing workspace assets are missing")

    server = ThreadingHTTPServer(("127.0.0.1", options.port), SequencerRequestHandler)
    from lor_sequence_builder.audio_analysis import warm_up_in_background
    from lor_sequence_builder.diagnostics import sweep_leftovers

    warm_up_in_background()
    threading.Thread(target=sweep_leftovers, name="sweep-leftovers", daemon=True).start()
    server.daemon_threads = True
    address = server.server_address
    url = "http://127.0.0.1:" + str(address[1]) + "/"
    if options.preview:
        try:
            url += offer_preview(options.preview)
        except (OSError, ValueError) as exc:
            print(f"Not opening that preview: {exc}")
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
