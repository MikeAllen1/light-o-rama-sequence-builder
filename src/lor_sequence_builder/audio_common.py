"""Shared constants and errors for bounded audio analysis."""

from __future__ import annotations


ANALYSIS_SCHEMA_VERSION = "1.3"
SAMPLE_RATE = 11_025
FRAME_HOP_SAMPLES = round(SAMPLE_RATE * 0.01)
FRAME_WINDOW_SAMPLES = round(SAMPLE_RATE * 0.05)
FRAME_SECONDS = FRAME_HOP_SAMPLES / SAMPLE_RATE
FRAME_WINDOW_SECONDS = FRAME_WINDOW_SAMPLES / SAMPLE_RATE
FRAME_CENTER_SECONDS = FRAME_WINDOW_SECONDS / 2.0
MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_DURATION_SECONDS = 30 * 60
MIN_DURATION_SECONDS = 2.0
MAX_DECODED_SAMPLES = SAMPLE_RATE * MAX_DURATION_SECONDS
MAX_FFMPEG_SECONDS = 300
INPUT_FORMATS = {
    ".aac": "aac",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".flac": "flac",
    ".m4a": "mov",
    ".mp3": "mp3",
    ".mp4": "mov",
    ".ogg": "ogg",
    ".wav": "wav",
    ".wma": "asf",
}
MIN_BPM = 60
MAX_BPM = 200


class AudioAnalysisError(ValueError):
    """Raised when audio cannot be safely analyzed."""
