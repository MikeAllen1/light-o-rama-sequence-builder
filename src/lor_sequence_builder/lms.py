"""Light-O-Rama S4 musical sequences (``.lms``, saveFileVersion 14).

S4 has no display preview: a sequence is a flat list of channels, each carrying its
own controller address (``unit``/``circuit``, and ``network`` when it is not the
Regular network), plus channel groups, tracks and timing grids. This module

* reads an ``.lms`` safely (bounded size, depth and element count; no DTDs or
  entities) and validates its channel and group identities,
* turns the user's own ``.lms`` into an equivalent display preview, one prop per
  LOR channel, so the classifier, planner and rules run unchanged, and
* writes a generated show back as a new ``.lms``, using the user's ``.lms`` as the
  template: every channel, group and track is kept exactly, and only the effects
  and the song-specific timings are replaced.

Controller addresses are copied verbatim from the source file in both directions;
nothing is renumbered, reassigned or invented.
"""

from __future__ import annotations

import copy
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from lor_sequence_builder.artifacts import write_new_bytes_atomically

SUPPORTED_LMS_SAVE_FILE_VERSIONS = frozenset({"14"})
MAX_LMS_BYTES = 50 * 1024 * 1024
MAX_LMS_DEPTH = 64
MAX_LMS_ELEMENTS = 2_000_000
MAX_LMS_CHANNELS = 20_000

# S4 effect types and the choreography kinds that write them.
_EFFECT_TYPES = {"on": "intensity", "fade": "intensity", "twinkle": "twinkle",
                 "shimmer": "shimmer"}

_NAMESPACE = uuid.UUID("6f1d2c3e-5a4b-4c7d-9e8f-0a1b2c3d4e5f")

# Named LOR colors, as Windows COLORREF values (0x00BBGGRR).
_COLORS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("Red", (255, 0, 0)), ("Green", (0, 255, 0)), ("Blue", (0, 0, 255)),
    ("White", (255, 255, 255)), ("Yellow", (255, 255, 0)), ("Orange", (255, 128, 0)),
    ("Purple", (128, 0, 192)), ("Pink", (255, 128, 192)), ("Cyan", (0, 255, 255)),
)


class LmsError(ValueError):
    """Raised for an unreadable, unsafe or unsupported S4 sequence."""


@dataclass(frozen=True, slots=True)
class LmsChannel:
    """One S4 channel and its controller address, exactly as the file states it."""

    saved_index: int
    name: str
    color: int | None
    device_type: str | None
    network: str | None
    unit: str | None
    circuit: str | None
    effect_count: int

    @property
    def is_lor(self) -> bool:
        return self.device_type == "LOR" and bool(self.unit) and bool(self.circuit)


@dataclass(frozen=True, slots=True)
class LmsGroup:
    """A channel group; members are savedIndex values of channels or other groups."""

    saved_index: int
    name: str
    members: tuple[int, ...]


@dataclass(slots=True)
class LmsDocument:
    root: ET.Element
    source_path: Path | None
    channels: tuple[LmsChannel, ...]
    groups: tuple[LmsGroup, ...]

    @property
    def save_file_version(self) -> str:
        return self.root.get("saveFileVersion", "")

    @property
    def total_centiseconds(self) -> int:
        values = [int(channel.get("centiseconds", "0") or 0)
                  for channel in self._channels_element().findall("channel")]
        values += [int(track.get("totalCentiseconds", "0") or 0)
                   for track in self.root.iterfind("tracks/track")]
        return max(values, default=0)

    def _channels_element(self) -> ET.Element:
        found = self.root.find("channels")
        if found is None:
            raise LmsError("The .lms has no channels")
        return found


@dataclass(frozen=True, slots=True)
class LmsDisplay:
    """A display preview made from an .lms, and how its props map back to channels."""

    preview: ET.Element
    prop_channels: dict[str, int]
    excluded: tuple[tuple[str, str], ...]


def _int(value: str | None, what: str) -> int:
    try:
        number = int(value or "")
    except ValueError as exc:
        raise LmsError(f"The .lms has an invalid {what}: {value!r}") from exc
    if number < 0:
        raise LmsError(f"The .lms has a negative {what}: {value!r}")
    return number


