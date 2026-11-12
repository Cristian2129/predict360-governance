"""US-03 P1: revisiom de calidad de datos sintéticos

Paula Gacha — PCM Analytics.

Gate 1 (US-04-P2): ``validate_table`` / ``run_gate1`` validate each table against
its data contract with Expectations-style rule names (the library is not installed).
``audit_source`` and ``export_quality_report`` are kept as the Sprint 1 legacy.
"""
from datetime import date, datetime
from pathlib import Path
import argparse
import json
import math
import numbers
import re
import shutil
import sys

import pandas as pd

from src.predict360.config import CONFIG_DIR, load_config, load_contract

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
    """Legacy (Sprint 1, US-03). Superseded by validate_table / run_gate1.

    Revisa un DataFrame y entrega un diccionario fácil de leer.

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


# =============================================================================
# Gate 1 (US-04-P2): contract-driven validation
# =============================================================================

SOURCE_CONTRACTS = {"delinquency": "delinquency_v1", "churn": "churn_v1", "scores": "scores_v1"}
DEFAULT_OUTPUT_DIR = ROOT / "runs" / "adhoc"
EVIDENCE_DIR = ROOT / "docs" / "evidence"
FORMATS = {"sha256_hex": re.compile(r"^[0-9a-f]{64}$")}

# Everything a rule result may contain: counts, percentages, rule parameters taken
# from the contract and column NAMES. Never row values (no IDs, no scores).
REPORT_RESULT_KEYS = frozenset({
    "rule", "column", "critical", "success", "unexpected_count", "unexpected_pct",
    "observed_value", "kwargs", "missing_columns", "extra_columns", "waived_by",
})


def _to_date(value):
    """ISO date (YYYY-MM-DD) or date object -> date; None if invalid."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _type_ok(value, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "date":
        return _to_date(value) is not None
    if kind == "decimal":
        return _is_valid_type(value, "n")
    if kind == "integer":
        return _is_valid_type(value, "i")
    if kind == "binary":
        return _is_valid_type(value, "i") and float(value) in (0.0, 1.0)
    raise ValueError(f"Unknown contract type: {kind}")


def _result(rule, column, critical, unexpected, total, **extra) -> dict:
    success = extra.pop("success", unexpected == 0)
    return {
        "rule": rule,
        "column": column,
        "critical": critical,
        "success": bool(success),
        "unexpected_count": int(unexpected),
        "unexpected_pct": round(100.0 * unexpected / total, 2) if total else 0.0,
        **extra,
    }


def _column_rules(df: pd.DataFrame, column: str, spec: dict, snapshot: date) -> tuple[list[dict], dict]:
    rows = len(df)
    critical = bool(spec.get("critical", False))
    series = df[column]
    absent = series.map(_is_missing)
    nulls = int(absent.sum())
    present = series[~absent]
    results = []

    limit = 0.0 if spec.get("required") else spec.get("max_null_pct")
    null_pct = round(100.0 * nulls / rows, 2) if rows else 0.0
    missing = {"count": nulls, "pct": null_pct,
               "limit_pct": None if limit is None else round(100.0 * limit, 2)}
    if limit is not None:
        results.append(_result("expect_column_values_to_not_be_null", column, critical, nulls, rows,
                               success=null_pct <= 100.0 * limit + 1e-9,
                               kwargs={"mostly": round(1.0 - limit, 4)}))

    kind = spec["type"]
    typed = present.map(lambda v: _type_ok(v, kind))
    results.append(_result("expect_column_values_to_be_of_type", column, critical,
                           int((~typed).sum()), rows, kwargs={"type_": kind}))
    valid = present[typed]

    if spec.get("unique"):
        results.append(_result("expect_column_values_to_be_unique", column, critical,
                               int(present.duplicated(keep=False).sum()), rows))

    if "min" in spec or "max" in spec:
        low, high = spec.get("min"), spec.get("max")
        strict = bool(spec.get("min_exclusive", False))

        def outside(v):
            v = float(v)
            if low is not None and (v <= low if strict else v < low):
                return True
            return high is not None and v > high

        results.append(_result("expect_column_values_to_be_between", column, critical,
                               int(valid.map(outside).sum()), rows,
                               kwargs={"min_value": low, "max_value": high, "strict_min": strict}))

    if "allowed" in spec:
        allowed = spec["allowed"]
        if kind in ("integer", "decimal", "binary"):
            allowed_set = {float(a) for a in allowed}
            bad = valid.map(lambda v: float(v) not in allowed_set)
        else:
            bad = valid.map(lambda v: v not in allowed)
        results.append(_result("expect_column_values_to_be_in_set", column, critical,
                               int(bad.sum()), rows, kwargs={"value_set": list(allowed)}))

    if "format" in spec:
        pattern = FORMATS[spec["format"]]
        strings = present[present.map(lambda v: isinstance(v, str))]
        results.append(_result("expect_column_values_to_match_regex", column, critical,
                               int((~strings.map(lambda v: bool(pattern.match(v)))).sum()), rows,
                               kwargs={"regex": spec["format"]}))

    for relation in ("after", "before"):
        other = spec.get(relation)
        if other is None or other not in df.columns:
            continue
        mine, theirs = df[column].map(_to_date), df[other].map(_to_date)
        both = mine.notna() & theirs.notna()
        if relation == "after":   # column > other
            bad = [not (a > b) for a, b in zip(mine[both], theirs[both])]
            column_a, column_b = column, other
        else:                     # other > column
            bad = [not (b > a) for a, b in zip(mine[both], theirs[both])]
            column_a, column_b = other, column
        results.append(_result("expect_column_pair_values_a_to_be_greater_than_b", column, critical,
                               sum(bad), rows, kwargs={"column_A": column_a, "column_B": column_b}))

    if spec.get("equals") == "run.snapshot_date":
        bad = valid.map(lambda v: _to_date(v) != snapshot)
        results.append(_result("expect_column_values_to_equal_run_snapshot", column, critical,
                               int(bad.sum()), rows, kwargs={"value": snapshot.isoformat()}))
    return results, missing


