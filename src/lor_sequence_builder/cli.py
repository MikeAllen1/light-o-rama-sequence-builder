"""Command-line entry point for the Light-O-Rama S6 Sequence Builder."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from lor_sequence_builder.loredit import LoreditError, read_loredit, write_loredit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lor-sequence-builder",
        description="Read and write verified Light-O-Rama S6 LOREDIT v15 files.",
    )
    commands = parser.add_subparsers(dest="command")
    inspect = commands.add_parser("inspect", help="summarize a supported LOREDIT file")
    inspect.add_argument("sequence", help="input .loredit file")
    roundtrip = commands.add_parser("roundtrip", help="write a loss-preserving copy")
    roundtrip.add_argument("sequence", help="input .loredit file")
    roundtrip.add_argument("output", help="new output .loredit path (must not exist)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    parser = _build_parser()
    if not arguments:
        parser.print_help()
        return 0
    options = parser.parse_args(arguments)
    if options.command is None:
        parser.print_help()
        return 0
    try:
        document = read_loredit(options.sequence)
        if options.command == "inspect":
            print(f"Format: S6 LOREDIT v{document.save_file_version}")
            print(f"Duration: {document.total_centiseconds} centiseconds")
            print(f"Sequence props: {len(document.root.findall('./SequenceProps/SeqProp'))}")
            print(f"Timing grids: {len(document.root.findall('./TimingGrids/*'))}")
            return 0
        output = write_loredit(document, options.output)
        print(f"Wrote: {output}")
        return 0
    except LoreditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
