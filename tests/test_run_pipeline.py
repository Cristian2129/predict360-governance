"""Tests for run_pipeline.py (technical spec, section 9): one command, twelve stations, runs/<run_id>/.

The official demo run (--official) is versioned under runs/official/<run_id>/ with aggregates
only; every other run stays in the git-ignored runs/ folder.
"""
import json
import subprocess
from datetime import date, datetime, timezone

import pandas as pd
import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT, load_assumptions
from src.predict360.make_synthetic import generate_synthetic_data
from src.predict360.run_pipeline import AGGREGATE_OUTPUTS, OfficialRunRefused, main, run_pipeline

SYNTHETIC = CONFIG_DIR / "synthetic.yaml"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"
COMMIT = "a" * 40
NOW = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 11, 14)
HOURS = """date,person,sprint,story_id,hours,estimated,note
2026-10-30,Cristian Vega,2,US-07,12,1,reconstructed
2026-11-11,Cristian Vega,3,US-10,4,0,dashboard
2026-11-12,Paula Gacha,3,US-05,5,0,evaluator
2026-11-12,Marco Jimenez,3,MGMT,2,0,consolidation
"""


def _config(tmp_path, hours=HOURS):
    """synthetic.yaml with the hours log in tmp_path (the repository log is still empty)."""
    cfg = yaml.safe_load(SYNTHETIC.read_text(encoding="utf-8"))
    hours_path = tmp_path / "hours_log.csv"
    hours_path.write_text(hours, encoding="utf-8")
    cfg["management"]["hours_log"] = str(hours_path)
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _citations(tmp_path, items=None):
    items = items if items is not None else [{"figure_id": "exposure.delinquency.observed_cop_m",
                                              "text": "COP 58.800 M", "locale": "es", "where": "slide 2"}]
    path = tmp_path / "cited_figures.yaml"
    path.write_text(yaml.safe_dump({"version": "v1", "citations": items}, allow_unicode=True), encoding="utf-8")
    return path


def _run(tmp_path, **kwargs):
    # Defaults are built only when missing: building them always would overwrite the
    # hours log or citations file that the test prepared in the same folder
    if "config_path" not in kwargs:
        kwargs["config_path"] = _config(tmp_path)
    if "citations_path" not in kwargs:
        kwargs["citations_path"] = _citations(tmp_path, [])
    kwargs.setdefault("runs_dir", tmp_path / "runs")
    return run_pipeline(commit=kwargs.pop("commit", COMMIT), now=NOW, as_of=AS_OF, **kwargs)


def _files(run_dir):
    return {p.name for p in run_dir.iterdir()}


