"""Tests for the evaluator core (technical spec, sections 4 and 9): COP capture, net value and K*."""
import hashlib
import json

import pandas as pd
import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT, load_assumptions, load_config
from src.predict360.evaluator import (
    MIN_PUBLISHED_CLIENTS,
    applied_point,
    bootstrap_net_values,
    brier_score,
    calibration_table,
    capture_curve,
    evaluate_at_k,
    evaluate_models,
    interval,
    k_star,
    pr_auc,
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


# --- one rule for K, shared with the dashboard simulator (B12b-2) ------------------------

def test_applied_point_rounds_down_never_to_the_nearest():
    points = [{"k": 0.0}, {"k": 50.0}, {"k": 100.0}]
    assert applied_point(points, 99.0)["k"] == 50.0          # the nearest would be 100
    assert applied_point(points, 100.0)["k"] == 100.0
    assert applied_point(points, 100.0 + 1e-12)["k"] == 100.0
    assert applied_point(points, 10.0)["k"] == 0.0           # capacity is a hard limit


def test_k_applied_is_a_point_of_the_published_curve(assumptions):
    # Capacity of 12% on 1,000 clients: the grid has 50-client steps, so 120 becomes 100,
    # the same point the simulator can use (it only has the published curve)
    at_k = evaluate_at_k(_spec_case(30), 120, assumptions)
    assert at_k["k_requested"] == 120 and at_k["k_applied"] == 100
    assert random_baseline(_spec_case(30), 120, assumptions)["k_applied"] == 100


def test_every_at_k_is_the_published_point_at_k_applied(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    for e in report["evaluations"]:
        if e["status"] != "evaluated":
            continue
        point = applied_point(e["curve"], e["k_requested"])
        assert point["k"] == e["k_applied"]
        assert {k: v for k, v in point.items() if k != "k"} == e["at_k"]


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


# --- B8b: ranking metrics at K and on the published grid ---------------------------------

@pytest.mark.parametrize("events_in_top_100,precision,recall,lift", [
    (15, 0.15, 0.30, 3.0),    # rule: 15 of 100 contacted are events; prevalence 50/1000
    (30, 0.30, 0.60, 6.0),    # model
])
def test_precision_recall_and_lift_at_k(assumptions, events_in_top_100, precision, recall, lift):
    result = evaluate_at_k(_spec_case(events_in_top_100), 100, assumptions)
    assert result["precision"] == pytest.approx(precision)
    assert result["recall"] == pytest.approx(recall)
    assert result["lift"] == pytest.approx(lift)


def test_random_baseline_rates(assumptions):
    result = random_baseline(_spec_case(30), 100, assumptions)
    assert result["precision"] == pytest.approx(0.05)
    assert result["recall"] == pytest.approx(0.10)
    assert result["lift"] == pytest.approx(1.0)


def test_rates_are_weighted_by_clients(assumptions):
    df = pd.DataFrame({"client_id": ["a", "b", "c"], "score": [0.9, 0.5, 0.1], "y": [1, 0, 1],
                       "exposure_cop_m": [1.0, 1.0, 1.0], "weight": [300.0, 100.0, 100.0]})
    # rows a and b: 400 clients, 300 events of 400 (x100 so that K = 400 is a published grid point)
    result = evaluate_at_k(df, 400, assumptions)
    assert result["precision"] == pytest.approx(0.75)
    assert result["recall"] == pytest.approx(0.75)
    assert result["lift"] == pytest.approx(0.75 / 0.8)


def test_curve_starts_without_precision_or_lift(assumptions):
    first = capture_curve(_spec_case(30), assumptions).iloc[0]
    assert first["recall"] == 0.0
    assert pd.isna(first["precision"]) and pd.isna(first["lift"])


# --- B8b: PR-AUC and calibration -----------------------------------------------------------

def _tiny(weights=(1.0, 1.0, 1.0, 1.0)):
    return pd.DataFrame({"client_id": ["a", "b", "c", "d"], "score": [0.9, 0.8, 0.7, 0.6],
                         "y": [1, 0, 1, 0], "exposure_cop_m": [1.0] * 4, "weight": list(weights)})


def test_pr_auc_by_hand():
    assert pr_auc(_tiny()) == pytest.approx(0.5 * 1 + 0.5 * 2 / 3)
    assert pr_auc(_tiny((2.0, 1.0, 1.0, 1.0))) == pytest.approx(2 / 3 * 1 + 1 / 3 * 3 / 4)


def test_pr_auc_of_a_perfect_model_is_one_and_without_events_is_none():
    df = _spec_case(30)
    df["score"] = df["y"].astype(float)
    assert pr_auc(df) == pytest.approx(1.0)
    assert pr_auc(df.assign(y=0)) is None


def test_brier_score_by_hand():
    assert brier_score(_tiny()) == pytest.approx((0.01 + 0.64 + 0.09 + 0.36) / 4)
    assert brier_score(_tiny((2.0, 1.0, 1.0, 1.0))) == pytest.approx((0.02 + 0.64 + 0.09 + 0.36) / 5)


def test_calibration_has_ten_deciles_that_add_up(assumptions):
    df = _spec_case(30)
    df["score"] = [i / 1000 for i in range(1000)]
    table = calibration_table(df, assumptions)
    assert len(table) == 10
    assert [cell["n_clients"] for cell in table] == [100.0] * 10
    assert sum(cell["observed_rate"] * cell["n_clients"] for cell in table) == pytest.approx(50)
    assert table[0]["mean_score"] < table[-1]["mean_score"]


def test_calibration_merges_cells_below_the_configured_minimum(assumptions):
    df = _spec_case(30)
    df["score"] = [i / 1000 for i in range(1000)]
    strict = {**assumptions, "evaluation": {**assumptions["evaluation"], "min_cell_clients": 150}}
    table = calibration_table(df, strict)
    assert all(cell["n_clients"] >= 150 for cell in table)
    assert sum(cell["n_clients"] for cell in table) == 1000
    assert [cell["bin"] for cell in table] == list(range(1, len(table) + 1))


def test_calibration_publishes_nothing_under_the_minimum(assumptions):
    assert calibration_table(_tiny(), assumptions) == []


# --- B8b: paired bootstrap of net value at a fixed K -------------------------------------------

def _ranking(events_in_top_100):
    """Scores over the population of _spec_case(30): `events_in_top_100` of its 50 events lead the top 100."""
    case = _spec_case(30)
    events = case.loc[case["y"] == 1, "client_id"].tolist()
    others = case.loc[case["y"] == 0, "client_id"].tolist()
    top = set(events[:events_in_top_100] + others[:100 - events_in_top_100])
    return case["client_id"].map(lambda cid: 0.99 if cid in top else 0.01).to_numpy()


def _models_on_spec_case(**events_in_top_100):
    rows = _spec_case(30).drop(columns="score")    # same events for every model, only the ranking changes
    return rows, {model_id: _ranking(events) for model_id, events in events_in_top_100.items()}


def test_bootstrap_is_reproducible_and_keeps_the_number_of_rows(assumptions):
    rows, scores = _models_on_spec_case(rule=15, model=30)
    first = bootstrap_net_values(rows, scores, 100, assumptions, samples=50, seed=42)
    second = bootstrap_net_values(rows, scores, 100, assumptions, samples=50, seed=42)
    assert set(first) == {"rule", "model"} and len(first["model"]) == 50
    assert (first["model"] == second["model"]).all() and (first["rule"] == second["rule"]).all()


def test_bootstrap_is_paired(assumptions):
    rows, scores = _models_on_spec_case(model=30)
    scores["copy"] = scores["model"].copy()
    draws = bootstrap_net_values(rows, scores, 100, assumptions, samples=50, seed=42)
    assert (draws["model"] - draws["copy"] == 0).all()     # same resamples, same K


def test_interval_is_a_percentile_interval():
    low, high = interval(pd.Series(range(101)).to_numpy(), 0.95)
    assert low == pytest.approx(2.5) and high == pytest.approx(97.5)


# --- B8b: promotion and verdict per target ---------------------------------------------------

def _labeled_delinquency():
    case = _spec_case(30)
    table = case[["client_id", "exposure_cop_m", "weight"]].copy()
    table["delinquency_30"] = case["y"].astype("Int8")
    table["delinquency_60"] = case["y"].astype("Int8")
    return {"delinquency": {"table": table}}


def _scores_long(models: dict) -> pd.DataFrame:
    """models: model_id -> (events in the top 100 at 30 days, at 60 days)."""
    frames = []
    for model_id, per_horizon in models.items():
        for horizon, events in zip((30, 60), per_horizon):
            frames.append(pd.DataFrame({"client_id": _spec_case(30)["client_id"], "model_id": model_id,
                                        "horizon_days": horizon, "score": _ranking(events)}))
    return pd.concat(frames, ignore_index=True)


def _gate2(*model_ids):
    return {"cards": [{"target": "delinquency", "model_id": m, "decision": "ADMITTED"} for m in model_ids]}


def _decision(report, target="delinquency"):
    matches = [d for d in report["decisions"] if d["target"] == target]
    assert len(matches) == 1
    return matches[0]


def test_model_that_beats_the_rule_on_both_horizons_is_authorized_for_shadow(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30)}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), assumptions)
    decision = _decision(report)
    assert decision["verdict"] == "authorized_for_shadow_deployment" and decision["model_id"] == "model_a"
    for label in ("delinquency_30", "delinquency_60"):
        vs = _find(report, "model_a", label)["vs_baseline"]
        assert vs["baseline_model"] == "baseline_rule" and vs["beats"] is True
        assert vs["difference_cop_m"] == pytest.approx(60.0)       # 118 - 58 at K = 100
        assert vs["ci_low_cop_m"] > vs["margin_cop_m"]
        assert vs["k_clients"] == 100
    assert _find(report, "baseline_rule", "delinquency_30")["vs_baseline"] is None


