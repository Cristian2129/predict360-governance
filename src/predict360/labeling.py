"""Station 4 (Label): window labels, label maturity and anti-leakage guard.

Technical spec, sections 2 and 3. Horizons come from ``config/assumptions.yaml``
(``delinquency.horizons_days``, ``churn.horizon_days``), never from the code.

- Label: 1 if the first event date falls in (T, T + H]; otherwise 0.
- Maturity: a horizon is labeled only if ``observation_end_date >= T + H``; otherwise
  the label stays empty (``Int8`` null, never 0). A row with no mature horizon leaves
  the table and is counted in the funnel. An event seen before an immature end of
  observation does not rescue the row.
- Anti-leakage: an event dated on or before T is rejected, and the labeled table
  drops every date after T (event and end-of-observation dates).

Delinquency and churn are different cohorts (all active loans vs. preferred clients),
so each one gets its own labeled table and funnel.

Cohort exclusions that the v1 contracts cannot check are reported as ``not_verifiable``
in the funnel, never as 0 excluded rows (a 0 would claim a check that did not happen):

- delinquency, loans already in arrears at T.
  TODO(FinBank, contract v2): add ``current_dpd`` (days past due at T).
- churn, loans maturing within the horizon.
  TODO(FinBank, contract v2): add ``maturity_date``.

In the synthetic data the cohort already meets both conditions because
``make_synthetic`` builds it that way; only real data leaves them pending.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.predict360.config import CONFIG_DIR, load_assumptions

NOT_VERIFIABLE = "not_verifiable"
LABEL_DTYPE = "Int8"
OBSERVATION_END = "observation_end_date"

DELINQUENCY_EVENT = "first_delinquency_date"
CHURN_EVENT = "cancellation_date"

UNVERIFIABLE_COHORT_STEPS = {
    "delinquency": {"step": "cohort_not_in_arrears_at_T", "missing_column": "current_dpd"},
    "churn": {"step": "cohort_not_maturing_within_horizon", "missing_column": "maturity_date"},
}


def _churn_label_name(horizon_days: int) -> str:
    """churn_3m for the 90-day spec horizon; whole months as ``churn_<n>m``, otherwise ``churn_<n>d``."""
    return f"churn_{horizon_days // 30}m" if horizon_days % 30 == 0 else f"churn_{horizon_days}d"


def label_column(target: str, horizon_days: int) -> str:
    """Label name for a target and horizon: delinquency_30, delinquency_60, churn_3m."""
    if target == "delinquency":
        return f"delinquency_{int(horizon_days)}"
    if target == "churn":
        return _churn_label_name(int(horizon_days))
    raise ValueError(f"Unknown target: {target}")


def _count(df: pd.DataFrame, mask=None) -> dict:
    part = df if mask is None else df[mask]
    return {"rows": int(len(part)), "clients": float(part["weight"].sum())}


def _label(df: pd.DataFrame, table: str, snapshot_date, event_column: str,
           horizons: dict[str, int]) -> tuple[pd.DataFrame, dict]:
    """horizons: label name -> horizon in days."""
    t = pd.Timestamp(str(snapshot_date))
    event = pd.to_datetime(df[event_column])
    observed_until = pd.to_datetime(df[OBSERVATION_END])

    leaked = int((event <= t).sum())
    if leaked:
        raise ValueError(f"{table}: {leaked} {event_column} value(s) on or before the cut-off "
                         f"date {t.date()}; an event must happen after T")

    labels, horizon_stats = {}, {}
    for name, days in sorted(horizons.items(), key=lambda item: item[1]):
        end = t + pd.Timedelta(days=days)
        mature = observed_until >= end
        positive = event.notna() & (event <= end)
        labels[name] = pd.Series(positive.astype("int8"), index=df.index,
                                 dtype=LABEL_DTYPE).where(mature, pd.NA)
        weight = df.loc[mature, "weight"]
        positives = positive & mature
        horizon_stats[name] = {
            "horizon_days": int(days),
            "mature_rows": int(mature.sum()),
            "mature_clients": float(weight.sum()),
            "immature_rows": int((~mature).sum()),
            "positive_rows": int(positives.sum()),
            "positive_clients": float(df.loc[positives, "weight"].sum()),
            "base_rate": round(float(df.loc[positives, "weight"].sum() / weight.sum()), 6)
            if weight.sum() else None,
        }

    labeled = pd.DataFrame(labels, index=df.index)
    keep = labeled.notna().any(axis=1)
    out = pd.concat([df.drop(columns=[event_column, OBSERVATION_END]), labeled], axis=1)
    out = out[keep].reset_index(drop=True)

    funnel = {
        "table": table,
        "snapshot_date": t.date().isoformat(),
        "steps": [
            {"step": "input", **_count(df)},
            {**UNVERIFIABLE_COHORT_STEPS[table], "status": NOT_VERIFIABLE},
            {"step": "excluded_immature_all_horizons", **_count(df, ~keep)},
            {"step": "labeled", **_count(df, keep)},
        ],
        "horizons": horizon_stats,
    }
    return out, funnel


def label_delinquency(df: pd.DataFrame, snapshot_date, horizons_days) -> tuple[pd.DataFrame, dict]:
    """Adds ``delinquency_<H>`` per horizon; returns the labeled table and its funnel."""
    horizons = {label_column("delinquency", h): int(h) for h in horizons_days}
    return _label(df, "delinquency", snapshot_date, DELINQUENCY_EVENT, horizons)


def label_churn(df: pd.DataFrame, snapshot_date, horizon_days) -> tuple[pd.DataFrame, dict]:
    """Adds ``churn_3m`` (90 days by default assumption); returns the labeled table and its funnel."""
    horizons = {label_column("churn", horizon_days): int(horizon_days)}
    return _label(df, "churn", snapshot_date, CHURN_EVENT, horizons)


def label_all(delinquency_df: pd.DataFrame, churn_df: pd.DataFrame, snapshot_date,
              assumptions_path: str | Path = CONFIG_DIR / "assumptions.yaml") -> dict:
    """Labels both cohorts with the horizons declared in the assumptions file."""
    values = load_assumptions(assumptions_path)["values"]
    dlq_table, dlq_funnel = label_delinquency(delinquency_df, snapshot_date,
                                              values["delinquency"]["horizons_days"])
    churn_table, churn_funnel = label_churn(churn_df, snapshot_date, values["churn"]["horizon_days"])
    return {
        "delinquency": {"table": dlq_table, "funnel": dlq_funnel},
        "churn": {"table": churn_table, "funnel": churn_funnel},
    }
