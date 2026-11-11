"""Fixed-tempo pulse generator: preview to Timeline to native sequence.

By default the sequence is built from the preview alone (Phase 4b). Passing a
matching template sequence is still supported but deprecated.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from lor_sequence_builder.loredit import (
    LoreditDocument,
    LoreditError,
    read_loredit,
    write_loredit,
)
from lor_sequence_builder.lorprev import PropModel, RawElement, read_lorprev
from lor_sequence_builder.new_sequence import NewSequenceError, build_new_sequence
from lor_sequence_builder.timeline import (
    ExcludedProp,
    PulseEvent,
    Timeline,
    TimelineChannel,
    timeline_json,
)

SUPPORTED_DEVICE_TYPES = frozenset({"LOR"})
SUPPORTED_TRADITIONAL_TYPES = frozenset(
    {"Single Color", "Multicolor_string_1_ch", "Channel_per_color"}
)
MAX_BPM = 300
MIN_BPM = 30
MAX_TIMELINE_EVENTS = 250_000
MAX_TIMELINE_BEATS = 50_000


class PulseGenerationError(ValueError):
    """Raised when a safe, traceable walking-skeleton sequence cannot be built."""


@dataclass(frozen=True, slots=True)
class PulseGenerationResult:
    """Paths and counts produced by a successful pulse build."""

    sequence_path: Path
    timeline_path: Path
    supported_prop_count: int
    excluded_prop_count: int
    beat_count: int
    event_count: int
    excluded_props: tuple[ExcludedProp, ...]


@dataclass(frozen=True, slots=True)
class _MappedChannel:
    reference: TimelineChannel
    element: ET.Element


def preview_element(model: PropModel) -> ET.Element:
    """Return the validated preview as an XML element."""
    return _element_from_raw(model.display)


def _element_from_raw(raw: RawElement) -> ET.Element:
    """Rebuild an XML element from the already-validated, loss-preserving preview model."""
    element = ET.Element(
        raw.tag,
        {name: value.value for name, value in raw.attributes.items()},
    )
    element.text = raw.text
    element.tail = raw.tail
    for child in raw.children:
        element.append(_element_from_raw(child))
    return element


def _xml_fingerprint(root: ET.Element) -> str:
    """Fingerprint the exact parsed XML tree used by this generation run."""
    return hashlib.sha256(ET.tostring(root, encoding="utf-8")).hexdigest()


def _attribute(element: ET.Element, name: str) -> str | None:
    value = element.attrib.get(name)
    return value if value is not None and value.strip() else None




def _elements_equivalent(left: ET.Element, right: ET.Element) -> bool:
    """Compare preview subtrees semantically, allowing harmless coordinate rounding."""
    if left.tag != right.tag or set(left.attrib) != set(right.attrib):
        return False
    for name, left_value in left.attrib.items():
        right_value = right.attrib[name]
        if name in {"x", "y", "top", "left"}:
            try:
                if abs(float(left_value) - float(right_value)) > 1e-6:
                    return False
                continue
            except ValueError:
                pass
        if left_value != right_value:
            return False
    if (left.text or "").strip() != (right.text or "").strip():
        return False
    if (left.tail or "").strip() != (right.tail or "").strip():
        return False
    left_children = list(left)
    right_children = list(right)
    return len(left_children) == len(right_children) and all(
        _elements_equivalent(a, b) for a, b in zip(left_children, right_children)
    )

def _beat_positions(duration: int, bpm: int) -> tuple[int, ...]:
    # Bound beat-list allocation before iterating over untrusted template duration.
    estimated_beats = (duration * bpm + 5999) // 6000
    if estimated_beats > MAX_TIMELINE_BEATS:
        raise PulseGenerationError(
            f"Timeline would contain more than {MAX_TIMELINE_BEATS} beats; "
            "sequence duration is too long for the walking skeleton"
        )
    # Round rational beat positions to the nearest centisecond, half-up.
    positions: list[int] = []
    beat_index = 0
    while True:
        position = (6000 * beat_index + bpm // 2) // bpm
        if position >= duration:
            break
        if positions and position <= positions[-1]:
            raise PulseGenerationError("BPM produces duplicate centisecond beat positions")
        positions.append(position)
        beat_index += 1
    return tuple(positions)


def _validate_paths(
    preview_path: Path,
    template_path: Path | None,
    output_path: Path,
    timeline_path: Path,
) -> None:
    paths = {
        "preview": preview_path.resolve(),
        "sequence output": output_path.resolve(),
        "Timeline output": timeline_path.resolve(),
    }
    if template_path is not None:
        paths["template"] = template_path.resolve()
    if paths["sequence output"] == paths["Timeline output"]:
        raise PulseGenerationError("Sequence and Timeline outputs must be different paths")
    for output_name in ("sequence output", "Timeline output"):
        for input_name in ("preview", "template"):
            if input_name not in paths:
                continue
            if paths[output_name] == paths[input_name]:
                raise PulseGenerationError(
                    f"{output_name} must not alias the {input_name} input"
                )
    for output_name, output in (
        ("sequence output", output_path),
        ("Timeline output", timeline_path),
    ):
        if output.exists():
            raise PulseGenerationError(f"{output_name} already exists: {output}")
    if output_path.suffix.lower() != ".loredit":
        raise PulseGenerationError("Sequence output must use the .loredit extension")
    if timeline_path.suffix.lower() != ".json":
        raise PulseGenerationError("Timeline output must use the .json extension")


def _write_timeline_temp(parent: Path, prefix: str, suffix: str, content: str) -> Path:
    """Create and write a private timeline temp file through its original handle."""
    parent.mkdir(parents=True, exist_ok=True)
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=parent, prefix=prefix, suffix=suffix, delete=False
        ) as stream:
            path = Path(stream.name)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    return path


def _build_timeline(
    preview_root: ET.Element,
    document: LoreditDocument,
    preview_xml_sha256: str,
    template_xml_sha256: str,
    bpm: int,
    pulse_duration_centiseconds: int,
) -> tuple[Timeline, dict[tuple[str, int], _MappedChannel]]:
    embedded_preview = document.root.find("PreviewClass")
    sequence_props = document.root.find("SequenceProps")
    if embedded_preview is None or sequence_props is None:
        raise PulseGenerationError("Template must contain PreviewClass and SequenceProps")

    preview_nodes = preview_root.findall("PropClass")
    preview_ids = [_attribute(prop, "id") for prop in preview_nodes]
    if any(prop_id is None for prop_id in preview_ids):
        raise PulseGenerationError("Preview contains a prop with a missing or blank id")
    if len(set(preview_ids)) != len(preview_ids):
        raise PulseGenerationError("Preview contains duplicate prop IDs")
    preview_id_set = {prop_id for prop_id in preview_ids if prop_id is not None}

    embedded_nodes = embedded_preview.findall("PropClass")
    embedded_ids = [_attribute(prop, "id") for prop in embedded_nodes]
    if any(prop_id is None for prop_id in embedded_ids):
        raise PulseGenerationError("Template PreviewClass contains a missing or blank prop id")
    if len(set(embedded_ids)) != len(embedded_ids):
        raise PulseGenerationError("Template PreviewClass contains duplicate prop IDs")
    embedded_id_set = {prop_id for prop_id in embedded_ids if prop_id is not None}
    if embedded_id_set != preview_id_set:
        missing = sorted(preview_id_set - embedded_id_set)
        extra = sorted(embedded_id_set - preview_id_set)
        raise PulseGenerationError(
            "Preview/template prop IDs do not match exactly; "
            f"missing from template={missing[:8]}, extra in template={extra[:8]}"
        )

    embedded_prop_map = {
        prop_id: prop
        for prop in embedded_nodes
        if (prop_id := _attribute(prop, "id")) is not None
    }
    for preview_prop in preview_nodes:
        prop_id = _attribute(preview_prop, "id")
        assert prop_id is not None
        template_prop = embedded_prop_map[prop_id]
        if not _elements_equivalent(preview_prop, template_prop):
            raise PulseGenerationError(
                f"Prop {prop_id!r} has mismatched preview data between standalone "
                "preview and template (attributes, geometry, or nested structures)"
            )

    preview_groups = preview_root.findall("PropGroup")
    template_groups = embedded_preview.findall("PropGroup")
    if len(preview_groups) != len(template_groups) or any(
        not _elements_equivalent(preview_group, template_group)
        for preview_group, template_group in zip(preview_groups, template_groups)
    ):
        raise PulseGenerationError(
            "Preview/template PropGroup relationships or arrangement data do not match"
        )

    sequence_prop_nodes = sequence_props.findall("SeqProp")
    sequence_prop_map: dict[str, ET.Element] = {}
    for sequence_prop_node in sequence_prop_nodes:
        prop_id = _attribute(sequence_prop_node, "id")
        if prop_id is None:
            raise PulseGenerationError("Template contains a SeqProp with a missing or blank id")
        if prop_id in sequence_prop_map:
            raise PulseGenerationError(f"Template contains duplicate SeqProp id {prop_id!r}")
        sequence_prop_map[prop_id] = sequence_prop_node

    excluded: list[ExcludedProp] = []
    supported_prop_ids: list[str] = []
    mapped_channels: dict[tuple[str, int], _MappedChannel] = {}
    channels_by_prop: dict[str, list[_MappedChannel]] = {}

    for prop in preview_nodes:
        prop_id = _attribute(prop, "id")
        assert prop_id is not None
        name = _attribute(prop, "Name") or prop_id
        device_type = _attribute(prop, "DeviceType")
        traditional_type = _attribute(prop, "TraditionalType")

        if device_type in {"AC", "DC"}:
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason=(
                        f"DeviceType {device_type!r} is recognized by the preview parser "
                        "but legacy AC/DC native channel mapping is not verified for Phase 3"
                    ),
                )
            )
            continue
        if device_type not in SUPPORTED_DEVICE_TYPES:
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason=(
                        f"DeviceType {device_type!r} is outside the verified "
                        "walking-skeleton support boundary (LOR only)"
                    ),
                )
            )
            continue
        if traditional_type not in SUPPORTED_TRADITIONAL_TYPES:
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason=(
                        f"TraditionalType {traditional_type!r} is outside the "
                        "verified support boundary (Single Color, "
                        "Multicolor_string_1_ch, and Channel_per_color)"
                    ),
                )
            )
            continue

        channel_grid = _attribute(prop, "ChannelGrid")
        if channel_grid is None:
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason="No ChannelGrid assignment is present",
                )
            )
            continue
        address_entries = [entry.split(",") for entry in channel_grid.split(";")]
        if not address_entries or any(
            len(entry) < 3 or not all(field.strip() for field in entry[:3])
            for entry in address_entries
        ):
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason="ChannelGrid lacks a complete LOR network/Unit ID/circuit address",
                )
            )
            continue

        sequence_prop = sequence_prop_map.get(prop_id)
        if sequence_prop is None:
            master_id = _attribute(prop, "MasterPropId")
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason=(
                        f"Linked to master prop {master_id}; S6 drives it through the "
                        "master's channels, so it has no sequence channels of its own"
                        if master_id
                        else "No matching native SeqProp exists; no sequence channel can be targeted"
                    ),
                )
            )
            continue
        native_channels = sequence_prop.findall("channel")
        if not native_channels:
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason="Matching native SeqProp contains no channel records",
                )
            )
            continue
        if len(address_entries) != len(native_channels):
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason=(
                        f"Ambiguous physical mapping: {len(address_entries)} ChannelGrid "
                        f"addresses but {len(native_channels)} native sequence channels"
                    ),
                )
            )
            continue

        channel_refs: list[_MappedChannel] = []
        seen_coordinates: set[tuple[str, str, str]] = set()
        mapping_error: str | None = None
        for index, (address, channel) in enumerate(zip(address_entries, native_channels)):
            row = _attribute(channel, "row")
            col = _attribute(channel, "col")
            color = _attribute(channel, "color")
            if row is None or col is None or color is None:
                mapping_error = (
                    f"Native channel {index} is missing row, col, or color coordinates"
                )
                break
            # Verified S6 v15 mappings use ChannelGrid entry order. Ordinary
            # one-channel/multichannel props index native channels by column;
            # Channel_per_color indexes native channels by the color coordinate.
            if traditional_type == "Channel_per_color":
                expected_coordinates = ("0", "0", str(index))
            else:
                expected_coordinates = ("0", str(index), color)
            if (row, col, color) != expected_coordinates:
                mapping_error = (
                    f"Native channel {index} has unverified coordinates "
                    f"row={row!r}, col={col!r}, color={color!r}; "
                    f"expected row={expected_coordinates[0]!r}, "
                    f"col={expected_coordinates[1]!r}, "
                    f"color={expected_coordinates[2]!r}"
                )
                break
            coordinates = (row, col, color)
            if coordinates in seen_coordinates:
                mapping_error = f"Duplicate native channel coordinates {coordinates!r}"
                break
            seen_coordinates.add(coordinates)
            reference = TimelineChannel(
                prop_id=prop_id,
                channel_index=index,
                preview_channel_index=index,
                network=address[0].strip(),
                unit_id=address[1].strip(),
                circuit=address[2].strip(),
                row=row,
                col=col,
                color=color,
            )
            channel_refs.append(_MappedChannel(reference=reference, element=channel))

        if mapping_error is not None:
            excluded.append(
                ExcludedProp(
                    prop_id=prop_id,
                    name=name,
                    reason=f"Physical channel mapping is not verified: {mapping_error}",
                )
            )
            continue

        supported_prop_ids.append(prop_id)
        channels_by_prop[prop_id] = channel_refs
        for mapped in channel_refs:
            mapped_channels[(prop_id, mapped.reference.channel_index)] = mapped

    if not supported_prop_ids:
        raise PulseGenerationError(
            "No props qualify for the verified walking-skeleton support boundary; "
            "see preview DeviceType, TraditionalType, ChannelGrid, and template channels"
        )

    duration = document.total_centiseconds
    if duration <= 0:
        raise PulseGenerationError("Template sequence duration must be greater than zero")
    beats = _beat_positions(duration, bpm)
    if not beats:
        raise PulseGenerationError("Sequence duration is too short to contain a beat")
    if pulse_duration_centiseconds > (6000 // bpm):
        raise PulseGenerationError(
            "Pulse duration must not exceed the fixed-tempo beat interval"
        )

    event_count = sum(len(channels_by_prop[prop_id]) for prop_id in supported_prop_ids) * len(
        beats
    )
    if event_count > MAX_TIMELINE_EVENTS:
        raise PulseGenerationError(
            f"Timeline would contain {event_count} events; limit is {MAX_TIMELINE_EVENTS}"
        )

    events: list[PulseEvent] = []
    for beat_index, start in enumerate(beats):
        end = min(start + pulse_duration_centiseconds, duration)
        for prop_id in supported_prop_ids:
            for mapped in channels_by_prop[prop_id]:
                events.append(
                    PulseEvent(
                        start_centisecond=start,
                        end_centisecond=end,
                        beat_index=beat_index,
                        channel=mapped.reference,
                    )
                )

    timeline = Timeline(
        schema_version="1.0",
        timebase="integer centiseconds from sequence start",
        preview_xml_sha256=preview_xml_sha256,
        template_xml_sha256=template_xml_sha256,
        bpm=bpm,
        duration_centiseconds=duration,
        pulse_duration_centiseconds=pulse_duration_centiseconds,
        beat_positions_centiseconds=beats,
        supported_prop_ids=tuple(supported_prop_ids),
        excluded_props=tuple(excluded),
        events=tuple(events),
    )
    _validate_timeline(timeline, preview_id_set, mapped_channels)
    return timeline, mapped_channels


def _validate_timeline(
    timeline: Timeline,
    preview_ids: set[str],
    mapped_channels: dict[tuple[str, int], _MappedChannel],
) -> None:
    supported = set(timeline.supported_prop_ids)
    if len(supported) != len(timeline.supported_prop_ids):
        raise PulseGenerationError("Timeline contains duplicate supported prop IDs")
    if not supported.issubset(preview_ids):
        raise PulseGenerationError("Timeline contains a prop ID absent from the preview")

    excluded_ids = [prop.prop_id for prop in timeline.excluded_props]
    if len(set(excluded_ids)) != len(excluded_ids):
        raise PulseGenerationError("Timeline contains duplicate excluded prop IDs")
    if not set(excluded_ids).issubset(preview_ids) or supported.intersection(excluded_ids):
        raise PulseGenerationError("Timeline excluded-prop references are invalid")
    if supported.union(excluded_ids) != preview_ids:
        raise PulseGenerationError("Every preview prop must be supported or explicitly excluded")

    beats = timeline.beat_positions_centiseconds
    if not beats or tuple(sorted(set(beats))) != beats:
        raise PulseGenerationError("Timeline beat positions must be non-empty and strictly increasing")
    if {prop_id for prop_id, _ in mapped_channels} != supported:
        raise PulseGenerationError("Timeline supported props do not match the native channel map")

    expected = {
        (beat_index, prop_id, channel_index)
        for beat_index in range(len(beats))
        for prop_id, channel_index in mapped_channels
    }
    if len(expected) != len(timeline.events):
        raise PulseGenerationError("Timeline does not contain exactly one pulse per beat/channel")

    observed: set[tuple[int, str, int]] = set()
    for event in timeline.events:
        channel = event.channel
        if channel.prop_id not in preview_ids or channel.prop_id not in supported:
            raise PulseGenerationError("Timeline event references an unknown or unsupported prop")
        key = (event.beat_index, channel.prop_id, channel.channel_index)
        if key not in expected or key in observed:
            raise PulseGenerationError("Timeline event has an invalid or duplicate beat/channel reference")
        if event.beat_index < 0 or event.beat_index >= len(beats):
            raise PulseGenerationError("Timeline event references an invalid beat index")
        if event.start_centisecond != beats[event.beat_index]:
            raise PulseGenerationError("Timeline event does not begin at its indexed beat position")
        if event.start_centisecond < 0 or event.end_centisecond > timeline.duration_centiseconds:
            raise PulseGenerationError("Timeline event extends outside sequence duration")
        expected_end = min(
            event.start_centisecond + timeline.pulse_duration_centiseconds,
            timeline.duration_centiseconds,
        )
        if event.end_centisecond != expected_end:
            raise PulseGenerationError("Timeline event duration does not match the configured pulse")
        mapped = mapped_channels[(channel.prop_id, channel.channel_index)]
        if channel != mapped.reference:
            raise PulseGenerationError(
                "Timeline physical address or native channel coordinates do not match "
                "the validated preview/template mapping"
            )
        if channel.preview_channel_index != channel.channel_index:
            raise PulseGenerationError("Timeline preview/native channel indices do not match")
        if not all((channel.network, channel.unit_id, channel.circuit)):
            raise PulseGenerationError("Timeline channel is missing its physical LOR address")
        native_channel = mapped.element
        if (
            native_channel.attrib.get("row") != channel.row
            or native_channel.attrib.get("col") != channel.col
            or native_channel.attrib.get("color") != channel.color
        ):
            raise PulseGenerationError("Timeline channel coordinates do not match the native template")
        observed.add(key)

    if observed != expected:
        raise PulseGenerationError("Timeline is missing one or more expected beat/channel pulses")


def build_pulse_sequence(
    preview_path: str | Path,
    template_path: str | Path | None,
    output_path: str | Path,
    timeline_path: str | Path,
    bpm: int,
    pulse_duration_centiseconds: int = 10,
    total_centiseconds: int | None = None,
    music_filename: str | None = None,
) -> PulseGenerationResult:
    """Build a deterministic beat-pulse sequence.

    Without a template, a new native sequence is built from the preview alone
    and ``total_centiseconds`` and ``music_filename`` are required. With a
    template (deprecated), the template's embedded preview must match exactly.
    """
    preview_source = Path(preview_path)
    template_source = Path(template_path) if template_path is not None else None
    output = Path(output_path)
    timeline_output = Path(timeline_path)

    if not isinstance(bpm, int) or isinstance(bpm, bool) or not MIN_BPM <= bpm <= MAX_BPM:
        raise PulseGenerationError(f"BPM must be an integer from {MIN_BPM} to {MAX_BPM}")
    if (
        not isinstance(pulse_duration_centiseconds, int)
        or isinstance(pulse_duration_centiseconds, bool)
        or not (
            1 <= pulse_duration_centiseconds <= 100
        )
    ):
        raise PulseGenerationError("Pulse duration must be an integer from 1 to 100 centiseconds")
    _validate_paths(preview_source, template_source, output, timeline_output)

    preview_model = read_lorprev(preview_source)
    if any(item.kind == "prop identity" for item in preview_model.unsupported_constructs):
        raise PulseGenerationError("Preview contains missing or duplicate prop identities")
    preview_root = _element_from_raw(preview_model.display)
    if template_source is None:
        if total_centiseconds is None or music_filename is None:
            raise PulseGenerationError(
                "Without a template, a sequence duration and an audio file name are required"
            )
        try:
            document = build_new_sequence(
                preview_root, total_centiseconds, music_filename
            ).document
        except NewSequenceError as exc:
            raise PulseGenerationError(str(exc)) from exc
    else:
        if total_centiseconds is not None or music_filename is not None:
            raise PulseGenerationError(
                "Duration and audio file name come from the template; do not pass both"
            )
        document = read_loredit(template_source)

    timeline, mapped_channels = _build_timeline(
        preview_root,
        document,
        _xml_fingerprint(preview_root),
        _xml_fingerprint(document.root),
        bpm,
        pulse_duration_centiseconds,
    )

    sequence_props = document.root.find("SequenceProps")
    assert sequence_props is not None
    for sequence_prop in sequence_props.findall("SeqProp"):
        for channel in sequence_prop.findall("channel"):
            for effect in list(channel.findall("effect")):
                channel.remove(effect)

    for event in timeline.events:
        channel = mapped_channels[(event.channel.prop_id, event.channel.channel_index)].element
        ET.SubElement(
            channel,
            "effect",
            {
                "startCentisecond": str(event.start_centisecond),
                "endCentisecond": str(event.end_centisecond),
                "settings": "INTENSITY",
                "intensity": "100",
            },
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    timeline_temp: Path | None = None
    sequence_linked = False
    try:
        # write_loredit performs its own atomic create-if-absent publication.
        # Give it a private, atomically-created staging directory so its target
        # starts absent without exposing a path-swap race in the shared output dir.
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.", dir=output.parent
        ) as sequence_stage:
            sequence_temp = Path(sequence_stage) / "sequence.loredit"
            write_loredit(document, sequence_temp)
            # Re-read the exact generated bytes before publishing either artifact.
            read_loredit(sequence_temp)
            timeline_temp = _write_timeline_temp(
                timeline_output.parent,
                prefix=f".{timeline_output.name}.",
                suffix=".tmp",
                content=timeline_json(timeline),
            )
            os.link(sequence_temp, output)
            sequence_linked = True
            os.link(timeline_temp, timeline_output)
    except (LoreditError, OSError) as exc:
        if sequence_linked:
            output.unlink(missing_ok=True)
        raise PulseGenerationError(f"Could not safely publish generated artifacts: {exc}") from exc
    finally:
        if timeline_temp is not None:
            timeline_temp.unlink(missing_ok=True)

    return PulseGenerationResult(
        sequence_path=output,
        timeline_path=timeline_output,
        supported_prop_count=len(timeline.supported_prop_ids),
        excluded_prop_count=len(timeline.excluded_props),
        beat_count=len(timeline.beat_positions_centiseconds),
        event_count=len(timeline.events),
        excluded_props=timeline.excluded_props,
    )
