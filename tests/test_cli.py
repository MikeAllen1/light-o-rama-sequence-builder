from __future__ import annotations

from pathlib import Path

import pytest

from lor_sequence_builder.cli import main


def test_cli_without_arguments_displays_available_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = " ".join(capsys.readouterr().out.lower().split())
    assert "inspect" in output
    assert "inspect-preview" in output
    assert "roundtrip" in output


def test_cli_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()



def test_inspect_preview_reports_lor_controller_addresses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preview = tmp_path / "controller-layout.lorprev"
    preview.write_text(
        '<PreviewClass Revision="1">'
        '<PropClass id="a" DeviceType="LOR" ChannelGrid="Regular,01,01,01,0,White" />'
        '<PropClass id="b" DeviceType="LOR" ChannelGrid="Regular,01,02,01,0,White" />'
        '<PropClass id="c" DeviceType="LOR" ChannelGrid="Aux A,02,01,01,0,White" />'
        '<PropClass id="d" DeviceType="DMX" ChannelGrid="12,301" />'
        '</PreviewClass>',
        encoding="utf-8",
    )

    assert main(["inspect-preview", str(preview)]) == 0
    output = capsys.readouterr().out
    assert "LOR controller addresses: 2" in output
    assert "  Regular / 01" in output
    assert "  Aux A / 02" in output
    assert "DMX universes: 1" in output
    assert "  12" in output
