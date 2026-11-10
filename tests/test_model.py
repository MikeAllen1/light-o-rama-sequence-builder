from lor_sequence_builder.model import EffectEvent, Prop, SequenceProject, TimingMark


def test_valid_project_has_no_validation_errors():
    project = SequenceProject(
        title="Test Sequence",
        duration_ms=10_000,
        props=[Prop(id="tree", name="Tree")],
        events=[
            EffectEvent(
                id="event-1",
                prop_id="tree",
                start_ms=0,
                end_ms=1_000,
                effect_type="intensity",
                parameters={"intensity": 100},
            )
        ],
        timings=[TimingMark(time_ms=500, label="Beat")],
    )

    assert project.validate() == []


def test_event_cannot_reference_unknown_prop():
    project = SequenceProject(
        title="Test Sequence",
        duration_ms=10_000,
        events=[
            EffectEvent(
                id="event-1",
                prop_id="missing",
                start_ms=0,
                end_ms=1_000,
                effect_type="intensity",
            )
        ],
    )

    assert any("unknown prop" in error for error in project.validate())


def test_event_cannot_exceed_sequence_duration():
    project = SequenceProject(
        title="Test Sequence",
        duration_ms=1_000,
        props=[Prop(id="tree", name="Tree")],
        events=[
            EffectEvent(
                id="event-1",
                prop_id="tree",
                start_ms=0,
                end_ms=1_001,
                effect_type="intensity",
            )
        ],
    )

    assert any("after the sequence duration" in error for error in project.validate())


def test_project_json_round_trip():
    original = SequenceProject(
        title="Jingle Bells",
        duration_ms=120_000,
        props=[Prop(id="tree", name="Tree", element_type="rgb")],
    )

    restored = SequenceProject.from_dict(original.to_dict())

    assert restored.to_dict() == original.to_dict()
    assert restored.validate() == []
