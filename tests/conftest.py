"""Shared test settings."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never ask GitHub for releases; update tests turn the check back on."""
    monkeypatch.setenv("LOR_NO_UPDATE_CHECK", "1")
