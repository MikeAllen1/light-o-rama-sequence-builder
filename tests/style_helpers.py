"""Styles for tests about how the leads move, without the glow underneath them."""

from __future__ import annotations

import dataclasses

from lor_sequence_builder.style import Style, get_style


def leads_only(key: str | None = None) -> Style:
    """A built-in style with its glow turned off, so a test sees only the leads."""
    return dataclasses.replace(get_style(key), glow=(None, None, None))