def _parse(content: bytes, label: str) -> ET.Element:
    try:
        iterator: Any = SafeET.iterparse(
            _BytesSource(content), events=("start", "end"),
            forbid_dtd=True, forbid_entities=True, forbid_external=True,
        )
        depth = 0
        count = 0
        root: ET.Element | None = None
        for event, element in iterator:
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                count += 1
                if depth > MAX_LMS_DEPTH:
                    raise LmsError(f"{label} is nested more deeply than a sequence can be")
                if count > MAX_LMS_ELEMENTS:
                    raise LmsError(f"{label} has more parts than a sequence can have")
            else:
                depth -= 1
    except LmsError:
        raise
    except (ET.ParseError, DefusedXmlException) as exc:
        raise LmsError(f"{label} is not a readable S4 sequence") from exc
    if root is None:
        raise LmsError(f"{label} is empty")
    return root


class _BytesSource:
    """A minimal binary file object for iterparse over bytes already read."""

    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def parse_lms(content: bytes, name: str = "The .lms file",
              source_path: Path | None = None) -> LmsDocument:
    """Validate S4 sequence bytes and return the document."""
    if not content:
        raise LmsError(f"{name} is empty")
    if len(content) > MAX_LMS_BYTES:
        raise LmsError(f"{name} is larger than the {MAX_LMS_BYTES // (1024 * 1024)} MB "
                       "this program accepts")
    root = _parse(content, name)
    if root.tag != "sequence":
        raise LmsError(f"{name} is not a Light-O-Rama sequence")
    version = root.get("saveFileVersion")
    if version not in SUPPORTED_LMS_SAVE_FILE_VERSIONS:
        if root.find("PreviewClass") is not None or root.find("SequenceProps") is not None:
            raise LmsError(f"{name} is an S5/S6 sequence; open it as a .loredit")
        raise LmsError(f"{name} uses saveFileVersion {version!r}; this program reads S4 "
                       "sequences (saveFileVersion 14)")
    container = root.find("channels")
    if container is None:
        raise LmsError(f"{name} has no channels")
    channels: list[LmsChannel] = []
    seen: set[int] = set()
    for element in container.findall("channel"):
        index = _int(element.get("savedIndex"), "channel savedIndex")
        if index in seen:
            raise LmsError(f"{name} has two channels with savedIndex {index}")
        seen.add(index)
        color_text = element.get("color")
        channels.append(LmsChannel(
            saved_index=index,
            name=element.get("name", "") or f"Channel {index}",
            color=_int(color_text, "channel color") if color_text else None,
            device_type=element.get("deviceType"),
            network=element.get("network"),
            unit=element.get("unit"),
            circuit=element.get("circuit"),
            effect_count=len(element.findall("effect")),
        ))
        if len(channels) > MAX_LMS_CHANNELS:
            raise LmsError(f"{name} has more than {MAX_LMS_CHANNELS} channels")
    if not channels:
        raise LmsError(f"{name} has no channels")
    for other in container:
        if other.tag in {"rgbChannel", "cosmicColorDevice"}:
            for member in other.iter("channel"):
                if member is not other and member.get("savedIndex") is not None:
                    _int(member.get("savedIndex"), "RGB member savedIndex")
            device_index = other.get("savedIndex")
            if device_index is not None:
                value = _int(device_index, f"{other.tag} savedIndex")
                if value in seen:
                    raise LmsError(f"{name} reuses savedIndex {value}")
                seen.add(value)

    addresses: dict[tuple[str, str, str], str] = {}
    for channel in channels:
        if channel.is_lor:
            key = (channel.network or "Regular", channel.unit or "", channel.circuit or "")
            if key in addresses:
                raise LmsError(
                    f"{name}: channels {addresses[key]!r} and {channel.name!r} share "
                    f"unit {key[1]} circuit {key[2]}; fix the channel settings in S4 first")
            addresses[key] = channel.name

    groups: list[LmsGroup] = []
    for element in container.findall("channelGroupList"):
        index = _int(element.get("savedIndex"), "group savedIndex")
        if index in seen:
            raise LmsError(f"{name} reuses savedIndex {index}")
        seen.add(index)
        members = tuple(
            _int(member.get("savedIndex"), "group member savedIndex")
            for member in element.iter("channelGroup")
        )
        groups.append(LmsGroup(index, element.get("name", "") or f"Group {index}", members))
    for group in groups:
        missing = [member for member in group.members if member not in seen]
        if missing:
            raise LmsError(f"{name}: group {group.name!r} lists savedIndex {missing[0]}, "
                           "which is not in the file")
    for track in root.iterfind("tracks/track"):
        for ref in track.iterfind("channels/channel"):
            if _int(ref.get("savedIndex"), "track savedIndex") not in seen:
                raise LmsError(f"{name}: a track lists a channel that is not in the file")
    for element in root.iterfind("channels/channel/effect"):
        start = _int(element.get("startCentisecond"), "effect start")
        end = _int(element.get("endCentisecond"), "effect end")
        if end < start:
            raise LmsError(f"{name} has an effect that ends before it starts")
    return LmsDocument(root, source_path, tuple(channels), tuple(groups))


