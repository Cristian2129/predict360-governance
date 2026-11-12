"""Synthetic data generator for FinBank Predict360, version 2 (technical spec, section 7).

Scope note:
- 100% synthetic data, fixed seed (42). No real FinBank record is used.
- Keeps the figures that already reconcile: 500 delinquency rows x weight 250
  (125,000 clients) summing to COP 58,800M, and 200 churn rows x weight 62.5
  (12,500 preferred clients) summing to COP 18,200M. ``exposure_cop_m`` is
  already sample-expanded and must not be weighted again.
- Adds dates, events driven by a latent risk, immature rows, SIMULATED scores
  from three demo models and their model cards. The scores are not trained
  models and are declared as such.
- ``client_id`` is HMAC-SHA256 of a raw identifier that only lives in memory.
- ``--defect <type>`` writes a deliberately broken variant for gate demos.

Usage:
    python -m src.predict360.make_synthetic --config config/synthetic.yaml
    python -m src.predict360.make_synthetic --defect exposure_mismatch
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.predict360.config import CONFIG_DIR, DEMO_KEY_FIELD, ROOT, contract_columns, load_config

DEFAULT_CONFIG = CONFIG_DIR / "synthetic.yaml"
MODEL_IDS = ("baseline_rule", "model_a", "model_b")
DEFECTS = (
    "critical_nulls",
    "schema",
    "duplicate_ids",
    "score_out_of_range",
    "exposure_mismatch",
    "overlapping_split",
)
SPEC_VERSION = "technical_spec 2026-11-10"


# --- helpers ----------------------------------------------------------------

def _resolve_hmac_key(cfg: dict) -> bytes:
    """FinBank's key comes from the environment; the demo key only for synthetic runs."""
    env_name = cfg["hmac"]["key_env"]
    key = os.environ.get(env_name)
    if key:
        return key.encode("utf-8")
    if cfg["synthetic"] and cfg["hmac"].get(DEMO_KEY_FIELD):
        return str(cfg["hmac"][DEMO_KEY_FIELD]).encode("utf-8")
    raise RuntimeError(f"Environment variable {env_name} is not set (required outside synthetic runs)")


def _pseudonymize(raw_ids: list[str], key: bytes) -> list[str]:
    return [hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest() for raw in raw_ids]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _zscore(x: np.ndarray) -> np.ndarray:
    std = x.std()
    return (x - x.mean()) / std if std > 0 else np.zeros_like(x, dtype=float)


def _calibrate_intercept(latent: np.ndarray, target_rate: float) -> float:
    """Bisection: intercept b such that mean(sigmoid(latent + b)) == target_rate."""
    low, high = -30.0, 30.0
    for _ in range(100):
        mid = (low + high) / 2
        if _sigmoid(latent + mid).mean() < target_rate:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _rescale_exact(raw: np.ndarray, total: float, decimals: int = 4) -> np.ndarray:
    """Rescales to an exact total; the rounding residual goes to the LARGEST row."""
    values = np.round(raw * (total / raw.sum()), decimals)
    largest = int(np.argmax(values))
    values[largest] = np.round(values[largest] + (total - values.sum()), decimals)
    return values


def _observation_days(rng, n: int, horizons: list[int], mature_range: list[int],
                      immature_pct: float) -> np.ndarray:
    """Days from T to observation end. Immature rows are spread across horizon bands."""
    days = rng.integers(mature_range[0], mature_range[1] + 1, size=n)
    n_immature = int(round(immature_pct * n))
    immature_idx = np.sort(rng.choice(n, size=n_immature, replace=False))
    bands = list(zip([1] + list(horizons[:-1]), horizons))  # [1, 30), [30, 60) ...
    for i, idx in enumerate(immature_idx):
        low, high = bands[i % len(bands)]
        days[idx] = rng.integers(low, high)  # high exclusive -> always < T + H
    return days


