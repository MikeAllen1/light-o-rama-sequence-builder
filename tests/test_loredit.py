from pathlib import Path

import pytest

from lor_sequence_builder.loredit import LoreditError, extract_display, inspect_loredit


def test_inspect_loredit_xml(tmp_path: Path):
    sample = tmp_path / "sample.loredit"
    sample.write_text(
        '<?xml version="1.0"?><Sequence><Props/><Effects><Effect/></Effects></Sequence>',
        encoding="utf-8",
    )

    result = inspect_loredit(sample)

    assert result["root_element"] == "Sequence"
    assert result["element_counts"]["Effect"] == 1
    assert result["top_level_elements"] == ["Props", "Effects"]


def test_inspect_s6_sequence_structure_without_private_metadata(tmp_path: Path):
    sample = tmp_path / "sample.loredit"
    sample.write_text(
        """<?xml version="1.0"?>
        <sequence saveFileVersion="15" AppVersion="6.6.0.12"
                  totalCentiseconds="1000" author="Private Name"
                  musicFilename="C:\\Users\\private\\song.mp3">
          <PreviewClass>
            <PropClass id="prop-1" Name="Tree" DeviceType="LOR"
                       ChannelGrid="Regular" TraditionalType="Traditional"/>
          </PreviewClass>
          <SequenceProps>
            <SeqProp id="prop-1" name="Tree">
              <channel row="0" col="0" color="0">
                <effect startCentisecond="10" endCentisecond="20"
                        intensity="100" settings="INTENSITY"/>
              </channel>
            </SeqProp>
          </SequenceProps>
          <TimingGrids>
            <TimingGridFree name="Beats">
              <timing centisecond="0"/>
              <timing centisecond="50"/>
            </TimingGridFree>
            <TimingGridFixed name="Fixed" spacing="5"/>
          </TimingGrids>
        </sequence>""",
        encoding="utf-8",
    )

    result = inspect_loredit(sample)

    assert result["format_metadata"] == {
        "saveFileVersion": "15",
        "AppVersion": "6.6.0.12",
        "totalCentiseconds": "1000",
    }
    assert result["sequence_prop_count"] == 1
    assert result["preview_prop_count"] == 1
    assert result["channel_count"] == 1
    assert result["effect_count"] == 1
    assert result["effect_settings"] == {"INTENSITY": 1}
    assert result["timing_grids"][0]["timing_count"] == 2
    assert result["props"][0]["has_preview_definition"] is True
    assert "author" not in result
    assert "musicFilename" not in result["format_metadata"]


def test_invalid_xml_is_rejected(tmp_path: Path):
    sample = tmp_path / "broken.loredit"
    sample.write_text("<Sequence>", encoding="utf-8")

    with pytest.raises(LoreditError):
        inspect_loredit(sample)



def test_extract_display_props_groups_and_unmapped_sequence_props(tmp_path: Path):
    sample = tmp_path / "display.loredit"
    sample.write_text(
        """<?xml version="1.0"?>
        <sequence author="Private Name">
          <PreviewClass>
            <Scene BackgroundFile="C:\\private\\background.jpg"/>
            <PropClass id="tree" Name="Tree" DeviceType="LOR"
                       ChannelGrid="Regular,01,2,2,0,Multi"
                       TraditionalType="Multicolor_string_1_ch"
                       TraditionalColors="Red,Green,Blue"
                       IndividualChannels="True" MaxChannels="16">
              <shape/>
            </PropClass>
            <PropGroup id="yard" Name="Yard" Arrangement="Preview">
              <member id="tree"/>
            </PropGroup>
          </PreviewClass>
          <SequenceProps>
            <SeqProp id="tree" name="Tree">
              <channel row="0" col="0" color="Red"/>
              <channel row="0" col="1" color="Green"/>
            </SeqProp>
            <SeqProp id="orphan" name="No Preview">
              <channel row="0" col="0" color="White"/>
            </SeqProp>
          </SequenceProps>
        </sequence>""",
        encoding="utf-8",
    )

    result = extract_display(sample)

    assert result["preview_prop_count"] == 1
    assert result["sequence_prop_count"] == 2
    assert result["props"][0]["name"] == "Tree"
    assert result["props"][0]["traditional_colors"] == ["Red", "Green", "Blue"]
    assert result["props"][0]["sequence_channel_count"] == 2
    assert result["props"][0]["has_sequence_data"] is True
    assert result["groups"][0]["members"] == ["tree"]
    assert result["unmapped_sequence_props"] == [
        {"id": "orphan", "name": "No Preview", "channel_count": 1}
    ]
    serialized = str(result)
    assert "background.jpg" not in serialized
    assert "Private Name" not in serialized