def read_lms(path: str | Path) -> LmsDocument:
    """Read and validate an S4 sequence file."""
    source = Path(path)
    try:
        with source.open("rb") as stream:
            content = stream.read(MAX_LMS_BYTES + 1)
    except OSError as exc:
        raise LmsError(f"Cannot read {source.name}") from exc
    return parse_lms(content, source.name, source)


def color_name(value: int | None) -> str:
    """The nearest named LOR color for a Windows COLORREF channel color."""
    if value is None:
        return "White"
    red, green, blue = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
    return min(_COLORS, key=lambda item: sum(
        (a - b) ** 2 for a, b in zip((red, green, blue), item[1], strict=True)))[0]


def _prop_id(saved_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"channel/{saved_index}"))


def _group_id(saved_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"group/{saved_index}"))


def _layout(root: ET.Element) -> dict[int, tuple[float, float, float, float]]:
    """Each channel's box in preview space from the S4 visualizer grid, if present."""
    animation = root.find("animation")
    if animation is None:
        return {}
    try:
        rows = max(1, int(animation.get("rows", "0")))
        columns = max(1, int(animation.get("columns", "0")))
    except ValueError:
        return {}
    cells: dict[int, list[tuple[int, int]]] = {}
    for row in animation.findall("row"):
        for column in row.findall("column"):
            try:
                cells.setdefault(int(column.get("channel", "")), []).append(
                    (int(row.get("index", "")), int(column.get("index", ""))))
            except ValueError:
                continue
    boxes: dict[int, tuple[float, float, float, float]] = {}
    for channel, points in cells.items():
        xs = [(column + 0.5) / columns * 2 - 1 for _, column in points]
        ys = [1 - (row + 0.5) / rows * 2 for row, _ in points]
        boxes[channel] = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2,
                          max(max(xs) - min(xs), 2 / columns),
                          max(max(ys) - min(ys), 2 / rows))
    return boxes


