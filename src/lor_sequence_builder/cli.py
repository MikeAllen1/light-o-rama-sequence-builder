"""Command-line interface for Light-O-Rama Sequence Builder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audio import AudioAnalysisError, analyze_audio
from .loredit import LoreditError, extract_display, inspect_loredit
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

    display_parser = subparsers.add_parser(
        "import-display",
        help="Extract prop and group mappings from an S6 .LOREDIT file.",
    )
    display_parser.add_argument("sequence_file", type=Path)
    display_parser.add_argument(
        "--output",
        type=Path,
        help="Write the extracted display mapping JSON to this file.",
    )

    audio_parser = subparsers.add_parser(
        "analyze-audio",
        help="Detect tempo, beat candidates, onsets, and energy from audio.",
    )
    audio_parser.add_argument("audio_file", type=Path)
    audio_parser.add_argument(
        "--output",
        type=Path,
        help="Write the full analysis JSON to this file.",
    )

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

        if args.command == "import-display":
            result = extract_display(args.sequence_file)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"Display mapping written to: {args.output}")
            else:
                print(json.dumps(result, indent=2))
            print(
                f"Props: {result['preview_prop_count']} | "
                f"Sequence props: {result['sequence_prop_count']} | "
                f"Groups: {result['group_count']} | "
                f"Unmapped sequence props: {len(result['unmapped_sequence_props'])}"
            )
            return 0

        if args.command == "analyze-audio":
            result = analyze_audio(args.audio_file)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"Analysis written to: {args.output}")
            print(
                f"Duration: {result['duration_ms'] / 1000:.2f}s | "
                f"Tempo candidate: {result['tempo_bpm']:.2f} BPM | "
                f"Beat candidates: {result['beat_count']} | "
                f"Onsets: {result['onset_count']}"
            )
            print(
                "Beat interval regularity: "
                f"{result['interval_regularity']:.3f} "
                "(diagnostic only; not a correctness score)"
            )
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

    except (
        OSError,
        json.JSONDecodeError,
        LoreditError,
        AudioAnalysisError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
