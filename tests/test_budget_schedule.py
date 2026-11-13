"""Tests for budget_schedule (technical spec, section 12): PV, EV, AC, SPI, CPI and EAC.

Hand-computed figures use the Charter baseline decided on 2026-11-12:
ceiling 180M = BAC 160M + contingency 20M; CR-01 moves 8.333333M from the reserve to Sprint 3.
"""
import pandas as pd
import pytest

from src.predict360.budget_schedule import MGMT_STORY, budget_baseline, budget_schedule
from src.predict360.config import load_assumptions


@pytest.fixture(scope="module")
def values():
    return load_assumptions()["values"]


def _without_change_requests(values):
    return {**values, "budget": {**values["budget"], "change_requests": []}}


def _hours(*rows):
    """rows: (sprint, person, hours, story_id, estimated, date)."""
    return pd.DataFrame(rows, columns=["sprint", "person", "hours", "story_id", "estimated", "date"])


def _sprint_log(sprint, committed_sp, done_sp):
    """One story per SP block: done stories first."""
    rows = [{"sprint": sprint, "story_id": f"US-{sprint}{i:02d}", "story_points": 1,
             "status": "Done" if i < done_sp else "In Progress", "closed_block": 1}
            for i in range(committed_sp)]
    return pd.DataFrame(rows)


def _sprint3_hours(total=51.0, story="US-05"):
    per_person = total / 3
    return _hours(*[(3, p, per_person, story, 0, "2026-11-11")
                    for p in ("Cristian Vega", "Paula Gacha", "Marco Jimenez")])


def _sprint(report, number):
    (found,) = [s for s in report["sprints"] if s["sprint"] == number]
    return found


# --- baseline: BAC, reserve and change requests ------------------------------------

def test_rate_is_derived_and_not_rounded(values):
    base = budget_baseline(values)
    assert base["rate_cop"] == pytest.approx(180_000_000 / 1620)
    assert base["rate_cop"] != 111_111
    assert base["logged_hour_cop_m"] == pytest.approx(7.5 * 180 / 1620)  # 0.8333...M per logged hour


def test_contingency_is_kept_out_of_the_baseline(values):
    base = budget_baseline(_without_change_requests(values))
    assert base["bac_cop_m"] == pytest.approx(160.0)
    assert base["reserve_remaining_cop_m"] == pytest.approx(20.0)
    assert base["pv_by_sprint_cop_m"] == pytest.approx({s: 160 / 6 for s in range(1, 7)})


def test_cr01_moves_money_from_the_reserve_to_sprint_3(values):
    base = budget_baseline(values)
    assert base["pv_by_sprint_cop_m"][3] == pytest.approx(35.0, abs=1e-5)
    assert base["pv_by_sprint_cop_m"][1] == pytest.approx(160 / 6)
    assert base["bac_cop_m"] == pytest.approx(168.333333, abs=1e-5)
    assert base["reserve_remaining_cop_m"] == pytest.approx(11.666667, abs=1e-5)
    assert sum(base["pv_by_sprint_cop_m"].values()) == pytest.approx(base["bac_cop_m"])
    assert base["change_requests"] == [{"id": "CR-01", "sprint": 3, "approved_cop_m": 8.333333}]


def test_change_requests_cannot_exceed_the_reserve(values):
    over = {**values, "budget": {**values["budget"],
                                 "change_requests": [{"id": "CR-99", "sprint": 4, "approved_cop_m": 25.0}]}}
    with pytest.raises(ValueError, match="reserve"):
        budget_baseline(over)


# --- the Sprint 3 case ---------------------------------------------------------------

def test_sprint3_case_51_hours_all_sp_closed(values):
    report = budget_schedule(_sprint3_hours(), _sprint_log(3, 16, 16), values)
    s3 = _sprint(report, 3)
    assert s3["pv_cop_m"] == pytest.approx(35.0, abs=1e-5)
    assert s3["ev_cop_m"] == pytest.approx(35.0, abs=1e-5)
    assert s3["ac_cop_m"] == pytest.approx(42.5)
    assert s3["spi"] == pytest.approx(1.0)
    assert s3["cpi"] == pytest.approx(35 / 42.5, abs=1e-6)  # 0.824
    assert s3["change_requests_cop_m"] == pytest.approx(8.333333)


