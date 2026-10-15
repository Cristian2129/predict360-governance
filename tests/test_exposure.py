import pandas as pd
import pytest

from src.predict360.exposure import (
    export_prioritized_backlog,
    get_direct_exposure_total,
    prioritize_backlog,
)


def test_delinquency_ranks_before_churn_and_computes_efficiency():
    """EarlyRisk (11,760M/SP) must rank ahead of StayBank Churn (2,275M/SP)."""
    sample = pd.DataFrame([
        {"story_id": "US-05", "exposure_type": "direct", "exposure_cop_m": 18200.0, "sp": 8},
        {"story_id": "US-04-P1", "exposure_type": "direct", "exposure_cop_m": 58800.0, "sp": 5},
    ])
    ordered = prioritize_backlog(sample)
    assert list(ordered["story_id"]) == ["US-04-P1", "US-05"]
    assert list(ordered["cop_m_per_sp"]) == [11760.0, 2275.0]
    assert list(ordered["priority_rank"]) == [1, 2]


def test_zero_exposure_flagged_as_enabling():
    """Stories with 0 COP exposure must be categorized as Enabling with 0.0 efficiency."""
    sample = pd.DataFrame([
        {"story_id": "US-01", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 2},
        {"story_id": "US-04-P1", "exposure_type": "direct", "exposure_cop_m": 58800.0, "sp": 5},
    ])
    ordered = prioritize_backlog(sample)
    enabling_row = ordered[ordered["story_id"] == "US-01"].iloc[0]
    assert enabling_row["priority_tier"] == "Enabling"
    assert enabling_row["cop_m_per_sp"] == 0.0


def test_direct_exposure_avoids_double_counting():
    """Direct exposure sum must equal 77,000M even when umbrella stories (US-03) are present."""
    sample = pd.DataFrame([
        {"story_id": "US-03-P1", "exposure_type": "umbrella", "exposure_cop_m": 77000.0, "sp": 5},
        {"story_id": "US-04-P1", "exposure_type": "direct", "exposure_cop_m": 58800.0, "sp": 5},
        {"story_id": "US-05", "exposure_type": "direct", "exposure_cop_m": 18200.0, "sp": 8},
        {"story_id": "US-01", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 2},
    ])
    assert get_direct_exposure_total(sample) == 77000.0


def test_export_creates_markdown_file_with_table(tmp_path):
    """Verifies that export_prioritized_backlog automatically writes the .md evidence table."""
    csv_path = tmp_path / "backlog.csv"
    md_path = tmp_path / "backlog_prioritization.md"

    pd.DataFrame([
        {"story_id": "US-03-P1", "title": "Data gate", "domain": "Data", "exposure_type": "umbrella", "exposure_cop_m": 77000.0, "sp": 5, "sprint": 1},
        {"story_id": "US-04-P1", "title": "EarlyRisk", "domain": "Credit", "exposure_type": "direct", "exposure_cop_m": 58800.0, "sp": 5, "sprint": 2},
        {"story_id": "US-05", "title": "StayBank", "domain": "Churn", "exposure_type": "direct", "exposure_cop_m": 18200.0, "sp": 8, "sprint": 3},
    ]).to_csv(csv_path, index=False)

    export_prioritized_backlog(backlog_csv=csv_path, out_md=md_path)

    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "COP 77,000.0M" in content
    assert "| Rank | Story ID |" in content
    assert "11,760.0" in content


def test_missing_columns_raise_value_error():
    with pytest.raises(ValueError):
        prioritize_backlog(pd.DataFrame([{"story_id": "US-01"}]))