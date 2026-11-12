"""A complete show for an invented yard and an invented song.

``lor-sequence-builder demo FOLDER`` writes a small S6 preview of a fictional
yard (a row of arches, mini trees, a mega tree, two columns of falling
snowflakes, a star and a house outline), a 48-second synthesized song with a
quiet opening, a louder middle and an ending, and then generates the show.

It proves an installation works end to end without any of the user's own
files, and gives a first look at every output: the sequence, the plan picture
and the show report. Everything in it is made up.
"""

from __future__ import annotations

import base64
import json
import math
import shutil
import tempfile
import threading
import uuid
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from lor_sequence_builder.generate import GeneratedShow, generate_show
from lor_sequence_builder.rules import load_rule_set

DEMO_NAME = "Demo Yard"
SONG_SECONDS = 48.0
SONG_BPM = 120.0
_RATE = 22_050
_NAMESPACE = uuid.UUID("6f1d2a40-0000-4000-8000-00000000de30")


def _id(name: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{DEMO_NAME}/{name}"))


class _Preview:
    def __init__(self) -> None:
        self.root = ET.Element("PreviewClass", {
            "id": _id("preview"), "Name": DEMO_NAME, "Revision": "1",
            "EmbedBackgrounds": "False", "LastSelectedSceneId": _id("scene"), "Brightness": "5",
        })
        ET.SubElement(self.root, "Scene", {
            "id": _id("scene"), "Name": "Scene 1", "HScroll": "0", "VScroll": "0", "Zoom": "2",
            "CreateGridView": "False", "BackgroundFile": "",
        })
        self.circuit: dict[str, int] = {}

    def add(self, name: str, shape: str, unit: str, *, channels: int = 1,
            colors: tuple[str, ...] = ("White",), multicolor: bool = False,
            box: tuple[float, float, float, float] | None = None,
            points: list[tuple[float, float]] | None = None, start: str = "n/a") -> None:
        first = self.circuit.get(unit, 1)
        self.circuit[unit] = first + channels
        color = "Multi" if multicolor else colors[0]
        grid = ";".join(f"Regular,{unit},{first + i},{first + i},0,{color}"
                        for i in range(channels))
        prop = ET.SubElement(self.root, "PropClass", {
            "id": _id(name), "BulbShape": "Square", "ChannelGrid": grid, "Comment": "",
            "CustomBulbColor": "FFFFFFFF", "DeviceType": "LOR", "DimmingCurveName": "None",
            "IndividualChannels": "True" if channels > 1 else "False",
            "LegacySequenceMethod": "", "MaxChannels": "16", "Opacity": "255",
            "MasterDimmable": "True", "PreviewBulbSize": "2", "RgbOrder": "RGB order",
            "MasterPropId": "", "SeparateIds": "False", "StartLocation": start,
            "StringType": "Traditional", "TraditionalColors": ",".join(colors),
            "TraditionalType": "Multicolor_string_1_ch" if multicolor else "Single Color",
            "EffectBulbSize": "1", "Tag": "", "Name": name,
            "Parm1": str(max(1, (len(points) - 1) if points else channels)), "Parm2": "50",
        })
        element = ET.SubElement(prop, "shape", {"ShapeName": shape})
        if box is not None:
            x, y, w, h = box
            element.attrib.update({"OffsetX": str(x), "OffsetY": str(y), "ScaleX": str(w),
                                   "ScaleY": str(h), "Radians": "0"})
        for px, py in points or []:
            ET.SubElement(element, "point", {"x": f"{px:.4f}", "y": f"{py:.4f}"})

    def group(self, name: str, members: list[str]) -> None:
        group = ET.SubElement(self.root, "PropGroup", {
            "id": _id(f"group/{name}"), "Name": name, "Arrangement": "Preview"})
        for member in members:
            ET.SubElement(group, "member", {"id": _id(member), "orientation": "normal",
                                            "top": "0", "left": "0"})


def demo_preview() -> ET.Element:
    """The fictional yard as an S6 ``PreviewClass``."""
    yard = _Preview()
    arches = [f"Arch {i}" for i in range(1, 6)]
    for i, name in enumerate(arches):
        yard.add(name, "Arch", "20", colors=("Red",), box=(-0.85 + 0.18 * i, -0.45, 0.08, 0.07),
                 start="Left")
    yard.group("Arches", arches)
    for i in range(4):
        yard.add(f"Mini Tree {i + 1}", "Tree 180", "21", colors=("Red", "Green"),
                 multicolor=True, box=(-0.75 + 0.15 * i, -0.25, 0.03, 0.06))
    yard.add("Mega Tree", "Tree 180", "22", channels=8, colors=("Green", "White"),
             multicolor=True, box=(0.45, -0.1, 0.17, 0.4), start="Bottom Left")
    yard.add("Tree Star", "Star", "23", colors=("Yellow",), box=(0.45, 0.33, 0.05, 0.06))
    for column, x in enumerate((-0.55, 0.05)):
        for row in range(3):
            yard.add(f"Snowflake {column * 3 + row + 1}", "Snowflake", "24",
                     box=(x, 0.55 - 0.13 * row, 0.05, 0.05))
    house = [(-0.95, 0.2), (-0.95, 0.7), (-0.5, 0.92), (-0.05, 0.7), (-0.05, 0.2), (-0.95, 0.2)]
    yard.add("House Outline", "Lines-Connected", "25", colors=("White",), points=house)
    ET.SubElement(yard.root, "PropViews")
    return yard.root


def demo_song(path: Path) -> Path:
    """Synthesize a short song: drums, a bass line and bells, quiet then loud then out."""
    total = int(SONG_SECONDS * _RATE)
    t = np.arange(total) / _RATE
    song = np.zeros(total)
    beat = 60.0 / SONG_BPM

    def hit(at: float, length: float, tone: float, decay: float, gain: float,
            noise: bool = False) -> None:
        start = int(at * _RATE)
        n = min(int(length * _RATE), total - start)
        if n <= 0:
            return
        k = np.arange(n) / _RATE
        if noise:
            body = np.random.default_rng(start).uniform(-1, 1, n)
        else:
            body = np.sin(2 * math.pi * tone * k)
        song[start:start + n] += gain * body * np.exp(-k / decay)

    def loudness(at: float) -> float:
        if at < 16:
            return 0.35
        if at < 40:
            return 1.0
        return 0.55

    notes = (55.0, 55.0, 73.4, 65.4)
    for i in range(int(SONG_SECONDS / beat)):
        at = i * beat
        level = loudness(at)
        hit(at, 0.25, 60.0 if i % 2 == 0 else 180.0, 0.06, 0.9 * level)
        hit(at, 0.45, notes[(i // 4) % 4], 0.25, 0.35 * level)
        if 16 <= at < 40:
            hit(at + beat / 2, 0.08, 0, 0.02, 0.25, noise=True)
        if i % 8 == 7 and 16 <= at < 40:
            hit(at + beat / 2, 0.3, 1568.0, 0.08, 0.3)
    hit(16.0, 2.0, 0, 0.7, 0.6, noise=True)
    song *= np.clip((SONG_SECONDS - t) / 2.0, 0, 1)
    data = (song / np.max(np.abs(song)) * 0.8 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(_RATE)
        stream.writeframes(data.tobytes())
    return path


def build_demo(folder: str | Path) -> GeneratedShow:
    """Write the demo yard and song into ``folder`` and generate the show there."""
    target = Path(folder)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Choose an empty or new folder for the demo: {target}")
    target.mkdir(parents=True, exist_ok=True)
    preview = target / "Demo Yard.lorprev"
    ET.ElementTree(demo_preview()).write(preview, encoding="utf-8", xml_declaration=True)
    song = demo_song(target / "Demo Song.wav")
    return generate_show(preview, target / "Demo Song.loredit", load_rule_set(),
                         audio_path=song, separate=False)


_demo_lock = threading.Lock()
_demo_cache: dict[str, Any] = {}


def demo_payload() -> dict[str, Any]:
    """The demo show for the start page's "Watch a demo" button: the sequence, its
    song (base64 WAV) and the song's analysis. Built once per run, then reused."""
    with _demo_lock:
        if not _demo_cache:
            folder = Path(tempfile.mkdtemp(prefix="lor-demo-"))
            try:
                show = build_demo(folder / "demo")
                analysis_path = show.analysis_path
                _demo_cache.update(
                    file_name=show.sequence_path.name,
                    sequence=show.sequence_path.read_text(encoding="utf-8-sig"),
                    sound_name="Demo Song.wav",
                    sound=base64.b64encode((folder / "demo" / "Demo Song.wav").read_bytes())
                    .decode("ascii"),
                    analysis=json.loads(analysis_path.read_text(encoding="utf-8"))
                    if analysis_path else None,
                    rules_ok=show.report.ok,
                )
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        return dict(_demo_cache)

