"""Right-clicking an S6 preview can start a show with it, without taking .lorprev from S6."""

from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder import desktop, ui_server
from lor_sequence_builder.ui_server import offer_preview
from tests.display_builders import classic_yard
from tests.test_planner import _preview
from tests.test_show_builder import _json, server  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[1]


def test_only_real_previews_are_offered(tmp_path: Path) -> None:
    for name, content, words in (("yard.txt", b"<x/>", "not an S5/S6 preview"),
                                 ("gone.lorprev", None, "not an S5/S6 preview"),
                                 ("bad.lorprev", b"\xff\xfe\x00bad", "not a readable")):
        path = tmp_path / name
        if content is not None:
            path.write_bytes(content)
        with pytest.raises(ValueError, match=words):
            offer_preview(path)
    assert offer_preview(_preview(tmp_path, classic_yard())) == "?start=preview"


def test_the_preview_is_handed_over_once(server: str, tmp_path: Path) -> None:  # noqa: F811
    offer_preview(_preview(tmp_path, classic_yard()))
    status, first = _json(server + "/api/startup", {})
    assert status == 200 and first["preview"]["name"].endswith(".lorprev")
    assert "<PreviewClass" in first["preview"]["text"]
    status, second = _json(server + "/api/startup", {})
    assert second["preview"] is None


def test_new_show_opens_with_the_preview(server: str, tmp_path: Path) -> None:  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    offer_preview(_preview(tmp_path, classic_yard()))
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(server + "/?start=preview", wait_until="networkidle")
            page.locator("#displayStatus.good").wait_for(timeout=20000)
            assert page.locator("#newShow").is_visible()
            assert "arches" in page.locator("#displayStatus").inner_text()
            assert "start=preview" not in page.url  # a reload does not repeat it
        finally:
            browser.close()


def test_the_desktop_app_takes_a_preview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    opened: list[str] = []
    told: list[str] = []
    def window(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(desktop, "_open_window", window)
    monkeypatch.setattr(desktop, "_tell", told.append)
    monkeypatch.setattr(desktop, "use_bundled_ffmpeg", lambda: None)
    assert desktop.main(["--preview", str(_preview(tmp_path, classic_yard()))]) == 0
    assert opened[-1].endswith("/?start=preview") and not told
    assert desktop.main(["--preview", str(tmp_path / "missing.lorprev")]) == 0
    assert opened[-1].endswith("/") and "could not open that preview" in told[0]
    ui_server._take_startup()


def test_the_installer_adds_a_menu_item_but_leaves_previews_to_s6() -> None:
    script = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert r"SystemFileAssociations\.lorprev\shell\LORSequencerBuildShow\command" in script
    assert '--preview ""%1""' in script
    assert r".lorprev\OpenWithProgids" in script
    registry = [line for line in script.splitlines() if line.startswith("Root: HKCU")]
    # Nothing sets the default program for .lorprev itself.
    assert not any(r'Subkey: "Software\Classes\.lorprev"; ' in line for line in registry)
    assert all("Tasks: previewmenu" in line for line in registry)


