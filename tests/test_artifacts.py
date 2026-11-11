from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder.artifacts import write_new_text_atomically


def test_atomic_text_publication_never_leaves_a_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "report.json"

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("lor_sequence_builder.artifacts.os.fsync", fail_fsync)
    with pytest.raises(OSError, match="synthetic disk failure"):
        write_new_text_atomically(destination, '{"ok": true}\n')

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_text_publication_refuses_to_overwrite_existing_files(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    destination.write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_new_text_atomically(destination, "replacement")

    assert destination.read_text(encoding="utf-8") == "keep me"
    assert list(tmp_path.iterdir()) == [destination]
