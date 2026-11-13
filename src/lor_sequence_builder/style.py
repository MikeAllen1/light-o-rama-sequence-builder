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
# the beat, the half beat, the sixteenth note, or the drums (the kick or the snare; where a song has no
# clear drum, the beat).
GRIDS = ("phrase", "bar", "half_bar", "beat", "half", "sixteenth", "kick", "snare")

# What each kind of prop can do.
#   rows of arches and other look-alike rows: chase, bounce, fill, wave, alternate
#   mega tree: rotate, spiral, fill_up, breathe, twinkle
#   families of loose look-alikes (decorations, homemade trees): trade, breathe, pulse
#   outlines: base, breathe, trade, pulse, twinkle
#   star: hold, base, twinkle
MOTIONS = {
    "arch_row": ("chase", "bounce", "fill", "wave", "alternate"),
    "row": ("chase", "bounce", "fill", "wave", "alternate"),
    "outline_row": ("chase", "bounce", "fill", "wave", "alternate"),
    "mega_tree": ("rotate", "spiral", "fill_up", "breathe", "twinkle"),
    "family": ("trade", "breathe", "pulse"),
    "outline": ("base", "breathe", "trade", "pulse", "twinkle"),
    "star": ("hold", "base", "twinkle"),
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
class Profile:
    """What a finished show in a style should measure, so the quality check can say
    whether the show lived up to the style. Ranges are (lowest, highest)."""

    # How long an effect typically lasts, in beats.
    hold_beats: tuple[float, float]
    # Share of effects that fade instead of cutting.
    fade_share: tuple[float, float]
    # Most of the yard lit, on average, in the quiet and middle parts.
    calm_lit: float
    # Most of the yard lit, on average, in the loud parts (room left for contrast).
    peak_lit: float
    # Loud parts light at least this many times as much of the yard as quiet ones.
    loud_to_quiet: float
    # Seconds the whole yard may be lit outside the loud parts, finale and flashes.
    full_outside_peaks: float
    # Whole-yard accents (crash flashes, returns, louder parts opening) per minute.
    accents_per_minute: tuple[float, float]


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
    # What a show in this style should measure (None for learned styles: they are
    # judged by the general checks only).
    profile: Profile | None = None
    # The glow under the show at each level: (hit, hold) brightness. Props that are not
    # leading stay lit at ``hold``; the steady props (outlines, house, yard figures)
    # hit ``hit`` together on each beat and decay back to ``hold``, and the sparkly ones
    # (arches, snowflakes, the mega tree, stars) twinkle, or shimmer in loud parts.
    # A hit of 0 only holds; None leaves the yard dark around the leads.
    glow: tuple[tuple[int, int] | None, tuple[int, int] | None,
                tuple[int, int] | None] = (None, None, None)
    # The glow hits on every half beat in loud parts (True) or stays on the beat.
    glow_half_beats: bool = False
    # Snowflakes falling on high-pitched hits fall at most once per this many beats
    # (0: as often as each fall can be seen).
    sparkle_every: float = 0
    # Stabs on the song's strongest hits: (share of the yard, share of onsets that
    # count as strong, longest flash in centiseconds). A share of 0 turns them off.
    stabs: tuple[float, float, int] = (0.0, 0.0, 0)
    # Stabs fade out (True) or cut off sharply.
    stab_fade: bool = True
    # From this loudness level (0 quiet, 1 mid, 2 loud) arches and the mega tree rest
    # on a twinkle or shimmer through long gaps between their moves.
    beds_from: int = 1

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
                          ("half_bar", "beat", ("half", "beat"))),
            row=Part(("alternate", ("alternate", "chase"), ("alternate", "chase")),
                     ("beat", "beat", ("beat", "half"))),
            mega_tree=Part(("rotate", ("rotate", "spiral"), ("spiral", "fill_up")),
                           ("beat", "beat", ("beat", "half_bar"))),
            family=Part(("trade", "trade", ("trade", "pulse")),
                        ("bar", "snare", ("snare", "beat"))),
            outline=Part(("base", "base", ("trade", "pulse")),
                         ("phrase", "phrase", "bar")),
            outline_row=Part(("alternate", "chase", ("chase", "bounce")),
                             ("half_bar", "kick", "kick")),
            star=Part(("twinkle", "base", "twinkle"), ("phrase", "phrase", "phrase")),
        ),
        phrase_bars=4, entry="flash", arc=1, vary_repeats=True,
        spin_width=2, fall=(12, 20, 25),
        glow=((0, 30), (85, 40), (100, 50)), stabs=(0.3, 0.4, 30),
        # Traditional and festive: balanced fades and cuts, moderate speed, clear
        # difference between verse and chorus, a flash to open the big parts.
        profile=Profile(hold_beats=(0.4, 2.5), fade_share=(0.3, 0.85), calm_lit=0.45,
                        peak_lit=0.75, loud_to_quiet=1.5, full_outside_peaks=3.0,
                        accents_per_minute=(1.0, 6.0)),
    ),
    "energetic": Style(
        "energetic", "High energy",
        "Busy and punchy: more of the yard leads at once, motion on the half beat, chases "
        "that bounce, outlines that pulse with the beat, sharp hits instead of fades, and a "
        "dark beat before every big part so it hits harder. For fast, loud songs.",
        leads=(1, 2, 4), chase_hold=(1, 1, 1),
        soft=(False, False, False), brightness=(75, 100, 100),
        flashes=True, crash_spacing=200, flash_length=50, sparkle_density=0.35,
        build_from=0.4, call_and_response=True, fall_every=(2, 1, 1),
        parts=_parts(
            arch_row=Part(("chase", ("bounce", "alternate"), ("bounce", "chase")),
                          ("beat", "half", ("sixteenth", "half"))),
            row=Part(("chase", ("alternate", "bounce"), "alternate"),
                     ("beat", "half", "half")),
            mega_tree=Part(("spiral", ("fill_up", "spiral"), ("rotate", "fill_up")),
                           ("half", "beat", ("sixteenth", "half"))),
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
        glow=((70, 20), (100, 30), (100, 35)), glow_half_beats=True,
        stabs=(0.5, 0.45, 25), stab_fade=False, beds_from=2,
        # Dynamic and aggressive: quick hits, strong contrast between quiet and loud,
        # frequent accents, but never so much light that the contrast is lost.
        profile=Profile(hold_beats=(0.2, 0.9), fade_share=(0.0, 0.5), calm_lit=0.5,
                        peak_lit=0.75, loud_to_quiet=1.7, full_outside_peaks=3.0,
                        accents_per_minute=(1.5, 8.0)),
    ),
    "elegant": Style(
        "elegant", "Elegant",
        "Calm and graceful: motion on bars and phrases instead of beats, arches that fill "
        "and wave, decorations that breathe one after another, a mega tree that breathes "
        "and turns slowly, louder parts that swell in, softer brightness and no flashes. "
        "For ballads and quiet songs.",
        leads=(1, 1, 3), chase_hold=(1, 2, 2),
        soft=(True, True, True), brightness=(50, 75, 90),
        flashes=False, crash_spacing=800, flash_length=80, sparkle_density=0.8,
        build_from=0.6, call_and_response=False, fall_every=(0, 0, 2),
        parts=_parts(
            # Even the loud parts move on bars and phrases, with swells instead of cuts.
            arch_row=Part(("wave", "wave", "wave"), ("phrase", "phrase", "phrase")),
            row=Part(("wave", "wave", "wave"), ("phrase", "phrase", "phrase")),
            mega_tree=Part(("breathe", "rotate", ("rotate", "breathe")),
                           ("phrase", "half_bar", ("half_bar", "bar"))),
            family=Part(("breathe", "trade", ("breathe", "trade")),
                        ("phrase", "bar", ("phrase", "bar"))),
            outline=Part(("twinkle", "breathe", "breathe"), ("phrase", "phrase", "phrase")),
            outline_row=Part(("wave", "wave", "fill"), ("phrase", "bar", "bar")),
            star=Part(("twinkle", "twinkle", "twinkle"), ("phrase", "phrase", "phrase")),
        ),
        phrase_bars=8, entry="swell", arc=1, vary_repeats=False,
        spin_width=3, fall=(22, 40, 60),
        glow=(None, (0, 20), (0, 35)), sparkle_every=4,
        # Cinematic and refined: long lights and fades, few props at once, the whole
        # yard saved for the peaks, and almost no flashing.
        profile=Profile(hold_beats=(1.2, 8.0), fade_share=(0.35, 1.0), calm_lit=0.45,
                        peak_lit=0.75, loud_to_quiet=1.3, full_outside_peaks=3.0,
                        accents_per_minute=(0.0, 2.5)),
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
