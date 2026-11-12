"""Adding new props to a finished sequence. Every display and sequence here is invented."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lor_sequence_builder.add_props import AddPropsError, add_props, song_shape
from lor_sequence_builder.cli import main
from lor_sequence_builder.generate import generate_show
from lor_sequence_builder.lms import read_lms
from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.rules import load_rule_set
from lor_sequence_builder.style import get_style
from lor_sequence_builder.style_learning import sequence_effects
from tests.display_builders import DisplayBuilder, classic_yard
from tests.test_lms import s4_sequence
from tests.test_planner import synthetic_analysis


def _write_preview(path: Path, display: DisplayBuilder) -> Path:
    ET.ElementTree(display.element()).write(path, encoding="utf-8", xml_declaration=True)
    return path


def this_year() -> DisplayBuilder:
    """Last year's yard plus two new props: a row of three snowmen."""
    display = classic_yard()
    for i in range(3):
        display.add(f"Snowman {i + 1}", "decor", shape="Square", channels=1,
                    box=(-0.4 + 0.12 * i, -0.4, 0.05, 0.08), unit="30")
    return display


@pytest.fixture
def last_year(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """A finished show for last year's yard, with a two-second stop in the middle."""
    folder = tmp_path / "last year"
    folder.mkdir()
    preview = _write_preview(folder / "yard.lorprev", classic_yard())
    analysis = synthetic_analysis(stops=((30.0, 2.0),))
    analysis_path = folder / "song.analysis.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    show = generate_show(preview, folder / "Song.loredit", load_rule_set(),
                         analysis_path=analysis_path, music_filename="Song.mp3",
                         style=get_style("energetic"))
    return show.sequence_path, analysis


def _seq_props(path: Path) -> dict[str, bytes]:
    root = read_loredit(path).root
    return {p.get("id", ""): ET.tostring(p) for p in root.iterfind("SequenceProps/SeqProp")}


def test_new_props_are_added_and_nothing_else_changes(
        tmp_path: Path, last_year: tuple[Path, dict[str, object]]) -> None:
    sequence, _ = last_year
    before_bytes = sequence.read_bytes()
    preview = _write_preview(tmp_path / "this year.lorprev", this_year())
    result = add_props(sequence, tmp_path / "Song (new props).loredit", load_rule_set(),
                       preview_path=preview)
    assert sequence.read_bytes() == before_bytes  # the original is untouched
    assert result.added == ("Snowman 1", "Snowman 2", "Snowman 3")
    assert result.report.ok and not result.from_song
    assert result.quality is not None and result.quality.score >= 80
    before = _seq_props(sequence)
    after = _seq_props(result.sequence_path)
    # Every existing prop, effects and all, exactly as it was, in the same order.
    assert list(after)[:len(before)] == list(before)
    assert all(after[pid] == xml for pid, xml in before.items())
    new = [pid for pid in after if pid not in before]
    assert len(new) == 3 and all(b"<effect" in after[pid] for pid in new)
    # The updated preview is embedded, and everything else in the file is kept.
    old_root = read_loredit(sequence).root
    new_root = read_loredit(result.sequence_path).root
    names = {p.get("Name") for p in new_root.iterfind("PreviewClass/PropClass")}
    assert {"Snowman 1", "Arch 1"} <= names
    assert [c.tag for c in new_root] == [c.tag for c in old_root]
    old_grids, new_grids = old_root.find("TimingGrids"), new_root.find("TimingGrids")
    assert old_grids is not None and new_grids is not None
    assert ET.tostring(new_grids) == ET.tostring(old_grids)
    assert new_root.attrib == old_root.attrib
    # The snowmen take turns, as look-alikes do.
    timelines = {pid: [(e.start, e.end) for e in sequence_effects(new_root, False)[0]
                       if e.channel.startswith(pid + "/")] for pid in new}
    assert len({tuple(t) for t in timelines.values()}) == 3


def test_new_props_stay_dark_where_the_sequence_goes_dark(
        tmp_path: Path, last_year: tuple[Path, dict[str, object]]) -> None:
    sequence, _ = last_year
    preview = _write_preview(tmp_path / "this year.lorprev", this_year())
    result = add_props(sequence, tmp_path / "out.loredit", load_rule_set(),
                       preview_path=preview)
    lits, _ = sequence_effects(read_loredit(sequence).root, False)
    dark_start = 3000
    assert not any(lit.start < 3200 and lit.end > dark_start for lit in lits)
    new = [e for e in result.plan.choreography.effects]
    assert new and not any(e.start_centisecond < 3200 and e.end_centisecond > dark_start
                           for e in new)


