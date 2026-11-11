"""Build a ready-to-open Phase 3 validation ZIP from the sanitized S6 fixtures."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from lor_sequence_builder.loredit import (
    read_loredit,
    strip_local_preview_background_references,
)
from lor_sequence_builder.pulse import build_pulse_sequence

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATE_FIXTURE = FIXTURES / "s6_revision_56_independent_template.loredit.gz.b64"

PACKAGE_README = """PHASE 3 LIGHT-O-RAMA S6 TEST

1. Extract this ZIP.
2. Double-click Phase3-Test.loredit to open it in Light-O-Rama S6.
3. Press Play and watch the sequence preview.

Expected result: the sequence opens and the supported sample props pulse
at a steady 60 BPM. The included Timeline JSON is a technical record of
the generated events; you do not need it to run the test.

IMPORTANT: These are sanitized, fictional test fixtures. This test checks
native S6 file compatibility and sequence-preview animation only. It does
not address or activate your real controllers or validate your house's
physical channel mapping. Do not use this sample as a live-show sequence.
"""


def _decode_fixture(source: Path, destination: Path) -> None:
    """Decode the repository's base64-wrapped gzip fixture without modifying it."""
    encoded = source.read_text(encoding="ascii")
    destination.write_bytes(gzip.decompress(base64.b64decode(encoded, validate=True)))


def _strip_local_background_references(template: Path) -> None:
    """Remove workstation-specific preview image paths from the test template."""
    tree = ET.parse(template)
    removed = strip_local_preview_background_references(tree.getroot())
    if removed == 0:
        raise RuntimeError(
            "Expected a workstation-specific preview background reference, "
            "but none was found; review the fixture before packaging."
        )
    tree.write(template, encoding="utf-8", xml_declaration=True)

def _assert_no_local_background_references(sequence: Path) -> None:
    """Fail package creation if any local preview background reference survives."""
    root = ET.parse(sequence).getroot()
    for element in root.iter():
        for attribute in element.attrib:
            if attribute.casefold() in {
                "backgroundfile",
                "backgroundimage",
                "backgroundimagefile",
            }:
                raise RuntimeError(
                    "Generated validation sequence still contains a local "
                    "preview background reference."
                )


def build_package(destination: Path) -> None:
    """Generate, validate, and package the sample sequence and Timeline."""
    if not TEMPLATE_FIXTURE.is_file():
        raise FileNotFoundError("The committed independent Phase 3 template fixture is missing.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    with tempfile.TemporaryDirectory(prefix="lor-phase3-validation-") as temp_dir:
        work = Path(temp_dir)
        preview = work / "display.lorprev"
        template = work / "template.loredit"
        sequence = work / "Phase3-Test.loredit"
        timeline_path = work / "Phase3-Test.timeline.json"

        _decode_fixture(TEMPLATE_FIXTURE, template)
        _strip_local_background_references(template)
        template_root = ET.parse(template).getroot()
        embedded_preview = template_root.find("PreviewClass")
        if embedded_preview is None:
            raise RuntimeError("The native S6 template does not contain an embedded PreviewClass.")
        ET.ElementTree(embedded_preview).write(
            preview, encoding="utf-8", xml_declaration=True
        )

        result = build_pulse_sequence(
            preview_path=preview,
            template_path=template,
            output_path=sequence,
            timeline_path=timeline_path,
            bpm=60,
            pulse_duration_centiseconds=10,
        )

        # Re-open the exact output through the production reader before packaging.
        document = read_loredit(sequence)
        _assert_no_local_background_references(sequence)
        if document.save_file_version != "15":
            raise RuntimeError("Generated test sequence is not native LOREDIT v15.")

        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        required = {
            "schema_version",
            "bpm",
            "duration_centiseconds",
            "beat_positions_centiseconds",
            "supported_prop_ids",
            "excluded_props",
            "events",
        }
        if not required.issubset(timeline):
            raise RuntimeError("Generated Timeline JSON is missing required fields.")
        if timeline["schema_version"] != "1.0" or timeline["bpm"] != 60:
            raise RuntimeError("Generated Timeline does not match the Phase 3 test settings.")
        if not timeline["events"] or not timeline["beat_positions_centiseconds"]:
            raise RuntimeError("Generated Timeline contains no pulse events or beat positions.")

        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(sequence, "Phase3-Test.loredit")
            archive.write(timeline_path, "Phase3-Test.timeline.json")
            archive.writestr("README-FIRST.txt", PACKAGE_README)

        print(f"Package: {destination}")
        print(f"Native LOREDIT version: {document.save_file_version}")
        print(f"Supported props: {result.supported_prop_count}")
        print(f"Excluded props: {result.excluded_prop_count}")
        print(f"Beats: {result.beat_count}")
        print(f"Pulse events: {result.event_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "Phase3-S6-Validation.zip",
        help="destination ZIP path (default: dist/Phase3-S6-Validation.zip)",
    )
    args = parser.parse_args()
    build_package(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
