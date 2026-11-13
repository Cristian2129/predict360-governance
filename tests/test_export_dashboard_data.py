"""Tests for export_dashboard_data.py (technical spec, section 11; US-10, B11b).

The pipeline writes dashboard_data.json and index.html inside its own run folder, before the
manifest closes. Every value comes from the run's aggregate outputs: nothing is recomputed.
"""
import hashlib
import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT
from src.predict360.dashboard_contract import SAMPLE_PATH, validate_dashboard_data
from src.predict360.export_dashboard_data import (DASHBOARD_OUTPUTS, HANDOVER_PATH, NOT_RUN_HOURS_LOG,
                                                  write_dashboard_data)
from src.predict360.run_pipeline import AGGREGATE_OUTPUTS, run_pipeline

SYNTHETIC = CONFIG_DIR / "synthetic.yaml"
COMMIT = "b" * 40
NOW = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 11, 14)
HEADER = "date,person,sprint,story_id,hours,estimated,note\n"
HOURS = HEADER + "2026-10-30,Cristian Vega,2,US-07,12,1,reconstructed\n2026-11-12,Paula Gacha,3,US-05,5,0,evaluator\n"


def _config(tmp_path, hours=HOURS):
    cfg = yaml.safe_load(SYNTHETIC.read_text(encoding="utf-8"))
    hours_path = tmp_path / "hours_log.csv"
    hours_path.write_text(hours, encoding="utf-8")
    cfg["management"]["hours_log"] = str(hours_path)
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _citations(tmp_path, items):
    path = tmp_path / "cited_figures.yaml"
    path.write_text(yaml.safe_dump({"version": "v1", "citations": items}, allow_unicode=True), encoding="utf-8")
    return path


def _run(tmp_path, hours=HOURS, citations=(), **kwargs):
    kwargs.setdefault("runs_dir", tmp_path / "runs")
    return run_pipeline(_config(tmp_path, hours), citations_path=_citations(tmp_path, list(citations)),
                        commit=COMMIT, now=NOW, as_of=AS_OF, **kwargs)


