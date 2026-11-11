from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.choreography import (
    Choreography,
    Effect,
    Movement,
    Section,
    choreography_json,
)
from lor_sequence_builder.cli import main
from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.rules import load_rule_set
import lor_sequence_builder.sequence_writer as sequence_writer_module

from lor_sequence_builder.sequence_writer import (
    RulesFailedError,
    SequenceWriteError,
    build_from_timeline,
)
from tests.display_builders import DisplayBuilder, classic_yard

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _preview(tmp_path: Path, display: DisplayBuilder) -> Path:
    path = tmp_path / "yard.lorprev"
    ET.ElementTree(display.element()).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _ids(display: DisplayBuilder) -> dict[str, str]:
    return {p.get("Name", ""): p.get("id", "") for p in display.element().findall("PropClass")}


def _good(display: DisplayBuilder) -> Choreography:
    ids = _ids(display)
    arches = tuple(ids[f"Arch {i}"] for i in range(1, 5))
    return Choreography(
        duration_centiseconds=2000,
        effects=(
            *(Effect(p, 0, 100 + 25 * i, 200 + 25 * i, movement_id="chase")
              for i, p in enumerate(arches)),
            Effect(ids["Mega Tree"], 3, 400, 800, "fade", 0, 100),
            Effect(ids["Mega Tree"], 4, 400, 800, "twinkle", 60, 60),
            Effect(ids["Santa"], 2, 900, 1000, "shimmer", 80, 80, color="Green"),
        ),
        movements=(Movement("chase", "chase", arches, "left_to_right", 100, 300),),
        sections=(Section("intro", 0, 1000), Section("verse", 1000, 2000)),
    )


def test_a_passing_timeline_becomes_a_native_sequence(tmp_path: Path) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    before = preview.read_bytes()
    result = build_from_timeline(
        preview, _good(display), load_rule_set(), "Songs/Fictional Song.mp3",
        tmp_path / "out.loredit", tmp_path / "out.rules.json",
    )
    assert result.effect_count == 7 and result.report.ok
    assert result.excluded_props == ()
    persisted_report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert persisted_report["ok"] is True
    assert persisted_report["rules_ok"] is True
    assert persisted_report["build_status"] == "success"
    assert persisted_report["sequence_written"] is True
    assert persisted_report["excluded_props"] == []
    assert preview.read_bytes() == before

    document = read_loredit(result.sequence_path)
    root = document.root
    assert document.total_centiseconds == 2000
    assert root.attrib["musicFilename"] == "Songs/Fictional Song.mp3"
    ids = _ids(display)
    props = {seq.attrib["id"]: seq for seq in root.findall("./SequenceProps/SeqProp")}
    arch_effect = props[ids["Arch 2"]].findall("channel")[0].findall("effect")
    assert [e.attrib for e in arch_effect] == [{
        "startCentisecond": "125", "endCentisecond": "225", "intensity": "100",
        "settings": "INTENSITY",
    }]
    mega = props[ids["Mega Tree"]].findall("channel")
    assert mega[3].find("effect").attrib == {  # type: ignore[union-attr]
        "startCentisecond": "400", "endCentisecond": "800", "startIntensity": "0",
        "endIntensity": "100", "settings": "INTENSITY",
    }
    assert mega[4].find("effect").attrib["settings"] == "TWINKLE"  # type: ignore[union-attr]
    santa = props[ids["Santa"]].findall("channel")
    assert santa[2].find("effect").attrib["settings"] == "SHIMMER"  # type: ignore[union-attr]
    # Linked props get no sequence prop; the star rides on the mega tree.
    assert ids["Tree Topper"] not in props
    sections = root.find("./TimingGrids/TimingGridFree[@name='Sections']")
    assert sections is not None
    assert [t.attrib["centisecond"] for t in sections.findall("timing")] == ["0", "1000"]

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True


