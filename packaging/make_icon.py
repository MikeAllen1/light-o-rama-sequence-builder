"""Draw the app icon (packaging/windows/lor-sequencer.ico) with no image library.

A rounded teal square with a white "L" and three small lights, at 256, 48, 32 and
16 pixels, each stored as a PNG inside one Windows icon file.
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


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "windows" / "lor-sequencer.ico"
    build_icon(target)
    print(f"Wrote {target}")
