"""Shared test settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# On Windows, Playwright finds its browsers under %LOCALAPPDATA%. Tests point
# LOCALAPPDATA at a temporary folder to keep remembered settings private, so pin
# the browsers' location first, while it still names the real folder.
if os.name == "nt" and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and os.environ.get(
        "LOCALAPPDATA"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(os.environ["LOCALAPPDATA"])
                                                 / "ms-playwright")


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never ask GitHub for releases; update tests turn the check back on."""
    monkeypatch.setenv("LOR_NO_UPDATE_CHECK", "1")


@pytest.fixture(autouse=True)
def _private_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The workspace log goes to the test's own folder, never the user's."""
    monkeypatch.setattr("lor_sequence_builder.diagnostics.log_folder", lambda: tmp_path / "logs")


@pytest.fixture(autouse=True)
def _private_recent_shows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Recent shows go to the test's own folder, never the user's."""
    monkeypatch.setattr("lor_sequence_builder.recent_shows.recent_folder",
                        lambda: tmp_path / "recent-shows")



@pytest.fixture(autouse=True)
def _private_last_display(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The remembered display goes to the test's own folder, never the user's."""
    monkeypatch.setattr("lor_sequence_builder.last_display.last_folder",
                        lambda: tmp_path / "last-display")
