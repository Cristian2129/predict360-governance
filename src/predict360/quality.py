"""US-03 P1: revisiom de calidad de datos sintéticos

Paula Gacha — PCM Analytics.

"""
from pathlib import Path
import math
import numbers

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "synthetic"
EVIDENCE_FILE = ROOT / "docs" / "evidence" / "us03_quality_report.md"

# s: cadena, i: entero, n: numérico (entero o decimal).
SCHEMAS = {
    "backlog": {
        "story_id": "s", "title": "s", "domain": "s",
        "exposure_type": "s", "exposure_cop_m": "n",
        "sp": "i", "sprint": "i",
    },
    "delinquency": {
        "client_hash_id": "s", "days_past_due": "i", "risk_score": "n",
        "client_balance_cop_m": "n", "client_exposure_cop_m": "n",
        "sampling_weight": "n", "exposure_cop_m": "n",
    },
    "churn": {
        "client_hash_id": "s", "tenure_months": "n",
        "churn_probability": "n", "client_exposure_cop_m": "n",
        "sampling_weight": "n", "exposure_cop_m": "n",
    },
}

# El identificador, puntajes y exposición financiera son críticos: 0% vacíos.
CRITICAL_COLUMNS = {
    "story_id", "client_hash_id", "risk_score",
    "churn_probability", "exposure_cop_m",
}
DEFAULT_MISSING_LIMIT_PCT = 5.0  # propuesta de negocio para otros campos
SCORE_COLUMNS = {"risk_score", "churn_probability"}


def _is_missing(value):
    """Detecta NaN, None y cadenas en blanco."""
    return bool(pd.isna(value)) or (isinstance(value, str) and not value.strip())


def _is_valid_type(value, expected):
    """No acepta cadenas como números ni booleanos como enteros."""
    if expected == "s":
        return isinstance(value, str)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    if not math.isfinite(float(value)):
        return False
    if expected == "i":
        return float(value).is_integer()
    return True


def audit_source(df: pd.DataFrame, source: str) -> dict:
    """Revisa un DataFrame y entrega un diccionario fácil de leer.

    source: 'backlog', 'delinquency' o 'churn'.
    status: PASS si cumple todos los umbrales; FAIL en caso contrario.
    """
    if source not in SCHEMAS:
        raise ValueError(f"Unknown source: {source}")

    schema = SCHEMAS[source]
    rows = len(df)
    missing_columns = sorted(set(schema) - set(df.columns))
    result = {
        "source": source,
        "rows": rows,
        "status": "PASS",
        "missing_columns": missing_columns,
        "missing": {},
        "invalid_types": {},
        "out_of_range": {},
        "errors": [],
    }

    if rows == 0:
        result["errors"].append("The dataset is empty")
    for column in missing_columns:
        result["errors"].append(f"Missing required column: {column}")

    for column, kind in schema.items():
        if column not in df.columns:
            continue
        series = df[column]
        absent = series.map(_is_missing)
        count = int(absent.sum())
        pct = 100.0 * count / rows if rows else 0.0
        allowed = 0.0 if column in CRITICAL_COLUMNS else DEFAULT_MISSING_LIMIT_PCT
        result["missing"][column] = {
            "count": count, "pct": round(pct, 2), "limit_pct": allowed,
        }
        if pct > allowed:
            result["errors"].append(
                f"{column}: {pct:.2f}% missing (limit {allowed:.1f}%)"
            )

        present = series.loc[~absent]
        wrong_type = int((~present.map(lambda x: _is_valid_type(x, kind))).sum())
        result["invalid_types"][column] = wrong_type
        if wrong_type:
            result["errors"].append(f"{column}: {wrong_type} invalid data type(s)")

        if column in SCORE_COLUMNS:
            # Verifica 0 <= puntaje <= 1, ignorando valores no numéricos
            # (que ya quedan registrados en invalid_types).
            out = sum(
                1 for val in present
                if _is_valid_type(val, "n") and not 0 <= float(val) <= 1
            )
            result["out_of_range"][column] = out
            if out:
                result["errors"].append(f"{column}: {out} score(s) outside [0, 1]")

    if result["errors"]:
        result["status"] = "FAIL"
    return result


def audit_csv(csv_path: str | Path, source: str) -> dict:
    """Lee un archivo CSV y ejecuta los chequeos de calidad."""
    return audit_source(pd.read_csv(csv_path), source)


def export_quality_report(data_dir: str | Path = DATA_DIR,
                          output: str | Path = EVIDENCE_FILE) -> list[dict]:
    """Genera evidencia Markdown con los hallazgos de las tres fuentes."""
    data_dir, output = Path(data_dir), Path(output)
    paths = {
        "backlog": data_dir / "backlog.csv",
        "delinquency": data_dir / "delinquency_sample.csv",
        "churn": data_dir / "churn_sample.csv",
    }
    results = [audit_csv(path, source) for source, path in paths.items()]
    lines = ["# US-03 P1 — Data Quality Audit", "",
             "Author: Paula Gacha | FinBank Predict360", "",
             "Proposed thresholds: 0% missing in critical fields; 5% in other fields; "
             "0 invalid types; 0 risk scores outside [0, 1].", "",
             "| Source | Rows | Status | Issues |",
             "| --- | ---: | :---: | ---: |"]
    for res in results:
        lines.append(f"| {res['source']} | {res['rows']} | {res['status']} | {len(res['errors'])} |")
    for res in results:
        lines += ["", f"## {res['source']}: {res['status']}", ""]
        for col, info in res["missing"].items():
            if info["count"]:
                lines.append(
                    f"- Missing `{col}`: {info['count']}/{res['rows']} "
                    f"({info['pct']:.2f}%, limit {info['limit_pct']:.1f}%)."
                )
        for error in res["errors"]:
            lines.append(f"- Issue: {error}")
        if not res["errors"]:
            lines.append("- No threshold violations detected.")
    lines += ["", "## Interpretation", "",
              "A FAIL in churn is an expected business finding when 12% of tenure_months "
              "are empty; do not edit or hide the synthetic data. The Python tests can "
              "pass while the data-quality gate reports FAIL.", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return results


if __name__ == "__main__":
    for item in export_quality_report():
        print(f"{item['source']}: {item['status']} | rows={item['rows']}")
    print(f"Report: {EVIDENCE_FILE}")
