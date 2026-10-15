"""Tests simples para US-04 P1 (primero RED, luego GREEN)."""
import pandas as pd
import pytest

from src.predict360.reconcile import reconcile_exposure, reconcile_csv, export_reconciliation_report


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
