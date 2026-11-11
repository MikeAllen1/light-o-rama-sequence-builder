"""Build a new native S6 v15 sequence from a display preview alone.

The structure mirrors what S6 6.6.0.12 writes for musical sequences, as
established by comparing native sequences (see docs/S6_FORMAT.md):

- One ``SeqProp`` per preview prop that is not linked to a master prop
  (``MasterPropId`` empty), in preview order. Linked props are driven by their
  master and get no sequence prop of their own.
- One ``channel`` per ``ChannelGrid`` entry. ``Single Color`` and
  ``Multicolor_string_1_ch`` use row 0 and sequential columns;
  ``Channel_per_color`` uses row 0, column 0, and sequential colors.
- A fixed set of top-level sections in a fixed order, and a 0.05 s fixed grid.

Props whose channel layout has not been verified (pixel/RGB, DMX, legacy AC/DC,
unassigned) are excluded and reported, never silently dropped.
"""

from __future__ import annotations

import copy
import hashlib
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from lor_sequence_builder.loredit import LoreditDocument
from lor_sequence_builder.timeline import ExcludedProp

SAVE_FILE_VERSION = "15"
DEFAULT_APP_VERSION = "6.6.0.12"
MAX_SEQUENCE_CENTISECONDS = 30 * 60 * 100
SUPPORTED_DEVICE_TYPES = frozenset({"LOR"})
COLUMN_LAYOUT_TYPES = frozenset({"Single Color", "Multicolor_string_1_ch"})
COLOR_LAYOUT_TYPES = frozenset({"Channel_per_color"})

# Interface defaults observed identically in every native S6 6.6.0.12 sequence
# examined. They control the editor view, not the show.
_EDITOR_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("WaveHeight", "1"),
    ("TimingGridIdx", "0"),
    ("DragEventsWithTimings", "True"),
    ("ChaseClearFirst", "True"),
    ("ChaseSameRowType", "True"),
    ("ChaseType", "0"),
    ("AudioAnalysisLevel", "0"),
)
_VIEW_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("NameAreaWidth", "344"),
    ("ZoomWidth", "15"),
    ("ZoomHeight", "16"),
)
_TRAILING_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("GridView", "Show All Items"),
    ("GridViewSource", "Sequence"),
    ("StartColor", "FFFF0000"),
    ("EndColor", "FF00FF00"),
)


class NewSequenceError(ValueError):
    """Raised when a new sequence cannot be built safely from a preview."""


@dataclass(frozen=True, slots=True)
class FreeTimingGrid:
    """A named free timing grid to include in the new sequence."""

    name: str
    marks_centiseconds: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NewSequence:
    document: LoreditDocument
    excluded_props: tuple[ExcludedProp, ...]


def _channel_count(prop: ET.Element) -> int:
    return len([entry for entry in prop.attrib.get("ChannelGrid", "").split(";") if entry])


def _exclusion_reason(prop: ET.Element) -> str | None:
    device_type = prop.attrib.get("DeviceType", "")
    traditional_type = prop.attrib.get("TraditionalType", "")
    if device_type not in SUPPORTED_DEVICE_TYPES:
        return f"DeviceType {device_type or '(missing)'} has no verified native channel layout"
    if traditional_type not in COLUMN_LAYOUT_TYPES | COLOR_LAYOUT_TYPES:
        return (
            f"TraditionalType {traditional_type or '(missing)'} has no verified native "
            "channel layout"
        )
    if _channel_count(prop) == 0:
        return "ChannelGrid has no controller assignments"
    return None


def _sequence_id(preview: ET.Element, total_centiseconds: int, music_filename: str) -> str:
    digest = hashlib.sha256()
    digest.update(ET.tostring(preview, encoding="utf-8"))
    digest.update(f"|{total_centiseconds}|{music_filename}".encode())
    # UUIDv5 accurately describes this deterministic, name-derived identifier.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, digest.hexdigest()))


