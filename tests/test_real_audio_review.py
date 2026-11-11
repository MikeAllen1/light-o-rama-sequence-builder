from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_real_audio_review


def test_real_audio_harness_uses_locked_console_entry_point_and_reads_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "track.mp3"
    output_dir = tmp_path / "output"
    audio.write_bytes(b"audio")
    output_dir.mkdir()

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        assert command[1:5] == ["run", "--locked", "--no-sync", "lor-sequence-builder"]
        json_path = Path(command[command.index("--output-json") + 1])
        svg_path = Path(command[command.index("--plot") + 1])
        report = {
            "schema_version": "1.3",
            "audio": {"duration_seconds": 12.5, "sha256": "a" * 64},
            "tool_versions": {"ffmpeg": "test-ffmpeg", "python": "3.12"},
            "analysis": {
                "tempo": {"bpm": 120.0, "confidence": 0.8, "candidates": []},
                "beat_grid_status": "provisional",
                "beats": [{}, {}],
                "onsets": [{}],
                "section_candidates": [],
                "hard_stops": [],
            },
        }
        json_path.write_text(json.dumps(report), encoding="utf-8")
        svg_path.write_text("<svg/>", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="analysis complete", stderr="")

    monkeypatch.setattr(run_real_audio_review.subprocess, "run", fake_run)

    result = run_real_audio_review._run_track("uv", audio, output_dir, 1)

    assert result["status"] == "ok"
    assert result["bpm"] == 120.0
    assert result["beat_grid_status"] == "provisional"
    assert result["beat_count"] == 2
    assert result["sha256"] == "a" * 64


def test_real_audio_harness_records_cli_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "track.mp3"
    output_dir = tmp_path / "output"
    audio.write_bytes(b"audio")
    output_dir.mkdir()

    monkeypatch.setattr(
        run_real_audio_review.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="unsupported audio"
        ),
    )

    result = run_real_audio_review._run_track("uv", audio, output_dir, 1)

    assert result["status"] == "cli_failed"
    assert result["exit_code"] == 2
    assert result["stderr"] == "unsupported audio"


def test_real_audio_harness_records_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "track.mp3"
    output_dir = tmp_path / "output"
    audio.write_bytes(b"audio")
    output_dir.mkdir()

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("uv", 360)

    monkeypatch.setattr(run_real_audio_review.subprocess, "run", timeout)

    result = run_real_audio_review._run_track("uv", audio, output_dir, 1)

    assert result["status"] == "cli_execution_error"
    assert "timed out" in result["error"].lower()


def test_real_audio_harness_tracks_the_ten_review_inputs() -> None:
    assert len(run_real_audio_review.TRACKS) == 10
    assert len(set(run_real_audio_review.TRACKS)) == 10
