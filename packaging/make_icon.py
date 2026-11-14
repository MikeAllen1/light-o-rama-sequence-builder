"""Draw the app icon with no image library.

A rounded teal square with a white "L" and three small lights. Writes the Windows
icon (packaging/windows/lor-sequencer.ico: 256, 48, 32 and 16 pixels), the macOS
icon (packaging/macos/lor-sequencer.icns: 128, 256 and 512 pixels) and the Linux
icon (packaging/linux/lor-sequencer.png: 256 pixels); each image is a PNG.
Run: python packaging/make_icon.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def _pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    rows = []
    radius = size * 0.2
    for y in range(size):
        row = []
        for x in range(size):
            # Rounded square mask, softened at the edge.
            dx = max(radius - x - 0.5, 0, x + 0.5 - (size - radius))
            dy = max(radius - y - 0.5, 0, y + 0.5 - (size - radius))
            inside = radius - math.hypot(dx, dy) if dx and dy else radius
            alpha = max(0.0, min(1.0, inside + 0.5)) if dx and dy else 1.0
            t = (x + y) / (2 * size)
            color = (int(139 - 76 * t), int(215 - 60 * t), int(229 - 45 * t))
            u, v = x / size, y / size
            letter = (0.30 <= u <= 0.44 and 0.20 <= v <= 0.78) or \
                     (0.30 <= u <= 0.70 and 0.66 <= v <= 0.78)
            if letter:
                color = (8, 19, 25)
            for cx, cy, light in ((0.62, 0.30, (255, 70, 60)), (0.74, 0.42, (60, 220, 110)),
                                  (0.62, 0.54, (255, 214, 10))):
                if math.hypot(u - cx, v - cy) <= 0.065:
                    color = light
            row.append((*color, int(255 * alpha)))
        rows.append(row)
    return rows


def _png(size: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for pixel in row for c in pixel) for row in _pixels(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def build_icon(path: Path) -> None:
    sizes = (256, 48, 32, 16)
    images = [_png(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    directory = b""
    for size, image in zip(sizes, images, strict=True):
        side = 0 if size == 256 else size
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + directory + b"".join(images))


def build_icns(path: Path) -> None:
    """A macOS icon: PNG images under their ICNS type codes."""
    entries = b""
    for kind, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512)):
        image = _png(size)
        entries += kind + struct.pack(">I", 8 + len(image)) + image
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(entries)) + entries)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    targets = (here / "windows" / "lor-sequencer.ico", here / "macos" / "lor-sequencer.icns",
               here / "linux" / "lor-sequencer.png")
    for target in targets:
        target.parent.mkdir(exist_ok=True)
    build_icon(targets[0])
    build_icns(targets[1])
    targets[2].write_bytes(_png(256))
    for target in targets:
        print(f"Wrote {target}")