def display_from_lms(document: LmsDocument, display_name: str) -> LmsDisplay:
    """An equivalent S6-style preview: one single-color prop per LOR channel.

    Channels that are not LOR channels with a unit and circuit (dummy, DMX, or
    unassigned channels) are listed as excluded; they stay in the output unchanged.
    """
    # Every S4 sequence of the same display has the same channels, so they share an
    # id: requirements remembered for one song apply to the next.
    identity = "\n".join(
        f"{c.network or 'Regular'},{c.unit},{c.circuit},{c.name}"
        for c in sorted(document.channels, key=lambda c: c.saved_index) if c.is_lor)
    preview = ET.Element("PreviewClass", {
        "id": str(uuid.uuid5(_NAMESPACE, "preview/" + identity)),
        "Name": display_name, "Revision": "0", "EmbedBackgrounds": "False",
        "Brightness": "5",
    })
    boxes = _layout(document.root)
    prop_channels: dict[str, int] = {}
    excluded: list[tuple[str, str]] = []
    for channel in document.channels:
        if not channel.is_lor:
            reason = ("no controller assigned" if not channel.device_type
                      else f"{channel.device_type} channels are not generated yet"
                      if channel.device_type != "LOR" else "missing unit or circuit")
            excluded.append((channel.name, reason))
            continue
        prop_id = _prop_id(channel.saved_index)
        color = color_name(channel.color)
        network = channel.network or "Regular"
        prop = ET.SubElement(preview, "PropClass", {
            "id": prop_id, "Name": channel.name, "DeviceType": "LOR",
            "ChannelGrid": f"{network},{channel.unit},{channel.circuit},{channel.circuit},0,{color}",
            "TraditionalType": "Single Color", "TraditionalColors": color,
            "BulbShape": "Square", "MaxChannels": "16", "IndividualChannels": "False",
            "StartLocation": "n/a", "StringType": "Traditional", "MasterPropId": "",
            "Parm1": "1", "Parm2": "50", "Comment": "", "Tag": "",
        })
        box = boxes.get(channel.saved_index)
        shape = ET.SubElement(prop, "shape", {"ShapeName": "Square"})
        if box is not None:
            x, y, width, height = box
            shape.attrib.update({"OffsetX": f"{x:.5f}", "OffsetY": f"{y:.5f}",
                                 "ScaleX": f"{width:.5f}", "ScaleY": f"{height:.5f}",
                                 "Radians": "0"})
        prop_channels[prop_id] = channel.saved_index

    by_index = {group.saved_index: group for group in document.groups}
    lor_props = {index: prop for prop, index in prop_channels.items()}

    def flatten(index: int, seen: frozenset[int]) -> list[str]:
        if index in lor_props:
            return [lor_props[index]]
        group = by_index.get(index)
        if group is None or index in seen:
            return []
        found: list[str] = []
        for member in group.members:
            found.extend(flatten(member, seen | {index}))
        return found

    for group in document.groups:
        members = list(dict.fromkeys(flatten(group.saved_index, frozenset())))
        if len(members) < 2:
            continue
        element = ET.SubElement(preview, "PropGroup", {
            "id": _group_id(group.saved_index), "Name": group.name, "Arrangement": "Preview",
        })
        for member in members:
            ET.SubElement(element, "member", {"id": member, "orientation": "normal",
                                              "top": "0", "left": "0"})
    ET.SubElement(preview, "PropViews")
    if not prop_channels:
        raise LmsError("The .lms has no LOR channels with a unit and circuit to light")
    return LmsDisplay(preview, prop_channels, tuple(excluded))


def preview_bytes(display: LmsDisplay) -> bytes:
    text = ET.tostring(display.preview, encoding="unicode")
    return ('<?xml version="1.0" encoding="utf-8"?>\n' + text).encode("utf-8")


@dataclass(frozen=True, slots=True)
class LmsEffect:
    saved_index: int
    kind: str
    start_centisecond: int
    end_centisecond: int
    start_intensity: int
    end_intensity: int


def _effect_attributes(effect: LmsEffect) -> dict[str, str]:
    attributes = {"type": _EFFECT_TYPES[effect.kind],
                  "startCentisecond": str(effect.start_centisecond),
                  "endCentisecond": str(effect.end_centisecond)}
    if effect.start_intensity == effect.end_intensity:
        attributes["intensity"] = str(effect.start_intensity)
    else:
        attributes["startIntensity"] = str(effect.start_intensity)
        attributes["endIntensity"] = str(effect.end_intensity)
    return attributes


