from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder.artifacts import (
    copy_new_file_atomically,
    write_new_bytes_atomically,
    write_new_text_atomically,
)


def test_atomic_text_writer_publishes_complete_new_file(tmp_path: Path) -> None:
    target = tmp_path / "result.txt"
    assert write_new_text_atomically(target, "complete\n") == target
    assert target.read_text(encoding="utf-8") == "complete\n"
    with pytest.raises(FileExistsError):
        write_new_text_atomically(target, "replacement\n")
    assert target.read_text(encoding="utf-8") == "complete\n"
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_binary_writer_publishes_complete_new_file(tmp_path: Path) -> None:
    target = tmp_path / "result.bin"
    assert write_new_bytes_atomically(target, b"\x00\x01payload") == target
    assert target.read_bytes() == b"\x00\x01payload"
    with pytest.raises(FileExistsError):
        write_new_bytes_atomically(target, b"replacement")
    assert target.read_bytes() == b"\x00\x01payload"
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_file_copy_does_not_load_source_into_memory(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "copy.bin"
    source.write_bytes(b"\x00payload" * 1000)
    assert copy_new_file_atomically(source, target) == target
    assert target.read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        copy_new_file_atomically(source, target)
    assert not list(tmp_path.glob(".*.tmp"))
