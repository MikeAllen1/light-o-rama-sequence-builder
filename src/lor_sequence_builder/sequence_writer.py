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
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from lor_sequence_builder.choreography import Choreography, Effect
from lor_sequence_builder.loredit import LoreditError, read_loredit, write_loredit
from lor_sequence_builder.lorprev import read_lorprev
from lor_sequence_builder.new_sequence import (
    FreeTimingGrid,
    NewSequenceError,
    build_new_sequence,
)
from lor_sequence_builder.pulse import preview_element
from lor_sequence_builder.rules import RuleReport, RuleSet, check_choreography

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
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise SequenceWriteError(f"Report already exists; refusing to overwrite: {path}") from exc
    except OSError as exc:
        raise SequenceWriteError(f"Cannot write report: {path}") from exc


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
    for label, path in (("Sequence output", output), ("Report", report_output)):
        if path.exists():
            raise SequenceWriteError(f"{label} already exists; refusing to overwrite: {path}")

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
    report = check_choreography(preview, choreography, rule_set)
    _write_new_text(report_output, json.dumps(report.to_dict(), indent=2) + "\n")
    if not report.ok:
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
            raise SequenceWriteError(
                f"Effect on prop {effect.prop_id!r} channel {effect.channel_index} has no "
                "native channel"
            )
        ET.SubElement(targets[effect.channel_index], "effect", _effect_attributes(effect))

    try:
        write_loredit(built.document, output)
    except LoreditError as exc:
        raise SequenceWriteError(f"Could not write the sequence safely: {exc}") from exc
    try:
        read_loredit(output)
    except LoreditError as exc:
        output.unlink(missing_ok=True)
        raise SequenceWriteError(f"Could not write the sequence safely: {exc}") from exc
    return WriteResult(output, report_output, len(ordered), report)
