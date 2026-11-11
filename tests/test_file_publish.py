from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder.file_publish import publish_new_files, write_new_file


def test_write_new_file_creates_without_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "new.txt"
    write_new_file(output, lambda stream: stream.write(b"new"))
    assert output.read_bytes() == b"new"
    with pytest.raises(FileExistsError):
        write_new_file(output, lambda stream: stream.write(b"replace"))
    assert output.read_bytes() == b"new"


def test_write_new_file_removes_partial_output_after_writer_failure(tmp_path: Path) -> None:
    output = tmp_path / "partial.txt"

    def fail_after_write(stream: object) -> None:
        stream.write(b"partial")  # type: ignore[attr-defined]
        raise OSError("simulated write failure")

    with pytest.raises(OSError, match="simulated"):
        write_new_file(output, fail_after_write)
    assert not output.exists()


def test_publish_new_files_rolls_back_when_later_destination_exists(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first-source"
    second_source = tmp_path / "second-source"
    first_destination = tmp_path / "first-destination"
    second_destination = tmp_path / "second-destination"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    second_destination.write_bytes(b"preserve")

    with pytest.raises(FileExistsError):
        publish_new_files(
            [(first_source, first_destination), (second_source, second_destination)]
        )

    assert not first_destination.exists()
    assert second_destination.read_bytes() == b"preserve"
