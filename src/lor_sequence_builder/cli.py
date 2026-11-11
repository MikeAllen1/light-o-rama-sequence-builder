"""Command-line entry point for the Light-O-Rama S6 Sequence Builder."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from lor_sequence_builder.audio_analysis import AudioAnalysisError, analyze_audio
from lor_sequence_builder.evaluation import EvaluationError, evaluate
from lor_sequence_builder.loredit import LoreditError, read_loredit, write_loredit
from lor_sequence_builder.lorprev import LorprevError, read_lorprev
from lor_sequence_builder.pulse import PulseGenerationError, build_pulse_sequence


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
    pulse = commands.add_parser(
        "pulse", help="build a fixed-tempo beat-pulse walking-skeleton sequence"
    )
    pulse.add_argument("--preview", required=True, help="required standalone .lorprev file")
    pulse.add_argument("--template", required=True, help="matching native S6 .loredit template")
    pulse.add_argument("--bpm", required=True, type=int, help="fixed tempo in beats per minute")
    pulse.add_argument("--output", required=True, help="new output .loredit path")
    pulse.add_argument("--timeline-output", required=True, help="new deterministic Timeline .json path")
    pulse.add_argument(
        "--pulse-duration-cs",
        type=int,
        default=10,
        help="pulse duration in centiseconds (default: 10)",
    )
    analyze = commands.add_parser(
        "analyze-audio", help="analyze music and write JSON plus SVG diagnostics"
    )
    analyze.add_argument("audio", help="input audio file supported by FFmpeg")
    analyze.add_argument("--output-json", required=True, help="new versioned analysis JSON path")
    analyze.add_argument("--plot", required=True, help="new SVG diagnostic plot path")
    analyze.add_argument("--min-bpm", type=int, default=60, help="minimum tempo to search (default: 60)")
    analyze.add_argument("--max-bpm", type=int, default=200, help="maximum tempo to search (default: 200)")
    analyze.add_argument(
        "--beats-per-bar",
        type=int,
        choices=(3, 4),
        default=4,
        help="beats per bar for downbeats: 4 for most songs, 3 for waltz time (default: 4)",
    )
    score = commands.add_parser(
        "evaluate-analysis",
        help="score an analysis JSON against hand-placed timing grids in a sequence",
    )
    score.add_argument("--analysis", required=True, help="analysis JSON from analyze-audio")
    score.add_argument("--sequence", required=True, help="reference .loredit (read only)")
    score.add_argument("--beats-grid", help="name of the free timing grid marking beats")
    score.add_argument("--bars-grid", help="name of the free timing grid marking bar starts")
    score.add_argument("--sections-grid", help="name of the free timing grid marking sections")
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
        if options.command == "analyze-audio":
            report = analyze_audio(
                options.audio,
                options.output_json,
                options.plot,
                min_bpm=options.min_bpm,
                max_bpm=options.max_bpm,
                beats_per_bar=options.beats_per_bar,
            )
            analysis = report["analysis"]
            tempo = analysis["tempo"]
            print(f"Analysis: {options.output_json}")
            print(f"Diagnostic plot: {options.plot}")
            print(f"Duration: {report['audio']['duration_seconds']} seconds")
            print(f"Estimated tempo: {tempo['bpm']} BPM (confidence {tempo['confidence']})")
            print(f"Beats: {len(analysis['beats'])}")
            beat_events = analysis["beats"]
            if beat_events:
                mean_beat_confidence = sum(
                    event["confidence"] for event in beat_events
                ) / len(beat_events)
                print(f"Beat grid confidence: {mean_beat_confidence:.4f}")
            else:
                print("Beat grid confidence: unavailable (no beat grid)")
            print(f"Downbeats: {len(analysis['downbeats'])}")
            print(f"Onsets: {len(analysis['onsets'])}")
            print(f"Section candidates: {len(analysis['section_candidates'])}")
            print(f"Hard stops: {len(analysis['hard_stops'])}")
            return 0
        if options.command == "pulse":
            result = build_pulse_sequence(
                preview_path=options.preview,
                template_path=options.template,
                output_path=options.output,
                timeline_path=options.timeline_output,
                bpm=options.bpm,
                pulse_duration_centiseconds=options.pulse_duration_cs,
            )
            print(f"Sequence: {result.sequence_path}")
            print(f"Timeline: {result.timeline_path}")
            print(f"Supported props: {result.supported_prop_count}")
            print(f"Excluded props: {result.excluded_prop_count}")
            print(f"Beats: {result.beat_count}")
            print(f"Pulse events: {result.event_count}")
            for excluded in result.excluded_props:
                print(f"  Excluded prop {excluded.prop_id} ({excluded.name}): {excluded.reason}")
            return 0
        if options.command == "inspect-preview":
            model = read_lorprev(options.preview)
            edit_revision = model.revision.value if model.revision else "not recorded"
            print("Format: standalone LORPREV")
            print(f"Preview edit revision: {edit_revision}")
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
            print(f"Unsupported constructs: {len(model.unsupported_constructs)}")
            print(f"Unrecognized elements (all levels): {len(model.unrecognized_elements)}")
            return 0
        if options.command == "evaluate-analysis":
            results = evaluate(
                options.analysis,
                options.sequence,
                beats_grid=options.beats_grid,
                bars_grid=options.bars_grid,
                sections_grid=options.sections_grid,
            )
            for name, score in results.items():
                print(
                    f"{name}: {score.hits}/{score.reference} reference marks matched "
                    f"within {score.tolerance_seconds:g}s; {score.estimated} estimated; "
                    f"precision {score.precision:.2f}, recall {score.recall:.2f}, "
                    f"F-measure {score.f_measure:.2f}"
                )
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
    except (
        AudioAnalysisError,
        EvaluationError,
        LoreditError,
        LorprevError,
        PulseGenerationError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
