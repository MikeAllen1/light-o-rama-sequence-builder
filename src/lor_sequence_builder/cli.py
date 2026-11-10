"""Command-line interface for Light-O-Rama Sequence Builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .loredit import LoreditError, inspect_loredit
from .model import SequenceProject


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lor-sequence-builder",
        description="Build and inspect Light-O-Rama S6 sequence projects.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect the XML structure of an S6 .LOREDIT file.",
    )
    inspect_parser.add_argument("sequence_file", type=Path)

    validate_parser = subparsers.add_parser(
        "validate-project",
        help="Validate a sequence-builder project JSON file.",
    )
    validate_parser.add_argument("project_file", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "inspect":
            result = inspect_loredit(args.sequence_file)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "validate-project":
            data = json.loads(args.project_file.read_text(encoding="utf-8"))
            project = SequenceProject.from_dict(data)
            errors = project.validate()
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print(f"Valid project: {project.title}")
            return 0

    except (OSError, json.JSONDecodeError, LoreditError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
