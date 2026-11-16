"""Pixel props: which props are pixels, how S6 stores their effects, and a plan for
them that follows the music and the rest of the show.

Evidence (an S6 sequence with 33 pixel props on E1.31: a mega tree, a matrix, roof
lines and snowflakes; see docs/S6_FORMAT.md, "Pixel props"):

- A pixel prop is ``StringType="RGB"`` (one ``ChannelGrid`` entry per string: type,
  universe, first channel, last channel, ...; three channels per pixel).
- Its ``SeqProp`` holds no ``channel`` but motion-effect rows: ``<track id name=
  "Effects 01"/>``, ``"Effects 02"``, with ``OverlayMotionRows="1"``.
- Each effect on a row is ``<effect startCentisecond endCentisecond intensity
  settings/>`` (or ``startIntensity``/``endIntensity`` for a fade, in percent). The
  settings are ``Mix|a|b|full|20|<left effect>|<right effect>``, each effect being
  ``name:<six palette slots>:<options>``; a slot is ``AARRGGBB,<1 when used>`` and
  the sixth slot is always black.

Only option strings copied verbatim from that evidence are written; this module
changes nothing but the palette, the times and the brightness. The planner is plain
rules (no AI, no randomness): an effect per phrase, chosen by how loud the part is
and what kind of prop it is, in the colors the rest of the show is using, dark
whenever the rest of the show is dark.
"""

from __future__ import annotations

import dataclasses
import itertools
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any

from lor_sequence_builder.choreography import Choreography
from lor_sequence_builder.rgb import COLORS, color_name, is_pixel
from lor_sequence_builder.rules import RuleSet
from lor_sequence_builder.rules.engine import Display, select_props

MIX = "Mix_Average|0|0|full|20"
_DEFAULT_SLOTS = ("FFFF0000", "FF00FF00", "FF0000FF", "FFFFFF00", "FFFFFFFF")
NONE_LAYER = "lightorama_none:" + ";".join(f"{c},0" for c in _DEFAULT_SLOTS) + ";FF000000,0:"

# Effect options exactly as S6 wrote them in the evidence, by effect.
OPTIONS: dict[str, tuple[str, str]] = {
    # key: (S6 effect name, options)
    "wash": ("lightorama_colorwash", "full,full,single_color"),
    "gradient": ("lightorama_colorwash", "full,full,horizontal_gradient"),
    "twinkle": ("lightorama_twinkle", "50,25,twinkle,random,0,255"),
    "bars": ("lightorama_bars", "H_expand,1,False,False,12,0"),
    "blend_up": ("lightorama_blendedbars", "up,10,10,0"),
    "blend_expand": ("lightorama_blendedbars", "V_expand,10,12,0"),
    "meteors_down": ("lightorama_meteors", "palette,19,35,down,0,16,pixel_rate,oscillate"),
    "meteors_up": ("lightorama_meteors", "palette,100,25,up,0,12,pixel_rate,linear2"),
    "spiral_left": ("lightorama_spirals", "2,left_to_right,100,18,0,False,none,5"),
    "spiral_right": ("lightorama_spirals", "2,left_to_right,-100,18,0,False,none,5"),
    "lines": ("lightorama_straightlines", "default,4,12,1,21"),
    "lines_across": ("lightorama_straightlines", "Left_to_Right,3,12,1,21"),
    "ripple": ("lightorama_ripple", "circle,1,25,A12A50A1.00,4,3,1,13,False,50"),
    "garland_up": ("lightorama_garland", "0,0,once_fit_to_duration,12,bottom_to_top"),
    "garland_down": ("lightorama_garland", "0,0,once_fit_to_duration,12,top_to_bottom"),
    "garland_across": ("lightorama_garland", "0,0,once_fit_to_duration,12,left_to_right"),
}

# What each kind of prop does at each energy level (low, mid, high); phrases take
# turns through the list. Lines run along a strand; the tree and matrix have area.
_TREE = (("wash", "twinkle"), ("garland_up", "spiral_left", "blend_up"),
         ("spiral_left", "spiral_right", "bars", "meteors_down"))
_LINE = (("wash", "twinkle"), ("lines_across", "blend_expand", "gradient"),
         ("meteors_down", "bars", "lines", "meteors_up"))
_FLAKE = (("wash", "twinkle"), ("ripple", "gradient", "wash"),
          ("ripple", "bars", "blend_expand", "wash"))
_MATRIX = (("wash", "twinkle"), ("blend_up", "lines_across", "ripple"),
           ("bars", "spiral_left", "meteors_down", "ripple"))
_BY_ROLE = {"mega_tree": _TREE, "mini_tree": _TREE, "snowflake": _FLAKE, "star": _FLAKE}
_BRIGHTNESS = (55, 80, 100)
FLASH = 30  # centiseconds


