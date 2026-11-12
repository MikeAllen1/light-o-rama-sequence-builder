"""The update check: compares versions, trusts only this project's links, never fails loudly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder import update_check
from lor_sequence_builder.update_check import RELEASES_PAGE, check_for_update, parse_version
from tests.test_show_builder import _json, server  # noqa: F401 - fixture

INSTALLER = ("https://github.com/MikeAllen1/light-o-rama-sequence-builder/releases/download/"
             "v0.2.0/LOR-Sequencer-Setup-0.2.0.exe")


def _release(tag: str = "v0.2.0", **extra: Any) -> dict[str, Any]:
    return {"tag_name": tag, "html_url": f"{RELEASES_PAGE}/tag/{tag}",
            "assets": [{"browser_download_url": INSTALLER}], **extra}


@pytest.fixture(autouse=True)
def _checking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOR_NO_UPDATE_CHECK", raising=False)


def test_versions_parse_and_compare() -> None:
    assert parse_version("v0.2.0") == (0, 2, 0)
    assert parse_version("1.10") == (1, 10, 0)
    assert parse_version("v1.0.0-beta") is None
    assert parse_version("v0.10.0") > parse_version("v0.9.9")  # type: ignore[operator]


def test_a_newer_release_is_reported_with_its_installer() -> None:
    result = check_for_update("0.1.0", fetch=_release, use_cache=False)
    assert result["newer"] and result["latest"] == "0.2.0"
    assert result["installer"] == INSTALLER
    assert result["page"] == f"{RELEASES_PAGE}/tag/v0.2.0"


@pytest.mark.parametrize("tag", ["v0.1.0", "v0.0.9"])
def test_the_same_or_an_older_release_is_not_news(tag: str) -> None:
    assert not check_for_update("0.1.0", fetch=lambda: _release(tag), use_cache=False)["newer"]


def test_links_elsewhere_are_never_passed_on() -> None:
    def elsewhere() -> dict[str, Any]:
        return _release(html_url="https://example.com/fake",
                        assets=[{"browser_download_url": "https://example.com/setup.exe"}])

    result = check_for_update("0.1.0", fetch=elsewhere, use_cache=False)
    assert result["newer"]
    assert result["page"] == RELEASES_PAGE and result["installer"] is None


def test_pre_releases_drafts_and_no_releases_are_not_news() -> None:
    releases: list[dict[str, Any] | None] = [_release(prerelease=True), _release(draft=True), None]
    for release in releases:
        def answer(found: dict[str, Any] | None = release) -> dict[str, Any] | None:
            return found

        result = check_for_update("0.1.0", fetch=answer, use_cache=False)
        assert not result["newer"] and result["latest"] is None


def test_being_offline_is_quiet() -> None:
    def offline() -> dict[str, Any]:
        raise OSError("no network")

    result = check_for_update("0.1.0", fetch=offline, use_cache=False)
    assert not result["newer"] and "Could not check" in result["error"]


def test_it_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOR_NO_UPDATE_CHECK", "1")

    def never() -> dict[str, Any]:
        raise AssertionError("must not ask GitHub")

    assert check_for_update("0.1.0", fetch=never)["disabled"]


def test_the_answer_is_remembered_for_a_while() -> None:
    calls: list[int] = []

    def counted() -> dict[str, Any]:
        calls.append(1)
        return _release()

    update_check._cache.clear()
    check_for_update("9.9.1", fetch=counted)
    check_for_update("9.9.1", fetch=counted)
    assert len(calls) == 1


def test_the_workspace_shows_a_newer_release(server: str, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                                             tmp_path: Path) -> None:
    from playwright import sync_api

    monkeypatch.setattr(update_check, "_fetch_latest", _release)
    update_check._cache.clear()
    status, result = _json(server + "/api/update", {})
    assert status == 200 and result["newer"] and result["installer"] == INSTALLER
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(server + "/", wait_until="networkidle")
            page.locator("#updateBar").wait_for(state="visible")
            assert "0.2.0 is out" in page.locator("#updateText").inner_text()
            assert page.locator("#updateLink").get_attribute("href") == INSTALLER
            page.locator("#updateLater").click()
            assert page.locator("#updateBar").is_hidden()
            page.reload(wait_until="networkidle")
            assert page.locator("#updateBar").is_hidden()  # "Later" skips this version
            page.locator("#checkUpdates").click()  # a manual check shows it again
            page.locator("#updateBar").wait_for(state="visible")
        finally:
            browser.close()
    update_check._cache.clear()
