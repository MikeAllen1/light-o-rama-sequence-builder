"""Load, validate, and layer rule profiles.

The built-in profile (``default.yaml``) is always loaded first. Each user
profile layers on top, in the order given:

- ``rules``: override a built-in rule by id. Only the keys given change
  (``severity`` and that rule's own tunables); everything else keeps the value
  from the layer below. Rules that guard file integrity are locked and cannot
  be relaxed or turned off.
- ``requirements``: display-specific asks ("keep the star on", "arches stay
  white"). They are added to the requirements of earlier layers; an id that is
  already in use is an error rather than a silent replacement.

Unknown keys, unknown rule ids, wrong types, and out-of-range values all fail
with a message naming the file and the key, never silently ignored.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from lor_sequence_builder.choreography import MOVEMENT_DIRECTIONS, MOVEMENT_KINDS
from lor_sequence_builder.classifier import ROLES

PROFILE_SCHEMA_VERSION = "rules-1.0"
MAX_PROFILE_BYTES = 1024 * 1024
SEVERITIES = ("error", "warning", "off")


class RuleProfileError(ValueError):
    """Raised when a rule profile is invalid or cannot be layered."""


@dataclass(frozen=True, slots=True)
class _Param:
    kind: type
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class RuleSpec:
    rule_id: str
    title: str
    locked: bool
    params: dict[str, _Param]


_NAMES = _Param(list)
RULE_SPECS: dict[str, RuleSpec] = {
    spec.rule_id: spec
    for spec in (
        RuleSpec("effects_well_formed", "Effects are well formed and inside the song", True, {}),
        RuleSpec("known_props_and_channels", "Effects use real, sequenceable channels", True, {}),
        RuleSpec("no_overlapping_effects", "No overlapping effects on one channel", True, {}),
        RuleSpec("movements_complete", "Movements reach every prop in order", False, {}),
        RuleSpec("chases_follow_layout", "Chases and fills follow the row order", False, {}),
        RuleSpec("falls_go_down", "Falling effects run top to bottom", False, {}),
        RuleSpec(
            "face_outline_with_mouth",
            "A face outline is on whenever a mouth is on",
            False,
            {"outline_names": _NAMES, "mouth_names": _NAMES},
        ),
        RuleSpec(
            "mouths_only_during_vocals",
            "Mouths move only while someone is singing",
            False,
            {"mouth_names": _NAMES},
        ),
        RuleSpec(
            "single_color_only_where_possible",
            "A specific color is asked only of props that can show it alone",
            False,
            {},
        ),
        RuleSpec("motion_stops_at_hard_stops", "Motion stops when the music stops", False, {}),
        RuleSpec(
            "not_everything_at_once",
            "Not every channel is on at once for long",
            False,
            {
                "max_share": _Param(float, 0.0, 1.0),
                "max_seconds": _Param(float, 0.0, 600.0),
                "allow_sections": _NAMES,
            },
        ),
    )
}

# Requirement type -> (required fields, optional fields), beyond the shared ones.
REQUIREMENT_TYPES: dict[str, tuple[dict[str, _Param], dict[str, _Param]]] = {
    "keep_on": ({}, {"during": _NAMES}),
    "never_use": ({}, {}),
    "colors_only": ({"colors": _NAMES}, {}),
    "max_intensity": ({"max": _Param(int, 0, 100)}, {}),
    "quiet_during": ({"sections": _NAMES}, {}),
    "move_direction": (
        {"direction": _Param(str)},
        {"movement": _Param(str)},
    ),
}
_SHARED_REQUIREMENT_FIELDS = {"id", "type", "props", "severity", "note"}
SELECTOR_KEYS = ("all", "role", "names", "group")


@dataclass(frozen=True, slots=True)
class Selector:
    """Which props a requirement is about. Exactly one way of choosing."""

    all: bool = False
    role: str | None = None
    names: tuple[str, ...] = ()
    group: str | None = None

    def describe(self) -> str:
        if self.all:
            return "all props"
        if self.role is not None:
            return f"props identified as {self.role}"
        if self.group is not None:
            return f"props in group {self.group!r}"
        return "props named " + ", ".join(repr(name) for name in self.names)


@dataclass(frozen=True, slots=True)
class Requirement:
    requirement_id: str
    type: str
    props: Selector
    severity: str
    params: dict[str, Any]
    note: str
    source: str


@dataclass(frozen=True, slots=True)
class RuleSettings:
    rule_id: str
    severity: str
    params: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RuleSet:
    """The effective, merged profile used for one build."""

    sources: tuple[str, ...]
    rules: dict[str, RuleSettings]
    requirements: tuple[Requirement, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "rules": {
                rule_id: {"severity": s.severity, **copy.deepcopy(s.params)}
                for rule_id, s in sorted(self.rules.items())
            },
            "requirements": [
                {
                    "id": r.requirement_id,
                    "type": r.type,
                    "props": r.props.describe(),
                    "severity": r.severity,
                    **copy.deepcopy(r.params),
                    "note": r.note,
                    "source": r.source,
                }
                for r in self.requirements
            ],
        }


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that refuses duplicate keys instead of keeping the last one."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise RuleProfileError(
                f"line {key_node.start_mark.line + 1}: key {key!r} appears more than once"
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)
# YAML 1.1 reads bare yes/no/on/off as booleans, so "severity: off" would arrive
# as False. Only true/false are booleans here; everything else stays text.
_UniqueKeyLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_UniqueKeyLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _parse_yaml(text: str, source: str) -> Any:
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)  # safe loader subclass
    except RuleProfileError as exc:
        raise RuleProfileError(f"{source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RuleProfileError(f"{source}: not valid YAML: {exc}") from exc


def _check(value: Any, param: _Param, where: str) -> Any:
    if param.kind is list:
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise RuleProfileError(f"{where} must be a list of names")
        return list(value)
    if param.kind is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RuleProfileError(f"{where} must be a number")
        value = float(value)
    elif param.kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuleProfileError(f"{where} must be a whole number")
    elif param.kind is str:
        if not isinstance(value, str) or not value.strip():
            raise RuleProfileError(f"{where} must be text")
        return value
    if param.minimum is not None and value < param.minimum:
        raise RuleProfileError(f"{where} must be at least {param.minimum:g}")
    if param.maximum is not None and value > param.maximum:
        raise RuleProfileError(f"{where} must be at most {param.maximum:g}")
    return value


def _severity(value: Any, where: str) -> str:
    if value not in SEVERITIES:
        raise RuleProfileError(f"{where} must be one of {', '.join(SEVERITIES)}")
    return str(value)


def _selector(raw: Any, where: str) -> Selector:
    if not isinstance(raw, dict) or len(raw) != 1 or next(iter(raw)) not in SELECTOR_KEYS:
        raise RuleProfileError(
            f"{where} must choose props one way: " + ", ".join(f"{k}:" for k in SELECTOR_KEYS)
        )
    key, value = next(iter(raw.items()))
    if key == "all":
        if value is not True:
            raise RuleProfileError(f"{where}.all must be true")
        return Selector(all=True)
    if key == "role":
        if value not in ROLES or value == "unknown":
            raise RuleProfileError(
                f"{where}.role {value!r} is not a known role; use one of "
                + ", ".join(role for role in ROLES if role != "unknown")
            )
        return Selector(role=value)
    if key == "group":
        return Selector(group=_check(value, _Param(str), f"{where}.group"))
    return Selector(names=tuple(_check(value, _NAMES, f"{where}.names")))


def _apply_rules(
    rules: dict[str, RuleSettings], raw: Any, source: str, base: bool
) -> None:
    if not isinstance(raw, dict):
        raise RuleProfileError(f"{source}: rules must be a mapping of rule id to settings")
    for rule_id, settings in raw.items():
        spec = RULE_SPECS.get(rule_id)
        where = f"{source}: rules.{rule_id}"
        if spec is None:
            raise RuleProfileError(
                f"{where} is not a known rule; known rules: " + ", ".join(sorted(RULE_SPECS))
            )
        if not isinstance(settings, dict):
            raise RuleProfileError(f"{where} must be a mapping")
        current = rules.get(rule_id)
        severity = current.severity if current else "error"
        params = dict(current.params) if current else {}
        for key, value in settings.items():
            if key == "severity":
                new = _severity(value, f"{where}.severity")
                if spec.locked and not base and new != "error":
                    raise RuleProfileError(
                        f"{where}.severity: {spec.title.lower()} protects the sequence file "
                        "and cannot be relaxed"
                    )
                severity = new
            elif key in spec.params:
                params[key] = _check(value, spec.params[key], f"{where}.{key}")
            else:
                allowed = ", ".join(["severity", *spec.params]) or "severity"
                raise RuleProfileError(f"{where}.{key} is not a setting; allowed: {allowed}")
        rules[rule_id] = RuleSettings(rule_id, severity, params)


def _requirement(raw: Any, index: int, source: str) -> Requirement:
    where = f"{source}: requirements[{index}]"
    if not isinstance(raw, dict):
        raise RuleProfileError(f"{where} must be a mapping")
    kind = raw.get("type")
    if kind not in REQUIREMENT_TYPES:
        raise RuleProfileError(
            f"{where}.type must be one of {', '.join(REQUIREMENT_TYPES)}"
        )
    required, optional = REQUIREMENT_TYPES[kind]
    unknown = raw.keys() - _SHARED_REQUIREMENT_FIELDS - required.keys() - optional.keys()
    if unknown:
        raise RuleProfileError(f"{where} has unknown field(s) {', '.join(sorted(unknown))}")
    missing = (required.keys() | {"props"}) - raw.keys()
    if missing:
        raise RuleProfileError(f"{where} ({kind}) is missing {', '.join(sorted(missing))}")
    params = {
        key: _check(raw[key], spec, f"{where}.{key}")
        for key, spec in {**required, **optional}.items()
        if key in raw
    }
    if kind == "move_direction":
        if params["direction"] not in MOVEMENT_DIRECTIONS:
            raise RuleProfileError(
                f"{where}.direction must be one of {', '.join(MOVEMENT_DIRECTIONS)}"
            )
        if params.get("movement", "chase") not in MOVEMENT_KINDS:
            raise RuleProfileError(f"{where}.movement must be one of {', '.join(MOVEMENT_KINDS)}")
    requirement_id = raw.get("id", f"requirement-{index + 1}")
    if not isinstance(requirement_id, str) or not requirement_id.strip():
        raise RuleProfileError(f"{where}.id must be text")
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise RuleProfileError(f"{where}.note must be text")
    return Requirement(
        requirement_id=requirement_id,
        type=kind,
        props=_selector(raw["props"], f"{where}.props"),
        severity=_severity(raw.get("severity", "error"), f"{where}.severity"),
        params=params,
        note=note,
        source=source,
    )


def _layer(
    data: Any,
    source: str,
    rules: dict[str, RuleSettings],
    requirements: list[Requirement],
    base: bool,
) -> None:
    if not isinstance(data, dict):
        raise RuleProfileError(f"{source}: a rule profile must be a mapping")
    allowed = {"schema_version", "name", "description", "rules", "requirements"}
    unknown = data.keys() - allowed
    if unknown:
        raise RuleProfileError(
            f"{source}: unknown top-level key(s) {', '.join(sorted(map(str, unknown)))}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )
    if data.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise RuleProfileError(
            f"{source}: schema_version must be {PROFILE_SCHEMA_VERSION!r}, "
            f"found {data.get('schema_version')!r}"
        )
    _apply_rules(rules, data.get("rules", {}), source, base)
    raw_requirements = data.get("requirements", [])
    if not isinstance(raw_requirements, list):
        raise RuleProfileError(f"{source}: requirements must be a list")
    if base and raw_requirements:
        raise RuleProfileError(f"{source}: the built-in profile holds no display requirements")
    taken = {r.requirement_id for r in requirements}
    for index, raw in enumerate(raw_requirements):
        requirement = _requirement(raw, index, source)
        if requirement.requirement_id in taken:
            raise RuleProfileError(
                f"{source}: requirement id {requirement.requirement_id!r} is already used"
            )
        taken.add(requirement.requirement_id)
        requirements.append(requirement)


def _read_profile(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_PROFILE_BYTES:
            raise RuleProfileError(f"{path.name}: rule profile exceeds the 1 MiB limit")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuleProfileError(f"Cannot read rule profile: {path}") from exc


def default_profile_text() -> str:
    return resources.files("lor_sequence_builder.rules").joinpath("default.yaml").read_text(
        encoding="utf-8"
    )


def load_rule_set(profiles: tuple[str | Path, ...] = ()) -> RuleSet:
    """Return the built-in profile with each user profile layered on in order."""
    rules: dict[str, RuleSettings] = {}
    requirements: list[Requirement] = []
    _layer(_parse_yaml(default_profile_text(), "default.yaml"), "default.yaml", rules,
           requirements, base=True)
    missing = RULE_SPECS.keys() - rules.keys()
    if missing:
        raise RuleProfileError(f"default.yaml does not configure {', '.join(sorted(missing))}")
    sources = ["default.yaml"]
    for profile in profiles:
        path = Path(profile)
        _layer(_parse_yaml(_read_profile(path), path.name), path.name, rules, requirements,
               base=False)
        sources.append(path.name)
    return RuleSet(tuple(sources), rules, tuple(requirements))