def pixel_count(attributes: dict[str, str]) -> int:
    """Pixels on the prop (three channels each), or 0 when the grid cannot be read."""
    total = 0
    for entry in attributes.get("ChannelGrid", "").split(";"):
        fields = entry.split(",")
        try:
            first, last = int(fields[2]), int(fields[3])
        except (IndexError, ValueError):
            continue
        if last >= first:
            total += (last - first + 1) // 3
    return total


def pixel_props(preview: ET.Element) -> list[ET.Element]:
    """The preview's pixel props that can be sequenced (not driven by a master)."""
    return [p for p in preview.findall("PropClass")
            if is_pixel(dict(p.attrib)) and not p.get("MasterPropId", "").strip()
            and p.get("id")]


def palette(colors: list[str]) -> str:
    """Six S6 palette slots with ``colors`` (up to five) switched on. Like S6, a color
    that is one of the default slots switches that slot on; another color takes the
    place of a default slot that is not used."""
    slots = list(_DEFAULT_SLOTS)
    used = [False] * len(slots)
    for name in colors[:5]:
        red, green, blue = COLORS[name]
        value = f"FF{red:02X}{green:02X}{blue:02X}"
        if value in slots and not used[slots.index(value)]:
            used[slots.index(value)] = True
            continue
        free = next(i for i in range(len(slots)) if not used[i] and slots[i] not in
                    {f"FF{COLORS[c][0]:02X}{COLORS[c][1]:02X}{COLORS[c][2]:02X}"
                     for c in colors[:5]})
        slots[free] = value
        used[free] = True
    return ";".join([*(f"{v},{int(u)}" for v, u in zip(slots, used, strict=True)),
                     "FF000000,0"])


def settings(effect: str, colors: list[str]) -> str:
    name, options = OPTIONS[effect]
    return f"{MIX}|{name}:{palette(colors)}:{options}|{NONE_LAYER}"


@dataclass(frozen=True, slots=True)
class PixelEffect:
    prop_id: str
    start_centisecond: int
    end_centisecond: int
    effect: str
    colors: tuple[str, ...]
    start_intensity: int
    end_intensity: int

    def element(self) -> ET.Element:
        attributes = {"startCentisecond": str(self.start_centisecond),
                      "endCentisecond": str(self.end_centisecond)}
        if self.start_intensity == self.end_intensity:
            attributes["intensity"] = str(self.start_intensity)
        else:
            attributes["startIntensity"] = str(self.start_intensity)
            attributes["endIntensity"] = str(self.end_intensity)
        attributes["settings"] = settings(self.effect, list(self.colors))
        return ET.Element("effect", attributes)


@dataclass(frozen=True, slots=True)
class PixelPlan:
    effects: tuple[PixelEffect, ...]
    prop_ids: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]  # (name, reason)
    notes: tuple[str, ...]


