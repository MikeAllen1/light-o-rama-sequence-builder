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

    nearest = sorted(min(math.dist(_center(a), _center(b)) for b in props if b is not a)
                     for a in props)
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

    # Clusters: neighbors within reach of each other, joined into groups.
    parent = list(range(len(props)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in itertools.combinations(range(len(props)), 2):
        if math.dist(_center(props[i]), _center(props[j])) <= CLUSTER_REACH * spacing:
            parent[find(i)] = find(j)
    groups: dict[int, list[DisplayProp]] = {}
    for i, prop in enumerate(props):
        groups.setdefault(find(i), []).append(prop)
    clusters = [sorted(g, key=lambda p: _center(p)[0]) for g in groups.values()
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
