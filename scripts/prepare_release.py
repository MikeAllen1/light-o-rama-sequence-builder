"""Get a new version ready: bump the number everywhere and draft its release notes.

    uv run python scripts/prepare_release.py 0.2.0

It changes the version in pyproject.toml, uv.lock, the package and the installer
script, and writes docs/releases/v0.2.0.md from the pull requests merged since the
last version change. Review the notes, open a pull request with the result, merge
it, then publish a release named v0.2.0 on GitHub (Releases, Draft a new release)
and paste the notes. The Desktop app workflow attaches the installer and the
portable zip, and everyone's app announces the new version.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONED = {
    "pyproject.toml": (r'(?m)^(version = ")(\d+\.\d+\.\d+)(")', 1),
    "uv.lock": (r'(name = "light-o-rama-sequence-builder"\nversion = ")(\d+\.\d+\.\d+)(")', 1),
    "src/lor_sequence_builder/__init__.py": (r'(__version__ = ")(\d+\.\d+\.\d+)(")', 1),
    "packaging/windows/installer.iss": (r'(#define AppVersion ")(\d+\.\d+\.\d+)(")', 1),
}


def current_versions(root: Path = ROOT) -> dict[str, str]:
    found = {}
    for name, (pattern, _) in VERSIONED.items():
        match = re.search(pattern, (root / name).read_text(encoding="utf-8"))
        found[name] = match.group(2) if match else ""
    return found


def _parse(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise SystemExit(f"error: a version looks like 0.2.0, not {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def bump(version: str, root: Path = ROOT) -> None:
    now = current_versions(root)
    if len(set(now.values())) != 1:
        raise SystemExit(f"error: the version differs between files: {now}")
    if _parse(version) <= _parse(next(iter(now.values()))):
        raise SystemExit(f"error: {version} is not newer than {next(iter(now.values()))}")
    for name, (pattern, count) in VERSIONED.items():
        path = root / name
        text, made = re.subn(pattern, rf"\g<1>{version}\g<3>", path.read_text(encoding="utf-8"),
                             count=count)
        if made != count:
            raise SystemExit(f"error: could not find the version in {name}")
        path.write_text(text, encoding="utf-8", newline="")


def merged_since_last_version(root: Path = ROOT) -> list[str]:
    """Titles of the pull requests merged since pyproject.toml's version last changed."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                              text=True).stdout

    last = git("log", "-1", "--format=%H", "-G", r'^version = "', "--", "pyproject.toml").strip()
    span = [f"{last}..HEAD"] if last else []
    subjects = git("log", "--first-parent", "--format=%s", *span).splitlines()
    return [s for s in subjects if re.search(r"\(#\d+\)$", s)]


def notes(version: str, titles: list[str]) -> str:
    lines = [f"# LOR Sequencer {version}", "", "What's new:", ""]
    lines += [f"- {title}" for title in reversed(titles)] or ["- (fill in)"]
    lines += ["", "Download LOR-Sequencer-Setup-" + version + ".exe below and run it over your "
              "current copy; it replaces it and keeps your settings. Cannot run installers? "
              "LOR-Sequencer-Portable-" + version + ".zip: unzip it and run LOR Sequencer.exe.",
              "", "Free to use, not to sell."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, for example 0.2.0")
    options = parser.parse_args(argv)
    titles = merged_since_last_version()
    bump(options.version)
    target = ROOT / "docs" / "releases" / f"v{options.version}.md"
    target.write_text(notes(options.version, titles), encoding="utf-8")
    print(f"Version {options.version} set in: {', '.join(VERSIONED)}")
    print(f"Release notes drafted: {target.relative_to(ROOT)} ({len(titles)} pull requests)")
    print("Next: review the notes, open a pull request, merge it, then publish release "
          f"v{options.version} on GitHub with those notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
