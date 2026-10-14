import pandas as pd
import pytest

from src.predict360.sprint_metrics import calculate_velocity, get_burndown_series


def _log():
    return pd.DataFrame([
        {"sprint": 1, "story_id": "US-01", "story_points": 5, "status": "Done", "closed_block": 1},
        {"sprint": 1, "story_id": "US-02", "story_points": 3, "status": "Planned", "closed_block": None},
    ])


def test_velocity_counts_only_done_stories():
    row = calculate_velocity(_log()).iloc[0]
    assert row["planned_sp"] == 8
    assert row["completed_sp"] == 5
    assert row["completion_rate_pct"] == 62.5


def test_velocity_is_zero_when_nothing_is_done():
    log = _log()
    log["status"] = "Planned"
    assert calculate_velocity(log).iloc[0]["completed_sp"] == 0


def test_missing_columns_raise_clear_error():
    with pytest.raises(ValueError):
        calculate_velocity(pd.DataFrame([{"sprint": 1}]))


def test_burndown_series_uses_closed_block():
    series = get_burndown_series(_log(), 1, total_blocks=2)
    assert list(series["block"]) == [0, 1, 2]
    assert list(series["actual_remaining"]) == [8, 3, 3]
    assert list(series["ideal_remaining"]) == [8.0, 4.0, 0.0] 