def _read(run_dir, name):
    return json.loads((run_dir / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ordinary(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("export"))


@pytest.fixture(scope="module")
def data(ordinary):
    return _read(ordinary["run_dir"], "dashboard_data.json")


# --- written inside the run, meeting the contract -------------------------------------------

def test_the_run_writes_the_dashboard_data_and_page(ordinary):
    assert DASHBOARD_OUTPUTS == ("dashboard_data.json", "index.html")
    files = {p.name for p in ordinary["run_dir"].iterdir()}
    assert files == set(AGGREGATE_OUTPUTS) | set(DASHBOARD_OUTPUTS) | {"manifest.json"}


def test_dashboard_data_meets_the_contract_and_is_not_a_sample(data, ordinary):
    assert validate_dashboard_data(data) == []
    assert data["meta"]["sample"] is False and data["meta"]["run_id"] == ordinary["run_id"]
    assert data["meta"]["synthetic"] is True and data["meta"]["scores_simulated"] is True
    assert data["meta"]["commit"] == COMMIT
    assert data["meta"]["contract_versions"]["dashboard_data"] == "v1"


def test_values_are_copied_from_the_outputs_not_recomputed(data, ordinary):
    run_dir = ordinary["run_dir"]
    assert data["exposure"] == _read(run_dir, "reconciliation.json")
    evaluation = _read(run_dir, "evaluation.json")
    assert data["models"]["evaluations"] == evaluation["evaluations"]
    assert data["models"]["decisions"] == evaluation["decisions"]
    assert data["models"]["cards"] == _read(run_dir, "gate2.json")["cards"]
    assert data["quality"]["labeling_funnel"] == _read(run_dir, "labeling_funnel.json")
    management = _read(run_dir, "management.json")
    for key in ("baseline", "sprints", "cumulative", "hours_outside_reported_sprints"):
        assert data["management"][key] == management[key]
    assert data["lineage"]["figures"] == _read(run_dir, "manifest.json")["figures"]


def test_gates_summarise_the_gate_reports(data, ordinary):
    gate1 = _read(ordinary["run_dir"], "gate1.json")
    assert data["gates"]["gate1"]["status"] == gate1["status"]
    churn = data["gates"]["gate1"]["tables"]["churn"]
    assert churn["status"] == "PASS_WITH_WAIVERS" and churn["rows"] == 200
    assert [(r["column"], r["waived_by"]) for r in churn["failed_rules"]] == [("tenure_months", "W-01")]
    gate3 = _read(ordinary["run_dir"], "consistency.json")
    assert data["gates"]["gate3"]["status"] == gate3["status"]
    assert data["gates"]["gate3"]["mismatches"] == gate3["mismatches"]
    assert data["quality"]["missing"]["churn"]["tenure_months"]["count"] == 24
    assert [w["id"] for w in data["quality"]["waivers"]] == ["W-01"]


# --- the manifest snapshot and the final manifest --------------------------------------------

def test_the_lineage_section_is_a_snapshot_taken_at_export(data):
    snapshot = data["lineage"]["manifest"]
    # A file cannot carry its own hash: the snapshot lists the outputs written before the export
    assert {o["file"] for o in snapshot["outputs"]} == set(AGGREGATE_OUTPUTS)
    assert snapshot["closed_at"] == "2026-11-14T18:00:00Z"


def test_the_final_manifest_hashes_the_dashboard_files(ordinary):
    manifest = _read(ordinary["run_dir"], "manifest.json")
    outputs = {o["file"]: o for o in manifest["outputs"]}
    assert set(outputs) == set(AGGREGATE_OUTPUTS) | set(DASHBOARD_OUTPUTS)
    for name in DASHBOARD_OUTPUTS:
        digest = hashlib.sha256((ordinary["run_dir"] / name).read_bytes()).hexdigest()
        assert outputs[name]["sha256"] == digest


def test_management_inputs_are_hashed_as_sources(ordinary):
    names = {s["name"] for s in _read(ordinary["run_dir"], "manifest.json")["sources"]}
    assert {"hours_log", "sprint_log", "risk_register", "risk_reviews", "handover"} <= names


@pytest.mark.parametrize("before,expected", [(None, "NOT_CHECKED"), ("chain", "OK"), ("garbage", "TAMPERED")])
def test_log_status_checks_the_log_the_run_appends_to(tmp_path, before, expected):
    runs = tmp_path / "runs"
    if before == "chain":
        (tmp_path / "first").mkdir()
        _run(tmp_path / "first", runs_dir=runs)          # a previous run leaves an intact log
    elif before == "garbage":
        runs.mkdir()
        (runs / "lineage_log.jsonl").write_text('{"run_id": "x", "prev_entry_sha256": "nope"}\n', encoding="utf-8")
    result = _run(tmp_path, runs_dir=runs)
    assert _read(result["run_dir"], "dashboard_data.json")["lineage"]["log_status"] == expected


# --- the page ---------------------------------------------------------------------------------------

def test_index_html_is_rendered_from_this_run(ordinary):
    html = (ordinary["run_dir"] / "index.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and ordinary["run_id"] in html
    assert 'id="banner-sample"' not in html and 'id="banner-synthetic"' in html


# --- management that did not run --------------------------------------------------------------------

def test_management_that_did_not_run_says_why(tmp_path):
    result = _run(tmp_path, hours=HEADER)
    data = _read(result["run_dir"], "dashboard_data.json")
    assert NOT_RUN_HOURS_LOG == "hours_log failed Gate 1"
    assert data["management"] == {"status": "NOT_RUN", "reason": NOT_RUN_HOURS_LOG}
    assert validate_dashboard_data(data) == []


def test_management_carries_velocity_risks_and_the_review_count(data):
    management = data["management"]
    assert management["status"] == "RUN"
    sprint_log = pd.read_csv(ROOT / "docs" / "sprint_log.csv")
    assert [v["sprint"] for v in management["velocity"]] == sorted(sprint_log["sprint"].unique().tolist())
    register = pd.read_csv(ROOT / "data" / "risk_register.csv")
    assert [r["risk_id"] for r in management["risks"]] == register["risk_id"].tolist()
    assert management["risk_reviews_count"] == len(pd.read_csv(ROOT / "data" / "risk_reviews.csv"))


# --- handover: runbook steps written by people, contract gaps from the funnel ------------------------

def test_handover_steps_come_from_the_yaml(data):
    steps = yaml.safe_load(HANDOVER_PATH.read_text(encoding="utf-8"))["steps"]
    assert HANDOVER_PATH == CONFIG_DIR / "handover.yaml"
    assert [s["title"] for s in data["handover"]["steps"]] == [s["title"] for s in steps]
    assert [s["step"] for s in data["handover"]["steps"]] == list(range(1, len(steps) + 1))


def test_contract_gaps_come_from_the_funnel_and_are_not_duplicated_in_the_yaml(data):
    todo = " ".join(data["handover"]["finbank_todo"])
    assert "current_dpd" in todo and "maturity_date" in todo
    assert "delinquency_v2" in todo and "churn_v2" in todo
    text = HANDOVER_PATH.read_text(encoding="utf-8")
    assert "current_dpd" not in text and "maturity_date" not in text


# --- refusal ---------------------------------------------------------------------------------------

def test_data_that_breaks_the_contract_is_not_written(data, tmp_path):
    broken = json.loads(json.dumps(data))
    broken["meta"]["invented"] = 1
    path = tmp_path / "dashboard_data.json"
    with pytest.raises(ValueError, match="dashboard_data_v1"):
        write_dashboard_data(broken, path)
    assert not path.exists()


def test_the_fixture_still_differs_from_a_run_only_in_being_a_sample():
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    assert sample["meta"]["sample"] is True and sample["management"]["status"] == "RUN"
