"""Tests for Gate 2 (technical spec, section 9): model card admission and statuses."""
import json

import pytest

from src.predict360.config import CONFIG_DIR, ROOT, load_config
from src.predict360.make_synthetic import generate_synthetic_data
from src.predict360.model_card import admit_card, run_gate2, scores_sha256, transition

CONFIG = CONFIG_DIR / "synthetic.yaml"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"
CARDS_DIR = SYNTHETIC_DIR / "model_cards"
SCORES = SYNTHETIC_DIR / "scores_sample.csv"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG)


@pytest.fixture(scope="module")
def scores_hash():
    return scores_sha256(SCORES)


def _card(name="delinquency_model_a", **overrides):
    card = json.loads((CARDS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    card.update(overrides)
    return card


def _with_gate2(cfg, **gate2):
    return {**cfg, "gate2": {**cfg["gate2"], **gate2}}


def _reasons(result, severity=None):
    return {r["rule"] for r in result["reasons"] if severity is None or r["severity"] == severity}


# --- clean synthetic cards ------------------------------------------------------

def test_scores_hash_is_the_sha256_of_the_file(scores_hash):
    assert scores_hash == _card()["dataset_hash"]


def test_all_synthetic_cards_are_admitted_without_warnings(cfg):
    report = run_gate2(cfg, CARDS_DIR, SCORES)
    assert report["status"] == "PASS"
    assert len(report["cards"]) == 6
    assert {c["decision"] for c in report["cards"]} == {"ADMITTED"}
    assert all(c["reasons"] == [] for c in report["cards"])
    assert report["counts"] == {"ADMITTED": 6, "REJECTED": 0, "SKIPPED": 0}


def test_overlapping_split_defect_rejects_model_a(cfg, tmp_path, monkeypatch):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path, defect="overlapping_split")
    report = run_gate2(cfg, tmp_path / "model_cards", tmp_path / "scores_sample.csv")
    # Rejecting a card is the gate doing its job: the gate passes, the card carries REJECTED
    assert report["status"] == "PASS" and report["failures"] == []
    for card in report["cards"]:
        if card["model_id"] == "model_a":
            assert card["decision"] == "REJECTED"
            assert _reasons(card, "reject") == {"temporal_split"}
        else:
            assert card["decision"] == "ADMITTED"


# --- rejections ----------------------------------------------------------------------

def test_missing_field_rejects_as_incomplete(cfg, scores_hash):
    card = _card()
    del card["seed"]
    result = admit_card(card, scores_hash, cfg)
    assert result["decision"] == "REJECTED"
    assert "complete_card" in _reasons(result, "reject")
    assert any("seed" in r["message"] for r in result["reasons"])


@pytest.mark.parametrize("field,value", [
    ("status", "production"),
    ("target", "fraud"),
    ("seed", "42"),
    ("features", "utilization"),
    ("train_end_date", "2025-13-01"),
    ("dataset_hash", "not-a-hash"),
])
def test_invalid_field_rejects_as_incomplete(cfg, scores_hash, field, value):
    result = admit_card(_card(**{field: value}), scores_hash, cfg)
    assert result["decision"] == "REJECTED"
    assert "complete_card" in _reasons(result, "reject")


def test_different_scores_hash_is_not_traceable(cfg):
    result = admit_card(_card(), "0" * 64, cfg)
    assert result["decision"] == "REJECTED"
    assert _reasons(result, "reject") == {"traceable"}


def test_snapshot_different_from_run_cut_off_is_not_traceable(cfg, scores_hash):
    result = admit_card(_card(snapshot_date="2026-02-28"), scores_hash, cfg)
    assert result["decision"] == "REJECTED"
    assert _reasons(result, "reject") == {"traceable"}


@pytest.mark.parametrize("train_end", ["2026-03-31", "2026-04-15"])
def test_train_end_not_before_eval_start_rejects(cfg, scores_hash, train_end):
    result = admit_card(_card(train_end_date=train_end), scores_hash, cfg)
    assert _reasons(result, "reject") == {"temporal_split"}


def test_preprocessing_not_fitted_on_train_only_is_possible_leakage(cfg, scores_hash):
    card = _card(preprocessing_fit_on="all_data")
    result = admit_card(card, scores_hash, cfg)
    assert result["decision"] == "REJECTED"
    assert "preprocessing_train_only" in _reasons(result, "reject")


@pytest.mark.parametrize("status", ["shadow", "pilot", "approved"])
def test_card_beyond_candidate_without_approver_is_rejected(cfg, scores_hash, status):
    rejected = admit_card(_card(status=status), scores_hash, cfg)
    assert rejected["decision"] == "REJECTED"
    assert _reasons(rejected, "reject") == {"status_backed"}
    backed = admit_card(_card(status=status, approved_by="FinBank risk committee"), scores_hash, cfg)
    assert backed["decision"] == "ADMITTED"


def test_retired_card_is_skipped_not_rejected(cfg, scores_hash):
    result = admit_card(_card(status="retired", approved_by="FinBank"), scores_hash, cfg)
    assert result["decision"] == "SKIPPED"
    assert result["reasons"] == [{"rule": "status", "severity": "skip", "message": "retired"}]


def test_retired_card_in_gate2_counts_as_skipped(cfg, tmp_path):
    for path in CARDS_DIR.glob("*.json"):
        card = json.loads(path.read_text(encoding="utf-8"))
        if path.stem == "churn_model_b":
            card.update(status="retired", approved_by="FinBank")
        (tmp_path / path.name).write_text(json.dumps(card), encoding="utf-8")
    report = run_gate2(cfg, tmp_path, SCORES)
    assert report["status"] == "PASS"
    assert report["counts"] == {"ADMITTED": 5, "REJECTED": 0, "SKIPPED": 1}


def _cards_in(tmp_path, change=None):
    for path in CARDS_DIR.glob("*.json"):
        card = json.loads(path.read_text(encoding="utf-8"))
        if change:
            change(path.stem, card)
        (tmp_path / path.name).write_text(json.dumps(card), encoding="utf-8")
    return tmp_path


def test_gate2_fails_when_the_baseline_of_a_target_is_not_admitted(cfg, tmp_path):
    def reject_churn_baseline(stem, card):
        if stem == "churn_baseline_rule":
            del card["seed"]
    report = run_gate2(cfg, _cards_in(tmp_path, reject_churn_baseline), SCORES)
    assert report["status"] == "FAIL"
    assert len(report["failures"]) == 1
    assert "baseline_rule" in report["failures"][0] and "churn" in report["failures"][0]


def test_gate2_fails_when_it_cannot_run(cfg, tmp_path):
    assert run_gate2(cfg, tmp_path, SCORES)["status"] == "FAIL"                 # no cards
    missing = run_gate2(cfg, CARDS_DIR, tmp_path / "missing_scores.csv")        # no scores file
    assert missing["status"] == "FAIL" and missing["failures"]


# --- warnings and strict rules -------------------------------------------------------

def test_missing_intervention_handling_is_a_warning(cfg, scores_hash):
    result = admit_card(_card(intervention_handling=""), scores_hash, cfg)
    assert result["decision"] == "ADMITTED"
    assert _reasons(result, "warning") == {"intervention_declared"}


def test_intervention_handling_field_must_still_exist(cfg, scores_hash):
    card = _card()
    del card["intervention_handling"]
    assert _reasons(admit_card(card, scores_hash, cfg), "reject") == {"complete_card"}


@pytest.mark.parametrize("baselines", [["baseline_rule"], ["random"], []])
def test_baselines_must_include_random_and_a_heuristic_rule(cfg, scores_hash, baselines):
    result = admit_card(_card(baselines_compared=baselines), scores_hash, cfg)
    assert result["decision"] == "ADMITTED"
    assert _reasons(result, "warning") == {"baselines_compared"}


def test_baseline_model_is_exempt_from_comparing_against_itself(cfg, scores_hash):
    card = _card("delinquency_baseline_rule")
    assert card["baselines_compared"] == ["random"]
    assert admit_card(card, scores_hash, cfg)["reasons"] == []


def test_baseline_exemption_comes_from_the_config_not_the_name(cfg, scores_hash):
    card = _card("delinquency_baseline_rule")
    renamed = _with_gate2(cfg, baseline_models=["finbank_rule"])
    assert _reasons(admit_card(card, scores_hash, renamed), "warning") == {"baselines_compared"}
    other = _card(baselines_compared=["random", "finbank_rule"])
    assert admit_card(other, scores_hash, renamed)["reasons"] == []


@pytest.mark.parametrize("rule,overrides", [
    ("intervention_declared", {"intervention_handling": ""}),
    ("baselines_compared", {"baselines_compared": ["random"]}),
])
def test_strict_rule_turns_the_warning_into_a_rejection(cfg, scores_hash, rule, overrides):
    result = admit_card(_card(**overrides), scores_hash, _with_gate2(cfg, strict_rules=[rule]))
    assert result["decision"] == "REJECTED"
    assert _reasons(result, "reject") == {rule}


# --- statuses ------------------------------------------------------------------------

def test_status_advances_one_step_with_its_evidence():
    card = _card()
    shadow = transition(card, "shadow", {"beats_baselines": True, "approved_by": "PCM committee"})
    assert shadow["status"] == "shadow" and shadow["approved_by"] == "PCM committee"
    assert card["status"] == "candidate"  # the input card is not modified
    pilot = transition(shadow, "pilot", {"shadow_report": "runs/x/shadow.json", "approved_by": "FinBank"})
    approved = transition(pilot, "approved", {"control_effectiveness": 0.38, "approved_by": "FinBank"})
    assert approved["status"] == "approved"


@pytest.mark.parametrize("current,target", [
    ("candidate", "pilot"), ("candidate", "approved"), ("shadow", "approved"), ("shadow", "candidate"),
])
def test_status_cannot_skip_or_go_back(current, target):
    evidence = {"beats_baselines": True, "shadow_report": "x", "control_effectiveness": 0.4,
                "approved_by": "FinBank"}
    with pytest.raises(ValueError, match="transition"):
        transition(_card(status=current, approved_by="FinBank"), target, evidence)


@pytest.mark.parametrize("evidence", [
    {"approved_by": "PCM committee"},                            # no evidence
    {"beats_baselines": False, "approved_by": "PCM committee"},  # evidence says no
    {"beats_baselines": True},                                   # nobody approved it
])
def test_status_does_not_advance_without_evidence_and_approver(evidence):
    with pytest.raises(ValueError):
        transition(_card(), "shadow", evidence)


def test_any_status_can_be_retired_with_a_reason_and_retired_is_final():
    retired = transition(_card(status="pilot", approved_by="FinBank"), "retired",
                         {"reason": "drift", "approved_by": "FinBank"})
    assert retired["status"] == "retired"
    with pytest.raises(ValueError):
        transition(_card(), "retired", {"approved_by": "FinBank"})  # no reason
    with pytest.raises(ValueError, match="transition"):
        transition(retired, "candidate", {"approved_by": "FinBank"})
