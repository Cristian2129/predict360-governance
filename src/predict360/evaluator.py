"""Station 8, evaluator core: exposure capture in COP, net value and K* (technical spec, sections 4 and 9).

Formulas (y event, E exposure in COP millions, K clients contacted, e effectiveness,
l share of exposure lost, c cost per contact), all assumptions from ``config/assumptions.yaml``:

    capture(K)   = sum_topK(E * y) / sum(E * y)
    net_value(K) = e * l * sum_topK(E * y) - c * K
    K*           = argmax_K net_value(K)

- K counts clients: each row weighs ``weight`` clients and rows are never split, so the
  applied K is the largest whole-row prefix not above the requested K. Both values are
  reported, and cost, capture and the random baseline all use ``k_applied`` so that the
  model and the baseline are compared on the same K.
- Ties in the score are broken by ``client_id``. The ID is an HMAC, so that order is
  equivalent to a random but reproducible one: a model with constant scores lands close
  to random, which is the correct reading.
- The random baseline is analytical: its expected capture is k_applied / N.
- Amounts are in COP millions; the cost per contact is in COP in the assumptions and is
  converted in one place (``_contact_cost_cop_m``).
- Only aggregates leave this module. The published capture curve has points at least
  ``MIN_PUBLISHED_CLIENTS`` clients apart, so no point reveals a slice under 30 clients,
  and the published K* is the best point of that grid (``k_star`` on the full curve is
  kept for analysis inside the bank).

Ranking metrics, calibration and promotion (B8b) and slices and intervened clients (B8c)
are built on top of this core.
"""
from __future__ import annotations

import pandas as pd

from src.predict360.labeling import label_column

COP_PER_MILLION = 1_000_000
MIN_PUBLISHED_CLIENTS = 30
CURVE_STEP_SHARE = 0.05
_EPS = 1e-9


def _contact_cost_cop_m(k_clients: float, values: dict) -> float:
    return k_clients * values["value"]["cost_per_contact_cop"] / COP_PER_MILLION


def _gain_cop_m(captured_cop_m: float, values: dict) -> float:
    return values["value"]["action_effectiveness"] * values["value"]["loss_given_event"] * captured_cop_m


def _ratio(part: float, total: float):
    return part / total if total else None


def capture_curve(df: pd.DataFrame, values: dict, keep_order: bool = False) -> pd.DataFrame:
    """Cumulative curve over whole-row prefixes, from K = 0 to every client.

    df columns: client_id, score, y (0/1), exposure_cop_m, weight.
    """
    ranked = df.sort_values(["score", "client_id"], ascending=[False, True], kind="mergesort")
    event_exposure = ranked["exposure_cop_m"] * ranked["y"]
    curve = pd.DataFrame({
        "k": ranked["weight"].cumsum().to_numpy(),
        "captured_cop_m": event_exposure.cumsum().to_numpy(),
    })
    # The total is the last cumulative value, not a separate sum: both round differently,
    # and a non-decreasing cumsum then keeps every capture <= 1 and the last one exactly 1
    total = float(curve["captured_cop_m"].iloc[-1]) if len(curve) else 0.0
    if keep_order:
        curve["client_id"] = ranked["client_id"].to_numpy()
    start = pd.DataFrame({"k": [0.0], "captured_cop_m": [0.0]})
    curve = pd.concat([start, curve], ignore_index=True)
    curve["capture"] = curve["captured_cop_m"] / total if total else float("nan")
    curve["net_value_cop_m"] = (_gain_cop_m(curve["captured_cop_m"], values)
                                - _contact_cost_cop_m(curve["k"], values))
    return curve


def _point(row) -> dict:
    capture = row["capture"]
    return {
        "k": float(row["k"]),
        "capture": None if pd.isna(capture) else float(capture),
        "captured_cop_m": float(row["captured_cop_m"]),
        "net_value_cop_m": float(row["net_value_cop_m"]),
    }


def _applied(curve: pd.DataFrame, k_requested: float) -> pd.Series:
    return curve[curve["k"] <= k_requested + _EPS].iloc[-1]


def evaluate_at_k(df: pd.DataFrame, k_requested: float, values: dict) -> dict:
    point = _point(_applied(capture_curve(df, values), k_requested))
    k_applied = point.pop("k")
    return {"k_requested": k_requested, "k_applied": k_applied, **point}


def random_baseline(df: pd.DataFrame, k_requested: float, values: dict) -> dict:
    """Expected result of contacting k_applied clients at random (analytical, no simulation)."""
    k_applied = float(_applied(capture_curve(df, values), k_requested)["k"])
    total = float((df["exposure_cop_m"] * df["y"]).sum())
    share = k_applied / float(df["weight"].sum())
    captured = total * share
    return {
        "k_requested": k_requested,
        "k_applied": k_applied,
        "capture": share if total else None,
        "captured_cop_m": captured,
        "net_value_cop_m": _gain_cop_m(captured, values) - _contact_cost_cop_m(k_applied, values),
    }


