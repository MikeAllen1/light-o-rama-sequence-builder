"""Loss-preserving parser for observed standalone S6 LORPREV preview XML."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

MAX_LORPREV_BYTES = 20 * 1024 * 1024
MAX_XML_DEPTH = 256
MAX_LORPREV_ELEMENTS = 100_000
MAX_CHANNEL_GRID_ENTRIES_PER_PROP = 10_000
MAX_CHANNEL_GRID_ENTRIES_TOTAL = 100_000


class LorprevError(ValueError):
    """Base error for invalid or unsupported LORPREV documents."""


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
    """One source channel assignment, with documented address fields and raw provenance."""

    source: SourceValue
    entry_index: int
    device_type: str | None
    raw_fields: tuple[str, ...]
    network: str | None = None
    unit_id: str | None = None
    circuit: str | None = None
    universe: str | None = None
    channel: str | None = None


@dataclass(frozen=True, slots=True)
class GeometryPoint:
    """A source geometry point with separately traceable coordinates."""

    x: SourceValue
    y: SourceValue
    locator: str


@dataclass(frozen=True, slots=True)
class PropGroupMemberModel:
    """A group member reference and its source layout attributes."""

    source: RawElement
    prop_id: SourceValue | None
    orientation: SourceValue | None
    top: SourceValue | None
    left: SourceValue | None


@dataclass(frozen=True, slots=True)
class PropGroupModel:
    """A preview prop group with loss-preserving member references."""

    source: RawElement
    group_id: SourceValue | None
    name: SourceValue | None
    arrangement: SourceValue | None
    members: tuple[PropGroupMemberModel, ...]


@dataclass(frozen=True, slots=True)
class PropModel:
    """Raw display model; interpretation/classification is deliberately deferred."""

    source_file: str
    # PreviewClass/@Revision is an edit counter that S6 increments each time the
    # preview is saved. It is recorded as metadata only and never used to accept,
    # reject, or interpret a preview; compatibility is judged by structure.
    revision: SourceValue | None
    display: RawElement
    props: tuple[RawElement, ...]
    scenes: tuple[RawElement, ...]
    prop_views: tuple[RawElement, ...]
    groups: tuple[PropGroupModel, ...]
    unrecognized_top_level: tuple[RawElement, ...]
    unrecognized_elements: tuple[RawElement, ...]
    unsupported_constructs: tuple[UnsupportedConstruct, ...]
    channel_grid_entries: tuple[ChannelGridEntry, ...]
    geometry_points: tuple[GeometryPoint, ...]


def _raw_element(
    element: ET.Element, source: str, locator: str, depth: int = 0
) -> RawElement:
    """Capture source XML while bounding nesting depth against stack exhaustion."""
    if depth > MAX_XML_DEPTH:
        raise LorprevError(
            f"LORPREV XML nesting exceeds the maximum depth of {MAX_XML_DEPTH}"
        )
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
        children.append(_raw_element(child, source, child_locator, depth + 1))
    return RawElement(
        tag=str(element.tag),
        attributes=attributes,
        children=tuple(children),
        text=element.text,
        tail=element.tail,
        locator=locator,
    )


def _walk_raw_elements(element: RawElement) -> tuple[RawElement, ...]:
    """Return the element and all descendants in source order."""
    matches = [element]
    for child in element.children:
        matches.extend(_walk_raw_elements(child))
    return tuple(matches)


def read_lorprev(path: str | Path) -> PropModel:
    """Read a standalone S6 preview. Compatibility is judged by structure, not Revision."""
    source = Path(path)
    try:
        with source.open("rb") as preview_file:
            content = preview_file.read(MAX_LORPREV_BYTES + 1)
    except OSError as exc:
        raise LorprevError(f"Cannot access LORPREV file: {source}") from exc
    if not content:
        raise LorprevError("LORPREV file is empty")
    if len(content) > MAX_LORPREV_BYTES:
        raise LorprevError(
            f"LORPREV file exceeds the {MAX_LORPREV_BYTES // (1024 * 1024)} MiB limit"
        )

    try:
        # Parse incrementally so depth and total-node limits are enforced while
        # the XML parser is consuming input, before building the raw model.
        iterator = SafeET.iterparse(
            io.BytesIO(content),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        depth = 0
        element_count = 0
        for event, _element in iterator:
            if event == "start":
                depth += 1
                element_count += 1
                if depth > MAX_XML_DEPTH:
                    raise LorprevError(
                        f"LORPREV XML nesting exceeds the maximum depth of {MAX_XML_DEPTH}"
                    )
                if element_count > MAX_LORPREV_ELEMENTS:
                    raise LorprevError(
                        "LORPREV XML exceeds the maximum element count "
                        f"of {MAX_LORPREV_ELEMENTS}"
                    )
            else:
                depth -= 1
        # defusedxml's iterator type does not expose its runtime root attribute
        # in the published stubs. Reparse the already-bounded bytes securely.
        root = SafeET.fromstring(
            content, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except LorprevError:
        raise
    except (ET.ParseError, DefusedXmlException) as exc:
        raise LorprevError(f"Invalid or unsafe LORPREV XML: {source}") from exc

    if root is None or root.tag != "PreviewClass":
        raise LorprevError("LORPREV root element must be <PreviewClass>")

    revision = root.attrib.get("Revision")

    props = tuple(root.findall("PropClass"))
    if not props:
        raise LorprevError("LORPREV contains zero PropClass entries; add at least one prop")

    display = _raw_element(root, str(source), "/PreviewClass")
    prop_nodes = tuple(
        child for child in display.children if child.tag == "PropClass"
    )
    scenes = tuple(child for child in display.children if child.tag == "Scene")
    prop_views = tuple(child for child in display.children if child.tag == "PropViews")
    group_nodes = tuple(child for child in display.children if child.tag == "PropGroup")
    known = {"PropClass", "Scene", "PropViews", "PropGroup"}
    unknown = tuple(child for child in display.children if child.tag not in known)
    # Only these tags have been observed in committed native fixtures. Preserve
    # and surface every other tag at any depth without guessing its meaning.
    known_tags = {"PreviewClass", "PropClass", "Scene", "PropViews", "PropGroup", "member", "shape", "point"}
    unrecognized_elements = tuple(
        node for node in _walk_raw_elements(display) if node.tag not in known_tags
    )

    # Surface unfamiliar prop/device declarations explicitly. Preserve the raw
    # source unchanged; these checks do not attempt to classify a prop.
    unsupported: list[UnsupportedConstruct] = []
    for prop in prop_nodes:
        for attribute, kind, supported_values in (
            ("DeviceType", "device type", {"LOR", "AC", "DC", "DMX", "Undetermined"}),
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

    prop_ids: set[str] = set()
    for prop in prop_nodes:
        prop_id = prop.attributes.get("id")
        if prop_id is None or not prop_id.value.strip():
            unsupported.append(
                UnsupportedConstruct(
                    kind="prop identity",
                    detail="PropClass is missing a non-empty id attribute",
                    source=SourceValue("", str(source), f"{prop.locator}/@id"),
                )
            )
            continue
        if prop_id.value in prop_ids:
            unsupported.append(
                UnsupportedConstruct(
                    kind="prop identity",
                    detail=f"Duplicate PropClass id {prop_id.value!r}",
                    source=prop_id,
                )
            )
            continue
        prop_ids.add(prop_id.value)

    groups: list[PropGroupModel] = []
    all_identity_ids = set(prop_ids)
    for group in group_nodes:
        group_id = group.attributes.get("id")
        if group_id is None or not group_id.value.strip():
            unsupported.append(
                UnsupportedConstruct(
                    kind="prop group identity",
                    detail="PropGroup is missing a non-empty id attribute",
                    source=SourceValue("", str(source), f"{group.locator}/@id"),
                )
            )
        elif group_id.value in all_identity_ids:
            unsupported.append(
                UnsupportedConstruct(
                    kind="prop group identity",
                    detail=f"Duplicate identity id {group_id.value!r} across PropClass/PropGroup",
                    source=group_id,
                )
            )
        else:
            all_identity_ids.add(group_id.value)
        members: list[PropGroupMemberModel] = []
        for member in (child for child in group.children if child.tag == "member"):
            member_id = member.attributes.get("id")
            if member_id is None:
                unsupported.append(
                    UnsupportedConstruct(
                        kind="prop group member",
                        detail="PropGroup member is missing its prop id reference",
                        source=group.attributes.get("id")
                        or SourceValue("", str(source), member.locator),
                    )
                )
            elif member_id.value not in prop_ids:
                unsupported.append(
                    UnsupportedConstruct(
                        kind="prop group member",
                        detail=f"PropGroup member references unknown prop id {member_id.value!r}",
                        source=member_id,
                    )
                )
            members.append(
                PropGroupMemberModel(
                    source=member,
                    prop_id=member_id,
                    orientation=member.attributes.get("orientation"),
                    top=member.attributes.get("top"),
                    left=member.attributes.get("left"),
                )
            )
        groups.append(
            PropGroupModel(
                source=group,
                group_id=group_id,
                name=group.attributes.get("Name"),
                arrangement=group.attributes.get("Arrangement"),
                members=tuple(members),
            )
        )

    channel_entries: list[ChannelGridEntry] = []
    geometry_points: list[GeometryPoint] = []
    total_channel_entries = 0
    for prop in prop_nodes:
        channel_grid = prop.attributes.get("ChannelGrid")
        device_type_value = prop.attributes.get("DeviceType")
        device_type = device_type_value.value if device_type_value is not None else None
        if channel_grid is not None:
            entry_count = channel_grid.value.count(";") + 1
            if entry_count > MAX_CHANNEL_GRID_ENTRIES_PER_PROP:
                raise LorprevError(
                    f"Prop ChannelGrid exceeds the {MAX_CHANNEL_GRID_ENTRIES_PER_PROP} entry limit"
                )
            total_channel_entries += entry_count
            if total_channel_entries > MAX_CHANNEL_GRID_ENTRIES_TOTAL:
                raise LorprevError(
                    "LORPREV exceeds the total ChannelGrid entry limit "
                    f"of {MAX_CHANNEL_GRID_ENTRIES_TOTAL}"
                )
            for entry_index, entry in enumerate(channel_grid.value.split(";")):
                raw_fields = tuple(entry.split(","))
                assignment: dict[str, str | None] = {
                    "network": None,
                    "unit_id": None,
                    "circuit": None,
                    "universe": None,
                    "channel": None,
                }
                if device_type == "LOR":
                    if len(raw_fields) >= 3 and all(raw_fields[:3]):
                        assignment.update(
                            network=raw_fields[0],
                            unit_id=raw_fields[1],
                            circuit=raw_fields[2],
                        )
                    else:
                        unsupported.append(
                            UnsupportedConstruct(
                                kind="channel assignment",
                                detail=(
                                    "LOR ChannelGrid entry must include network, "
                                    "Unit ID, and circuit fields"
                                ),
                                source=channel_grid,
                            )
                        )
                elif device_type == "DMX":
                    if len(raw_fields) >= 2 and all(raw_fields[:2]):
                        assignment.update(
                            universe=raw_fields[0],
                            channel=raw_fields[1],
                        )
                    else:
                        unsupported.append(
                            UnsupportedConstruct(
                                kind="channel assignment",
                                detail=(
                                    "DMX ChannelGrid entry must include universe "
                                    "and channel fields"
                                ),
                                source=channel_grid,
                            )
                        )
                channel_entries.append(
                    ChannelGridEntry(
                        source=channel_grid,
                        entry_index=entry_index,
                        device_type=device_type,
                        raw_fields=raw_fields,
                        **assignment,
                    )
                )
        # A point is geometry only when it is a direct child of an observed
        # shape element. Do not interpret similarly named nodes in unknown
        # nested structures as display geometry.
        for shape in (child for child in prop.children if child.tag == "shape"):
            for point in (child for child in shape.children if child.tag == "point"):
                x_value = point.attributes.get("x")
                y_value = point.attributes.get("y")
                if x_value is None or y_value is None:
                    raise LorprevError(
                        f"Incomplete geometry point at {point.locator}: "
                        "both x and y attributes are required"
                    )
                geometry_points.append(
                    GeometryPoint(x=x_value, y=y_value, locator=point.locator)
                )

    return PropModel(
        source_file=str(source),
        revision=(
            None
            if revision is None
            else SourceValue(
                value=revision, file=str(source), locator="/PreviewClass/@Revision"
            )
        ),
        display=display,
        props=prop_nodes,
        scenes=scenes,
        prop_views=prop_views,
        groups=tuple(groups),
        unrecognized_top_level=unknown,
        unrecognized_elements=unrecognized_elements,
        unsupported_constructs=tuple(unsupported),
        channel_grid_entries=tuple(channel_entries),
        geometry_points=tuple(geometry_points),
    )
