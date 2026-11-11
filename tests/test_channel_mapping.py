from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import MutableMapping
from typing import cast

import pytest

from lor_sequence_builder.channel_mapping import (
    ChannelAddress,
    channel_layout_problem,
    parse_channel_grid,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01,02,03", (ChannelAddress(0, "01", "02", "03"),)),
        (
            "01,02,03;01,02,04",
            (
                ChannelAddress(0, "01", "02", "03"),
                ChannelAddress(1, "01", "02", "04"),
            ),
        ),
        (" 01 , 02 , 03 ", (ChannelAddress(0, "01", "02", "03"),)),
    ],
)
def test_channel_grid_parser_preserves_order_and_normalizes_address_fields(
    raw: str, expected: tuple[ChannelAddress, ...]
) -> None:
    assert parse_channel_grid(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_channel_grid_parser_returns_no_assignments_for_missing_value(raw: str | None) -> None:
    assert parse_channel_grid(raw) == ()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("01,02,03;", "entry 1 is empty"),
        (";01,02,03", "entry 0 is empty"),
        ("01,02", "entry 0 lacks a complete"),
        ("01,,03", "entry 0 lacks a complete"),
        ("01,02, ", "entry 0 lacks a complete"),
    ],
)
def test_channel_grid_parser_rejects_malformed_positions_without_compacting(
    raw: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_channel_grid(raw)


def test_channel_layout_validation_is_shared_by_sequence_and_pulse_paths() -> None:
    prop = ET.Element(
        "PropClass",
        {
            "DeviceType": "LOR",
            "StringType": "Traditional",
            "TraditionalType": "Single Color",
            "ChannelGrid": "01,02,03;01,02,04",
        },
    )

    assert channel_layout_problem(prop) is None

    prop.set("ChannelGrid", "01,02,03;;01,02,05")
    assert "entry 1 is empty" in (channel_layout_problem(prop) or "")


def test_channel_layout_rejects_unsupported_hardware_before_mapping() -> None:
    prop = ET.Element(
        "PropClass",
        {
            "DeviceType": "DMX",
            "StringType": "Traditional",
            "TraditionalType": "Single Color",
            "ChannelGrid": "01,02,03",
        },
    )

    assert "DeviceType DMX" in (channel_layout_problem(prop) or "")


def test_raw_element_attributes_are_deeply_read_only() -> None:
    from lor_sequence_builder.lorprev import RawElement, SourceValue

    source = {"id": SourceValue("prop-1", "sample.lorprev", "/PreviewClass/PropClass[0]")}
    raw = RawElement(
        tag="PropClass",
        attributes=source,
        children=(),
        text=None,
        tail=None,
        locator="/PreviewClass/PropClass[0]",
    )

    source.clear()
    assert raw.attributes["id"].value == "prop-1"
    with pytest.raises(TypeError):
        cast(MutableMapping[str, SourceValue], raw.attributes)["other"] = SourceValue(
            "x", "sample.lorprev", "/"
        )