def test_the_song_shape_is_read_from_the_sequence(
        last_year: tuple[Path, dict[str, object]]) -> None:
    sequence, analysis = last_year
    root = read_loredit(sequence).root
    lits, marks = sequence_effects(root, False)
    shape = song_shape(lits, marks, int(root.get("totalCentiseconds", "0")),
                       len({lit.channel for lit in lits}))
    beats = [round(b["time"] * 100) for b in shape["analysis"]["beats"]]
    real = [round(b["time"] * 100) for b in analysis["analysis"]["beats"]]  # type: ignore[index]
    # Every beat found is a beat of the song (the grid in the file is the song's).
    on_beat = sum(1 for b in beats if any(abs(b - r) <= 2 for r in real))
    assert len(beats) >= 0.9 * len(real) and on_beat >= 0.9 * len(beats)
    stops = [(s["time"], s["silence_duration"]) for s in shape["analysis"]["hard_stops"]]
    assert any(abs(t - 30.0) < 0.3 and d >= 1.5 for t, d in stops)
    # The loud part lights more of the yard than the quiet intro.
    energy = {round(f["time"] * 100): f["rms"] for f in shape["analysis"]["energy"]}
    quiet = sum(v for t, v in energy.items() if 200 <= t < 1400)
    loud = sum(v for t, v in energy.items() if 3400 <= t < 4600)
    assert loud > quiet


def test_props_added_inside_the_sequence_are_filled_without_a_preview(
        tmp_path: Path, last_year: tuple[Path, dict[str, object]]) -> None:
    # Someone added the snowmen to the sequence's own preview in the Sequencer and
    # left them empty.
    sequence, _ = last_year
    preview = _write_preview(tmp_path / "this year.lorprev", this_year())
    first = add_props(sequence, tmp_path / "with snowmen.loredit", load_rule_set(),
                      preview_path=preview)
    root = read_loredit(first.sequence_path).root
    snowmen = [p for p in root.iterfind("SequenceProps/SeqProp")
               if (p.get("name") or "").startswith("Snowman")]
    for prop in snowmen:
        for channel in prop.findall("channel"):
            for effect in channel.findall("effect"):
                channel.remove(effect)
    emptied = tmp_path / "emptied.loredit"
    ET.ElementTree(root).write(emptied, encoding="utf-8", xml_declaration=True)
    second = add_props(emptied, tmp_path / "filled.loredit", load_rule_set())
    assert second.added == ("Snowman 1", "Snowman 2", "Snowman 3")


def test_unsafe_changes_are_refused(tmp_path: Path,
                                    last_year: tuple[Path, dict[str, object]]) -> None:
    sequence, _ = last_year
    rules = load_rule_set()
    # Nothing new.
    same = _write_preview(tmp_path / "same.lorprev", classic_yard())
    with pytest.raises(AddPropsError, match="nothing new"):
        add_props(sequence, tmp_path / "a.loredit", rules, preview_path=same)
    # A prop taken away.
    smaller = classic_yard()
    removed = smaller.root.find(f"PropClass[@id='{smaller.prop_id('Arch 4')}']")
    assert removed is not None
    smaller.root.remove(removed)
    for group in smaller.root.findall("PropGroup"):
        for member in group.findall("member"):
            if member.get("id") == smaller.prop_id("Arch 4"):
                group.remove(member)
    path = _write_preview(tmp_path / "smaller.lorprev", smaller)
    with pytest.raises(AddPropsError, match="no longer has Arch 4"):
        add_props(sequence, tmp_path / "b.loredit", rules, preview_path=path)
    # Overwriting the original, or an existing file.
    with pytest.raises(AddPropsError, match="already exists"):
        add_props(sequence, sequence, rules)
    with pytest.raises(AddPropsError, match="loredit"):
        add_props(sequence, tmp_path / "c.lms", rules,
                  preview_path=_write_preview(tmp_path / "new.lorprev", this_year()))