def test_winning_only_one_delinquency_horizon_is_not_enough(assumptions):
    models = {"baseline_rule": (15, 15), "model_c": (30, 5)}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), assumptions)
    decision = _decision(report)
    assert decision["verdict"] == "not_authorized" and decision["model_id"] is None
    assert _find(report, "model_c", "delinquency_30")["vs_baseline"]["beats"] is True
    assert _find(report, "model_c", "delinquency_60")["vs_baseline"]["beats"] is False
    assert "delinquency_60" in decision["reason"]


def test_margin_comes_from_the_assumptions(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30)}
    strict = {**assumptions, "promotion": {**assumptions["promotion"], "margin_cop_m": 1_000.0}}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), strict)
    decision = _decision(report)
    assert decision["verdict"] == "not_authorized"
    assert decision["reason_code"] == "does_not_beat_baseline"     # 60 M point difference <= 1,000 M margin


def test_point_difference_above_margin_with_a_wide_interval_is_insufficient_evidence(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30)}
    tight = {**assumptions, "promotion": {**assumptions["promotion"], "margin_cop_m": 59.0}}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), tight)
    vs = _find(report, "model_a", "delinquency_30")["vs_baseline"]
    assert vs["difference_cop_m"] > 59.0 >= vs["ci_low_cop_m"]
    assert vs["outcome"] == "insufficient_evidence" and vs["beats"] is False
    decision = _decision(report)
    assert decision["verdict"] == "not_authorized" and decision["reason_code"] == "insufficient_evidence"


