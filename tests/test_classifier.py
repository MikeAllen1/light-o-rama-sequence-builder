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
    line_drawn_yard,
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
        # Figure evidence comes from other props' names, so it may fade too.
        name_dependent = any(
            e.reason.startswith(("Name ", "Drawn as one figure", "Linked to face part"))
            for e in before.evidence if e.role == before.role
        )
        if before.role != "unknown" and not name_dependent:
            assert result.role == before.role


def test_names_decide_only_when_the_shape_says_nothing() -> None:
    results = _by_name(misleading_names())
    # Plain lines: the name decides, flagged for review.
    arch_seven = results["Arch 7"]
    assert (arch_seven.role, arch_seven.status) == ("arch", "review")
    assert any("Identified from its name" in note for note in arch_seven.review_notes)
    # Specific S6 shapes beat names.
    assert results["Mega Tree"].role == "arch"
    assert results["Arch 3"].role == "star"
    # Structural evidence beats a name that points elsewhere ("Santa" alone suggests decor).
    santa = _by_name(classic_yard())["Santa"]
    assert santa.role == "singing_face"
    assert any(e.reason.startswith("Name ") and e.weight <= 0.25 for e in santa.evidence)


def test_rows_need_props_that_actually_look_alike() -> None:
    results = _by_name(line_drawn_yard())
    for name in ("Reindeer", "Snowman", "Toy Train", "Yard Santa"):
        assert results[name].position_in_row is None
    assert [results[f"Column {i}"].position_in_row for i in (1, 2, 3)] == [1, 2, 3]
    assert {results[f"Column {i}"].row_size for i in (1, 2, 3)} == {3}
    # Parts of one figure are never a row.
    assert results["Mouth Open"].position_in_row is None


def test_a_face_built_from_overlapping_parts_is_one_figure() -> None:
    results = _by_name(line_drawn_yard())
    parts = ("Face Outline", "Mouth Open", "Mouth Closed", "Face Eyes", "Santa Cap")
    for name in parts:
        assert results[name].role == "singing_face"
        assert set(results[name].figure) == set(parts) - {name}
    assert results["Face Eyes"].sequencing_support == "driven by its master prop"
    # A linked part drawn on the face joins it even though "Santa" alone suggests decor.
    assert results["Santa Cap"].role == "singing_face"
    assert results["Yard Santa"].role == "decor"
    assert results["Yard Santa"].figure == ()


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


@pytest.mark.parametrize(
    "ids",
    [
        ("", "second"),
        ("   ", "second"),
        ("duplicate", "duplicate"),
    ],
)
def test_classifier_rejects_missing_blank_and_duplicate_prop_ids(ids: tuple[str, str]) -> None:
    root = classic_yard().element()
    props = root.findall("PropClass")
    props[0].set("id", ids[0])
    props[1].set("id", ids[1])
    with pytest.raises(ClassificationError, match="id"):
        classify_preview(root)


@pytest.mark.parametrize(
    ("master_reference", "master_setup", "message"),
    [
        ("missing-master", None, "missing master"),
        ("self", "self", "cannot reference itself"),
        ("chain", "chain", "master chains and cycles"),
        ("unsupported", "unsupported", "without a verified native channel layout"),
    ],
)
def test_classifier_rejects_invalid_master_links(
    master_reference: str, master_setup: str | None, message: str
) -> None:
    root = classic_yard().element()
    props = root.findall("PropClass")
    linked, master = props[1], props[0]
    if master_setup == "self":
        linked.set("MasterPropId", linked.get("id", ""))
    elif master_setup == "chain":
        master.set("MasterPropId", props[2].get("id", ""))
        linked.set("MasterPropId", master.get("id", ""))
    elif master_setup == "unsupported":
        master.set("DeviceType", "DMX")
        linked.set("MasterPropId", master.get("id", ""))
    else:
        linked.set("MasterPropId", master_reference)
    with pytest.raises(ClassificationError, match=message):
        classify_preview(root)


def test_classifier_treats_whitespace_master_reference_as_unlinked() -> None:
    root = classic_yard().element()
    prop = root.findall("PropClass")[1]
    prop.set("MasterPropId", " \t\n ")
    result = next(item for item in classify_preview(root) if item.prop_id == prop.get("id"))
    assert result.linked_to is None
    assert result.sequencing_support == "supported"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_classifier_rejects_non_finite_shape_parameters(value: str) -> None:
    root = classic_yard().element()
    mega_tree = next(p for p in root.findall("PropClass") if p.get("Name") == "Mega Tree")
    mega_tree.set("Parm1", value)
    with pytest.raises(ClassificationError, match="non-finite"):
        classify_preview(root)


def test_figure_detection_uses_spatial_index_instead_of_all_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lor_sequence_builder import classifier

    props: list[ET.Element] = []
    geometries: dict[str, classifier._Geometry | None] = {}
    for index in range(2_000):
        prop_id = f"p{index}"
        props.append(ET.Element("PropClass", {"id": prop_id}))
        geometries[prop_id] = classifier._Geometry(
            center_x=float(index), center_y=0.0, width=0.1, height=0.1,
            closed=False, arc_like=False,
        )
    calls = 0
    original = classifier._overlap

    def counted(left: classifier._Geometry, right: classifier._Geometry) -> float:
        nonlocal calls
        calls += 1
        return original(left, right)

    monkeypatch.setattr(classifier, "_overlap", counted)
    assert classifier._figures(props, geometries) == {}
    assert calls < 2_000


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
    assert "Arch 7: arch" in out and "Identified from its name" in out
    assert "Preview Editor" in out
    assert json.loads(report.read_text(encoding="utf-8"))["summary"]["props"] == 5
    assert preview.read_bytes() == before
    assert main(["analyze-preview", str(preview), "--report", str(report)]) == 2
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("identity", ["missing", "duplicate"])
def test_cli_analyze_preview_rejects_invalid_prop_identities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], identity: str
) -> None:
    display = classic_yard()
    root = display.element()
    props = root.findall("PropClass")
    if identity == "missing":
        props[0].attrib.pop("id")
    else:
        props[1].set("id", props[0].get("id", ""))
    preview = tmp_path / f"{identity}.lorprev"
    ET.ElementTree(root).write(preview, encoding="utf-8", xml_declaration=True)
    report = tmp_path / f"{identity}.json"

    assert main(["analyze-preview", str(preview), "--report", str(report)]) == 2
    assert "error:" in capsys.readouterr().err
    assert not report.exists()


def test_cli_analyze_preview_requires_a_real_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["analyze-preview", str(tmp_path / "missing.lorprev")]) == 2
    assert "error" in capsys.readouterr().err
