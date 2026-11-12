"""Tests for Gate 1 (technical spec, sections 6 and 8): contract-driven data validation."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import date

import pandas as pd
import pytest

from src.predict360 import quality
from src.predict360.config import CONFIG_DIR, ROOT, load_config
from src.predict360.make_synthetic import generate_synthetic_data
from src.predict360.quality import REPORT_RESULT_KEYS, run_gate1, validate_table

CONFIG = CONFIG_DIR / "synthetic.yaml"
T = "2026-03-31"
AS_OF = date(2026, 11, 11)


def _hex(i):
    return hashlib.sha256(f"id-{i}".encode()).hexdigest()


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG)


@pytest.fixture(scope="module")
def clean_dir(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("PREDICT360_HMAC_KEY", raising=False)
        out = tmp_path_factory.mktemp("clean")
        generate_synthetic_data(config=CONFIG, output_dir=out)
    return out


@pytest.fixture(scope="module")
def clean_report(cfg, clean_dir):
    return run_gate1(cfg, data_dir=clean_dir, as_of=AS_OF)


def _defect_dir(tmp_path, monkeypatch, defect):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path, defect=defect)
    return tmp_path


def _failed(result):
    return [r for r in result["results"] if not r["success"]]


def _delinquency_df(n=40):
    return pd.DataFrame({
        "client_id": [_hex(i) for i in range(n)],
        "snapshot_date": [T] * n,
        "exposure_cop_m": [100.0 + i for i in range(n)],
        "weight": [250.0] * n,
        "origination_date": ["2025-01-15"] * n,
        "utilization": [0.5] * n,
        "prior_late_12m": [0] * n,
        "max_dpd_12m": [0] * n,
        "tenure_months": [24] * n,
        "first_delinquency_date": [None] * (n - 1) + ["2026-04-20"],
        "observation_end_date": ["2026-07-31"] * n,
    })


def _scores_df(n=40):
    return pd.DataFrame({
        "client_id": [_hex(i) for i in range(n)],
        "model_id": ["model_a"] * n,
        "snapshot_date": [T] * n,
        "horizon_days": [30] * n,
        "score": [0.5] * n,
        "intervened": [0] * n,
    })


def _rule(result, rule, column):
    matches = [r for r in result["results"] if r["rule"] == rule and r["column"] == column]
    assert matches, f"rule {rule} on {column} not evaluated"
    return matches[0]


# --- configuration ----------------------------------------------------------

def test_configs_declare_sources_and_waivers():
    synthetic = load_config(CONFIG_DIR / "synthetic.yaml")
    real = load_config(CONFIG_DIR / "real.yaml")
    for cfg in (synthetic, real):
        assert set(cfg["sources"]) == {"delinquency", "churn", "scores"}
    assert real["waivers"] == []
    (w01,) = synthetic["waivers"]
    assert w01["id"] == "W-01"
    assert w01["table"] == "churn" and w01["column"] == "tenure_months"
    assert w01["rule"] == "expect_column_values_to_not_be_null"
    assert w01["risk"] == "R-01"
    assert w01["approved_by"] == "Cristian Vega (Project Leader)"
    assert str(w01["date"]) == "2026-11-11" and str(w01["expires"]) == "2026-12-31"


def test_legacy_audit_source_is_marked_as_superseded():
    assert "Legacy (Sprint 1, US-03). Superseded by validate_table / run_gate1" in quality.audit_source.__doc__


# --- clean synthetic data -----------------------------------------------------

def test_clean_data_passes_with_the_r01_waiver(clean_report):
    tables = clean_report["tables"]
    assert tables["delinquency"]["status"] == "PASS"
    assert tables["scores"]["status"] == "PASS"
    assert tables["churn"]["status"] == "PASS_WITH_WAIVERS"
    assert tables["churn"]["waivers_applied"] == ["W-01"]
    assert clean_report["status"] == "PASS_WITH_WAIVERS"
    assert clean_report["waivers_applied"] == ["W-01"]


def test_churn_without_waiver_fails_on_tenure_nulls(cfg, clean_dir):
    report = run_gate1({**cfg, "waivers": []}, data_dir=clean_dir, as_of=AS_OF)
    churn = report["tables"]["churn"]
    assert churn["status"] == "FAIL" and report["status"] == "FAIL"
    (failed,) = _failed(churn)
    assert failed["rule"] == "expect_column_values_to_not_be_null"
    assert failed["column"] == "tenure_months"
    assert failed["critical"] is False
    assert failed["unexpected_count"] == 24 and failed["unexpected_pct"] == 12.0
    assert churn["missing"]["tenure_months"] == {"count": 24, "pct": 12.0, "limit_pct": 5.0}


def test_expired_waiver_is_ignored(cfg, clean_dir):
    report = run_gate1(cfg, data_dir=clean_dir, as_of=date(2027, 1, 1))
    churn = report["tables"]["churn"]
    assert churn["status"] == "FAIL"
    assert churn["waivers_applied"] == []
    assert {"id": "W-01", "reason": "expired"} in churn["waivers_ignored"]


# --- defective files ------------------------------------------------------------

@pytest.mark.parametrize("defect,table,rule,column", [
    ("critical_nulls", "delinquency", "expect_column_values_to_not_be_null", "observation_end_date"),
    ("schema", "delinquency", "expect_table_columns_to_match_set", None),
    ("duplicate_ids", "delinquency", "expect_column_values_to_be_unique", "client_id"),
    ("score_out_of_range", "scores", "expect_column_values_to_be_between", "score"),
])
def test_each_data_defect_is_rejected_by_the_right_rule(cfg, tmp_path, monkeypatch, defect, table, rule, column):
    report = run_gate1(cfg, data_dir=_defect_dir(tmp_path, monkeypatch, defect), as_of=AS_OF)
    assert report["status"] == "FAIL"
    assert report["tables"][table]["status"] == "FAIL"
    failed = _rule(report["tables"][table], rule, column)
    assert failed["success"] is False and failed["critical"] is True


def test_missing_source_file_fails(cfg, clean_dir, tmp_path):
    for name in ("delinquency_sample.csv", "churn_sample.csv"):
        (tmp_path / name).write_bytes((clean_dir / name).read_bytes())
    report = run_gate1(cfg, data_dir=tmp_path, as_of=AS_OF)
    assert report["status"] == "FAIL"
    assert _rule(report["tables"]["scores"], "expect_file_to_exist", None)["success"] is False


# --- rules, one by one ------------------------------------------------------------

def test_valid_small_tables_pass():
    assert validate_table(_delinquency_df(), "delinquency_v1", T)["status"] == "PASS"
    assert validate_table(_scores_df(), "scores_v1", T)["status"] == "PASS"


def test_empty_table_fails():
    result = validate_table(_delinquency_df().iloc[0:0], "delinquency_v1", T)
    assert result["status"] == "FAIL"
    assert _rule(result, "expect_table_row_count_to_be_between", None)["success"] is False


def test_exposure_must_be_strictly_positive():
    df = _delinquency_df()
    df.loc[0, "exposure_cop_m"] = 0.0
    result = validate_table(df, "delinquency_v1", T)
    rule = _rule(result, "expect_column_values_to_be_between", "exposure_cop_m")
    assert rule["success"] is False and rule["unexpected_count"] == 1
    assert result["status"] == "FAIL"


def test_integer_with_nulls_read_as_float_is_still_integer():
    df = _delinquency_df()
    df["tenure_months"] = [24.0] * 39 + [float("nan")]  # 2.5% nulls, under the 5% limit
    result = validate_table(df, "delinquency_v1", T)
    assert _rule(result, "expect_column_values_to_be_of_type", "tenure_months")["success"] is True
    df.loc[1, "tenure_months"] = 24.5
    result = validate_table(df, "delinquency_v1", T)
    assert _rule(result, "expect_column_values_to_be_of_type", "tenure_months")["success"] is False


def test_text_in_a_decimal_column_fails_type():
    df = _delinquency_df()
    df["utilization"] = df["utilization"].astype(object)
    df.loc[0, "utilization"] = "wrong"
    result = validate_table(df, "delinquency_v1", T)
    assert _rule(result, "expect_column_values_to_be_of_type", "utilization")["unexpected_count"] == 1


def test_invalid_calendar_date_fails_type():
    df = _delinquency_df()
    df.loc[0, "origination_date"] = "2026-02-30"
    result = validate_table(df, "delinquency_v1", T)
    assert _rule(result, "expect_column_values_to_be_of_type", "origination_date")["success"] is False


def test_dates_must_respect_the_cut_off():
    df = _delinquency_df()
    df.loc[0, "origination_date"] = "2026-05-01"      # must be before T
    df.loc[1, "observation_end_date"] = "2026-03-31"  # must be after T
    result = validate_table(df, "delinquency_v1", T)
    rule = "expect_column_pair_values_a_to_be_greater_than_b"
    assert _rule(result, rule, "origination_date")["unexpected_count"] == 1
    assert _rule(result, rule, "observation_end_date")["unexpected_count"] == 1
    assert result["status"] == "FAIL"


@pytest.mark.parametrize("contract,make_df", [
    ("delinquency_v1", _delinquency_df), ("scores_v1", _scores_df),
])
def test_raw_identifier_passes_because_hashing_happens_at_curate(contract, make_df):
    # Gate 1 validates RAW: inside the bank, client_id is the original identifier
    df = make_df()
    df["client_id"] = [f"CLI-{i:06d}" for i in range(123, 123 + len(df))]
    result = validate_table(df, contract, T)
    assert result["status"] == "PASS"
    assert not any(r["rule"] == "expect_column_values_to_match_regex" for r in result["results"])


def test_raw_identifier_must_still_be_present_and_unique():
    df = _delinquency_df()
    df.loc[0, "client_id"] = "CLI-000123"
    df.loc[1, "client_id"] = "CLI-000123"
    df.loc[2, "client_id"] = None
    result = validate_table(df, "delinquency_v1", T)
    assert _rule(result, "expect_column_values_to_be_unique", "client_id")["unexpected_count"] == 2
    assert _rule(result, "expect_column_values_to_not_be_null", "client_id")["unexpected_count"] == 1
    assert result["status"] == "FAIL"


def test_extra_column_is_a_minimization_warning_not_a_failure():
    df = _delinquency_df()
    df["national_id"] = "x"
    result = validate_table(df, "delinquency_v1", T)
    schema = _rule(result, "expect_table_columns_to_match_set", None)
    assert schema["success"] is True
    assert schema["extra_columns"] == ["national_id"]
    assert result["status"] == "PASS"


def test_scores_horizon_binary_and_snapshot_rules():
    df = _scores_df()
    df.loc[0, "horizon_days"] = 45
    df.loc[1, "intervened"] = 2
    df.loc[2, "snapshot_date"] = "2026-04-30"
    result = validate_table(df, "scores_v1", T)
    assert _rule(result, "expect_column_values_to_be_in_set", "horizon_days")["unexpected_count"] == 1
    assert _rule(result, "expect_column_values_to_be_of_type", "intervened")["unexpected_count"] == 1
    assert _rule(result, "expect_column_values_to_equal_run_snapshot", "snapshot_date")["unexpected_count"] == 1
    assert result["status"] == "FAIL"


# --- waivers ----------------------------------------------------------------------

def _w01(**overrides):
    waiver = {"id": "W-01", "table": "delinquency", "column": "tenure_months",
              "rule": "expect_column_values_to_not_be_null", "risk": "R-01",
              "reason": "test", "approved_by": "tester", "date": "2026-11-11",
              "expires": "2026-12-31"}
    return {**waiver, **overrides}


def _too_many_tenure_nulls():
    df = _delinquency_df()
    df["tenure_months"] = [None] * 4 + [24.0] * 36  # 10% > 5%
    return df


def test_waiver_covers_only_its_table_column_and_rule():
    df = _too_many_tenure_nulls()
    assert validate_table(df, "delinquency_v1", T, table="delinquency", waivers=[_w01()],
                          as_of=AS_OF)["status"] == "PASS_WITH_WAIVERS"
    for other in (_w01(table="churn"), _w01(column="utilization"),
                  _w01(rule="expect_column_values_to_be_between")):
        result = validate_table(df, "delinquency_v1", T, table="delinquency",
                                waivers=[other], as_of=AS_OF)
        assert result["status"] == "FAIL", other


def test_waiver_never_covers_a_critical_column():
    df = _delinquency_df()
    df.loc[0, "observation_end_date"] = None
    waiver = _w01(column="observation_end_date")
    result = validate_table(df, "delinquency_v1", T, table="delinquency", waivers=[waiver], as_of=AS_OF)
    assert result["status"] == "FAIL"
    assert {"id": "W-01", "reason": "critical"} in result["waivers_ignored"]


# --- report privacy -----------------------------------------------------------------

def test_report_has_only_counts_never_row_values(cfg, tmp_path, monkeypatch):
    data = _defect_dir(tmp_path, monkeypatch, "score_out_of_range")
    report = run_gate1(cfg, data_dir=data, as_of=AS_OF)
    text = json.dumps(report, default=str)
    ids = set(pd.read_csv(data / "delinquency_sample.csv")["client_id"])
    ids |= set(pd.read_csv(data / "churn_sample.csv")["client_id"])
    assert not any(client_id in text for client_id in ids)
    assert "1.25" not in text and "-0.1" not in text  # the injected out-of-range scores
    for table in report["tables"].values():
        for result in table["results"]:
            assert set(result) <= REPORT_RESULT_KEYS, set(result) - REPORT_RESULT_KEYS


# --- CLI ----------------------------------------------------------------------------

def _cli(*args):
    env = {k: v for k, v in os.environ.items() if k != "PREDICT360_HMAC_KEY"}
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "src.predict360.quality", "--config", str(CONFIG),
                           "--as-of", AS_OF.isoformat(), *args],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_cli_writes_to_output_dir_and_exits_zero_on_pass(clean_dir, tmp_path):
    out, evidence = tmp_path / "adhoc", tmp_path / "evidence"
    proc = _cli("--data-dir", str(clean_dir), "--output-dir", str(out), "--evidence-dir", str(evidence))
    assert proc.returncode == 0, proc.stderr
    report = json.loads((out / "gate1_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS_WITH_WAIVERS"
    assert (out / "gate1_report.md").exists()
    assert not evidence.exists()  # only copied with --evidence


def test_cli_copies_to_evidence_only_when_asked(clean_dir, tmp_path):
    out, evidence = tmp_path / "adhoc", tmp_path / "evidence"
    proc = _cli("--data-dir", str(clean_dir), "--output-dir", str(out),
                "--evidence", "--evidence-dir", str(evidence))
    assert proc.returncode == 0, proc.stderr
    assert (evidence / "gate1_report.json").exists() and (evidence / "gate1_report.md").exists()


def test_cli_exits_non_zero_when_gate_fails(tmp_path, monkeypatch):
    data = _defect_dir(tmp_path / "data", monkeypatch, "duplicate_ids")
    proc = _cli("--data-dir", str(data), "--output-dir", str(tmp_path / "adhoc"))
    assert proc.returncode != 0
    assert "FAIL" in proc.stdout


def test_cli_default_output_is_runs_adhoc():
    assert quality.DEFAULT_OUTPUT_DIR == ROOT / "runs" / "adhoc"