def build_lms(
    template: LmsDocument,
    effects: Iterable[LmsEffect],
    duration_centiseconds: int,
    music_filename: str,
    section_starts: Iterable[int] = (),
) -> bytes:
    """A new S4 sequence: the template's channels, groups and tracks with new effects.

    The template's own effects, freeform timings and loops are song-specific and are
    removed; its author and creation time are not carried into the new show.
    """
    if duration_centiseconds <= 0:
        raise LmsError("A show must be longer than zero")
    root = copy.deepcopy(template.root)
    for key in ("author", "createdAt", "modifiedBy"):
        root.attrib.pop(key, None)
    root.set("musicFilename", music_filename)
    channels = root.find("channels")
    assert channels is not None  # parse_lms guarantees it
    by_index: dict[int, ET.Element] = {}
    for channel in channels.findall("channel"):
        for old_effect in channel.findall("effect"):
            channel.remove(old_effect)
        channel.set("centiseconds", str(duration_centiseconds))
        by_index[int(channel.get("savedIndex", "-1"))] = channel
    for element in channels:
        if element.tag != "channel" and element.get("totalCentiseconds") is not None:
            element.set("totalCentiseconds", str(duration_centiseconds))
        if element.tag != "channel" and element.get("centiseconds") is not None:
            element.set("centiseconds", str(duration_centiseconds))

    ordered = sorted(effects, key=lambda e: (e.saved_index, e.start_centisecond))
    last_end: dict[int, int] = {}
    for effect in ordered:
        target = by_index.get(effect.saved_index)
        if target is None:
            raise LmsError(f"An effect was planned for savedIndex {effect.saved_index}, "
                           "which is not a channel in the template")
        if effect.kind not in _EFFECT_TYPES:
            raise LmsError(f"S4 has no {effect.kind!r} effect")
        if not 0 <= effect.start_centisecond < effect.end_centisecond <= duration_centiseconds:
            raise LmsError("An effect falls outside the show")
        if effect.start_centisecond < last_end.get(effect.saved_index, 0):
            raise LmsError("Two effects overlap on one channel")
        for value in (effect.start_intensity, effect.end_intensity):
            if not 0 <= value <= 100:
                raise LmsError("Intensities run from 0 to 100")
        last_end[effect.saved_index] = effect.end_centisecond
        ET.SubElement(target, "effect", _effect_attributes(effect))

    grids = root.find("timingGrids")
    if grids is None:
        grids = ET.SubElement(root, "timingGrids")
    used_ids: set[int] = set()
    for grid in grids.findall("timingGrid"):
        used_ids.add(int(grid.get("saveID", "0") or 0))
        if grid.get("type") == "freeform":
            for timing in grid.findall("timing"):
                grid.remove(timing)
    if not any(grid.get("type") == "fixed" for grid in grids.findall("timingGrid")):
        fixed_id = max(used_ids, default=-1) + 1
        used_ids.add(fixed_id)
        ET.SubElement(grids, "timingGrid", {"saveID": str(fixed_id), "name": "Fixed Grid: 0.05",
                                            "type": "fixed", "spacing": "5"})
    starts = sorted({s for s in section_starts if 0 < s < duration_centiseconds})
    if starts:
        section_id = max(used_ids, default=-1) + 1
        sections = ET.SubElement(grids, "timingGrid", {"saveID": str(section_id),
                                                       "name": "Sections", "type": "freeform"})
        for start in starts:
            ET.SubElement(sections, "timing", {"centisecond": str(start)})
    tracks = root.find("tracks")
    if tracks is None or tracks.find("track") is None:
        tracks = tracks if tracks is not None else ET.SubElement(root, "tracks")
        track = ET.SubElement(tracks, "track", {"totalCentiseconds": "0", "timingGrid": "0"})
        refs = ET.SubElement(track, "channels")
        for index in sorted(by_index):
            ET.SubElement(refs, "channel", {"savedIndex": str(index)})
        ET.SubElement(track, "loopLevels")
    for track in tracks.findall("track"):
        track.set("totalCentiseconds", str(duration_centiseconds))
        loops = track.find("loopLevels")
        if loops is not None:
            for level in list(loops):
                loops.remove(level)

    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    text = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + body + "\n"
    output = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    parse_lms(output, "The generated .lms")
    return output


def write_lms(path: str | Path, content: bytes) -> Path:
    """Publish a generated .lms without overwriting anything."""
    target = Path(path)
    if target.suffix.lower() != ".lms":
        raise LmsError("An S4 sequence must use the .lms extension")
    try:
        return write_new_bytes_atomically(target, content)
    except FileExistsError as exc:
        raise LmsError(f"{target.name} already exists; choose a new name") from exc
    except OSError as exc:
        raise LmsError(f"Cannot write {target.name}: {exc}") from exc
