"""Learn a style from sequences someone made by hand.

Anyone who has sequenced a few songs by hand has habits: short punchy hits or long
fades, a busy yard or a sparse one, flashes on the big moments or none, twinkle or
steady. This reads their own ``.loredit`` (S5/S6) or ``.lms`` (S4) files, measures
those habits, and turns them into a style the planner can use, starting from the
built-in style they are closest to and adjusting it.

Everything happens on this computer. Only the measurements are kept (how long
effects last, how often they fade, how much is lit); nothing of the sequences
themselves, their names or their channels.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lor_sequence_builder.style import HIGH, LOW, MID, STYLES, Part, Style, _parts

SCHEMA = "lor-style-1.0"
PREFIX = "mine:"
MAX_STYLE_BYTES = 64 * 1024
MAX_SAVED = 50
# Built-in grids from fastest to slowest. Drum grids keep their place.
_SPEED = ("half", "beat", "half_bar", "bar", "phrase")


class StyleLearningError(ValueError):
    """A sequence that cannot be learned from, or a style file that cannot be used."""


@dataclass(frozen=True, slots=True)
class Habits:
    """What a set of hand-made sequences does, independent of their props and songs."""

    sequences: int
    effects: int
    beat: int  # centiseconds
    hold_beats: float  # how long an effect lasts, in beats (median)
    fade_share: float  # share of effects that fade
    twinkle_share: float  # share of effects that twinkle or shimmer
    brightness: int  # typical peak intensity (percent)
    lit_share: float  # average share of the sequence's channels lit
    together_share: float  # share of starts where most channels light at once
    beat_from_grid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in dataclasses.asdict(self).items()}

    @classmethod
    def from_dict(cls, data: Any) -> Habits:
        if not isinstance(data, dict):
            raise StyleLearningError("The style's measurements are missing.")
        try:
            habits = cls(
                sequences=int(data["sequences"]), effects=int(data["effects"]),
                beat=int(data["beat"]), hold_beats=float(data["hold_beats"]),
                fade_share=float(data["fade_share"]),
                twinkle_share=float(data["twinkle_share"]),
                brightness=int(data["brightness"]), lit_share=float(data["lit_share"]),
                together_share=float(data["together_share"]),
                beat_from_grid=bool(data.get("beat_from_grid", True)))
        except (KeyError, TypeError, ValueError) as exc:
            raise StyleLearningError("The style's measurements are not valid.") from exc
        if not (1 <= habits.sequences <= 1000 and 1 <= habits.effects <= 10_000_000
                and 20 <= habits.beat <= 200 and 0 < habits.hold_beats <= 64
                and 1 <= habits.brightness <= 100
                and all(0 <= v <= 1 for v in (habits.fade_share, habits.twinkle_share,
                                               habits.lit_share, habits.together_share))):
            raise StyleLearningError("The style's measurements are out of range.")
        return habits


@dataclass(frozen=True, slots=True)
class Lit:
    channel: str
    start: int
    end: int
    kind: str  # "on", "fade", "twinkle"
    peak: int


# ---------------------------------------------------------------- reading


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _effect(channel: str, element: ET.Element, settings: str) -> Lit | None:
    start = _int(element.get("startCentisecond"))
    end = _int(element.get("endCentisecond"))
    if start is None or end is None or end <= start or start < 0:
        return None
    level = _int(element.get("intensity"))
    first = _int(element.get("startIntensity"))
    last = _int(element.get("endIntensity"))
    peak = max(v for v in (level, first, last, 0) if v is not None)
    if peak <= 0:
        return None
    upper = settings.upper()
    if "TWINKLE" in upper or "SHIMMER" in upper:
        kind = "twinkle"
    elif first is not None and last is not None and first != last:
        kind = "fade"
    else:
        kind = "on"
    return Lit(channel, start, end, kind, min(100, peak))


def _beats_from_grid(grids: Iterable[ET.Element], timing: str) -> list[int]:
    best: list[int] = []
    for grid in grids:
        marks = sorted({v for v in (_int(t.get(timing)) for t in grid.findall("timing"))
                        if v is not None and v >= 0})
        if len(marks) > len(best):
            best = marks
    return best


def sequence_effects(root: ET.Element, s4: bool) -> tuple[list[Lit], list[int]]:
    """Every lit effect of a sequence, keyed by channel, and the densest free timing
    grid's marks. S4 channels are keyed ``s<savedIndex>``; S5/S6 ``<SeqProp id>/<n>``."""
    lits: list[Lit] = []
    if s4:
        for index, channel in enumerate(root.iterfind("channels/channel")):
            key = "s" + channel.get("savedIndex", f"#{index}")
            for effect in channel.findall("effect"):
                found = _effect(key, effect, effect.get("type", ""))
                if found is not None:
                    lits.append(found)
        marks = _beats_from_grid(root.iterfind("timingGrids/timingGrid"), "centisecond")
    else:
        for p, prop in enumerate(root.iterfind("SequenceProps/SeqProp")):
            prop_id = prop.get("id") or f"#{p}"
            for c, channel in enumerate(prop.findall("channel")):
                key = f"{prop_id}/{c}"
                for effect in channel.findall("effect"):
                    found = _effect(key, effect, effect.get("settings", ""))
                    if found is not None:
                        lits.append(found)
        marks = _beats_from_grid(root.iterfind("TimingGrids/TimingGridFree"), "centisecond")
    return lits, marks


