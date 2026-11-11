"""Tests for configuration files, data contracts and assumptions (step 1)."""
from pathlib import Path

import pytest
import yaml

from src.predict360.config import (
    CONFIG_DIR,
    REQUIRED_CONFIG_KEYS,
    contract_columns,
    load_assumptions,
    load_config,
    load_contract,
)

DATA_TYPES = {"string", "date", "decimal", "integer", "binary"}
CARD_TYPES = DATA_TYPES | {"datetime", "list", "object"}
CONTRACTS = ["delinquency_v1", "churn_v1", "scores_v1", "model_card_v1"]


# --- synthetic.yaml / real.yaml -------------------------------------------

def test_synthetic_and_real_configs_load_with_same_top_level_keys():
    synthetic = load_config(CONFIG_DIR / "synthetic.yaml")
    real = load_config(CONFIG_DIR / "real.yaml")
    assert set(synthetic) == set(real)
    assert set(REQUIRED_CONFIG_KEYS) <= set(synthetic)
    assert synthetic["synthetic"] is True
    assert real["synthetic"] is False


def test_synthetic_config_reproduces_client_figures():
    cfg = load_config(CONFIG_DIR / "synthetic.yaml")
    assert cfg["seed"] == 42
    assert str(cfg["snapshot_date"]) == "2026-03-31"
    assert cfg["reconciliation"]["delinquency_expected_cop_m"] == 58800.0
    assert cfg["reconciliation"]["churn_expected_cop_m"] == 18200.0
    assert cfg["reconciliation"]["tolerance_cop_m"] == 0.01
    assert cfg["horizons_days"] == [30, 60, 90]
    assert cfg["hmac"]["key_env"] == "PREDICT360_HMAC_KEY"


def test_real_config_has_no_hmac_key_and_no_synthetic_flag():
    raw_text = (CONFIG_DIR / "real.yaml").read_text(encoding="utf-8")
    real = load_config(CONFIG_DIR / "real.yaml")
    assert "demo_key" not in real["hmac"]
    assert "synthetic: true" not in raw_text
    assert real["retention_days"] is None  # FinBank sets it, not us


def test_missing_required_key_raises_value_error(tmp_path):
    cfg = yaml.safe_load((CONFIG_DIR / "synthetic.yaml").read_text(encoding="utf-8"))
    del cfg["seed"]
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match="seed"):
        load_config(path)


def test_demo_key_is_rejected_in_a_non_synthetic_config(tmp_path):
    cfg = yaml.safe_load((CONFIG_DIR / "synthetic.yaml").read_text(encoding="utf-8"))
    cfg["synthetic"] = False
    path = tmp_path / "leaky.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match="demo_key"):
        load_config(path)


# --- contracts ------------------------------------------------------------

@pytest.mark.parametrize("name", CONTRACTS)
def test_contracts_load_with_version_v1_and_valid_types(name):
    contract = load_contract(name)
    assert contract["version"] == "v1"
    allowed = CARD_TYPES if name == "model_card_v1" else DATA_TYPES
    columns = contract_columns(name)
    assert columns
    for column in columns:
        spec = (contract.get("columns") or contract.get("fields"))[column]
        assert spec["type"] in allowed, f"{name}.{column}"


def test_delinquency_v1_columns_match_spec_section_6():
    assert contract_columns("delinquency_v1") == [
        "client_id", "snapshot_date", "exposure_cop_m", "weight",
        "origination_date", "utilization", "prior_late_12m", "max_dpd_12m",
        "tenure_months", "first_delinquency_date", "observation_end_date",
    ]


def test_churn_v1_columns_match_spec_section_6():
    assert contract_columns("churn_v1") == [
        "client_id", "snapshot_date", "exposure_cop_m", "weight",
        "tenure_months", "products_active", "cancellation_date",
        "observation_end_date",
    ]


def test_scores_v1_rules():
    contract = load_contract("scores_v1")
    cols = contract["columns"]
    assert contract_columns("scores_v1") == [
        "client_id", "model_id", "snapshot_date", "horizon_days", "score", "intervened",
    ]
    assert cols["horizon_days"]["allowed"] == [30, 60, 90]
    assert cols["score"]["min"] == 0 and cols["score"]["max"] == 1
    assert cols["score"]["required"] is True
    assert cols["score"]["max_null_pct"] == 0
    assert cols["intervened"]["type"] == "binary"
    assert cols["intervened"]["required"] is False


def test_data_contract_date_and_null_rules():
    dlq = load_contract("delinquency_v1")["columns"]
    assert dlq["client_id"]["unique"] is True
    assert dlq["origination_date"]["before"] == "snapshot_date"
    assert dlq["first_delinquency_date"]["after"] == "snapshot_date"
    assert dlq["observation_end_date"]["after"] == "snapshot_date"
    assert dlq["tenure_months"]["max_null_pct"] == 0.05
    churn = load_contract("churn_v1")["columns"]
    assert churn["cancellation_date"]["after"] == "snapshot_date"
    assert churn["tenure_months"]["max_null_pct"] == 0.05


def test_model_card_v1_fields_and_statuses():
    contract = load_contract("model_card_v1")
    assert contract["allowed_status"] == ["candidate", "shadow", "pilot", "approved", "retired"]
    for field in ["model_id", "target", "dataset_hash", "train_end_date",
                  "eval_start_date", "preprocessing_fit_on", "status", "approved_by"]:
        assert field in contract["fields"]


def test_unknown_contract_raises():
    with pytest.raises(FileNotFoundError):
        load_contract("does_not_exist_v9")


# --- assumptions ----------------------------------------------------------

def test_assumptions_has_twelve_typed_entries():
    data = load_assumptions(CONFIG_DIR / "assumptions.yaml")
    items = data["items"]
    assert len(items) == 12
    for item in items:
        assert {"id", "name", "value", "type", "rationale"} <= set(item)
        assert item["type"] in {"business", "design", "simulation"}


def test_illustrative_effectiveness_and_cost_are_simulation():
    values = load_assumptions(CONFIG_DIR / "assumptions.yaml")["values"]
    assert values["value"]["action_effectiveness"] == 0.40
    assert values["value"]["cost_per_contact_cop"] == 20000
    items = load_assumptions(CONFIG_DIR / "assumptions.yaml")["items"]
    simulated = [i for i in items if "value.action_effectiveness" in i["value"]]
    assert len(simulated) == 1 and simulated[0]["type"] == "simulation"
    assert all(i["type"] == "simulation" for i in items
               if "value.cost_per_contact_cop" in i["value"])


def test_assumption_values_match_team_decisions():
    values = load_assumptions(CONFIG_DIR / "assumptions.yaml")["values"]
    assert values["delinquency"] == {"dpd_threshold_days": 30, "horizons_days": [30, 60]}
    assert values["churn"]["horizon_days"] == 90
    assert values["churn"]["preferred_segment"] == "top_10pct_by_exposure"
    assert values["intervention"]["control_group_share"] == 0.05
    assert values["value"]["loss_given_event"] == 1.0
    assert values["value"]["default_capacity_share"] == 0.10
    assert values["reconciliation"]["tolerance_cop_m"] == 0.01
    assert values["retention"]["raw_retention_days"] is None
