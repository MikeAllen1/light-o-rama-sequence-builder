"""Is there a newer LOR Sequencer? Asks GitHub for the latest published release.

The check sends nothing about the user or their files: it is a plain request for the
project's public release list. It is skipped when ``LOR_NO_UPDATE_CHECK`` is set, and
the workspace lets people turn it off. Any network problem just means "no news".
Links are only passed on when they point at this project's own releases.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lor_sequence_builder import __version__

REPOSITORY = "MikeAllen1/light-o-rama-sequence-builder"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
_DOWNLOAD_PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"
_MAX_BYTES = 1024 * 1024
_CACHE_SECONDS = 6 * 3600
_cache: dict[str, Any] = {}
_lock = threading.Lock()

Fetch = Callable[[], dict[str, Any] | None]


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.2.0', 'v.0.2.0' or '0.2' -> (0, 2, 0); None for anything else (pre-releases
    included)."""
    match = re.fullmatch(r"v?\.?(\d+)\.(\d+)(?:\.(\d+))?", text.strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _fetch_latest() -> dict[str, Any] | None:
    """The latest release as GitHub describes it; None when there is none yet."""
    request = Request(LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                           "User-Agent": f"LOR-Sequencer/{__version__}"})
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read(_MAX_BYTES + 1)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if len(body) > _MAX_BYTES:
        raise ValueError("The release description is too large")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise TypeError("Unexpected release description")
    return data


def _installer_url(release: dict[str, Any]) -> str | None:
    for asset in release.get("assets") or []:
        url = asset.get("browser_download_url") if isinstance(asset, dict) else None
        if (isinstance(url, str) and url.startswith(_DOWNLOAD_PREFIX)
                and url.lower().endswith(".exe") and "/../" not in url):
            return url
    return None


def check_for_update(current: str = __version__, fetch: Fetch | None = None,
                     use_cache: bool = True) -> dict[str, Any]:
    """{"current", "latest", "newer", "page", "installer"}; "error" when it could not check."""
    result: dict[str, Any] = {"current": current, "latest": None, "newer": False,
                              "page": RELEASES_PAGE, "installer": None}
    if os.environ.get("LOR_NO_UPDATE_CHECK"):
        result["disabled"] = True
        return result
    with _lock:
        cached = _cache.get(current)
        if use_cache and cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
            return dict(cached[1])
        try:
            release = (fetch or _fetch_latest)()
        except Exception as error:  # noqa: BLE001 - offline or GitHub down: no news
            result["error"] = f"Could not check for updates ({type(error).__name__})"
            return result
        if release and not release.get("draft") and not release.get("prerelease"):
            tag = str(release.get("tag_name") or "")
            latest = parse_version(tag)
            mine = parse_version(current)
            if latest is not None:
                result["latest"] = tag.lstrip("v.")
                result["newer"] = mine is not None and latest > mine
                page = release.get("html_url")
                if isinstance(page, str) and page.startswith(RELEASES_PAGE + "/"):
                    result["page"] = page
                result["installer"] = _installer_url(release)
        _cache[current] = (time.monotonic(), dict(result))
    return result
