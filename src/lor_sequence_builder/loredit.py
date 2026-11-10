"""Diagnostic reader for Light-O-Rama LOREDIT XML files.

This module deliberately inspects the XML structure without claiming to understand
or rewrite undocumented sequence semantics. The native writer will be added only
after the required structure has been verified against S6-created examples.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


class LoreditError(ValueError):
    """Raised when a LOREDIT file cannot be parsed as XML."""


def _local_name(tag: str) -> str:
    """Remove an optional XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


def inspect_loredit(path: str | Path) -> dict[str, Any]:
    """Return a safe structural summary of a LOREDIT XML file."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Sequence file not found: {source}")

    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise LoreditError(f"Invalid XML in {source}: {exc}") from exc
    except OSError as exc:
        raise LoreditError(f"Unable to read {source}: {exc}") from exc

    counts = Counter(_local_name(element.tag) for element in root.iter())
    return {
        "file": str(source),
        "size_bytes": source.stat().st_size,
        "root_element": _local_name(root.tag),
        "root_attributes": dict(root.attrib),
        "element_counts": dict(sorted(counts.items())),
        "top_level_elements": [_local_name(child.tag) for child in root],
    }
