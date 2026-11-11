"""Wholly fictional S6 display previews with known classifications.

Coordinates follow S6's preview space: roughly -1..1, with y increasing upward.
Every name, id, and controller address is invented.
"""

from __future__ import annotations

import math
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass

_NAMESPACE = uuid.UUID("2b7c9d10-0000-4000-8000-0000000c1a55")


def _id(display: str, name: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{display}/{name}"))


@dataclass
class DisplayBuilder:
    name: str

    def __post_init__(self) -> None:
        self.root = ET.Element("PreviewClass", {
            "id": _id(self.name, "preview"), "Name": self.name, "Revision": "1",
            "EmbedBackgrounds": "False", "LastSelectedSceneId": _id(self.name, "scene"),
            "Brightness": "5",
        })
        ET.SubElement(self.root, "Scene", {
            "id": _id(self.name, "scene"), "Name": "Scene 1", "HScroll": "0", "VScroll": "0",
            "Zoom": "2", "CreateGridView": "False", "BackgroundFile": "",
        })
        self.expected: dict[str, str] = {}
        self._next_circuit: dict[str, int] = {}

    def prop_id(self, name: str) -> str:
        return _id(self.name, name)

    def add(
        self,
        name: str,
        expected_role: str,
        *,
        shape: str,
        channels: int = 1,
        traditional: str = "Single Color",
        colors: Sequence[str] = ("Red",),
        unit: str = "20",
        points: Sequence[tuple[float, float]] = (),
        box: tuple[float, float, float, float] | None = None,
        parm1: int | None = None,
        start: str = "n/a",
        master: str | None = None,
        device: str = "LOR",
        string_type: str = "Traditional",
    ) -> str:
        first = self._next_circuit.get(unit, 1)
        self._next_circuit[unit] = first + channels
        if traditional == "Channel_per_color":
            entry_colors = list(colors) + ["White"] * channels
        else:
            entry_colors = ["Multi" if traditional == "Multicolor_string_1_ch" else colors[0]] * channels
        grid = ";".join(
            f"Regular,{unit},{first + i},{first + i},0,{entry_colors[i]}" for i in range(channels)
        )
        prop = ET.SubElement(self.root, "PropClass", {
            "id": self.prop_id(name), "BulbShape": "Square", "ChannelGrid": grid, "Comment": "",
            "CustomBulbColor": "FFFFFFFF", "DeviceType": device, "DimmingCurveName": "None",
            "IndividualChannels": "True" if channels > 1 else "False",
            "LegacySequenceMethod": "",
            "MaxChannels": "512" if traditional == "Channel_per_color" else "16",
            "Opacity": "255", "MasterDimmable": "True", "PreviewBulbSize": "2",
            "RgbOrder": "RGB order", "MasterPropId": self.prop_id(master) if master else "",
            "SeparateIds": "False", "StartLocation": start, "StringType": string_type,
            "TraditionalColors": ",".join(colors), "TraditionalType": traditional,
            "EffectBulbSize": "1", "Tag": "", "Name": name,
            "Parm1": str(parm1 if parm1 is not None else max(1, len(points) - 1 or channels)),
            "Parm2": "50",
        })
        element = ET.SubElement(prop, "shape", {"ShapeName": shape})
        if box is not None:
            x, y, w, h = box
            element.attrib.update({
                "OffsetX": str(x), "OffsetY": str(y), "ScaleX": str(w), "ScaleY": str(h),
                "Radians": "0",
            })
        for px, py in points:
            ET.SubElement(element, "point", {"x": f"{px:.4f}", "y": f"{py:.4f}"})
        self.expected[self.prop_id(name)] = expected_role
        return self.prop_id(name)

    def group(self, name: str, members: Sequence[str]) -> None:
        group = ET.SubElement(self.root, "PropGroup", {
            "id": _id(self.name, f"group/{name}"), "Name": name, "Arrangement": "Preview",
        })
        for member in members:
            ET.SubElement(group, "member", {
                "id": self.prop_id(member), "orientation": "normal", "top": "0", "left": "0",
            })

    def element(self) -> ET.Element:
        if self.root.find("PropViews") is None:
            ET.SubElement(self.root, "PropViews")
        return self.root


def _arc(cx: float, base: float, width: float, height: float, n: int = 13) -> list[tuple[float, float]]:
    return [(cx - width / 2 + width * i / (n - 1), base + height * math.sin(math.pi * i / (n - 1)))
            for i in range(n)]


def _loop(cx: float, cy: float, r: float, n: int = 16) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n + 1)]


