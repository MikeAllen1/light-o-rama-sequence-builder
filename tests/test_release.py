"""The version agrees everywhere, and the release helper bumps it in every place."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_release",
                                                  ROOT / "scripts" / "prepare_release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_file_has_the_same_version() -> None:
    from lor_sequence_builder import __version__

    found = _helper().current_versions()
    assert set(found.values()) == {__version__}, found


def test_this_version_has_release_notes() -> None:
    from lor_sequence_builder import __version__

    notes = ROOT / "docs" / "releases" / f"v{__version__}.md"
    assert notes.is_file() and "Free to use, not to sell." in notes.read_text(encoding="utf-8")


def test_bumping_changes_every_file_and_refuses_going_back(tmp_path: Path) -> None:
    helper = _helper()
    for name in helper.VERSIONED:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, tmp_path / name)
    helper.bump("9.8.7", tmp_path)
    assert set(helper.current_versions(tmp_path).values()) == {"9.8.7"}
    assert "version = \"9.8.7\"" in (tmp_path / "uv.lock").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        helper.bump("9.8.6", tmp_path)
    with pytest.raises(SystemExit):
        helper.bump("v10", tmp_path)


def test_notes_list_the_merged_pull_requests() -> None:
    text = _helper().notes("0.2.0", ["Add batch (#73)", "Add diagnostics (#72)"])
    assert text.index("Add diagnostics (#72)") < text.index("Add batch (#73)")
    # The notes start with how to install, for people who have never used GitHub.
    assert text.index("How to install") < text.index("What's new")
    assert "releases/latest/download/LOR-Sequencer-Setup.exe" in text
    assert "Source code" in text and "Run anyway" in text