def _read(path: Path) -> tuple[list[Lit], int, list[int]]:
    """Effects, how many channels have any, and the densest timing grid's marks."""
    suffix = path.suffix.lower()
    if suffix == ".lms":
        from lor_sequence_builder.lms import LmsError, read_lms

        try:
            root = read_lms(path).root
        except LmsError as exc:
            raise StyleLearningError(f"{path.name}: {exc}") from exc
    elif suffix == ".loredit":
        from lor_sequence_builder.loredit import LoreditError, read_loredit

        try:
            root = read_loredit(path).root
        except LoreditError as exc:
            raise StyleLearningError(f"{path.name}: {exc}") from exc
    else:
        raise StyleLearningError(f"{path.name}: learn from .loredit (S5/S6) or .lms (S4) "
                                 "sequences.")
    lits, marks = sequence_effects(root, suffix == ".lms")
    return lits, len({lit.channel for lit in lits}), marks


# ---------------------------------------------------------------- measuring


def song_beat(marks: list[int], starts: list[int]) -> tuple[int, bool]:
    """The song's beat, from the sequence's own timing grid when it has one that looks
    like a beat, else from the spacing of effect starts."""
    gaps = [b - a for a, b in itertools.pairwise(marks) if b > a]
    from_grid = len(gaps) >= 16
    if from_grid:
        beat = int(statistics.median(gaps))
    else:
        distinct = sorted(set(starts))
        spacing = [b - a for a, b in itertools.pairwise(distinct) if 10 <= b - a <= 200]
        if not spacing:
            return 50, False
        counts: dict[int, int] = defaultdict(int)
        for gap in spacing:
            counts[round(gap / 2) * 2] += 1
        beat = max(counts, key=lambda g: (counts[g], -g))
    # A grid of half or quarter beats: count in beats.
    while beat < 35:
        beat *= 2
    while beat > 150:
        beat //= 2
    return beat, from_grid


def _merged_lengths(lits: list[Lit]) -> list[int]:
    """How long each light stays lit: back-to-back effects on one channel are one."""
    by_channel: dict[str, list[Lit]] = defaultdict(list)
    for lit in lits:
        by_channel[lit.channel].append(lit)
    lengths: list[int] = []
    for items in by_channel.values():
        items.sort(key=lambda lit: lit.start)
        start, end = items[0].start, items[0].end
        for lit in items[1:]:
            if lit.start <= end:
                end = max(end, lit.end)
            else:
                lengths.append(end - start)
                start, end = lit.start, lit.end
        lengths.append(end - start)
    return lengths