def classic_yard() -> DisplayBuilder:
    """Arches, mini trees, a mega tree with a linked star, and a singing face."""
    d = DisplayBuilder("Fictional Classic Yard")
    arches = [f"Arch {i}" for i in range(1, 5)]
    for i, name in enumerate(arches):
        d.add(name, "arch", shape="Arch", channels=1, box=(-0.8 + 0.2 * i, -0.3, 0.08, 0.07),
              start="Left")
    d.group("Arches", arches)
    for i in range(4):
        d.add(f"Mini Tree {i + 1}", "mini_tree", shape="Tree 180", channels=1,
              traditional="Multicolor_string_1_ch", colors=("Red", "Green"),
              box=(-0.7 + 0.15 * i, -0.15, 0.03, 0.06), parm1=1)
    d.add("Mega Tree", "mega_tree", shape="Tree 180", channels=16,
          traditional="Multicolor_string_1_ch", colors=("Red", "White"), unit="21",
          box=(0.4, -0.05, 0.17, 0.4), parm1=16, start="Bottom Left")
    d.add("Tree Topper", "star", shape="Star", channels=1, box=(0.4, 0.38, 0.05, 0.06),
          master="Mega Tree", unit="21")
    d.add("Santa", "singing_face", shape="Lines-Connected", channels=3,
          traditional="Channel_per_color", colors=("White", "Red", "Green"), unit="22",
          points=_loop(0.8, -0.1, 0.08))
    return d


def roofline_house() -> DisplayBuilder:
    """A roofline-heavy display: long outlines, icicles, and windows."""
    d = DisplayBuilder("Fictional Roofline House")
    d.add("Upper Roof", "outline", shape="Lines-Connected", channels=2, colors=("White",),
          points=[(-0.8, 0.45), (0.0, 0.47), (0.8, 0.45)], start="Left")
    d.add("Lower Gutter", "outline", shape="Lines-Connected", channels=2, colors=("White",),
          points=[(-0.9, 0.1), (0.9, 0.11)], start="Left")
    d.add("Front Icicles", "icicles", shape="Icicles", channels=4, colors=("Blue",),
          points=[(-0.8, 0.09), (0.8, 0.09), (0.8, 0.0), (-0.8, 0.0)], parm1=32, start="Left")
    for i in range(3):
        d.add(f"Window {i + 1}", "outline", shape="Lines-Connected", channels=1,
              colors=("Warm White",),
              points=[(-0.5 + 0.35 * i, 0.2), (-0.4 + 0.35 * i, 0.2), (-0.4 + 0.35 * i, 0.3),
                      (-0.5 + 0.35 * i, 0.3), (-0.5 + 0.35 * i, 0.2)])
    d.add("C9 Strand", "outline", shape="Lines-Unconnected", channels=1, colors=("Multi",),
          points=[(-0.9, -0.45), (-0.9, -0.2)])
    d.add("Big Flake", "snowflake", shape="Snowflake", channels=1, colors=("White",),
          box=(0.0, 0.6, 0.06, 0.06))
    return d


def misleading_names() -> DisplayBuilder:
    """Names that contradict the preview; the preview must win."""
    d = DisplayBuilder("Fictional Misleading Names")
    d.add("Mega Tree", "arch", shape="Arch", channels=1, box=(-0.5, -0.3, 0.08, 0.07))
    d.add("Arch 3", "star", shape="Star", channels=1, box=(0.0, 0.3, 0.05, 0.06))
    d.add("Arch 7", "arch", shape="Lines-Unconnected", channels=1,
          points=[(0.3, -0.2), (0.35, -0.1)])
    d.add("Thing 12", "mega_tree", shape="Tree 180", channels=12,
          traditional="Multicolor_string_1_ch", colors=("Red", "Green"), box=(0.5, 0.0, 0.15, 0.35),
          parm1=12)
    d.add("Prop 9", "arch", shape="Lines-Connected", channels=1, points=_arc(-0.1, -0.3, 0.2, 0.12))
    return d


