"""
Synthetic data generator for FinBank Predict360 

Statistical & Scope Note:
- Datasets are 100% synthetic (fixed seed = 42) in compliance with Ley 1581 de 2012.
- Designed exclusively to test governance, data-quality thresholds, and exposure
  reconciliation rules (a trained production model is out of scope per the Charter).
- Client balances reflect FinBank's average credit size (~3.36M COP = 420,000M / 125,000 clients).
  The column `exposure_cop_m` represents the sample-expanded risk exposure (using `sampling_weight`)
  so that sample totals reconcile with portfolio risk figures (COP 58,800M and COP 18,200M).
"""

from pathlib import Path
import numpy as np
import pandas as pd

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def generate_synthetic_data(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, pd.DataFrame]:
    """Generates backlog.csv, delinquency_sample.csv, and churn_sample.csv."""
    rng = np.random.default_rng(42)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Product Backlog dataset (US-02: Exposure-based prioritization)
    backlog = pd.DataFrame([
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

    # 2. EarlyRisk Delinquency Sample (n = 500 representing N = 125,000 clients, weight = 250)
    n_delinq = 500
    sampling_weight_delinq = 125000.0 / n_delinq
    client_balance = np.round(rng.gamma(shape=4.0, scale=0.84, size=n_delinq), 4)

    raw_weights = rng.gamma(shape=2.0, scale=1.0, size=n_delinq)
    expanded_exposure = np.round(raw_weights * (58800.0 / raw_weights.sum()), 4)
    expanded_exposure[-1] = np.round(58800.0 - expanded_exposure[:-1].sum(), 4)
    client_exposure = np.round(expanded_exposure / sampling_weight_delinq, 6)

    delinquency_df = pd.DataFrame({
        "client_hash_id": [f"CLI_{i:05d}" for i in range(1, n_delinq + 1)],
        "days_past_due": rng.choice([0, 15, 30, 60, 90], size=n_delinq, p=[0.70, 0.12, 0.10, 0.05, 0.03]),
        "risk_score": np.round(rng.uniform(0.01, 0.99, size=n_delinq), 4),
        "client_balance_cop_m": client_balance,
        "client_exposure_cop_m": client_exposure,
        "sampling_weight": sampling_weight_delinq,
        "exposure_cop_m": expanded_exposure,
    })

    # 3. StayBank Churn Sample (n = 200 preferred clients, 12% missing tenure_months -> Risk R-01)
    n_churn = 200
    sampling_weight_churn = 12500.0 / n_churn
    churn_scores = rng.uniform(0.05, 0.95, size=n_churn)
    tenure = rng.integers(3, 60, size=n_churn).astype(float)
    tenure[rng.choice(n_churn, size=24, replace=False)] = np.nan

    raw_churn = rng.gamma(shape=2.0, scale=1.0, size=n_churn)
    expanded_churn_exp = np.round(raw_churn * (18200.0 / raw_churn.sum()), 4)
    expanded_churn_exp[-1] = np.round(18200.0 - expanded_churn_exp[:-1].sum(), 4)
    client_churn_exp = np.round(expanded_churn_exp / sampling_weight_churn, 6)

    churn_df = pd.DataFrame({
        "client_hash_id": [f"PREF_{i:04d}" for i in range(1, n_churn + 1)],
        "tenure_months": tenure,
        "churn_probability": np.round(churn_scores, 4),
        "client_exposure_cop_m": client_churn_exp,
        "sampling_weight": sampling_weight_churn,
        "exposure_cop_m": expanded_churn_exp,
    })

    backlog.to_csv(out / "backlog.csv", index=False)
    delinquency_df.to_csv(out / "delinquency_sample.csv", index=False)
    churn_df.to_csv(out / "churn_sample.csv", index=False)

    return {
        "backlog": backlog,
        "delinquency": delinquency_df,
        "churn": churn_df,
    }


if __name__ == "__main__":
    generate_synthetic_data()