def test_a_timeline_that_breaks_the_rules_never_reaches_the_file(tmp_path: Path) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    good = _good(display)
    mega = _ids(display)["Mega Tree"]
    bad = Choreography(
        duration_centiseconds=good.duration_centiseconds,
        effects=(*good.effects, Effect(mega, 3, 700, 900)),
        movements=good.movements,
        sections=good.sections,
    )
    output = tmp_path / "out.loredit"
    report_path = tmp_path / "out.rules.json"
    with pytest.raises(RulesFailedError) as caught:
        build_from_timeline(preview, bad, load_rule_set(), "song.mp3", output, report_path)
    assert not output.exists()
    assert "1 rule error(s); the sequence was not written" in str(caught.value)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["rules_ok"] is False
    assert report["build_status"] == "failed"
    assert report["failure_stage"] == "rules"
    assert report["sequence_written"] is False
    finding = next(r for r in report["results"] if r["rule_id"] == "no_overlapping_effects")[
        "findings"][0]
    assert (finding["prop_name"], finding["channel_index"], finding["time"]) == (
        "Mega Tree", 3, "0:07.00")


def test_user_requirements_also_gate_the_writer(tmp_path: Path) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    rule_set = load_rule_set((EXAMPLES / "rules-sample-a.yaml",))
    with pytest.raises(RulesFailedError) as caught:
        build_from_timeline(preview, _good(display), rule_set, "song.mp3",
                            tmp_path / "out.loredit", tmp_path / "out.rules.json")
    # The fictional arches are red, and sample A says arches stay white.
    assert {f.rule_id for f in caught.value.report.errors} == {"arches-white"}
    assert not (tmp_path / "out.loredit").exists()


def test_writer_refuses_unsafe_paths(tmp_path: Path) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    good = _good(display)
    rules = load_rule_set()
    existing = tmp_path / "taken.loredit"
    existing.write_text("keep me", encoding="utf-8")
    for output, report, message in (
        (tmp_path / "out.txt", tmp_path / "r.json", ".loredit extension"),
        (tmp_path / "out.loredit", tmp_path / "r.txt", ".json extension"),
        (existing, tmp_path / "r.json", "already exists"),
    ):
        with pytest.raises(SequenceWriteError, match=message):
            build_from_timeline(preview, good, rules, "song.mp3", output, report)
    assert existing.read_text(encoding="utf-8") == "keep me"
    with pytest.raises(SequenceWriteError, match="relative path"):
        build_from_timeline(preview, good, rules, "C:\\Music\\song.mp3",
                            tmp_path / "x.loredit", tmp_path / "x.json")
    assert not (tmp_path / "x.loredit").exists()


def test_cli_check_build_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    timeline = tmp_path / "plan.json"
    timeline.write_text(choreography_json(_good(display)), encoding="utf-8")

    assert main(["check-timeline", str(preview), str(timeline)]) == 0
    out = capsys.readouterr().out
    assert "PASS no_overlapping_effects" in out and "N/A  falls_go_down" in out

    sample_a = str(EXAMPLES / "rules-sample-a.yaml")
    assert main(["check-timeline", str(preview), str(timeline), "--rules", sample_a,
                 "--report", str(tmp_path / "check.json")]) == 1
    out = capsys.readouterr().out
    assert "FAIL arches-white" in out and "Arch 1 channel 1 at 0:01.00: Shows red" in out
    assert json.loads((tmp_path / "check.json").read_text(encoding="utf-8"))["ok"] is False

    args = ["build-from-timeline", "--preview", str(preview), "--timeline", str(timeline),
            "--music-filename", "song.mp3", "--output", str(tmp_path / "a.loredit"),
            "--report", str(tmp_path / "a.json")]
    assert main([*args, "--rules", sample_a]) == 1
    assert not (tmp_path / "a.loredit").exists()
    assert "the sequence was not written" in capsys.readouterr().err
    (tmp_path / "a.json").unlink()
    assert main(args) == 0
    assert "Effects: 7" in capsys.readouterr().out
    assert (tmp_path / "a.loredit").exists()

    assert main(["list-rules", "--rules", sample_a]) == 0
    out = capsys.readouterr().out
    assert "no_overlapping_effects [error, locked]" in out
    assert "arches-white [error] colors_only: props identified as arch" in out

    bad_profile = tmp_path / "bad.yaml"
    bad_profile.write_text("schema_version: rules-1.0\nrules: {nope: {}}\n", encoding="utf-8")
    assert main(["list-rules", "--rules", str(bad_profile)]) == 2
    assert "nope is not a known rule" in capsys.readouterr().err
    timeline.write_text("{}", encoding="utf-8")
    assert main(["check-timeline", str(preview), str(timeline)]) == 2
    assert "missing" in capsys.readouterr().err


