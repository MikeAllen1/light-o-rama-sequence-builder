from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lor_sequence_builder.choreography import Choreography, Effect, choreography_json
from lor_sequence_builder.cli import main
from lor_sequence_builder.requirements_intake import (
    API_KEY_VARIABLE,
    API_URL,
    MODEL_VARIABLE,
    ApiTranslator,
    IntakeError,
    Translation,
    gather_requirements,
    guided_requirements,
    load_saved_requirements,
    saved_requirements_path,
    translator_from_environment,
)
from lor_sequence_builder.rules import display_from_preview, load_rule_set
from lor_sequence_builder.rules.engine import Display, DisplayProp
from tests.display_builders import DisplayBuilder, classic_yard, roofline_house


class Script:
    """Answers prompts by the first matching phrase; records everything said."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers = list((answers or {}).items())
        self.prompts: list[str] = []
        self.said: list[str] = []

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        for index, (phrase, answer) in enumerate(self.answers):
            if phrase in prompt:
                del self.answers[index]
                return answer
        return ""

    def say(self, text: str) -> None:
        self.said.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.said)


class FakeTranslator:
    def __init__(self, translation: Translation) -> None:
        self.translation = translation
        self.calls: list[str] = []

    def translate(self, text: str, display: Display) -> Translation:
        self.calls.append(text)
        return self.translation


def _preview(tmp_path: Path, display: DisplayBuilder, name: str = "yard.lorprev") -> Path:
    path = tmp_path / name
    ET.ElementTree(display.element()).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _display(builder: DisplayBuilder) -> Display:
    return display_from_preview(builder.element())


def test_guided_questions_only_ask_about_props_the_display_has() -> None:
    script = Script({
        "group 'Arches'": "l",
        "singing face can show": "red, green",
        "mega tree, 1 to 100": "80",
        "never light up": "Santa, Garden Gnome",
    })
    found = guided_requirements(_display(classic_yard()), script.ask, script.say)
    assert found == [
        {"type": "move_direction", "props": {"group": "Arches"}, "movement": "chase",
         "direction": "left_to_right"},
        {"type": "colors_only", "props": {"role": "singing_face"}, "colors": ["Green", "Red"]},
        {"type": "max_intensity", "props": {"role": "mega_tree"}, "max": 80},
        {"type": "never_use", "props": {"names": ["Santa"]}},
    ]
    asked = "\n".join(script.prompts)
    # The star is driven by the mega tree, the arches have one color, and the
    # mini trees share one circuit for all colors, so none of those is asked.
    assert "lit for the whole song" not in asked
    assert "arches can show" not in asked and "mini trees can show" not in asked
    assert "chases across the mini trees" in asked
    assert "Not in this preview, skipped: Garden Gnome" in script.text

    house = Script()
    guided_requirements(_display(roofline_house()), house.ask, house.say)
    house_asked = "\n".join(house.prompts)
    assert "mega tree" not in house_asked and "Arches" not in house_asked


def test_plain_english_is_translated_validated_and_confirmed(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    translator = FakeTranslator(Translation(
        requirements=[
            {"type": "colors_only", "props": {"role": "singing_face"}, "colors": ["Red"],
             "note": "Santa only shows red"},
            {"type": "max_intensity", "props": {"names": ["Mega Tree"]}, "max": 70},
            {"type": "keep_on", "props": {"role": "wizard"}},
            {"type": "never_use", "props": {"names": ["Garden Gnome"]}},
        ],
        not_supported=["Make it look festive"],
    ))
    script = Script({"Describe them": "santa red only, mega tree 70%, festive",
                     "Continue?": "", "Use these?": "y"})
    result = gather_requirements(preview, _display(classic_yard()), script.ask, script.say,
                                 translator)
    assert translator.calls == ["santa red only, mega tree 70%, festive"]
    assert [r.type for r in result] == ["colors_only", "max_intensity"]
    text = script.text
    assert "sends what you typed, plus your prop names" in text
    assert "1. Props identified as singing_face show only Red: Santa only shows red" in text
    assert "2. Props named 'Mega Tree' stay at or below 70%" in text
    assert "Not something the builder can enforce yet:\n  - Make it look festive" in text
    assert "role 'wizard' is not a known role" in text
    assert "Props named 'Garden Gnome' are never used: skipped, no prop" in text

    saved = saved_requirements_path(preview)
    assert saved.name == "yard.requirements.yaml"
    assert [r.type for r in load_saved_requirements(preview)] == ["colors_only",
                                                                  "max_intensity"]
    # The saved file is a normal profile.
    assert load_rule_set((saved,)).sources == ("default.yaml", "yard.requirements.yaml")


def test_fresh_requirements_bypass_malformed_saved_sidecar(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    sidecar = saved_requirements_path(preview)
    sidecar.write_text("schema_version: rules-1.0\\nrequirements: [broken\\n", encoding="utf-8")
    translator = FakeTranslator(Translation([
        {"type": "never_use", "props": {"names": ["Santa"]}},
    ]))
    script = Script({"Describe them": "never use Santa", "Use these?": "y"})
    result = gather_requirements(
        preview, _display(classic_yard()), script.ask, script.say,
        translator, fresh=True,
    )
    assert [item.type for item in result] == ["never_use"]
    assert [item.type for item in load_saved_requirements(preview)] == ["never_use"]



def test_fresh_intake_with_no_new_requirements_clears_old_saved_sidecar(
    tmp_path: Path,
) -> None:
    preview = _preview(tmp_path, classic_yard())
    sidecar = saved_requirements_path(preview)
    sidecar.write_text(
        "schema_version: rules-1.0\\nrequirements:\\n"
        "  - type: never_use\\n    props: {names: [Santa]}\\n",
        encoding="utf-8",
    )
    script = Script({
        "Describe them": "",
        "Answer a few quick questions": "n",
    })

    result = gather_requirements(
        preview, _display(classic_yard()), script.ask, script.say, None, fresh=True
    )

    assert result == ()
    assert not sidecar.exists()


def test_nothing_is_saved_without_confirmation(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    translator = FakeTranslator(Translation(
        [{"type": "never_use", "props": {"role": "mega_tree"}}]))
    script = Script({"Describe them": "no mega tree", "Use these?": "n"})
    assert gather_requirements(preview, _display(classic_yard()), script.ask, script.say,
                               translator) == ()
    assert not saved_requirements_path(preview).exists()
    assert "Nothing was saved" in script.text


def test_without_an_api_key_or_consent_it_asks_questions_instead(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    script = Script({"Describe them": "arches left to right", "group 'Arches'": "l",
                     "Use these?": "y"})
    result = gather_requirements(preview, _display(classic_yard()), script.ask, script.say,
                                 translator=None)
    assert "need an API key (ANTHROPIC_API_KEY)" in script.text
    assert [r.params["direction"] for r in result] == ["left_to_right"]

    translator = FakeTranslator(Translation([]))
    declined = Script({"Describe them": "anything", "Continue?": "n"})
    gather_requirements(_preview(tmp_path, classic_yard(), "b.lorprev"),
                        _display(classic_yard()), declined.ask, declined.say, translator)
    assert translator.calls == []
    assert any("chases across" in p for p in declined.prompts)


def test_skipping_entirely_changes_nothing(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    script = Script()
    assert gather_requirements(preview, _display(classic_yard()), script.ask, script.say,
                               None) == ()
    assert not saved_requirements_path(preview).exists()
    assert len(script.prompts) == 2


def test_saved_requirements_are_remembered_extended_or_cleared(tmp_path: Path) -> None:
    preview = _preview(tmp_path, classic_yard())
    display = _display(classic_yard())
    first = FakeTranslator(Translation([{"type": "never_use", "props": {"names": ["Santa"]}}]))
    gather_requirements(preview, display, *_io(Script({"Describe": "x", "Use": "y"})), first)

    keep = Script()
    kept = gather_requirements(preview, display, keep.ask, keep.say, None)
    assert [r.requirement_id for r in kept] == ["never_use"]
    assert "Saved requirements for this display (1):" in keep.text
    assert len(keep.prompts) == 1

    more = FakeTranslator(Translation([{"type": "never_use", "props": {"role": "mega_tree"}}]))
    added = gather_requirements(
        preview, display, *_io(Script({"[K]eep": "a", "Describe": "x", "Use": "y"})), more)
    assert [r.requirement_id for r in added] == ["never_use", "never_use-2"]
    assert len(load_saved_requirements(preview)) == 2

    clear = Script({"[K]eep": "f", "Remove your saved": "y"})
    assert gather_requirements(preview, display, clear.ask, clear.say, None) == ()
    assert not saved_requirements_path(preview).exists()


def _io(script: Script) -> tuple[Callable[[str], str], Callable[[str], None]]:
    return script.ask, script.say


def test_api_translator_sends_the_display_and_reads_the_tool_answer() -> None:
    sent: dict[str, Any] = {}

    def transport(url: str, headers: dict[str, str], body: bytes) -> bytes:
        sent.update(url=url, headers=headers, body=json.loads(body))
        return json.dumps({"content": [
            {"type": "text", "text": "ignored"},
            {"type": "tool_use", "name": "record_requirements", "input": {
                "requirements": [{"type": "keep_on", "props": {"role": "arch"}}],
                "not_supported": ["sparkle more"],
            }},
        ]}).encode()

    translation = ApiTranslator("key-123", "some-model", transport).translate(
        "arches always on", _display(classic_yard()))
    assert translation == Translation([{"type": "keep_on", "props": {"role": "arch"}}],
                                      ["sparkle more"])
    assert sent["url"] == API_URL
    assert sent["headers"]["x-api-key"] == "key-123"
    body = sent["body"]
    assert body["model"] == "some-model"
    assert body["tool_choice"] == {"type": "tool", "name": "record_requirements"}
    assert body["messages"] == [{"role": "user", "content": "arches always on"}]
    assert '"name": "Mega Tree"' in body["system"]
    assert '"driven_by": "Mega Tree"' in body["system"]

    def garbage(url: str, headers: dict[str, str], body: bytes) -> bytes:
        return b'{"content": [{"type": "text", "text": "no tool"}]}'

    with pytest.raises(IntakeError, match="cannot read"):
        ApiTranslator("k", transport=garbage).translate("x", _display(classic_yard()))



def test_translator_rejects_mixed_valid_and_malformed_requirement_entries() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes) -> bytes:
        return json.dumps({"content": [{
            "type": "tool_use",
            "name": "record_requirements",
            "input": {
                "requirements": [
                    {"type": "keep_on", "props": {"role": "arch"}},
                    "malformed entry",
                ],
                "not_supported": [],
            },
        }]}).encode()

    with pytest.raises(IntakeError, match="malformed requirement"):
        ApiTranslator("key", transport=transport).translate(
            "arches stay on", _display(classic_yard())
        )


def test_translator_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    assert translator_from_environment() is None
    monkeypatch.setenv(API_KEY_VARIABLE, " secret ")
    monkeypatch.setenv(MODEL_VARIABLE, "custom-model")
    translator = translator_from_environment()
    assert isinstance(translator, ApiTranslator)
    assert (translator.api_key, translator.model) == ("secret", "custom-model")


def test_builds_use_saved_requirements_automatically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    display = classic_yard()
    preview = _preview(tmp_path, display)
    ids = {p.get("Name", ""): p.get("id", "") for p in display.element().findall("PropClass")}
    timeline = tmp_path / "plan.json"
    timeline.write_text(choreography_json(Choreography(
        duration_centiseconds=1000, effects=(Effect(ids["Santa"], 0, 0, 100),))),
        encoding="utf-8")

    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    answers = iter(["", "y", "", "", "", "", "Santa", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert main(["requirements", str(preview)]) == 0
    assert "Saved to yard.requirements.yaml" in capsys.readouterr().out

    assert main(["check-timeline", str(preview), str(timeline)]) == 1
    out = capsys.readouterr().out
    assert "Using your saved requirements: yard.requirements.yaml" in out
    assert "Santa channel 1 at 0:00.00: Should never be used" in out
    assert main(["check-timeline", str(preview), str(timeline),
                 "--ignore-saved-requirements"]) == 0
    capsys.readouterr()

    build = ["build-from-timeline", "--preview", str(preview), "--timeline", str(timeline),
             "--music-filename", "song.mp3", "--output", str(tmp_path / "s.loredit"),
             "--report", str(tmp_path / "s.json")]
    assert main(build) == 1
    assert not (tmp_path / "s.loredit").exists()
    assert main(["list-rules", "--preview", str(preview)]) == 0
    assert "never_use [error] never_use: props named 'Santa'" in capsys.readouterr().out

    # --ask-requirements runs the same conversation before building: start fresh, remove.
    answers = iter(["f", "", "", "y"])
    (tmp_path / "s.json").unlink()
    assert main([*build, "--ask-requirements"]) == 0
    assert not saved_requirements_path(preview).exists()
    assert (tmp_path / "s.loredit").exists()


def test_guided_chase_direction_is_asked_for_each_group_in_a_role() -> None:
    props = {}
    groups = {"Arches": (), "Porch Arches": ()}
    for group in groups:
        members = []
        for index in range(3):
            prop_id = f"{group}-{index}"
            props[prop_id] = DisplayProp(
                prop_id=prop_id, name=prop_id, role="arch", channel_count=1,
                color_kind="multi_color", channel_colors=("Red",), linked_to=None,
                layout_problem=None, center=None, direction="horizontal",
                group=group, position_in_row=index + 1, row_size=3,
            )
            members.append(prop_id)
        groups[group] = tuple(members)
    display = Display(props=props, groups=groups)
    script = Script({
        "group 'Arches'": "l",
        "group 'Porch Arches'": "r",
    })

    found = guided_requirements(display, script.ask, script.say)

    assert found == [
        {"type": "move_direction", "props": {"group": "Arches"},
         "movement": "chase", "direction": "left_to_right"},
        {"type": "move_direction", "props": {"group": "Porch Arches"},
         "movement": "chase", "direction": "right_to_left"},
    ]
    assert any("group 'Arches'" in prompt for prompt in script.prompts)
    assert any("group 'Porch Arches'" in prompt for prompt in script.prompts)