def test_ev_is_pv_times_share_of_sp_closed_with_dod(values):
    s3 = _sprint(budget_schedule(_sprint3_hours(), _sprint_log(3, 16, 13), values), 3)
    assert (s3["committed_sp"], s3["done_sp"]) == (16, 13)
    assert s3["ev_cop_m"] == pytest.approx(35.0 * 13 / 16, abs=1e-5)


def test_management_hours_add_to_ac_but_not_to_ev(values):
    base = budget_schedule(_sprint3_hours(), _sprint_log(3, 16, 16), values)
    hours = pd.concat([_sprint3_hours(), _hours((3, "Marco Jimenez", 3.0, MGMT_STORY, 0, "2026-11-12"))])
    with_mgmt = budget_schedule(hours, _sprint_log(3, 16, 16), values)
    s3, b3 = _sprint(with_mgmt, 3), _sprint(base, 3)
    assert s3["ev_cop_m"] == pytest.approx(b3["ev_cop_m"])
    assert s3["ac_cop_m"] == pytest.approx(b3["ac_cop_m"] + 2.5)   # 3 h x 0.8333M
    assert s3["mgmt_hours"] == 3.0 and s3["mgmt_ac_cop_m"] == pytest.approx(2.5)


# --- cumulative EAC against the 180M ceiling --------------------------------------------

def _three_sprints():
    hours = pd.concat([
        _hours((1, "Cristian Vega", 12.0, "US-01", 1, "2026-10-15"),
               (1, "Paula Gacha", 12.0, "US-03-P1", 1, "2026-10-15"),
               (1, "Marco Jimenez", 12.0, "US-06", 1, "2026-10-15")),
        _hours((2, "Cristian Vega", 12.0, "US-04-P1", 1, "2026-10-29"),
               (2, "Paula Gacha", 12.0, "US-03-P2", 1, "2026-10-29"),
               (2, "Marco Jimenez", 12.0, "US-07", 1, "2026-10-29")),
        _sprint3_hours(),
    ])
    log = pd.concat([_sprint_log(1, 15, 15), _sprint_log(2, 13, 13), _sprint_log(3, 16, 16)])
    return hours, log


def test_eac_is_cumulative_and_compared_with_the_ceiling(values):
    hours, log = _three_sprints()
    cum = budget_schedule(hours, log, values)["cumulative"]
    pv = 160 / 6 * 2 + 35.0
    ac = 36 * 2 * 7.5 * 180 / 1620 + 42.5            # 30 + 30 + 42.5 = 102.5
    assert cum["pv_cop_m"] == pytest.approx(pv, abs=1e-5)
    assert cum["ev_cop_m"] == pytest.approx(pv, abs=1e-5)
    assert cum["ac_cop_m"] == pytest.approx(ac)
    assert cum["cpi"] == pytest.approx(pv / ac, abs=1e-6)
    eac = 168.333333 / (pv / ac)
    assert cum["eac_cop_m"] == pytest.approx(eac, abs=1e-3)   # ~195.3M, not 255M from Sprint 3 alone
    assert cum["ceiling_cop_m"] == 180
    assert cum["eac_minus_ceiling_cop_m"] == pytest.approx(eac - 180, abs=1e-3)
    assert cum["eac_over_ceiling"] is True


def test_estimated_hours_are_flagged_per_sprint(values):
    hours, log = _three_sprints()
    report = budget_schedule(hours, log, values)
    assert _sprint(report, 1)["estimated_hours"] == 36.0
    assert _sprint(report, 1)["hours_estimated"] is True
    assert _sprint(report, 3)["estimated_hours"] == 0.0
    assert _sprint(report, 3)["hours_estimated"] is False
    assert report["cumulative"]["estimated_hours"] == 72.0


def test_hours_of_sprints_not_yet_in_the_sprint_log_are_kept_apart(values):
    hours = pd.concat([_sprint3_hours(), _hours((4, "Paula Gacha", 2.0, "US-08", 0, "2026-11-13"))])
    report = budget_schedule(hours, _sprint_log(3, 16, 16), values)
    assert [s["sprint"] for s in report["sprints"]] == [3]
    assert report["hours_outside_reported_sprints"] == {4: 2.0}
    assert report["cumulative"]["ac_cop_m"] == pytest.approx(42.5)


def test_sprint_without_hours_has_zero_ac_and_no_cpi(values):
    s3 = _sprint(budget_schedule(_hours(), _sprint_log(3, 16, 16), values), 3)
    assert s3["ac_cop_m"] == 0.0 and s3["cpi"] is None
