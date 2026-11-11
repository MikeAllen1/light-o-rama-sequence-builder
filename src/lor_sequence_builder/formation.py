"""How a set of look-alike props is laid out in the preview, so motion can follow it.

Nothing here knows about any particular yard. Given the props of one kind (all
the snowflakes, say), it reads their positions from the preview and finds the
formation a person would see:

- ``columns``: props stacked one above another (falling snowflakes, a strand of
  hanging stars). Motion runs down each column, top to bottom.
- ``rows``: props side by side at one height (snowflakes along a porch). Motion
  runs across each row.
- ``clusters``: small groups standing close together (a few snowflakes on each
  window). Motion ripples through each group, left to right.
- ``scatter``: props spread around with no clear lines. Motion sweeps across them
  left to right.
- ``single``: one prop on its own.

Each line comes back in the order motion should visit it. Props that do not fit
the formation are returned as ``loose`` (they glitter rather than move).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from lor_sequence_builder.rules.engine import Display, DisplayProp

# Props whose positions differ by less than this share of the typical spacing
# between neighbors are lined up (same column, or same row).
ALIGN = 0.35
# A formation must account for at least this share of the props.
COVERAGE = 0.6
# Neighbors closer than this many typical spacings belong to one cluster.
CLUSTER_REACH = 1.6


@dataclass(frozen=True, slots=True)
class Formation:
    kind: str
    lines: tuple[tuple[str, ...], ...]
    loose: tuple[str, ...]
    # Movement for the lines: ("fall", "top_to_bottom") or ("chase", "left_to_right").
    movement: tuple[str, str]


def _center(prop: DisplayProp) -> tuple[float, float]:
    assert prop.center is not None
    return prop.center

CLUSTER_COMPARISON_BUDGET = 2_000_000


@dataclass(slots=True)
class _KDNode:
    index: int
    left: _KDNode | None = None
    right: _KDNode | None = None
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _nearest_distances(points: list[tuple[float, float]]) -> list[float]:
    """Exact nearest-neighbor distances using a bounding-box KD tree."""
    if len(points) < 2:
        return [math.inf] * len(points)
    duplicates: dict[tuple[float, float], list[int]] = {}
    for index, point in enumerate(points):
        duplicates.setdefault(point, []).append(index)
    nearest = [math.inf] * len(points)
    for indices in duplicates.values():
        if len(indices) > 1:
            for index in indices:
                nearest[index] = 0.0

    def build(indices: list[int], depth: int = 0) -> _KDNode | None:
        if not indices:
            return None
        axis = depth % 2
        indices.sort(key=lambda index: points[index][axis])
        middle = len(indices) // 2
        node = _KDNode(indices[middle])
        node.left = build(indices[:middle], depth + 1)
        node.right = build(indices[middle + 1:], depth + 1)
        x, y = points[node.index]
        boxes = [child.bounds for child in (node.left, node.right) if child is not None]
        node.bounds = (
            min([x, *(box[0] for box in boxes)]),
            min([y, *(box[1] for box in boxes)]),
            max([x, *(box[2] for box in boxes)]),
            max([y, *(box[3] for box in boxes)]),
        )
        return node

    root = build(list(range(len(points))))
    if root is None:
        return nearest

    def box_distance(point: tuple[float, float],
                     bounds: tuple[float, float, float, float]) -> float:
        x, y = point
        dx = max(bounds[0] - x, 0.0, x - bounds[2])
        dy = max(bounds[1] - y, 0.0, y - bounds[3])
        return math.hypot(dx, dy)

    for target, point in enumerate(points):
        if nearest[target] == 0.0:
            continue
        best = math.inf

        def visit(
            node: _KDNode | None,
            target_index: int = target,
            target_point: tuple[float, float] = point,
        ) -> None:
            nonlocal best
            if node is None or box_distance(target_point, node.bounds) >= best:
                return
            if node.index != target_index:
                best = min(best, math.dist(target_point, points[node.index]))
            children = [child for child in (node.left, node.right) if child is not None]
            children.sort(key=lambda child: box_distance(target_point, child.bounds))
            for child in children:
                visit(child)

        visit(root)
        nearest[target] = best
    return nearest


def _cluster_groups(props: list[DisplayProp], spacing: float) -> list[list[DisplayProp]] | None:
    """Connected components via spatial hashing; stop at a fixed comparison budget."""
    parent = list(range(len(props)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[a] = b

    reach = CLUSTER_REACH * spacing
    cell_size = max(reach, 1e-9)
    buckets: dict[tuple[int, int], list[int]] = {}
    comparisons = 0
    for index, prop in enumerate(props):
        x, y = _center(prop)
        cell = (math.floor(x / cell_size), math.floor(y / cell_size))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((cell[0] + dx, cell[1] + dy), ()):
                    comparisons += 1
                    if comparisons > CLUSTER_COMPARISON_BUDGET:
                        return None
                    if math.dist((x, y), _center(props[other])) <= reach:
                        union(index, other)
        buckets.setdefault(cell, []).append(index)

    groups: dict[int, list[DisplayProp]] = {}
    for index, prop in enumerate(props):
        groups.setdefault(find(index), []).append(prop)
    return list(groups.values())


def _bands(props: list[DisplayProp], axis: int, gap: float) -> list[list[DisplayProp]]:
    """Split props into bands whose coordinate on ``axis`` stays within ``gap`` steps."""
    ordered = sorted(props, key=lambda p: _center(p)[axis])
    bands: list[list[DisplayProp]] = [[ordered[0]]]
    for prop in ordered[1:]:
        if _center(prop)[axis] - _center(bands[-1][-1])[axis] <= gap:
            bands[-1].append(prop)
        else:
            bands.append([prop])
    return bands


def _spread(values: list[float], gap: float) -> bool:
    """Whether consecutive values are clearly apart (not stacked on one spot)."""
    return all(b - a >= 0.5 * gap for a, b in itertools.pairwise(sorted(values)))


def formation(display: Display, prop_ids: set[str] | list[str],
              prefer: str = "columns") -> Formation:
    """Read the formation of these props. ``prefer`` breaks a tie between columns and
    rows (a grid): "columns" for things that fall, "rows" for things that chase."""
    props = [display.props[pid] for pid in prop_ids
             if pid in display.props and display.props[pid].center is not None]
    unplaced = tuple(sorted(pid for pid in prop_ids
                            if pid in display.props and display.props[pid].center is None))
    if not props:
        return Formation("single", (), unplaced, ("chase", "left_to_right"))
    if len(props) == 1:
        return Formation("single", (), (props[0].prop_id, *unplaced), ("chase", "left_to_right"))

    nearest = sorted(_nearest_distances([_center(prop) for prop in props]))
    spacing = nearest[len(nearest) // 2] or 1e-6
    gap = ALIGN * spacing

    columns = [sorted(band, key=lambda p: -_center(p)[1]) for band in _bands(props, 0, gap)
               if len(band) >= 2 and _spread([_center(p)[1] for p in band], gap)]
    rows = [sorted(band, key=lambda p: _center(p)[0]) for band in _bands(props, 1, gap)
            if len(band) >= 3 and _spread([_center(p)[0] for p in band], gap)]
    in_columns = sum(len(c) for c in columns) / len(props)
    in_rows = sum(len(r) for r in rows) / len(props)

    def build(kind: str, lines: list[list[DisplayProp]], movement: tuple[str, str]) -> Formation:
        used = {p.prop_id for line in lines for p in line}
        lines = sorted(lines, key=lambda line: sum(_center(p)[0] for p in line) / len(line))
        loose = tuple(sorted(p.prop_id for p in props if p.prop_id not in used)) + unplaced
        return Formation(kind, tuple(tuple(p.prop_id for p in line) for line in lines),
                         loose, movement)

    column_ok = in_columns >= COVERAGE
    row_ok = in_rows >= COVERAGE
    if column_ok and (not row_ok or prefer == "columns" or in_columns > in_rows):
        return build("columns", columns, ("fall", "top_to_bottom"))
    if row_ok:
        return build("rows", rows, ("chase", "left_to_right"))

    # Clusters: spatial hashing avoids comparing every prop with every other prop.
    groups = _cluster_groups(props, spacing)
    if groups is None:
        return build("scatter", [], ("chase", "left_to_right"))
    clusters = [sorted(g, key=lambda p: _center(p)[0]) for g in groups
                if len(g) >= 2 and _spread([_center(p)[0] for p in g], gap)]
    in_clusters = sum(len(c) for c in clusters) / len(props)
    if len(clusters) >= 2 and in_clusters >= COVERAGE:
        return build("clusters", clusters, ("chase", "left_to_right"))
    # No clear lines: sweep across all of them, left to right.
    xs = [_center(p)[0] for p in props]
    if _spread(xs, gap):
        return build("scatter", [sorted(props, key=lambda p: _center(p)[0])],
                     ("chase", "left_to_right"))
    return build("scatter", [], ("chase", "left_to_right"))
