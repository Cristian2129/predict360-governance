"""Parity of the dashboard stress simulator (JavaScript) with evaluator.py (US-10, B12b-2).

The simulator recomputes net value from the published curve with other assumptions. It must
use the same formulas and the same K rule (``applied_point``: round down on the published
grid) as the evaluator, so with the assumptions of the evidence record it reproduces the
evaluator's numbers exactly: every curve point, at_k, K*, the random line and 18/58/118.

These tests need node. Locally they are skipped with a reason when node is missing; in CI
(``CI=true``) a missing node is a failure, and ci.yml pins Node 20.
"""
import json
import os
import shutil
import subprocess
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.predict360.config import ROOT, load_assumptions
from src.predict360.dashboard_contract import SAMPLE_PATH
from src.predict360.dashboard_render import ASSETS_DIR, simulator_data
from src.predict360.evaluator import (_contact_cost_cop_m, _gain_cop_m, _published, applied_point,
                                      capture_curve)

SIMULATOR = ASSETS_DIR / "simulator.js"
NODE = shutil.which("node")
TOLERANCE = 1e-9
HARNESS = """
const sim = require(process.argv[2]);
const calls = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify(calls.map(c => sim[c[0]](...c.slice(1)))));
"""


@pytest.fixture(scope="module")
def node(tmp_path_factory):
    if NODE is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI for the simulator parity tests")
        pytest.skip("node is not installed locally; CI runs these parity tests (CI=true, Node 20)")
    folder = tmp_path_factory.mktemp("node")
    (folder / "harness.js").write_text(HARNESS, encoding="utf-8")

    def call(calls):
        path = folder / "calls.json"
        path.write_text(json.dumps(calls), encoding="utf-8")
        proc = subprocess.run([NODE, str(folder / "harness.js"), str(SIMULATOR), str(path)],
                              capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)
    return call


def _defaults():
    values = load_assumptions()["values"]["value"]
    return {"capacity_share": values["default_capacity_share"], "action_effectiveness": values["action_effectiveness"],
            "loss_given_event": values["loss_given_event"], "cost_per_contact_cop": values["cost_per_contact_cop"]}


def _values(a):
    """The same assumptions in the evaluator's shape."""
    return {"value": {"action_effectiveness": a["action_effectiveness"], "loss_given_event": a["loss_given_event"],
                      "cost_per_contact_cop": a["cost_per_contact_cop"],
                      "default_capacity_share": a["capacity_share"]}}


@pytest.fixture(scope="module")
def run_data(tmp_path_factory):
    from src.predict360.run_pipeline import run_pipeline
    tmp = tmp_path_factory.mktemp("run")
    result = run_pipeline(runs_dir=tmp / "runs", citations_path=tmp / "none.yaml", commit="d" * 40,
                          now=datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc), as_of=date(2026, 11, 14))
    return json.loads((result["run_dir"] / "dashboard_data.json").read_text(encoding="utf-8"))


def _datasets(run_data):
    return {"fixture": json.loads(SAMPLE_PATH.read_text(encoding="utf-8")), "run": run_data}


def _evaluations(data):
    return [e for e in data["models"]["evaluations"] if e["status"] == "evaluated"]


# --- with the assumptions of the evidence record: exactly the evaluator's numbers -----------------

@pytest.mark.parametrize("dataset", ["fixture", "run"])
def test_every_curve_point_and_at_k_match_the_evaluator(node, run_data, dataset):
    a = _defaults()
    for e in _evaluations(_datasets(run_data)[dataset]):
        calls = [["netValue", p, a] for p in e["curve"]]
        calls += [["appliedPoint", e["curve"], a["capacity_share"] * e["n_clients"]],
                  ["kStar", e["curve"], a],
                  ["randomNet", e["event_exposure_cop_m"], e["n_clients"], e["k_applied"], a]]
        *nets, applied, star, random = node(calls)
        for p, net in zip(e["curve"], nets):
            assert net == pytest.approx(p["net_value_cop_m"], abs=TOLERANCE)
        assert applied["k"] == e["k_applied"]
        assert applied["net_value_cop_m"] == pytest.approx(e["at_k"]["net_value_cop_m"], abs=TOLERANCE)
        assert star["k"] == e["k_star"]["k"]
        assert random == pytest.approx(e["random_at_k"]["net_value_cop_m"], abs=TOLERANCE)


