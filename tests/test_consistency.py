"""Tests for Gate 3, consistency (technical spec, section 9, station 11).

Every figure registered in the manifest must still be in its output file (same hash, same
value at its path), and every figure cited in the report or the presentation
(docs/cited_figures.yaml) must be written exactly as the system formats it in that locale.
"""
import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT, load_config
from src.predict360.consistency import CITATIONS_PATH, run_gate3
from src.predict360.dashboard_contract import SAMPLE_PATH, validate_dashboard_data
from src.predict360.lineage import add_output, record_gate, register_figure, start_manifest, write_manifest

CONFIG = CONFIG_DIR / "synthetic.yaml"
NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
RECONCILIATION = {"status": "PASS", "tables": {"delinquency": {"actual_cop_m": 58800.0},
                                               "churn": {"actual_cop_m": 18200.0}}}
EVALUATION = {"evaluations": [
    {"model_id": "model_a", "label": "delinquency_60", "at_k": {"net_value_cop_m": 177.1, "capture": 0.31}},
    {"model_id": "model_b", "label": "delinquency_60", "at_k": {"net_value_cop_m": 852.6, "capture": 0.52}},
]}
FIGURES = [
    ("exposure.delinquency.observed_cop_m", 58800.0, "COP_m", "reconciliation.json", "tables.delinquency.actual_cop_m"),
    ("exposure.churn.observed_cop_m", 18200.0, "COP_m", "reconciliation.json", "tables.churn.actual_cop_m"),
    ("models.delinquency_60.model_b.net_value_at_k_cop_m", 852.6, "COP_m", "evaluation.json",
     "evaluations[model_id=model_b,label=delinquency_60].at_k.net_value_cop_m"),
    ("models.delinquency_60.model_b.capture_at_k", 0.52, "share", "evaluation.json",
     "evaluations[model_id=model_b,label=delinquency_60].at_k.capture"),
]
CITATIONS = [
    {"figure_id": "exposure.delinquency.observed_cop_m", "text": "COP 58.800 M", "locale": "es",
     "where": "presentation, slide 2"},
    {"figure_id": "exposure.delinquency.observed_cop_m", "text": "COP 58,800 M", "locale": "en",
     "where": "report, section 1"},
    {"figure_id": "models.delinquency_60.model_b.capture_at_k", "text": "52,0 %", "locale": "es",
     "where": "presentation, slide 7"},
]


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _run(tmp_path, evaluation=EVALUATION):
    """An open manifest with real output files in tmp_path/run, as run_pipeline will leave it."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    _write_json(run_dir / "reconciliation.json", RECONCILIATION)
    _write_json(run_dir / "evaluation.json", evaluation)
    manifest = start_manifest(load_config(CONFIG), CONFIG, run_id="20261113T1500-a1b2c3", now=NOW, commit="abc123")
    for name in ("reconciliation.json", "evaluation.json"):
        add_output(manifest, run_dir / name, base=run_dir)
    for figure_id, value, unit, file, path in FIGURES:
        register_figure(manifest, figure_id, value, unit, file, "x.py", path)
    return manifest, run_dir


def _citations(tmp_path, items=CITATIONS):
    path = tmp_path / "cited_figures.yaml"
    path.write_text(yaml.safe_dump({"version": "v1", "citations": items}, allow_unicode=True), encoding="utf-8")
    return path


def _reasons(report):
    return [(m["figure_id"], m["reason"]) for m in report["mismatches"]]


# --- a clean run ---------------------------------------------------------------------

def test_clean_run_passes(tmp_path):
    manifest, run_dir = _run(tmp_path)
    report = run_gate3(manifest, run_dir, _citations(tmp_path))
    assert report["gate"] == "gate3" and report["status"] == "PASS"
    assert report["figures_checked"] == 4 and report["citations_checked"] == 3
    assert report["checked"] == 7 and report["mismatches"] == [] and report["warnings"] == []


def test_reordering_evaluations_does_not_change_the_result(tmp_path):
    reordered = {"evaluations": list(reversed(EVALUATION["evaluations"]))}
    manifest, run_dir = _run(tmp_path, reordered)
    assert run_gate3(manifest, run_dir, _citations(tmp_path))["status"] == "PASS"


def test_gate3_is_recorded_in_the_manifest(tmp_path):
    manifest, run_dir = _run(tmp_path)
    record_gate(manifest, run_gate3(manifest, run_dir, _citations(tmp_path)), {})
    assert manifest["gates"]["gate3"] == {"status": "PASS"}


# --- figures against their output files ---------------------------------------------------

def test_an_altered_output_file_fails(tmp_path):
    manifest, run_dir = _run(tmp_path)
    altered = copy.deepcopy(EVALUATION)
    altered["evaluations"][1]["at_k"]["net_value_cop_m"] = 999.0
    _write_json(run_dir / "evaluation.json", altered)
    report = run_gate3(manifest, run_dir, _citations(tmp_path))
    assert report["status"] == "FAIL"
    assert ("models.delinquency_60.model_b.net_value_at_k_cop_m", "output_altered") in _reasons(report)


def test_a_registered_value_that_differs_from_its_file_fails(tmp_path):
    manifest, run_dir = _run(tmp_path)
    manifest["figures"][2]["value"] = 850.0
    report = run_gate3(manifest, run_dir, _citations(tmp_path))
    (mismatch,) = [m for m in report["mismatches"] if m["reason"] == "value_differs"]
    assert mismatch["figure_id"] == "models.delinquency_60.model_b.net_value_at_k_cop_m"
    assert mismatch["expected"] == 850.0 and mismatch["found"] == 852.6


def test_a_missing_output_file_fails(tmp_path):
    manifest, run_dir = _run(tmp_path)
    (run_dir / "reconciliation.json").unlink()
    report = run_gate3(manifest, run_dir, _citations(tmp_path))
    assert ("exposure.churn.observed_cop_m", "output_missing") in _reasons(report)


def test_a_path_with_a_list_position_fails(tmp_path):
    manifest, run_dir = _run(tmp_path)
    manifest["figures"][2]["path"] = "evaluations.1.at_k.net_value_cop_m"
    report = run_gate3(manifest, run_dir, _citations(tmp_path))
    assert ("models.delinquency_60.model_b.net_value_at_k_cop_m", "path_not_found") in _reasons(report)


# --- citations in the report and the presentation ------------------------------------------

def test_a_citation_written_differently_fails_with_its_location(tmp_path):
    items = copy.deepcopy(CITATIONS)
    items[0]["text"] = "COP 58.000 M"
    report = run_gate3(*_run(tmp_path), _citations(tmp_path, items))
    (mismatch,) = report["mismatches"]
    assert mismatch["reason"] == "text_differs" and mismatch["source"] == "citation"
    assert mismatch["where"] == "presentation, slide 2"
    assert mismatch["expected"] == "COP 58.800 M" and mismatch["found"] == "COP 58.000 M"


def test_english_text_is_checked_with_english_format(tmp_path):
    items = copy.deepcopy(CITATIONS)
    items[1]["locale"] = "es"            # "COP 58,800 M" read as Spanish is wrong
    report = run_gate3(*_run(tmp_path), _citations(tmp_path, items))
    assert _reasons(report) == [("exposure.delinquency.observed_cop_m", "text_differs")]


def test_citing_an_unknown_figure_fails(tmp_path):
    items = CITATIONS + [{"figure_id": "exposure.total_cop_m", "text": "COP 77.000 M", "locale": "es",
                          "where": "slide 1"}]
    report = run_gate3(*_run(tmp_path), _citations(tmp_path, items))
    assert _reasons(report) == [("exposure.total_cop_m", "unknown_figure")]


@pytest.mark.parametrize("change", [{"locale": "fr"}, {"text": None}, {"where": ""}])
def test_an_incomplete_citation_fails(tmp_path, change):
    items = copy.deepcopy(CITATIONS)
    items[0].update(change)
    report = run_gate3(*_run(tmp_path), _citations(tmp_path, items))
    assert _reasons(report) == [("exposure.delinquency.observed_cop_m", "invalid_citation")]


# --- no citations: warning while working, FAIL for the official run ----------------------------

@pytest.mark.parametrize("make", ["missing", "empty"])
def test_without_citations_it_passes_with_a_warning(tmp_path, make):
    path = tmp_path / "none.yaml" if make == "missing" else _citations(tmp_path, [])
    report = run_gate3(*_run(tmp_path), path)
    assert report["status"] == "PASS" and report["citations_checked"] == 0
    assert report["warnings"] and "citation" in report["warnings"][0]


@pytest.mark.parametrize("make", ["missing", "empty"])
def test_strict_mode_fails_without_citations(tmp_path, make):
    path = tmp_path / "none.yaml" if make == "missing" else _citations(tmp_path, [])
    report = run_gate3(*_run(tmp_path), path, require_citations=True)
    assert report["status"] == "FAIL" and report["require_citations"] is True
    assert _reasons(report) == [(None, "no_citations")]


def test_repository_citations_file_exists_and_is_valid_yaml():
    data = yaml.safe_load(CITATIONS_PATH.read_text(encoding="utf-8"))
    assert CITATIONS_PATH == ROOT / "docs" / "cited_figures.yaml"
    assert data["version"] == "v1" and isinstance(data["citations"], list)


# --- the report fits dashboard_data_v1 ---------------------------------------------------------

def test_report_fits_the_dashboard_contract(tmp_path):
    items = copy.deepcopy(CITATIONS)
    items[0]["text"] = "COP 1 M"
    report = run_gate3(*_run(tmp_path), _citations(tmp_path, items))
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    data["gates"]["gate3"] = {k: v for k, v in report.items() if k != "gate"}
    assert validate_dashboard_data(data) == []


# --- re-check an existing run after editing the report ---------------------------------------

def test_cli_rechecks_a_written_run_without_changing_it(tmp_path):
    manifest, run_dir = _run(tmp_path)
    runs = tmp_path / "runs"
    manifest_path = write_manifest(manifest, runs, runs / "lineage_log.jsonl", now=NOW)
    for name in ("reconciliation.json", "evaluation.json"):
        (manifest_path.parent / name).write_bytes((run_dir / name).read_bytes())
    before = manifest_path.read_bytes()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}

    def cli(*extra):
        return subprocess.run([sys.executable, "-m", "src.predict360.consistency", "--run", str(manifest_path.parent),
                               *extra], cwd=ROOT, capture_output=True, text=True, env=env)

    ok = cli("--citations", str(_citations(tmp_path)))
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["status"] == "PASS"
    strict = cli("--citations", str(tmp_path / "none.yaml"), "--require-citations")
    assert strict.returncode == 1 and json.loads(strict.stdout)["status"] == "FAIL"
    assert manifest_path.read_bytes() == before
