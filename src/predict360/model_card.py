"""Station 7, Gate 2: model card admission and statuses (technical spec, section 9).

A model enters evaluation only if its card meets the admission rules:

| Rule                     | Checks                                                    | If it fails |
| ------------------------ | --------------------------------------------------------- | ----------- |
| complete_card            | every model_card_v1 field present and valid               | reject: incomplete card |
| traceable                | dataset_hash = sha256 of the scores; snapshot_date = T    | reject: not traceable |
| temporal_split           | train_end_date before eval_start_date                     | reject: non-temporal split |
| preprocessing_train_only | preprocessing_fit_on declares training only               | reject: possible leakage |
| status_backed            | a card beyond candidate names who approved it             | reject |
| intervention_declared    | intervention_handling declared                            | warning (*) |
| baselines_compared       | random and a heuristic rule (gate2.baseline_models)       | warning (*) |

(*) Rejections when listed in ``gate2.strict_rules`` of the run config.

A retired card is not evaluated: it is SKIPPED with the reason "retired", not rejected.
The split and the transformations are declared in the card: the system checks the
dates, but it cannot prove by itself how an external model was fitted.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from src.predict360.config import load_contract

CONTRACT = "model_card_v1"
FORMATS = {"sha256_hex": re.compile(r"^[0-9a-f]{64}$")}
RANDOM_BASELINE = "random"
# The field must exist (complete_card); left empty it is a warning, not an incomplete card.
WARNING_FIELDS = {"intervention_handling"}
# A disallowed value here is reported by its own rule, with the spec's reason (possible leakage).
OWN_RULE_FIELDS = {"preprocessing_fit_on"}

# Each step forward needs its evidence; any status may be retired with a reason.
NEXT_STATUS = {"candidate": "shadow", "shadow": "pilot", "pilot": "approved"}
EVIDENCE = {
    "shadow": "beats_baselines",          # from the evaluator, per the configured threshold
    "pilot": "shadow_report",             # volume, alert consistency and score stability
    "approved": "control_effectiveness",  # effectiveness measured against the control group
    "retired": "reason",
}


def scores_sha256(path: str | Path) -> str:
    """Hash of the scores file. TODO(B5): read it from the run manifest instead."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _is_datetime(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str) and bool(v.strip()),
    "datetime": _is_datetime,
    "date": lambda v: _parse_date(v) is not None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "list": lambda v: isinstance(v, list),
}


def _reason(rule: str, severity: str, message: str) -> dict:
    return {"rule": rule, "severity": severity, "message": message}


def _completeness(card: dict) -> list[str]:
    problems = []
    for field, spec in load_contract(CONTRACT)["fields"].items():
        value = card.get(field)
        if value is None:
            if spec.get("required"):
                problems.append(f"missing field {field}")
            continue
        if field in WARNING_FIELDS and value == "":
            continue  # present but not declared: the intervention_declared rule decides
        if not TYPE_CHECKS[spec["type"]](value):
            problems.append(f"{field} is not a valid {spec['type']}")
        elif "allowed" in spec and value not in spec["allowed"] and field not in OWN_RULE_FIELDS:
            problems.append(f"{field} must be one of {', '.join(spec['allowed'])}")
        elif "format" in spec and not FORMATS[spec["format"]].match(value):
            problems.append(f"{field} does not match {spec['format']}")
    return problems


def admit_card(card: dict, scores_hash: str, cfg: dict) -> dict:
    """ADMITTED, REJECTED or SKIPPED (retired), with the reason for every finding."""
    result = {"model_id": card.get("model_id"), "target": card.get("target"),
              "status": card.get("status"), "decision": "ADMITTED", "reasons": []}
    if card.get("status") == "retired":
        result.update(decision="SKIPPED", reasons=[_reason("status", "skip", "retired")])
        return result

    reasons = result["reasons"]
    problems = _completeness(card)
    if problems:
        reasons.extend(_reason("complete_card", "reject", f"incomplete card: {p}") for p in problems)
        result["decision"] = "REJECTED"
        return result

    if card["dataset_hash"] != scores_hash:
        reasons.append(_reason("traceable", "reject", "not traceable: dataset_hash differs from the scores hash"))
    if _parse_date(card["snapshot_date"]) != _parse_date(str(cfg["snapshot_date"])):
        reasons.append(_reason("traceable", "reject",
                               f"not traceable: snapshot_date differs from the run cut-off {cfg['snapshot_date']}"))
    if not _parse_date(card["train_end_date"]) < _parse_date(card["eval_start_date"]):
        reasons.append(_reason("temporal_split", "reject",
                               "non-temporal split: train_end_date is not before eval_start_date"))
    if card["preprocessing_fit_on"] != "train_only":
        reasons.append(_reason("preprocessing_train_only", "reject",
                               "possible leakage: preprocessing not fitted on training only"))
    if card["status"] != "candidate" and not card.get("approved_by"):
        reasons.append(_reason("status_backed", "reject",
                               f"status {card['status']} without approved_by"))

    gate2 = cfg["gate2"]
    warnings = []
    if not card["intervention_handling"].strip():
        warnings.append(("intervention_declared", "intervention_handling not declared"))
    baselines = set(card["baselines_compared"])
    heuristics = set(gate2["baseline_models"])
    needs_heuristic = card["model_id"] not in heuristics
    if RANDOM_BASELINE not in baselines or (needs_heuristic and not baselines & heuristics):
        expected = "random" + (f" and one of {', '.join(sorted(heuristics))}" if needs_heuristic else "")
        warnings.append(("baselines_compared", f"baselines_compared must include {expected}"))
    for rule, message in warnings:
        severity = "reject" if rule in gate2["strict_rules"] else "warning"
        reasons.append(_reason(rule, severity, message))

    if any(r["severity"] == "reject" for r in reasons):
        result["decision"] = "REJECTED"
    return result


def run_gate2(cfg: dict, cards_dir: str | Path, scores_path: str | Path) -> dict:
    """Admits every ``*.json`` card in ``cards_dir`` against the scores file.

    status: PASS if no card is rejected (retired cards are skipped, not rejected).
    """
    scores_hash = scores_sha256(scores_path)
    cards = []
    for path in sorted(Path(cards_dir).glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        cards.append({"file": path.name, **admit_card(card, scores_hash, cfg)})
    counts = {d: sum(1 for c in cards if c["decision"] == d) for d in ("ADMITTED", "REJECTED", "SKIPPED")}
    return {
        "gate": "gate2",
        "status": "FAIL" if counts["REJECTED"] else "PASS",
        "scores_sha256": scores_hash,
        "counts": counts,
        "cards": cards,
    }


def transition(card: dict, new_status: str, evidence: dict) -> dict:
    """Returns a copy of the card in ``new_status``; raises ValueError without the evidence.

    Statuses only move one step forward (candidate -> shadow -> pilot -> approved) or to
    retired; retired is final. Every change records who approved it in ``approved_by``.
    """
    current = card["status"]
    allowed = current != "retired" and (new_status == "retired" or NEXT_STATUS.get(current) == new_status)
    if not allowed:
        raise ValueError(f"invalid status transition {current} -> {new_status}")
    required = EVIDENCE[new_status]
    value = evidence.get(required)
    if value is None or value is False or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{current} -> {new_status} needs evidence: {required}")
    approver = evidence.get("approved_by")
    if not (isinstance(approver, str) and approver.strip()):
        raise ValueError(f"{current} -> {new_status} needs approved_by")
    return {**card, "status": new_status, "approved_by": approver}
