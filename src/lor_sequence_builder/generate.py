"""Song plus display in, native sequence out.

The display is an S5/S6 preview (``.lorprev``), which makes an S5/S6 ``.loredit``,
or one of the user's own S4 sequences (``.lms``), which makes a new S4 ``.lms``
with the same channels.

``generate`` runs the whole pipeline: analyze the audio (or reuse an analysis),
read the display from the preview, plan the show with the active rules and
requirements, check the plan, and write the sequence. Next to the sequence it
writes the Timeline, the plan summary, and the rule report, so every decision
can be reviewed. Inputs are never modified and no output is overwritten.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lor_sequence_builder.artifacts import write_new_text_atomically
from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.choreography import choreography_json
from lor_sequence_builder.classifier import classify_preview
from lor_sequence_builder.evaluation import load_analysis
from lor_sequence_builder.lms import LmsError, display_from_lms, preview_bytes, read_lms
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.lyrics import read_lyrics
from lor_sequence_builder.plan_preview import plan_svg
from lor_sequence_builder.planner import Plan, display_has_mouths, plan_show
from lor_sequence_builder.progress import step as report_step
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.rules import RuleReport, RuleSet, display_from_preview
from lor_sequence_builder.sequence_writer import (
    RulesFailedError,
    SequenceWriteError,
    build_from_timeline,
    build_lms_from_timeline,
)
from lor_sequence_builder.show_report import ReportInputs, render_report
from lor_sequence_builder.style import Style, get_style
from lor_sequence_builder.timeline import ExcludedProp
from lor_sequence_builder.vocal_separation import separate_vocals, separation_available
from lor_sequence_builder.vocals import analyze_vocals, load_vocals, lyrics_from_words


@dataclass(frozen=True, slots=True)
class GeneratedShow:
    sequence_path: Path
    timeline_path: Path
    plan_path: Path
    picture_path: Path
    report_path: Path
    summary_path: Path
    analysis_path: Path | None
    vocals_path: Path | None
    vocals_note: str | None
    plan: Plan
    report: RuleReport


def output_paths(output_path: str | Path) -> dict[str, Path]:
    output = Path(output_path)
    stem = output.with_suffix("")
    return {
        "sequence": output,
        "timeline": stem.with_name(stem.name + ".timeline.json"),
        "plan": stem.with_name(stem.name + ".plan.json"),
        "picture": stem.with_name(stem.name + ".plan.svg"),
        "report": stem.with_name(stem.name + ".rules.json"),
        "summary": stem.with_name(stem.name + ".report.html"),
        "analysis": stem.with_name(stem.name + ".analysis.json"),
        "vocals": stem.with_name(stem.name + ".vocals.json"),
        "vocals_audio": stem.with_name(stem.name + ".vocals.wav"),
        "plot": stem.with_name(stem.name + ".analysis.svg"),
    }


def _write_new(path: Path, text: str) -> None:
    try:
        write_new_text_atomically(path, text)
    except OSError as exc:
        raise SequenceWriteError(f"Cannot write {path}: {exc}") from exc


def _plan_document(plan: Plan, report: RuleReport | None, analysis: dict[str, Any]) -> str:
    data = {
        "audio": analysis.get("audio", {}).get("file_name"),
        "tempo_bpm": analysis.get("analysis", {}).get("tempo", {}).get("bpm"),
        **plan.to_dict(),
        "rules": None if report is None else report.to_dict()["summary"],
    }
    return json.dumps(data, indent=2) + "\n"


def generate_show(
    preview_path: str | Path,
    output_path: str | Path,
    rule_set: RuleSet,
    audio_path: str | Path | None = None,
    analysis_path: str | Path | None = None,
    music_filename: str | None = None,
    beats_per_bar: int = 4,
    vocals_path: str | Path | None = None,
    separate: bool | None = None,
    progress: Callable[[str], None] | None = None,
    vocal_beats: bool = False,
    style: str | Style | None = None,
    lyrics_path: str | Path | None = None,
    singer: str | None = None,
) -> GeneratedShow:
    """Build a show. ``preview_path`` is a ``.lorprev`` (S5/S6 output, ``.loredit``)
    or the user's own S4 sequence (``.lms`` output with the same channels). Vocals for singing faces come from ``vocals_path`` (a vocals-only
    audio file, or a vocals JSON from an earlier run); otherwise, when the display
    has face mouths, they are split out of the song if the add-on is installed.
    ``separate`` forces separation on (True) or off (False)."""
    if (audio_path is None) == (analysis_path is None):
        raise SequenceWriteError("Give either the audio file or an existing analysis, not both")
    try:
        chosen_style = style if isinstance(style, Style) else get_style(style)
    except ValueError as exc:
        raise SequenceWriteError(str(exc)) from exc
    lyrics = read_lyrics(lyrics_path) if lyrics_path is not None else None
    with ExitStack() as stack:
        return _generate(stack, preview_path, output_path, rule_set, audio_path, analysis_path,
                         music_filename, beats_per_bar, vocals_path, separate, progress,
                         vocal_beats, chosen_style, lyrics, singer)


def _generate(
    stack: ExitStack,
    preview_path: str | Path,
    output_path: str | Path,
    rule_set: RuleSet,
    audio_path: str | Path | None,
    analysis_path: str | Path | None,
    music_filename: str | None,
    beats_per_bar: int,
    vocals_path: str | Path | None,
    separate: bool | None,
    progress: Callable[[str], None] | None,
    vocal_beats: bool,
    chosen_style: Style,
    lyrics: dict[str, Any] | None,
    singer: str | None = None,
) -> GeneratedShow:
    paths = output_paths(output_path)
    s4 = Path(preview_path).suffix.lower() == ".lms"
    expected = ".lms" if s4 else ".loredit"
    if paths["sequence"].suffix.lower() != expected:
        raise SequenceWriteError(
            "An S4 display (.lms) makes an S4 sequence: use the .lms extension" if s4
            else "Sequence output must use the .loredit extension")
    lms_template = None
    lms_display = None
    if s4:
        try:
            lms_template = read_lms(preview_path)
            lms_display = display_from_lms(lms_template, Path(preview_path).stem)
        except LmsError as exc:
            raise SequenceWriteError(str(exc)) from exc
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="lor-s4-")))
        preview_path = folder / "display.lorprev"
        preview_path.write_bytes(preview_bytes(lms_display))
    needed = ["sequence", "timeline", "plan", "picture", "report", "summary"]
    if audio_path is not None:
        needed += ["analysis", "plot"]
    preview = preview_element(read_lorprev(preview_path))
    display = display_from_preview(preview)
    wants_vocals = display_has_mouths(display, rule_set)
    will_separate = (
        vocals_path is None and audio_path is not None and wants_vocals
        and (separate is True or (separate is None and separation_available()))
    )
    if separate is True and audio_path is None:
        raise SequenceWriteError("Separating vocals needs the song's audio file (--audio)")
    if will_separate or (vocals_path is not None
                         and Path(vocals_path).suffix.lower() != ".json"):
        needed.append("vocals")
    if will_separate:
        needed.append("vocals_audio")
    for name in needed:
        if paths[name].exists():
            raise SequenceWriteError(f"Output already exists; refusing to overwrite: "
                                     f"{paths[name]}")

    paths["sequence"].parent.mkdir(parents=True, exist_ok=True)
    vocals_audio: Path | None = None
    if vocals_path is not None and Path(vocals_path).suffix.lower() != ".json":
        vocals_audio = Path(vocals_path)
    elif will_separate:
        assert audio_path is not None
        if progress is not None:
            progress("Splitting the vocals out of the song for the singing faces. This can "
                     "take a few minutes; the vocals are saved so later runs can reuse them "
                     "with --vocals.")
        report_step("Splitting the vocals out of the song for the singing faces", 0.03,
                    slow=True)
        vocals_audio = separate_vocals(audio_path, paths["vocals_audio"])

    if audio_path is not None:
        # Vocal-guided beats are opt-in: on real songs they can hurt a steady band.
        analyze_audio(audio_path, paths["analysis"], paths["plot"],
                      beats_per_bar=beats_per_bar,
                      vocals_path=vocals_audio if vocal_beats else None)
        analysis = load_analysis(paths["analysis"])
        written_analysis: Path | None = paths["analysis"]
        default_music = Path(audio_path).name
    else:
        assert analysis_path is not None
        analysis = load_analysis(analysis_path)
        written_analysis = None
        default_music = str(analysis.get("audio", {}).get("file_name") or "")
    if lyrics is not None:
        # Timed lyrics let the planner cue the props a line names.
        analysis = {**analysis, "lyrics": lyrics}

    vocals: dict[str, Any] | None = None
    written_vocals: Path | None = None
    vocals_note: str | None = None
    if vocals_audio is not None:
        source = "separated on this PC" if vocals_path is None else "supplied vocals file"
        report_step("Following the singing", 0.75)
        vocals = analyze_vocals(vocals_audio, paths["vocals"], source)
        written_vocals = paths["vocals"]
    elif vocals_path is not None:
        vocals = load_vocals(vocals_path, singer)
        words = lyrics_from_words(vocals_path) if lyrics is None else None
        if words is not None:
            # The word file's lyrics also cue the props the words name.
            analysis = {**analysis, "lyrics": words}
    elif wants_vocals:
        vocals_note = (
            "Face mouths stay still: pass a vocals-only file with --vocals, or install "
            "the vocals add-on (uv sync --extra vocals) to split vocals out of the song."
        )
    report_step("Planning the show", 0.8 if vocals_audio is not None else 0.3)
    plan = plan_show(analysis, display, rule_set, vocals, chosen_style)
    paths["sequence"].parent.mkdir(parents=True, exist_ok=True)
    _write_new(paths["timeline"], choreography_json(plan.choreography))
    _write_new(paths["picture"], plan_svg(plan, display, f"{paths['sequence'].stem}: planned show"))
    report_step("Checking the rules and writing the sequence",
                0.88 if vocals_audio is not None else 0.6)
    try:
        if lms_template is not None and lms_display is not None:
            written = build_lms_from_timeline(
                preview_path, lms_template, lms_display.prop_channels, plan.choreography,
                rule_set, music_filename or default_music, paths["sequence"], paths["report"],
                tuple(ExcludedProp("", name, reason) for name, reason in lms_display.excluded),
            )
        else:
            beats = tuple(round(float(b["time"]) * 100)
                          for b in analysis.get("analysis", {}).get("beats", [])
                          if isinstance(b, dict) and isinstance(b.get("time"), int | float))
            written = build_from_timeline(
                preview_path, plan.choreography, rule_set, music_filename or default_music,
                paths["sequence"], paths["report"], beats=beats,
            )
    except RulesFailedError as failed:
        _write_new(paths["plan"], _plan_document(plan, failed.report, analysis))
        raise
    _write_new(paths["plan"], _plan_document(plan, written.report, analysis))
    music = music_filename or default_music
    report_step("Writing the show report", 0.95 if vocals_audio is not None else 0.85)
    _write_new(paths["summary"], render_report(ReportInputs(
        title=paths["sequence"].stem, music_filename=music, display=display,
        classifications=classify_preview(preview), plan=plan, report=written.report,
        duration_centiseconds=plan.choreography.duration_centiseconds,
        files={"Sequence": paths["sequence"].name, "Plan picture": paths["picture"].name,
               "Rule details": paths["report"].name, "Timeline": paths["timeline"].name},
    )))
    return GeneratedShow(paths["sequence"], paths["timeline"], paths["plan"], paths["picture"],
                         paths["report"], paths["summary"], written_analysis, written_vocals,
                         vocals_note, plan, written.report)
