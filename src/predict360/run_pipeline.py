"""One command for the whole system (technical spec, section 9): ``run_pipeline.py --config``.

Stations, in order: load the config, hash the sources, Gate 1, reconciliation, labeling
(funnel only), Gate 2, evaluation and verdict, project management, figure registry,
Gate 3, evidence record (acta), and closing the manifest with its lineage log entry.
Everything goes to ``runs/<run_id>/`` and only aggregates are written: the curated and
labeled tables are client rows and never leave memory, not even synthetic ones.

- A data table (delinquency, churn, scores) failing Gate 1 stops the run after Gate 1.
  A failing hours log only leaves the management station NOT_RUN.
- An ordinary run exits 0 when it completes (its gates may still FAIL and say so) and 1
  when it stops. CI runs it on every merge as a test only.

Official demo run (``--official``), the only run that is versioned:
- refused before running if the commit is ``-dirty`` or ``unknown`` or the config is not
  synthetic (``OfficialRunRefused``);
- Gate 3 runs in strict mode (citations required) and the three gates must not FAIL;
  otherwise it is kept as an ordinary run and exits 1;
- when it passes, its folder moves to ``runs/official/<run_id>/`` and its entry goes to
  ``runs/official/lineage_log.jsonl``, separate from the local log of each computer.
Order: clean code on main -> ``--official`` (the manifest records that commit) -> a commit
``chore: official demo run <run_id>`` that only adds the folder.

Usage:
    python -m src.predict360.run_pipeline --config config/synthetic.yaml [--official]
        [--require-citations] [--citations docs/cited_figures.yaml] [--runs-dir runs]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.predict360.config import CONFIG_DIR, ROOT, load_assumptions, load_config
from src.predict360.consistency import CITATIONS_PATH, run_gate3
from src.predict360.evaluator import evaluate_models
from src.predict360.labeling import label_all
from src.predict360.budget_schedule import budget_schedule
from src.predict360.lineage import (add_output, add_source, git_commit, record_gate, register_figure,
                                    start_manifest, write_manifest)
from src.predict360.model_card import run_gate2
from src.predict360.quality import run_gate1
from src.predict360.reconcile import reconcile_all

ASSUMPTIONS_PATH = CONFIG_DIR / "assumptions.yaml"
DATA_TABLES = ("delinquency", "churn", "scores")
AGGREGATE_OUTPUTS = ("gate1.json", "reconciliation.json", "labeling_funnel.json", "gate2.json",
                     "evaluation.json", "management.json", "consistency.json", "evidence_record.json")
OFFICIAL_DIR = "official"
LOG_NAME = "lineage_log.jsonl"
STRONGEST_VERDICT = ("authorized_for_shadow_deployment: shadow, pilot and approval are criteria and a plan "
                     "for FinBank, decided and signed by its committee")
MANAGEMENT_FIGURES = (("pv_cop_m", "COP_m"), ("ev_cop_m", "COP_m"), ("ac_cop_m", "COP_m"), ("spi", "ratio"),
                      ("cpi", "ratio"), ("eac_cop_m", "COP_m"))


class OfficialRunRefused(Exception):
    """The official demo run cannot start: uncommitted or unknown code, or real data."""


def _write(manifest: dict, run_dir: Path, name: str, data) -> None:
    path = run_dir / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8",
                    newline="\n")
    add_output(manifest, path, base=run_dir)


def _register_figures(manifest: dict, reconciliation: dict, evaluation: dict, management: dict | None) -> None:
    for table in reconciliation["tables"]:
        register_figure(manifest, f"exposure.{table}.observed_cop_m", reconciliation["tables"][table]["actual_cop_m"],
                        "COP_m", "reconciliation.json", "src/predict360/reconcile.py",
                        f"tables.{table}.actual_cop_m")
    for e in evaluation["evaluations"]:
        if e["status"] != "evaluated":
            continue
        base, select = f"models.{e['label']}.{e['model_id']}", f"evaluations[model_id={e['model_id']},label={e['label']}]"
        figures = [("net_value_at_k_cop_m", e["at_k"]["net_value_cop_m"], "COP_m", "at_k.net_value_cop_m"),
                   ("capture_at_k", e["at_k"]["capture"], "share", "at_k.capture")]
        if e["vs_baseline"]:
            figures += [(f"{name}_vs_baseline_cop_m", e["vs_baseline"][key], "COP_m", f"vs_baseline.{key}")
                        for name, key in (("difference", "difference_cop_m"), ("ci_low", "ci_low_cop_m"),
                                          ("ci_high", "ci_high_cop_m"))]
        for name, value, unit, path in figures:
            if value is not None:
                register_figure(manifest, f"{base}.{name}", value, unit, "evaluation.json",
                                "src/predict360/evaluator.py", f"{select}.{path}")
    if management:
        for key, unit in MANAGEMENT_FIGURES:
            value = management["cumulative"].get(key)
            if value is not None:
                register_figure(manifest, f"management.cumulative.{key}", value, unit, "management.json",
                                "src/predict360/budget_schedule.py", f"cumulative.{key}")


def _evidence_record(manifest: dict, cfg: dict, values: dict, gates: dict, evaluation: dict, official: bool) -> dict:
    promotion = values["promotion"]
    assumptions_sha = next(s["sha256"] for s in manifest["sources"] if s["name"] == "assumptions")
    gate3 = gates["gate3"]
    decisions = []
    for d in evaluation["decisions"]:
        comparisons = [{"model_id": e["model_id"], "label": e["label"], **{k: e["vs_baseline"][k] for k in (
                        "difference_cop_m", "ci_low_cop_m", "ci_high_cop_m", "outcome")}}
                       for e in evaluation["evaluations"]
                       if e["target"] == d["target"] and e["status"] == "evaluated" and e["vs_baseline"]]
        decisions.append({**{k: d[k] for k in ("target", "verdict", "reason_code", "model_id", "reason")},
                          "comparisons": comparisons})
    return {
        "run_id": manifest["run_id"],
        "generated_at": manifest["created_at"],
        "commit": manifest["commit"],
        "code_version": manifest["code_version"],
        "config": manifest["config"],
        "synthetic": cfg["synthetic"],
        "scores_simulated": cfg["synthetic"],
        "official": official,
        "gates": {
            "gate1": {"status": gates["gate1"]["status"],
                      "tables": {n: t["status"] for n, t in gates["gate1"]["tables"].items()}},
            "gate2": {k: gates["gate2"][k] for k in ("status", "counts", "failures")},
            "gate3": {"status": gate3["status"], "figures_checked": gate3["figures_checked"],
                      "citations_checked": gate3["citations_checked"],
                      "require_citations": gate3["require_citations"], "mismatches": len(gate3["mismatches"])},
        },
        "decision_criterion": {
            "rule": promotion["beat_baseline_rule"],
            "margin_cop_m": promotion["margin_cop_m"],
            "confidence_level": promotion["confidence_level"],
            "bootstrap_samples": promotion["bootstrap_samples"],
            "bootstrap_seed": promotion["bootstrap_seed"],
            "capacity_share": values["value"]["default_capacity_share"],
            "delinquency_horizons_days": values["delinquency"]["horizons_days"],
            "assumptions_sha256": assumptions_sha,
            "note": ("Fixed in config/assumptions.yaml (A11, A16) before the evaluation ran; the hash records "
                     "which values were used."),
        },
        "decisions": decisions,
        "waivers": [w["id"] for w in manifest["waivers"]],
        "strongest_possible_verdict": STRONGEST_VERDICT,
    }


def run_pipeline(config_path: str | Path = CONFIG_DIR / "synthetic.yaml", *, official: bool = False,
                 require_citations: bool = False, runs_dir: str | Path | None = None,
                 data_dir: str | Path | None = None, citations_path: str | Path = CITATIONS_PATH,
                 commit: str | None = None, now: datetime | None = None, as_of: date | None = None) -> dict:
    cfg = load_config(config_path)
    commit = commit if commit is not None else git_commit()
    if official:
        if commit == "unknown" or commit.endswith("-dirty"):
            raise OfficialRunRefused(f"the official run needs committed code on a clean tree; commit is {commit}")
        if not cfg["synthetic"]:
            raise OfficialRunRefused("the official demo run is synthetic only; real data never leaves FinBank")
    runs_dir = Path(runs_dir) if runs_dir is not None else ROOT / cfg["paths"]["runs_dir"]
    data_dir = Path(data_dir) if data_dir is not None else ROOT / cfg["paths"]["input_dir"]
    values = load_assumptions(ASSUMPTIONS_PATH)["values"]

    manifest = start_manifest(cfg, config_path, now=now, commit=commit)
    manifest["official"] = False
    manifest["stations"] = {}
    run_dir = runs_dir / manifest["run_id"]
    run_dir.mkdir(parents=True)
    for name in DATA_TABLES:
        add_source(manifest, name, data_dir / cfg["sources"][name])
    add_source(manifest, "config", config_path)
    add_source(manifest, "assumptions", ASSUMPTIONS_PATH)
    if Path(citations_path).exists():
        add_source(manifest, "citations", citations_path)
    result = {"run_id": manifest["run_id"], "official": False, "stopped_at": None, "refused": []}

    gate1 = run_gate1(cfg, data_dir, as_of)
    _write(manifest, run_dir, "gate1.json", gate1)
    record_gate(manifest, gate1, cfg)
    if any(gate1["tables"][name]["status"] == "FAIL" for name in DATA_TABLES):
        result.update(stopped_at="gate1", refused=["gate1"] if official else [])
        write_manifest(manifest, runs_dir, runs_dir / LOG_NAME, now=now)
        return {**result, "run_dir": run_dir, "exit_code": 1, "gates": manifest["gates"]}

    delinquency = pd.read_csv(data_dir / cfg["sources"]["delinquency"])
    churn = pd.read_csv(data_dir / cfg["sources"]["churn"])
    reconciliation = reconcile_all(cfg, delinquency, churn)
    _write(manifest, run_dir, "reconciliation.json", reconciliation)
    labeled = label_all(delinquency, churn, str(cfg["snapshot_date"]), ASSUMPTIONS_PATH)
    _write(manifest, run_dir, "labeling_funnel.json", {t: labeled[t]["funnel"] for t in labeled})

    scores_path = data_dir / cfg["sources"]["scores"]
    gate2 = run_gate2(cfg, data_dir / "model_cards", scores_path)
    _write(manifest, run_dir, "gate2.json", gate2)
    record_gate(manifest, gate2, cfg)
    evaluation = evaluate_models(labeled, pd.read_csv(scores_path), gate2, values, cfg["gate2"]["baseline_models"])
    _write(manifest, run_dir, "evaluation.json", evaluation)

    management = None
    hours = (cfg.get("management") or {}).get("hours_log")
    if hours and gate1["tables"].get("hours_log", {}).get("status") != "FAIL":
        management = budget_schedule(pd.read_csv(ROOT / hours), pd.read_csv(ROOT / cfg["management"]["sprint_log"]),
                                     values)
        _write(manifest, run_dir, "management.json", management)
    manifest["stations"]["management"] = "RUN" if management else "NOT_RUN"

    _register_figures(manifest, reconciliation, evaluation, management)
    gate3 = run_gate3(manifest, run_dir, citations_path, require_citations=require_citations or official)
    _write(manifest, run_dir, "consistency.json", gate3)
    record_gate(manifest, gate3, cfg)

    gates = {"gate1": gate1, "gate2": gate2, "gate3": gate3}
    if official:
        result["refused"] = [name for name, report in gates.items() if report["status"] == "FAIL"]
    is_official = official and not result["refused"]
    manifest["official"] = is_official
    _write(manifest, run_dir, "evidence_record.json",
           _evidence_record(manifest, cfg, values, gates, evaluation, is_official))

    if is_official:
        official_dir = runs_dir / OFFICIAL_DIR
        official_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(shutil.move(str(run_dir), str(official_dir / manifest["run_id"])))
        write_manifest(manifest, official_dir, official_dir / LOG_NAME, now=now)
    else:
        write_manifest(manifest, runs_dir, runs_dir / LOG_NAME, now=now)
    return {**result, "official": is_official, "run_dir": run_dir, "exit_code": 1 if result["refused"] else 0,
            "gates": manifest["gates"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Predict360 pipeline end to end.")
    parser.add_argument("--config", default=str(CONFIG_DIR / "synthetic.yaml"))
    parser.add_argument("--official", action="store_true", help="the versioned demo run (strict, clean commit)")
    parser.add_argument("--require-citations", action="store_true", help="Gate 3 fails without citations")
    parser.add_argument("--citations", default=str(CITATIONS_PATH))
    parser.add_argument("--runs-dir", default=None)
    args = parser.parse_args(argv)
    try:
        result = run_pipeline(args.config, official=args.official, require_citations=args.require_citations,
                              runs_dir=args.runs_dir, citations_path=args.citations)
    except OfficialRunRefused as error:
        print(f"Official run refused: {error}", file=sys.stderr)
        return 2
    gates = ", ".join(f"{name} {gate['status']}" for name, gate in result["gates"].items())
    print(f"Run {result['run_id']} -> {result['run_dir']} ({gates})")
    if result["stopped_at"]:
        print(f"Stopped at {result['stopped_at']}: a data table failed its contract.", file=sys.stderr)
    if result["refused"]:
        print(f"Not official: {', '.join(result['refused'])} failed; kept as an ordinary run.", file=sys.stderr)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
