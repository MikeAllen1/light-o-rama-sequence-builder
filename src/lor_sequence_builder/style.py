"""Show styles: the same song and display, arranged with a different character.

A style never changes which rules a show must pass. It decides, for each kind of
prop at each energy level, *what the prop does* (its motion) and *what it moves on*
(the musical grid: a whole phrase, a bar, every other beat, the beat, or the half
beat), and how the song is read and entered:

- ``classic``: the default. Arches chase on the beat and bounce back in loud parts,
  decorations take turns on the beat, the mega tree spins, a flash opens each louder
  part.
- ``energetic``: half-beat motion, bouncing chases, outlines pulse with the beat,
  the mega tree fills bar by bar, and the beat before a louder part goes dark so the
  hit lands.
- ``elegant``: motion on bars and phrases, never on the half beat. Arches fill and
  wave, decorations breathe one after another, the mega tree breathes before it
  turns slowly, louder parts swell in, and eight-bar phrases.

Each motion can list alternatives: a part that comes back (a second chorus) keeps
its handoffs but, in styles that vary repeats, moves the next way on the list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOW, MID, HIGH = 0, 1, 2

# The musical grids a motion can move on: a whole phrase, a bar, every other beat,
# the beat, the half beat, or the drums (the kick or the snare; where a song has no
# clear drum, the beat).
GRIDS = ("phrase", "bar", "half_bar", "beat", "half", "kick", "snare")

# What each kind of prop can do.
#   rows of arches and other look-alike rows: chase, bounce, fill, wave, alternate
#   mega tree: rotate, spiral, fill_up, breathe, twinkle
#   families of loose look-alikes (decorations, homemade trees): trade, breathe, pulse
#   outlines: base, breathe, trade, pulse, twinkle
#   star: hold, twinkle
MOTIONS = {
    "arch_row": ("chase", "bounce", "fill", "wave", "alternate"),
    "row": ("chase", "bounce", "fill", "wave", "alternate"),
    "outline_row": ("chase", "bounce", "fill", "wave", "alternate"),
    "mega_tree": ("rotate", "spiral", "fill_up", "breathe", "twinkle"),
    "family": ("trade", "breathe", "pulse"),
    "outline": ("base", "breathe", "trade", "pulse", "twinkle"),
    "star": ("hold", "twinkle"),
}

# A motion at one level: one choice, or alternatives for repeats.
Choice = str | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Part:
    """What one kind of prop does at the low, mid and high levels, and on what grid."""

    motion: tuple[Choice, Choice, Choice]
    grid: tuple[Choice, Choice, Choice]

    def at(self, level: int, variant: int = 0) -> tuple[str, str]:
        def pick(choice: Choice) -> str:
            return choice if isinstance(choice, str) else choice[variant % len(choice)]
        return pick(self.motion[level]), pick(self.grid[level])


@dataclass(frozen=True, slots=True)
class Style:
    key: str
    name: str
    description: str
    # Lead groups at each energy level.
    leads: tuple[int, int, int]
    # Each prop of a chase holds for N steps.
    chase_hold: tuple[int, int, int]
    # Fade the hits out (True) or cut them off sharply (False).
    soft: tuple[bool, bool, bool]
    # Brightness of the patterns at each level (percent).
    brightness: tuple[int, int, int]
    # Signature flashes on crashes and returns from a stop.
    flashes: bool
    crash_spacing: int
    flash_length: int
    # High hits per beat needed before snowflakes fall on them.
    sparkle_density: float
    # A build-up rises from this share of full brightness.
    build_from: float
    call_and_response: bool
    # Snowflakes fall every N beats at each level (0: once a bar).
    fall_every: tuple[int, int, int]
    # What each kind of prop does, and on what grid.
    parts: dict[str, Part] = field(default_factory=dict)
    # Bars in a phrase: how long one arrangement idea lasts before the leads hand off.
    phrase_bars: int = 4
    # How a louder part is entered: "flash" (everything flashes and fades over a
    # beat), "drop" (the beat before goes dark, then the flash) or "swell" (it fades
    # in over its first bar).
    entry: str = "flash"
    # Extra lead groups by the end of the song, so the show grows as it goes.
    arc: int = 1
    # A part that comes back moves differently (True) or repeats its look (False).
    vary_repeats: bool = True
    # How many segments of a spinning tree are lit at once (a thin, sharp spin or a
    # broad, soft one).
    spin_width: int = 2
    # A falling snowflake starts this long after the one above it, holds, then fades
    # (centiseconds): quick and sparkly, or a slow drift.
    fall: tuple[int, int, int] = (12, 20, 25)

    def part(self, kind: str) -> Part:
        return self.parts[kind]

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "name": self.name, "description": self.description}


def _parts(**parts: Part) -> dict[str, Part]:
    for kind, part in parts.items():
        for level in (LOW, MID, HIGH):
            for variant in range(3):
                motion, grid = part.at(level, variant)
                if motion not in MOTIONS[kind] or grid not in GRIDS:
                    raise ValueError(f"{kind}: unknown motion {motion!r} or grid {grid!r}")
    return dict(parts)


STYLES: dict[str, Style] = {
    "classic": Style(
        "classic", "Classic",
        "Balanced: a few groups lead at a time and hand off across the yard, arches chase "
        "on the beat and bounce back in the big parts, decorations take turns, and a "
        "flash opens each louder part.",
        leads=(2, 2, 3), chase_hold=(1, 1, 2),
        soft=(True, False, True), brightness=(60, 90, 100),
        flashes=True, crash_spacing=400, flash_length=60, sparkle_density=0.5,
        build_from=0.5, call_and_response=True, fall_every=(0, 2, 1),
        parts=_parts(
            arch_row=Part(("chase", "chase", ("bounce", "chase")),
                          ("half_bar", "beat", "beat")),
            row=Part(("alternate", ("alternate", "chase"), ("alternate", "chase")),
                     ("beat", "beat", ("beat", "half"))),
            mega_tree=Part(("rotate", ("rotate", "spiral"), ("spiral", "fill_up")),
                           ("beat", "half", ("half", "beat"))),
            family=Part(("trade", "trade", ("trade", "pulse")),
                        ("bar", "snare", ("snare", "half"))),
            outline=Part(("base", "base", ("trade", "pulse")),
                         ("phrase", "phrase", "bar")),
            outline_row=Part(("alternate", "chase", ("chase", "bounce")),
                             ("half_bar", "kick", "kick")),
            star=Part(("hold", "hold", "twinkle"), ("phrase", "phrase", "phrase")),
        ),
        phrase_bars=4, entry="flash", arc=1, vary_repeats=True,
        spin_width=2, fall=(12, 20, 25),
    ),
    "energetic": Style(
        "energetic", "High energy",
        "Busy and punchy: more of the yard leads at once, motion on the half beat, chases "
        "that bounce, outlines that pulse with the beat, sharp hits instead of fades, and a "
        "dark beat before every big part so it hits harder. For fast, loud songs.",
        leads=(2, 3, 4), chase_hold=(1, 1, 2),
        soft=(False, False, False), brightness=(75, 100, 100),
        flashes=True, crash_spacing=200, flash_length=50, sparkle_density=0.35,
        build_from=0.4, call_and_response=True, fall_every=(2, 1, 1),
        parts=_parts(
            arch_row=Part(("chase", ("bounce", "alternate"), ("bounce", "chase")),
                          ("beat", "half", "half")),
            row=Part(("chase", ("alternate", "bounce"), "alternate"),
                     ("beat", "half", "half")),
            mega_tree=Part(("spiral", ("fill_up", "spiral"), ("rotate", "fill_up")),
                           ("half", "beat", "half")),
            family=Part(("pulse", "trade", ("pulse", "trade")),
                        ("snare", "half", ("half", "snare"))),
            outline=Part(("pulse", ("trade", "pulse"), "pulse"),
                         ("bar", "beat", "beat")),
            outline_row=Part(("chase", "alternate", ("alternate", "wave")),
                             ("beat", "kick", "kick")),
            star=Part(("twinkle", "twinkle", "twinkle"), ("phrase", "phrase", "phrase")),
        ),
        phrase_bars=4, entry="drop", arc=2, vary_repeats=True,
        spin_width=1, fall=(7, 10, 14),
    ),
    "elegant": Style(
        "elegant", "Elegant",
        "Calm and graceful: motion on bars and phrases instead of beats, arches that fill "
        "and wave, decorations that breathe one after another, a mega tree that breathes "
        "and turns slowly, louder parts that swell in, softer brightness and no flashes. "
        "For ballads and quiet songs.",
        leads=(1, 2, 3), chase_hold=(1, 2, 2),
        soft=(True, True, True), brightness=(50, 75, 90),
        flashes=False, crash_spacing=800, flash_length=80, sparkle_density=0.8,
        build_from=0.6, call_and_response=False, fall_every=(0, 0, 2),
        parts=_parts(
            arch_row=Part(("wave", "fill", ("fill", "wave")), ("phrase", "bar", "bar")),
            row=Part(("wave", "wave", "fill"), ("phrase", "bar", "bar")),
            mega_tree=Part(("breathe", "rotate", ("rotate", "fill_up")),
                           ("phrase", "half_bar", ("beat", "bar"))),
            family=Part(("breathe", "breathe", "trade"), ("phrase", "bar", "half_bar")),
            outline=Part(("twinkle", "breathe", "breathe"), ("phrase", "phrase", "bar")),
            outline_row=Part(("wave", "wave", "fill"), ("phrase", "bar", "bar")),
            star=Part(("twinkle", "twinkle", "twinkle"), ("phrase", "phrase", "phrase")),
        ),
        phrase_bars=8, entry="swell", arc=1, vary_repeats=False,
        spin_width=3, fall=(22, 40, 60),
    ),
}
DEFAULT_STYLE = "classic"


def get_style(key: str | None) -> Style:
    """The style named ``key`` (default: classic), or a learned style kept for the app
    (``mine:<name>``); raises ValueError for an unknown one."""
    name = (key or DEFAULT_STYLE).strip().lower()
    if name.startswith("mine:"):
        # A style learned from the user's own sequences and kept for the app.
        from lor_sequence_builder.style_learning import StyleLearningError, load_saved

        try:
            return load_saved(name)
        except StyleLearningError as exc:
            raise ValueError(str(exc)) from exc
    if name not in STYLES:
        raise ValueError(f"Unknown style {key!r}; choose one of: {', '.join(STYLES)}")
    return STYLES[name]
