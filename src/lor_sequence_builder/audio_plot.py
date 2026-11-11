"""SVG diagnostic plot rendering for audio analysis."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def _svg_plot(
    path: Path,
    duration: float,
    energy: list[dict[str, Any]],
    beats: list[float],
    downbeats: list[float],
    onsets: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    stops: list[dict[str, Any]],
) -> None:
    width, height = 1400, 520
    left, right, top, bottom = 70, 20, 35, 55
    plot_width, plot_height = width - left - right, height - top - bottom
    max_energy = max((point["rms"] for point in energy), default=1.0) or 1.0
    points = []
    for point in energy:
        x = left + point["time"] / duration * plot_width
        y = top + plot_height - point["rms"] / max_energy * plot_height
        points.append(f"{x:.1f},{y:.1f}")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="70" y="22" font-family="sans-serif" font-size="16">Audio analysis: RMS energy, beats, onsets, hard stops</text>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{width-right}" y2="{top + plot_height}" stroke="#333"/>',
    ]
    if points:
        parts.append(f'<polyline fill="none" stroke="#2767a8" stroke-width="2" points="{" ".join(points)}"/>')
    for beat in beats:
        x = left + beat / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#2b8a3e" opacity=".28"/>')
    for downbeat in downbeats:
        x = left + downbeat / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#7048e8" stroke-width="2" opacity=".65"/>')
    for onset in onsets:
        x = left + onset["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top+plot_height-12}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#d97706"/>')
    for section in sections:
        x = left + section["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#0c8599" stroke-dasharray="4 4"/>')
    for stop in stops:
        x = left + stop["time"] / duration * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#c92a2a" stroke-width="2"/>')
    for tick in range(0, math.ceil(duration) + 1, max(1, math.ceil(duration / 12))):
        x = left + tick / duration * plot_width
        parts.append(f'<text x="{x:.1f}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="11">{tick}s</text>')
    parts.extend([
        '<text x="70" y="500" font-family="sans-serif" font-size="11">Blue: RMS energy | Green: beats | Purple: provisional downbeats | Amber: onsets | Teal: energy transitions | Red: hard stops</text>',
        '</svg>',
    ])
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(parts))


