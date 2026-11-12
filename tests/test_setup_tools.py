"""Installation check, demo show, example requirements and launchers."""

from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.demo import build_demo, demo_preview
from lor_sequence_builder.doctor import run_checks
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.rules import (
    check_choreography,
    display_from_preview,
    load_rule_set,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples" / "requirements").glob("*.yaml"))


def test_doctor_finds_this_installation_ready(capsys: pytest.CaptureFixture[str]) -> None:
    checks = run_checks()
    assert all(check.ok for check in checks if check.required), checks
    assert {c.name for c in checks} >= {"Python", "Libraries", "Audio decoding",
                                        "Browser workspace", "Data folders"}
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Ready." in out and "OK   Audio decoding" in out


def test_doctor_explains_a_missing_library(monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    import importlib

    real = importlib.import_module

    def broken(name: str, *args: object) -> object:
        if name == "librosa":
            raise ImportError("no librosa")
        return real(name, *args)  # type: ignore[arg-type]

    monkeypatch.setattr("lor_sequence_builder.doctor.importlib.import_module", broken)
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "FIX  Libraries" in out and "uv sync" in out


def test_demo_builds_a_complete_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "demo"
    assert main(["demo", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "Every rule passed." in out
    names = {path.name for path in folder.iterdir()}
    assert {"Demo Yard.lorprev", "Demo Song.wav", "Demo Song.loredit",
            "Demo Song.report.html", "Demo Song.plan.svg"} <= names
    # A second run into the same folder refuses instead of overwriting.
    assert main(["demo", str(folder)]) == 2


def test_the_demo_yard_has_every_kind_of_motion() -> None:
    display = display_from_preview(demo_preview())
    roles = {p.role for p in display.props.values()}
    assert {"arch", "mini_tree", "mega_tree", "snowflake", "star", "outline"} <= roles


@pytest.mark.parametrize("profile", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_requirements_load_and_shape_the_demo(profile: Path, tmp_path: Path) -> None:
    rules = load_rule_set((profile,))
    assert rules.requirements
    show = build_demo(tmp_path / "base")
    preview = tmp_path / "base" / "Demo Yard.lorprev"
    shaped = generate_show(preview, tmp_path / "shaped.loredit", rules,
                           analysis_path=show.analysis_path, separate=False)
    assert check_choreography(demo_preview(), shaped.plan.choreography, rules).ok
    assert shaped.plan.choreography != show.plan.choreography


def test_launchers_install_then_start_the_workspace() -> None:
    windows = (ROOT / "Start LOR Sequencer.cmd").read_bytes()
    assert b"\r\n" in windows and b"uv sync --locked" in windows
    assert b"uv run lor-sequence-ui" in windows
    unix = (ROOT / "start-lor-sequencer.sh").read_text(encoding="utf-8")
    assert unix.startswith("#!/usr/bin/env sh") and "uv run lor-sequence-ui" in unix


def test_doctor_says_how_to_get_ffmpeg(monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "FIX  FFmpeg (reads audio)" in out and "install it with" in out
