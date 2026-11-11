from __future__ import annotations

import json
import random
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import pytest

from lor_sequence_builder.classifier import (
    ClassificationError,
    PropClassification,
    classification_report,
    classify_preview,
)
from lor_sequence_builder.cli import main
from lor_sequence_builder.new_sequence import channel_layout_problem
from tests.display_builders import (
    ALL_DISPLAYS,
    DisplayBuilder,
    classic_yard,
    misleading_names,
    unsupported_hardware,
)


def _by_name(display: DisplayBuilder) -> dict[str, PropClassification]:
    return {c.name: c for c in classify_preview(display.element())}


@pytest.mark.parametrize("make", ALL_DISPLAYS, ids=lambda f: f.__name__)
def test_every_fictional_display_matches_its_known_answers(
    make: Callable[[], DisplayBuilder],
) -> None:
    display = make()
    results = classify_preview(display.element())
    assert {r.prop_id: r.role for r in results} == display.expected


@pytest.mark.parametrize("make", ALL_DISPLAYS, ids=lambda f: f.__name__)
def test_names_can_never_switch_a_role(make: Callable[[], DisplayBuilder]) -> None:
    display = make()
    original = {r.prop_id: r for r in classify_preview(display.element())}
    renamed = make().element()
    for index, prop in enumerate(renamed.findall("PropClass")):
        prop.set("Name", f"Zq {index}")
    for result in classify_preview(renamed):
        before = original[result.prop_id]
        # Without names a role may lose confidence, but it never becomes a different role.
        assert result.role in {before.role, "unknown"}
        if before.role != "unknown" and not any(
            e.reason.startswith("Name ") for e in before.evidence if e.role == before.role
        ):
            assert result.role == before.role


def test_a_name_alone_never_assigns_a_role() -> None:
    results = _by_name(misleading_names())
    arch_seven = results["Arch 7"]
    assert arch_seven.role == "unknown"
    assert any("name only" in note for note in arch_seven.review_notes)
    assert results["Mega Tree"].role == "arch"
    assert results["Arch 3"].role == "star"


def test_color_capability_follows_the_prop_type() -> None:
    results = _by_name(classic_yard())
    arch = results["Arch 1"].color_capability
    mega = results["Mega Tree"].color_capability
    face = results["Santa"].color_capability
    assert (arch.kind, arch.can_show_single_color) == ("single_color", True)
    assert (mega.kind, mega.can_show_single_color) == ("combined_colors", False)
    assert "no single color can be shown alone" in mega.note
    assert (face.kind, face.colors) == ("color_per_channel", ("White", "Red", "Green"))


def test_rows_follow_group_order_or_left_to_right_position() -> None:
    display = classic_yard()
    root = display.element()
    props = root.findall("PropClass")
    shuffled = props[:]
    random.Random(7).shuffle(shuffled)
    for prop in props:
        root.remove(prop)
    for prop in reversed(shuffled):
        root.insert(1, prop)

    results = {r.name: r for r in classify_preview(root)}

    assert [results[f"Arch {i}"].position_in_row for i in range(1, 5)] == [1, 2, 3, 4]
    assert results["Arch 1"].group == "Arches"
    # Mini trees have no group, so their row is ordered left to right in the preview.
    assert [results[f"Mini Tree {i}"].position_in_row for i in range(1, 5)] == [1, 2, 3, 4]
    assert results["Mini Tree 1"].group is None


def test_direction_comes_from_the_string_start_location() -> None:
    results = _by_name(classic_yard())
    assert results["Mega Tree"].direction == "left_to_right"
    assert results["Santa"].direction == "not applicable"
    thing = _by_name(misleading_names())["Thing 12"]
    assert thing.direction == "unknown"
    assert any("Direction unknown" in note for note in thing.review_notes)


def test_linked_and_unsupported_props_report_why() -> None:
    star = _by_name(classic_yard())["Tree Topper"]
    assert star.sequencing_support == "driven by its master prop"
    assert star.linked_to is not None

    display = unsupported_hardware()
    root = display.element()
    props = {p.get("Name"): p for p in root.findall("PropClass")}
    results = {r.name: r for r in classify_preview(root)}
    for name in ("Pixel Arch", "Old Roof", "Mystery Prop"):
        assert results[name].sequencing_support == channel_layout_problem(props[name])
        assert results[name].status in {"review", "unknown"}
    assert results["Pixel Arch"].role == "arch"


def test_classifier_rejects_non_previews() -> None:
    with pytest.raises(ClassificationError, match="PreviewClass"):
        classify_preview(ET.Element("sequence"))
    with pytest.raises(ClassificationError, match="zero"):
        classify_preview(ET.Element("PreviewClass"))


def test_report_carries_every_conclusion_with_evidence() -> None:
    results = classify_preview(classic_yard().element())
    report = classification_report(results, "yard.lorprev")
    json.dumps(report)
    summary = report["summary"]
    assert isinstance(summary, dict) and summary["props"] == 11
    props = report["props"]
    assert isinstance(props, list)
    assert all(p["evidence"] or p["role"] == "unknown" for p in props)
    assert "Preview Editor" in str(report["how_to_correct"])


def _write_preview(path: Path, display: DisplayBuilder) -> Path:
    ET.ElementTree(display.element()).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_cli_analyze_preview_prints_and_writes_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preview = _write_preview(tmp_path / "names.lorprev", misleading_names())
    before = preview.read_bytes()
    report = tmp_path / "report.json"

    assert main(["analyze-preview", str(preview), "--report", str(report)]) == 0

    out = capsys.readouterr().out
    assert "Arch 7: unknown" in out and "name only" in out
    assert "Preview Editor" in out
    assert json.loads(report.read_text(encoding="utf-8"))["summary"]["props"] == 5
    assert preview.read_bytes() == before
    assert main(["analyze-preview", str(preview), "--report", str(report)]) == 2
    assert "already exists" in capsys.readouterr().err


def test_cli_analyze_preview_requires_a_real_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["analyze-preview", str(tmp_path / "missing.lorprev")]) == 2
    assert "error" in capsys.readouterr().err
