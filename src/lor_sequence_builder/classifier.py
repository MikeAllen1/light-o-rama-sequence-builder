"""Infer what each prop in a display preview is, the way a person reads a preview.

The preview is the only input. Evidence comes from what S6 stores for each prop:
its shape type and parameters, geometry, channel count and type, string start
location, group membership and order, and links to a master prop. Names are a
capped tiebreaker: a name alone can never reach the confidence needed to assign
a role. Every conclusion carries its evidence so a person can check it, and a
wrong conclusion is corrected the LOR way, by fixing the prop in the preview.
"""

from __future__ import annotations

import itertools
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from lor_sequence_builder.new_sequence import channel_layout_problem

ROLES = (
    "arch",
    "mini_tree",
    "mega_tree",
    "star",
    "singing_face",
    "icicles",
    "outline",
    "snowflake",
    "unknown",
)
CONFIDENT = 0.7
DIRECTIONAL_ROLES = frozenset({"arch", "mini_tree", "mega_tree", "icicles", "outline", "unknown"})
ASSIGN = 0.5
NAME_WEIGHT = 0.25

_NAME_HINTS: tuple[tuple[str, str], ...] = (
    (r"\barch", "arch"),
    (r"\bmega\b|\bmegatree\b|\bmega[\s_-]*tree", "mega_tree"),
    (r"\bmini\b|\bmini[\s_-]*trees?\b|\bminitree", "mini_tree"),
    (r"\bstar\b", "star"),
    (r"\bface\b|\bsinging\b|\bmouth\b|\bmustache\b|\bsanta\b", "singing_face"),
    (r"\bicicle", "icicles"),
    (r"\broof|\bgutter|\boutline|\bwindow|\bdoor|\beave", "outline"),
    (r"\bsnow\s*flake|\bflake\b", "snowflake"),
)

_START_DIRECTION = {
    "Left": "left_to_right",
    "Right": "right_to_left",
    "Bottom Left": "left_to_right",
    "Bottom Right": "right_to_left",
    "Top Left": "left_to_right",
    "Top Right": "right_to_left",
    "Bottom": "bottom_to_top",
    "Top": "top_to_bottom",
}


class ClassificationError(ValueError):
    """Raised when a preview cannot be classified."""


@dataclass(frozen=True, slots=True)
class Evidence:
    role: str
    weight: float
    reason: str


@dataclass(frozen=True, slots=True)
class ColorCapability:
    kind: str
    colors: tuple[str, ...]
    can_show_single_color: bool
    note: str


