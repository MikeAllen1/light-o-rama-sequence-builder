"""What the program is doing right now, so the page can show it.

Long steps (reading a song, finding its beats, splitting out the vocals, planning
and writing a show) call :func:`step` as they go. The workspace runs each request
under :func:`tracking` with a key the page chose, and the page asks
:func:`snapshot` for that key a few times a second while it waits, to show the
stage, a bar and the time so far. Outside :func:`tracking`, :func:`step` does
nothing, so the command line and tests are unaffected.
"""

from __future__ import annotations

import contextvars
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("progress", default=None)
_lock = threading.Lock()
_states: dict[str, dict[str, Any]] = {}
_KEEP_SECONDS = 120
_MAX_STATES = 64


def valid_key(key: str) -> bool:
    return bool(_KEY.fullmatch(key))


@contextmanager
def tracking(key: str | None, start: str = "Starting") -> Iterator[None]:
    """Report the steps of the work inside this block under ``key``."""
    if not key or not valid_key(key):
        yield
        return
    with _lock:
        _prune()
        _states[key] = {"step": start, "fraction": 0.0, "started": time.monotonic(),
                        "updated": time.monotonic(), "done": False, "slow": False}
    token = _current.set(key)
    try:
        yield
    finally:
        _current.reset(token)
        with _lock:
            if key in _states:
                _states[key].update(done=True, fraction=1.0, updated=time.monotonic())


def step(name: str, fraction: float | None = None, slow: bool = False) -> None:
    """Say what is happening now; ``fraction`` is how far through the whole job (0 to 1).

    ``slow`` marks a step that takes minutes (splitting out the vocals) so the page
    can say so."""
    key = _current.get()
    if key is None:
        return
    with _lock:
        state = _states.get(key)
        if state is None:
            return
        state["step"] = name
        state["slow"] = slow
        if fraction is not None:
            state["fraction"] = max(state["fraction"], min(1.0, max(0.0, fraction)))
        state["updated"] = time.monotonic()


def snapshot(key: str) -> dict[str, Any]:
    """The latest step for ``key``: step, fraction, seconds so far, done."""
    with _lock:
        state = _states.get(key)
        if state is None:
            return {"known": False}
        return {"known": True, "step": state["step"], "fraction": round(state["fraction"], 3),
                "seconds": round(time.monotonic() - state["started"], 1),
                "done": state["done"], "slow": state["slow"]}


def _prune() -> None:
    now = time.monotonic()
    for key in [k for k, s in _states.items()
                if s["done"] and now - s["updated"] > _KEEP_SECONDS]:
        del _states[key]
    while len(_states) >= _MAX_STATES:
        del _states[min(_states, key=lambda k: _states[k]["updated"])]
