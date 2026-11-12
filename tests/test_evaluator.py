"""Tests for the evaluator core (technical spec, sections 4 and 9): COP capture, net value and K*."""
import hashlib
import json

import pandas as pd
import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT, load_assumptions, load_config
from src.predict360.evaluator import (
    MIN_PUBLISHED_CLIENTS,
    capture_curve,
    evaluate_at_k,
    evaluate_models,
    k_star,
    random_baseline,
)
from src.predict360.labeling import label_all
from src.predict360.model_card import run_gate2

SYNTHETIC_DIR = ROOT / "data" / "synthetic"


@pytest.fixture(scope="module")
def assumptions():
    return load_assumptions()["values"]


def _hmac_like(i):
    return hashlib.sha256(f"client-{i}".encode()).hexdigest()


def _spec_case(events_in_top_100):
    """Section 4 test case: 1,000 clients, 50 events of 10M; ``events_in_top_100`` ranked first."""
    n, events = 1000, 50
    y = [0] * n
    score = [0.0] * n
    # Events ranked inside the top 100 get the highest scores, the rest of the events rank last
    for i in range(events_in_top_100):
        y[i], score[i] = 1, 0.99
    for i in range(events_in_top_100, 100):
        score[i] = 0.98                      # non-events filling the top 100
    for i in range(n - (events - events_in_top_100), n):
        y[i] = 1                             # remaining events at the bottom (score 0.0)
    return pd.DataFrame({
        "client_id": [_hmac_like(i) for i in range(n)],
        "score": score,
        "y": y,
        "exposure_cop_m": [10.0] * n,
        "weight": [1.0] * n,
    })


# --- the mandatory case: 18M, 58M, 118M ------------------------------------------------

@pytest.mark.parametrize("events_in_top_100,capture,captured,net_value", [
    (15, 0.30, 150.0, 58.0),    # simple rule
    (30, 0.60, 300.0, 118.0),   # model
])
def test_spec_case_rule_and_model(assumptions, events_in_top_100, capture, captured, net_value):
    result = evaluate_at_k(_spec_case(events_in_top_100), 100, assumptions)
    assert result["k_requested"] == 100 and result["k_applied"] == 100
    assert result["capture"] == pytest.approx(capture)
    assert result["captured_cop_m"] == pytest.approx(captured)
    assert result["net_value_cop_m"] == pytest.approx(net_value)


def test_spec_case_random_baseline(assumptions):
    result = random_baseline(_spec_case(30), 100, assumptions)
    assert result["capture"] == pytest.approx(0.10)
    assert result["captured_cop_m"] == pytest.approx(50.0)
    assert result["net_value_cop_m"] == pytest.approx(18.0)


def test_perfect_model_captures_everything(assumptions):
    df = _spec_case(30)
    df["score"] = df["y"].astype(float)
    assert evaluate_at_k(df, 50, assumptions)["capture"] == pytest.approx(1.0)


def test_random_capture_is_k_share(assumptions):
    df = _spec_case(30)
    for k in (100, 250, 1000):
        assert random_baseline(df, k, assumptions)["capture"] == pytest.approx(k / 1000)


# --- weighted K: requested vs applied --------------------------------------------------

def _weighted(n=487, weight=250.0):
    return pd.DataFrame({
        "client_id": [_hmac_like(i) for i in range(n)],
        "score": [1.0 - i / n for i in range(n)],
        "y": [1 if i % 10 == 0 else 0 for i in range(n)],
        "exposure_cop_m": [100.0] * n,
        "weight": [weight] * n,
    })


def test_rows_are_not_split_and_both_k_values_are_reported(assumptions):
    result = evaluate_at_k(_weighted(), 12_175, assumptions)
    assert result["k_requested"] == 12_175
    assert result["k_applied"] == 12_000          # 48 rows x 250 clients
    cost_cop_m = 12_000 * assumptions["value"]["cost_per_contact_cop"] / 1_000_000
    gross = assumptions["value"]["action_effectiveness"] * result["captured_cop_m"]
    assert result["net_value_cop_m"] == pytest.approx(gross - cost_cop_m)


def test_random_baseline_uses_the_applied_k(assumptions):
    df = _weighted()
    total = float((df["exposure_cop_m"] * df["y"]).sum())
    result = random_baseline(df, 12_175, assumptions)
    assert result["k_applied"] == 12_000
    assert result["captured_cop_m"] == pytest.approx(total * 12_000 / df["weight"].sum())


# --- K* --------------------------------------------------------------------------------

def test_k_star_is_the_maximum_of_the_curve(assumptions):
    curve = capture_curve(_spec_case(30), assumptions)
    best = k_star(curve)
    assert best["net_value_cop_m"] == pytest.approx(curve["net_value_cop_m"].max())
    assert best["net_value_cop_m"] >= 118.0


def test_higher_cost_per_contact_never_raises_k_star(assumptions):
    cheap = k_star(capture_curve(_spec_case(30), assumptions))["k"]
    expensive_values = {**assumptions, "value": {**assumptions["value"], "cost_per_contact_cop": 2_000_000}}
    expensive = k_star(capture_curve(_spec_case(30), expensive_values))["k"]
    assert expensive <= cheap


def test_ties_are_broken_by_client_id(assumptions):
    df = _spec_case(30)
    df["score"] = 0.5
    order = capture_curve(df, assumptions, keep_order=True)["client_id"].dropna().tolist()  # row 0 is K = 0
    assert order == sorted(df["client_id"])


