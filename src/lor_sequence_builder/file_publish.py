"""Portable create-only file publication helpers."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Sequence
import contextlib
from pathlib import Path
from typing import BinaryIO


def write_new_file(path: Path, writer: Callable[[BinaryIO], None]) -> Path:
    """Create a new file exclusively, fsync it, and remove partial output on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def publish_new_files(files: Sequence[tuple[Path, Path]]) -> None:
    """Copy staged files to new destinations and roll back earlier copies on failure."""
    published: list[Path] = []
    try:
        for source, destination in files:
            def copy_to(stream: BinaryIO, source_path: Path = source) -> None:
                with source_path.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, stream)

            write_new_file(destination, copy_to)
            published.append(destination)
    except BaseException:
        for destination in reversed(published):
            with contextlib.suppress(OSError):
                destination.unlink(missing_ok=True)
        raise
