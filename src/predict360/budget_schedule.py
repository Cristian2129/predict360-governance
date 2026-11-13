"""Station 10, project management: PV, EV, AC, SPI, CPI and EAC in COP millions.

Baseline (``config/assumptions.yaml``, A13-A15):

- BAC = ceiling - contingency (180M - 20M = 160M); PV per sprint = BAC / sprints.
  The contingency reserve stays apart, so its use is visible.
- An approved change request moves its amount from the reserve to the BAC and to the
  PV of its sprint (CR-01: 8.33M to Sprint 3, so PV = 35M, BAC = 168.33M, reserve 11.67M).
- The rate is derived, never rounded: ceiling / planned consultant hours (180M / 1,620 h).
  One logged hour costs k_scale x rate (7.5 x 111,111.11 = 833,333.33 COP).

Per sprint (sprints present in ``docs/sprint_log.csv``):

- AC = logged hours x k x rate, including estimated hours and MGMT (management work
  without SP): management is a real cost, so it counts in AC and never in EV.
- EV = PV x SP closed with DoD (status Done) / SP committed.
- SPI = EV / PV, CPI = EV / AC.

The EAC is cumulative (BAC / cumulative CPI) and is compared with the 180M ceiling;
a single sprint's CPI would give a misleading EAC. Hours of sprints not yet in the
sprint log are reported apart, not mixed into the cumulative figures.
"""
from __future__ import annotations

import pandas as pd

COP_PER_MILLION = 1_000_000
MGMT_STORY = "MGMT"
DONE_STATUS = "Done"


def _ratio(part: float, total: float):
    return part / total if total else None


def budget_baseline(values: dict) -> dict:
    budget = values["budget"]
    ceiling, contingency = budget["ceiling_cop_m"], budget["contingency_cop_m"]
    sprints = int(budget["sprints"])
    pv = {s: (ceiling - contingency) / sprints for s in range(1, sprints + 1)}
    change_requests = list(budget.get("change_requests") or [])
    approved = 0.0
    for cr in change_requests:
        pv[int(cr["sprint"])] += cr["approved_cop_m"]
        approved += cr["approved_cop_m"]
    if approved > contingency + 1e-9:
        raise ValueError(f"Change requests approve {approved}M but the contingency reserve is {contingency}M")
    rate_cop = ceiling * COP_PER_MILLION / budget["planned_consultant_hours"]
    return {
        "ceiling_cop_m": ceiling,
        "contingency_cop_m": contingency,
        "change_requests": change_requests,
        "bac_cop_m": ceiling - contingency + approved,
        "reserve_remaining_cop_m": contingency - approved,
        "pv_by_sprint_cop_m": pv,
        "k_scale": budget["k_scale"],
        "rate_cop": rate_cop,
        "logged_hour_cop_m": budget["k_scale"] * rate_cop / COP_PER_MILLION,
    }


def budget_schedule(hours_log: pd.DataFrame, sprint_log: pd.DataFrame, values: dict) -> dict:
    """Earned value per sprint and cumulative, from the hours log and the sprint log."""
    base = budget_baseline(values)
    hour_cost = base["logged_hour_cop_m"]
    hours = hours_log.assign(hours=pd.to_numeric(hours_log["hours"]),
                             sprint=pd.to_numeric(hours_log["sprint"]).astype("int64"),
                             estimated=pd.to_numeric(hours_log["estimated"]).astype("int64"))
    reported = sorted(int(s) for s in sprint_log["sprint"].unique())

    sprints = []
    for number in reported:
        stories = sprint_log[sprint_log["sprint"] == number]
        committed = int(stories["story_points"].sum())
        done = int(stories.loc[stories["status"] == DONE_STATUS, "story_points"].sum())
        mine = hours[hours["sprint"] == number]
        logged = float(mine["hours"].sum())
        estimated = float(mine.loc[mine["estimated"] == 1, "hours"].sum())
        mgmt = float(mine.loc[mine["story_id"] == MGMT_STORY, "hours"].sum())
        pv = base["pv_by_sprint_cop_m"][number]
        ev = pv * done / committed if committed else 0.0
        ac = logged * hour_cost
        sprints.append({
            "sprint": number,
            "committed_sp": committed,
            "done_sp": done,
            "pv_cop_m": pv,
            "ev_cop_m": ev,
            "ac_cop_m": ac,
            "spi": _ratio(ev, pv),
            "cpi": _ratio(ev, ac),
            "logged_hours": logged,
            "estimated_hours": estimated,
            "hours_estimated": estimated > 0,
            "mgmt_hours": mgmt,
            "mgmt_ac_cop_m": mgmt * hour_cost,
            "change_requests_cop_m": sum(cr["approved_cop_m"] for cr in base["change_requests"]
                                         if int(cr["sprint"]) == number),
        })

    pv, ev, ac = (sum(s[key] for s in sprints) for key in ("pv_cop_m", "ev_cop_m", "ac_cop_m"))
    cpi = _ratio(ev, ac)
    eac = base["bac_cop_m"] / cpi if cpi else None
    outside = hours[~hours["sprint"].isin(reported)].groupby("sprint")["hours"].sum()
    return {
        "baseline": {k: v for k, v in base.items() if k != "pv_by_sprint_cop_m"}
        | {"pv_by_sprint_cop_m": {str(k): v for k, v in base["pv_by_sprint_cop_m"].items()}},
        "sprints": sprints,
        "cumulative": {
            "sprints": reported,
            "pv_cop_m": pv,
            "ev_cop_m": ev,
            "ac_cop_m": ac,
            "spi": _ratio(ev, pv),
            "cpi": cpi,
            "bac_cop_m": base["bac_cop_m"],
            "eac_cop_m": eac,
            "ceiling_cop_m": base["ceiling_cop_m"],
            "eac_minus_ceiling_cop_m": None if eac is None else eac - base["ceiling_cop_m"],
            "eac_over_ceiling": None if eac is None else eac > base["ceiling_cop_m"],
            "estimated_hours": sum(s["estimated_hours"] for s in sprints),
            "mgmt_hours": sum(s["mgmt_hours"] for s in sprints),
        },
        "hours_outside_reported_sprints": {int(k): float(v) for k, v in outside.items()},
    }
