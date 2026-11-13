"""Station 12 (part): builds ``dashboard_data.json`` from a run's own outputs (spec, section 11).

``run_pipeline`` calls it after the evidence record and before the manifest closes, then
renders ``index.html`` from it; both files go into the run folder and the final manifest
records their hashes. Nothing is recomputed here: every value is copied from the run's
aggregate outputs (gate reports, reconciliation, funnel, evaluation, management) or from
the files people write (assumptions, sprint log, risk register, handover runbook).

- ``lineage.manifest`` is a snapshot of the manifest at export time. A file cannot carry
  its own hash, so its outputs list everything except ``dashboard_data.json`` and
  ``index.html``; the final ``manifest.json`` records those two as well.
- ``management`` is ``{"status": "NOT_RUN", "reason": ...}`` when the management station did
  not run, never null: the dashboard says why instead of guessing.
- ``handover.finbank_todo`` comes from the ``not_verifiable`` steps of the labeling funnel;
  ``config/handover.yaml`` only holds the runbook steps, so nothing is written twice.
- ``write_dashboard_data`` refuses data that breaks ``dashboard_data_v1``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from src.predict360.config import CONFIG_DIR, load_assumptions, load_contract
from src.predict360.dashboard_contract import CONTRACT, validate_dashboard_data
from src.predict360.lineage import _iso, _utc, log_head_sha256, verify_lineage_log
from src.predict360.risk_register import DEFAULT_REGISTER, DEFAULT_REVIEWS
from src.predict360.sprint_metrics import calculate_velocity

HANDOVER_PATH = CONFIG_DIR / "handover.yaml"
DASHBOARD_OUTPUTS = ("dashboard_data.json", "index.html")
NOT_RUN_HOURS_LOG = "hours_log failed Gate 1"
NOT_RUN_NO_HOURS_LOG = "no hours_log configured"
RISK_FIELDS = ("risk_id", "category", "description", "probability", "impact", "owner", "status")
FAILED_RULE_FIELDS = ("rule", "column", "critical", "unexpected_count", "unexpected_pct", "waived_by")
WAIVER_FIELDS = ("id", "table", "column", "rule", "risk", "reason", "approved_by", "date", "expires")


def _read(run_dir: Path, name: str) -> dict:
    return json.loads((run_dir / name).read_text(encoding="utf-8"))


def _gate1(report: dict) -> dict:
    tables = {}
    for name, table in report["tables"].items():
        failed = [{k: r.get(k) for k in FAILED_RULE_FIELDS} for r in table["results"] if not r["success"]]
        tables[name] = {"status": table["status"], "rows": table["rows"], "failed_rules": failed}
    return {"status": report["status"], "tables": tables}


def _log_status(log_path: Path, runs_dir: Path | None) -> str:
    """The chain this run will append to; runs_dir also checks each manifest (official log)."""
    if not log_path.exists() or not log_path.read_text(encoding="utf-8").strip():
        return "NOT_CHECKED"
    return verify_lineage_log(log_path, runs_dir)["status"]


def _management(run_dir: Path, cfg: dict, gate1: dict, sprint_log: Path | None,
                risk_register: Path, risk_reviews: Path) -> dict:
    if not (run_dir / "management.json").exists():
        configured = (cfg.get("management") or {}).get("hours_log")
        failed = gate1["tables"].get("hours_log", {}).get("status") == "FAIL"
        return {"status": "NOT_RUN", "reason": NOT_RUN_HOURS_LOG if configured and failed else NOT_RUN_NO_HOURS_LOG}
    management = _read(run_dir, "management.json")
    velocity = calculate_velocity(pd.read_csv(sprint_log)).to_dict("records")
    register = pd.read_csv(risk_register, dtype=str).fillna("")
    return {
        "status": "RUN",
        **{k: management[k] for k in ("baseline", "sprints", "cumulative", "hours_outside_reported_sprints")},
        "velocity": [{"sprint": int(v["sprint"]), "planned_sp": float(v["planned_sp"]),
                      "completed_sp": float(v["completed_sp"]),
                      "completion_rate_pct": float(v["completion_rate_pct"])} for v in velocity],
        "risks": [{k: row[k] for k in RISK_FIELDS} for row in register.to_dict("records")],
        "risk_reviews_count": len(pd.read_csv(risk_reviews)),
    }


def _handover(funnel: dict, handover_path: Path) -> dict:
    runbook = yaml.safe_load(Path(handover_path).read_text(encoding="utf-8"))
    steps = [{"step": n, "title": s["title"], "status": s["status"]}
             for n, s in enumerate(runbook["steps"], start=1)]
    todo = [f"{table}_v2: add {step['missing_column']} (needed to verify {step['step']})"
            for table, report in funnel.items() for step in report["steps"]
            if step.get("status") == "not_verifiable"]
    return {"steps": steps, "finbank_todo": todo}


def build_dashboard_data(run_dir: str | Path, manifest: dict, cfg: dict, *, log_path: str | Path,
                         verify_runs_dir: str | Path | None = None, now=None,
                         assumptions_path: str | Path = CONFIG_DIR / "assumptions.yaml",
                         sprint_log: str | Path | None = None, risk_register: str | Path = DEFAULT_REGISTER,
                         risk_reviews: str | Path = DEFAULT_REVIEWS,
                         handover_path: str | Path = HANDOVER_PATH) -> dict:
    """The dashboard_data_v1 document of an open run (its aggregate outputs already written)."""
    run_dir, log_path = Path(run_dir), Path(log_path)
    gate1, gate2, gate3 = (_read(run_dir, n) for n in ("gate1.json", "gate2.json", "consistency.json"))
    evaluation = _read(run_dir, "evaluation.json")
    funnel = _read(run_dir, "labeling_funnel.json")
    assumptions = load_assumptions(assumptions_path)
    exported_at = _iso(_utc(now))
    return {
        "meta": {
            "run_id": manifest["run_id"],
            "generated_at": exported_at,
            "synthetic": cfg["synthetic"],
            "sample": False,
            "scores_simulated": cfg["synthetic"],
            "commit": manifest["commit"],
            "code_version": manifest["code_version"],
            "config": manifest["config"],
            "snapshot_date": manifest["snapshot_date"],
            "contract_versions": {**manifest["contract_versions"],
                                  "model_card": load_contract("model_card_v1")["version"],
                                  "dashboard_data": load_contract(CONTRACT)["version"]},
        },
        "exposure": _read(run_dir, "reconciliation.json"),
        "gates": {
            "gate1": _gate1(gate1),
            "gate2": {k: gate2[k] for k in ("status", "counts", "failures")},
            "gate3": {k: gate3[k] for k in ("status", "checked", "figures_checked", "citations_checked",
                                            "require_citations", "warnings", "mismatches")},
        },
        "quality": {
            "missing": {name: table["missing"] for name, table in gate1["tables"].items()},
            "waivers": [{k: str(w[k]) for k in WAIVER_FIELDS} for w in manifest["waivers"]],
            "labeling_funnel": funnel,
        },
        "lineage": {
            "manifest": {   # snapshot at export: the final manifest also records this file and the page
                "run_id": manifest["run_id"],
                "created_at": manifest["created_at"],
                "closed_at": exported_at,
                "lineage_head_sha256": log_head_sha256(log_path),
                "scores_sha256": manifest["scores_sha256"],
                "sources": list(manifest["sources"]),
                "outputs": list(manifest["outputs"]),
            },
            "log_status": _log_status(log_path, Path(verify_runs_dir) if verify_runs_dir else None),
            "figures": list(manifest["figures"]),
        },
        "models": {"cards": gate2["cards"], "evaluations": evaluation["evaluations"],
                   "decisions": evaluation["decisions"]},
        "assumptions": [{"id": i["id"], "name": i["name"], "type": i["type"], "value": i["value"],
                         "rationale": i["rationale"]} for i in assumptions["items"]],
        "management": _management(run_dir, cfg, gate1, Path(sprint_log) if sprint_log else None,
                                  Path(risk_register), Path(risk_reviews)),
        "handover": _handover(funnel, Path(handover_path)),
    }


def write_dashboard_data(data: dict, path: str | Path) -> Path:
    """Writes the document only if it meets dashboard_data_v1."""
    errors = validate_dashboard_data(data)
    if errors:
        raise ValueError(f"{CONTRACT}: " + "; ".join(errors[:5]))
    path = Path(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8",
                    newline="\n")
    return path
