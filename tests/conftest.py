"""Shared test settings."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never ask GitHub for releases; update tests turn the check back on."""
    monkeypatch.setenv("LOR_NO_UPDATE_CHECK", "1")


@pytest.fixture(autouse=True)
def _private_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The workspace log goes to the test's own folder, never the user's."""
    monkeypatch.setattr("lor_sequence_builder.diagnostics.log_folder", lambda: tmp_path / "logs")
