"""A whole playlist at once: one show per song, saved together."""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import pytest

from lor_sequence_builder.cli import main
from lor_sequence_builder.loredit import read_loredit
from tests.display_builders import classic_yard
from tests.test_audio_analysis import _rhythmic_track
from tests.test_planner import _preview
from tests.test_show_builder import _json, _post, server  # noqa: F401


def _songs(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        _rhythmic_track(path, duration=20.0)
        paths.append(path)
    return paths


def test_the_workspace_builds_a_playlist(server: str, tmp_path: Path) -> None:  # noqa: F811
    status, started = _post(server + "/api/show/start?name=yard.lorprev",
                            _preview(tmp_path, classic_yard()).read_bytes(), "application/xml")
    token = started["token"]
    first, second = _songs(tmp_path / "songs", "Jingle.wav", "Silent.wav")
    results = []
    for song, name in ((first, "Jingle.wav"), (second, "Silent.wav"), (second, "Jingle.wav")):
        status, result = _post(f"{server}/api/show/batch?token={token}&name={name}&style=elegant",
                               song.read_bytes(), "application/octet-stream")
        assert status == 200, result
        results.append(result)
    assert all(r["ok"] for r in results)
    assert [r["show"] for r in results] == ["Jingle (generated).loredit",
                                            "Silent (generated).loredit",
                                            "Jingle (2) (generated).loredit"]
    status, saved = _json(f"{server}/api/show/batch-zip?token={token}", {})
    assert status == 200 and saved["count"] == 3
    archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(saved["zip"])))
    names = set(archive.namelist())
    assert "Silent (generated).report.html" in names and "Batch - read me.txt" in names
    sequence = tmp_path / "out.loredit"
    sequence.write_bytes(archive.read("Silent (generated).loredit"))
    assert read_loredit(sequence).root.attrib["musicFilename"] == "Silent.wav"
    status, _ = _json(f"{server}/api/show/batch-clear?token={token}", {})
    status, empty = _json(f"{server}/api/show/batch-zip?token={token}", {})
    assert status == 422 and "No batch shows" in empty["error"]


def test_the_cli_builds_a_folder_of_songs(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    preview = _preview(tmp_path, classic_yard())
    _songs(tmp_path / "songs", "A.wav", "B.wav")
    (tmp_path / "songs" / "notes.txt").write_text("not a song", encoding="utf-8")
    out = tmp_path / "shows"
    assert main(["generate-batch", "--preview", str(preview), "--songs", str(tmp_path / "songs"),
                 "--output", str(out), "--ignore-saved-requirements"]) == 0
    assert (out / "A.loredit").is_file() and (out / "B.loredit").is_file()
    assert "2 of 2 shows built" in capsys.readouterr().out
    assert main(["generate-batch", "--preview", str(preview), "--songs", str(tmp_path / "songs"),
                 "--output", str(out)]) == 2


def test_new_show_builds_and_saves_a_playlist(server: str, tmp_path: Path) -> None:  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    preview = _preview(tmp_path, classic_yard())
    songs = _songs(tmp_path / "songs", "One.wav", "Two.wav")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#welcomeNewShow").click()
            assert page.locator("#batchFiles").is_disabled()
            page.locator("#showDisplayFile").set_input_files(str(preview))
            page.locator("#displayStatus.good").wait_for(timeout=20000)
            page.locator("#batchFiles").set_input_files([str(s) for s in songs])
            page.locator("#batchStatus.good").wait_for(timeout=120000)
            assert "2 of 2 shows built" in page.locator("#batchStatus").inner_text()
            assert page.locator("#batchList li.good").count() == 2
            with page.expect_download() as saved:
                page.locator("#saveBatch").click()
            assert saved.value.suggested_filename.endswith("shows.zip")
        finally:
            browser.close()
