"""Write a native S6 sequence from a choreography Timeline, only if it passes the rules.

The rules run inside this function, against the same preview the sequence is
built from, so there is no way to hand the writer a Timeline that skipped them.
The rule report is always written; the sequence is written only when the report
has no errors.

Effect encoding is limited to what native S6 sequences have been seen to use
(docs/S6_FORMAT.md): ``INTENSITY`` with one intensity or a start/end pair, and
``TWINKLE`` / ``SHIMMER`` with one intensity.
"""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from lor_sequence_builder.artifacts import write_new_text_atomically
from lor_sequence_builder.choreography import Choreography, ChoreographyError, Effect
from lor_sequence_builder.lms import LmsDocument, LmsEffect, LmsError, build_lms, write_lms
from lor_sequence_builder.loredit import LoreditError, read_loredit, write_loredit
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.new_sequence import (
    FreeTimingGrid,
    NewSequenceError,
    build_new_sequence,
)
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.rules import RuleReport, RuleSet, check_choreography
from lor_sequence_builder.timeline import ExcludedProp

__all__ = ["NewSequenceError", "build_from_timeline", "build_lms_from_timeline",
           "build_new_sequence"]

_SETTINGS = {"on": "INTENSITY", "fade": "INTENSITY", "twinkle": "TWINKLE", "shimmer": "SHIMMER"}


class SequenceWriteError(ValueError):
    """Raised when a sequence cannot be written safely."""


class RulesFailedError(SequenceWriteError):
    """Raised when the Timeline breaks error-level rules; nothing but the report is written."""

    def __init__(self, report: RuleReport, report_path: Path) -> None:
        super().__init__(
            f"{len(report.errors)} rule error(s); the sequence was not written. "
            f"See {report_path}"
        )
        self.report = report
        self.report_path = report_path


@dataclass(frozen=True, slots=True)
class WriteResult:
    sequence_path: Path
    report_path: Path
    effect_count: int
    report: RuleReport
    excluded_props: tuple[ExcludedProp, ...] = ()