def test_s4_channels_added_in_the_s4_sequencer_are_filled(tmp_path: Path) -> None:
    # Last year's S4 show for five channels, made by this program; this year a sixth
    # channel was added in the S4 Sequencer and left empty.
    template = tmp_path / "Display.lms"
    template.write_bytes(s4_sequence())
    analysis_path = tmp_path / "song.analysis.json"
    analysis_path.write_text(json.dumps(synthetic_analysis()), encoding="utf-8")
    show = generate_show(template, tmp_path / "Song.lms", load_rule_set(),
                         analysis_path=analysis_path, music_filename="Song.mp3")
    root = ET.fromstring(show.sequence_path.read_bytes())
    channels = root.find("channels")
    assert channels is not None
    roof = next(c for c in channels.findall("channel") if c.get("name") == "Roof Line")
    before = {c.get("savedIndex"): ET.tostring(c) for c in channels.findall("channel")}
    for effect in roof.findall("effect"):
        roof.remove(effect)
    emptied = tmp_path / "This year.lms"
    emptied.write_bytes(ET.tostring(root))
    result = add_props(emptied, tmp_path / "This year (filled).lms", load_rule_set())
    assert result.added == ("Roof Line",)
    after_root = read_lms(result.sequence_path).root
    after = {c.get("savedIndex"): ET.tostring(c) for c in after_root.iterfind(
        "channels/channel")}
    for index, xml in before.items():
        if index != roof.get("savedIndex"):
            assert after[index] == xml
    assert after[roof.get("savedIndex")].count(b"<effect") > 5
    with pytest.raises(AddPropsError, match="already has effects|Every LOR channel"):
        add_props(show.sequence_path, tmp_path / "again.lms", load_rule_set())
    with pytest.raises(AddPropsError, match="no separate preview"):
        add_props(emptied, tmp_path / "x.lms", load_rule_set(),
                  preview_path=tmp_path / "anything.lorprev")


def test_add_props_on_the_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                       last_year: tuple[Path, dict[str, object]]) -> None:
    sequence, _ = last_year
    preview = _write_preview(tmp_path / "this year.lorprev", this_year())
    output = tmp_path / "Song 2026.loredit"
    assert main(["add-props", "--sequence", str(sequence), "--preview", str(preview),
                 "--output", str(output), "--ignore-saved-requirements"]) == 0
    out = capsys.readouterr().out
    assert "Added 3 prop(s): Snowman 1, Snowman 2, Snowman 3" in out
    assert "read from the sequence" in out and output.is_file()
    assert main(["add-props", "--sequence", str(sequence), "--preview", str(preview),
                 "--output", str(output), "--ignore-saved-requirements"]) == 2
    assert "already exists" in capsys.readouterr().err



def test_the_app_adds_props_to_a_sequence(tmp_path: Path,
                                          last_year: tuple[Path, dict[str, object]]) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    import threading
    from http.server import ThreadingHTTPServer

    from lor_sequence_builder.ui_server import SequencerRequestHandler

    sequence, _ = last_year
    preview = _write_preview(tmp_path / "this year.lorprev", this_year())
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
            status = page.locator("#addStatus")
            assert page.locator("#addBuild").is_disabled()
            page.locator("#addSequenceFile").set_input_files(str(sequence))
            status.filter(has_text="effects on").wait_for()
            page.locator("#addPreviewFile").set_input_files(str(preview))
            status.filter(has_text="Preview read").wait_for()
            page.locator("#addBuild").click()
            status.filter(has_text="Added 3 prop(s)").wait_for(timeout=60000)
            assert "Everything else is unchanged" in status.inner_text()
            assert page.locator("#addNotes li").count() >= 1
            with page.expect_download() as download:
                page.locator("#addSave").click()
            assert download.value.suggested_filename == "Song (new props).loredit"
            saved = tmp_path / "saved.loredit"
            download.value.save_as(saved)
            assert {"Snowman 1", "Snowman 2", "Snowman 3"} <= {
                p.get("name") for p in read_loredit(saved).root.iterfind(
                    "SequenceProps/SeqProp")}
            page.locator("#addOpen").click()
            page.locator("#sequenceTitle").filter(has_text="new props").wait_for()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#closeWorkspace").click()
            # A wrong file is refused plainly.
            page.locator("#addSequenceFile").set_input_files(
                {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello"})
            status.filter(has_text=".loredit (S5/S6) or .lms").wait_for()
            assert page.locator("#addBuild").is_disabled()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
