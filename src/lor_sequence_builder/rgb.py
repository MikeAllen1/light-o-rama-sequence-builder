"""RGB props: the colors the planner uses and how S6 stores them.

Evidence (an owner's S6 sequence with seven ``DumbRGB`` floods; see
docs/S6_FORMAT.md): a ``DumbRGB`` prop has ``TraditionalType="Channel_per_color"``
and three ``ChannelGrid`` entries (red, green, blue), but the sequence holds ONE
``channel`` (row 0, column 0, color 0). Each effect stores its color as a signed
32-bit ARGB number in the intensity fields: ``intensity`` for one color, or
``startIntensity``/``endIntensity`` for a fade from one color to another (black is
``-16777216``, white ``-1``). ``INTENSITY`` and ``SHIMMER`` effects were seen, both
with start/end pairs; a single ``intensity`` was seen on ``INTENSITY``.

Pixel props (``StringType="RGB"``: three channels per pixel) are sequenced with
motion effects instead of channels; see pixels.py.
"""

from __future__ import annotations

RGB_STRING_TYPE = "DumbRGB"

# Color names the planner and requirements use, with the light each makes.
COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "warm white": (255, 180, 100),
    "gold": (255, 176, 0),
    "yellow": (255, 255, 0),
    "orange": (255, 96, 0),
    "purple": (176, 2, 176),  # the purple S6 itself mixes
    "magenta": (255, 0, 255),
    "pink": (255, 64, 128),
    "cyan": (0, 255, 255),
    "teal": (0, 176, 176),
    "ice blue": (64, 128, 255),
}
ALIASES = {"aqua": "cyan", "violet": "purple", "amber": "gold", "warmwhite": "warm white",
           "cool white": "white", "pure white": "white"}

BLACK = -16777216

PIXEL_STRING_TYPE = "RGB"
PIXEL_DEVICES = frozenset({"DMX", "LOR"})
PIXEL_PROBLEM = "a pixel prop: it gets pixel effects when you turn them on"


def is_pixel(attributes: dict[str, str]) -> bool:
    """A pixel prop on a controller: S6 "RGB" strings (three channels per pixel)."""
    return (attributes.get("StringType") == PIXEL_STRING_TYPE
            and attributes.get("DeviceType") in PIXEL_DEVICES)


def color_name(name: str | None) -> str | None:
    """The known color a name stands for (case and aliases ignored), or None."""
    if not name:
        return None
    key = " ".join(name.strip().lower().replace("_", " ").split())
    key = ALIASES.get(key, key)
    return key if key in COLORS else None


def is_rgb(attributes: dict[str, str]) -> bool:
    """A non-pixel RGB prop (S6 "DumbRGB"): three color circuits, one sequence channel."""
    return attributes.get("StringType") == RGB_STRING_TYPE


def argb(color: str | None, intensity: int) -> int:
    """S6's stored value for ``color`` at ``intensity`` percent: opaque ARGB as a
    signed 32-bit number (0 percent is black)."""
    red, green, blue = COLORS.get(color_name(color) or "white", COLORS["white"])
    share = max(0, min(100, intensity)) / 100
    value = (0xFF << 24) | (round(red * share) << 16) | (round(green * share) << 8) \
        | round(blue * share)
    return value - (1 << 32)


def from_argb(value: int) -> tuple[tuple[int, int, int], int]:
    """The (red, green, blue) and brightness percent a stored S6 value shows."""
    unsigned = value & 0xFFFFFFFF
    rgb = ((unsigned >> 16) & 0xFF, (unsigned >> 8) & 0xFF, unsigned & 0xFF)
    return rgb, round(max(rgb) * 100 / 255)