def test_timeline_writer_rejects_sparse_lor_channel_grid_without_compacting(
    tmp_path: Path,
) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    tree = ET.parse(preview)
    prop = tree.getroot().find("./PropClass[@Name='Arch 1']")
    assert prop is not None
    prop.set("ChannelGrid", "Regular,99,01,01,0,White;;Regular,99,01,03,0,White")
    tree.write(preview, encoding="utf-8", xml_declaration=True)

    output = tmp_path / "sparse.loredit"
    report = tmp_path / "sparse.json"
    with pytest.raises(SequenceWriteError, match="malformed LOR channel assignments"):
        build_from_timeline(preview, _good(display), load_rule_set(), "song.mp3", output, report)
    assert not output.exists()
    assert not report.exists()


def test_timeline_writer_rejects_missing_preview_group_identity(tmp_path: Path) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    tree = ET.parse(preview)
    root = tree.getroot()
    group = ET.SubElement(root, "PropGroup", {"Name": "Ambiguous"})
    ET.SubElement(group, "member", {"id": _ids(display)["Arch 1"]})
    tree.write(preview, encoding="utf-8", xml_declaration=True)

    with pytest.raises(SequenceWriteError, match="invalid prop/group identities"):
        build_from_timeline(
            preview, _good(display), load_rule_set(), "song.mp3",
            tmp_path / "invalid.loredit", tmp_path / "invalid.json",
        )


def test_failed_native_build_report_is_truthful_and_same_attempt_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    output = tmp_path / "retry.loredit"
    report_path = tmp_path / "retry.json"
    original_builder = sequence_writer_module.build_new_sequence

    def fail_native_build(*args: object, **kwargs: object) -> object:
        raise sequence_writer_module.NewSequenceError("synthetic native build failure")

    monkeypatch.setattr(sequence_writer_module, "build_new_sequence", fail_native_build)
    with pytest.raises(SequenceWriteError, match="synthetic native build failure"):
        build_from_timeline(
            preview, _good(display), load_rule_set(), "song.mp3", output, report_path
        )
    failed = json.loads(report_path.read_text(encoding="utf-8"))
    assert failed["ok"] is False
    assert failed["rules_ok"] is True
    assert failed["build_status"] == "failed"
    assert failed["failure_stage"] == "native_sequence"
    assert failed["sequence_written"] is False
    assert not output.exists()

    monkeypatch.setattr(sequence_writer_module, "build_new_sequence", original_builder)
    result = build_from_timeline(
        preview, _good(display), load_rule_set(), "song.mp3", output, report_path
    )
    succeeded = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.sequence_path.exists()
    assert succeeded["ok"] is True
    assert succeeded["build_status"] == "success"
    assert succeeded["sequence_written"] is True



def test_sequence_is_rolled_back_when_success_report_cannot_be_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    output = tmp_path / "rollback.loredit"
    report_path = tmp_path / "rollback.json"
    original = sequence_writer_module._write_build_report

    def fail_success_report(*args: object, **kwargs: object) -> None:
        if kwargs.get("status") == "success":
            raise SequenceWriteError("synthetic report publication failure")
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sequence_writer_module, "_write_build_report", fail_success_report)
    with pytest.raises(SequenceWriteError, match="sequence was removed"):
        build_from_timeline(
            preview, _good(display), load_rule_set(), "song.mp3", output, report_path
        )

    assert not output.exists()
    assert not report_path.exists()


def test_timeline_writer_reports_excluded_preview_props(tmp_path: Path) -> None:
    display = classic_yard()
    display.add(
        "Unverified DMX Prop", "unknown", shape="Square", channels=1,
        device="DMX",
    )
    preview = _preview(tmp_path, display)
    result = build_from_timeline(
        preview, _good(display), load_rule_set(), "song.mp3",
        tmp_path / "with-exclusion.loredit", tmp_path / "with-exclusion.json",
    )

    assert len(result.excluded_props) == 1
    assert result.excluded_props[0].name == "Unverified DMX Prop"
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["build_status"] == "success"
    assert report["excluded_props"][0]["name"] == "Unverified DMX Prop"
    assert "no verified native channel layout" in report["excluded_props"][0]["reason"]
