"""Safe publication helpers for generated text artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_new_text_atomically(path: str | Path, content: str) -> Path:
    """Publish a complete new text file without exposing partial data or overwriting.

    The temporary file is created in the destination directory so the final
    hard-link operation is same-volume and atomic. Linking fails if the target
    already exists, preserving the caller's no-overwrite contract.
    """
    output = Path(path)
    temporary: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
            newline="\n",
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output
