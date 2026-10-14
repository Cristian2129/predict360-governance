from pathlib import Path
from src.predict360.make_synthetic import generate_synthetic_data


def test_synthetic_backlog_direct_exposure_and_sprints(tmp_path: Path):
    """Direct exposure must sum to COP 77,000M and cover all 6 sprints."""
    datasets = generate_synthetic_data(output_dir=tmp_path)
    backlog = datasets["backlog"]

    direct_sum = backlog.loc[backlog["exposure_type"] == "direct", "exposure_cop_m"].sum()
    assert abs(direct_sum - 77000.0) < 1e-6
    assert set(backlog["sprint"].unique()) == {1, 2, 3, 4, 5, 6}
    assert (tmp_path / "backlog.csv").exists()


def test_synthetic_delinquency_reconciles_and_has_realistic_balances(tmp_path: Path):
    """Delinquency sample must sum to COP 58,800M with realistic client balances (~3.36M COP)."""
    datasets = generate_synthetic_data(output_dir=tmp_path)
    delinq_df = datasets["delinquency"]

    assert abs(delinq_df["exposure_cop_m"].sum() - 58800.0) < 1e-6
    mean_balance = delinq_df["client_balance_cop_m"].mean()
    assert 2.5 <= mean_balance <= 4.5
    assert (tmp_path / "delinquency_sample.csv").exists()


def test_synthetic_churn_reconciles_and_injects_r01_missing_rate(tmp_path: Path):
    """Churn sample must sum to COP 18,200M and have exactly 12% missing tenure (Risk R-01)."""
    datasets = generate_synthetic_data(output_dir=tmp_path)
    churn_df = datasets["churn"]

    assert abs(churn_df["exposure_cop_m"].sum() - 18200.0) < 1e-6
    assert churn_df["tenure_months"].isna().mean() == 0.12
    assert (tmp_path / "churn_sample.csv").exists() 