def _split_waivers(waivers, table, columns: dict, as_of: date) -> tuple[list[dict], list[dict]]:
    """Active waivers for this table; expired ones and those on critical columns are ignored."""
    active, ignored = [], []
    for waiver in waivers or ():
        if waiver.get("table") != table:
            continue
        expires = _to_date(waiver.get("expires"))
        if expires is None or as_of > expires:
            ignored.append({"id": waiver.get("id"), "reason": "expired"})
        elif columns.get(waiver.get("column"), {}).get("critical", True):
            ignored.append({"id": waiver.get("id"), "reason": "critical"})
        else:
            active.append(waiver)
    return active, ignored


def _status(results: list[dict]) -> str:
    failed = [r for r in results if not r["success"]]
    if any(not r.get("waived_by") for r in failed):
        return "FAIL"
    return "PASS_WITH_WAIVERS" if failed else "PASS"


def validate_table(df: pd.DataFrame, contract_name: str, snapshot_date, waivers=(),
                   as_of: date | None = None, table: str | None = None) -> dict:
    """Validates one table against its contract. Returns aggregates only, never row values.

    status: PASS, PASS_WITH_WAIVERS (only non-critical findings, each covered by an
    unexpired waiver) or FAIL (any critical finding, or a non-critical one without waiver).
    """
    contract = load_contract(contract_name)
    columns = contract["columns"]
    table = table or contract.get("table")
    snapshot = _to_date(str(snapshot_date))
    as_of = as_of or date.today()
    rows = len(df)

    results = [{
        "rule": "expect_table_row_count_to_be_between", "column": None, "critical": True,
        "success": rows >= 1, "observed_value": rows, "kwargs": {"min_value": 1},
    }]
    missing_cols = [c for c in columns if c not in df.columns]
    extra_cols = [c for c in df.columns if c not in columns]
    results.append({
        "rule": "expect_table_columns_to_match_set", "column": None, "critical": True,
        "success": not missing_cols, "missing_columns": missing_cols,
        "extra_columns": extra_cols,  # minimization: dropped at the CURATED step
    })

    missing = {}
    if rows:
        for column, spec in columns.items():
            if column in df.columns:
                column_results, missing[column] = _column_rules(df, column, spec, snapshot)
                results.extend(column_results)

    active, ignored = _split_waivers(waivers, table, columns, as_of)
    applied = []
    for result in results:
        if result["success"] or result["critical"]:
            continue
        for waiver in active:
            if waiver["column"] == result["column"] and waiver["rule"] == result["rule"]:
                result["waived_by"] = waiver["id"]
                if waiver["id"] not in applied:
                    applied.append(waiver["id"])
                break

    return {
        "table": table,
        "contract": contract_name,
        "version": contract.get("version"),
        "rows": rows,
        "status": _status(results),
        "results": results,
        "missing": missing,
        "waivers_applied": applied,
        "waivers_ignored": ignored,
    }


def _read_source(path: Path, contract_name: str) -> pd.DataFrame:
    """Reads text and date columns as strings so pandas does not reinterpret them."""
    columns = load_contract(contract_name)["columns"]
    dtypes = {c: str for c, spec in columns.items() if spec["type"] in ("string", "date")}
    return pd.read_csv(path, dtype=dtypes)