def test_outcome_of_each_comparison(assumptions):
    models = {"baseline_rule": (15, 15), "model_c": (30, 5)}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), assumptions)
    assert _find(report, "model_c", "delinquency_30")["vs_baseline"]["outcome"] == "beats"
    assert _find(report, "model_c", "delinquency_60")["vs_baseline"]["outcome"] == "does_not_beat_baseline"
    assert _find(report, "model_c", "delinquency_30")["vs_baseline"]["confidence_level"] == 0.95
    assert _decision(report)["reason_code"] == "does_not_beat_baseline"


def test_authorized_decision_has_its_reason_code(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30)}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), assumptions)
    assert _decision(report)["reason_code"] == "authorized"


def test_without_an_evaluated_baseline_nothing_is_authorized(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30)}
    scores = _scores_long(models)
    scores = scores.drop(scores.index[(scores["model_id"] == "baseline_rule") & (scores["horizon_days"] == 60)][:1])
    report = evaluate_models(_labeled_delinquency(), scores, _gate2(*models), assumptions)
    decision = _decision(report)
    assert decision["verdict"] == "not_authorized" and decision["model_id"] is None
    assert decision["reason_code"] == "no_baseline"
    assert "baseline_rule" in decision["reason"]


def test_highest_net_value_is_recommended_and_close_runner_up_is_inconclusive(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30), "model_b": (30, 30), "model_d": (25, 25)}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), assumptions)
    decision = _decision(report)
    assert decision["model_id"] == "model_a"                       # ties go to the first model_id
    assert decision["also_beat_baseline"] == ["model_b", "model_d"]
    runner_up = decision["runner_up"]
    assert runner_up["model_id"] == "model_b" and runner_up["conclusive"] is False
    assert runner_up["ci_low_cop_m"] <= 0 <= runner_up["ci_high_cop_m"]
    assert "inconclusive" in decision["reason"]


def test_single_authorized_model_has_no_runner_up(assumptions):
    models = {"baseline_rule": (15, 15), "model_a": (30, 30)}
    report = evaluate_models(_labeled_delinquency(), _scores_long(models), _gate2(*models), assumptions)
    decision = _decision(report)
    assert decision["also_beat_baseline"] == [] and decision["runner_up"] is None


def test_decisions_never_mention_production(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    assert {d["target"] for d in report["decisions"]} == {"delinquency", "churn"}
    assert "production" not in json.dumps(report["decisions"]).lower()
    codes = {"authorized", "insufficient_evidence", "does_not_beat_baseline", "no_baseline", "no_candidate"}
    assert all(d["reason_code"] in codes for d in report["decisions"])


def test_synthetic_evaluations_carry_metrics(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    for e in report["evaluations"]:
        metrics = e["metrics"]
        assert 0 < metrics["pr_auc"] <= 1 and 0 <= metrics["brier"] <= 1
        assert all(cell["n_clients"] >= assumptions["evaluation"]["min_cell_clients"]
                   for cell in metrics["calibration"])
        assert {"precision", "recall", "lift"} <= set(e["at_k"]) and {"precision", "recall", "lift"} <= set(e["curve"][1])


def test_report_declares_the_promotion_assumptions(synthetic, assumptions):
    report = evaluate_models(*synthetic, assumptions)
    declared = report["assumptions"]
    assert declared["margin_cop_m"] == 0 and declared["bootstrap_samples"] == 500
    assert declared["bootstrap_seed"] == 42 and declared["confidence_level"] == 0.95
