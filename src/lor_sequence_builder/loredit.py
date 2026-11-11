"""Semantically preserving reader and writer for the observed S6 LOREDIT v15 format.

The implementation intentionally treats the sequence as an opaque XML document:
unknown elements and attributes are retained rather than interpreted or rebuilt.
XML serialization does not preserve original bytes, comments, BOMs, or line endings.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from lor_sequence_builder.file_publish import write_new_file

SUPPORTED_SAVE_FILE_VERSION = "15"
MAX_LOREDIT_BYTES = 50 * 1024 * 1024
MAX_XML_DEPTH = 256
MAX_LOREDIT_ELEMENTS = 250_000


class LoreditError(ValueError):
    """Base error for invalid or unsupported LOREDIT documents."""


class UnsupportedLoreditVersionError(LoreditError):
    """Raised when a sequence uses an unverified save-file version."""


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
        content = source.read_bytes()
        iterator = SafeET.iterparse(
            io.BytesIO(content),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        depth = 0
        element_count = 0
        for event, _element in iterator:
            if event == "start":
                depth += 1
                element_count += 1
                if depth > MAX_XML_DEPTH:
                    raise LoreditError(
                        f"LOREDIT XML nesting exceeds the maximum depth of {MAX_XML_DEPTH}"
                    )
                if element_count > MAX_LOREDIT_ELEMENTS:
                    raise LoreditError(
                        "LOREDIT XML exceeds the maximum element count "
                        f"of {MAX_LOREDIT_ELEMENTS}"
                    )
            else:
                depth -= 1
        root = SafeET.fromstring(
            content, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except LoreditError:
        raise
    except (OSError, ET.ParseError, DefusedXmlException) as exc:
        raise LoreditError(f"Invalid or unsafe LOREDIT XML: {source}") from exc

    if root is None:
        raise LoreditError("LOREDIT XML has no document element")
    if root.tag != "sequence":
        raise LoreditError("LOREDIT root element must be <sequence>")
    version = root.attrib.get("saveFileVersion")
    if version != SUPPORTED_SAVE_FILE_VERSION:
        raise UnsupportedLoreditVersionError(
            f"Unsupported LOREDIT saveFileVersion {version!r}; "
            f"verified version is {SUPPORTED_SAVE_FILE_VERSION}"
        )
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

    preview_ids = {
        prop.attrib["id"]
        for prop in preview.findall("PropClass")
        if prop.attrib.get("id")
    }
    preview_ids.update(
        group.attrib["id"]
        for group in preview.findall("PropGroup")
        if group.attrib.get("id")
    )
    orphan_ids = [
        prop.attrib.get("id", "<missing id>")
        for prop in sequence_props.findall("SeqProp")
        if prop.attrib.get("id") not in preview_ids
    ]
    if orphan_ids:
        joined = ", ".join(orphan_ids)
        raise LoreditError(
            "SequenceProps contains prop IDs missing from PreviewClass; "
            f"S6 may discard them when saving: {joined}"
        )


def write_loredit(document: LoreditDocument, output_path: str | Path) -> Path:
    """Create a new LOREDIT file without replacing an existing path."""
    output = Path(output_path)
    if document.root.tag != "sequence":
        raise LoreditError("Cannot write a document whose root is not <sequence>")
    if document.save_file_version != SUPPORTED_SAVE_FILE_VERSION:
        raise UnsupportedLoreditVersionError(
            f"Cannot write unverified saveFileVersion {document.save_file_version!r}"
        )
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

    try:
        tree = ET.ElementTree(document.root)
        write_new_file(
            output,
            lambda stream: tree.write(stream, encoding="utf-8", xml_declaration=True),
        )
    except FileExistsError as exc:
        raise LoreditError(f"Output already exists; refusing to overwrite: {output}") from exc
    except OSError as exc:
        raise LoreditError(f"Cannot create LOREDIT output: {output}") from exc
    return output


def semantic_xml(path: str | Path) -> str:
    """Return a stable XML representation for semantic round-trip assertions."""
    root = SafeET.parse(
        path, forbid_dtd=True, forbid_entities=True, forbid_external=True
    ).getroot()
    if root is None:
        raise LoreditError("LOREDIT XML has no document element")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)