def build_new_sequence(
    preview: ET.Element,
    total_centiseconds: int,
    music_filename: str,
    timing_grids: tuple[FreeTimingGrid, ...] = (),
    app_version: str = DEFAULT_APP_VERSION,
) -> NewSequence:
    """Return a new native sequence document for ``preview`` with no effects."""
    if preview.tag != "PreviewClass":
        raise NewSequenceError("Preview root element must be <PreviewClass>")
    if (
        not isinstance(total_centiseconds, int)
        or isinstance(total_centiseconds, bool)
        or not 1 <= total_centiseconds <= MAX_SEQUENCE_CENTISECONDS
    ):
        raise NewSequenceError("Sequence duration must be from 1 centisecond to 30 minutes")
    if not isinstance(music_filename, str) or not music_filename.strip():
        raise NewSequenceError("A musical sequence needs an audio file name")
    if any(ord(character) < 32 for character in music_filename):
        raise NewSequenceError("Audio file name contains control characters")
    # S6 resolves this value beneath its configured audio folder. Reject
    # absolute, drive-qualified, UNC, and parent-traversal paths on every OS.
    windows_path = PureWindowsPath(music_filename)
    posix_path = PurePosixPath(music_filename.replace("\\", "/"))
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(part == ".." for part in (*windows_path.parts, *posix_path.parts))
    ):
        raise NewSequenceError("Audio file name must be a relative path inside the S6 audio folder")
    if len(music_filename) > 240:
        raise NewSequenceError("Audio file name is too long")

    props = preview.findall("PropClass")
    if not props:
        raise NewSequenceError("Preview contains zero PropClass entries")
    prop_ids = [prop.attrib.get("id", "") for prop in props]
    if any(not prop_id for prop_id in prop_ids) or len(set(prop_ids)) != len(prop_ids):
        raise NewSequenceError("Preview contains missing or duplicate prop identities")

    attributes: dict[str, str] = {
        "saveFileVersion": SAVE_FILE_VERSION,
        "AppVersion": app_version,
        "id": _sequence_id(preview, total_centiseconds, music_filename),
        "totalCentiseconds": str(total_centiseconds),
    }
    attributes.update(_EDITOR_DEFAULTS)
    attributes.update(_VIEW_DEFAULTS)
    attributes["musicFilename"] = music_filename
    attributes.update(_TRAILING_DEFAULTS)
    root = ET.Element("sequence", attributes)

    root.append(copy.deepcopy(preview))
    ET.SubElement(root, "BeatChannels", {"MaxDisplayedRows": "10"})
    ET.SubElement(root, "Subsequences")

    sequence_props = ET.SubElement(root, "SequenceProps")
    excluded: list[ExcludedProp] = []
    for prop in props:
        if prop.attrib.get("MasterPropId"):
            continue
        prop_id = prop.attrib["id"]
        name = prop.attrib.get("Name", "")
        reason = _exclusion_reason(prop)
        if reason is not None:
            excluded.append(ExcludedProp(prop_id=prop_id, name=name, reason=reason))
            continue
        sequence_prop = ET.SubElement(
            sequence_props,
            "SeqProp",
            {"id": prop_id, "name": name, "EnablePixelChannels": "0", "OverlayMotionRows": "0"},
        )
        per_color = prop.attrib.get("TraditionalType") in COLOR_LAYOUT_TYPES
        for index in range(_channel_count(prop)):
            ET.SubElement(
                sequence_prop,
                "channel",
                {
                    "row": "0",
                    "col": "0" if per_color else str(index),
                    "color": str(index) if per_color else "0",
                },
            )
    if not sequence_props.findall("SeqProp"):
        raise NewSequenceError("No preview prop has a verified native channel layout")

    ET.SubElement(root, "ArchivedProps")
    ET.SubElement(root, "RgbAggregates")
    grids = ET.SubElement(root, "TimingGrids")
    ET.SubElement(grids, "TimingGridFixed", {"name": "Fixed Grid: 0.05", "spacing": "5"})
    seen_names: set[str] = set()
    for grid in timing_grids:
        if not grid.name.strip() or grid.name in seen_names:
            raise NewSequenceError(f"Timing grid names must be unique and non-empty: {grid.name!r}")
        seen_names.add(grid.name)
        marks = sorted(set(grid.marks_centiseconds))
        if marks and (marks[0] < 0 or marks[-1] > total_centiseconds):
            raise NewSequenceError(f"Timing grid {grid.name!r} has marks outside the sequence")
        free = ET.SubElement(grids, "TimingGridFree", {"name": grid.name})
        for mark in marks:
            ET.SubElement(free, "timing", {"centisecond": str(mark)})
    ET.SubElement(root, "BeatView")
    ET.SubElement(root, "PropViews")
    ET.SubElement(root, "MotionPaks")
    ET.SubElement(root, "pictures")

    return NewSequence(document=LoreditDocument(root=root), excluded_props=tuple(excluded))