@pytest.mark.parametrize("dataset", ["fixture", "run"])
def test_the_browser_self_check_passes_on_real_data(node, run_data, dataset):
    sim = simulator_data(_datasets(run_data)[dataset])
    assert node([["selfCheck", sim]]) == [[]]


def test_the_self_check_catches_a_mismatch(node, run_data):
    sim = simulator_data(run_data)
    label = next(iter(sim["labels"]))
    sim["labels"][label]["models"][0]["at_k_net_value_cop_m"] += 1.0
    assert node([["selfCheck", sim]])[0]


def test_the_redrawn_curve_at_the_acta_is_the_drawn_one(node, run_data):
    sim = simulator_data(run_data)
    for name, label in sim["labels"].items():
        (geometry,) = node([["curveGeometry", label, sim["defaults"]]])
        nets = [p["net_value_cop_m"] for m in label["models"] for p in m["curve"]]
        last = label["models"][0]["curve"][-1]["net_value_cop_m"]
        assert geometry["low"] == pytest.approx(min(nets + [0.0, last]), abs=TOLERANCE)
        assert geometry["high"] == pytest.approx(max(nets + [0.0, last]), abs=TOLERANCE)
        assert [s["k"] for s in geometry["stars"]] == [m["k_star_k"] for m in label["models"]]


# --- with other assumptions: the same formulas and K rule as the evaluator -----------------------

def test_other_assumptions_follow_the_evaluator_formulas(node, run_data):
    a = {"capacity_share": 0.23, "action_effectiveness": 0.3, "loss_given_event": 0.8, "cost_per_contact_cop": 50000}
    v = _values(a)
    for e in _evaluations(run_data):
        k = a["capacity_share"] * e["n_clients"]
        point = applied_point(e["curve"], k)
        expected = _gain_cop_m(point["captured_cop_m"], v) - _contact_cost_cop_m(point["k"], v)
        captured = e["event_exposure_cop_m"] * (point["k"] / e["n_clients"])
        expected_random = _gain_cop_m(captured, v) - _contact_cost_cop_m(point["k"], v)
        applied, net, random = node([["appliedPoint", e["curve"], k], ["netValue", point, a],
                                     ["randomNet", e["event_exposure_cop_m"], e["n_clients"], point["k"], a]])
        assert applied["k"] == point["k"]
        assert net == pytest.approx(expected, abs=TOLERANCE)
        assert random == pytest.approx(expected_random, abs=TOLERANCE)


# --- the mandatory case: 18 / 58 / 118 -----------------------------------------------------------

def _spec_curve(events_in_top_100):
    n, y = 1000, [0] * 1000
    for i in range(events_in_top_100):
        y[i] = 1
    for i in range(n - (50 - events_in_top_100), n):
        y[i] = 1
    df = pd.DataFrame({"client_id": [f"c{i:04d}" for i in range(n)], "score": [1 - i / n for i in range(n)],
                       "y": y, "exposure_cop_m": [10.0] * n, "weight": [1.0] * n})
    return _published(capture_curve(df, _values(_defaults())))["curve"]


def test_spec_case_18_58_118(node):
    a = {"capacity_share": 0.10, "action_effectiveness": 0.40, "loss_given_event": 1.0, "cost_per_contact_cop": 20000}
    rule, model = node([["appliedPoint", _spec_curve(15), 100], ["appliedPoint", _spec_curve(30), 100]])
    net_rule, net_model, random = node([["netValue", rule, a], ["netValue", model, a],
                                        ["randomNet", 500.0, 1000.0, 100.0, a]])
    assert (round(random, 9), round(net_rule, 9), round(net_model, 9)) == (18.0, 58.0, 118.0)


# --- CI wiring -------------------------------------------------------------------------------------

def test_ci_pins_node_20_before_the_tests():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "actions/setup-node@v4" in workflow and 'node-version: "20"' in workflow
    assert workflow.index("actions/setup-node") < workflow.index("python -m pytest")
