"""Validates dashboard_data.json against ``config/contracts/dashboard_data_v1.yaml``.

The same contract binds the pipeline output (B11b) and the fixture
``dashboard/dashboard_data.sample.json`` that the dashboard is built against (B12a).
``validate_dashboard_data`` returns a list of errors (empty = valid), each with its path.

Schema rules come from the YAML contract (see its header). Semantic rules a schema cannot
express are checked here:

- every figure points to a file in ``lineage.manifest.outputs`` and figure ids are unique;
- each published curve starts at K = 0, grows, and its points are at least
  ``MIN_PUBLISHED_CLIENTS`` apart; ``k_star`` is one of its points; k_applied <= k_requested;
  ``at_k`` is the published point at ``k_applied`` (the K rule shared with the simulator);
- gate 2 counts match the decisions of the cards;
- budget lines add up: PV per sprint sums to the BAC, and the reserve is the contingency
  minus the approved change requests;
- no calibration cell describes fewer than ``MIN_PUBLISHED_CLIENTS`` clients;
- the decision's reason_code matches its verdict, and only an authorized verdict names a model.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.predict360.config import ROOT, load_contract

CONTRACT = "dashboard_data_v1"
SAMPLE_PATH = ROOT / "dashboard" / "dashboard_data.sample.json"
MIN_PUBLISHED_CLIENTS = 30   # same rule as the evaluator: no curve step under 30 clients
_EPS = 1e-6

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "any": lambda v: True,
}


def _check(value, spec: dict, path: str, defs: dict, errors: list[str]) -> None:
    if "ref" in spec:
        _check(value, {**defs[spec["ref"]], **{k: v for k, v in spec.items() if k != "ref"}}, path, defs, errors)
        return
    if "one_of" in spec:
        matches = 0
        for option in spec["one_of"]:
            option_errors: list[str] = []
            _check(value, option, path, defs, option_errors)
            matches += not option_errors
        if matches != 1:
            errors.append(f"{path}: must match exactly one allowed shape (matched {matches})")
        return

    types = spec.get("type", "any")
    types = types if isinstance(types, list) else [types]
    if not any(_TYPES[t](value) for t in types):
        errors.append(f"{path}: expected {' or '.join(types)}, got {type(value).__name__}")
        return
    if value is None:
        return
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: {value!r} not in {spec['enum']}")
    if "pattern" in spec and isinstance(value, str) and not re.match(spec["pattern"], value):
        errors.append(f"{path}: {value!r} does not match {spec['pattern']}")
    if _TYPES["number"](value):
        if "min" in spec and value < spec["min"]:
            errors.append(f"{path}: {value} below {spec['min']}")
        if "max" in spec and value > spec["max"]:
            errors.append(f"{path}: {value} above {spec['max']}")

    if isinstance(value, dict):
        fields = spec.get("fields")
        if fields is not None:
            for name, child in fields.items():
                if name in value:
                    _check(value[name], child, f"{path}.{name}", defs, errors)
                elif not child.get("optional"):
                    errors.append(f"{path}.{name}: required field missing")
            if not spec.get("open"):
                for name in value:
                    if name not in fields:
                        errors.append(f"{path}.{name}: unknown field")
        elif "values" in spec:
            for name, child_value in value.items():
                _check(child_value, spec["values"], f"{path}.{name}", defs, errors)
    if isinstance(value, list):
        if len(value) < spec.get("min_items", 0):
            errors.append(f"{path}: needs at least {spec['min_items']} item(s)")
        if "items" in spec:
            for i, item in enumerate(value):
                _check(item, spec["items"], f"{path}[{i}]", defs, errors)


def _semantic(data: dict) -> list[str]:
    errors = []
    outputs = {o["file"] for o in data["lineage"]["manifest"]["outputs"]}
    seen = set()
    for i, figure in enumerate(data["lineage"]["figures"]):
        where = f"lineage.figures[{i}]"
        if figure["file"] not in outputs:
            errors.append(f"{where}: file {figure['file']} is not in lineage.manifest.outputs")
        if figure["figure_id"] in seen:
            errors.append(f"{where}: duplicate figure_id {figure['figure_id']}")
        seen.add(figure["figure_id"])

    for i, evaluation in enumerate(data["models"]["evaluations"]):
        if evaluation["status"] != "evaluated":
            continue
        where = f"models.evaluations[{i}]"
        ks = [p["k"] for p in evaluation["curve"]]
        if ks[0] != 0:
            errors.append(f"{where}.curve: must start at K = 0")
        if any(b - a < MIN_PUBLISHED_CLIENTS - _EPS for a, b in zip(ks, ks[1:])):
            errors.append(f"{where}.curve: points must be at least {MIN_PUBLISHED_CLIENTS} clients apart")
        if evaluation["k_star"] not in evaluation["curve"]:
            errors.append(f"{where}.k_star: must be a point of the published curve")
        if evaluation["k_applied"] > evaluation["k_requested"] + _EPS:
            errors.append(f"{where}.k_applied: exceeds k_requested")
        # One K rule for the evaluator and the simulator: at_k IS the published point at k_applied
        point = next((p for p in evaluation["curve"] if abs(p["k"] - evaluation["k_applied"]) <= _EPS), None)
        if point is None or {k: v for k, v in point.items() if k != "k"} != evaluation["at_k"]:
            errors.append(f"{where}.at_k: must be the published curve point at k_applied")
        if any(cell["n_clients"] < MIN_PUBLISHED_CLIENTS - _EPS for cell in evaluation["metrics"]["calibration"]):
            errors.append(f"{where}.metrics.calibration: no cell may describe fewer than "
                          f"{MIN_PUBLISHED_CLIENTS} clients")

    for i, decision in enumerate(data["models"]["decisions"]):
        where = f"models.decisions[{i}]"
        authorized = decision["verdict"] == "authorized_for_shadow_deployment"
        if authorized != (decision["reason_code"] == "authorized"):
            errors.append(f"{where}.reason_code: {decision['reason_code']} does not match the verdict "
                          f"{decision['verdict']}")
        if authorized and not decision["model_id"]:
            errors.append(f"{where}.model_id: an authorized verdict must name the model")
        if not authorized and decision["model_id"]:
            errors.append(f"{where}.model_id: a not_authorized verdict names no model")

    counts = {d: sum(c["decision"] == d for c in data["models"]["cards"]) for d in ("ADMITTED", "REJECTED", "SKIPPED")}
    if counts != data["gates"]["gate2"]["counts"]:
        errors.append(f"gates.gate2.counts: {data['gates']['gate2']['counts']} do not match the cards {counts}")

    if data["management"]["status"] != "RUN":
        return errors
    base = data["management"]["baseline"]
    if abs(sum(base["pv_by_sprint_cop_m"].values()) - base["bac_cop_m"]) > _EPS:
        errors.append("management.baseline: PV by sprint does not add up to the BAC")
    approved = sum(cr["approved_cop_m"] for cr in base["change_requests"])
    if abs(base["contingency_cop_m"] - approved - base["reserve_remaining_cop_m"]) > _EPS:
        errors.append("management.baseline: reserve_remaining is not contingency minus approved change requests")
    return errors


def validate_dashboard_data(data: dict) -> list[str]:
    contract = load_contract(CONTRACT)
    errors: list[str] = []
    _check(data, {k: v for k, v in contract.items() if k in ("type", "fields")}, "$", contract["definitions"], errors)
    if errors:
        return errors   # semantic rules assume a well-formed document
    return _semantic(data)


def validate_file(path: str | Path) -> list[str]:
    return validate_dashboard_data(json.loads(Path(path).read_text(encoding="utf-8")))
