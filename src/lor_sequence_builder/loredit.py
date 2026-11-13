"""Loss-preserving reader and writer for the observed S6 LOREDIT v15 format.

The implementation intentionally treats the sequence as an opaque XML document:
unknown elements and attributes are retained rather than interpreted or rebuilt.
"""

from __future__ import annotations

import heapq
import os
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

MAX_LOREDIT_BYTES = 50 * 1024 * 1024
MAX_LOREDIT_ELEMENTS = 100_000
MAX_LOREDIT_DEPTH = 256


class LoreditError(ValueError):
    """Base error for invalid or unsupported LOREDIT documents."""


@dataclass(slots=True)
class LoreditDocument:
    """Parsed sequence document; its XML tree is preserved opaquely."""

    root: ET.Element
    source_path: Path | None = None

    @property
    def save_file_version(self) -> str:
        return self.root.attrib.get("saveFileVersion", "")

    @property
    def total_centiseconds(self) -> int:
        try:
            value = int(self.root.attrib["totalCentiseconds"])
        except (KeyError, ValueError) as exc:
            raise LoreditError("LOREDIT has no valid totalCentiseconds value") from exc
        if value < 0:
            raise LoreditError("LOREDIT totalCentiseconds cannot be negative")
        return value


def read_loredit(path: str | Path) -> LoreditDocument:
    """Read and validate an observed S6 LOREDIT v15 XML document."""
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise LoreditError(f"Cannot access LOREDIT file: {source}") from exc
    if size == 0:
        raise LoreditError("LOREDIT file is empty")
    if size > MAX_LOREDIT_BYTES:
        raise LoreditError(
            f"LOREDIT file exceeds the {MAX_LOREDIT_BYTES // (1024 * 1024)} MiB limit"
        )

    try:
        iterator: Any = SafeET.iterparse(
            source,
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        depth = 0
        element_count = 0
        root: ET.Element | None = None
        for event, element in iterator:
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                element_count += 1
                if depth > MAX_LOREDIT_DEPTH:
                    raise LoreditError(
                        f"LOREDIT XML exceeds the maximum nesting depth of {MAX_LOREDIT_DEPTH}"
                    )
                if element_count > MAX_LOREDIT_ELEMENTS:
                    raise LoreditError(
                        f"LOREDIT XML exceeds the {MAX_LOREDIT_ELEMENTS}-element limit"
                    )
            else:
                depth -= 1
    except LoreditError:
        raise
    except (OSError, ET.ParseError, DefusedXmlException) as exc:
        raise LoreditError(f"Invalid or unsafe LOREDIT XML: {source}") from exc

    if root is None:
        raise LoreditError("LOREDIT XML has no document element")
    if root.tag != "sequence":
        raise LoreditError("LOREDIT root element must be <sequence>")
    # Any saveFileVersion is accepted: the file's structure decides whether it can be
    # read, never its version number.
    document = LoreditDocument(root=root, source_path=source)
    _ = document.total_centiseconds
    if root.find("SequenceProps") is None:
        raise LoreditError("LOREDIT is missing the SequenceProps section")
    if root.find("TimingGrids") is None:
        raise LoreditError("LOREDIT is missing the TimingGrids section")
    _validate_sequence_prop_references(root)
    return document


def _validate_sequence_prop_references(root: ET.Element) -> None:
    """Reject sequence props that have no matching embedded preview prop.

    S6 warns that these records will be removed on save. SequenceProps may
    reference either a PropClass or a native PropGroup ID. Preview-only props
    are allowed because observed fixtures contain preview entities that are not
    currently represented in SequenceProps.
    """
    preview = root.find("PreviewClass")
    sequence_props = root.find("SequenceProps")
    if preview is None or sequence_props is None:
        raise LoreditError("LOREDIT must contain PreviewClass and SequenceProps sections")

    preview_ids: set[str] = set()
    for element_name in ("PropClass", "PropGroup"):
        for index, element in enumerate(preview.findall(element_name)):
            element_id = element.attrib.get("id", "")
            if not element_id.strip():
                raise LoreditError(
                    f"PreviewClass {element_name} at index {index} has a missing or blank id"
                )
            if element_id in preview_ids:
                raise LoreditError(
                    f"PreviewClass contains duplicate identity {element_id!r}"
                )
            preview_ids.add(element_id)

    sequence_prop_ids: set[str] = set()
    orphan_ids: list[str] = []
    for index, prop in enumerate(sequence_props.findall("SeqProp")):
        prop_id = prop.attrib.get("id", "")
        if not prop_id.strip():
            raise LoreditError(f"SequenceProps SeqProp at index {index} has a missing or blank id")
        if prop_id in sequence_prop_ids:
            raise LoreditError(f"SequenceProps contains duplicate SeqProp id {prop_id!r}")
        sequence_prop_ids.add(prop_id)
        if prop_id not in preview_ids:
            orphan_ids.append(prop_id)
    if orphan_ids:
        joined = ", ".join(orphan_ids)
        raise LoreditError(
            "SequenceProps contains prop IDs missing from PreviewClass; "
            f"S6 may discard them when saving: {joined}"
        )


def effect_timing_problems(
    document: LoreditDocument, limit: int = 20, original: LoreditDocument | None = None
) -> list[str]:
    """Check effect timing, permitting overlaps that were already in the source.

    A new or changed effect may not overlap any other effect. Existing overlapping
    effects are retained because S6 files can legitimately contain them.
    """
    total = document.total_centiseconds
    problems: list[str] = []
    original_channels: dict[tuple[str, int], list[tuple[int, int]]] = {}
    if original is not None:
        original_props = original.root.find("SequenceProps")
        for source_prop in [] if original_props is None else original_props.findall("SeqProp"):
            prop_id = source_prop.attrib.get("id", "")
            for channel_index, source_channel in enumerate(source_prop.findall("channel")):
                source_spans: list[tuple[int, int]] = []
                for effect in source_channel.findall("effect"):
                    try:
                        source_spans.append((
                            int(effect.attrib["startCentisecond"]),
                            int(effect.attrib["endCentisecond"]),
                        ))
                    except (KeyError, ValueError):
                        continue
                original_channels[(prop_id, channel_index)] = source_spans

    sequence_props = document.root.find("SequenceProps")
    for prop in [] if sequence_props is None else sequence_props.findall("SeqProp"):
        name = prop.attrib.get("name") or prop.attrib.get("id", "?")
        prop_id = prop.attrib.get("id", "")
        for index, channel in enumerate(prop.findall("channel")):
            spans: list[tuple[int, int]] = []
            for effect in channel.findall("effect"):
                try:
                    start = int(effect.attrib["startCentisecond"])
                    end = int(effect.attrib["endCentisecond"])
                except (KeyError, ValueError):
                    problems.append(f"{name} channel {index + 1}: effect without valid times")
                    continue
                if start < 0 or end <= start or end > total + 100:
                    problems.append(
                        f"{name} channel {index + 1}: effect {start}-{end} cs is out of range")
                spans.append((start, end))

            available_original = Counter(original_channels.get((prop_id, index), []))
            active: list[tuple[int, int, bool]] = []
            active_count = 0
            active_changed = 0
            active_spans: Counter[tuple[int, int]] = Counter()
            changed_spans: Counter[tuple[int, int]] = Counter()
            for start, end in sorted(spans):
                while active and active[0][0] <= start:
                    prior_end, prior_start, changed = heapq.heappop(active)
                    prior_span = (prior_start, prior_end)
                    active_count -= 1
                    active_changed -= int(changed)
                    active_spans[prior_span] -= 1
                    changed_spans[prior_span] -= int(changed)
                is_original = available_original[(start, end)] > 0
                if is_original:
                    available_original[(start, end)] -= 1
                span = (start, end)
                other_active = active_count - active_spans[span]
                other_changed = active_changed - changed_spans[span]
                # Exact duplicates are preserved by S6 and are not overlaps.
                if other_active and (not is_original or other_changed):
                    problems.append(
                        f"{name} channel {index + 1}: effects overlap at {start} cs")
                changed = not is_original
                heapq.heappush(active, (end, start, changed))
                active_count += 1
                active_changed += int(changed)
                active_spans[span] += 1
                changed_spans[span] += int(changed)
            if len(problems) >= limit:
                return problems[:limit]
    return problems


def write_loredit(document: LoreditDocument, output_path: str | Path) -> Path:
    """Atomically write a new LOREDIT file without replacing an existing path."""
    output = Path(output_path)
    if document.root.tag != "sequence":
        raise LoreditError("Cannot write a document whose root is not <sequence>")
    _ = document.total_centiseconds
    if document.root.find("SequenceProps") is None:
        raise LoreditError("LOREDIT is missing the SequenceProps section")
    if document.root.find("TimingGrids") is None:
        raise LoreditError("LOREDIT is missing the TimingGrids section")
    _validate_sequence_prop_references(document.root)
    if document.source_path is not None:
        try:
            if output.resolve() == document.source_path.resolve():
                raise LoreditError("Refusing to overwrite the source LOREDIT file")
        except OSError as exc:
            raise LoreditError(f"Cannot resolve output path: {output}") from exc

    temporary: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(document.root)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            tree.write(stream, encoding="utf-8", xml_declaration=True)
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link is an atomic create-if-absent operation on the same volume.
        # Unlike replace/rename, it cannot overwrite an existing destination.
        os.link(temporary, output)
    except FileExistsError as exc:
        raise LoreditError(f"Output already exists; refusing to overwrite: {output}") from exc
    except OSError as exc:
        raise LoreditError(f"Cannot write LOREDIT output atomically: {output}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def semantic_xml(path: str | Path) -> str:
    """Return a stable XML representation for semantic round-trip assertions."""
    root = SafeET.parse(
        path, forbid_dtd=True, forbid_entities=True, forbid_external=True
    ).getroot()
    if root is None:
        raise LoreditError("LOREDIT XML has no document element")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)