def measure_effects(lits: list[Lit], channels: int, marks: list[int]) -> Habits:
    if len(lits) < 20 or channels < 2:
        raise StyleLearningError("has too few effects to learn from (at least 20 on two or "
                                 "more channels).")
    beat, from_grid = song_beat(marks, [lit.start for lit in lits])
    lengths = [lit.end - lit.start for lit in lits]
    end = max(lit.end for lit in lits)
    first = min(lit.start for lit in lits)
    step = 10
    count = (end - first) // step + 1
    lit_at = [0] * count
    seen: dict[tuple[str, int], bool] = {}
    for lit in lits:
        for t in range((lit.start - first) // step, min(count, (lit.end - first) // step)):
            if not seen.get((lit.channel, t)):
                seen[(lit.channel, t)] = True
                lit_at[t] += 1
    starts: dict[int, set[str]] = defaultdict(set)
    for lit in lits:
        starts[lit.start // 5].add(lit.channel)
    together = sum(1 for chans in starts.values() if len(chans) >= max(3, 0.6 * channels))
    return Habits(
        sequences=1, effects=len(lits), beat=beat,
        hold_beats=max(0.05, statistics.median(lengths) / beat),
        fade_share=sum(1 for lit in lits if lit.kind == "fade") / len(lits),
        twinkle_share=sum(1 for lit in lits if lit.kind == "twinkle") / len(lits),
        brightness=max(1, round(statistics.median(lit.peak for lit in lits))),
        lit_share=sum(lit_at) / (count * channels),
        together_share=together / max(1, len(starts)),
        beat_from_grid=from_grid)


def combine(habits: Sequence[Habits]) -> Habits:
    """Several sequences' habits, each weighted by how many effects it has."""
    if not habits:
        raise StyleLearningError("No sequences to learn from.")
    total = sum(h.effects for h in habits)

    def mean(name: str) -> float:
        return sum(float(getattr(h, name)) * h.effects for h in habits) / total

    return Habits(
        sequences=sum(h.sequences for h in habits), effects=total,
        beat=round(mean("beat")), hold_beats=mean("hold_beats"),
        fade_share=mean("fade_share"), twinkle_share=mean("twinkle_share"),
        brightness=round(mean("brightness")), lit_share=mean("lit_share"),
        together_share=mean("together_share"),
        beat_from_grid=all(h.beat_from_grid for h in habits))


def measure(path: str | Path) -> Habits:
    """Measure one hand-made sequence."""
    source = Path(path)
    lits, channels, marks = _read(source)
    try:
        return measure_effects(lits, channels, marks)
    except StyleLearningError as exc:
        raise StyleLearningError(f"{source.name} {exc}") from exc


def measure_bytes(content: bytes, file_name: str) -> Habits:
    """Measure a sequence uploaded in the app (written to a private temporary file,
    read with the same limits, then removed)."""
    import tempfile

    suffix = Path(file_name).suffix.lower()
    if suffix not in {".lms", ".loredit"}:
        raise StyleLearningError(f"{Path(file_name).name}: learn from .loredit (S5/S6) or "
                                 ".lms (S4) sequences.")
    with tempfile.TemporaryDirectory(prefix="lor-style-") as folder:
        path = Path(folder) / ("sequence" + suffix)
        path.write_bytes(content)
        try:
            return measure(path)
        except StyleLearningError as exc:
            raise StyleLearningError(str(exc).replace("sequence" + suffix,
                                                      Path(file_name).name)) from exc


# ---------------------------------------------------------------- a style from habits

# What each built-in style's own shows measure (on the test yards; see
# tests/test_style_learning.py, which checks these stay true).
SIGNATURES: dict[str, dict[str, float]] = {
    "classic": {"hold_beats": 1.23, "fade_share": 0.66, "lit_share": 0.64, "brightness": 66},
    "energetic": {"hold_beats": 0.37, "fade_share": 0.46, "lit_share": 0.45, "brightness": 90},
    "elegant": {"hold_beats": 2.83, "fade_share": 0.76, "lit_share": 0.76, "brightness": 55},
}

# Most of the yard lighting at once on this share of start moments is a flash habit.
FLASH_HABIT = 0.03


def nearest(habits: Habits) -> str:
    """The built-in style whose shows are most like these habits."""
    import math

    def distance(key: str) -> float:
        sig = SIGNATURES[key]
        return (abs(math.log2(max(0.05, habits.hold_beats) / sig["hold_beats"]))
                + 2.0 * abs(habits.fade_share - sig["fade_share"])
                + 2.0 * abs(habits.lit_share - sig["lit_share"])
                + abs(habits.brightness - sig["brightness"]) / 10)

    return min(SIGNATURES, key=lambda key: (distance(key), key))


def _shift(grid: str, steps: int) -> str:
    if grid not in _SPEED or not steps:
        return grid
    return _SPEED[max(0, min(len(_SPEED) - 1, _SPEED.index(grid) + steps))]


def _shift_part(part: Part, steps: int) -> Part:
    def each(choice: str | tuple[str, ...]) -> str | tuple[str, ...]:
        return _shift(choice, steps) if isinstance(choice, str) else tuple(
            _shift(c, steps) for c in choice)

    grids = part.grid
    return Part(part.motion, (each(grids[LOW]), each(grids[MID]), each(grids[HIGH])))


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return slug or "my-style"


def style_from_habits(habits: Habits, name: str = "My style") -> tuple[Style, list[str]]:
    """A style that works like the habits, and what was changed from its base, in
    words."""
    name = " ".join(name.split())[:60] or "My style"
    base_key = nearest(habits)
    base = STYLES[base_key]
    sig = SIGNATURES[base_key]
    changes = [f"Starts from {base.name}, the closest built-in style."]

    # Speed: lights that stay on much longer or shorter than the base's move on a
    # slower or faster grid.
    ratio = habits.hold_beats / sig["hold_beats"]
    steps = 1 if ratio >= 1.8 else -1 if ratio <= 0.55 else 0
    parts = {kind: _shift_part(part, steps) for kind, part in base.parts.items()}
    if steps:
        changes.append("Moves on slower beats (your lights stay on longer)." if steps > 0
                       else "Moves on faster beats (your lights are quick hits).")

    # Fades or cuts.
    soft = base.soft
    if habits.fade_share >= sig["fade_share"] + 0.2:
        soft = (True, True, True)
    elif habits.fade_share <= sig["fade_share"] - 0.2:
        soft = (False, False, False)
    if soft != base.soft:
        changes.append("Fades lights out." if soft[MID] else "Cuts lights off sharply.")

    # Brightness: the loud parts at the brightness you use, the rest in proportion.
    top = max(30, min(100, habits.brightness))
    brightness = tuple(max(20, min(100, round(b * top / base.brightness[HIGH])))
                       for b in base.brightness)
    if abs(top - base.brightness[HIGH]) >= 10:
        changes.append(f"Peaks at {top}% brightness.")

    # Busy or sparse: more or fewer groups lead at once.
    busy = habits.lit_share / sig["lit_share"]
    delta = 1 if busy >= 1.3 else -1 if busy <= 0.7 else 0
    leads = tuple(max(1, min(4, n + delta)) for n in base.leads)
    if delta:
        changes.append("Lights more of the yard at once." if delta > 0 else
                       "Keeps more of the yard dark.")

    # Flashes: most of the yard lighting at the same instant, again and again.
    flashes = base.flashes or habits.together_share >= FLASH_HABIT
    if flashes != base.flashes:
        changes.append("Flashes the yard on the big moments.")

    # Twinkle: a sequencer who twinkles gets twinkling stars and outlines in quiet parts.
    if habits.twinkle_share >= 0.08:
        parts["star"] = Part(("twinkle", "twinkle", "twinkle"), parts["star"].grid)
        outline = parts["outline"]
        parts["outline"] = Part(("twinkle", outline.motion[MID], outline.motion[HIGH]),
                                outline.grid)
        changes.append("Twinkles the stars and, in quiet parts, the outlines.")
    elif habits.twinkle_share <= 0.01 and base.key != "classic":
        parts["star"] = Part(("hold", "hold", "hold"), parts["star"].grid)

    style = dataclasses.replace(
        base, key=PREFIX + _slug(name), name=name,
        description=f"Learned from {habits.sequences} of your sequence(s). "
                    + " ".join(changes[1:] or ["Works like " + base.name + "."]),
        leads=(leads[0], leads[1], leads[2]),
        soft=(soft[0], soft[1], soft[2]),
        brightness=(brightness[0], brightness[1], brightness[2]),
        flashes=flashes, parts=_parts(**parts), profile=None)
    return style, changes


# ---------------------------------------------------------------- files


def to_json(style: Style, habits: Habits, base: str) -> str:
    return json.dumps({"schema": SCHEMA, "name": style.name, "based_on": base,
                       "habits": habits.to_dict()}, indent=2) + "\n"


def from_json(text: str) -> tuple[Style, Habits]:
    """A learned style from its file. The file keeps only the measurements; the style
    is worked out from them again, so a file cannot ask for anything a learned style
    could not be."""
    if len(text.encode("utf-8")) > MAX_STYLE_BYTES:
        raise StyleLearningError("The style file is too large.")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise StyleLearningError("The style file is not valid JSON.") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise StyleLearningError(f"Not a learned style file (expected schema {SCHEMA}).")
    name = data.get("name")
    if not isinstance(name, str):
        raise StyleLearningError("The style file has no name.")
    habits = Habits.from_dict(data.get("habits"))
    style, _ = style_from_habits(habits, name)
    return style, habits


def load_style_file(path: str | Path) -> Style:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_STYLE_BYTES:
            raise StyleLearningError("The style file is too large.")
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StyleLearningError(f"Cannot read the style file: {source.name}") from exc
    return from_json(text)[0]


def styles_folder() -> Path:
    from lor_sequence_builder.vocal_separation import model_folder

    return model_folder().parent / "styles"


def save(style: Style, habits: Habits, folder: Path | None = None) -> str:
    """Keep a learned style for the app; returns its key. A style with the same name
    is replaced."""
    root = folder or styles_folder()
    root.mkdir(parents=True, exist_ok=True)
    slug = style.key.removeprefix(PREFIX)
    if len(list(root.glob("*.json"))) >= MAX_SAVED and not (root / f"{slug}.json").exists():
        raise StyleLearningError(f"You can keep up to {MAX_SAVED} learned styles; remove one "
                                 "first.")
    target = root / f"{slug}.json"
    temporary = root / f".{slug}.json.tmp"
    temporary.write_text(to_json(style, habits, nearest(habits)), encoding="utf-8")
    temporary.replace(target)
    return style.key


def _saved_path(key: str, folder: Path | None) -> Path:
    slug = key.removeprefix(PREFIX)
    if not key.startswith(PREFIX) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise StyleLearningError(f"Unknown style {key!r}.")
    return (folder or styles_folder()) / f"{slug}.json"


def load_saved(key: str, folder: Path | None = None) -> Style:
    path = _saved_path(key, folder)
    if not path.is_file():
        raise StyleLearningError(f"Unknown style {key!r}; it may have been removed.")
    return load_style_file(path)


def remove_saved(key: str, folder: Path | None = None) -> None:
    _saved_path(key, folder).unlink(missing_ok=True)


def saved(folder: Path | None = None) -> list[Style]:
    """The learned styles kept for the app, by name. A file that no longer reads is
    skipped."""
    root = folder or styles_folder()
    found: list[Style] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                found.append(load_style_file(path))
            except StyleLearningError:
                continue
    return sorted(found, key=lambda s: s.name.lower())


def learn(paths: Sequence[str | Path], name: str = "My style") -> tuple[Style, Habits,
                                                                          list[str]]:
    """Learn a style from hand-made sequences."""
    habits = combine([measure(p) for p in paths])
    style, changes = style_from_habits(habits, name)
    return style, habits, changes

