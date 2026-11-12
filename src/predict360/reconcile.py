"""US-04 P1: comprueba que la exposición a mora sume 58,800M COP."""
from pathlib import Path
import math
import numbers

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = ROOT / "data" / "synthetic" / "delinquency_sample.csv"
EVIDENCE_FILE = ROOT / "docs" / "evidence" / "us04_reconciliation.md"
EXPECTED_COP_M = 58800.0
TOLERANCE_COP_M = 0.01  # propuesta; confirmar con equipo


def reconcile_exposure(df: pd.DataFrame,
                       expected: float = EXPECTED_COP_M,
                       tolerance: float = TOLERANCE_COP_M) -> dict:
    """Suma exposure_cop_m sin volver a aplicar sampling_weight."""
    if "exposure_cop_m" not in df.columns:
        raise ValueError("Missing required column: exposure_cop_m")
    if df.empty:
        raise ValueError("Cannot reconcile an empty portfolio")
    if tolerance < 0:
        raise ValueError("Tolerance must be >= 0")
    values = df["exposure_cop_m"]
    for value in values:
        if (pd.isna(value) or isinstance(value, bool)
                or not isinstance(value, numbers.Real)
                or not math.isfinite(float(value)) or value < 0):
            raise ValueError("exposure_cop_m must contain finite nonnegative numbers")
    actual = float(values.sum())
    difference = round(actual - expected, 6)
    if difference == 0:
        difference = 0.0  # evita mostrar -0.000000 por redondeo
    return {
        "expected_cop_m": expected,
        "actual_cop_m": round(actual, 6),
        "difference_cop_m": difference,
        "tolerance_cop_m": tolerance,
        "status": "PASS" if abs(actual - expected) <= tolerance else "FAIL",
    }


def reconcile_all(cfg: dict, delinquency_df: pd.DataFrame, churn_df: pd.DataFrame) -> dict:
    """Station 9: each portfolio against its own client figure from ``cfg['reconciliation']``.

    PASS only if both portfolios reconcile within the configured tolerance.
    """
    rec = cfg["reconciliation"]
    tolerance = rec["tolerance_cop_m"]
    tables = {
        "delinquency": reconcile_exposure(delinquency_df, rec["delinquency_expected_cop_m"], tolerance),
        "churn": reconcile_exposure(churn_df, rec["churn_expected_cop_m"], tolerance),
    }
    status = "PASS" if all(t["status"] == "PASS" for t in tables.values()) else "FAIL"
    return {"status": status, "tables": tables}


def reconcile_csv(csv_path: str | Path = DEFAULT_CSV) -> dict:
    return reconcile_exposure(pd.read_csv(csv_path))


def export_reconciliation_report(csv_path: str | Path = DEFAULT_CSV,
                                 output: str | Path = EVIDENCE_FILE) -> dict:
    result = reconcile_csv(csv_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# US-04 P1 — Delinquency Exposure Reconciliation", "",
        "Author: Paula Gacha | Sprint 2", "",
        f"- Expected: COP {result['expected_cop_m']:,.2f}M",
        f"- Actual: COP {result['actual_cop_m']:,.2f}M",
        f"- Difference: COP {result['difference_cop_m']:,.6f}M",
        f"- Proposed tolerance: COP {result['tolerance_cop_m']:.2f}M",
        f"- Status: **{result['status']}**", "",
        "The source is synthetic. Its `exposure_cop_m` values already incorporate "
        "sample expansion and must not be weighted again.", "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = export_reconciliation_report()
    print(f"Exposure reconciliation: {result['status']}")
    print(f"Actual: COP {result['actual_cop_m']:,.2f}M")
    print(f"Report: {EVIDENCE_FILE}")