# --- assumptions live in config ----------------------------------------------------------

def test_changing_effectiveness_in_assumptions_changes_net_value(tmp_path):
    data = yaml.safe_load((CONFIG_DIR / "assumptions.yaml").read_text(encoding="utf-8"))
    for item in data["assumptions"]:
        if "value.action_effectiveness" in item["value"]:
            item["value"]["value.action_effectiveness"] = 0.20
    path = tmp_path / "assumptions.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    values = load_assumptions(path)["values"]
    assert evaluate_at_k(_spec_case(30), 100, values)["net_value_cop_m"] == pytest.approx(58.0)  # 0.2 x 300 - 2


# --- synthetic data: admitted models only ------------------------------------------------

@pytest.fixture(scope="module")
def synthetic(assumptions):
    cfg = load_config(CONFIG_DIR / "synthetic.yaml")
    labeled = label_all(pd.read_csv(SYNTHETIC_DIR / "delinquency_sample.csv"),
                        pd.read_csv(SYNTHETIC_DIR / "churn_sample.csv"), str(cfg["snapshot_date"]))
    scores = pd.read_csv(SYNTHETIC_DIR / "scores_sample.csv")
    gate2 = run_gate2(cfg, SYNTHETIC_DIR / "model_cards", SYNTHETIC_DIR / "scores_sample.csv")
    return labeled, scores, gate2


def _find(report, model_id, label):
    matches = [e for e in report["evaluations"] if e["model_id"] == model_id and e["label"] == label]
    assert len(matches) == 1, (model_id, label)
    return matches[0]


def test_every_admitted_model_is_evaluated_on_every_label(synthetic, assumptions):
    labeled, scores, gate2 = synthetic
    report = evaluate_models(labeled, scores, gate2, assumptions)
    keys = {(e["model_id"], e["label"]) for e in report["evaluations"]}
    assert keys == {(m, label) for m in ("baseline_rule", "model_a", "model_b")
                    for label in ("delinquency_30", "delinquency_60", "churn_3m")}
    assert all(e["status"] == "evaluated" for e in report["evaluations"])


def test_rejected_card_is_not_evaluated(synthetic, assumptions):
    labeled, scores, gate2 = synthetic
    rejected = json.loads(json.dumps(gate2))
    for card in rejected["cards"]:
        if card["model_id"] == "model_b" and card["target"] == "delinquency":
            card["decision"] = "REJECTED"
    report = evaluate_models(labeled, scores, rejected, assumptions)
    models = {(e["model_id"], e["label"]) for e in report["evaluations"]}
    assert ("model_b", "delinquency_30") not in models and ("model_b", "churn_3m") in models


def test_immature_scored_rows_are_dropped_and_counted(synthetic, assumptions):
    labeled, scores, gate2 = synthetic
    report = evaluate_models(labeled, scores, gate2, assumptions)
    d30 = _find(report, "model_a", "delinquency_30")
    assert d30["n_rows"] == 487 and d30["scores_dropped_rows"] == 13
    assert d30["n_clients"] == 121_750
    assert d30["k_requested"] == pytest.approx(12_175) and d30["k_applied"] == 12_000


def test_model_a_beats_random_on_capture(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    for label in ("delinquency_30", "delinquency_60", "churn_3m"):
        e = _find(report, "model_a", label)
        assert e["at_k"]["capture"] > e["random_at_k"]["capture"], label


def test_missing_score_for_a_labeled_client_is_not_evaluated(synthetic, assumptions):
    labeled, scores, gate2 = synthetic
    first = labeled["churn"]["table"]["client_id"].iloc[0]
    holes = scores[~((scores["client_id"] == first) & (scores["model_id"] == "model_a")
                     & (scores["horizon_days"] == 90))]
    report = evaluate_models(labeled, holes, gate2, assumptions)
    e = _find(report, "model_a", "churn_3m")
    assert e["status"] == "not_evaluated" and e["reason"] == "incomplete_scores"
    assert "at_k" not in e
    assert _find(report, "model_b", "churn_3m")["status"] == "evaluated"


def test_duplicate_score_rows_raise(synthetic, assumptions):
    labeled, scores, gate2 = synthetic
    doubled = pd.concat([scores, scores.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_models(labeled, doubled, gate2, assumptions)


def test_report_is_aggregates_only(synthetic, assumptions):
    labeled, scores, gate2 = synthetic
    report = evaluate_models(labeled, scores, gate2, assumptions)
    text = json.dumps(report)
    assert not any(client_id in text for client_id in scores["client_id"].unique())
    for e in report["evaluations"]:
        steps = pd.Series([p["k"] for p in e["curve"]]).diff().dropna()
        assert (steps >= MIN_PUBLISHED_CLIENTS).all(), e["label"]  # no point reveals < 30 clients


# --- published values (dashboard_data_v1 contract) ------------------------------------

def test_capture_never_exceeds_one_despite_float_sums(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    for e in report["evaluations"]:
        assert all(p["capture"] <= 1.0 for p in e["curve"]), (e["model_id"], e["label"])
        assert e["curve"][-1]["capture"] == 1.0


def test_published_k_star_is_a_point_of_the_published_curve(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    for e in report["evaluations"]:
        assert e["k_star"] in e["curve"], (e["model_id"], e["label"])
        assert e["k_star"]["net_value_cop_m"] == max(p["net_value_cop_m"] for p in e["curve"])
