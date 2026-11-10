"""Minimal Phase 0 command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _build_parser() -> argparse.ArgumentParser:
    """Build the intentionally empty scaffold CLI."""
    return argparse.ArgumentParser(
        prog="lor-sequence-builder",
        description=(
            "Light-O-Rama S6 Sequence Builder scaffold. "
            "No sequence commands are implemented yet."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Display help until a later approved phase adds commands."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    parser = _build_parser()
    if not arguments:
        parser.print_help()
        return 0
    parser.parse_args(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
