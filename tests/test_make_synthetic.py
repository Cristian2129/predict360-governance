"""Tests for make_synthetic v2 (technical spec, section 7). Everything writes to tmp_path."""
import hashlib
import json
import re

import numpy as np
import pandas as pd
import pytest

from src.predict360.config import CONFIG_DIR, contract_columns, load_config
from src.predict360.make_synthetic import DEFECTS, _offset_dates, generate_synthetic_data
from src.predict360.reconcile import reconcile_exposure

CONFIG = CONFIG_DIR / "synthetic.yaml"
CSV_FILES = ["backlog.csv", "delinquency_sample.csv", "churn_sample.csv", "scores_sample.csv"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_written_files(folder):
    return sorted(p for p in folder.rglob("*") if p.is_file())


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG)


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("PREDICT360_HMAC_KEY", raising=False)
        out = tmp_path_factory.mktemp("clean")
        result = generate_synthetic_data(config=CONFIG, output_dir=out)
    dates = ["snapshot_date", "origination_date", "first_delinquency_date", "observation_end_date"]
    return {
        "dir": out,
        "result": result,
        "dlq": pd.read_csv(out / "delinquency_sample.csv", parse_dates=dates),
        "churn": pd.read_csv(out / "churn_sample.csv",
                             parse_dates=["snapshot_date", "cancellation_date", "observation_end_date"]),
        "scores": pd.read_csv(out / "scores_sample.csv", parse_dates=["snapshot_date"]),
    }


def _generate_defect(tmp_path, defect, monkeypatch):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path, defect=defect)
    return tmp_path


# --- reproducibility ------------------------------------------------------

def test_same_seed_gives_byte_identical_files(clean, tmp_path, monkeypatch):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path)
    first = {p.relative_to(clean["dir"]): _sha256(p) for p in _all_written_files(clean["dir"])}
    second = {p.relative_to(tmp_path): _sha256(p) for p in _all_written_files(tmp_path)}
    assert first == second
    assert len(first) == len(CSV_FILES) + 6  # 6 model cards


def test_backlog_is_unchanged(clean):
    backlog = pd.read_csv(clean["dir"] / "backlog.csv")
    assert list(backlog.columns) == ["story_id", "title", "domain", "exposure_type",
                                     "exposure_cop_m", "sp", "sprint"]
    assert len(backlog) == 11


# --- exposure and weights -------------------------------------------------

def test_exposure_reconciles_with_client_figures(clean, cfg):
    tol = cfg["reconciliation"]["tolerance_cop_m"]
    dlq = reconcile_exposure(clean["dlq"], expected=58800.0, tolerance=tol)
    churn = reconcile_exposure(clean["churn"], expected=18200.0, tolerance=tol)
    assert dlq["status"] == "PASS" and churn["status"] == "PASS"


def test_rows_weights_and_positive_exposure(clean):
    dlq, churn = clean["dlq"], clean["churn"]
    assert len(dlq) == 500 and (dlq["weight"] == 250.0).all()
    assert len(churn) == 200 and (churn["weight"] == 62.5).all()
    assert dlq["weight"].sum() == 125000 and churn["weight"].sum() == 12500
    assert (dlq["exposure_cop_m"] > 0).all() and (churn["exposure_cop_m"] > 0).all()


def test_exposure_is_heavy_tailed(clean):
    exp = clean["dlq"]["exposure_cop_m"]
    assert exp.mean() > exp.median() * 1.2  # right skew: many small loans, few large ones


# --- contracts ------------------------------------------------------------

def test_columns_match_contracts_exactly(clean):
    assert list(clean["dlq"].columns) == contract_columns("delinquency_v1")
    assert list(clean["churn"].columns) == contract_columns("churn_v1")
    assert list(clean["scores"].columns) == contract_columns("scores_v1")


def test_contract_ranges_hold_on_clean_data(clean):
    dlq = clean["dlq"]
    assert dlq["utilization"].between(0, 1.5).all()
    assert (dlq["prior_late_12m"] >= 0).all() and (dlq["max_dpd_12m"] >= 0).all()
    assert dlq["tenure_months"].isna().mean() <= 0.05
    assert (clean["churn"]["products_active"] >= 1).all()


def test_churn_tenure_missing_is_exactly_12_percent(clean):
    assert clean["churn"]["tenure_months"].isna().mean() == pytest.approx(0.12)


# --- pseudonymization -----------------------------------------------------

def test_client_ids_are_unique_sha256_hex(clean):
    for df in (clean["dlq"], clean["churn"]):
        assert df["client_id"].is_unique
        assert df["client_id"].map(lambda v: bool(HEX64.match(v))).all()
    assert set(clean["scores"]["client_id"]) <= (set(clean["dlq"]["client_id"])
                                                 | set(clean["churn"]["client_id"]))


