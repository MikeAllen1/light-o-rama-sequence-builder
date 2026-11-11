"""Command-line entry point for the Light-O-Rama S6 Sequence Builder."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from lor_sequence_builder.loredit import LoreditError, read_loredit, write_loredit
from lor_sequence_builder.lorprev import LorprevError, read_lorprev


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lor-sequence-builder",
        description="Inspect and process verified Light-O-Rama S6 files.",
    )
    commands = parser.add_subparsers(dest="command")
    inspect = commands.add_parser("inspect", help="summarize a supported LOREDIT file")
    inspect.add_argument("sequence", help="input .loredit file")
    preview = commands.add_parser("inspect-preview", help="inspect a standalone LORPREV file")
    preview.add_argument("preview", help="input .lorprev file")
    roundtrip = commands.add_parser("roundtrip", help="write a loss-preserving LOREDIT copy")
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
        if options.command == "inspect-preview":
            model = read_lorprev(options.preview)
            print(f"Format: standalone LORPREV revision {model.revision.value}")
            print(f"Props: {len(model.props)}")
            print(f"Scenes: {len(model.scenes)}")
            print(f"Prop views: {len(model.prop_views)}")
            print(f"Channel-grid entries: {len(model.channel_grid_entries)}")
            lor_addresses = sorted(
                {
                    (entry.network, entry.unit_id)
                    for entry in model.channel_grid_entries
                    if entry.network is not None and entry.unit_id is not None
                }
            )
            dmx_universes = sorted(
                {
                    entry.universe
                    for entry in model.channel_grid_entries
                    if entry.universe is not None
                }
            )
            print(f"LOR controller addresses: {len(lor_addresses)}")
            for network, unit_id in lor_addresses:
                print(f"  {network} / {unit_id}")
            print(f"DMX universes: {len(dmx_universes)}")
            for universe in dmx_universes:
                print(f"  {universe}")
            print(f"Prop groups: {len(model.groups)}")
            for group in model.groups:
                name = group.name.value if group.name is not None else "(unnamed)"
                arrangement = (
                    group.arrangement.value if group.arrangement is not None else "unspecified"
                )
                print(f"  {name}: {len(group.members)} members, arrangement={arrangement}")
            print(f"Geometry points: {len(model.geometry_points)}")
            print(f"Unsupported prop/device constructs: {len(model.unsupported_constructs)}")
            print(f"Unrecognized elements (all levels): {len(model.unrecognized_elements)}")
            return 0
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
    except (LoreditError, LorprevError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
