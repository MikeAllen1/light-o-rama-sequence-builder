"""Timed lyrics: imported from a lyrics file, or transcribed offline and unverified.

Vocal timing from loudness alone is not reliable enough to show words, so lyrics
come from text, never from guessing:

- Import: LRC (``[mm:ss.xx] line``), SRT or WebVTT files the user already has.
  The text is the user's; line times come from the file.
- Transcribe: an optional offline speech-recognition add-on
  (``uv sync --extra lyrics``, faster-whisper) listens to the song or, better,
  to a vocals-only track, and returns lines with per-word timestamps. Every
  transcribed line and word is marked ``verified: false``: recognizers mishear
  sung words, so nothing is presented as confirmed until a person reviews it.

The result is a ``lyrics-1.0`` JSON document that the browser workspace shows
as a lyric track aligned with the waveform. Audio never leaves the computer.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from lor_sequence_builder.artifacts import write_new_text_atomically

LYRICS_SCHEMA_VERSION = "lyrics-1.0"
DEFAULT_MODEL = "base.en"
MAX_LYRICS_BYTES = 2 * 1024 * 1024
MAX_LINES = 5000
WHISPER_RATE = 16_000

_LRC = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\]")
_CUE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})"
)


class LyricsError(ValueError):
    """Raised when lyrics cannot be read, transcribed or written."""


def transcription_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _seconds(hours: str | None, minutes: str, secs: str, fraction: str) -> float:
    return (int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
            + int(fraction.ljust(3, "0")[:3]) / 1000)


def _document(lines: list[dict[str, Any]], source: str, origin: str,
              verified: bool, **extra: Any) -> dict[str, Any]:
    lines = sorted(lines, key=lambda line: line["start"])
    for index, line in enumerate(lines):
        if line.get("end") is None:
            following = lines[index + 1]["start"] if index + 1 < len(lines) else None
            line["end"] = following if following is not None else line["start"] + 4.0
        line["verified"] = verified
        line.setdefault("words", [])
    return {
        "schema_version": LYRICS_SCHEMA_VERSION,
        "source": source,
        "origin": origin,
        "lines": [line for line in lines if line["end"] > line["start"] and line["text"]],
        **extra,
    }


def parse_lyrics_text(text: str, name: str) -> dict[str, Any]:
    """Parse LRC, SRT or VTT text into a lyrics-1.0 document."""
    lines: list[dict[str, Any]] = []
    if _LRC.search(text):
        for raw in text.splitlines():
            stamps = _LRC.findall(raw)
            words = _LRC.sub("", raw).strip()
            for minutes, secs in stamps:
                if words:
                    lines.append({"start": int(minutes) * 60 + float(secs), "end": None,
                                  "text": words})
        origin = "lrc"
    elif _CUE.search(text):
        for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
            match = _CUE.search(block)
            if not match:
                continue
            g = match.groups()
            after = block[match.end():].strip().splitlines()
            words = " ".join(re.sub(r"<[^>]+>", "", line).strip() for line in after).strip()
            if words:
                lines.append({"start": _seconds(g[0], g[1], g[2], g[3]),
                              "end": _seconds(g[4], g[5], g[6], g[7]), "text": words})
        origin = "vtt" if text.lstrip().startswith("WEBVTT") else "srt"
    else:
        raise LyricsError(f"{name}: no LRC time tags or SRT/VTT cues found")
    if not lines:
        raise LyricsError(f"{name}: no timed lyric lines found")
    if len(lines) > MAX_LINES:
        raise LyricsError(f"{name}: more than {MAX_LINES} lyric lines")
    # Imported text is the user's own; its timing comes from the file.
    return _document(lines, "imported", origin, verified=True, file_name=name)


def import_lyrics(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_LYRICS_BYTES:
            raise LyricsError(f"{source.name}: lyrics file exceeds 2 MiB")
        text = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise LyricsError(f"Cannot read lyrics file: {source}") from exc
    return parse_lyrics_text(text, source.name)


def read_lyrics(path: str | Path) -> dict[str, Any]:
    """A lyrics file for planning: LRC, SRT or VTT, or a lyrics JSON this program wrote."""
    source = Path(path)
    if source.suffix.lower() != ".json":
        return import_lyrics(source)
    try:
        if source.stat().st_size > MAX_LYRICS_BYTES:
            raise LyricsError(f"{source.name}: lyrics file exceeds 2 MiB")
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LyricsError(f"Cannot read lyrics file: {source}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != LYRICS_SCHEMA_VERSION \
            or not isinstance(data.get("lines"), list):
        raise LyricsError(f"{source.name} is not a lyrics file from this program")
    return data


def lines_from_segments(segments: Any) -> list[dict[str, Any]]:
    """Turn recognizer segments (with word timings) into lyric lines."""
    lines = []
    for segment in segments:
        words = [
            {"start": round(float(w.start), 3), "end": round(float(w.end), 3),
             "text": str(w.word).strip(), "confidence": round(float(w.probability), 3),
             "verified": False}
            for w in (segment.words or []) if str(w.word).strip()
        ]
        text = str(segment.text).strip()
        if text:
            lines.append({"start": round(float(segment.start), 3),
                          "end": round(float(segment.end), 3), "text": text, "words": words})
    return lines


def transcribe_lyrics(audio_path: str | Path, model_name: str = DEFAULT_MODEL,
                      model: Any = None) -> dict[str, Any]:
    """Transcribe sung lyrics offline. ``model`` may be supplied (tests, reuse)."""
    from lor_sequence_builder.audio_analysis import SAMPLE_RATE, decode_audio
    from lor_sequence_builder.vocal_separation import model_folder

    if model is None:
        if not transcription_available():
            raise LyricsError("Lyric transcription is an optional add-on; install it with "
                              "'uv sync --extra lyrics', or import an LRC/SRT/VTT file")
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             download_root=str(model_folder()))
    import librosa
    import numpy as np

    samples, _ = decode_audio(audio_path)
    audio = np.asarray(librosa.resample(samples, orig_sr=SAMPLE_RATE, target_sr=WHISPER_RATE),
                       dtype=np.float32)
    segments, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                   condition_on_previous_text=False)
    return _document(
        lines_from_segments(segments), "transcribed", "faster-whisper", verified=False,
        model=model_name, file_name=Path(audio_path).name,
        limitations=[("Speech recognition mishears sung words; every line and word is "
                     "unverified until reviewed."),
                     "Timing is best on a vocals-only track."],
    )


def write_lyrics(document: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    if path.exists():
        raise LyricsError(f"Refusing to overwrite existing lyrics: {path}")
    try:
        write_new_text_atomically(
            path, json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError as exc:
        raise LyricsError(f"Cannot write lyrics: {path}") from exc
    return path
