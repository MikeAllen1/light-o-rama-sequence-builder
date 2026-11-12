"""The desktop app: its self-test, bundled FFmpeg, window fallback and packaging files."""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

import pytest

from lor_sequence_builder import desktop

ROOT = Path(__file__).resolve().parents[1]


def test_the_self_test_checks_a_whole_show(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    assert desktop.main(["--self-test", str(result)]) == 0
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert [s["name"] for s in report["steps"]] == [
        "Bundled FFmpeg", "Workspace served", "Doctor", "Demo show"]


def test_a_failing_self_test_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(folder: Path) -> None:
        raise RuntimeError("no room on the disk")

    monkeypatch.setattr("lor_sequence_builder.demo.build_demo", broken)
    result = tmp_path / "result.json"
    assert desktop.main(["--self-test", str(result)]) == 1
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["ok"] is False and "no room on the disk" in report["steps"][-1]["detail"]


def test_the_bundled_ffmpeg_comes_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "ffmpeg"
    folder.mkdir()
    (folder / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")).write_bytes(b"")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    assert desktop.use_bundled_ffmpeg() == folder
    assert os.environ["PATH"].split(os.pathsep)[0] == str(folder)


def test_without_a_native_window_it_opens_the_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(desktop, "_open_window", lambda url: False)
    monkeypatch.setattr("webbrowser.open", opened.append)

    def stop(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop)
    assert desktop.main([]) == 0
    assert opened and opened[0].startswith("http://127.0.0.1:")


def test_a_windowed_app_never_loses_its_log_lines(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    desktop._ensure_streams()
    print("written to the log")
    sys.stderr.flush()
    log = tmp_path / "lor-sequence-builder" / "logs" / "desktop.log"
    assert "written to the log" in log.read_text(encoding="utf-8")


def test_the_packaging_files_fit_together() -> None:
    spec = (ROOT / "packaging" / "lor_sequencer.spec").read_text(encoding="utf-8")
    assert "launch.py" in spec and "LOR_FFMPEG_DIR" in spec and '"web/*"' in spec
    assert (ROOT / "packaging" / "launch.py").is_file()
    installer = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in installer and "LOR Sequencer.exe" in installer
    # A new installer replaces an existing install: the app is closed and old files cleared.
    assert "CloseApplications=force" in installer and '{app}\\_internal' in installer
    icon = (ROOT / "packaging" / "windows" / "lor-sequencer.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", icon[:6])
    assert (reserved, kind) == (0, 1) and count == 4
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    assert "--self-test" in workflow and "FFMPEG_SHA256" in workflow
