"""Tests for lineage (technical spec, section 5): run manifest and tamper-evident lineage log."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from src.predict360 import __version__
from src.predict360.config import CONFIG_DIR, ROOT, load_config
from src.predict360.lineage import (
    add_output,
    add_source,
    file_entry,
    git_commit,
    new_run_id,
    record_gate,
    register_figure,
    resolve_figure_path,
    start_manifest,
    verify_lineage_log,
    write_manifest,
)
from src.predict360.quality import run_gate1

CONFIG = CONFIG_DIR / "synthetic.yaml"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"
NOW = datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def cfg():
    return {**load_config(CONFIG), "management": None}


def _manifest(cfg, run_id="20261112T1530-a1b2c3"):
    return start_manifest(cfg, CONFIG, run_id=run_id, now=NOW, commit="abc123")


def _with_sources(cfg, **kwargs):
    manifest = _manifest(cfg, **kwargs)
    for name, file in (("delinquency", "delinquency_sample.csv"), ("churn", "churn_sample.csv"),
                       ("scores", "scores_sample.csv")):
        add_source(manifest, name, SYNTHETIC_DIR / file, base=ROOT)
    return manifest


def _output(tmp_path, name="evaluation.json", text='{"net_value_cop_m": 118.0}'):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- run id, hashes and code version ----------------------------------------------

def test_run_id_format():
    assert new_run_id(now=NOW, suffix="a1b2c3") == "20261112T1530-a1b2c3"
    generated = new_run_id(now=NOW)
    assert generated.startswith("20261112T1530-") and len(generated) == len("20261112T1530-a1b2c3")
    assert generated != new_run_id(now=NOW)


def test_file_hash_changes_with_a_single_byte(tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(b"a,b\n1,2\n")
    first = file_entry(path, base=tmp_path)
    assert first == {"file": "data.csv", "sha256": hashlib.sha256(b"a,b\n1,2\n").hexdigest(),
                     "rows": 1, "bytes": 8}
    assert file_entry(path, base=tmp_path)["sha256"] == first["sha256"]
    path.write_bytes(b"a,b\n1,3\n")
    assert file_entry(path, base=tmp_path)["sha256"] != first["sha256"]


def test_commit_is_marked_dirty_or_unknown_without_failing(tmp_path, monkeypatch):
    commit = git_commit()
    assert commit == "unknown" or len(commit.removesuffix("-dirty")) == 40
    # No repository, e.g. code shipped as a zip (git must not search parent folders)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert git_commit(cwd=tmp_path) == "unknown"


def test_commit_is_unknown_when_git_is_not_installed(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr("src.predict360.lineage.subprocess.run", no_git)
    assert git_commit() == "unknown"


def test_manifest_records_code_version_and_spec_fields(cfg):
    manifest = _manifest(cfg)
    assert manifest["code_version"] == __version__
    assert manifest["run_id"] == "20261112T1530-a1b2c3"
    assert manifest["config"] == "synthetic.yaml" and manifest["synthetic"] is True
    assert manifest["commit"] == "abc123" and manifest["created_at"] == "2026-11-12T15:30:00Z"
    assert manifest["snapshot_date"] == "2026-03-31"
    assert manifest["parameters"] == {"horizons": [30, 60, 90], "seed": 42}
    for key in ("sources", "outputs", "figures", "waivers"):
        assert manifest[key] == []


# --- sources, gates and waivers -------------------------------------------------

def test_sources_with_rows_and_scores_hash(cfg):
    manifest = _with_sources(cfg)
    rows = {s["name"]: s["rows"] for s in manifest["sources"]}
    assert rows == {"delinquency": 500, "churn": 200, "scores": 3600}
    assert manifest["sources"][0]["file"] == "data/synthetic/delinquency_sample.csv"
    card = json.loads((SYNTHETIC_DIR / "model_cards" / "delinquency_model_a.json").read_text(encoding="utf-8"))
    assert manifest["scores_sha256"] == card["dataset_hash"]


def test_gate1_status_contracts_and_full_waiver_records(cfg):
    manifest = _with_sources(cfg)
    record_gate(manifest, run_gate1(cfg, as_of=datetime(2026, 11, 12).date()), cfg)
    assert manifest["gates"] == {"gate1": "PASS_WITH_WAIVERS"}
    assert manifest["contract_versions"] == {"delinquency": "v1", "churn": "v1", "scores": "v1"}
    (waiver,) = manifest["waivers"]
    assert waiver == cfg["waivers"][0]   # the whole record, not only its id


def test_manifest_holds_no_client_rows(cfg):
    manifest = _with_sources(cfg)
    record_gate(manifest, run_gate1(cfg, as_of=datetime(2026, 11, 12).date()), cfg)
    text = json.dumps(manifest, default=str)
    ids = (SYNTHETIC_DIR / "churn_sample.csv").read_text(encoding="utf-8").splitlines()[1:6]
    assert not any(line.split(",")[0] in text for line in ids)


# --- figures --------------------------------------------------------------------

def test_figure_points_to_an_output_and_keeps_full_precision(cfg, tmp_path):
    manifest = _manifest(cfg)
    out = add_output(manifest, _output(tmp_path), base=tmp_path)
    figure = register_figure(manifest, "exposure.delinquency.observed_cop_m", 58800.000123, "COP_m",
                             out["file"], "src/predict360/reconcile.py", "tables.delinquency.actual_cop_m")
    assert figure == {"figure_id": "exposure.delinquency.observed_cop_m", "value": 58800.000123,
                      "unit": "COP_m", "file": "evaluation.json", "script": "src/predict360/reconcile.py",
                      "path": "tables.delinquency.actual_cop_m"}
    assert "sha256" not in figure   # the hash lives in outputs


@pytest.mark.parametrize("figure_id", ["exposure", "Exposure.Delinquency", "exposure..cop_m", "exposure delinquency"])
def test_figure_ids_are_dotted_lowercase(cfg, tmp_path, figure_id):
    manifest = _manifest(cfg)
    out = add_output(manifest, _output(tmp_path), base=tmp_path)
    with pytest.raises(ValueError, match="figure_id"):
        register_figure(manifest, figure_id, 1.0, "COP_m", out["file"], "x.py", "net_value_cop_m")


def test_figure_must_reference_a_registered_output_and_be_unique(cfg, tmp_path):
    manifest = _manifest(cfg)
    out = add_output(manifest, _output(tmp_path), base=tmp_path)
    with pytest.raises(ValueError, match="outputs"):
        register_figure(manifest, "models.model_a.net_value_cop_m", 118.0, "COP_m", "other.json", "x.py",
                        "net_value_cop_m")
    register_figure(manifest, "models.model_a.net_value_cop_m", 118.0, "COP_m", out["file"], "x.py",
                    "net_value_cop_m")
    with pytest.raises(ValueError, match="already"):
        register_figure(manifest, "models.model_a.net_value_cop_m", 118.0, "COP_m", out["file"], "x.py",
                        "net_value_cop_m")


# --- figure paths: selectors by identifier, never list positions ------------------------

EVALUATION = {"evaluations": [
    {"model_id": "model_a", "label": "delinquency_60", "horizon_days": 60, "at_k": {"net_value_cop_m": 177.1}},
    {"model_id": "model_b", "label": "delinquency_60", "horizon_days": 60, "at_k": {"net_value_cop_m": 852.6}},
    {"model_id": "model_b", "label": "delinquency_30", "horizon_days": 30, "at_k": {"net_value_cop_m": 271.9}},
], "pv_by_sprint_cop_m": {"3": 35.0}}
SELECTOR = "evaluations[model_id=model_b,label=delinquency_60].at_k.net_value_cop_m"


def test_selector_finds_the_item_by_its_identifiers():
    assert resolve_figure_path(EVALUATION, SELECTOR) == 852.6
    assert resolve_figure_path(EVALUATION, "evaluations[model_id=model_b,horizon_days=30].at_k.net_value_cop_m") == 271.9
    assert resolve_figure_path(EVALUATION, "pv_by_sprint_cop_m.3") == 35.0   # numeric KEY of a mapping


def test_reordering_the_list_does_not_change_the_figure():
    reordered = {**EVALUATION, "evaluations": list(reversed(EVALUATION["evaluations"]))}
    assert resolve_figure_path(reordered, SELECTOR) == resolve_figure_path(EVALUATION, SELECTOR)


def test_list_positions_are_refused():
    with pytest.raises(ValueError, match="selector"):
        resolve_figure_path(EVALUATION, "evaluations.1.at_k.net_value_cop_m")


@pytest.mark.parametrize("path", [
    "evaluations[model_id=model_b].at_k.net_value_cop_m",       # two matches
    "evaluations[model_id=model_z].at_k.net_value_cop_m",       # none
    "evaluations[model_id=model_a].at_k.capture",               # missing key
])
def test_selector_must_match_exactly_one_item_and_existing_keys(path):
    with pytest.raises((KeyError, ValueError)):
        resolve_figure_path(EVALUATION, path)


@pytest.mark.parametrize("path", ["", "evaluations[model_id]", "a..b", "evaluations[=x].y"])
def test_malformed_paths_are_refused_at_registration(cfg, tmp_path, path):
    manifest = _manifest(cfg)
    out = add_output(manifest, _output(tmp_path), base=tmp_path)
    with pytest.raises(ValueError, match="path"):
        register_figure(manifest, "models.model_a.net_value_cop_m", 118.0, "COP_m", out["file"], "x.py", path)


# --- written manifest is immutable ------------------------------------------------

def test_manifest_cannot_be_overwritten_or_changed_after_writing(cfg, tmp_path):
    runs = tmp_path / "runs"
    manifest = _with_sources(cfg)
    out = add_output(manifest, _output(tmp_path), base=tmp_path)
    path = write_manifest(manifest, runs, runs / "lineage_log.jsonl", now=NOW)
    assert path == runs / manifest["run_id"] / "manifest.json"
    assert json.loads(path.read_text(encoding="utf-8"))["closed_at"] == "2026-11-12T15:30:00Z"
    with pytest.raises(ValueError, match="closed"):
        register_figure(manifest, "models.model_a.net_value_cop_m", 118.0, "COP_m", out["file"], "x.py",
                        "net_value_cop_m")
    with pytest.raises(ValueError, match="closed"):
        add_output(manifest, _output(tmp_path, "late.json"), base=tmp_path)
    again = _with_sources(cfg)   # same run_id
    with pytest.raises(FileExistsError):
        write_manifest(again, runs, runs / "lineage_log.jsonl", now=NOW)


# --- tamper-evident lineage log ------------------------------------------------------

def _three_runs(cfg, tmp_path):
    runs, log = tmp_path / "runs", tmp_path / "runs" / "lineage_log.jsonl"
    manifests = []
    for suffix in ("aaaaaa", "bbbbbb", "cccccc"):
        manifest = _with_sources(cfg, run_id=f"20261112T1530-{suffix}")
        write_manifest(manifest, runs, log, now=NOW)
        manifests.append(manifest)
    return runs, log, manifests


def _lines(log):
    return log.read_text(encoding="utf-8").splitlines()


def test_log_is_a_hash_chain_anchored_in_the_manifests(cfg, tmp_path):
    runs, log, manifests = _three_runs(cfg, tmp_path)
    lines = _lines(log)
    entries = [json.loads(line) for line in lines]
    assert [e["run_id"] for e in entries] == [m["run_id"] for m in manifests]
    assert entries[0]["prev_entry_sha256"] is None
    for previous, entry in zip(lines, entries[1:]):
        assert entry["prev_entry_sha256"] == hashlib.sha256(previous.encode("utf-8")).hexdigest()
    for manifest, entry in zip(manifests, entries):
        assert manifest["lineage_head_sha256"] == entry["prev_entry_sha256"]
    assert verify_lineage_log(log, runs) == {"status": "OK", "entries": 3, "problems": []}


def test_appending_never_rewrites_earlier_lines(cfg, tmp_path):
    runs, log, _ = _three_runs(cfg, tmp_path)
    before = _lines(log)
    write_manifest(_with_sources(cfg, run_id="20261112T1530-dddddd"), runs, log, now=NOW)
    assert _lines(log)[:3] == before


def test_editing_or_deleting_a_line_is_detected(cfg, tmp_path):
    runs, log, _ = _three_runs(cfg, tmp_path)
    lines = _lines(log)
    edited = json.loads(lines[1])
    edited["run_id"] = "20261112T1530-ffffff"
    log.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n", encoding="utf-8")
    assert verify_lineage_log(log)["status"] == "TAMPERED"
    log.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert verify_lineage_log(log)["status"] == "TAMPERED"


def test_recomputed_chain_is_caught_by_the_manifest_anchor(cfg, tmp_path):
    # Tamper-evident, not tamper-proof: rewriting the whole chain passes the chain check,
    # but no longer matches the lineage_head_sha256 stored in the manifests already written
    runs, log, _ = _three_runs(cfg, tmp_path)
    entries = [json.loads(line) for line in _lines(log)]
    del entries[1]
    rebuilt, prev = [], None
    for entry in entries:
        entry["prev_entry_sha256"] = prev
        line = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        rebuilt.append(line)
        prev = hashlib.sha256(line.encode("utf-8")).hexdigest()
    log.write_text("\n".join(rebuilt) + "\n", encoding="utf-8")
    assert verify_lineage_log(log)["status"] == "OK"          # the chain alone is consistent
    result = verify_lineage_log(log, runs)
    assert result["status"] == "TAMPERED"
    assert any("lineage_head_sha256" in p for p in result["problems"])


def test_edited_manifest_is_detected(cfg, tmp_path):
    runs, log, manifests = _three_runs(cfg, tmp_path)
    path = runs / manifests[0]["run_id"] / "manifest.json"
    path.write_text(path.read_text(encoding="utf-8").replace("PASS", "FAIL") + " ", encoding="utf-8")
    result = verify_lineage_log(log, runs)
    assert result["status"] == "TAMPERED"
    assert any("manifest_sha256" in p for p in result["problems"])
