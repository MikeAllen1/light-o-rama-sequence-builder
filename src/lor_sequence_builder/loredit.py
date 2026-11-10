"""Loss-preserving reader and writer for the observed S6 LOREDIT v15 format.

The implementation intentionally treats the sequence as an opaque XML document:
unknown elements and attributes are retained rather than interpreted or rebuilt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

SUPPORTED_SAVE_FILE_VERSION = "15"
MAX_LOREDIT_BYTES = 50 * 1024 * 1024


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
        return self.root.attrib["saveFileVersion"]

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
        root = SafeET.parse(source).getroot()
    except (OSError, ET.ParseError, DefusedXmlException) as exc:
        raise LoreditError(f"Invalid or unsafe LOREDIT XML: {source}") from exc

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

    S6 warns that these records will be removed on save. Preview-only props are
    allowed because the observed fixture contains preview entities that are not
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
    """Write a new LOREDIT file; refuse to overwrite any existing path."""
    output = Path(output_path)
    if document.root.tag != "sequence":
        raise LoreditError("Cannot write a document whose root is not <sequence>")
    if document.save_file_version != SUPPORTED_SAVE_FILE_VERSION:
        raise UnsupportedLoreditVersionError(
            f"Cannot write unverified saveFileVersion {document.save_file_version!r}"
        )
    if document.source_path is not None:
        try:
            if output.resolve() == document.source_path.resolve():
                raise LoreditError("Refusing to overwrite the source LOREDIT file")
        except OSError as exc:
            raise LoreditError(f"Cannot resolve output path: {output}") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(document.root)
    try:
        with output.open("xb") as stream:
            tree.write(stream, encoding="utf-8", xml_declaration=True)
    except FileExistsError as exc:
        raise LoreditError(f"Output already exists; refusing to overwrite: {output}") from exc
    except OSError as exc:
        raise LoreditError(f"Cannot write LOREDIT output: {output}") from exc
    return output


def semantic_xml(path: str | Path) -> str:
    """Return a stable XML representation for semantic round-trip assertions."""
    root = SafeET.parse(path).getroot()
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)