def k_star(curve: pd.DataFrame) -> dict:
    """The K with the highest net value (the first one on ties)."""
    return _point(curve.loc[curve["net_value_cop_m"].idxmax()])


def _published_curve(curve: pd.DataFrame) -> list[dict]:
    """Grid points every 5% of clients, never closer than MIN_PUBLISHED_CLIENTS."""
    n = float(curve["k"].iloc[-1])
    step = max(n * CURVE_STEP_SHARE, MIN_PUBLISHED_CLIENTS)
    points, last = [_point(curve.iloc[0])], 0.0
    target = step
    while target < n:
        row = _applied(curve, target)
        if row["k"] - last >= MIN_PUBLISHED_CLIENTS and n - row["k"] >= MIN_PUBLISHED_CLIENTS:
            points.append(_point(row))
            last = float(row["k"])
        target += step
    points.append(_point(curve.iloc[-1]))
    return points


def _published(curve: pd.DataFrame) -> dict:
    """What leaves the module: the grid curve and K* chosen on that same grid
    (dashboard_data_v1: k_star must be a point of the published curve)."""
    points = _published_curve(curve)
    return {"k_star": max(points, key=lambda p: p["net_value_cop_m"]), "curve": points}


def _admitted(gate2_report: dict) -> list[tuple[str, str]]:
    return sorted({(c["target"], c["model_id"]) for c in gate2_report["cards"] if c["decision"] == "ADMITTED"})


def _horizons(values: dict) -> dict[str, list[int]]:
    return {"delinquency": [int(h) for h in values["delinquency"]["horizons_days"]],
            "churn": [int(values["churn"]["horizon_days"])]}


def evaluate_models(labeled: dict, scores: pd.DataFrame, gate2_report: dict, values: dict) -> dict:
    """Evaluates every ADMITTED card on every label of its target.

    labeled: output of ``labeling.label_all``. scores: long format (scores_v1).
    A labeled client without a score leaves that model and label ``not_evaluated``
    (``incomplete_scores``); scores of clients outside the labeled table (immature
    rows) are dropped and counted.
    """
    key = ["client_id", "model_id", "horizon_days"]
    duplicated = int(scores.duplicated(subset=key).sum())
    if duplicated:
        raise ValueError(f"{duplicated} duplicate (client_id, model_id, horizon_days) score row(s): "
                         "the same exposure would be counted twice")

    share = values["value"]["default_capacity_share"]
    horizons = _horizons(values)
    evaluations = []
    for target, model_id in _admitted(gate2_report):
        table = labeled[target]["table"]
        for horizon in horizons[target]:
            label = label_column(target, horizon)
            rows = table.loc[table[label].notna(), ["client_id", "exposure_cop_m", "weight", label]]
            model_scores = scores.loc[(scores["model_id"] == model_id) & (scores["horizon_days"] == horizon),
                                      ["client_id", "score"]]
            merged = rows.merge(model_scores, on="client_id", how="left")
            entry = {
                "target": target, "horizon_days": horizon, "label": label, "model_id": model_id,
                "n_rows": int(len(rows)), "n_clients": float(rows["weight"].sum()),
                "scores_dropped_rows": int((~model_scores["client_id"].isin(rows["client_id"])).sum()),
            }
            if merged["score"].isna().any():
                entry.update(status="not_evaluated", reason="incomplete_scores",
                             missing_score_rows=int(merged["score"].isna().sum()))
                evaluations.append(entry)
                continue

            df = merged.rename(columns={label: "y"}).astype({"y": "int64"})
            curve = capture_curve(df, values)
            k_requested = share * entry["n_clients"]
            at_k = evaluate_at_k(df, k_requested, values)
            entry.update(
                status="evaluated",
                event_clients=float(df.loc[df["y"] == 1, "weight"].sum()),
                event_exposure_cop_m=float((df["exposure_cop_m"] * df["y"]).sum()),
                k_requested=k_requested,
                k_applied=at_k.pop("k_applied"),
                at_k={k: v for k, v in at_k.items() if k != "k_requested"},
                random_at_k={k: v for k, v in random_baseline(df, k_requested, values).items()
                             if k not in ("k_requested", "k_applied")},
                **_published(curve),
            )
            evaluations.append(entry)

    return {
        "assumptions": {
            "action_effectiveness": values["value"]["action_effectiveness"],
            "loss_given_event": values["value"]["loss_given_event"],
            "cost_per_contact_cop": values["value"]["cost_per_contact_cop"],
            "default_capacity_share": share,
        },
        "evaluations": evaluations,
    }
