"""Tests for the dashboard_data.json contract (technical spec, section 11)."""
import copy
import json

import pytest

from src.predict360.config import ROOT, load_assumptions
from src.predict360.dashboard_contract import SAMPLE_PATH, validate_dashboard_data

TOP_LEVEL = ["meta", "exposure", "gates", "quality", "lineage", "models", "assumptions", "management", "handover"]


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def _errors(data):
    return validate_dashboard_data(data)


def _evaluated(data):
    return next(e for e in data["models"]["evaluations"] if e["status"] == "evaluated")


# --- the fixture ----------------------------------------------------------------------

def test_fixture_meets_the_contract(sample):
    assert _errors(sample) == []


def test_fixture_is_marked_as_sample_and_synthetic(sample):
    assert SAMPLE_PATH == ROOT / "dashboard" / "dashboard_data.sample.json"
    assert sample["meta"]["sample"] is True
    assert sample["meta"]["synthetic"] is True and sample["meta"]["scores_simulated"] is True
    assert list(sample) == TOP_LEVEL


def test_fixture_assumptions_are_the_real_ones_with_their_type(sample):
    items = load_assumptions()["items"]
    assert [(a["id"], a["type"]) for a in sample["assumptions"]] == [(i["id"], i["type"]) for i in items]


def test_fixture_covers_the_cases_the_dashboard_must_show(sample):
    decisions = {c["decision"] for c in sample["models"]["cards"]}
    assert decisions == {"ADMITTED", "REJECTED", "SKIPPED"}
    assert any(r["message"] == "retired" for c in sample["models"]["cards"] for r in c["reasons"])
    statuses = {e["status"] for e in sample["models"]["evaluations"]}
    assert statuses == {"evaluated", "not_evaluated"}
    steps = [s for f in sample["quality"]["labeling_funnel"].values() for s in f["steps"]]
    assert sum(s.get("status") == "not_verifiable" for s in steps) == 2
    assert {s["hours_estimated"] for s in sample["management"]["sprints"]} == {True, False}
    assert any(s["mgmt_hours"] > 0 for s in sample["management"]["sprints"])


# --- schema rules ---------------------------------------------------------------------

@pytest.mark.parametrize("key", TOP_LEVEL)
def test_every_section_is_required(sample, key):
    data = copy.deepcopy(sample)
    del data[key]
    assert any(key in e for e in _errors(data))


def test_unknown_fields_fail_so_nobody_invents_them(sample):
    data = copy.deepcopy(sample)
    data["models"]["leaderboard"] = []
    assert any("leaderboard" in e for e in _errors(data))


def test_not_verifiable_step_cannot_carry_numbers(sample):
    data = copy.deepcopy(sample)
    step = next(s for s in data["quality"]["labeling_funnel"]["delinquency"]["steps"]
                if s.get("status") == "not_verifiable")
    step["rows"] = 0
    assert _errors(data)


@pytest.mark.parametrize("verdict", ["production", "approved", "goes_to_production"])
def test_verdict_never_goes_beyond_shadow_deployment(sample, verdict):
    data = copy.deepcopy(sample)
    data["models"]["decisions"][0]["verdict"] = verdict
    assert any("verdict" in e for e in _errors(data))


@pytest.mark.parametrize("commit,ok", [
    ("a" * 40, True), ("a" * 40 + "-dirty", True), ("unknown", True), ("main", False), ("abc", False),
])
def test_commit_is_a_sha_dirty_or_unknown(sample, commit, ok):
    data = copy.deepcopy(sample)
    data["meta"]["commit"] = commit
    assert (_errors(data) == []) is ok


def test_assumption_type_must_be_business_design_or_simulation(sample):
    data = copy.deepcopy(sample)
    data["assumptions"][0]["type"] = "guess"
    assert any("assumptions" in e for e in _errors(data))


def test_figure_id_must_be_dotted(sample):
    data = copy.deepcopy(sample)
    data["lineage"]["figures"][0]["figure_id"] = "NetValue"
    assert any("figure_id" in e for e in _errors(data))


# --- semantic rules -------------------------------------------------------------------

def test_figure_must_point_to_an_output(sample):
    data = copy.deepcopy(sample)
    data["lineage"]["figures"][0]["file"] = "not_an_output.json"
    assert any("outputs" in e for e in _errors(data))


def test_figure_ids_are_unique(sample):
    data = copy.deepcopy(sample)
    data["lineage"]["figures"].append(copy.deepcopy(data["lineage"]["figures"][0]))
    assert any("duplicate" in e for e in _errors(data))


def test_curve_points_are_at_least_30_clients_apart(sample):
    data = copy.deepcopy(sample)
    curve = _evaluated(data)["curve"]
    curve.insert(1, {**curve[1], "k": curve[0]["k"] + 10})
    assert any("30 clients" in e for e in _errors(data))


def test_k_star_is_a_point_of_the_published_curve(sample):
    data = copy.deepcopy(sample)
    evaluation = _evaluated(data)
    evaluation["k_star"] = {**evaluation["k_star"], "k": evaluation["k_star"]["k"] + 1}
    assert any("k_star" in e for e in _errors(data))


def test_k_applied_never_exceeds_k_requested(sample):
    data = copy.deepcopy(sample)
    evaluation = _evaluated(data)
    evaluation["k_applied"] = evaluation["k_requested"] + 1
    assert any("k_applied" in e for e in _errors(data))


def test_gate2_counts_match_the_cards(sample):
    data = copy.deepcopy(sample)
    data["gates"]["gate2"]["counts"]["ADMITTED"] += 1
    assert any("gate2" in e for e in _errors(data))


def test_budget_lines_add_up(sample):
    data = copy.deepcopy(sample)
    data["management"]["baseline"]["reserve_remaining_cop_m"] = 20.0   # CR-01 not discounted
    assert any("reserve" in e for e in _errors(data))


# --- the real output ------------------------------------------------------------------

@pytest.mark.skip(reason="B11b: export_dashboard_data.py does not exist yet; it must enable this test")
def test_pipeline_output_meets_the_same_contract():
    from src.predict360.export_dashboard_data import build_dashboard_data  # noqa: F401  (B11b)