def _event_days(rng, latent: np.ndarray, target_rate: float, obs_days: np.ndarray) -> np.ndarray:
    """Bernoulli(sigmoid(latent + b)); event day uniform in (T, observation_end]. NaN = no event."""
    prob = _sigmoid(latent + _calibrate_intercept(latent, target_rate))
    happens = rng.random(len(latent)) < prob
    day = np.array([rng.integers(1, d + 1) for d in obs_days], dtype=float)
    day[~happens] = np.nan
    return day


def _offset_dates(t: pd.Timestamp, days: np.ndarray) -> pd.Series:
    """ISO date strings T + days (empty for NaN)."""
    out = pd.Series(t + pd.to_timedelta(days, unit="D"))
    return out.dt.strftime("%Y-%m-%d")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- tables -----------------------------------------------------------------

def _backlog() -> pd.DataFrame:
    """Product Backlog (US-02); unchanged from v1."""
    return pd.DataFrame([
        {"story_id": "US-01", "title": "Governance framework (RACI & cadence)", "domain": "Enabling", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 2, "sprint": 1},
        {"story_id": "US-02", "title": "Exposure-based backlog prioritization", "domain": "Enabling", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 3, "sprint": 1},
        {"story_id": "US-03-P1", "title": "Data readiness: source inventory & quality thresholds", "domain": "Delinquency_Churn", "exposure_type": "umbrella", "exposure_cop_m": 77000.0, "sp": 5, "sprint": 1},
        {"story_id": "US-06", "title": "Evidence-based sprint closure mechanism", "domain": "Enabling", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 5, "sprint": 1},
        {"story_id": "US-03-P2", "title": "Data readiness: Ley 1581 compliance & gap report", "domain": "Delinquency_Churn", "exposure_type": "umbrella", "exposure_cop_m": 77000.0, "sp": 3, "sprint": 2},
        {"story_id": "US-04-P1", "title": "EarlyRisk: delinquency baseline & early-warning requirements", "domain": "Delinquency", "exposure_type": "direct", "exposure_cop_m": 58800.0, "sp": 5, "sprint": 2},
        {"story_id": "US-07", "title": "Risk and impediment visibility", "domain": "Enabling", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 5, "sprint": 2},
        {"story_id": "US-04-P2", "title": "EarlyRisk: delinquency model roadmap & validation plan", "domain": "Delinquency", "exposure_type": "umbrella", "exposure_cop_m": 58800.0, "sp": 3, "sprint": 3},
        {"story_id": "US-05", "title": "StayBank: churn roadmap and validation plan", "domain": "Churn", "exposure_type": "direct", "exposure_cop_m": 18200.0, "sp": 8, "sprint": 4},
        {"story_id": "US-08", "title": "Sprint checkpoint and business validation review", "domain": "Enabling", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 5, "sprint": 5},
        {"story_id": "US-09", "title": "Operational roadmap, handover and reusable framework", "domain": "Enabling", "exposure_type": "enabling", "exposure_cop_m": 0.0, "sp": 8, "sprint": 6},
    ])


