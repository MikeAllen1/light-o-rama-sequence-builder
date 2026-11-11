"""Browser editing: select, move, trim, draw, delete, undo, edit, retime and export.

Uses a small invented sequence; nothing here comes from a real display.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.loredit import read_loredit
from lor_sequence_builder.ui_server import SequencerRequestHandler

playwright_api = pytest.importorskip("playwright.sync_api")

ROW = 22
PPS = 40  # pixels per second used by the test
BUSH_ROW = 7  # group, arch prop, four arch channels, bush prop, bush channel


def _effect(start: int, end: int, level: int) -> str:
    return (f'        <effect startCentisecond="{start}" endCentisecond="{end}" '
            f'intensity="{level}" settings="INTENSITY" />')


def sequence_text() -> str:
    arch = "\n".join(
        f'      <channel row="0" col="{col}" color="0">\n{_effect(0, 192, 50)}\n'
        f'{_effect(192, 400, 80)}\n      </channel>'
        for col in range(4)
    )
    lines = f"""<?xml version="1.0" encoding="utf-8"?>
<sequence saveFileVersion="15" totalCentiseconds="1000" musicTitle="Editing Test">
  <PreviewClass id="preview" name="Invented Yard">
    <PropClass id="p-arch" name="Arch" />
    <PropClass id="p-bush" name="Bush" />
    <PropGroup id="g-yard" Name="Yard">
      <member id="p-arch" />
      <member id="p-bush" />
    </PropGroup>
  </PreviewClass>
  <SequenceProps>
    <SeqProp id="p-arch" name="Arch">
{arch}
    </SeqProp>
    <SeqProp id="p-bush" name="Bush">
      <channel row="0" col="0" color="0">
{_effect(500, 600, 100)}
{_effect(700, 800, 100)}
      </channel>
    </SeqProp>
  </SequenceProps>
  <TimingGrids>
    <TimingGridFixed name="Half seconds" spacing="50" />
  </TimingGrids>
