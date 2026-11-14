"""Station 8, evaluator core: exposure capture in COP, net value and K* (technical spec, sections 4 and 9).

Formulas (y event, E exposure in COP millions, K clients contacted, e effectiveness,
l share of exposure lost, c cost per contact), all assumptions from ``config/assumptions.yaml``:

    capture(K)   = sum_topK(E * y) / sum(E * y)
    net_value(K) = e * l * sum_topK(E * y) - c * K
    K*           = argmax_K net_value(K)

- K counts clients: each row weighs ``weight`` clients and rows are never split. The
  applied K is the last point of the published curve not above the requested K
  (``applied_point``, rounding down: capacity is a hard limit). The dashboard simulator
  applies the same rule to the same published curve. Both values are reported, and cost,
  capture and the random baseline all use ``k_applied`` so that the model and the
  baseline are compared on the same K.
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

Ranking metrics, calibration and promotion (B8b):

- precision, recall and lift count clients (weights), at K and on every published curve
  point; PR-AUC is the average precision over the same ranking as the capture curve;
  Brier score and a calibration table by score decile, with no cell under
  ``evaluation.min_cell_clients`` (small cells are merged with a neighbour).
- Promotion (A11, A16): a paired bootstrap resamples rows with their weights and scores the
  model and the baseline rule on the SAME resamples at the SAME K. The model beats the rule
  only if the lower bound of the interval of the net value difference (model - rule) is
  above ``promotion.margin_cop_m``. This refines the spec rule "the intervals do not
  overlap": a paired interval answers the same question with less noise.
- Delinquency must beat the rule on every horizon (30 and 60 days), each reported apart.
  Among the models that do, the highest net value at K summed over the horizons is
  recommended (ties go to the first model_id); if the interval of its difference with the
  runner-up includes 0, the verdict says the difference is inconclusive.
- Each comparison has an outcome: ``beats``, ``insufficient_evidence`` (the point difference
  is above the margin but the interval reaches it) or ``does_not_beat_baseline`` (the point
  difference is not above the margin). A ``not_authorized`` verdict carries the matching
  ``reason_code`` (or ``no_baseline`` / ``no_candidate``), so the committee sees why.
- The strongest verdict is ``authorized_for_shadow_deployment``. The verdict does not
  change any card status: moving a card to ``shadow`` is FinBank's signed decision.

``bootstrap_net_values`` and ``interval`` are reused by the slices (B8c), which with
intervened clients are built on top of this core.
"""
from __future__ import annotations

import numpy as np
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


def _ranked(df: pd.DataFrame) -> pd.DataFrame:
    """Highest score first; ties broken by client_id (see the module docstring)."""
    return df.sort_values(["score", "client_id"], ascending=[False, True], kind="mergesort")


def capture_curve(df: pd.DataFrame, values: dict, keep_order: bool = False) -> pd.DataFrame:
    """Cumulative curve over whole-row prefixes, from K = 0 to every client.

    df columns: client_id, score, y (0/1), exposure_cop_m, weight.
    """
    ranked = _ranked(df)
    event_exposure = ranked["exposure_cop_m"] * ranked["y"]
    curve = pd.DataFrame({
        "k": ranked["weight"].cumsum().to_numpy(),
        "captured_cop_m": event_exposure.cumsum().to_numpy(),
        "event_clients": (ranked["weight"] * ranked["y"]).cumsum().to_numpy(),
    })
    # The total is the last cumulative value, not a separate sum: both round differently,
    # and a non-decreasing cumsum then keeps every capture <= 1 and the last one exactly 1
    total = float(curve["captured_cop_m"].iloc[-1]) if len(curve) else 0.0
    if keep_order:
        curve["client_id"] = ranked["client_id"].to_numpy()
    start = pd.DataFrame({"k": [0.0], "captured_cop_m": [0.0], "event_clients": [0.0]})
    curve = pd.concat([start, curve], ignore_index=True)
    curve["capture"] = curve["captured_cop_m"] / total if total else float("nan")
    curve["net_value_cop_m"] = (_gain_cop_m(curve["captured_cop_m"], values)
                                - _contact_cost_cop_m(curve["k"], values))
    events, clients = float(curve["event_clients"].iloc[-1]), float(curve["k"].iloc[-1])
    curve["precision"] = curve["event_clients"] / curve["k"].where(curve["k"] > 0)
    curve["recall"] = curve["event_clients"] / events if events else float("nan")
    curve["lift"] = curve["precision"] / (events / clients) if events else float("nan")
    return curve


def _number_or_none(value):
    return None if pd.isna(value) else float(value)


def _point(row) -> dict:
    return {
        "k": float(row["k"]),
        "capture": _number_or_none(row["capture"]),
        "captured_cop_m": float(row["captured_cop_m"]),
        "net_value_cop_m": float(row["net_value_cop_m"]),
        "precision": _number_or_none(row["precision"]),
        "recall": _number_or_none(row["recall"]),
        "lift": _number_or_none(row["lift"]),
    }