def _delinquency(rng, cfg: dict, key: bytes, t: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    g = cfg["generator"]["delinquency"]
    n = g["n_rows"]
    exposure = _rescale_exact(rng.lognormal(0.0, g["exposure_lognormal_sigma"], n),
                              cfg["reconciliation"]["delinquency_expected_cop_m"])
    utilization = np.round(np.clip(rng.beta(*g["utilization_beta"], n) * g["utilization_scale"], 0, 1.5), 4)
    prior_late = rng.poisson(g["prior_late_lambda"], n)
    max_dpd = np.where(prior_late > 0, rng.integers(1, 90, n), 0)
    tenure = rng.integers(g["tenure_months_range"][0], g["tenure_months_range"][1] + 1, n)
    origination_days = rng.integers(g["origination_days_range"][0], g["origination_days_range"][1] + 1, n)

    c = g["latent_coefficients"]
    latent = (c["utilization"] * _zscore(utilization)
              + c["prior_late_12m"] * _zscore(prior_late.astype(float))
              + c["tenure_months"] * _zscore(tenure.astype(float))
              + rng.normal(0.0, g["latent_noise_sd"], n))
    obs_days = _observation_days(rng, n, g["horizons_days"], g["observation_days_range"],
                                 cfg["generator"]["immature_pct"])
    event_day = _event_days(rng, latent, g["base_rate"]["target"], obs_days)

    raw_ids = [f"CLI_{i:05d}" for i in range(1, n + 1)]  # in memory only
    df = pd.DataFrame({
        "client_id": _pseudonymize(raw_ids, key),
        "snapshot_date": t.strftime("%Y-%m-%d"),
        "exposure_cop_m": exposure,
        "weight": float(g["weight"]),
        "origination_date": _offset_dates(t, -origination_days.astype(float)),
        "utilization": utilization,
        "prior_late_12m": prior_late,
        "max_dpd_12m": max_dpd,
        "tenure_months": tenure,
        "first_delinquency_date": _offset_dates(t, event_day),
        "observation_end_date": _offset_dates(t, obs_days.astype(float)),
    })
    hidden = {"latent": latent, "prior_late": prior_late.astype(float), "exposure": exposure}
    return df[contract_columns("delinquency_v1")], hidden


def _churn(rng, cfg: dict, key: bytes, t: pd.Timestamp) -> tuple[pd.DataFrame, dict, np.ndarray]:
    g = cfg["generator"]["churn"]
    n = g["n_rows"]
    pool_n = int(round(n / g["preferred_top_pct"]))
    pool_raw = rng.lognormal(0.0, g["exposure_lognormal_sigma"], pool_n)
    top_idx = np.sort(np.argsort(pool_raw)[::-1][:n])  # preferred segment: top % by exposure
    scale = cfg["reconciliation"]["churn_expected_cop_m"] / pool_raw[top_idx].sum()
    exposure = _rescale_exact(pool_raw[top_idx], cfg["reconciliation"]["churn_expected_cop_m"])

    tenure = rng.integers(g["tenure_months_range"][0], g["tenure_months_range"][1] + 1, n)
    products = rng.integers(g["products_active_range"][0], g["products_active_range"][1] + 1, n)
    rate_gap = rng.normal(0.0, 1.0, n)  # hidden: loan rate vs market rate, not in the contract

    c = g["latent_coefficients"]
    latent = (c["tenure_months"] * _zscore(tenure.astype(float))
              + c["products_active"] * _zscore(products.astype(float))
              + c["rate_gap"] * rate_gap
              + rng.normal(0.0, g["latent_noise_sd"], n))
    obs_days = _observation_days(rng, n, g["horizons_days"], g["observation_days_range"],
                                 cfg["generator"]["immature_pct"])
    event_day = _event_days(rng, latent, g["base_rate"]["target"], obs_days)

    tenure_out = pd.array(tenure, dtype="Int64")
    missing = rng.choice(n, size=int(round(g["tenure_missing_pct"] * n)), replace=False)
    tenure_out[missing] = pd.NA  # R-01: kept on purpose, never imputed

    raw_ids = [f"PREF_{i:05d}" for i in top_idx]  # in memory only
    df = pd.DataFrame({
        "client_id": _pseudonymize(raw_ids, key),
        "snapshot_date": t.strftime("%Y-%m-%d"),
        "exposure_cop_m": exposure,
        "weight": float(g["weight"]),
        "tenure_months": tenure_out,
        "products_active": products,
        "cancellation_date": _offset_dates(t, event_day),
        "observation_end_date": _offset_dates(t, obs_days.astype(float)),
    })
    hidden = {"latent": latent, "products": products.astype(float), "exposure": exposure}
    return df[contract_columns("churn_v1")], hidden, pool_raw * scale


def _simulated_scores(rng, cfg: dict, client_ids: pd.Series, hidden: dict,
                      rule_signal: np.ndarray, horizon: int, t: pd.Timestamp) -> pd.DataFrame:
    """Three SIMULATED models; noise keeps every one of them from being an oracle."""
    sd = cfg["generator"]["scores"]["noise_sd"]
    n = len(client_ids)
    latent = hidden["latent"]
    p_rule = _sigmoid(_zscore(rule_signal) + rng.normal(0.0, sd["baseline_rule"], n))
    p_a = _sigmoid(latent + rng.normal(0.0, sd["model_a"], n))
    p_b = _sigmoid(latent + rng.normal(0.0, sd["model_b"], n))
    expected_loss = p_b * hidden["exposure"]
    by_model = {
        "baseline_rule": p_rule,
        "model_a": p_a,
        "model_b": expected_loss / expected_loss.max(),  # normalized to [0, 1]
    }
    frames = [
        pd.DataFrame({
            "client_id": client_ids.values,
            "model_id": model_id,
            "snapshot_date": t.strftime("%Y-%m-%d"),
            "horizon_days": horizon,
            "score": np.round(by_model[model_id], 6),
            "intervened": 0,  # simulated scores: nobody was contacted
        })
        for model_id in MODEL_IDS
    ]
    return pd.concat(frames, ignore_index=True)


def _model_cards(cfg: dict, t: pd.Timestamp, scores_hash: str) -> dict[str, dict]:
    s = cfg["generator"]["scores"]
    train_end = (t + pd.Timedelta(days=s["train_end_offset_days"])).strftime("%Y-%m-%d")
    eval_start = (t + pd.Timedelta(days=s["eval_start_offset_days"])).strftime("%Y-%m-%d")
    features = {
        "delinquency": {"baseline_rule": ["prior_late_12m"],
                        "model": ["utilization", "prior_late_12m", "tenure_months"]},
        "churn": {"baseline_rule": ["products_active"],
                  "model": ["tenure_months", "products_active", "rate_gap (hidden)"]},
    }
    ranking = {"baseline_rule": "by rule score", "model_a": "by probability",
               "model_b": "by probability x exposure (expected loss)"}
    algorithm = {"baseline_rule": "simulated heuristic rule on a single observable variable plus noise",
                 "model_a": "simulated probability from latent risk plus noise",
                 "model_b": "simulated probability x exposure, normalized to [0, 1]"}
    cards = {}
    for target in ("delinquency", "churn"):
        for model_id in MODEL_IDS:
            values = {
                "model_id": model_id,
                "created_at": cfg["generator"]["created_at"],
                "run_by": "PCM Analytics - make_synthetic v2",
                "target": target,
                "spec_version": SPEC_VERSION,
                "dataset_hash": scores_hash,
                "snapshot_date": t.strftime("%Y-%m-%d"),
                "train_end_date": train_end,
                "eval_start_date": eval_start,
                "preprocessing_fit_on": "train_only",
                "commit": "n/a (simulated scores, no training code)",
                "libs": {"numpy": np.__version__, "pandas": pd.__version__},
                "seed": cfg["seed"],
                "algorithm": algorithm[model_id],
                "hyperparameters": {"noise_sd": s["noise_sd"][model_id]},
                "features": features[target]["baseline_rule" if model_id == "baseline_rule" else "model"],
                "ranking_policy": ranking[model_id],
                "baselines_compared": ["random"] if model_id == "baseline_rule" else ["random", "baseline_rule"],
                "intervention_handling": "none: simulated scores, intervened = 0 for every client",
                "status": "candidate",
                "approved_by": None,
            }
            cards[f"{target}_{model_id}"] = {f: values.get(f) for f in contract_columns("model_card_v1")}
    return cards


# --- defects ------------------------------------------------------------------

def _apply_data_defect(defect: str | None, dlq: pd.DataFrame, scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dlq, scores = dlq.copy(), scores.copy()
    if defect == "critical_nulls":
        dlq.loc[dlq.index[:5], "observation_end_date"] = None
    elif defect == "schema":
        dlq = dlq.drop(columns=["max_dpd_12m"])
    elif defect == "duplicate_ids":
        dlq.loc[dlq.index[1], "client_id"] = dlq.loc[dlq.index[0], "client_id"]
    elif defect == "score_out_of_range":
        scores.loc[scores.index[0], "score"] = 1.25
        scores.loc[scores.index[1], "score"] = -0.1
    elif defect == "exposure_mismatch":
        largest = dlq["exposure_cop_m"].idxmax()
        dlq.loc[largest, "exposure_cop_m"] = round(dlq.loc[largest, "exposure_cop_m"] + 150.0, 4)
    return dlq, scores


# --- entry point ----------------------------------------------------------------

def generate_synthetic_data(config: str | Path | dict = DEFAULT_CONFIG,
                            output_dir: str | Path | None = None,
                            defect: str | None = None) -> dict:
    """Writes backlog, delinquency, churn and scores CSVs plus model cards.

    Returns the DataFrames written, the model cards and ``churn_pool_exposure``
    (pool exposure on the same scale, in memory only, to check the preferred segment).
    """
    if defect is not None and defect not in DEFECTS:
        raise ValueError(f"Unknown defect '{defect}'. Choose one of: {', '.join(DEFECTS)}")
    cfg = config if isinstance(config, dict) else load_config(config)
    key = _resolve_hmac_key(cfg)
    if output_dir is None:
        output_dir = ROOT / cfg["paths"]["output_dir"]
        if defect:
            output_dir = output_dir / "defects" / defect
    out = Path(output_dir)
    (out / "model_cards").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(cfg["seed"])
    t = pd.Timestamp(date.fromisoformat(str(cfg["snapshot_date"])))

    backlog = _backlog()
    dlq, dlq_hidden = _delinquency(rng, cfg, key, t)
    churn, churn_hidden, churn_pool = _churn(rng, cfg, key, t)

    score_frames = [
        _simulated_scores(rng, cfg, dlq["client_id"], dlq_hidden, dlq_hidden["prior_late"], h, t)
        for h in cfg["generator"]["delinquency"]["horizons_days"]
    ] + [
        # churn rule: fewer active products -> higher score
        _simulated_scores(rng, cfg, churn["client_id"], churn_hidden, -churn_hidden["products"], h, t)
        for h in cfg["generator"]["churn"]["horizons_days"]
    ]
    scores = pd.concat(score_frames, ignore_index=True)[contract_columns("scores_v1")]

    dlq, scores = _apply_data_defect(defect, dlq, scores)

    # LF everywhere: the sha256 in the model cards must not depend on the OS
    backlog.to_csv(out / "backlog.csv", index=False, lineterminator="\n")
    dlq.to_csv(out / "delinquency_sample.csv", index=False, lineterminator="\n")
    churn.to_csv(out / "churn_sample.csv", index=False, lineterminator="\n")
    scores.to_csv(out / "scores_sample.csv", index=False, lineterminator="\n")

    cards = _model_cards(cfg, t, _sha256(out / "scores_sample.csv"))
    if defect == "overlapping_split":
        for name, card in cards.items():
            if card["model_id"] == "model_a":
                card["train_end_date"] = (pd.Timestamp(card["eval_start_date"])
                                          + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    for name, card in cards.items():
        (out / "model_cards" / f"{name}.json").write_text(
            json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    return {
        "backlog": backlog,
        "delinquency": dlq,
        "churn": churn,
        "scores": scores,
        "model_cards": cards,
        "churn_pool_exposure": churn_pool,
        "output_dir": out,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate Predict360 synthetic data (v2).")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Run configuration YAML")
    parser.add_argument("--defect", choices=DEFECTS, default=None,
                        help="Write a deliberately broken variant (default dir: <output_dir>/defects/<type>)")
    parser.add_argument("--output-dir", default=None, help="Override the output directory")
    args = parser.parse_args(argv)
    result = generate_synthetic_data(args.config, args.output_dir, args.defect)
    print(f"Synthetic data written to {result['output_dir']}"
          + (f" (defect: {args.defect})" if args.defect else ""))


if __name__ == "__main__":
    main()