def run_gate1(cfg: dict, data_dir: str | Path | None = None, as_of: date | None = None) -> dict:
    """Gate 1 over the three sources declared in ``cfg['sources']``."""
    data_dir = Path(data_dir) if data_dir is not None else ROOT / cfg["paths"]["input_dir"]
    as_of = as_of or date.today()
    snapshot = str(cfg["snapshot_date"])
    tables = {}
    for name, contract_name in SOURCE_CONTRACTS.items():
        file_name = cfg["sources"][name]
        path = data_dir / file_name
        if not path.exists():
            result = {
                "table": name, "contract": contract_name,
                "version": load_contract(contract_name).get("version"), "rows": 0,
                "status": "FAIL",
                "results": [{"rule": "expect_file_to_exist", "column": None,
                             "critical": True, "success": False}],
                "missing": {}, "waivers_applied": [], "waivers_ignored": [],
            }
        else:
            result = validate_table(_read_source(path, contract_name), contract_name, snapshot,
                                    waivers=cfg.get("waivers") or [], as_of=as_of, table=name)
        tables[name] = {"file": file_name, **result}

    statuses = [t["status"] for t in tables.values()]
    status = ("FAIL" if "FAIL" in statuses
              else "PASS_WITH_WAIVERS" if "PASS_WITH_WAIVERS" in statuses else "PASS")
    return {
        "gate": "gate1",
        "status": status,
        "synthetic": cfg["synthetic"],
        "snapshot_date": snapshot,
        "as_of": as_of.isoformat(),
        "contract_versions": {name: t["version"] for name, t in tables.items()},
        "waivers_applied": [w for t in tables.values() for w in t["waivers_applied"]],
        "tables": tables,
    }


def _gate1_markdown(report: dict) -> str:
    lines = ["# Gate 1 — Data Validation Report", "",
             f"- Status: **{report['status']}**",
             f"- Data: {'SYNTHETIC' if report['synthetic'] else 'REAL (inside FinBank)'}",
             f"- Cut-off date T: {report['snapshot_date']} | Evaluated on: {report['as_of']}",
             f"- Waivers applied: {', '.join(report['waivers_applied']) or 'none'}", "",
             "Aggregates only: counts and percentages per rule, never row values.", "",
             "| Table | Contract | Rows | Status | Failed rules |",
             "| --- | --- | ---: | :---: | ---: |"]
    for name, t in report["tables"].items():
        failed = sum(1 for r in t["results"] if not r["success"])
        lines.append(f"| {name} | {t['contract']} | {t['rows']} | {t['status']} | {failed} |")
    for name, t in report["tables"].items():
        failed = [r for r in t["results"] if not r["success"]]
        lines += ["", f"## {name}: {t['status']}", ""]
        if not failed:
            lines.append("- All rules passed.")
        for r in failed:
            where = f" on `{r['column']}`" if r["column"] else ""
            detail = (f": {r['unexpected_count']} rows ({r['unexpected_pct']:.2f}%)"
                      if "unexpected_count" in r else "")
            if r.get("missing_columns"):
                detail = f": missing columns {', '.join(r['missing_columns'])}"
            tag = "critical" if r["critical"] else (f"waived by {r['waived_by']}" if r.get("waived_by")
                                                    else "non-critical, no waiver")
            lines.append(f"- `{r['rule']}`{where}{detail} ({tag})")
        for w in t["waivers_ignored"]:
            lines.append(f"- Waiver {w['id']} ignored: {w['reason']}")
    return "\n".join(lines) + "\n"


def write_gate1_report(report: dict, output_dir: str | Path) -> list[Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "gate1_report.json", out / "gate1_report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                         encoding="utf-8", newline="\n")
    md_path.write_text(_gate1_markdown(report), encoding="utf-8", newline="\n")
    return [json_path, md_path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate 1: validate the sources against their contracts.")
    parser.add_argument("--config", default=str(CONFIG_DIR / "synthetic.yaml"))
    parser.add_argument("--data-dir", default=None, help="Override paths.input_dir")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--evidence", action="store_true", help="Also copy the report to docs/evidence/")
    parser.add_argument("--evidence-dir", default=str(EVIDENCE_DIR))
    parser.add_argument("--as-of", default=None, help="Evaluation date for waiver expiry (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    report = run_gate1(load_config(args.config), data_dir=args.data_dir, as_of=as_of)
    paths = write_gate1_report(report, args.output_dir)
    if args.evidence:
        evidence = Path(args.evidence_dir)
        evidence.mkdir(parents=True, exist_ok=True)
        for path in paths:
            shutil.copyfile(path, evidence / path.name)

    print(f"Gate 1: {report['status']}")
    for name, t in report["tables"].items():
        print(f"  {name}: {t['status']} | rows={t['rows']}")
    print(f"Report: {paths[0]}")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
