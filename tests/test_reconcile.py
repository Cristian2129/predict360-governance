"""Tests simples para US-04 P1 (primero RED, luego GREEN)."""
import pandas as pd
import pytest

from src.predict360.config import CONFIG_DIR, ROOT, load_config
from src.predict360.make_synthetic import generate_synthetic_data
from src.predict360.reconcile import (
    reconcile_all,
    reconcile_csv,
    reconcile_exposure,
    export_reconciliation_report,
)

CONFIG = CONFIG_DIR / "synthetic.yaml"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"


def test_exact_exposure_passes():
    df = pd.DataFrame({"exposure_cop_m": [30000.0, 28800.0]})
    result = reconcile_exposure(df)
    assert result["actual_cop_m"] == 58800.0
    assert result["status"] == "PASS"


def test_wrong_exposure_fails():
    result = reconcile_exposure(pd.DataFrame({"exposure_cop_m": [50000.0]}))
    assert result["status"] == "FAIL"


def test_within_tolerance_passes():
    df = pd.DataFrame({"exposure_cop_m": [58800.005]})
    assert reconcile_exposure(df)["status"] == "PASS"


def test_missing_column_raises_value_error():
    with pytest.raises(ValueError):
        reconcile_exposure(pd.DataFrame({"other": [1.0]}))


def test_negative_exposure_raises_value_error():
    with pytest.raises(ValueError):
        reconcile_exposure(pd.DataFrame({"exposure_cop_m": [-1.0, 58801.0]}))


def test_empty_exposure_raises_value_error():
    with pytest.raises(ValueError):
        reconcile_exposure(pd.DataFrame({"exposure_cop_m": []}))


def test_csv_and_evidence(tmp_path):
    csv = tmp_path / "delinquency.csv"
    md = tmp_path / "reconciliation.md"
    pd.DataFrame({"exposure_cop_m": [600.0, 58200.0]}).to_csv(csv, index=False)
    assert reconcile_csv(csv)["status"] == "PASS"
    assert export_reconciliation_report(csv, md)["status"] == "PASS"
    assert "58,800.00M" in md.read_text(encoding="utf-8")


# --- B6: churn reconciliation, expected figures from the config ----------------

def _synthetic(name):
    return pd.read_csv(SYNTHETIC_DIR / f"{name}_sample.csv")


def test_both_portfolios_reconcile_on_synthetic_data():
    result = reconcile_all(load_config(CONFIG), _synthetic("delinquency"), _synthetic("churn"))
    assert result["status"] == "PASS"
    assert result["tables"]["delinquency"]["expected_cop_m"] == 58800.0
    assert result["tables"]["churn"]["expected_cop_m"] == 18200.0
    assert result["tables"]["churn"]["actual_cop_m"] == pytest.approx(18200.0, abs=0.01)
    assert result["tables"]["churn"]["status"] == "PASS"


def test_each_portfolio_is_checked_against_its_own_figure():
    # Swapping the tables must fail both: churn is never compared with 58,800M
    result = reconcile_all(load_config(CONFIG), _synthetic("churn"), _synthetic("delinquency"))
    assert result["tables"]["delinquency"]["status"] == "FAIL"
    assert result["tables"]["churn"]["status"] == "FAIL"
    assert result["status"] == "FAIL"


def test_expected_figures_and_tolerance_come_from_the_config():
    cfg = load_config(CONFIG)
    cfg = {**cfg, "reconciliation": {**cfg["reconciliation"], "churn_expected_cop_m": 18000.0}}
    result = reconcile_all(cfg, _synthetic("delinquency"), _synthetic("churn"))
    assert result["tables"]["churn"]["expected_cop_m"] == 18000.0
    assert result["tables"]["churn"]["status"] == "FAIL"
    assert result["tables"]["delinquency"]["status"] == "PASS"
    assert result["tables"]["churn"]["tolerance_cop_m"] == cfg["reconciliation"]["tolerance_cop_m"]


def test_exposure_mismatch_defect_fails_delinquency_only(tmp_path, monkeypatch):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path, defect="exposure_mismatch")
    result = reconcile_all(load_config(CONFIG),
                           pd.read_csv(tmp_path / "delinquency_sample.csv"),
                           pd.read_csv(tmp_path / "churn_sample.csv"))
    assert result["status"] == "FAIL"
    assert result["tables"]["delinquency"]["status"] == "FAIL"
    assert result["tables"]["delinquency"]["difference_cop_m"] == pytest.approx(150.0)
    assert result["tables"]["churn"]["status"] == "PASS"
