"""Show styles: the same song and display, arranged with a different character.

A style never changes which rules a show must pass or what each kind of prop
follows; it changes how much happens and how it feels:

- ``classic``: the default. A few groups lead at a time, chases on the beat,
  build-ups, crash flashes, call and response in mid parts.
- ``energetic``: more groups lead, every chase runs on every beat, hard
  on/off hits instead of fades, more crash flashes, snowflakes fall on more
  of the high hits.
- ``elegant``: fewer groups lead, chases move every other beat, everything
  fades in and out, softer brightness, no flashes, stars and outlines
  twinkle gently.
"""

from __future__ import annotations

from dataclasses import dataclass

LOW, MID, HIGH = 0, 1, 2


@dataclass(frozen=True, slots=True)
class Style:
    key: str
    name: str
    description: str
    # Lead groups at each energy level.
    leads: tuple[int, int, int]
    # Chases step every N beats, and each prop holds for N steps.
    chase_every: tuple[int, int, int]
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
    # Stars and outlines twinkle instead of holding steady.
    twinkle_base: bool
    # Snowflakes fall every N beats at each level (0: once a bar).
    fall_every: tuple[int, int, int]

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "name": self.name, "description": self.description}


STYLES: dict[str, Style] = {
    "classic": Style(
        "classic", "Classic",
        "Balanced: a few groups lead at a time and hand off across the yard, chases on "
        "the beat, build-ups before the big parts, and a flash on the crashes.",
        leads=(2, 2, 3), chase_every=(2, 1, 1), chase_hold=(1, 1, 2),
        soft=(True, False, True), brightness=(60, 90, 100),
        flashes=True, crash_spacing=400, flash_length=60, sparkle_density=0.5,
        build_from=0.5, call_and_response=True, twinkle_base=False, fall_every=(0, 2, 1),
    ),
    "energetic": Style(
        "energetic", "High energy",
        "Busy and punchy: more of the yard leads at once, every chase on every beat, sharp "
        "hits instead of fades, and more flashes. For fast, loud songs.",
        leads=(2, 3, 4), chase_every=(1, 1, 1), chase_hold=(1, 1, 2),
        soft=(False, False, False), brightness=(75, 100, 100),
        flashes=True, crash_spacing=200, flash_length=50, sparkle_density=0.35,
        build_from=0.4, call_and_response=True, twinkle_base=False, fall_every=(2, 1, 1),
    ),
    "elegant": Style(
        "elegant", "Elegant",
        "Calm and graceful: fewer props at a time, slower chases that fade in and out, "
        "softer brightness, no flashes, and gently twinkling stars and outlines. For "
        "ballads and quiet songs.",
        leads=(1, 2, 2), chase_every=(2, 2, 1), chase_hold=(1, 2, 2),
        soft=(True, True, True), brightness=(50, 75, 90),
        flashes=False, crash_spacing=800, flash_length=80, sparkle_density=0.8,
        build_from=0.6, call_and_response=False, twinkle_base=True, fall_every=(0, 2, 2),
    ),
}
DEFAULT_STYLE = "classic"


def get_style(key: str | None) -> Style:
    """The style named ``key`` (default: classic); raises ValueError for an unknown one."""
    name = (key or DEFAULT_STYLE).strip().lower()
    if name not in STYLES:
        raise ValueError(f"Unknown style {key!r}; choose one of: {', '.join(STYLES)}")
    return STYLES[name]
