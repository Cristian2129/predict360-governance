import pandas as pd
from src.predict360.sprint_metrics import calculate_velocity, get_burndown_series


def test_done_story_repeated_in_blocks_is_counted_once():
    log = pd.DataFrame([
        {"sprint": 1, "block": 0, "story_id": "NONE", "story_points": 0, "status": "Planned", "ideal_remaining": 15.0, "actual_remaining": 15},
        {"sprint": 1, "block": 1, "story_id": "US-06", "story_points": 5, "status": "Done", "ideal_remaining": 10.0, "actual_remaining": 10},
        {"sprint": 1, "block": 2, "story_id": "US-06", "story_points": 5, "status": "Done", "ideal_remaining": 5.0, "actual_remaining": 10},
    ])
    assert calculate_velocity(log).iloc[0]["completed_sp"] == 5


def test_missing_block_zero_raises_clear_error():
    log = pd.DataFrame([
        {"sprint": 1, "block": 1, "story_id": "US-06", "story_points": 5, "status": "Done", "ideal_remaining": 10.0, "actual_remaining": 10},
    ])
    with pytest.raises(ValueError):
        calculate_velocity(log)


def test_zero_planned_sp_gives_zero_rate():
    log = pd.DataFrame([
        {"sprint": 1, "block": 0, "story_id": "NONE", "story_points": 0, "status": "Planned", "ideal_remaining": 0.0, "actual_remaining": 0},
    ])
    assert calculate_velocity(log).iloc[0]["completion_rate_pct"] == 0.0