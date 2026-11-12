"""Command-line entry point for the Light-O-Rama S6 Sequence Builder."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from lor_sequence_builder.add_props import AddPropsError
from lor_sequence_builder.artifacts import write_new_text_atomically
from lor_sequence_builder.audio_analysis import AudioAnalysisError, analyze_audio
from lor_sequence_builder.choreography import ChoreographyError, load_choreography
from lor_sequence_builder.classifier import (
    ClassificationError,
    classification_report,
    classify_preview,
)
from lor_sequence_builder.evaluation import EvaluationError, evaluate
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.lms import LmsError, read_lms
from lor_sequence_builder.loredit import LoreditError, read_loredit, write_loredit
from lor_sequence_builder.lorprev import LorprevError, read_lorprev
from lor_sequence_builder.lyrics import LyricsError
from lor_sequence_builder.planner import LEVEL_NAMES, PlanningError
from lor_sequence_builder.pulse import PulseGenerationError, build_pulse_sequence, preview_element
from lor_sequence_builder.requirements_intake import (
    IntakeError,
    gather_requirements,
    saved_requirements_path,
    translator_from_environment,
)
from lor_sequence_builder.rules import (
    RULE_SPECS,
    RuleProfileError,
    check_choreography,
    display_from_preview,
    load_rule_set,
)
from lor_sequence_builder.sequence_writer import (
    RulesFailedError,
    SequenceWriteError,
    build_from_timeline,
)
from lor_sequence_builder.style import DEFAULT_STYLE, STYLES, Style
from lor_sequence_builder.style_learning import (
    StyleLearningError,
    learn,
    load_style_file,
    nearest,
    save,
    to_json,
)
from lor_sequence_builder.vocal_separation import SeparationError
from lor_sequence_builder.vocals import VocalAnalysisError

_RULES_HELP = "rule profile to layer over the built-in rules; repeat to stack, later wins"
_IGNORE_HELP = "do not use the requirements saved next to the preview"


def _profiles(preview: str | None, rules: list[str], ignore_saved: bool = False) -> tuple[str, ...]:
    """Saved requirements for this preview first, then explicit --rules files (later wins)."""
    layers: list[str] = []
    if preview is not None and not ignore_saved:
        saved = saved_requirements_path(preview)
        if saved.exists():
            print(f"Using your saved requirements: {saved.name}")
            layers.append(str(saved))
    return (*layers, *rules)


def _run_intake(preview: str, fresh: bool, guided: bool) -> None:
    display = display_from_preview(preview_element(read_lorprev(preview)))
    gather_requirements(preview, display, input, print, translator_from_environment(),
                        fresh=fresh, guided=guided)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lor-sequence-builder",
        description="Inspect and process verified Light-O-Rama S6 files.",
    )
    parser.epilog = ("Add --debug to any command to see the full details of an unexpected "
                     "problem.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("diagnostics", help="print version, system checks and recent errors, "
                        "to include when reporting a problem")
    inspect = commands.add_parser(
        "inspect", help="summarize an S5/S6 .loredit or an S4 .lms sequence")
    inspect.add_argument("sequence", help="input .loredit or .lms file")
    preview = commands.add_parser("inspect-preview", help="inspect a standalone LORPREV file")
    preview.add_argument("preview", help="input .lorprev file")
    roundtrip = commands.add_parser("roundtrip", help="write a loss-preserving LOREDIT copy")
    roundtrip.add_argument("sequence", help="input .loredit file")
    roundtrip.add_argument("output", help="new output .loredit path (must not exist)")
    pulse = commands.add_parser(
        "pulse", help="build a fixed-tempo beat-pulse sequence from a preview"
    )
    pulse.add_argument("--preview", required=True, help="required standalone .lorprev file")
    pulse.add_argument(
        "--duration-seconds",
        type=float,
        help="sequence length in seconds (required unless --template is given)",
    )
    pulse.add_argument(
        "--music-filename",
        help="audio file name to store in the sequence, as S6 records it "
        "(required unless --template is given)",
    )
    pulse.add_argument(
        "--template",
        help="deprecated: matching native S6 .loredit to copy instead of building from scratch",
    )
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
        "--vocals",
        help="experimental: vocals-only track of the same song, to guide beats where the "
        "band follows the singer",
    )
    analyze.add_argument(
        "--beats-per-bar",
        type=int,
        choices=(3, 4),
        default=4,
        help="beats per bar for downbeats: 4 for most songs, 3 for waltz time (default: 4)",
    )
    classify = commands.add_parser(
        "analyze-preview",
        help="identify each prop in a display preview (arches, trees, faces, ...) with evidence",
    )
    classify.add_argument("preview", help="input .lorprev file (read only)")
    classify.add_argument("--report", help="optional new JSON report path with full evidence")
    score = commands.add_parser(
        "evaluate-analysis",
        help="score an analysis JSON against hand-placed timing grids in a sequence",
    )
    score.add_argument("--analysis", required=True, help="analysis JSON from analyze-audio")
    score.add_argument("--sequence", required=True, help="reference .loredit (read only)")
    score.add_argument("--beats-grid", help="name of the free timing grid marking beats")
    score.add_argument("--bars-grid", help="name of the free timing grid marking bar starts")
    score.add_argument("--sections-grid", help="name of the free timing grid marking sections")
    check = commands.add_parser(
        "check-timeline", help="check a choreography Timeline against the rules"
    )
    check.add_argument("preview", help="input .lorprev file (read only)")
    check.add_argument("timeline", help="choreography Timeline .json")
    check.add_argument("--rules", action="append", default=[], help=_RULES_HELP)
    check.add_argument("--report", help="optional new JSON rule report path")
    check.add_argument("--ignore-saved-requirements", action="store_true", help=_IGNORE_HELP)
    build = commands.add_parser(
        "build-from-timeline",
        help="write a native S6 sequence from a Timeline that passes the rules",
    )
    build.add_argument("--preview", required=True, help="required standalone .lorprev file")
    build.add_argument("--timeline", required=True, help="choreography Timeline .json")
    build.add_argument(
        "--music-filename", required=True,
        help="audio file name to store in the sequence, inside the S6 audio folder",
    )
    build.add_argument("--output", required=True, help="new output .loredit path")
    build.add_argument("--report", required=True, help="new JSON rule report path")
    build.add_argument("--rules", action="append", default=[], help=_RULES_HELP)
    build.add_argument("--ignore-saved-requirements", action="store_true", help=_IGNORE_HELP)
    build.add_argument(
        "--ask-requirements", action="store_true",
        help="ask about specific requirements before building",
    )
    listing = commands.add_parser(
        "list-rules", help="show the rules and requirements that would apply"
    )
    listing.add_argument("--rules", action="append", default=[], help=_RULES_HELP)
    listing.add_argument("--preview", help="include the requirements saved for this preview")
    generate = commands.add_parser(
        "generate", help="build a full show sequence from a song and a display preview"
    )
    generate.add_argument(
        "--preview", required=True,
        help="the display: an S5/S6 .lorprev, or one of your S4 sequences (.lms), which "
             "makes an S4 show with the same channels")
    source = generate.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", help="song audio file supported by FFmpeg")
    source.add_argument("--analysis", help="existing analysis JSON from analyze-audio, "
                        "or a music review saved by the workspace")
    generate.add_argument("--output", required=True,
                          help="new output .loredit path (.lms for an S4 display)")
    generate.add_argument(
        "--music-filename",
        help="audio file name to store in the sequence, inside the S6 audio folder "
        "(default: the audio file's name)",
    )
    generate.add_argument(
        "--vocals",
        help="vocals-only audio for singing faces, a .vocals.json from an earlier run, or "
             "a WhisperX word file (.json) for lip-sync on the words",
    )
    generate.add_argument(
        "--singer",
        help="with a WhisperX word file: the speaker the faces sing (for example "
             "SPEAKER_00); default: the one with the most words",
    )
    generate.add_argument(
        "--no-vocals", action="store_true",
        help="do not split vocals out of the song, even when the add-on is installed",
    )
    generate.add_argument(
        "--vocal-beats", action="store_true",
        help="experimental: let the vocals guide beats where the band follows the singer",
    )
    generate.add_argument("--beats-per-bar", type=int, choices=(3, 4), default=4,
                          help="4 for most songs, 3 for waltz time (default: 4)")
    generate.add_argument("--rules", action="append", default=[], help=_RULES_HELP)
    generate.add_argument("--ignore-saved-requirements", action="store_true",
                          help=_IGNORE_HELP)
    generate.add_argument("--style", choices=sorted(STYLES), default=DEFAULT_STYLE,
                          help="character of the show: classic (default), energetic, elegant")
    generate.add_argument("--style-file",
                          help="a style learned from your own sequences (see learn-style); "
                               "used instead of --style")
    generate.add_argument("--lyrics",
                          help="timed lyrics (LRC, SRT, VTT, or a lyrics JSON) so props a line "
                               "names light when it is sung")
    asking = generate.add_mutually_exclusive_group()
    asking.add_argument("--ask-requirements", action="store_true",
                        help="always ask about specific requirements first")
    asking.add_argument("--no-ask", action="store_true",
                        help="never ask; use saved requirements only")
    lyrics = commands.add_parser(
        "lyrics",
        help="make timed lyrics for the workspace: import LRC/SRT/VTT or transcribe offline",
    )
    lyric_source = lyrics.add_mutually_exclusive_group(required=True)
    lyric_source.add_argument("--import", dest="import_file",
                              help="LRC, SRT or VTT file with timed lyric lines")
    lyric_source.add_argument("--audio", help="song or vocals-only audio to transcribe "
                              "(needs the lyrics add-on; every word is unverified)")
    lyrics.add_argument("--output", required=True, help="new lyrics JSON path")
    lyrics.add_argument("--model", default="base.en",
                        help="speech model for transcription (default: base.en)")
    intake = commands.add_parser(
        "requirements",
        help="tell the builder your specific requirements for a display, and save them",
    )
    intake.add_argument("preview", help="input .lorprev file (read only)")
    intake.add_argument("--guided", action="store_true",
                        help="answer questions instead of describing requirements")
    intake.add_argument("--fresh", action="store_true",
                        help="ignore saved requirements and start over")
    commands.add_parser("doctor", help="check this computer is ready, and how to fix what is not")
    demo = commands.add_parser(
        "demo", help="build a show for an invented yard and song, to try everything out")
    demo.add_argument("folder", help="new or empty folder for the demo files")
    batch = commands.add_parser(
        "generate-batch", help="build a show for every song in a folder (a whole playlist)")
    batch.add_argument("--preview", required=True, help="required standalone .lorprev file")
    batch.add_argument("--songs", required=True, help="folder of songs (read only)")
    batch.add_argument("--output", required=True, help="new or empty folder for the shows")
    batch.add_argument("--style", choices=sorted(STYLES), default=DEFAULT_STYLE,
                       help="character of every show: classic (default), energetic, elegant")
    batch.add_argument("--style-file",
                       help="a style learned from your own sequences (see learn-style)")
    batch.add_argument("--beats-per-bar", type=int, choices=(3, 4), default=4,
                       help="4 for most songs, 3 for waltz time (default: 4)")
    batch.add_argument("--rules", action="append", default=[], help=_RULES_HELP)
    batch.add_argument("--ignore-saved-requirements", action="store_true", help=_IGNORE_HELP)
    adding = commands.add_parser(
        "add-props",
        help="add new props to a finished sequence, leaving everything else as it is")
    adding.add_argument("--sequence", required=True,
                        help="the finished .loredit (S5/S6) or .lms (S4) (read only)")
    adding.add_argument("--preview",
                        help="S5/S6: the updated .lorprev with the new props (leave out when "
                             "they were added to the sequence's own preview)")
    adding.add_argument("--output", required=True, help="new sequence file")
    adding.add_argument("--audio", help="the song, for a closer fit (optional: without it "
                        "the beat and loud parts are read from the sequence)")
    adding.add_argument("--style-file", help="a learned style to use instead of the "
                        "sequence's own")
    adding.add_argument("--beats-per-bar", type=int, choices=(3, 4), default=4)
    adding.add_argument("--rules", action="append", default=[], help=_RULES_HELP)
    adding.add_argument("--ignore-saved-requirements", action="store_true", help=_IGNORE_HELP)
    learn = commands.add_parser(
        "learn-style",
        help="learn a style from sequences you made by hand (.loredit or .lms), on this "
             "computer")
    learn.add_argument("sequences", nargs="+", help="your own .loredit or .lms sequences "
                       "(read only; a few songs work best)")
    learn.add_argument("--name", default="My style", help="what to call the style")
    learn.add_argument("--output", help="new style file (.json) to use with --style-file")
    learn.add_argument("--keep", action="store_true",
                       help="also keep it in the app, where it shows up as a style choice")
    test = commands.add_parser(
        "display-test",
        help="make a 10-second test that lights every prop in turn, to check the display")
    test.add_argument("--preview", required=True, help="input .lorprev file (read only)")
    test.add_argument("--output", required=True, help="new or empty folder for the test files")
    return parser


def _write_cli_json_report(
    path: str | Path, payload: dict[str, object], error_type: type[ValueError]
) -> None:
    destination = Path(path)
    try:
        write_new_text_atomically(destination, json.dumps(payload, indent=2) + "\n")
    except FileExistsError as exc:
        raise error_type(f"Report already exists: {destination}") from exc
    except OSError as exc:
        raise error_type(f"Cannot write report atomically: {destination}") from exc


def _check_timeline(
    preview: str, timeline: str, rules: list[str], report_path: str | None, ignore_saved: bool
) -> int:
    if report_path is not None and Path(report_path).exists():
        raise RuleProfileError(f"Report already exists: {report_path}")
    rule_set = load_rule_set(_profiles(preview, rules, ignore_saved))
    report = check_choreography(
        preview_element(read_lorprev(preview)), load_choreography(timeline), rule_set
    )
    print(report.format_text())
    if report_path is not None:
        _write_cli_json_report(report_path, report.to_dict(), RuleProfileError)
        print(f"Report: {report_path}")
    return 0 if report.ok else 1


SONG_SUFFIXES = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff",
                 ".mp4")


def _chosen_style(options: argparse.Namespace) -> str | Style:
    if options.style_file:
        return load_style_file(options.style_file)
    return str(options.style)


def _add_props(options: argparse.Namespace) -> int:
    from lor_sequence_builder.add_props import add_props

    display = options.preview or options.sequence
    rule_set = load_rule_set(
        _profiles(display, options.rules, options.ignore_saved_requirements))
    style = load_style_file(options.style_file) if options.style_file else None
    result = add_props(options.sequence, options.output, rule_set,
                       preview_path=options.preview, audio_path=options.audio, style=style,
                       beats_per_bar=options.beats_per_bar, progress=print)
    if not result.added:
        print("No new prop could be given a part (see the requirements).")
    else:
        print(f"Added {len(result.added)} prop(s): {', '.join(result.added)}")
    for note in (*result.notes, *(n for n in result.plan.notes
                                  if n.startswith("Arrangement"))):
        print(f"  {note}")
    if result.quality is not None:
        print(f"  Whole show, old and new props together: {result.quality.summary()}")
        for finding in result.quality.findings:
            if finding.status != "good":
                print(f"    - {finding.message}")
    print(f"Wrote {result.sequence_path}. Everything that was already in the sequence is "
          "unchanged.")
    return 0


def _learn_style(options: argparse.Namespace) -> int:
    if options.output and Path(options.output).exists():
        print(f"error: refusing to overwrite {options.output}", file=sys.stderr)
        return 2
    style, habits, changes = learn(options.sequences, options.name)
    print(f"Learned {style.name!r} from {habits.sequences} sequence(s), "
          f"{habits.effects} effects:")
    beat_source = "timing grid" if habits.beat_from_grid else "effect spacing"
    print(f"  Beat: {habits.beat / 100:.2f} s (from the {beat_source})")
    print(f"  Lights stay on: {habits.hold_beats:.1f} beats (typical)")
    print(f"  Fades: {habits.fade_share:.0%} of effects; twinkle: {habits.twinkle_share:.0%}")
    print(f"  Brightness: {habits.brightness}%; yard lit on average: {habits.lit_share:.0%}")
    for change in changes:
        print(f"  - {change}")
    if options.output:
        Path(options.output).write_text(to_json(style, habits, nearest(habits)),
                                        encoding="utf-8")
        print(f"Saved {options.output}; use it with: generate ... --style-file "
              f"{options.output}")
    if options.keep:
        key = save(style, habits)
        print(f"Kept in the app as {style.name!r} ({key}).")
    if not options.output and not options.keep:
        print("Nothing saved; add --output style.json or --keep.")
    return 0


def _generate_batch(options: argparse.Namespace) -> int:
    songs = sorted(path for path in Path(options.songs).iterdir()
                   if path.is_file() and path.suffix.lower() in SONG_SUFFIXES)
    if not songs:
        print(f"error: no songs in {options.songs}", file=sys.stderr)
        return 2
    target = Path(options.output)
    if target.exists() and any(target.iterdir()):
        print(f"error: choose an empty or new folder for the shows: {target}", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    rule_set = load_rule_set(
        _profiles(options.preview, options.rules, options.ignore_saved_requirements))
    style = _chosen_style(options)
    failed: list[str] = []
    for number, song in enumerate(songs, 1):
        print(f"[{number}/{len(songs)}] {song.name}")
        try:
            suffix = ".lms" if str(options.preview).lower().endswith(".lms") else ".loredit"
            show = generate_show(options.preview, target / f"{song.stem}{suffix}", rule_set,
                                 audio_path=song, music_filename=song.name,
                                 beats_per_bar=options.beats_per_bar, separate=False,
                                 style=style)
        except RulesFailedError as error:
            failed.append(song.name)
            print(f"  not built: {error}")
            continue
        except (ValueError, OSError) as error:
            failed.append(song.name)
            print(f"  not built: {error}")
            continue
        print(f"  {show.sequence_path.name}: {len(show.plan.sections)} parts, "
              f"{len(show.plan.used_props)} props")
    print(f"{len(songs) - len(failed)} of {len(songs)} shows built in {target}.")
    print("Copy each song into S6's audio folder with the same name, then open its .loredit.")
    return 1 if failed else 0


def _generate(options: argparse.Namespace) -> int:
    saved = saved_requirements_path(options.preview)
    interactive = sys.stdin.isatty()
    if options.ask_requirements or (
        not options.no_ask and not options.ignore_saved_requirements
        and interactive and not saved.exists()
    ):
        _run_intake(options.preview, fresh=False, guided=False)
    rule_set = load_rule_set(
        _profiles(options.preview, options.rules, options.ignore_saved_requirements)
    )
    try:
        show = generate_show(
            options.preview, options.output, rule_set,
            audio_path=options.audio, analysis_path=options.analysis,
            music_filename=options.music_filename, beats_per_bar=options.beats_per_bar,
            vocals_path=options.vocals, separate=False if options.no_vocals else None,
            progress=print, vocal_beats=options.vocal_beats, style=_chosen_style(options),
            lyrics_path=options.lyrics, singer=options.singer,
        )
    except RulesFailedError as failed:
        print(failed.report.format_text())
        print(f"error: {failed}. This is a planner bug; please report it.", file=sys.stderr)
        return 1
    plan = show.plan
    print("Sections:")
    for section in plan.sections:
        print(f"  {_time(section.start_centisecond)}-{_time(section.end_centisecond)} "
              f"{section.label} ({LEVEL_NAMES[section.level]} energy)")
    print(f"Props used: {len(plan.used_props)}")
    if plan.skipped_props:
        print("Props left out:")
        for skipped in plan.skipped_props:
            print(f"  {skipped.name}: {skipped.reason}")
    for note in plan.notes:
        print(f"Note: {note}")
    print(show.report.format_text())
    print(f"Sequence: {show.sequence_path}")
    print(f"Timeline: {show.timeline_path}")
    print(f"Plan: {show.plan_path}")
    print(f"Plan picture: {show.picture_path}")
    print(f"Rule report: {show.report_path}")
    print(f"Show report (open in a browser): {show.summary_path}")
    if show.analysis_path is not None:
        print(f"Analysis: {show.analysis_path}")
    if show.vocals_path is not None:
        print(f"Vocals: {show.vocals_path}")
    if show.vocals_note is not None:
        print(f"Note: {show.vocals_note}")
    return 0


def _time(centiseconds: int) -> str:
    return f"{centiseconds // 6000}:{(centiseconds // 100) % 60:02d}"


def _list_rules(rules: list[str], preview: str | None) -> int:
    rule_set = load_rule_set(_profiles(preview, rules))
    print("Profiles: " + ", ".join(rule_set.sources))
    print("\nBuilt-in rules")
    for rule_id, spec in RULE_SPECS.items():
        settings = rule_set.rules[rule_id]
        lock = ", locked" if spec.locked else ""
        tunables = "".join(f"; {key}={value}" for key, value in settings.params.items())
        print(f"  {rule_id} [{settings.severity}{lock}]: {spec.title}{tunables}")
    print(f"\nDisplay requirements ({len(rule_set.requirements)})")
    for requirement in rule_set.requirements:
        print(f"  {requirement.requirement_id} [{requirement.severity}] {requirement.type}: "
              f"{requirement.props.describe()} (from {requirement.source})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command; problems end in a plain message, never a Python traceback (add
    --debug, or set LOR_DEBUG=1, to see the full details)."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    debug = "--debug" in arguments or bool(os.environ.get("LOR_DEBUG"))
    arguments = [argument for argument in arguments if argument != "--debug"]
    try:
        return _main(arguments)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as error:
        if debug:
            raise
        from lor_sequence_builder.diagnostics import log_folder, log_unexpected

        reference = log_unexpected(error, "command " + (arguments[0] if arguments else ""))
        print(f"error: something went wrong inside the program (reference {reference}). The "
              f"details are in {log_folder() / 'workspace.log'}. Run "
              "'lor-sequence-builder diagnostics' and include its output when you report it, "
              "or add --debug to see them here.", file=sys.stderr)
        return 1


def _main(arguments: list[str]) -> int:
    parser = _build_parser()
    if not arguments:
        parser.print_help()
        return 0
    options = parser.parse_args(arguments)
    if options.command is None:
        parser.print_help()
        return 0
    try:
        if options.command == "diagnostics":
            from lor_sequence_builder.diagnostics import report as diagnostics_report

            print(diagnostics_report(), end="")
            return 0
        if options.command == "doctor":
            from lor_sequence_builder.doctor import print_checks, run_checks

            return print_checks(run_checks())
        if options.command == "add-props":
            return _add_props(options)
        if options.command == "learn-style":
            return _learn_style(options)
        if options.command == "demo":
            from lor_sequence_builder.demo import build_demo

            try:
                built = build_demo(options.folder)
            except FileExistsError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"Demo show for an invented yard and song, in {Path(options.folder)}:")
            print("  Preview: Demo Yard.lorprev")
            print("  Song: Demo Song.wav")
            print(f"  Sequence: {built.sequence_path.name}")
            print(f"  Show report (open in a browser): {built.summary_path.name}")
            print(f"  Plan picture: {built.picture_path.name}")
            print("Every rule passed." if built.report.ok else "Some rules did not pass.")
            return 0
        if options.command == "display-test":
            from lor_sequence_builder.display_test import build_display_test

            try:
                made = build_display_test(options.preview, options.output)
            except FileExistsError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"Display test in {Path(options.output)}:")
            print(f"  Sequence: {made.sequence_path.name}")
            print(f"  Sound (copy it into S6's audio folder): {made.sound_path.name}")
            print(f"  What to watch: {made.notes_path.name}")
            return 0
        if options.command == "analyze-audio":
            report = analyze_audio(
                options.audio,
                options.output_json,
                options.plot,
                min_bpm=options.min_bpm,
                max_bpm=options.max_bpm,
                beats_per_bar=options.beats_per_bar,
                vocals_path=options.vocals,
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
            if "beat_guidance" in analysis:
                stretches = analysis["beat_guidance"]["stretches"]
                print(f"Vocal-guided stretches: {len(stretches)}")
                for stretch in stretches:
                    print(f"  {stretch['start']:.1f}s to {stretch['end']:.1f}s")
            return 0
        if options.command == "pulse":
            if options.duration_seconds is not None and not math.isfinite(
                options.duration_seconds
            ):
                raise PulseGenerationError("Duration must be a finite number of seconds")
            total_centiseconds = (
                round(options.duration_seconds * 100)
                if options.duration_seconds is not None
                else None
            )
            result = build_pulse_sequence(
                preview_path=options.preview,
                template_path=options.template,
                output_path=options.output,
                timeline_path=options.timeline_output,
                bpm=options.bpm,
                pulse_duration_centiseconds=options.pulse_duration_cs,
                total_centiseconds=total_centiseconds,
                music_filename=options.music_filename,
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
        if options.command == "analyze-preview":
            return _analyze_preview(options.preview, options.report)
        if options.command == "check-timeline":
            return _check_timeline(options.preview, options.timeline, options.rules,
                                   options.report, options.ignore_saved_requirements)
        if options.command == "list-rules":
            return _list_rules(options.rules, options.preview)
        if options.command == "generate":
            return _generate(options)
        if options.command == "generate-batch":
            return _generate_batch(options)
        if options.command == "lyrics":
            from lor_sequence_builder.lyrics import import_lyrics, transcribe_lyrics, write_lyrics

            if options.import_file:
                lyric_document = import_lyrics(options.import_file)
            else:
                print("Transcribing offline; words are unverified until you review them.")
                lyric_document = transcribe_lyrics(options.audio, options.model)
            lyrics_path = write_lyrics(lyric_document, options.output)
            print(f"Lyric lines: {len(lyric_document['lines'])} ({lyric_document['source']})")
            print(f"Lyrics: {lyrics_path}")
            return 0
        if options.command == "requirements":
            _run_intake(options.preview, options.fresh, options.guided)
            return 0
        if options.command == "build-from-timeline":
            timeline = load_choreography(options.timeline)
            if options.ask_requirements:
                _run_intake(options.preview, fresh=False, guided=False)
            rule_set = load_rule_set(
                _profiles(options.preview, options.rules, options.ignore_saved_requirements)
            )
            try:
                written = build_from_timeline(
                    options.preview,
                    timeline,
                    rule_set,
                    options.music_filename,
                    options.output,
                    options.report,
                )
            except RulesFailedError as failed:
                print(failed.report.format_text())
                print(f"error: {failed}", file=sys.stderr)
                return 1
            print(written.report.format_text())
            print(f"Sequence: {written.sequence_path}")
            print(f"Report: {written.report_path}")
            print(f"Effects: {written.effect_count}")
            print(f"Excluded props: {len(written.excluded_props)}")
            for excluded in written.excluded_props:
                print(
                    f"  Excluded prop {excluded.prop_id} ({excluded.name}): "
                    f"{excluded.reason}"
                )
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
        if options.command == "inspect" and str(options.sequence).lower().endswith(".lms"):
            s4 = read_lms(options.sequence)
            print(f"Format: S4 LMS v{s4.save_file_version}")
            print(f"Duration: {s4.total_centiseconds} centiseconds")
            print(f"Channels: {len(s4.channels)} "
                  f"({sum(1 for c in s4.channels if c.is_lor)} LOR with unit and circuit)")
            print(f"Channel groups: {len(s4.groups)}")
            print(f"Effects: {sum(c.effect_count for c in s4.channels)}")
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
        ChoreographyError,
        ClassificationError,
        EvaluationError,
        IntakeError,
        LyricsError,
        PlanningError,
        SeparationError,
        VocalAnalysisError,
        RuleProfileError,
        SequenceWriteError,
        LoreditError,
        LmsError,
        LorprevError,
        PulseGenerationError,
        StyleLearningError,
        AddPropsError,
        OSError,
        MemoryError,
    ) as exc:
        from lor_sequence_builder.diagnostics import friendly

        print(f"error: {friendly(exc)}", file=sys.stderr)
        return 2


def _analyze_preview(preview_path: str, report_path: str | None) -> int:
    model = read_lorprev(preview_path)
    if report_path is not None and Path(report_path).exists():
        raise ClassificationError(f"Report already exists: {report_path}")
    invalid_groups = [
        item for item in model.unsupported_constructs
        if item.kind in {"prop group identity", "prop group member"}
    ]
    if invalid_groups:
        details = "; ".join(
            f"{item.source.locator}: {item.detail}" for item in invalid_groups
        )
        raise ClassificationError(
            f"Preview has invalid PropGroup identity or membership; cannot classify: {details}"
        )
    results = classify_preview(preview_element(model))
    order = {"confident": 0, "review": 1, "unknown": 2}
    print(f"Props: {len(results)}")
    for status in ("confident", "review", "unknown"):
        group = [r for r in results if r.status == status]
        if not group:
            continue
        print(f"\n{status.upper()} ({len(group)})")
        for item in sorted(group, key=lambda r: (order[r.status], r.role, r.position_in_row or 0, r.name)):
            role = item.role.replace("_", " ")
            extras = []
            if item.position_in_row is not None:
                where = f"in group {item.group!r}" if item.group else "in a row"
                extras.append(f"#{item.position_in_row} of {item.row_size} {where}")
            if item.direction not in {"not applicable", "unknown"}:
                extras.append(item.direction.replace("_", " "))
            if not item.color_capability.can_show_single_color and item.color_capability.kind == "combined_colors":
                extras.append("combined colors")
            if item.sequencing_support != "supported":
                extras.append(item.sequencing_support)
            suffix = f" [{'; '.join(extras)}]" if extras else ""
            print(f"  {item.name}: {role} ({item.confidence:.2f}){suffix}")
            for note in item.review_notes:
                print(f"      - {note}")
    print("\nTo correct a conclusion, fix the prop in the S6 Preview Editor and run this again.")
    if report_path is not None:
        report = classification_report(results, Path(preview_path).name)
        _write_cli_json_report(report_path, report, ClassificationError)
        print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