@pytest.fixture(scope="module")
def ordinary(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("ordinary")
    return _run(tmp_path)


# --- an ordinary synthetic run ----------------------------------------------------------

def test_run_completes_and_writes_only_aggregates(ordinary):
    assert ordinary["exit_code"] == 0 and ordinary["official"] is False
    assert _files(ordinary["run_dir"]) == set(AGGREGATE_OUTPUTS) | {"manifest.json"}
    assert "labeled" not in " ".join(AGGREGATE_OUTPUTS) and "curated" not in " ".join(AGGREGATE_OUTPUTS)


def test_no_client_identifier_reaches_any_output(ordinary):
    ids = set()
    for name in ("delinquency_sample.csv", "churn_sample.csv"):
        ids |= set(pd.read_csv(SYNTHETIC_DIR / name)["client_id"].head(50))
    for path in ordinary["run_dir"].iterdir():
        text = path.read_text(encoding="utf-8")
        assert not any(client_id in text for client_id in ids), path.name


def test_manifest_is_closed_with_outputs_figures_and_gate_detail(ordinary):
    manifest = json.loads((ordinary["run_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["closed_at"] and manifest["commit"] == COMMIT
    assert {o["file"] for o in manifest["outputs"]} == set(AGGREGATE_OUTPUTS)
    assert manifest["gates"]["gate1"]["status"] == "PASS_WITH_WAIVERS"
    assert manifest["gates"]["gate1"]["tables"] == {"delinquency": "PASS", "churn": "PASS_WITH_WAIVERS",
                                                    "scores": "PASS", "hours_log": "PASS"}
    assert manifest["gates"]["gate2"]["status"] == "PASS"
    assert manifest["gates"]["gate3"]["status"] == "PASS"
    assert {s["name"] for s in manifest["sources"]} >= {"delinquency", "churn", "scores", "config", "assumptions",
                                                        "citations"}
    figures = {f["figure_id"]: f for f in manifest["figures"]}
    assert figures["exposure.delinquency.observed_cop_m"]["value"] == pytest.approx(58800.0)
    assert "models.delinquency_30.model_a.net_value_at_k_cop_m" in figures
    assert all("[" in f["path"] for f in manifest["figures"] if f["file"] == "evaluation.json")
    assert manifest["stations"]["management"] == "RUN"


def test_gate3_without_citations_passes_with_a_warning(ordinary):
    report = json.loads((ordinary["run_dir"] / "consistency.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS" and report["warnings"] and report["require_citations"] is False


def test_runs_are_reproducible(ordinary, tmp_path):
    again = _run(tmp_path)
    read = lambda r: {f["figure_id"]: f["value"] for f in
                      json.loads((r["run_dir"] / "manifest.json").read_text(encoding="utf-8"))["figures"]}
    assert read(again) == read(ordinary)


# --- the evidence record (acta) -----------------------------------------------------------

def test_evidence_record_states_the_criterion_fixed_before_the_result(ordinary):
    record = json.loads((ordinary["run_dir"] / "evidence_record.json").read_text(encoding="utf-8"))
    promotion = load_assumptions()["values"]["promotion"]
    criterion = record["decision_criterion"]
    assert criterion["confidence_level"] == promotion["confidence_level"]
    assert criterion["bootstrap_samples"] == promotion["bootstrap_samples"]
    assert criterion["bootstrap_seed"] == promotion["bootstrap_seed"]
    assert criterion["margin_cop_m"] == promotion["margin_cop_m"]
    assert criterion["assumptions_sha256"] and record["run_id"] == ordinary["run_id"]
    assert record["synthetic"] is True and record["scores_simulated"] is True and record["official"] is False


def test_evidence_record_explains_each_verdict_with_point_difference_and_interval(ordinary):
    record = json.loads((ordinary["run_dir"] / "evidence_record.json").read_text(encoding="utf-8"))
    decisions = {d["target"]: d for d in record["decisions"]}
    assert set(decisions) == {"delinquency", "churn"}
    for decision in decisions.values():
        assert decision["reason_code"]
        for comparison in decision["comparisons"]:
            assert {"model_id", "label", "difference_cop_m", "ci_low_cop_m", "ci_high_cop_m", "outcome"} <= set(comparison)
    assert "shadow" in record["strongest_possible_verdict"]
    assert "production" not in json.dumps(record).lower()


# --- Gate 1 stops the run; the hours log only stops management --------------------------------

def test_a_failing_data_table_stops_the_run_after_gate1(tmp_path, monkeypatch):
    monkeypatch.delenv("PREDICT360_HMAC_KEY", raising=False)
    data_dir = tmp_path / "defect"
    generate_synthetic_data(config=SYNTHETIC, output_dir=data_dir, defect="critical_nulls")
    result = _run(tmp_path, data_dir=data_dir)
    assert result["exit_code"] == 1 and result["stopped_at"] == "gate1"
    assert _files(result["run_dir"]) == {"gate1.json", "manifest.json"}
    manifest = json.loads((result["run_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["gates"]["gate1"]["status"] == "FAIL"
    assert "FAIL" in manifest["gates"]["gate1"]["tables"].values()


def test_a_failing_hours_log_leaves_management_not_run(tmp_path):
    result = _run(tmp_path, config_path=_config(tmp_path, hours="date,person,sprint,story_id,hours,estimated,note\n"))
    assert result["exit_code"] == 0 and "evaluation.json" in _files(result["run_dir"])
    assert "management.json" not in _files(result["run_dir"])
    manifest = json.loads((result["run_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["gates"]["gate1"]["status"] == "FAIL"
    assert manifest["gates"]["gate1"]["tables"]["hours_log"] == "FAIL"
    assert manifest["stations"]["management"] == "NOT_RUN"


# --- the official demo run ------------------------------------------------------------------------

@pytest.mark.parametrize("commit", [COMMIT + "-dirty", "unknown"])
def test_official_refuses_uncommitted_or_unknown_code_before_running(tmp_path, commit):
    with pytest.raises(OfficialRunRefused, match="commit"):
        _run(tmp_path, official=True, commit=commit, citations_path=_citations(tmp_path))
    assert not (tmp_path / "runs").exists()


def test_official_refuses_real_data(tmp_path):
    with pytest.raises(OfficialRunRefused, match="synthetic"):
        _run(tmp_path, official=True, config_path=CONFIG_DIR / "real.yaml", citations_path=_citations(tmp_path))
    assert not (tmp_path / "runs").exists()


def test_official_without_citations_is_refused_and_kept_as_an_ordinary_run(tmp_path):
    result = _run(tmp_path, official=True)
    assert result["exit_code"] == 1 and result["official"] is False
    assert "gate3" in result["refused"]
    assert not (tmp_path / "runs" / "official").exists()
    assert (tmp_path / "runs" / "lineage_log.jsonl").exists()


def test_official_with_gate1_failing_is_refused(tmp_path):
    empty = "date,person,sprint,story_id,hours,estimated,note\n"
    result = _run(tmp_path, official=True, config_path=_config(tmp_path, hours=empty),
                  citations_path=_citations(tmp_path))
    assert result["exit_code"] == 1 and "gate1" in result["refused"]
    assert not (tmp_path / "runs" / "official").exists()


def test_official_run_goes_to_its_own_folder_and_log(tmp_path):
    result = _run(tmp_path, official=True, citations_path=_citations(tmp_path))
    official = tmp_path / "runs" / "official"
    assert result["exit_code"] == 0 and result["official"] is True
    assert result["run_dir"] == official / result["run_id"]
    assert _files(result["run_dir"]) == set(AGGREGATE_OUTPUTS) | {"manifest.json"}
    assert (official / "lineage_log.jsonl").exists()
    assert not (tmp_path / "runs" / "lineage_log.jsonl").exists()      # the local log stays separate
    assert not (tmp_path / "runs" / result["run_id"]).exists()
    record = json.loads((result["run_dir"] / "evidence_record.json").read_text(encoding="utf-8"))
    consistency = json.loads((result["run_dir"] / "consistency.json").read_text(encoding="utf-8"))
    assert record["official"] is True and consistency["require_citations"] is True
    assert consistency["citations_checked"] == 1


# --- repository wiring -------------------------------------------------------------------------------

@pytest.mark.parametrize("path,ignored", [
    ("runs/20261114T1800-a1b2c3/evaluation.json", True),
    ("runs/lineage_log.jsonl", True),
    ("runs/adhoc/dashboard/index.html", True),
    ("runs/official/20261114T1800-a1b2c3/evaluation.json", False),
    ("runs/official/lineage_log.jsonl", False),
])
def test_only_the_official_runs_are_versioned(path, ignored):
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    assert (result.returncode == 0) is ignored, path


def test_cli_runs_the_pipeline(tmp_path):
    code = main(["--config", str(_config(tmp_path)), "--runs-dir", str(tmp_path / "runs"),
                 "--citations", str(_citations(tmp_path, []))])
    assert code == 0
    assert len(list((tmp_path / "runs").glob("*/manifest.json"))) == 1


def test_ci_runs_the_synthetic_pipeline_as_a_test():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "src.predict360.run_pipeline" in workflow and "--official" not in workflow
