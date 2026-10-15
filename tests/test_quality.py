"""Pruebas sencillas para US-03 P1 (primero RED, luego GREEN)."""
import pandas as pd

from src.predict360.quality import audit_source, audit_csv, export_quality_report


def _delinquency():
    return pd.DataFrame({
        "client_hash_id": ["CLI_1", "CLI_2"],
        "days_past_due": [0, 30],
        "risk_score": [0.2, 0.8],
        "client_balance_cop_m": [2.5, 3.0],
        "client_exposure_cop_m": [1.0, 2.0],
        "sampling_weight": [250.0, 250.0],
        "exposure_cop_m": [250.0, 500.0],
    })


def _churn(n=200, missing=0):
    df = pd.DataFrame({
        "client_hash_id": [f"PREF_{i}" for i in range(n)],
        "tenure_months": [12.0] * n,
        "churn_probability": [0.3] * n,
        "client_exposure_cop_m": [2.0] * n,
        "sampling_weight": [62.5] * n,
        "exposure_cop_m": [125.0] * n,
    })
    if missing:
        df.loc[:missing-1, "tenure_months"] = float("nan")
    return df


def test_valid_delinquency_passes():
    assert audit_source(_delinquency(), "delinquency")["status"] == "PASS"


def test_churn_12_percent_missing_tenure_fails():
    result = audit_source(_churn(200, missing=24), "churn")
    assert result["status"] == "FAIL"
    assert result["missing"]["tenure_months"]["count"] == 24
    assert result["missing"]["tenure_months"]["pct"] == 12.0


def test_tenure_at_five_percent_is_accepted():
    result = audit_source(_churn(200, missing=10), "churn")
    assert result["status"] == "PASS"


def test_missing_client_id_always_fails():
    df = _delinquency()
    df.loc[0, "client_hash_id"] = None
    assert audit_source(df, "delinquency")["status"] == "FAIL"


def test_delinquency_risk_score_out_of_range_fails():
    df = _delinquency()
    df.loc[0, "risk_score"] = 1.5
    result = audit_source(df, "delinquency")
    assert result["out_of_range"]["risk_score"] == 1
    assert result["status"] == "FAIL"


def test_churn_probability_out_of_range_fails():
    df = _churn(2)
    df.loc[0, "churn_probability"] = -0.2
    assert audit_source(df, "churn")["out_of_range"]["churn_probability"] == 1


def test_invalid_numeric_data_type_fails():
    df = _delinquency()
    df.loc[0, "risk_score"] = "wrong"
    result = audit_source(df, "delinquency")
    assert result["status"] == "FAIL"
    assert result["invalid_types"]["risk_score"] == 1


def test_missing_required_column_fails():
    result = audit_source(_delinquency().drop(columns="risk_score"), "delinquency")
    assert "risk_score" in result["missing_columns"]
    assert result["status"] == "FAIL"


def test_blank_identifier_is_missing():
    df = _delinquency()
    df.loc[0, "client_hash_id"] = "   "
    assert audit_source(df, "delinquency")["status"] == "FAIL"


def test_csv_and_markdown_report(tmp_path):
    # Tres fuentes mínimas con el mismo esquema del repositorio.
    pd.DataFrame({
        "story_id": ["US-03-P1"], "title": ["Quality"],
        "domain": ["Data"], "exposure_type": ["umbrella"],
        "exposure_cop_m": [77000.0], "sp": [5], "sprint": [1],
    }).to_csv(tmp_path / "backlog.csv", index=False)
    _delinquency().to_csv(tmp_path / "delinquency_sample.csv", index=False)
    _churn(200, missing=24).to_csv(tmp_path / "churn_sample.csv", index=False)
    assert audit_csv(tmp_path / "delinquency_sample.csv", "delinquency")["status"] == "PASS"
    report = tmp_path / "report.md"
    results = export_quality_report(tmp_path, report)
    assert [r["status"] for r in results] == ["PASS", "PASS", "FAIL"]
    assert report.exists()
    assert "12.00%" in report.read_text(encoding="utf-8")