def test_no_raw_identifier_is_written_to_disk(clean):
    for path in _all_written_files(clean["dir"]):
        text = path.read_text(encoding="utf-8")
        assert "CLI_" not in text and "PREF_" not in text, path.name
        assert "hash_id" not in text, path.name


def test_env_key_changes_the_pseudonyms(clean, tmp_path, monkeypatch):
    monkeypatch.setenv("PREDICT360_HMAC_KEY", "finbank-owned-key")
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path)
    other = pd.read_csv(tmp_path / "delinquency_sample.csv")
    assert set(other["client_id"]).isdisjoint(set(clean["dlq"]["client_id"]))


def test_missing_key_fails_for_non_synthetic_config(cfg, tmp_path, monkeypatch):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    real_like = {**cfg, "synthetic": False, "hmac": {"key_env": "PREDICT360_HMAC_KEY"}}
    with pytest.raises(RuntimeError, match="PREDICT360_HMAC_KEY"):
        generate_synthetic_data(config=real_like, output_dir=tmp_path)


# --- dates, events and maturity ------------------------------------------

def test_dates_are_consistent_with_cut_off(clean, cfg):
    t = pd.Timestamp(cfg["snapshot_date"])
    dlq, churn = clean["dlq"], clean["churn"]
    assert (dlq["snapshot_date"] == t).all() and (churn["snapshot_date"] == t).all()
    assert (dlq["origination_date"] < t).all()
    assert (dlq["observation_end_date"] > t).all() and (churn["observation_end_date"] > t).all()


def test_events_fall_inside_the_observation_window(clean, cfg):
    t = pd.Timestamp(cfg["snapshot_date"])
    for df, col in ((clean["dlq"], "first_delinquency_date"), (clean["churn"], "cancellation_date")):
        ev = df.dropna(subset=[col])
        assert len(ev) > 0
        assert (ev[col] > t).all()
        assert (ev[col] <= ev["observation_end_date"]).all()


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_offset_dates_leaves_missing_days_empty_without_date_arithmetic():
    out = _offset_dates(pd.Timestamp("2026-03-31"), np.array([1.0, np.nan, -31.0]))
    assert out.tolist() == ["2026-04-01", None, "2026-02-28"]


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_generation_emits_no_runtime_warnings(tmp_path, monkeypatch):
    # NaN event days (no event) used to reach the date arithmetic and overflow
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    generate_synthetic_data(config=CONFIG, output_dir=tmp_path)


@pytest.mark.parametrize("table,horizon", [("dlq", 30), ("dlq", 60), ("churn", 90)])
def test_immature_rows_exist_for_each_horizon(clean, cfg, table, horizon):
    t = pd.Timestamp(cfg["snapshot_date"])
    df = clean[table]
    immature = df["observation_end_date"] < t + pd.Timedelta(days=horizon)
    assert 0 < immature.sum() < len(df) * 0.2


def test_base_rates_stay_within_configured_range(clean, cfg):
    gen = cfg["generator"]
    for table, col, key in (("dlq", "first_delinquency_date", "delinquency"),
                            ("churn", "cancellation_date", "churn")):
        rate = clean[table][col].notna().mean()
        bounds = gen[key]["base_rate"]
        assert bounds["min"] <= rate <= bounds["max"], (key, rate)


def test_churn_is_the_preferred_segment_top_10pct_of_pool(clean):
    pool = np.asarray(clean["result"]["churn_pool_exposure"])
    assert len(pool) == 2000  # 200 / 0.10
    assert clean["churn"]["exposure_cop_m"].min() >= np.quantile(pool, 0.90) - 1e-3


# --- simulated scores -----------------------------------------------------

def test_scores_shape_and_ranges(clean):
    s = clean["scores"]
    assert set(s["model_id"]) == {"baseline_rule", "model_a", "model_b"}
    assert s["score"].between(0, 1).all() and s["score"].notna().all()
    assert set(s["horizon_days"]) == {30, 60, 90}
    assert set(s["intervened"]) <= {0, 1}
    assert len(s) == 3 * (500 * 2 + 200)


def _labels(clean, cfg, horizon):
    t = pd.Timestamp(cfg["snapshot_date"])
    df, col = (clean["churn"], "cancellation_date") if horizon == 90 else (clean["dlq"], "first_delinquency_date")
    event = df[col].notna() & (df[col] <= t + pd.Timedelta(days=horizon))
    return pd.Series(event.astype(int).values, index=df["client_id"])


@pytest.mark.parametrize("horizon", [30, 60, 90])
def test_scores_are_not_an_oracle(clean, cfg, horizon):
    labels = _labels(clean, cfg, horizon)
    s = clean["scores"]
    for model_id, group in s[s["horizon_days"] == horizon].groupby("model_id"):
        y = group["client_id"].map(labels)
        assert not (group["score"].values == y.values).all(), model_id
        # not a perfect separator: some non-event outranks some event
        assert group.loc[y.values == 0, "score"].max() > group.loc[y.values == 1, "score"].min(), model_id


