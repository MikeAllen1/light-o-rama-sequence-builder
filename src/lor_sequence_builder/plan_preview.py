"""Draw a planned show as an SVG: one lane per prop, time left to right.

This is for reviewing a plan away from S6 (on a phone, in a browser). It shows
the sections, hard stops, and every effect: bright blocks for holds and pulses,
ramps for fades, blue for twinkle and purple for shimmer. Props with several
channels get one thin row per channel, so a rotating mega tree reads as a
diagonal stripe pattern.
"""

from __future__ import annotations

from collections import defaultdict
from xml.sax.saxutils import escape

from lor_sequence_builder.choreography import seconds
from lor_sequence_builder.planner import LEVEL_NAMES, Plan
from lor_sequence_builder.rules.engine import Display

_LABEL_WIDTH = 190
_TIMELINE_WIDTH = 1400
_HEADER = 58
_ROW = 3
_MIN_LANE = 14
_GAP = 4
_ROLE_ORDER = ("star", "mega_tree", "arch", "mini_tree", "icicles", "outline", "snowflake",
               "singing_face", "decor", "unknown")
_KIND_COLOR = {"on": "#ffb627", "fade": "#ffb627", "twinkle": "#7cc4ff", "shimmer": "#c58cff"}
_SECTION_FILL = {0: "#1d2433", 1: "#25304a", 2: "#33304f"}


def plan_svg(plan: Plan, display: Display, title: str = "Planned show") -> str:
    timeline = plan.choreography
    duration = max(1, timeline.duration_centiseconds)
    used = {e.prop_id for e in timeline.effects}
    props = sorted(
        (display.props[pid] for pid in used if pid in display.props),
        key=lambda p: (
            _ROLE_ORDER.index(p.role) if p.role in _ROLE_ORDER else len(_ROLE_ORDER),
            p.center[0] if p.center else 0.0,
            p.name,
        ),
    )

    def x(time: int) -> float:
        return _LABEL_WIDTH + _TIMELINE_WIDTH * time / duration

    lanes: dict[str, tuple[float, float]] = {}
    y = float(_HEADER)
    for prop in props:
        height = float(max(_MIN_LANE, prop.channel_count * _ROW))
        lanes[prop.prop_id] = (y, height)
        y += height + _GAP
    total_height = y + 30
    width = _LABEL_WIDTH + _TIMELINE_WIDTH + 20

    parts = [
        (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_height:.0f}" '
        f'width="{width}" height="{total_height:.0f}" font-family="system-ui, sans-serif" '
        'font-size="11">'),
        f"<title>{escape(title)}</title>",
        f'<rect width="{width}" height="{total_height:.0f}" fill="#11151f"/>',
        (f'<text x="12" y="20" fill="#e8ecf4" font-size="15" font-weight="600">'
        f"{escape(title)}</text>"),
    ]
    for section in plan.sections:
        x1, x2 = x(section.start_centisecond), x(section.end_centisecond)
        parts.append(
            f'<rect x="{x1:.1f}" y="30" width="{x2 - x1:.1f}" height="{total_height - 52:.0f}" '
            f'fill="{_SECTION_FILL[section.level]}"/>'
        )
        parts.append(
            f'<text x="{x1 + 4:.1f}" y="44" fill="#c9d2e3">{escape(section.label)} '
            f'<tspan fill="#8893a8">{LEVEL_NAMES[section.level]}</tspan></text>'
        )
    for stop in timeline.hard_stops_centiseconds:
        parts.append(f'<line x1="{x(stop):.1f}" x2="{x(stop):.1f}" y1="30" '
                     f'y2="{total_height - 22:.0f}" stroke="#ff5d5d" stroke-width="1.5"/>')

    for prop in props:
        top, height = lanes[prop.prop_id]
        parts.append(f'<text x="{_LABEL_WIDTH - 8}" y="{top + min(height, _MIN_LANE) - 3:.1f}" '
                     f'fill="#c9d2e3" text-anchor="end">{escape(prop.name)}</text>')
        parts.append(f'<rect x="{_LABEL_WIDTH}" y="{top:.1f}" width="{_TIMELINE_WIDTH}" '
                     f'height="{height:.1f}" fill="#000" fill-opacity="0.25"/>')

    by_prop: dict[str, list[str]] = defaultdict(list)
    for effect in timeline.effects:
        lane = lanes.get(effect.prop_id)
        if lane is None:
            continue
        top, height = lane
        prop = display.props[effect.prop_id]
        row = height / max(1, prop.channel_count)
        row_top = top + row * effect.channel_index
        x1, x2 = x(effect.start_centisecond), x(effect.end_centisecond)
        color = _KIND_COLOR[effect.kind]
        if effect.kind == "fade":
            bottom = row_top + row
            y1 = bottom - row * effect.start_intensity / 100
            y2 = bottom - row * effect.end_intensity / 100
            by_prop[effect.prop_id].append(
                f'<polygon points="{x1:.1f},{bottom:.1f} {x1:.1f},{y1:.1f} {x2:.1f},{y2:.1f} '
                f'{x2:.1f},{bottom:.1f}" fill="{color}"/>'
            )
        else:
            opacity = 0.25 + 0.75 * effect.start_intensity / 100
            by_prop[effect.prop_id].append(
                f'<rect x="{x1:.1f}" y="{row_top:.1f}" width="{max(0.6, x2 - x1):.1f}" '
                f'height="{max(1.0, row - 0.4):.1f}" fill="{color}" '
                f'fill-opacity="{opacity:.2f}"/>'
            )
    for prop in props:
        parts.append(f'<g><title>{escape(prop.name)}</title>{"".join(by_prop[prop.prop_id])}</g>')

    for tick in range(0, duration + 1, 3000):
        parts.append(f'<text x="{x(tick):.1f}" y="{total_height - 8:.0f}" fill="#8893a8" '
                     f'text-anchor="middle">{seconds(tick)[:-3]}</text>')
    legend = (("hold or pulse", "#ffb627"), ("twinkle", "#7cc4ff"), ("shimmer", "#c58cff"),
              ("hard stop", "#ff5d5d"))
    lx = _LABEL_WIDTH + _TIMELINE_WIDTH - 400
    for label, color in legend:
        parts.append(f'<rect x="{lx}" y="11" width="10" height="10" fill="{color}"/>'
                     f'<text x="{lx + 14}" y="20" fill="#c9d2e3">{label}</text>')
        lx += 100
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