def unsupported_hardware() -> DisplayBuilder:
    """Props whose channels v1 cannot drive; shapes may still be recognized."""
    d = DisplayBuilder("Fictional Unsupported Hardware")
    d.add("Pixel Arch", "arch", shape="Arch", channels=1, device="DMX", string_type="RGB",
          box=(-0.4, -0.3, 0.08, 0.07))
    d.add("Old Roof", "outline", shape="Lines-Connected", channels=1, device="AC",
          points=[(-0.8, 0.4), (0.8, 0.41)])
    d.add("Mystery Prop", "unknown", shape="Hexagon Thing", channels=2,
          traditional="Some Future Type", box=(0.5, 0.0, 0.05, 0.05))
    return d


def _box(cx: float, cy: float, w: float, h: float) -> list[tuple[float, float]]:
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2),
            (cx - w / 2, cy + h / 2)]


def line_drawn_yard() -> DisplayBuilder:
    """Most props drawn as plain lines, the way many real previews are built."""
    d = DisplayBuilder("Fictional Line-Drawn Yard")
    lines = "Lines-Unconnected"
    for i in range(6):
        d.add(f"Snowflake {i + 1}", "snowflake", shape=lines, channels=1,
              traditional="Multicolor_string_1_ch", colors=("White", "Blue"),
              points=_box(-0.8 + 0.06 * (i % 2), 0.5 - 0.12 * i, 0.04, 0.04))
    # Look-alike decor of different sizes and heights: not a row.
    d.add("Reindeer", "decor", shape=lines, channels=1, colors=("White",),
          points=_box(-0.4, -0.3, 0.12, 0.1))
    d.add("Snowman", "decor", shape=lines, channels=1, colors=("White",),
          points=_box(-0.2, -0.25, 0.06, 0.16))
    d.add("Toy Train", "decor", shape=lines, channels=1, colors=("White",),
          points=_box(0.05, -0.38, 0.22, 0.05))
    d.add("Yard Santa", "decor", shape=lines, channels=1, colors=("Red",),
          points=_box(0.45, -0.3, 0.1, 0.15))
    for i in range(3):
        d.add(f"Column {i + 1}", "outline", shape=lines, channels=1, colors=("White",),
              points=[(-0.1 + 0.2 * i, -0.1), (-0.1 + 0.2 * i, 0.3)])
    # A face built from three overlapping props plus a linked part.
    d.add("Face Outline", "singing_face", shape=lines, channels=1,
          traditional="Channel_per_color", colors=("White",), unit="23",
          points=_loop(0.75, 0.0, 0.08))
    d.add("Mouth Open", "singing_face", shape=lines, channels=1,
          traditional="Channel_per_color", colors=("Red",), unit="23",
          points=_box(0.75, -0.03, 0.06, 0.04))
    d.add("Mouth Closed", "singing_face", shape=lines, channels=1,
          traditional="Channel_per_color", colors=("Red",), unit="23",
          points=_box(0.75, -0.035, 0.06, 0.02))
    d.add("Face Eyes", "singing_face", shape=lines, channels=1,
          traditional="Channel_per_color", colors=("Blue",), unit="23",
          points=_box(0.75, 0.03, 0.06, 0.02), master="Face Outline")
    d.add("Santa Cap", "singing_face", shape=lines, channels=1,
          traditional="Channel_per_color", colors=("Red",), unit="23",
          points=_box(0.75, 0.07, 0.07, 0.03), master="Face Outline")
    d.add("Mystery Blob", "unknown", shape=lines, channels=1, colors=("White",),
          points=_box(0.2, 0.6, 0.05, 0.05))
    return d


ALL_DISPLAYS = (
    classic_yard, roofline_house, misleading_names, unsupported_hardware, line_drawn_yard,
)