def test_model_a_ranks_better_than_chance(clean, cfg):
    labels = _labels(clean, cfg, 60)
    s = clean["scores"]
    g = s[(s["horizon_days"] == 60) & (s["model_id"] == "model_a")]
    y = g["client_id"].map(labels)
    assert g.loc[y.values == 1, "score"].mean() > g.loc[y.values == 0, "score"].mean()


# --- model cards ----------------------------------------------------------

def test_model_cards_follow_contract_and_trace_scores(clean):
    fields = contract_columns("model_card_v1")
    scores_hash = _sha256(clean["dir"] / "scores_sample.csv")
    cards = sorted((clean["dir"] / "model_cards").glob("*.json"))
    assert len(cards) == 6
    for path in cards:
        card = json.loads(path.read_text(encoding="utf-8"))
        assert list(card) == fields
        assert card["status"] == "candidate"
        assert card["dataset_hash"] == scores_hash
        assert card["train_end_date"] < card["eval_start_date"]
        assert path.stem == f"{card['target']}_{card['model_id']}"
        assert "simulated" in card["algorithm"]


# --- byte-level reproducibility across operating systems ------------------

def test_written_files_use_lf_line_endings(clean):
    # CRLF on Windows vs LF on Linux would change the sha256 of the scores
    for path in _all_written_files(clean["dir"]):
        assert b"\r" not in path.read_bytes(), path.name


def test_committed_synthetic_data_is_traceable():
    repo_data = CONFIG_DIR.parent / "data" / "synthetic"
    scores = repo_data / "scores_sample.csv"
    assert b"\r" not in scores.read_bytes()
    for path in sorted((repo_data / "model_cards").glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        assert card["dataset_hash"] == _sha256(scores), path.name


# --- defects --------------------------------------------------------------

def test_defect_list_matches_spec():
    assert set(DEFECTS) == {"critical_nulls", "schema", "duplicate_ids",
                            "score_out_of_range", "exposure_mismatch", "overlapping_split"}


def test_unknown_defect_raises(tmp_path):
    with pytest.raises(ValueError):
        generate_synthetic_data(config=CONFIG, output_dir=tmp_path, defect="nope")


def test_defect_critical_nulls(tmp_path, monkeypatch):
    out = _generate_defect(tmp_path, "critical_nulls", monkeypatch)
    df = pd.read_csv(out / "delinquency_sample.csv")
    assert df["observation_end_date"].isna().sum() > 0


def test_defect_schema(tmp_path, monkeypatch):
    out = _generate_defect(tmp_path, "schema", monkeypatch)
    df = pd.read_csv(out / "delinquency_sample.csv")
    assert set(contract_columns("delinquency_v1")) - set(df.columns)


def test_defect_duplicate_ids(tmp_path, monkeypatch):
    out = _generate_defect(tmp_path, "duplicate_ids", monkeypatch)
    df = pd.read_csv(out / "delinquency_sample.csv")
    assert df["client_id"].duplicated().any()


def test_defect_score_out_of_range(tmp_path, monkeypatch):
    out = _generate_defect(tmp_path, "score_out_of_range", monkeypatch)
    s = pd.read_csv(out / "scores_sample.csv")
    assert (s["score"] > 1).any() or (s["score"] < 0).any()


def test_defect_exposure_mismatch(tmp_path, monkeypatch):
    out = _generate_defect(tmp_path, "exposure_mismatch", monkeypatch)
    df = pd.read_csv(out / "delinquency_sample.csv")
    assert reconcile_exposure(df, expected=58800.0, tolerance=0.01)["status"] == "FAIL"


def test_defect_overlapping_split(tmp_path, monkeypatch):
    out = _generate_defect(tmp_path, "overlapping_split", monkeypatch)
    cards = [json.loads(p.read_text(encoding="utf-8")) for p in (out / "model_cards").glob("*.json")]
    assert any(c["train_end_date"] >= c["eval_start_date"] for c in cards)


@pytest.mark.parametrize("defect", ["critical_nulls", "schema", "duplicate_ids",
                                    "score_out_of_range", "exposure_mismatch"])
def test_data_defects_leave_model_cards_clean(tmp_path, monkeypatch, defect):
    out = _generate_defect(tmp_path, defect, monkeypatch)
    for p in (out / "model_cards").glob("*.json"):
        card = json.loads(p.read_text(encoding="utf-8"))
        assert card["train_end_date"] < card["eval_start_date"]
        assert card["dataset_hash"] == _sha256(out / "scores_sample.csv")
