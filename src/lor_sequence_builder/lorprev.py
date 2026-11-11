"""Loss-preserving parser for observed standalone S6 LORPREV preview XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

SUPPORTED_PREVIEW_REVISIONS = frozenset({"0", "1"})
MAX_LORPREV_BYTES = 20 * 1024 * 1024


class LorprevError(ValueError):
    """Base error for invalid or unsupported LORPREV documents."""


class UnsupportedLorprevRevisionError(LorprevError):
    """Raised when a preview revision has not been verified."""


@dataclass(frozen=True, slots=True)
class SourceValue:
    """An unmodified source attribute and its stable XML locator."""

    value: str
    file: str
    locator: str


@dataclass(frozen=True, slots=True)
class RawElement:
    """Loss-preserving representation of one source XML element."""

    tag: str
    attributes: dict[str, SourceValue]
    children: tuple[RawElement, ...]
    text: str | None
    tail: str | None
    locator: str


@dataclass(frozen=True, slots=True)
class UnsupportedConstruct:
    """A source construct requiring later semantic support, with its provenance."""

    kind: str
    detail: str
    source: SourceValue


@dataclass(frozen=True, slots=True)
class ChannelGridEntry:
    """One source ChannelGrid entry; comma-separated fields remain uninterpreted."""

    source: SourceValue
    entry_index: int
    raw_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeometryPoint:
    """A source geometry point with separately traceable coordinates."""

    x: SourceValue
    y: SourceValue
    locator: str


@dataclass(frozen=True, slots=True)
class PropModel:
    """Raw display model; interpretation/classification is deliberately deferred."""

    source_file: str
    revision: SourceValue
    display: RawElement
    props: tuple[RawElement, ...]
    scenes: tuple[RawElement, ...]
    prop_views: tuple[RawElement, ...]
    unrecognized_top_level: tuple[RawElement, ...]
    unsupported_constructs: tuple[UnsupportedConstruct, ...]
    channel_grid_entries: tuple[ChannelGridEntry, ...]
    geometry_points: tuple[GeometryPoint, ...]


def _raw_element(element: ET.Element, source: str, locator: str) -> RawElement:
    """Capture all attributes and descendants without normalizing source values."""
    attributes = {
        key: SourceValue(value=value, file=source, locator=f"{locator}/@{key}")
        for key, value in element.attrib.items()
    }
    counts: dict[str, int] = {}
    children: list[RawElement] = []
    for child in list(element):
        index = counts.get(child.tag, 0)
        counts[child.tag] = index + 1
        child_locator = f"{locator}/{child.tag}[{index}]"
        children.append(_raw_element(child, source, child_locator))
    return RawElement(
        tag=str(element.tag),
        attributes=attributes,
        children=tuple(children),
        text=element.text,
        tail=element.tail,
        locator=locator,
    )


def _iter_raw_elements(element: RawElement, tag: str) -> tuple[RawElement, ...]:
    """Return matching descendants in source order, including the element itself."""
    matches: list[RawElement] = []
    if element.tag == tag:
        matches.append(element)
    for child in element.children:
        matches.extend(_iter_raw_elements(child, tag))
    return tuple(matches)


def read_lorprev(path: str | Path) -> PropModel:
    """Read a standalone S6 preview for verified Revision 0 and Revision 1 formats."""
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise LorprevError(f"Cannot access LORPREV file: {source}") from exc
    if size == 0:
        raise LorprevError("LORPREV file is empty")
    if size > MAX_LORPREV_BYTES:
        raise LorprevError(
            f"LORPREV file exceeds the {MAX_LORPREV_BYTES // (1024 * 1024)} MiB limit"
        )

    try:
        root = SafeET.parse(
            source, forbid_dtd=True, forbid_entities=True, forbid_external=True
        ).getroot()
    except (OSError, ET.ParseError, DefusedXmlException) as exc:
        raise LorprevError(f"Invalid or unsafe LORPREV XML: {source}") from exc

    if root is None or root.tag != "PreviewClass":
        raise LorprevError("LORPREV root element must be <PreviewClass>")

    revision = root.attrib.get("Revision")
    if revision is None:
        raise LorprevError("LORPREV is missing the PreviewClass Revision attribute")
    if revision not in SUPPORTED_PREVIEW_REVISIONS:
        supported = ", ".join(sorted(SUPPORTED_PREVIEW_REVISIONS))
        raise UnsupportedLorprevRevisionError(
            f"Unsupported LORPREV Revision {revision!r}; "
            f"verified revisions are {supported}"
        )

    props = tuple(root.findall("PropClass"))
    if not props:
        raise LorprevError("LORPREV contains zero PropClass entries; add at least one prop")

    display = _raw_element(root, str(source), "/PreviewClass")
    prop_nodes = tuple(
        child for child in display.children if child.tag == "PropClass"
    )
    scenes = tuple(child for child in display.children if child.tag == "Scene")
    prop_views = tuple(child for child in display.children if child.tag == "PropViews")
    known = {"PropClass", "Scene", "PropViews"}
    unknown = tuple(child for child in display.children if child.tag not in known)

    # Surface unfamiliar prop/device declarations explicitly. Preserve the raw
    # source unchanged; these checks do not attempt to classify a prop.
    unsupported: list[UnsupportedConstruct] = []
    for prop in prop_nodes:
        for attribute, kind, supported_values in (
            ("DeviceType", "device type", {"LOR", "AC", "DC"}),
            (
                "TraditionalType",
                "traditional prop type",
                {"Single Color", "Channel_per_color", "Multicolor_string_1_ch"},
            ),
        ):
            value = prop.attributes.get(attribute)
            if value is not None and value.value not in supported_values:
                unsupported.append(
                    UnsupportedConstruct(
                        kind=kind,
                        detail=f"Unsupported {attribute} value {value.value!r}",
                        source=value,
                    )
                )

    channel_entries: list[ChannelGridEntry] = []
    geometry_points: list[GeometryPoint] = []
    for prop in prop_nodes:
        channel_grid = prop.attributes.get("ChannelGrid")
        if channel_grid is not None:
            for entry_index, entry in enumerate(channel_grid.value.split(";")):
                channel_entries.append(
                    ChannelGridEntry(
                        source=channel_grid,
                        entry_index=entry_index,
                        raw_fields=tuple(entry.split(",")),
                    )
                )
        for point in _iter_raw_elements(prop, "point"):
            x_value = point.attributes.get("x")
            y_value = point.attributes.get("y")
            if x_value is not None and y_value is not None:
                geometry_points.append(
                    GeometryPoint(x=x_value, y=y_value, locator=point.locator)
                )

    return PropModel(        source_file=str(source),
        revision=SourceValue(
            value=revision, file=str(source), locator="/PreviewClass/@Revision"
        ),
        display=display,
        props=prop_nodes,
        scenes=scenes,
        prop_views=prop_views,
        unrecognized_top_level=unknown,
        unsupported_constructs=tuple(unsupported),
        channel_grid_entries=tuple(channel_entries),
        geometry_points=tuple(geometry_points),
    )
