"""Write THIRD-PARTY-NOTICES.txt: the licenses of every library the desktop app ships.

The desktop app bundles Python and the libraries the program runs on (numpy, librosa,
and so on). Most of their licenses (BSD, MIT, ISC, ...) ask that their notices travel
with any copy, so the build collects them from the installed packages into one file
that PyInstaller puts in the app folder.

Run from the repository root, in the environment the app is built from:
    python scripts/third_party_notices.py [output path]
"""

from __future__ import annotations

import re
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT = "light-o-rama-sequence-builder"
EXTRAS = ("desktop",)
# Build tools: used to make the app, not shipped inside it.
BUILD_ONLY = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "macholib", "pefile",
              "pywin32-ctypes"}
LICENSE_FILE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.IGNORECASE)


def _key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def shipped() -> list[metadata.Distribution]:
    """The program's runtime libraries, with what they need in turn."""
    seen: dict[str, metadata.Distribution] = {}
    todo: list[tuple[str, tuple[str, ...]]] = [(ROOT, EXTRAS)]
    while todo:
        name, extras = todo.pop()
        key = _key(name)
        if key in seen or key in BUILD_ONLY:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        for line in dist.requires or []:
            requirement = Requirement(line)
            environments = [{"extra": extra} for extra in extras] or [{"extra": ""}]
            if requirement.marker is None or any(
                    requirement.marker.evaluate(env) for env in environments):
                todo.append((requirement.name, tuple(sorted(requirement.extras))))
    return sorted((d for k, d in seen.items() if k != _key(ROOT)),
                  key=lambda d: _key(d.metadata["Name"]))


def notice(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    license_name = (meta.get("License-Expression") or meta.get("License") or "").strip()
    if not license_name or len(license_name) > 120:
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                       if c.startswith("License ::")]
        license_name = ", ".join(classifiers) or license_name[:120] or "see below"
    lines = [f"{meta['Name']} {dist.version}", f"License: {license_name}"]
    if meta.get("Home-page"):
        lines.append(f"Home page: {meta['Home-page']}")
    texts = []
    for file in dist.files or []:
        if LICENSE_FILE.search(file.name) and file.suffix.lower() in {"", ".txt", ".md",
                                                                       ".rst"}:
            path = Path(str(file.locate()))
            if path.is_file():
                texts.append(path.read_text(encoding="utf-8", errors="replace").strip())
    lines.append("")
    lines.append("\n\n".join(dict.fromkeys(texts)) or
                 "(This package ships no license file; its license is named above.)")
    return "\n".join(lines)


def _python_license() -> str:
    """Python's own license, which the app bundles too."""
    for folder in (Path(sys.base_prefix), Path(sysconfig.get_paths()["stdlib"])):
        path = folder / "LICENSE.txt"
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else Path("THIRD-PARTY-NOTICES.txt")
    dists = shipped()
    rule = "\n\n" + "=" * 78 + "\n\n"
    header = ("LOR Sequencer bundles the following open-source software. Each keeps its "
              "own license, reproduced below.\nFFmpeg's license is in "
              "FFmpeg-LICENSE.txt next to ffmpeg.")
    parts = [notice(d) for d in dists]
    python = _python_license()
    if python:
        parts.insert(0, f"Python {sys.version.split()[0]}\nLicense: PSF-2.0\n\n{python}")
    output.write_text(header + rule + rule.join(parts) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(dists)} libraries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
