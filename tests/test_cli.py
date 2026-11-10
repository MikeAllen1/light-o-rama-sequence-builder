from __future__ import annotations

import pytest

from lor_sequence_builder.cli import main


def test_cli_without_arguments_displays_available_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = " ".join(capsys.readouterr().out.lower().split())
    assert "inspect" in output
    assert "roundtrip" in output


def test_cli_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()
