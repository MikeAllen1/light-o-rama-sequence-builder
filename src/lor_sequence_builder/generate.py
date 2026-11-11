"""Song plus preview in, native S6 sequence out.

``generate`` runs the whole pipeline: analyze the audio (or reuse an analysis),
read the display from the preview, plan the show with the active rules and
requirements, check the plan, and write the sequence. Next to the sequence it
writes the Timeline, the plan summary, and the rule report, so every decision
can be reviewed. Inputs are never modified and no output is overwritten.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lor_sequence_builder.audio_analysis import analyze_audio
from lor_sequence_builder.choreography import choreography_json
from lor_sequence_builder.evaluation import load_analysis
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.plan_preview import plan_svg
from lor_sequence_builder.planner import Plan, display_has_mouths, plan_show
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.rules import RuleReport, RuleSet, display_from_preview
from lor_sequence_builder.sequence_writer import (
    RulesFailedError,
    SequenceWriteError,
    build_from_timeline,
)
from lor_sequence_builder.vocal_separation import separate_vocals, separation_available
from lor_sequence_builder.vocals import analyze_vocals, load_vocals


@dataclass(frozen=True, slots=True)
class GeneratedShow:
    sequence_path: Path
    timeline_path: Path
    plan_path: Path
    picture_path: Path
    report_path: Path
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
        "analysis": stem.with_name(stem.name + ".analysis.json"),
        "vocals": stem.with_name(stem.name + ".vocals.json"),
        "vocals_audio": stem.with_name(stem.name + ".vocals.wav"),
        "plot": stem.with_name(stem.name + ".analysis.svg"),
    }


def _write_new(path: Path, text: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
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
) -> GeneratedShow:
    """Build a show. Vocals for singing faces come from ``vocals_path`` (a vocals-only
    audio file, or a vocals JSON from an earlier run); otherwise, when the display
    has face mouths, they are split out of the song if the add-on is installed.
    ``separate`` forces separation on (True) or off (False)."""
    if (audio_path is None) == (analysis_path is None):
        raise SequenceWriteError("Give either the audio file or an existing analysis, not both")
    paths = output_paths(output_path)
    if paths["sequence"].suffix.lower() != ".loredit":
        raise SequenceWriteError("Sequence output must use the .loredit extension")
    needed = ["sequence", "timeline", "plan", "picture", "report"]
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

    if audio_path is not None:
        paths["sequence"].parent.mkdir(parents=True, exist_ok=True)
        analyze_audio(audio_path, paths["analysis"], paths["plot"],
                      beats_per_bar=beats_per_bar)
        analysis = load_analysis(paths["analysis"])
        written_analysis: Path | None = paths["analysis"]
        default_music = Path(audio_path).name
    else:
        assert analysis_path is not None
        analysis = load_analysis(analysis_path)
        written_analysis = None
        default_music = str(analysis.get("audio", {}).get("file_name") or "")

    vocals: dict[str, Any] | None = None
    written_vocals: Path | None = None
    vocals_note: str | None = None
    if vocals_path is not None:
        if Path(vocals_path).suffix.lower() == ".json":
            vocals = load_vocals(vocals_path)
        else:
            vocals = analyze_vocals(vocals_path, paths["vocals"], "supplied vocals file")
            written_vocals = paths["vocals"]
    elif will_separate:
        assert audio_path is not None
        if progress is not None:
            progress("Splitting the vocals out of the song for the singing faces. This can "
                     "take a few minutes; the vocals are saved so later runs can reuse them "
                     "with --vocals.")
        separate_vocals(audio_path, paths["vocals_audio"])
        vocals = analyze_vocals(paths["vocals_audio"], paths["vocals"], "separated on this PC")
        written_vocals = paths["vocals"]
    elif wants_vocals:
        vocals_note = (
            "Face mouths stay still: pass a vocals-only file with --vocals, or install "
            "the vocals add-on (uv sync --extra vocals) to split vocals out of the song."
        )
    plan = plan_show(analysis, display, rule_set, vocals)
    paths["sequence"].parent.mkdir(parents=True, exist_ok=True)
    _write_new(paths["timeline"], choreography_json(plan.choreography))
    _write_new(paths["picture"], plan_svg(plan, display, f"{paths['sequence'].stem}: planned show"))
    try:
        written = build_from_timeline(
            preview_path, plan.choreography, rule_set, music_filename or default_music,
            paths["sequence"], paths["report"],
        )
    except RulesFailedError as failed:
        _write_new(paths["plan"], _plan_document(plan, failed.report, analysis))
        raise
    _write_new(paths["plan"], _plan_document(plan, written.report, analysis))
    return GeneratedShow(paths["sequence"], paths["timeline"], paths["plan"], paths["picture"],
                         paths["report"], written_analysis, written_vocals, vocals_note, plan,
                         written.report)
