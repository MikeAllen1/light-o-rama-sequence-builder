"""Format-independent sequence model.

All event timestamps use integer milliseconds. The S6 format adapter is responsible
for converting these values to the exact timing representation required by LOREDIT.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MODEL_VERSION = 1


@dataclass(slots=True)
class Prop:
    """A controllable item from the user's Light-O-Rama preview."""

    id: str
    name: str
    element_type: str = "unknown"
    color: str | None = None
    group: str | None = None


@dataclass(slots=True)
class TimingMark:
    """A musical timing marker."""

    time_ms: int
    label: str = "Timing"


@dataclass(slots=True)
class EffectEvent:
    """An effect applied to one prop over an absolute time interval."""

    id: str
    prop_id: str
    start_ms: int
    end_ms: int
    effect_type: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SequenceProject:
    """Intermediate representation used by planners and export adapters."""

    title: str
    duration_ms: int
    props: list[Prop] = field(default_factory=list)
    events: list[EffectEvent] = field(default_factory=list)
    timings: list[TimingMark] = field(default_factory=list)
    media_path: str | None = None
    model_version: int = MODEL_VERSION

    def validate(self) -> list[str]:
        """Return all structural and timing errors; an empty list means valid."""
        errors: list[str] = []

        if self.model_version != MODEL_VERSION:
            errors.append(
                f"Unsupported model version {self.model_version}; expected {MODEL_VERSION}."
            )
        if not self.title.strip():
            errors.append("Sequence title must not be empty.")
        if self.duration_ms <= 0:
            errors.append("Sequence duration must be greater than zero.")

        prop_ids = [prop.id for prop in self.props]
        if any(not value.strip() for value in prop_ids):
            errors.append("Every prop must have a non-empty ID.")
        if len(prop_ids) != len(set(prop_ids)):
            errors.append("Prop IDs must be unique.")

        event_ids: set[str] = set()
        known_props = set(prop_ids)
        for event in self.events:
            if not event.id.strip():
                errors.append("Every event must have a non-empty ID.")
            elif event.id in event_ids:
                errors.append(f"Duplicate event ID: {event.id}.")
            event_ids.add(event.id)

            if event.prop_id not in known_props:
                errors.append(
                    f"Event {event.id!r} references unknown prop {event.prop_id!r}."
                )
            if event.start_ms < 0:
                errors.append(f"Event {event.id!r} starts before time zero.")
            if event.end_ms <= event.start_ms:
                errors.append(f"Event {event.id!r} must end after it starts.")
            if event.end_ms > self.duration_ms:
                errors.append(f"Event {event.id!r} ends after the sequence duration.")
            if not event.effect_type.strip():
                errors.append(f"Event {event.id!r} has no effect type.")

        for index, timing in enumerate(self.timings):
            if timing.time_ms < 0 or timing.time_ms > self.duration_ms:
                errors.append(f"Timing mark {index} is outside the sequence duration.")

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Serialize the project to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceProject:
        """Build a project from its JSON-compatible representation."""
        return cls(
            title=str(data.get("title", "")),
            duration_ms=int(data.get("duration_ms", 0)),
            props=[Prop(**item) for item in data.get("props", [])],
            events=[EffectEvent(**item) for item in data.get("events", [])],
            timings=[TimingMark(**item) for item in data.get("timings", [])],
            media_path=data.get("media_path"),
            model_version=int(data.get("model_version", MODEL_VERSION)),
        )
