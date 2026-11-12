"""Check that this computer can run the sequence builder, and say how to fix what is not.

``lor-sequence-builder doctor`` runs quick checks and prints one line each:

- the Python version;
- the required libraries load;
- FFmpeg, which reads the songs, is installed;
- audio can actually be decoded and analyzed (a one-second tone, made here);
- the browser workspace's files are installed;
- the folders it writes to (model cache, remembered requirements) are writable;
- the optional add-ons: vocal separation for singing faces, lyric transcription,
  and a translator for plain-English requirements.

Nothing is sent anywhere. Required checks that fail make the command exit with 1.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    ok = sys.version_info >= (3, 12)
    return Check("Python", ok, version if ok else
                 f"{version}; Python 3.12 or newer is needed (uv installs it: uv sync)")


def _libraries() -> Check:
    missing = []
    for module in ("numpy", "librosa", "defusedxml", "yaml", "soundfile"):
        try:
            importlib.import_module(module)
        except Exception:  # noqa: BLE001 - an import can fail in many ways on a broken install
            missing.append(module)
    if missing:
        return Check("Libraries", False, "missing " + ", ".join(missing)
                     + "; run 'uv sync' in the project folder")
    return Check("Libraries", True, "numpy, librosa, defusedxml, PyYAML, soundfile")


def ffmpeg_install_hint() -> str:
    if sys.platform.startswith("win"):
        return "install it with: winget install --id Gyan.FFmpeg -e (then open a new window)"
    if sys.platform == "darwin":
        return "install it with: brew install ffmpeg"
    return "install it with your package manager, for example: sudo apt install ffmpeg"


def _ffmpeg() -> Check:
    import shutil
    import subprocess

    path = shutil.which("ffmpeg")
    if path is None:
        return Check("FFmpeg (reads audio)", False, "not found; " + ffmpeg_install_hint())
    try:
        result = subprocess.run([path, "-version"], check=False, capture_output=True,
                                text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("FFmpeg (reads audio)", False, f"found but will not run ({exc}); "
                     + ffmpeg_install_hint())
    first = (result.stdout.splitlines() or ["ffmpeg"])[0]
    return Check("FFmpeg (reads audio)", result.returncode == 0, first[:60])


def _audio() -> Check:
    import numpy as np

    from lor_sequence_builder.audio_analysis import decode_audio

    with tempfile.TemporaryDirectory(prefix="lor-doctor-") as folder:
        path = Path(folder) / "tone.wav"
        rate = 22_050
        t = np.arange(3 * rate) / rate
        data = (0.4 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes(data.tobytes())
        try:
            samples, _ = decode_audio(path)
        except Exception as exc:  # noqa: BLE001 - report any decoder failure in plain words
            return Check("Audio decoding", False, f"could not decode a test tone: {exc}")
    return Check("Audio decoding", samples.size > 0, "WAV, and MP3/M4A through the "
                 "installed decoders" if samples.size else "decoded no samples")


def _workspace() -> Check:
    web = Path(__file__).resolve().parent / "web"
    missing = [name for name in ("index.html", "app.js", "app.css") if not (web / name).is_file()]
    if missing:
        return Check("Browser workspace", False, "files missing: " + ", ".join(missing)
                     + "; reinstall the package")
    return Check("Browser workspace", True, "start it with: lor-sequence-ui")


def _folders() -> Check:
    from lor_sequence_builder.show_builder import requirements_folder
    from lor_sequence_builder.vocal_separation import model_folder

    problems = []
    for folder in (model_folder(), requirements_folder()):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".doctor-"):
                pass
        except OSError as exc:
            problems.append(f"{folder} ({exc.strerror or exc})")
    if problems:
        return Check("Data folders", False, "cannot write to " + "; ".join(problems))
    return Check("Data folders", True, str(model_folder().parent))


def _optional(name: str, module: str, available: str, missing: str) -> Check:
    found = importlib.util.find_spec(module) is not None
    return Check(name, found, available if found else missing, required=False)


def run_checks() -> list[Check]:
    checks: list[Check] = []
    steps: list[Callable[[], Check]] = [_python, _libraries, _ffmpeg, _audio, _workspace,
                                        _folders]
    for step in steps:
        try:
            checks.append(step())
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide the others
            checks.append(Check(step.__name__.strip("_").title(), False, str(exc)))
    checks.append(_optional(
        "Singing faces (vocals add-on)", "audio_separator", "installed",
        "not installed; faces stay still unless you add 'uv sync --extra vocals'"))
    checks.append(_optional(
        "Lyric transcription add-on", "faster_whisper", "installed",
        "not installed; LRC/SRT/VTT lyric files still work ('uv sync --extra lyrics' adds it)"))
    translator = bool(os.environ.get("ANTHROPIC_API_KEY"))
    checks.append(Check("Plain-English requirements", translator,
                        "translator configured" if translator else
                        "not configured; the guided questions and the form still work "
                        "(set ANTHROPIC_API_KEY to type requirements in your own words)",
                        required=False))
    return checks


def print_checks(checks: list[Check]) -> int:
    width = max(len(check.name) for check in checks)
    for check in checks:
        mark = "OK  " if check.ok else ("FIX " if check.required else "--  ")
        print(f"{mark} {check.name.ljust(width)}  {check.detail}")
    failed = [check for check in checks if check.required and not check.ok]
    print()
    if failed:
        print(f"{len(failed)} required check(s) need fixing before the builder can run.")
        return 1
    print("Ready. Try 'lor-sequence-builder demo <folder>' or start the workspace with "
          "'lor-sequence-ui'.")
    return 0
