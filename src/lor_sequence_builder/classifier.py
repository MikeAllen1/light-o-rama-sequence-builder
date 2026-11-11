"""Infer what each prop in a display preview is, the way a person reads a preview.

The preview is the only input. Evidence comes from what S6 stores for each prop:
its shape type and parameters, geometry, channel count and type, string start
location, group membership and order, overlapping props drawn as one figure, and
links to a master prop.

Names follow the owner's rule: when the shape type is specific (Arch, Star,
Tree, Icicles, snowflake), it wins and the name is only a tiebreaker. When the
shape type is generic (plain lines) the name may decide, flagged for review,
because that is how a person reads such a prop. Every conclusion carries its
evidence, and a wrong conclusion is corrected the LOR way: fix the prop in the
preview and run the analysis again.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from lor_sequence_builder.channel_mapping import channel_layout_problem

ROLES = (
    "arch",
    "mini_tree",
    "mega_tree",
    "star",
    "singing_face",
    "icicles",
    "outline",
    "snowflake",
    "decor",
    "unknown",
)
CONFIDENT = 0.7
ASSIGN = 0.5
NAME_TIEBREAK_WEIGHT = 0.25
NAME_DECIDES_WEIGHT = 0.55
FIGURE_WEIGHT = 0.6
# Structural evidence at least this strong for a role turns names into tiebreakers.
STRUCTURE_OVERRULES_NAME = 0.45
DIRECTIONAL_ROLES = frozenset({"arch", "mini_tree", "mega_tree", "icicles", "outline", "unknown"})
_SPECIFIC_SHAPES = ("arch", "star", "tree", "icicles", "snowflake", "snow flake")
# A figure is a few small props drawn on top of each other (a face built from parts).
_FIGURE_MAX_SIZE = 0.4
_FIGURE_OVERLAP = 0.3

# Ordered: the first matching hint wins ("Mini Arch" is an arch, not a mini tree).
_NAME_HINTS: tuple[tuple[str, str], ...] = (
    (r"\bmega\s*tree|\bmegatree|\bmega\b", "mega_tree"),
    (r"\barch", "arch"),
    (r"\bicicle", "icicles"),
    (r"\bsnow\s*flakes?\b|\bflakes?\b", "snowflake"),
    (r"\bstar\b|\btopper\b", "star"),
    (r"\bface\b|\bmouth|\bmustache|\blips?\b|\bsinging\b", "singing_face"),
    (r"\bmini\s*trees?\b|\bminitree|\btrees?\b", "mini_tree"),
    (
        (
            r"\broof|\bgutter|\boutline|\bwindows?\b|\bdoors?\b|\beaves?\b|\bperimeter\b|"
            r"\bgarage\b|\bpillars?\b|\bcolumns?\b|\bposts?\b|\bc\s?[79]\b|\bborder\b|"
            r"\bfence\b|\brailing\b"
        ),
        "outline",
    ),
    (
        (
            r"\breindeer\b|\bdeer\b|\bsnow\s*m[ae]n\b|\bpresents?\b|\bgifts?\b|\bwreaths?\b|"
            r"\btrain\b|\bsleigh\b|\bcandy\s*canes?\b|\bpenguins?\b|\bbears?\b|\bsigns?\b|"
            r"\bnutcrackers?\b|\bangels?\b|\bnativity\b|\belf\b|\bsanta\b|\bdecor\b|"
            r"\binflatable\b|\blanterns?\b|\bbows?\b"
        ),
        "decor",
    ),
)
# Members of a face figure may carry these hints and still be face parts.
_FACE_PART_HINTS = frozenset({None, "singing_face", "outline"})

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
    row_size: int | None = None
    figure: tuple[str, ...] = field(default_factory=tuple)
    review_notes: tuple[str, ...] = field(default_factory=tuple)
    # Identifies the row this prop belongs to; two rows of the same size are distinct.
    row_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Geometry:
    center_x: float
    center_y: float
    width: float
    height: float
    closed: bool
    arc_like: bool

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (
            self.center_x - self.width / 2, self.center_y - self.height / 2,
            self.center_x + self.width / 2, self.center_y + self.height / 2,
        )


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        raise ClassificationError(f"Preview contains a non-finite numeric value: {value!r}")
    return parsed


def _geometry(prop: ET.Element) -> _Geometry | None:
    shape = prop.find("shape")
    if shape is None:
        return None
    offset_x, offset_y = _float(shape.get("OffsetX")), _float(shape.get("OffsetY"))
    scale_x, scale_y = _float(shape.get("ScaleX")), _float(shape.get("ScaleY"))
    if offset_x is not None and offset_y is not None and scale_x is not None and scale_y is not None:
        return _Geometry(offset_x, offset_y, abs(scale_x), abs(scale_y), False, False)
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
        (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, width, height, closed, arc_like
    )


def prop_center(prop: ET.Element) -> tuple[float, float] | None:
    """Center of a prop in preview space (y increases upward), when its shape has one."""
    geometry = _geometry(prop)
    return None if geometry is None else (geometry.center_x, geometry.center_y)


def _channel_entries(prop: ET.Element) -> list[list[str]]:
    value = prop.get("ChannelGrid", "")
    # Preserve empty slots: dropping one shifts every subsequent physical index.
    return [entry.split(",") for entry in value.split(";")] if value else []


def _shape_name(prop: ET.Element) -> str:
    shape = prop.find("shape")
    return shape.get("ShapeName", "") if shape is not None else ""


def _is_specific_shape(shape_name: str) -> bool:
    return shape_name.lower().startswith(_SPECIFIC_SHAPES)


def _normalized_name(name: str) -> str:
    spaced = re.sub(r"[_\-.]+", " ", name.lower())
    return re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", spaced)


def _name_hint(name: str) -> str | None:
    normalized = _normalized_name(name)
    for pattern, role in _NAME_HINTS:
        if re.search(pattern, normalized):
            return role
    return None


def _color_capability(prop: ET.Element) -> ColorCapability:
    traditional = prop.get("TraditionalType", "")
    device = prop.get("DeviceType", "")
    listed = tuple(c.strip() for c in prop.get("TraditionalColors", "").split(",") if c.strip())
    entries = _channel_entries(prop)
    # Keep one slot per physical channel. Filtering blank color fields shifts
    # later colors onto the wrong channel (for example, blank, Red, Green).
    entry_colors = tuple(entry[5].strip() if len(entry) > 5 else "" for entry in entries)
    has_entry_colors = any(entry_colors)
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
        colors = entry_colors if has_entry_colors else listed
        return ColorCapability(
            "color_per_channel", colors, True, "Each color has its own channel and can be shown alone"
        )
    return ColorCapability(
        "unknown", listed, False, f"TraditionalType {traditional or '(missing)'} is not recognized"
    )


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
    elif geometry is not None:
        if geometry.arc_like:
            evidence.append(Evidence("arch", 0.5, "Drawn as a single raised arc"))
        if geometry.closed and traditional == "Channel_per_color" and channels in (3, 4):
            evidence.append(Evidence(
                "singing_face", 0.55,
                f"Closed outline with {channels} independently colored channels "
                "(outline and mouth positions)",
            ))
        elif geometry.closed:
            evidence.append(Evidence("outline", 0.35, "Closed outline shape"))
        if geometry.width > 0.3 and geometry.height < 0.08 * geometry.width:
            evidence.append(Evidence("outline", 0.45, "Long, flat horizontal run"))
    return evidence


def _overlap(a: _Geometry, b: _Geometry) -> float:
    ax0, ay0, ax1, ay1 = a.box
    bx0, by0, bx1, by1 = b.box
    width = min(ax1, bx1) - max(ax0, bx0)
    height = min(ay1, by1) - max(ay0, by0)
    if width <= 0 or height <= 0:
        return 0.0
    smaller = max(min(a.width * a.height, b.width * b.height), 1e-12)
    return width * height / smaller


def _figures(props: list[ET.Element], geometries: dict[str, _Geometry | None]) -> dict[str, list[str]]:
    """Group overlapping small props using a bounded spatial index.

    The grid avoids comparing props that are too far apart to overlap. A hard
    comparison budget also bounds pathological previews where many props occupy
    the same tiny area.
    """
    candidates = [
        p.get("id", "") for p in props
        if (g := geometries[p.get("id", "")]) is not None
        and g.width <= _FIGURE_MAX_SIZE and g.height <= _FIGURE_MAX_SIZE
        and g.width * g.height > 0
    ]
    parent = {pid: pid for pid in candidates}

    def find(pid: str) -> str:
        while parent[pid] != pid:
            parent[pid] = parent[parent[pid]]
            pid = parent[pid]
        return pid

    cell_size = _FIGURE_MAX_SIZE
    buckets: dict[tuple[int, int], list[str]] = {}
    comparisons = 0
    max_comparisons = 2_000_000
    for pid in candidates:
        geometry = geometries[pid]
        assert geometry is not None
        cell = (math.floor(geometry.center_x / cell_size), math.floor(geometry.center_y / cell_size))
        nearby: list[str] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nearby.extend(buckets.get((cell[0] + dx, cell[1] + dy), ()))
        comparisons += len(nearby)
        if comparisons > max_comparisons:
            raise ClassificationError(
                "Preview contains too many overlapping small props to classify safely; "
                "separate dense overlapping geometry and retry"
            )
        for other in nearby:
            other_geometry = geometries[other]
            assert other_geometry is not None
            if _overlap(geometry, other_geometry) >= _FIGURE_OVERLAP:
                parent[find(pid)] = find(other)
        buckets.setdefault(cell, []).append(pid)

    clusters: dict[str, list[str]] = {}
    for pid in candidates:
        clusters.setdefault(find(pid), []).append(pid)
    return {pid: members for members in clusters.values() if len(members) >= 2 for pid in members}


def _validated_prop_links(props: list[ET.Element]) -> dict[str, str | None]:
    """Validate stable identities and direct master links before classification."""
    by_id: dict[str, ET.Element] = {}
    for prop in props:
        prop_id = prop.get("id", "")
        if not prop_id.strip():
            raise ClassificationError("Preview contains a prop with a missing or blank id")
        if prop_id in by_id:
            raise ClassificationError(f"Preview contains duplicate prop id {prop_id!r}")
        by_id[prop_id] = prop

    links: dict[str, str | None] = {}
    for prop_id, prop in by_id.items():
        master_id = prop.get("MasterPropId", "").strip() or None
        links[prop_id] = master_id
        if master_id is None:
            continue
        if master_id == prop_id:
            raise ClassificationError(f"Prop {prop_id!r} cannot reference itself as its master")
        master = by_id.get(master_id)
        if master is None:
            raise ClassificationError(
                f"Prop {prop_id!r} references missing master prop {master_id!r}"
            )
        if master.get("MasterPropId", "").strip():
            raise ClassificationError(
                f"Prop {prop_id!r} references linked master {master_id!r}; "
                "master chains and cycles are not supported"
            )
        problem = channel_layout_problem(master)
        if problem is not None:
            raise ClassificationError(
                f"Prop {prop_id!r} references master {master_id!r} without a verified "
                f"native channel layout: {problem}"
            )
    return links


def _rows(
    props: list[ET.Element], geometries: dict[str, _Geometry | None], preview: ET.Element,
    figures: dict[str, list[str]],
) -> dict[str, tuple[str, str, int, int]]:
    """Rows come from the user's groups first, then from look-alike props side by side.

    Values are (row key, group name, position, size). Parts drawn on top of each other
    (a face's mouth shapes) are never a row: row members must stand side by side. A
    prop that merely overlaps something else (an arch with a train drawn in front of
    it) can still belong to the row of its look-alikes.
    """
    rows: dict[str, tuple[str, str, int, int]] = {}
    for group in preview.findall("PropGroup"):
        members = [m.get("id", "") for m in group.findall("member") if m.get("id")]
        key = f"group:{group.get('id', '')}"
        for index, member in enumerate(members, start=1):
            rows.setdefault(member, (key, group.get("Name", ""), index, len(members)))
    by_signature: dict[tuple[str, int, str], list[str]] = {}
    for prop in props:
        pid = prop.get("id", "")
        if pid in rows or prop.get("MasterPropId", "").strip() or geometries[pid] is None:
            continue
        signature = (_shape_name(prop), len(_channel_entries(prop)), prop.get("TraditionalType", ""))
        by_signature.setdefault(signature, []).append(pid)
    row_comparisons = 0
    max_row_comparisons = 2_000_000
    for members in by_signature.values():
        remaining = sorted(members, key=lambda pid: geometries[pid].center_y)  # type: ignore[union-attr]
        while remaining:
            seed = geometries[remaining[0]]
            assert seed is not None
            row = [remaining[0]]
            for pid in remaining[1:]:
                row_comparisons += 1
                if row_comparisons > max_row_comparisons:
                    raise ClassificationError(
                        "Preview contains too many similar props to infer rows safely; "
                        "use explicit S6 groups or simplify the preview"
                    )
                g = geometries[pid]
                assert g is not None
                similar_size = all(
                    0.6 <= (x + 1e-9) / (y + 1e-9) <= 1.67
                    for x, y in ((g.width, seed.width), (g.height, seed.height))
                )
                level = abs(g.center_y - seed.center_y) <= max(0.04, 0.6 * seed.height)
                beside = all(
                    abs(g.center_x - other.center_x) >= 0.5 * min(g.width, other.width)
                    for other in (geometries[m] for m in row) if other is not None
                )
                if similar_size and level and beside:
                    row.append(pid)
            row_set = set(row)
            remaining = [pid for pid in remaining if pid not in row_set]
            if len(row) >= 3:
                ordered = sorted(row, key=lambda pid: geometries[pid].center_x)  # type: ignore[union-attr]
                key = f"auto:{ordered[0]}"
                for index, pid in enumerate(ordered, start=1):
                    rows[pid] = (key, "", index, len(ordered))
    return rows


def classify_preview(preview: ET.Element) -> tuple[PropClassification, ...]:
    """Classify every prop in a parsed ``PreviewClass`` element."""
    if preview.tag != "PreviewClass":
        raise ClassificationError("Preview root element must be <PreviewClass>")
    props = preview.findall("PropClass")
    if not props:
        raise ClassificationError("Preview contains zero PropClass entries")
    masters = _validated_prop_links(props)
    by_id = {p.get("id", ""): p for p in props}
    geometries = {p.get("id", ""): _geometry(p) for p in props}
    figures = _figures(props, geometries)
    rows = _rows(props, geometries, preview, figures)
    hints = {p.get("id", ""): _name_hint(p.get("Name", "")) for p in props}

    # A figure is a singing face when any part is clearly a face part.
    face_figures: set[str] = set()
    for pid, members in figures.items():
        if any(hints[m] == "singing_face" for m in members):
            face_figures.add(pid)

    results: list[PropClassification] = []
    for prop in props:
        prop_id = prop.get("id", "")
        name = prop.get("Name", "")
        shape_name = _shape_name(prop)
        specific = _is_specific_shape(shape_name)
        channels = len(_channel_entries(prop))
        parm1_value = _float(prop.get("Parm1"))
        parm1 = int(parm1_value) if parm1_value is not None else None
        traditional = prop.get("TraditionalType", "")
        geometry = geometries[prop_id]
        master = masters[prop_id]
        notes: list[str] = []

        evidence = _shape_evidence(shape_name, channels, parm1, geometry, traditional)
        row = rows.get(prop_id)
        if row is not None and row[3] >= 3:
            shared = f"one of {row[3]} matching props" + (
                f" in group {row[1]!r}" if row[1] else " side by side"
            )
            leading = max(evidence, key=lambda e: e.weight, default=None)
            if leading is not None and leading.role in {"arch", "mini_tree"}:
                evidence.append(Evidence(leading.role, 0.15, f"Repeated: {shared}"))

        figure_members = figures.get(prop_id, [])
        if prop_id in face_figures and hints[prop_id] in _FACE_PART_HINTS:
            parts = ", ".join(repr(by_id[m].get("Name", "")) for m in figure_members if m != prop_id)
            evidence.append(Evidence(
                "singing_face", FIGURE_WEIGHT, f"Drawn as one figure with face parts {parts}"
            ))

        hint = hints[prop_id]
        structural: dict[str, float] = {}
        for item in evidence:
            if item.role != "unknown":
                structural[item.role] = structural.get(item.role, 0.0) + item.weight
        overruled = any(
            role_name != hint and weight >= STRUCTURE_OVERRULES_NAME
            for role_name, weight in structural.items()
        )
        if hint is not None:
            if specific or overruled:
                evidence.append(Evidence(
                    hint, NAME_TIEBREAK_WEIGHT, f"Name {name!r} suggests {hint.replace('_', ' ')}"
                ))
            else:
                evidence.append(Evidence(
                    hint, NAME_DECIDES_WEIGHT,
                    f"Name {name!r} suggests {hint.replace('_', ' ')} "
                    "(shape type is generic, so the name decides)",
                ))
        if master is not None and master in by_id:
            evidence.append(Evidence(
                "unknown", 0.0,
                f"Linked to master prop {by_id[master].get('Name', '')!r}; "
                "driven by the master's channels",
            ))

        totals: dict[str, float] = {}
        for item in evidence:
            if item.role != "unknown":
                totals[item.role] = totals.get(item.role, 0.0) + item.weight
        role, score = ("unknown", 0.0)
        if totals:
            role, score = max(totals.items(), key=lambda pair: pair[1])
        close = [r for r, v in totals.items() if r != role and v >= score - 0.15]
        if close:
            notes.append(
                "Close call between "
                + " and ".join(r.replace("_", " ") for r in [role, *close])
            )
        from_name = any(
            e.reason.startswith("Name ") for e in evidence if e.role == role
        ) and sum(
            e.weight for e in evidence if e.role == role and not e.reason.startswith("Name ")
        ) < ASSIGN
        if score < ASSIGN:
            if role != "unknown":
                label = role.replace("_", " ")
                article = "an" if label[0] in "aeiou" else "a"
                notes.append(f"Evidence too weak to call it {article} {label}")
            role = "unknown"
        elif from_name:
            notes.append("Identified from its name; the shape type does not say what it is")
        confidence = round(min(1.0, score), 2)

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
            if capability.kind not in {"unsupported", "unknown"}:
                notes.append(f"Cannot be sequenced yet: {support_problem}")

        start = prop.get("StartLocation", "")
        directional = channels > 1 and role in DIRECTIONAL_ROLES
        direction = _START_DIRECTION.get(start, "unknown") if directional else "not applicable"
        if directional and direction == "unknown" and role != "unknown":
            notes.append("Direction unknown: no string start location in the preview")

        if role == "unknown":
            status = "unknown"
        elif confidence >= CONFIDENT and not from_name and not close and support_problem is None and (
            capability.kind not in {"unsupported", "unknown"}
        ):
            status = "confident"
        else:
            status = "review"

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
            segment_order="channel order as listed in the preview" if channels > 1 else "single channel",
            linked_to=master,
            group=(row[1] or None) if row is not None and row[0].startswith("group:") else None,
            position_in_row=None,
            figure=tuple(by_id[m].get("Name", "") for m in figure_members if m != prop_id),
            review_notes=tuple(notes),
        ))
    return _finish(tuple(results), rows, figures, geometries)


def _finish(
    results: tuple[PropClassification, ...],
    rows: dict[str, tuple[str, str, int, int]],
    figures: dict[str, list[str]],
    geometries: dict[str, _Geometry | None],
) -> tuple[PropClassification, ...]:
    """Apply conclusions that depend on other props' roles."""
    by_id = {r.prop_id: r for r in results}

    # A linked part drawn on a face is part of that face, whatever its name says.
    for result in results:
        master = by_id.get(result.linked_to or "")
        if (
            master is not None and master.role == "singing_face"
            and result.prop_id in figures and master.prop_id in figures[result.prop_id]
            and result.role != "singing_face"
        ):
            by_id[result.prop_id] = dataclasses.replace(
                result,
                role="singing_face",
                confidence=master.confidence,
                status="review" if master.status != "confident" else "confident",
                evidence=(*result.evidence, Evidence(
                    "singing_face", FIGURE_WEIGHT,
                    f"Linked to face part {master.name!r} and drawn on it",
                )),
                review_notes=tuple(
                    n for n in result.review_notes if not n.startswith("Identified from its name")
                ),
            )

    # A row only counts when its members turn out to be the same kind of prop.
    members_by_row: dict[tuple[str, str], list[str]] = {}
    for prop_id, (key, _, _, _) in rows.items():
        if prop_id in by_id:
            members_by_row.setdefault((key, by_id[prop_id].role), []).append(prop_id)
    for (key, role), members in members_by_row.items():
        user_group = key.startswith("group:")
        if role == "unknown" or (len(members) < 3 and not user_group):
            continue
        if user_group:
            members.sort(key=lambda pid: rows[pid][2])
        else:
            members.sort(key=lambda pid: geometries[pid].center_x)  # type: ignore[union-attr]
        for index, prop_id in enumerate(members, start=1):
            by_id[prop_id] = dataclasses.replace(
                by_id[prop_id], position_in_row=index, row_size=len(members),
                row_id=f"{key}/{role}",
            )
    return tuple(by_id[r.prop_id] for r in results)


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
                "row_size": c.row_size,
                "figure": list(c.figure),
                "review_notes": list(c.review_notes),
            }
            for c in classifications
        ],
    }
