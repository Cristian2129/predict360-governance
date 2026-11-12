"""Tests for labeling (technical spec, sections 2 and 3): window labels, maturity, anti-leakage."""
import json

import pandas as pd
import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT, load_config
from src.predict360.labeling import (
    NOT_VERIFIABLE,
    label_all,
    label_churn,
    label_delinquency,
)

T = "2026-03-31"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"


def _day(offset):
    return None if offset is None else (pd.Timestamp(T) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


def _table(event_column, rows, weight):
    """rows: list of (event day after T or None, observation end day after T)."""
    n = len(rows)
    return pd.DataFrame({
        "client_id": [f"CLI-{i:06d}" for i in range(n)],
        "snapshot_date": [T] * n,
        "exposure_cop_m": [10.0] * n,
        "weight": [weight] * n,
        "tenure_months": [24] * n,
        event_column: [_day(event) for event, _ in rows],
        "observation_end_date": [_day(end) for _, end in rows],
    })


def _dlq(rows):
    return _table("first_delinquency_date", rows, 250.0)


def _churn(rows):
    return _table("cancellation_date", rows, 62.5)


def _labels(table, column):
    return table[column].tolist()


def _step(funnel, name):
    matches = [s for s in funnel["steps"] if s["step"] == name]
    assert matches, f"step {name} missing"
    return matches[0]


# --- window boundaries ------------------------------------------------------

def test_event_on_t_plus_h_is_positive_and_one_day_later_is_not():
    table, _ = label_delinquency(_dlq([(30, 120), (31, 120), (None, 120)]), T, [30, 60])
    assert _labels(table, "delinquency_30") == [1, 0, 0]
    assert _labels(table, "delinquency_60") == [1, 1, 0]


def test_churn_3m_uses_a_90_day_window():
    table, _ = label_churn(_churn([(90, 150), (91, 150), (None, 150)]), T, 90)
    assert _labels(table, "churn_3m") == [1, 0, 0]


# --- maturity -----------------------------------------------------------------

def test_row_is_labeled_only_if_observation_reaches_t_plus_h():
    table, funnel = label_delinquency(_dlq([(None, 29), (None, 30)]), T, [30])
    assert table["client_id"].tolist() == ["CLI-000001"]
    assert _labels(table, "delinquency_30") == [0]
    assert _step(funnel, "excluded_immature_all_horizons") == {
        "step": "excluded_immature_all_horizons", "rows": 1, "clients": 250.0}


def test_observed_event_does_not_rescue_an_immature_row():
    # The event is inside (T, T+30] but observation stops before T+30: excluded, not 1
    table, funnel = label_delinquency(_dlq([(10, 20)]), T, [30])
    assert len(table) == 0
    assert _step(funnel, "excluded_immature_all_horizons")["rows"] == 1


def test_horizons_have_independent_maturity_with_nullable_integer_labels():
    table, funnel = label_delinquency(_dlq([(None, 45), (40, 90)]), T, [30, 60])
    assert str(table["delinquency_30"].dtype) == "Int8"
    assert str(table["delinquency_60"].dtype) == "Int8"
    assert _labels(table, "delinquency_30") == [0, 0]
    assert table["delinquency_60"].isna().tolist() == [True, False]  # empty, not 0
    assert table["delinquency_60"].iloc[1] == 1
    h60 = funnel["horizons"]["delinquency_60"]
    assert (h60["mature_rows"], h60["immature_rows"], h60["positive_rows"]) == (1, 1, 1)


def test_churn_rows_immature_for_90_days_leave_the_table():
    table, funnel = label_churn(_churn([(None, 89), (None, 90)]), T, 90)
    assert len(table) == 1
    assert str(table["churn_3m"].dtype) == "Int8"
    assert _step(funnel, "excluded_immature_all_horizons")["clients"] == 62.5


# --- anti-leakage -----------------------------------------------------------------

@pytest.mark.parametrize("event_day", [0, -5])
def test_event_on_or_before_cut_off_is_rejected(event_day):
    with pytest.raises(ValueError, match="cut-off"):
        label_delinquency(_dlq([(event_day, 120)]), T, [30])


def test_events_after_the_window_do_not_change_the_label():
    late, _ = label_delinquency(_dlq([(100, 120)]), T, [30, 60])
    none, _ = label_delinquency(_dlq([(None, 120)]), T, [30, 60])
    assert _labels(late, "delinquency_30") == _labels(none, "delinquency_30") == [0]
    assert _labels(late, "delinquency_60") == _labels(none, "delinquency_60") == [0]


def test_labeled_tables_drop_dates_after_the_cut_off():
    dlq, _ = label_delinquency(_dlq([(10, 120)]), T, [30, 60])
    churn, _ = label_churn(_churn([(10, 150)]), T, 90)
    for table in (dlq, churn):
        assert not {"first_delinquency_date", "cancellation_date", "observation_end_date"} & set(table.columns)
    assert {"client_id", "snapshot_date", "exposure_cop_m", "weight", "tenure_months"} <= set(dlq.columns)


# --- cohort exclusions the v1 contracts cannot check ------------------------------

@pytest.mark.parametrize("label,df,step,column", [
    (label_delinquency, _dlq([(None, 120)]), "cohort_not_in_arrears_at_T", "current_dpd"),
    (label_churn, _churn([(None, 150)]), "cohort_not_maturing_within_horizon", "maturity_date"),
])
def test_unverifiable_cohort_step_is_never_reported_as_zero(label, df, step, column):
    _, funnel = label(df, T, [30] if label is label_delinquency else 90)
    found = _step(funnel, step)
    assert found["status"] == NOT_VERIFIABLE
    assert found["missing_column"] == column
    assert "rows" not in found and "clients" not in found  # no number means "not checked"


# --- assumptions drive the horizons ------------------------------------------------

def _assumptions_file(tmp_path, delinquency_horizons, churn_horizon):
    data = yaml.safe_load((CONFIG_DIR / "assumptions.yaml").read_text(encoding="utf-8"))
    for item in data["assumptions"]:
        if "delinquency.horizons_days" in item["value"]:
            item["value"]["delinquency.horizons_days"] = delinquency_horizons
        if "churn.horizon_days" in item["value"]:
            item["value"]["churn.horizon_days"] = churn_horizon
    path = tmp_path / "assumptions.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_default_assumptions_give_the_spec_labels():
    result = label_all(_dlq([(None, 120)]), _churn([(None, 150)]), T)
    assert {"delinquency_30", "delinquency_60"} <= set(result["delinquency"]["table"].columns)
    assert "churn_3m" in result["churn"]["table"].columns


def test_changing_the_assumptions_changes_the_labels(tmp_path):
    path = _assumptions_file(tmp_path, [15], 45)
    result = label_all(_dlq([(20, 120)]), _churn([(40, 150)]), T, assumptions_path=path)
    dlq, churn = result["delinquency"]["table"], result["churn"]["table"]
    assert "delinquency_30" not in dlq.columns and _labels(dlq, "delinquency_15") == [0]
    assert "churn_3m" not in churn.columns and _labels(churn, "churn_45d") == [1]


# --- synthetic data -------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic():
    cfg = load_config(CONFIG_DIR / "synthetic.yaml")
    dlq = pd.read_csv(SYNTHETIC_DIR / "delinquency_sample.csv")
    churn = pd.read_csv(SYNTHETIC_DIR / "churn_sample.csv")
    return cfg, label_all(dlq, churn, str(cfg["snapshot_date"]))


def test_synthetic_funnel_adds_up_and_excludes_immature_rows(synthetic):
    cfg, result = synthetic
    for name, expected_rows in (("delinquency", 500), ("churn", 200)):
        funnel = result[name]["funnel"]
        entered = _step(funnel, "input")
        excluded = _step(funnel, "excluded_immature_all_horizons")
        labeled = _step(funnel, "labeled")
        assert entered["rows"] == expected_rows
        assert excluded["rows"] > 0
        assert entered["rows"] == excluded["rows"] + labeled["rows"] == expected_rows
        assert entered["clients"] == pytest.approx(excluded["clients"] + labeled["clients"])
        assert len(result[name]["table"]) == labeled["rows"]


def test_synthetic_input_clients_match_the_client_figures(synthetic):
    _, result = synthetic
    assert _step(result["delinquency"]["funnel"], "input")["clients"] == 125_000
    assert _step(result["churn"]["funnel"], "input")["clients"] == 12_500


def test_synthetic_base_rates_are_plausible_and_monotonic(synthetic):
    cfg, result = synthetic
    gen = cfg["generator"]
    horizons = result["delinquency"]["funnel"]["horizons"]
    for key, label in (("delinquency", "delinquency_30"), ("delinquency", "delinquency_60"),
                       ("churn", "churn_3m")):
        rate = result[key]["funnel"]["horizons"][label]["base_rate"]
        assert 0 < rate <= gen[key]["base_rate"]["max"], (label, rate)
    # On rows mature for both horizons, a 30-day event is also a 60-day event
    table = result["delinquency"]["table"].dropna(subset=["delinquency_60"])
    assert (table["delinquency_60"] >= table["delinquency_30"]).all()
    assert horizons["delinquency_30"]["mature_rows"] >= horizons["delinquency_60"]["mature_rows"]


def test_funnel_is_json_serializable_aggregates_only(synthetic):
    _, result = synthetic
    text = json.dumps({k: v["funnel"] for k, v in result.items()})
    churn_ids = pd.read_csv(SYNTHETIC_DIR / "churn_sample.csv")["client_id"]
    assert not any(client_id in text for client_id in churn_ids)