</sequence>
"""
    return lines.replace("\n", "\r\n")


def analysis_json() -> str:
    return json.dumps({
        "schema_version": "2.0",
        "audio": {"duration_seconds": 10.0},
        "analysis": {
            "method": "test", "provenance": "synthetic test fixture", "limitations": [],
            "tempo": {"bpm": 120, "confidence": 0.9, "method": "test"},
            "beats": [{"time": 2.0, "confidence": 0.9}],
            "downbeats": [{"time": 2.0, "confidence": 0.9}],
            "onsets": [], "energy": [], "phrase_boundaries": [],
            "section_candidates": [], "hard_stops": [],
        },
    })


@pytest.fixture
def workspace() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencerRequestHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(server.server_address[1]) + "/"
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def _channel_effects(path: Path) -> dict[str, list[list[tuple[int, int, str]]]]:
    root = read_loredit(path).root
    found: dict[str, list[list[tuple[int, int, str]]]] = {}
    for prop in root.findall("SequenceProps/SeqProp"):
        found[prop.attrib["name"]] = [
            [(int(e.attrib["startCentisecond"]), int(e.attrib["endCentisecond"]),
              e.attrib.get("intensity") or
              e.attrib.get("startIntensity", "") + ">" + e.attrib.get("endIntensity", ""))
             for e in channel.findall("effect")]
            for channel in prop.findall("channel")
        ]
    return found


def test_effects_can_be_edited_and_exported(workspace: str, tmp_path: Path) -> None:
    original = sequence_text().encode("utf-8")
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        try:
            page.goto(workspace, wait_until="networkidle")
            page.locator("#sequenceFile").set_input_files(
                {"name": "editing-test.loredit", "mimeType": "text/xml", "buffer": original})
            page.locator("#editor").wait_for(state="visible")
            page.locator("#zoomSlider").evaluate(
                f"""(element) => {{ element.value = "{PPS}";
                    element.dispatchEvent(new Event("input", {{ bubbles: true }})); }}""")
            box = page.locator("#tracksCanvas").bounding_box()
            assert box is not None

            def at(seconds: float, row: int) -> tuple[float, float]:
                return box["x"] + seconds * PPS, box["y"] + row * ROW + ROW / 2

            def drag(start: tuple[float, float], end: tuple[float, float],
                     alt: bool = False) -> None:
                page.mouse.move(*start)
                page.mouse.down()
                page.mouse.move((start[0] + end[0]) / 2, end[1], steps=3)
                if alt:
                    page.keyboard.down("Alt")
                page.mouse.move(*end, steps=3)
                page.mouse.up()
                if alt:
                    page.keyboard.up("Alt")

            def banner() -> str:
                return str(page.locator("#analysisMessage").inner_text())

            # An export with no edits gives back exactly the same bytes.
            with page.expect_download() as unchanged:
                page.locator("#exportButton").click()
            assert unchanged.value.suggested_filename == "editing-test (edited).loredit"
            assert Path(unchanged.value.path()).read_bytes() == original

            # Move: 5.00-6.00 dragged about +1.05 s snaps to the half-second grid.
            drag(at(5.5, BUSH_ROW), at(6.55, BUSH_ROW))
            assert "Moved 1 effect(s) +1.00 s" in banner()
            # Overlap is refused: 6.00-7.00 onto 7.00-8.00.
            drag(at(6.5, BUSH_ROW), at(7.5, BUSH_ROW))
            assert "Not changed" in banner() and "overlap" in banner()
            # Trim the end of 7.00-8.00 out to 8.50.
            drag(at(7.99, BUSH_ROW), at(8.48, BUSH_ROW))
            assert "Trimmed to 0:07.00 → 0:08.50" in banner()
            # Draw a new effect on the empty start of the row; Alt places it freely.
            drag(at(1.0, BUSH_ROW), at(2.37, BUSH_ROW), alt=True)
            assert "Added an effect 0:01.00 → 0:02.37" in banner()

            # Delete, undo, redo, undo.
            page.keyboard.press("Delete")
            assert "Deleted 1 effect(s)" in banner()
            page.keyboard.press("Control+z")
            assert "Undid: Deleted" in banner()
            page.keyboard.press("Control+y")
            assert "Redid: Deleted" in banner()
            page.keyboard.press("Control+z")
            assert page.locator("#effectStat").inner_text() == "11"

            # Edit the restored effect into a 0-100 fade.
            page.mouse.click(*at(1.5, BUSH_ROW))
            assert "Bush channel 1 · INTENSITY" in page.locator("#inspectorContent").inner_text()
            page.locator("#editFade").check()
            page.locator("#editStartIntensity").fill("0")
            page.locator("#editEndIntensity").fill("100")
            page.locator("#editApply").click()
            assert "Changed 1 effect(s)" in banner()
            # A bad value is refused without changing anything.
            page.locator("#editEndIntensity").fill("140")
            page.locator("#editApply").click()
            assert "whole numbers from 0 to 100" in banner()

            # Duplicate right after itself, then nudge the copy 10 cs later.
            page.keyboard.press("Control+d")
            assert "Duplicated 1 effect(s)" in banner()
            page.keyboard.press("Shift+ArrowRight")
            assert "Nudged 1 effect(s) +0.10 s" in banner()

            # Retime: the arch's lighting change at 1.92 s is 80 ms before the bar.
            page.locator("#analysisFile").set_input_files(
                {"name": "a.json", "mimeType": "application/json",
                 "buffer": analysis_json().encode("utf-8")})
            page.locator("#markerLabels").filter(has_text="Possible out-of-sync hits").wait_for()
            labels = page.locator("#markerLabels > div").all_inner_texts()
            lane = next(i for i, text in enumerate(labels) if text.startswith("Possible out"))
            markers = page.locator("#markersCanvas").bounding_box()
            assert markers is not None
            page.mouse.click(markers["x"] + 2.0 * PPS, markers["y"] + lane * ROW + ROW / 2)
            assert "80 ms early" in page.locator("#inspectorContent").inner_text()
            page.locator("#retimeButton").click()
            assert "Retimed 4 effect(s) from 0:01.92 to 0:02.00" in banner()
            assert "Unexported edits" in page.locator("#editStatus").inner_text()

            with page.expect_download() as edited:
                page.locator("#exportButton").click()
            saved = tmp_path / "edited.loredit"
            edited.value.save_as(saved)
            assert "Checked and saved" in banner()
        finally:
            browser.close()

    effects = _channel_effects(saved)
    assert effects["Bush"] == [[(100, 237, "0>100"), (247, 384, "0>100"), (600, 700, "100"),
                                (700, 850, "100")]]
    assert effects["Arch"] == [[(0, 200, "50"), (200, 400, "80")]] * 4
    text = saved.read_bytes()
    assert text.startswith(b'<?xml version="1.0" encoding="utf-8"?>\r\n')
    assert b"\n" not in text.replace(b"\r\n", b"")  # line endings kept
    assert b'settings="INTENSITY" />' in text


def test_export_check_refuses_overlaps_and_foreign_requests(workspace: str) -> None:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    def post(body: bytes, **headers: str) -> tuple[int, dict[str, Any]]:
        request = Request(workspace + "api/export", data=body, method="POST",
                          headers={"Content-Type": "application/xml", **headers})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            body_text = error.read()
            try:
                return error.code, json.loads(body_text)
            except ValueError:
                return error.code, {}

    good = sequence_text().encode("utf-8")
    assert post(good) == (200, {"ok": True, "channels": 5, "effects": 10})
    overlapping = good.replace(b'startCentisecond="700"', b'startCentisecond="550"')
    status, result = post(overlapping)
    assert status == 422 and "Bush channel 1: effects overlap at 550 cs" in result["error"]
    past_end = good.replace(b'endCentisecond="800"', b'endCentisecond="1500"')
    assert "out of range" in post(past_end)[1]["error"]
    # S6 itself sometimes saves an exact duplicate of an effect; that is not an overlap.
    duplicated = good.replace(b"</channel>\r\n    </SeqProp>\r\n  </SequenceProps>",
                              b'  <effect startCentisecond="700" endCentisecond="800" '
                              b'intensity="100" settings="INTENSITY" />\r\n      </channel>'
                              b"\r\n    </SeqProp>\r\n  </SequenceProps>")
    assert duplicated != good
    assert post(duplicated)[0] == 200
    assert post(b"<not-a-sequence/>")[0] == 422
    assert post(good, Origin="http://attacker.example")[0] == 403
    assert post(good, **{"Content-Type": "text/plain"})[0] == 415