def _row_at(curve: pd.DataFrame, k_requested: float) -> pd.Series:
    """Whole-row prefix not above k_requested (builds the published grid)."""
    return curve[curve["k"] <= k_requested + _EPS].iloc[-1]


def applied_point(points: list[dict], k_requested: float) -> dict:
    """THE K rule, shared with the dashboard simulator (dashboard_assets/simulator.js):
    the last point of the published curve with k <= k_requested. It rounds DOWN, never to
    the nearest, because capacity is a hard limit: nobody calls more clients than the team
    can handle. Using the published grid lets the simulator apply exactly the same rule."""
    return [p for p in points if p["k"] <= k_requested + _EPS][-1]


def evaluate_at_k(df: pd.DataFrame, k_requested: float, values: dict) -> dict:
    point = dict(applied_point(_published_curve(capture_curve(df, values)), k_requested))
    k_applied = point.pop("k")
    return {"k_requested": k_requested, "k_applied": k_applied, **point}


def random_baseline(df: pd.DataFrame, k_requested: float, values: dict) -> dict:
    """Expected result of contacting k_applied clients at random (analytical, no simulation)."""
    k_applied = float(applied_point(_published_curve(capture_curve(df, values)), k_requested)["k"])
    total = float((df["exposure_cop_m"] * df["y"]).sum())
    share = k_applied / float(df["weight"].sum())
    prevalence = float((df["weight"] * df["y"]).sum() / df["weight"].sum())
    captured = total * share
    return {
        "k_requested": k_requested,
        "k_applied": k_applied,
        "capture": share if total else None,
        "captured_cop_m": captured,
        "net_value_cop_m": _gain_cop_m(captured, values) - _contact_cost_cop_m(k_applied, values),
        "precision": prevalence if k_applied else None,
        "recall": share if prevalence else None,
        "lift": 1.0 if prevalence and k_applied else None,
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
        row = _row_at(curve, target)
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


def pr_auc(df: pd.DataFrame):
    """Average precision over the capture ranking, weighted by clients; None without events."""
    ranked = _ranked(df)
    events = ranked["weight"] * ranked["y"]
    total = float(events.sum())
    if not total:
        return None
    precision = events.cumsum() / ranked["weight"].cumsum()
    return float((events / total * precision).sum())


def brier_score(df: pd.DataFrame) -> float:
    return float((df["weight"] * (df["score"] - df["y"]) ** 2).sum() / df["weight"].sum())


def calibration_table(df: pd.DataFrame, values: dict, bins: int = 10) -> list[dict]:
    """Mean score against observed rate by score decile (rows are never split).

    A cell under ``evaluation.min_cell_clients`` is merged with the next one (the last with
    the previous one); if the whole table is under that minimum nothing is published.
    """
    minimum = values["evaluation"]["min_cell_clients"]
    total = float(df["weight"].sum())
    if total < minimum:
        return []
    ranked = df.sort_values(["score", "client_id"], kind="mergesort")
    before = ranked["weight"].cumsum() - ranked["weight"]
    cell = np.minimum((bins * before / total).astype(int), bins - 1)
    sums = pd.DataFrame({"cell": cell, "n": ranked["weight"], "ws": ranked["weight"] * ranked["score"],
                         "wy": ranked["weight"] * ranked["y"]}).groupby("cell", sort=True)[["n", "ws", "wy"]].sum()
    cells = sums.to_dict("records")
    while len(cells) > 1:
        small = [i for i, c in enumerate(cells) if c["n"] < minimum]
        if not small:
            break
        i = small[0]
        j = i + 1 if i + 1 < len(cells) else i - 1
        merged = {key: cells[i][key] + cells[j][key] for key in ("n", "ws", "wy")}
        cells[min(i, j):max(i, j) + 1] = [merged]
    return [{"bin": number, "n_clients": float(c["n"]), "mean_score": float(c["ws"] / c["n"]),
             "observed_rate": float(c["wy"] / c["n"])} for number, c in enumerate(cells, start=1)]


def _rank_order(rows: pd.DataFrame, score) -> np.ndarray:
    """Row positions in capture order for one model's scores."""
    frame = pd.DataFrame({"score": np.asarray(score, dtype=float),
                          "client_id": rows["client_id"].to_numpy(), "pos": np.arange(len(rows))})
    return _ranked(frame)["pos"].to_numpy()


def _net_at_k(sequence: np.ndarray, weight: np.ndarray, event_exposure: np.ndarray,
              k_clients: float, values: dict) -> float:
    """Net value of contacting the whole-row prefix of `sequence` not above k_clients."""
    cumulative = np.cumsum(weight[sequence])
    taken = int(np.searchsorted(cumulative, k_clients + _EPS, side="right"))
    k_applied = float(cumulative[taken - 1]) if taken else 0.0
    captured = float(event_exposure[sequence[:taken]].sum())
    return _gain_cop_m(captured, values) - _contact_cost_cop_m(k_applied, values)


def bootstrap_net_values(rows: pd.DataFrame, scores: dict, k_clients: float, values: dict,
                         samples: int, seed: int) -> dict[str, np.ndarray]:
    """Net value at a fixed K for every model on the SAME resamples (paired bootstrap).

    rows: client_id, y, exposure_cop_m, weight. scores: model_id -> scores aligned to rows.
    Each resample draws len(rows) rows with replacement and keeps their weights; a row drawn
    twice counts as two rows. Only aggregates come back: one net value per model and resample.
    """
    weight = rows["weight"].to_numpy(dtype=float)
    event_exposure = (rows["exposure_cop_m"] * rows["y"]).to_numpy(dtype=float)
    orders = {model_id: _rank_order(rows, score) for model_id, score in scores.items()}
    draws = {model_id: np.empty(samples) for model_id in scores}
    rng = np.random.default_rng(seed)
    for sample in range(samples):
        counts = np.bincount(rng.integers(0, len(rows), len(rows)), minlength=len(rows))
        for model_id, order in orders.items():
            draws[model_id][sample] = _net_at_k(np.repeat(order, counts[order]), weight,
                                                event_exposure, k_clients, values)
    return draws


def interval(draws: np.ndarray, level: float) -> tuple[float, float]:
    """Percentile interval of the bootstrap draws."""
    low, high = np.percentile(draws, [50 * (1 - level), 50 * (1 + level)])
    return float(low), float(high)


def _outcome(difference: float, low: float, margin: float) -> str:
    """beats: the whole interval is above the margin; insufficient_evidence: the point
    difference is above the margin but the interval reaches it; otherwise the model does not
    beat the baseline."""
    if low > margin:
        return "beats"
    return "insufficient_evidence" if difference > margin else "does_not_beat_baseline"


def _compare_with_baseline(entries: dict, frames: dict, baseline: str, values: dict):
    """Fills ``vs_baseline`` of every evaluated model of one label; returns the draws."""
    promotion = values["promotion"]
    for entry in entries.values():
        entry["vs_baseline"] = None
    if baseline not in entries or len(entries) < 2:
        return {}
    rows = frames[baseline].drop(columns="score")
    k_requested = entries[baseline]["k_requested"]
    draws = bootstrap_net_values(rows, {m: f["score"] for m, f in frames.items()}, k_requested, values,
                                 promotion["bootstrap_samples"], promotion["bootstrap_seed"])
    for model_id, entry in entries.items():
        if model_id == baseline:
            continue
        margin = float(promotion["margin_cop_m"])
        low, high = interval(draws[model_id] - draws[baseline], promotion["confidence_level"])
        difference = entry["at_k"]["net_value_cop_m"] - entries[baseline]["at_k"]["net_value_cop_m"]
        entry["vs_baseline"] = {
            "baseline_model": baseline,
            "k_clients": entry["k_applied"],
            "difference_cop_m": difference,
            "ci_low_cop_m": low,
            "ci_high_cop_m": high,
            "confidence_level": promotion["confidence_level"],
            "margin_cop_m": margin,
            "beats": bool(low > margin),
            "outcome": _outcome(difference, low, margin),
        }
    return draws


def _decide(target: str, labels: list[str], entries: dict, draws: dict, baseline: str,
            baseline_models, values: dict) -> dict:
    """Verdict for one target. entries/draws: label -> model_id -> evaluation entry / draws."""
    promotion = values["promotion"]
    level, margin = promotion["confidence_level"], float(promotion["margin_cop_m"])
    decision = {"target": target, "verdict": "not_authorized", "reason_code": None, "model_id": None,
                "also_beat_baseline": [], "runner_up": None}

    missing = [label for label in labels if baseline not in entries.get(label, {})]
    if missing:
        decision.update(reason_code="no_baseline",
                        reason=f"No comparable baseline: {baseline} was not evaluated on {', '.join(missing)}, "
                               "so no model can be authorized.")
        return decision

    def outcome(label, model_id):
        comparison = (entries[label].get(model_id) or {}).get("vs_baseline")
        return comparison["outcome"] if comparison else "not_evaluated"

    candidates = sorted({m for label in labels for m in entries[label]} - set(baseline_models))
    failed = {m: [label for label in labels if outcome(label, m) != "beats"] for m in candidates}
    winners = [m for m in candidates if not failed[m]]
    if not candidates:
        decision.update(reason_code="no_candidate",
                        reason=f"No candidate model was evaluated against {baseline}.")
        return decision
    if not winners:
        # Insufficient evidence when some model is ahead on every horizon it does not win
        ahead = any(all(outcome(label, m) == "insufficient_evidence" for label in failed[m]) for m in candidates)
        detail = "; ".join(f"{m} on {', '.join(f'{label} ({outcome(label, m)})' for label in failed[m])}"
                           for m in candidates)
        decision.update(reason_code="insufficient_evidence" if ahead else "does_not_beat_baseline",
                        reason=f"No model beat {baseline} by more than {margin:g} COP M at K on every horizon "
                               f"({', '.join(labels)}) at {level:.0%} confidence: {detail}.")
        return decision

    def total(model_id):
        return sum(entries[label][model_id]["at_k"]["net_value_cop_m"] for label in labels)

    ranked = sorted(winners, key=lambda m: (-total(m), m))
    best = ranked[0]
    decision.update(verdict="authorized_for_shadow_deployment", reason_code="authorized", model_id=best,
                    also_beat_baseline=ranked[1:])
    reason = (f"{best} beats {baseline} on {', '.join(labels)}: the lower bound of the {level:.0%} interval of "
              f"the net value difference at K is above the margin of {margin:g} COP M. It is recommended "
              "for shadow deployment, the strongest possible verdict")
    if len(ranked) > 1:
        second = ranked[1]
        low, high = interval(sum(draws[label][best] - draws[label][second] for label in labels), level)
        conclusive = not (low <= 0 <= high)
        decision["runner_up"] = {"model_id": second, "difference_cop_m": total(best) - total(second),
                                 "ci_low_cop_m": low, "ci_high_cop_m": high, "conclusive": conclusive}
        reading = f"it also beats {second}" if conclusive else f"its difference with {second} is inconclusive"
        reason += f"; {reading} ({level:.0%} interval [{low:.1f}, {high:.1f}] COP M)"
    decision["reason"] = reason + "."
    return decision


def _admitted(gate2_report: dict) -> list[tuple[str, str]]:
    return sorted({(c["target"], c["model_id"]) for c in gate2_report["cards"] if c["decision"] == "ADMITTED"})


def _horizons(values: dict) -> dict[str, list[int]]:
    return {"delinquency": [int(h) for h in values["delinquency"]["horizons_days"]],
            "churn": [int(values["churn"]["horizon_days"])]}


def evaluate_models(labeled: dict, scores: pd.DataFrame, gate2_report: dict, values: dict,
                    baseline_models=("baseline_rule",)) -> dict:
    """Evaluates every ADMITTED card on every label of its target and decides per target.

    labeled: output of ``labeling.label_all``. scores: long format (scores_v1).
    A labeled client without a score leaves that model and label ``not_evaluated``
    (``incomplete_scores``); scores of clients outside the labeled table (immature
    rows) are dropped and counted. baseline_models: ``gate2.baseline_models`` of the run
    config; models are compared with the first one and none of them can be recommended.
    """
    key = ["client_id", "model_id", "horizon_days"]
    duplicated = int(scores.duplicated(subset=key).sum())
    if duplicated:
        raise ValueError(f"{duplicated} duplicate (client_id, model_id, horizon_days) score row(s): "
                         "the same exposure would be counted twice")

    share = values["value"]["default_capacity_share"]
    horizons = _horizons(values)
    evaluations = []
    frames: dict[str, dict[str, pd.DataFrame]] = {}      # label -> model_id -> rows with score
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
                metrics={"pr_auc": pr_auc(df), "brier": brier_score(df),
                         "calibration": calibration_table(df, values)},
            )
            evaluations.append(entry)
            frames.setdefault(label, {})[model_id] = df

    baseline = baseline_models[0]
    decisions = []
    for target in sorted({t for t, _ in _admitted(gate2_report)}):
        labels = [label_column(target, h) for h in horizons[target]]
        entries, draws = {}, {}
        for label in labels:
            entries[label] = {e["model_id"]: e for e in evaluations
                              if e["label"] == label and e["status"] == "evaluated"}
            draws[label] = _compare_with_baseline(entries[label], frames.get(label, {}), baseline, values)
        decisions.append(_decide(target, labels, entries, draws, baseline, baseline_models, values))

    promotion = values["promotion"]
    return {
        "assumptions": {
            "action_effectiveness": values["value"]["action_effectiveness"],
            "loss_given_event": values["value"]["loss_given_event"],
            "cost_per_contact_cop": values["value"]["cost_per_contact_cop"],
            "default_capacity_share": share,
            "margin_cop_m": promotion["margin_cop_m"],
            "bootstrap_samples": promotion["bootstrap_samples"],
            "bootstrap_seed": promotion["bootstrap_seed"],
            "confidence_level": promotion["confidence_level"],
            "min_cell_clients": values["evaluation"]["min_cell_clients"],
        },
        "evaluations": evaluations,
        "decisions": decisions,
    }
