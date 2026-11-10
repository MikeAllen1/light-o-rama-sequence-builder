from lor_sequence_builder.audio import _interval_summary


def test_interval_summary_reports_regular_spacing():
    result = _interval_summary([0, 500, 1000, 1500])

    assert result["median_interval_ms"] == 500
    assert result["interval_regularity"] == 1.0


def test_interval_summary_handles_insufficient_beats():
    result = _interval_summary([250])

    assert result["median_interval_ms"] is None
    assert result["interval_regularity"] == 0.0


def test_interval_summary_detects_irregular_spacing():
    result = _interval_summary([0, 400, 1000, 1400])

    assert result["median_interval_ms"] == 400
    assert result["interval_regularity"] < 1.0