def _lit_spans(choreography: Choreography, bridge: int = 60) -> list[tuple[int, int]]:
    """When the rest of the show has anything lit (gaps under ``bridge`` closed)."""
    spans = sorted((e.start_centisecond, e.end_centisecond) for e in choreography.effects
                   if max(e.start_intensity, e.end_intensity) > 0)
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1] + bridge:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def _clip(start: int, end: int, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [(max(start, a), min(end, b)) for a, b in spans if min(end, b) - max(start, a) >= 10]


def _section_colors(choreography: Choreography, start: int, end: int,
                    fallback: tuple[str, ...]) -> list[str]:
    """The colors the show's RGB props use in this part, most used first, else the
    style's palette."""
    used = Counter(color_name(e.color) for e in choreography.effects
                   if e.color and start <= e.start_centisecond < end)
    named = [c for c, _ in used.most_common() if c is not None]
    return named[:3] or [c for c in (color_name(f) for f in fallback) if c][:2] or ["white"]


def _phrases(start: int, end: int, downbeats: list[int], bars: int) -> list[tuple[int, int]]:
    marks = [d for d in downbeats if start < d < end][bars - 1::bars] if bars > 0 else []
    edges = [start, *[m for m in marks if m - start >= 100 and end - m >= 100], end]
    return list(itertools.pairwise(edges))


def plan_pixels(
    preview: ET.Element,
    display: Display,
    rule_set: RuleSet,
    choreography: Choreography,
    sections: tuple[Any, ...],
    downbeats: list[int],
    style_palette: tuple[str, ...],
    phrase_bars: int = 4,
) -> PixelPlan:
    """Pixel effects for every pixel prop the requirements allow."""
    elements = {p.get("id", ""): p for p in pixel_props(preview)}
    if not elements:
        return PixelPlan((), (), (), ())
    # The requirements name pixel props like any other prop.
    as_sequenceable = {pid: dataclasses.replace(prop, layout_problem=None)
                       for pid, prop in display.props.items() if pid in elements}
    selectable = dataclasses.replace(display, props={**display.props, **as_sequenceable})
    excluded: dict[str, str] = {}
    caps: dict[str, int] = {}
    quiet: dict[str, set[str]] = {}
    allowed: dict[str, list[str]] = {}
    for req in rule_set.requirements:
        if req.severity == "off":
            continue
        chosen, _ = select_props(selectable, req)
        for pid in (p for p in chosen if p in elements):
            if req.type == "never_use":
                excluded[pid] = f"requirement {req.requirement_id!r}: never used"
            elif req.type == "max_intensity":
                caps[pid] = min(caps.get(pid, 100), int(req.params["max"]))
            elif req.type == "quiet_during":
                quiet.setdefault(pid, set()).update(s.lower() for s in req.params["sections"])
            elif req.type == "colors_only":
                mixable = [c for c in (color_name(x) for x in req.params["colors"]) if c]
                if mixable:
                    allowed[pid] = list(dict.fromkeys(mixable))
                else:
                    excluded[pid] = f"requirement {req.requirement_id!r}: no colors to use"
    lit = _lit_spans(choreography)
    effects: list[PixelEffect] = []
    used: list[str] = []
    for pid, element in elements.items():
        if pid in excluded:
            continue
        role = display.props[pid].role if pid in display.props else ""
        matrix = "matrix" in element.get("Name", "").lower()
        choices = _MATRIX if matrix else _BY_ROLE.get(role, _LINE)
        cap = caps.get(pid, 100)
        turn = 0
        for section in sections:
            if section.label.lower() in quiet.get(pid, set()):
                continue
            colors = _section_colors(choreography, section.start_centisecond,
                                     section.end_centisecond, style_palette)
            if pid in allowed:
                colors = [c for c in colors if c in allowed[pid]] or allowed[pid][:2]
            options = choices[section.level]
            # Quiet parts hold an idea longer; loud parts change it every couple of bars.
            bars = (phrase_bars * 2, phrase_bars, max(1, phrase_bars // 2))[section.level]
            start = section.start_centisecond
            if section.level == 2 and section.end_centisecond - start > 300:
                # A loud part arrives with a short full-brightness flash.
                flash = colors[:1] if "white" not in colors else ["white"]
                for a, b in _clip(start, start + FLASH, lit):
                    effects.append(PixelEffect(pid, a, b, "wash", tuple(flash), min(cap, 100),
                                               min(cap, 100)))
                start += FLASH
            for p_start, p_end in _phrases(start, section.end_centisecond, downbeats, bars):
                effect = options[turn % len(options)]
                turn += 1
                # Single-color effects take one color; moving ones get two to play with.
                shown = colors[:1] if effect in {"wash", "twinkle"} else colors[:2]
                if effect == "wash" and len(colors) > 1:
                    shown = [colors[turn % len(colors)]]
                level = min(cap, _BRIGHTNESS[section.level])
                for a, b in _clip(p_start, p_end, lit):
                    effects.append(PixelEffect(pid, a, b, effect, tuple(shown), level, level))
        if any(e.prop_id == pid for e in effects):
            used.append(pid)
    # Ease in at the very start and out at the very end, like the rest of the show.
    by_prop: dict[str, list[int]] = {}
    for index, planned in enumerate(effects):
        by_prop.setdefault(planned.prop_id, []).append(index)
    for indexes in by_prop.values():
        first, last = effects[indexes[0]], effects[indexes[-1]]
        if first.start_centisecond == min(e.start_centisecond for e in effects):
            fade = min(100, (first.end_centisecond - first.start_centisecond) // 2)
            if fade >= 20:
                head = dataclasses.replace(first, end_centisecond=first.start_centisecond + fade,
                                           start_intensity=0)
                rest = dataclasses.replace(first, start_centisecond=first.start_centisecond + fade)
                effects[indexes[0]] = head
                effects.append(rest)
        if last.end_centisecond == max(e.end_centisecond for e in effects):
            fade = min(200, (last.end_centisecond - last.start_centisecond) // 2)
            if fade >= 20:
                body = dataclasses.replace(last, end_centisecond=last.end_centisecond - fade)
                tail = dataclasses.replace(last, start_centisecond=last.end_centisecond - fade,
                                           end_intensity=0)
                effects[indexes[-1]] = body
                effects.append(tail)
    effects.sort(key=lambda e: (e.prop_id, e.start_centisecond))
    skipped = tuple((elements[pid].get("Name", ""), reason) for pid, reason in excluded.items())
    notes = ((f"Pixel effects on {len(used)} pixel prop(s): first version, built from the "
              "format of a real S6 sequence. Check them in S6's preview before show night."),
             ) if used else ()
    return PixelPlan(tuple(effects), tuple(used), skipped, notes)
