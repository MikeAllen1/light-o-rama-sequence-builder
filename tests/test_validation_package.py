from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_phase3_validation import build_package


def test_validation_package_never_overwrites_existing_output(tmp_path: Path) -> None:
    destination = tmp_path / "Phase3-S6-Validation.zip"
    destination.write_bytes(b"preserve this existing file")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        build_package(destination)

    assert destination.read_bytes() == b"preserve this existing file"