def _write_build_report(
    path: Path,
    report: RuleReport,
    output: Path,
    *,
    status: str,
    sequence_written: bool,
    failure_stage: str | None = None,
    error: str | None = None,
    excluded_props: tuple[ExcludedProp, ...] = (),
) -> None:
    payload = report.to_dict()
    payload.update({
        "ok": report.ok and status == "success",
        "rules_ok": report.ok,
        "build_report_version": 1,
        "build_status": status,
        "sequence_written": sequence_written,
        "sequence_output": str(output.resolve()),
        "failure_stage": failure_stage,
        "error": error,
        "excluded_props": [
            {"prop_id": item.prop_id, "name": item.name, "reason": item.reason}
            for item in excluded_props
        ],
    })
    content = json.dumps(payload, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SequenceWriteError(
                f"Report already exists; refusing to overwrite: {path}"
            ) from exc
        owned_failed_attempt = (
            isinstance(previous, dict)
            and previous.get("build_report_version") == 1
            and previous.get("build_status") == "failed"
            and previous.get("sequence_output") == str(output.resolve())
        )
        if not owned_failed_attempt:
            raise SequenceWriteError(f"Report already exists; refusing to overwrite: {path}")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                suffix=".tmp", delete=False, newline="\n",
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as exc:
            raise SequenceWriteError(f"Cannot update build report: {path}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return
    _write_new_text(path, content)


def _effect_attributes(effect: Effect) -> dict[str, str]:
    attributes = {
        "startCentisecond": str(effect.start_centisecond),
        "endCentisecond": str(effect.end_centisecond),
    }
    if effect.kind == "fade":
        attributes["startIntensity"] = str(effect.start_intensity)
        attributes["endIntensity"] = str(effect.end_intensity)
    else:
        attributes["intensity"] = str(effect.start_intensity)
    attributes["settings"] = _SETTINGS[effect.kind]
    return attributes


def _write_new_text(path: Path, content: str) -> None:
    try:
        write_new_text_atomically(path, content)
    except FileExistsError as exc:
        raise SequenceWriteError(f"Report already exists; refusing to overwrite: {path}") from exc
    except OSError as exc:
        raise SequenceWriteError(f"Cannot write report atomically: {path}") from exc

def build_from_timeline(
    preview_path: str | Path,
    choreography: Choreography,
    rule_set: RuleSet,
    music_filename: str,
    output_path: str | Path,
    report_path: str | Path,
) -> WriteResult:
    preview_source = Path(preview_path)
    output = Path(output_path)
    report_output = Path(report_path)
    if output.suffix.lower() != ".loredit":
        raise SequenceWriteError("Sequence output must use the .loredit extension")
    if report_output.suffix.lower() != ".json":
        raise SequenceWriteError("Rule report must use the .json extension")
    resolved = {p.resolve() for p in (preview_source, output, report_output)}
    if len(resolved) != 3:
        raise SequenceWriteError("Preview, sequence output and report must be different paths")
    if output.exists():
        raise SequenceWriteError(f"Sequence output already exists; refusing to overwrite: {output}")
    if report_output.exists():
        try:
            previous_report = json.loads(report_output.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SequenceWriteError(
                f"Report already exists; refusing to overwrite: {report_output}"
            ) from exc
        if not (
            isinstance(previous_report, dict)
            and previous_report.get("build_report_version") == 1
            and previous_report.get("build_status") == "failed"
            and previous_report.get("sequence_output") == str(output.resolve())
        ):
            raise SequenceWriteError(
                f"Report already exists; refusing to overwrite: {report_output}"
            )

    preview_model = read_lorprev(preview_source)
    invalid_identities = [
        item for item in preview_model.unsupported_constructs
        if item.kind in {"prop identity", "prop group identity"}
    ]
    if invalid_identities:
        raise SequenceWriteError(
            "Preview contains invalid prop/group identities: "
            + "; ".join(item.detail for item in invalid_identities[:5])
        )
    malformed_lor_assignments = [
        item for item in preview_model.unsupported_constructs
        if item.kind == "channel assignment"
        and any(
            prop.attributes.get("DeviceType") is not None
            and prop.attributes["DeviceType"].value == "LOR"
            and item.source.locator == f"{prop.locator}/@ChannelGrid"
            for prop in preview_model.props
        )
    ]
    if malformed_lor_assignments:
        raise SequenceWriteError(
            "Preview contains malformed LOR channel assignments; refusing to "
            "generate a sequence with shifted or ambiguous channel indices: "
            + "; ".join(item.detail for item in malformed_lor_assignments[:5])
        )
    preview = preview_element(preview_model)
    try:
        report = check_choreography(preview, choreography, rule_set)
    except ChoreographyError as exc:
        raise SequenceWriteError(f"Invalid choreography data: {exc}") from exc
    if not report.ok:
        _write_build_report(
            report_output, report, output, status="failed", sequence_written=False,
            failure_stage="rules", error=f"{len(report.errors)} rule error(s)",
        )
        raise RulesFailedError(report, report_output)

    sections = tuple(sorted({s.start_centisecond for s in choreography.sections}))
    try:
        built = build_new_sequence(
            preview,
            choreography.duration_centiseconds,
            music_filename,
            timing_grids=(FreeTimingGrid("Sections", sections),) if sections else (),
        )
    except NewSequenceError as exc:
        _write_build_report(
            report_output, report, output, status="failed", sequence_written=False,
            failure_stage="native_sequence", error=str(exc),
        )
        raise SequenceWriteError(str(exc)) from exc

    sequence_props = built.document.root.find("SequenceProps")
    assert sequence_props is not None
    channels: dict[str, list[ET.Element]] = {
        seq.attrib["id"]: seq.findall("channel") for seq in sequence_props.findall("SeqProp")
    }
    ordered = sorted(
        choreography.effects,
        key=lambda e: (e.prop_id, e.channel_index, e.start_centisecond),
    )
    for effect in ordered:
        targets = channels.get(effect.prop_id)
        # The locked rules already guarantee this; refuse rather than guess if not.
        if targets is None or not 0 <= effect.channel_index < len(targets):
            message = (
                f"Effect on prop {effect.prop_id!r} channel {effect.channel_index} "
                "has no native channel"
            )
            _write_build_report(
                report_output, report, output, status="failed", sequence_written=False,
                failure_stage="channel_mapping", error=message,
                excluded_props=built.excluded_props,
            )
            raise SequenceWriteError(message)
        ET.SubElement(targets[effect.channel_index], "effect", _effect_attributes(effect))

    try:
        write_loredit(built.document, output)
    except LoreditError as exc:
        _write_build_report(
            report_output, report, output, status="failed", sequence_written=False,
            failure_stage="sequence_write", error=str(exc),
            excluded_props=built.excluded_props,
        )
        raise SequenceWriteError(f"Could not write the sequence safely: {exc}") from exc
    try:
        read_loredit(output)
    except LoreditError as exc:
        output.unlink(missing_ok=True)
        _write_build_report(
            report_output, report, output, status="failed", sequence_written=False,
            failure_stage="readback_validation", error=str(exc),
            excluded_props=built.excluded_props,
        )
        raise SequenceWriteError(f"Could not write the sequence safely: {exc}") from exc
    try:
        _write_build_report(
            report_output, report, output, status="success", sequence_written=True,
            excluded_props=built.excluded_props,
        )
    except SequenceWriteError as exc:
        # The sequence is not a successful command result unless its final report
        # is published too. Roll back the validated sequence so a retry with the
        # same paths is possible and no unreported success artifact remains.
        try:
            output.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise SequenceWriteError(
                f"Could not publish the build report ({exc}); additionally could not "
                f"remove the unreported sequence at {output}: {cleanup_error}"
            ) from cleanup_error
        raise SequenceWriteError(
            f"Could not publish the build report; the sequence was removed: {exc}"
        ) from exc
    return WriteResult(output, report_output, len(ordered), report, built.excluded_props)


def build_lms_from_timeline(
    preview_path: str | Path,
    template: LmsDocument,
    prop_channels: dict[str, int],
    choreography: Choreography,
    rule_set: RuleSet,
    music_filename: str,
    output_path: str | Path,
    report_path: str | Path,
    excluded_props: tuple[ExcludedProp, ...] = (),
) -> WriteResult:
    """Write an S4 ``.lms`` from a Timeline, only if it passes the rules.

    ``preview_path`` is the preview made from ``template`` (see ``lms.display_from_lms``)
    and ``prop_channels`` maps each of its props to the template channel it came from.
    """
    output = Path(output_path)
    report_output = Path(report_path)
    if output.suffix.lower() != ".lms":
        raise SequenceWriteError("An S4 sequence must use the .lms extension")
    if report_output.suffix.lower() != ".json":
        raise SequenceWriteError("Rule report must use the .json extension")
    if output.exists():
        raise SequenceWriteError(f"Sequence output already exists; refusing to overwrite: {output}")
    if template.source_path is not None and output.resolve() == template.source_path.resolve():
        raise SequenceWriteError("Refusing to overwrite the source .lms")
    preview = preview_element(read_lorprev(preview_path))
    try:
        report = check_choreography(preview, choreography, rule_set)
    except ChoreographyError as exc:
        raise SequenceWriteError(f"Invalid choreography data: {exc}") from exc
    if not report.ok:
        _write_build_report(
            report_output, report, output, status="failed", sequence_written=False,
            failure_stage="rules", error=f"{len(report.errors)} rule error(s)",
        )
        raise RulesFailedError(report, report_output)

    effects: list[LmsEffect] = []
    for effect in choreography.effects:
        saved_index = prop_channels.get(effect.prop_id)
        # Each S4 channel is a one-channel prop; anything else would be a guess.
        if saved_index is None or effect.channel_index != 0:
            message = (f"Effect on prop {effect.prop_id!r} channel {effect.channel_index} "
                       "has no S4 channel")
            _write_build_report(
                report_output, report, output, status="failed", sequence_written=False,
                failure_stage="channel_mapping", error=message, excluded_props=excluded_props,
            )
            raise SequenceWriteError(message)
        end_intensity = effect.end_intensity if effect.kind == "fade" else effect.start_intensity
        effects.append(LmsEffect(saved_index, effect.kind, effect.start_centisecond,
                                 effect.end_centisecond, effect.start_intensity, end_intensity))
    sections = sorted({s.start_centisecond for s in choreography.sections})
    try:
        content = build_lms(template, effects, choreography.duration_centiseconds,
                            music_filename, sections)
        write_lms(output, content)
    except LmsError as exc:
        _write_build_report(
            report_output, report, output, status="failed", sequence_written=False,
            failure_stage="sequence_write", error=str(exc), excluded_props=excluded_props,
        )
        raise SequenceWriteError(f"Could not write the S4 sequence: {exc}") from exc
    try:
        _write_build_report(
            report_output, report, output, status="success", sequence_written=True,
            excluded_props=excluded_props,
        )
    except SequenceWriteError:
        output.unlink(missing_ok=True)
        raise
    return WriteResult(output, report_output, len(effects), report, excluded_props)
