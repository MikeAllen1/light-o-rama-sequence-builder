from __future__ import annotations

from pathlib import Path

import pytest

import lor_sequence_builder.cli as cli_module
from lor_sequence_builder.classifier import ClassificationError
from lor_sequence_builder.rules import RuleProfileError


@pytest.mark.parametrize("error_type", [RuleProfileError, ClassificationError])
def test_cli_report_write_errors_are_actionable_and_leave_no_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[ValueError],
) -> None:
    destination = tmp_path / "report.json"

    def fail_write(path: str | Path, content: str) -> Path:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(cli_module, "write_new_text_atomically", fail_write)
    with pytest.raises(error_type, match="Cannot write report atomically"):
        cli_module._write_cli_json_report(destination, {"ok": True}, error_type)

    assert not destination.exists()