@dataclass(frozen=True, slots=True)
class PropClassification:
    prop_id: str
    name: str
    role: str
    confidence: float
    status: str
    evidence: tuple[Evidence, ...]
    channel_count: int
    color_capability: ColorCapability
    sequencing_support: str
    direction: str
    segment_order: str
    linked_to: str | None
    group: str | None
    position_in_row: int | None
    review_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class _Geometry:
    center_x: float
    center_y: float
    width: float
    height: float
    point_count: int
    closed: bool
    arc_like: bool


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _geometry(prop: ET.Element) -> _Geometry | None:
    shape = prop.find("shape")
    if shape is None:
        return None
    offset_x, offset_y = _float(shape.get("OffsetX")), _float(shape.get("OffsetY"))
    scale_x, scale_y = _float(shape.get("ScaleX")), _float(shape.get("ScaleY"))
    if None not in (offset_x, offset_y, scale_x, scale_y):
        assert offset_x is not None and offset_y is not None
        assert scale_x is not None and scale_y is not None
        return _Geometry(offset_x, offset_y, abs(scale_x), abs(scale_y), 0, False, False)
    points = [
        (x, y)
        for x, y in ((_float(p.get("x")), _float(p.get("y"))) for p in shape.findall("point"))
        if x is not None and y is not None
    ]
    if not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    span = max(width, height, 1e-9)
    closed = len(points) >= 4 and math.dist(points[0], points[-1]) <= 0.05 * span
    arc_like = False
    if len(points) >= 5 and width > 0 and height > 0.15 * width:
        middle = points[len(points) // 2][1]
        ends = (points[0][1] + points[-1][1]) / 2
        ordered_x = all(b[0] >= a[0] for a, b in itertools.pairwise(points))
        arc_like = ordered_x and middle - ends >= 0.6 * height
    return _Geometry(
        (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, width, height,
        len(points), closed, arc_like,
    )


def _channel_entries(prop: ET.Element) -> list[list[str]]:
    return [entry.split(",") for entry in prop.get("ChannelGrid", "").split(";") if entry]


def _color_capability(prop: ET.Element) -> ColorCapability:
    traditional = prop.get("TraditionalType", "")
    device = prop.get("DeviceType", "")
    listed = tuple(c.strip() for c in prop.get("TraditionalColors", "").split(",") if c.strip())
    entry_colors = tuple(
        entry[5].strip() for entry in _channel_entries(prop) if len(entry) > 5 and entry[5].strip()
    )
    if device not in {"LOR", "AC", "DC"} or prop.get("StringType", "Traditional") != "Traditional":
        return ColorCapability(
            "unsupported", listed, False,
            f"{device or 'Unknown device'} / {prop.get('StringType', '')} props are not supported in v1",
        )
    if traditional == "Single Color":
        colors = listed[:1] or entry_colors[:1]
        return ColorCapability(
            "single_color", colors, True, "One color per channel; that color can be shown alone"
        )
    if traditional == "Multicolor_string_1_ch":
        return ColorCapability(
            "combined_colors", listed, False,
            "All colors share one circuit; no single color can be shown alone",
        )
    if traditional == "Channel_per_color":
        colors = entry_colors or listed
        return ColorCapability(
            "color_per_channel", colors, True, "Each color has its own channel and can be shown alone"
        )
    return ColorCapability(
        "unknown", listed, False, f"TraditionalType {traditional or '(missing)'} is not recognized"
    )


def _groups(preview: ET.Element) -> dict[str, tuple[str, list[str]]]:
    membership: dict[str, tuple[str, list[str]]] = {}
    for group in preview.findall("PropGroup"):
        members = [m.get("id", "") for m in group.findall("member") if m.get("id")]
        for member in members:
            membership.setdefault(member, (group.get("Name", ""), members))
    return membership


def _shape_evidence(
    shape_name: str, channels: int, parm1: int | None, geometry: _Geometry | None,
    traditional: str,
) -> list[Evidence]:
    evidence: list[Evidence] = []
    lowered = shape_name.lower()
    if lowered == "arch":
        evidence.append(Evidence("arch", 0.75, "S6 shape type is Arch"))
    elif lowered == "star":
        evidence.append(Evidence("star", 0.75, "S6 shape type is Star"))
    elif lowered.startswith("tree"):
        strands = max(channels, parm1 or 0)
        if strands >= 8:
            evidence.append(Evidence("mega_tree", 0.75, f"S6 tree shape with {strands} strands"))
        else:
            evidence.append(Evidence("mini_tree", 0.55, f"S6 tree shape with {strands} strand(s)"))
            evidence.append(Evidence("mega_tree", 0.3, "S6 tree shape"))
    elif lowered == "icicles":
        evidence.append(Evidence("icicles", 0.75, "S6 shape type is Icicles"))
    elif lowered.startswith(("snowflake", "snow flake")):
        evidence.append(Evidence("snowflake", 0.75, "S6 shape type is a snowflake"))
    elif lowered.startswith("lines") and geometry is not None:
        if geometry.arc_like:
            evidence.append(Evidence("arch", 0.5, "Drawn as a single raised arc"))
        if geometry.closed and traditional == "Channel_per_color" and channels in (3, 4):
            evidence.append(Evidence(
                "singing_face", 0.45,
                f"Closed outline with {channels} independently colored channels (outline and mouth positions)",
            ))
        elif geometry.closed:
            evidence.append(Evidence("outline", 0.35, "Closed outline shape"))
        if geometry.width > 0 and geometry.height < 0.08 * geometry.width and geometry.width > 0.3:
            evidence.append(Evidence("outline", 0.45, "Long, flat horizontal run"))
    if traditional == "Channel_per_color" and channels in (3, 4) and not lowered.startswith("lines"):
        evidence.append(Evidence("singing_face", 0.2, f"{channels} independently colored channels"))
    return evidence


def _name_evidence(name: str) -> list[Evidence]:
    lowered = name.lower()
    hits = [role for pattern, role in _NAME_HINTS if re.search(pattern, lowered)]
    return [Evidence(role, NAME_WEIGHT, f"Name {name!r} suggests {role.replace('_', ' ')}") for role in hits[:1]]


def classify_preview(preview: ET.Element) -> tuple[PropClassification, ...]:
    """Classify every prop in a parsed ``PreviewClass`` element."""
    if preview.tag != "PreviewClass":
        raise ClassificationError("Preview root element must be <PreviewClass>")
    props = preview.findall("PropClass")
    if not props:
        raise ClassificationError("Preview contains zero PropClass entries")
    groups = _groups(preview)
    by_id = {p.get("id", ""): p for p in props}
    geometries = {p.get("id", ""): _geometry(p) for p in props}

    # Props that look the same and sit together form a row (arches, mini trees).
    # Group order is the user's own ordering; otherwise order left to right.
    row_position: dict[str, tuple[str, int, int]] = {}
    for prop_id, (group_name, members) in groups.items():
        row_position[prop_id] = (group_name, members.index(prop_id) + 1, len(members))
    signature_rows: dict[tuple[str, int, str], list[str]] = {}
    for prop in props:
        prop_id = prop.get("id", "")
        if prop_id in row_position or prop.get("MasterPropId"):
            continue
        shape = prop.find("shape")
        signature = (
            shape.get("ShapeName", "") if shape is not None else "",
            len(_channel_entries(prop)),
            prop.get("TraditionalType", ""),
        )
        signature_rows.setdefault(signature, []).append(prop_id)
    for members in signature_rows.values():
        if len(members) < 3:
            continue
        ordered = sorted(
            members,
            key=lambda i: (geometries[i].center_x if geometries[i] is not None else 0.0),  # type: ignore[union-attr]
        )
        for index, prop_id in enumerate(ordered, start=1):
            row_position[prop_id] = ("", index, len(ordered))

    results: list[PropClassification] = []
    for prop in props:
        prop_id = prop.get("id", "")
        name = prop.get("Name", "")
        shape = prop.find("shape")
        shape_name = shape.get("ShapeName", "") if shape is not None else ""
        channels = len(_channel_entries(prop))
        parm1_value = _float(prop.get("Parm1"))
        parm1 = int(parm1_value) if parm1_value is not None else None
        traditional = prop.get("TraditionalType", "")
        geometry = geometries[prop_id]
        master = prop.get("MasterPropId") or None
        notes: list[str] = []

        evidence = _shape_evidence(shape_name, channels, parm1, geometry, traditional)
        row = row_position.get(prop_id)
        if row is not None and row[2] >= 3:
            shared = (
                f"one of {row[2]} matching props"
                + (f" in group {row[0]!r}" if row[0] else " in a row")
            )
            leading = max((e for e in evidence), key=lambda e: e.weight, default=None)
            if leading is not None and leading.role in {"arch", "mini_tree"}:
                evidence.append(Evidence(leading.role, 0.15, f"Repeated: {shared}"))
            elif not evidence and channels <= 4:
                evidence.append(Evidence("mini_tree", 0.2, f"Small repeated prop: {shared}"))
        evidence += _name_evidence(name)
        if master is not None and master in by_id:
            master_name = by_id[master].get("Name", "")
            evidence.append(Evidence(
                "star" if shape_name.lower() == "star" else "unknown", 0.0,
                f"Linked to master prop {master_name!r}; driven by the master's channels",
            ))

        totals: dict[str, float] = {}
        for item in evidence:
            if item.role != "unknown":
                totals[item.role] = totals.get(item.role, 0.0) + item.weight
        role, score = ("unknown", 0.0)
        if totals:
            role, score = max(totals.items(), key=lambda pair: (pair[1], pair[0] == "unknown"))
        competitors = sorted((v for r, v in totals.items() if r != role), reverse=True)
        if competitors and score - competitors[0] < 0.15:
            notes.append(
                "Close call between "
                + " and ".join(
                    r.replace("_", " ") for r, v in totals.items() if v >= score - 0.15
                )
            )
        name_only = all(e.reason.startswith("Name ") for e in evidence if e.role == role)
        if score < ASSIGN:
            if role != "unknown":
                label = role.replace("_", " ")
                article = "an" if label[0] in "aeiou" else "a"
                notes.append(
                    f"Evidence too weak to call it {article} {label}"
                    + (" (name only)" if name_only else "")
                )
            role = "unknown"
        confidence = round(min(1.0, score), 2)
        status = "confident" if role != "unknown" and confidence >= CONFIDENT and not notes else (
            "review" if role != "unknown" else "unknown"
        )

        capability = _color_capability(prop)
        if capability.kind in {"unsupported", "unknown"}:
            notes.append(capability.note)
        support_problem = None if master else channel_layout_problem(prop)
        if master:
            support = "driven by its master prop"
        elif support_problem is None:
            support = "supported"
        else:
            support = support_problem
            if support_problem not in notes and capability.kind not in {"unsupported", "unknown"}:
                notes.append(f"Cannot be sequenced yet: {support_problem}")
        if (capability.kind in {"unsupported", "unknown"} or support_problem) and status == "confident":
            status = "review"

        start = prop.get("StartLocation", "")
        directional = channels > 1 and role in DIRECTIONAL_ROLES
        direction = _START_DIRECTION.get(start, "unknown") if directional else "not applicable"
        if directional and direction == "unknown" and role != "unknown":
            notes.append("Direction unknown: no string start location in the preview")
        segment_order = (
            "channel order as listed in the preview" if channels > 1 else "single channel"
        )

        results.append(PropClassification(
            prop_id=prop_id,
            name=name,
            role=role,
            confidence=confidence,
            status=status,
            evidence=tuple(evidence),
            channel_count=channels,
            color_capability=capability,
            sequencing_support=support,
            direction=direction,
            segment_order=segment_order,
            linked_to=master,
            group=(row[0] or None) if row is not None else None,
            position_in_row=row[1] if row is not None and row[2] >= 3 else None,
            review_notes=tuple(notes),
        ))
    return tuple(results)


def classification_report(
    classifications: tuple[PropClassification, ...], source_name: str
) -> dict[str, object]:
    """Machine-readable report of every conclusion and the evidence behind it."""
    counts: dict[str, int] = {}
    for item in classifications:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "schema_version": "1.0",
        "preview": source_name,
        "summary": {
            "props": len(classifications),
            "confident": counts.get("confident", 0),
            "review": counts.get("review", 0),
            "unknown": counts.get("unknown", 0),
        },
        "how_to_correct": (
            "Fix the prop in the S6 Preview Editor (shape type, grouping, start location, "
            "or name) and run the analysis again. The preview is the only input."
        ),
        "props": [
            {
                "id": c.prop_id,
                "name": c.name,
                "role": c.role,
                "confidence": c.confidence,
                "status": c.status,
                "evidence": [
                    {"role": e.role, "weight": e.weight, "reason": e.reason} for e in c.evidence
                ],
                "channels": c.channel_count,
                "color_capability": {
                    "kind": c.color_capability.kind,
                    "colors": list(c.color_capability.colors),
                    "can_show_single_color": c.color_capability.can_show_single_color,
                    "note": c.color_capability.note,
                },
                "sequencing_support": c.sequencing_support,
                "direction": c.direction,
                "segment_order": c.segment_order,
                "linked_to": c.linked_to,
                "group": c.group,
                "position_in_row": c.position_in_row,
                "review_notes": list(c.review_notes),
            }
            for c in classifications
        ],
    }
