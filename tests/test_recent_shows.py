"""Shows made recently are kept on this computer to open or save again."""

from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder import recent_shows
from lor_sequence_builder.recent_shows import RecentShowError, keep, listing, load, remove
from tests.display_builders import classic_yard
from tests.test_audio_analysis import _rhythmic_track
from tests.test_planner import _preview
from tests.test_show_builder import _json, _post, server  # noqa: F401 - fixture


def _show(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_text("<sequence/>", encoding="utf-8")
    return path


def test_kept_shows_are_listed_newest_first_and_capped(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recent_shows, "MAX_KEPT", 3)
    store = tmp_path / "store"
    ids = [keep(_show(tmp_path, f"s{n}.loredit"), None, None, file_name=f"Song {n}.loredit",
                display="Yard", song=f"Song {n}.mp3", style="classic", rules_ok=True,
                folder=store) for n in range(5)]
    shown = listing(store)
    assert [s["file_name"] for s in shown] == ["Song 4.loredit", "Song 3.loredit",
                                               "Song 2.loredit"]
    assert not shown[0]["has_report"]
    assert load(ids[-1], store)["sequence"] == "<sequence/>"
    remove(ids[-1], store)
    assert len(listing(store)) == 2


@pytest.mark.parametrize("bad", ["../../etc", "20260101-000000-000000-zzzz", "", "x" * 50])
def test_only_real_ids_are_opened(tmp_path: Path, bad: str) -> None:
    with pytest.raises(RecentShowError):
        load(bad, tmp_path)
    with pytest.raises(RecentShowError):
        remove(bad, tmp_path)


def test_new_show_keeps_each_show_it_builds(server: str, tmp_path: Path) -> None:  # noqa: F811
    status, started = _post(server + "/api/show/start?name=yard.lorprev",
                            _preview(tmp_path, classic_yard()).read_bytes(), "application/xml")
    token = started["token"]
    song = tmp_path / "Jingle.wav"
    _rhythmic_track(song, duration=20.0)
    _post(f"{server}/api/show/audio?token={token}&name=Jingle.wav", song.read_bytes(),
          "application/octet-stream")
    status, built = _json(f"{server}/api/show/generate?token={token}", {"style": "elegant"})
    assert status == 200 and built["recent_id"]
    status, found = _json(server + "/api/recent", {})
    assert [s["id"] for s in found["shows"]] == [built["recent_id"]]
    entry = found["shows"][0]
    assert entry["song"] == "Jingle.wav" and entry["style"] == "elegant" and entry["has_report"]
    status, opened = _json(server + "/api/recent/open", {"id": built["recent_id"]})
    assert opened["sequence"] == built["sequence"] and opened["summary"]
    status, missing = _json(server + "/api/recent/open", {"id": "../x"})
    assert status == 404 and "not there" in missing["error"]
    status, cleared = _json(server + "/api/recent/clear", {})
    assert cleared["removed"] == 1


def test_the_start_page_lists_and_opens_recent_shows(server: str, tmp_path: Path) -> None:  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    built = tmp_path / "built"
    built.mkdir()
    from lor_sequence_builder.demo import build_demo

    show = build_demo(built / "demo")
    keep(show.sequence_path, show.summary_path, show.picture_path,
         file_name="Demo Song (generated).loredit", display="Demo Yard", song="Demo Song.wav",
         style="classic", rules_ok=True)
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#recentShows").wait_for(state="visible", timeout=10000)
            row = page.locator("#recentList li")
            assert row.count() == 1 and "Demo Song" in row.inner_text()
            assert "Demo Yard · classic" in row.inner_text()
            with page.expect_download() as saved:
                page.get_by_role("button", name="Save: Demo Song").click()
            assert saved.value.suggested_filename == "Demo Song (generated).loredit"
            page.get_by_role("button", name="Open: Demo Song").click()
            page.locator("#yardPanel").wait_for(state="visible", timeout=10000)
            assert "choose Open audio and pick Demo Song.wav" in page.locator(
                "#analysisBanner").inner_text()
        finally:
            browser.close()
