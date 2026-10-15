# XP Practices Technical Log — PCM Analytics (FinBank Predict360)

Traceability record of the 4 *Extreme Programming (XP)* engineering practices executed during Sprints 1 and 2.

## 1. Pair Programming & Modeling
| Session | Sprint | Module / Task | Driver | Navigator | Evidence |
| :---: | :---: | :--- | :--- | :--- | :--- |
| 1 | Sprint 1 | `sprint_metrics.py` (US-06) | Marco Jimenez | Cristian Vega | *[screenshot in `docs/pairing/Screenshot 2026-10-14 122517.png`]* |
| 2 | Sprint 1 | `quality.py` (US-03 P1) | Paula Gacha | Marco Jimenez | *[screenshot in `docs/pairing/us04_pairing_teams.png`]* |
| 3 | Sprint 2 | `reconcile.py` (US-04 P1) | Paula Gacha | Marco Jimenez | `docs/pairing/us04_pairing_teams.png` (recorded in `c4ff7cc`); co-authored commits `e7939ea65a4bdacc43a51e0ff7300f9921122cd5`|
| 4 | Sprint 2 | Refactor `exposure.py` (US-02 / XP-04) | Cristian Vega | Marco Jimenez | *[screenshot in `docs/pairing/pairingrefactor.png`]* |

> Requirement: at least **two** documented sessions with a photo/screenshot or `Co-authored-by:` commits. Session 3 is complete. Add a screenshot for one more session, and delete any row that did not take place.

## 2. Test-Driven Development (TDD)
- **Test Suite:** Located in `tests/` and executed automatically via `pytest` on every Pull Request through GitHub Actions (`ci.yml`).
- **Enforced Cycle:** `test:` (red) $\rightarrow$ `feat:` (green) $\rightarrow$ `refactor:` (clean design while keeping all tests green).
- **Execution report:** `docs/evidence/pytest_report.txt` (output of `python -m pytest tests/ -v`).

**Test-first commit history (red → green)**
| Story | Test commit (red) | Feature commit (green) | Date | Author | PR |
| :--- | :---: | :---: | :---: | :--- | :---: |
| US-02 Exposure prioritization | `e7af26f` | `09af9d2` | 2026-10-14 | Cristian Vega | #11 |
| US-03 P1 Data quality audit | `5802b88` | `35484a5` | 2026-10-14 | Paula Gacha | #12 |
| US-04 P1 Delinquency reconciliation | `e7939ea` | `1bf81a6` | 2026-10-14 / 2026-10-15 | Paula Gacha | #13 |


## 3. Continuous Integration & Collective Ownership (Pull Requests)
| PR # | Branch | Story | Author | Approving Reviewer | CI Status |
| :---: | :--- | :--- | :--- | :--- | :---: |
| #1 | `feature/us-06-sprint-metrics` | US-06 | Marco Jimenez | Paula Gacha | *merged* |
| #2 | `feature/us-02-exposure-ordering` | US-02 | Cristian Vega | Marco Jimenez | *merged* |
| #3 | `feature/us-03-data-quality` | US-03 P1 | Paula Gacha | Marco Jimenez | *merged* |
| #4 | `feature/us-04-reconcile-baseline` | US-04 P1 | Paula Gacha | Cristian Vega | *merged* |
| #5 | `refactor/quality-simple-design` | US-03 / XP-04 | Paula Gacha | Cristian Vega | *merged*|
| #6 | `refactor/quality-simple-design` | US-07| Marco Jimenez | Cristian Vega | *merged*|
> Reviewer and CI columns come from each PR page on GitHub (Approved review and green check). No author approves their own PR.

## 4. Simple Design & Refactoring (Before vs. After)

### Refactor: `src/predict360/exposure.py` (US-02)
**Branch / PR:** `refactor/exposure-simple-design` — *[PR # / commit hash]*
**Driver / Navigator:** Cristian Vega / *[Navigator]*

**Problems found**
1. The same rule ("exposure > 0 means risk-bearing, otherwise enabling") was written twice, as two separate `lambda` functions.
2. The report text hardcoded `COP 231,000M raw sum`. The real raw sum of `backlog.csv` is **COP 289,800M** (77,000 × 2 umbrella + 58,800 × 2 + 18,200), so the evidence file stated a wrong figure.
3. The docstring and report said the backlog is ranked by efficiency, but the code sorts by exposure first and uses efficiency only to break ties.

**Before**
```python
if "exposure_type" not in result.columns:
    result["exposure_type"] = result["exposure_cop_m"].apply(
        lambda x: "direct" if x > 0 else "enabling"
    )

result["priority_tier"] = result["exposure_cop_m"].apply(
    lambda x: "Risk-Bearing" if x > 0 else "Enabling"
)
```
```python
"... to prevent double-counting (COP 231,000M raw sum vs. COP 77,000M net portfolio) and ranks stories by **Exposure Efficiency (`COP M / SP`)**.\n",
```

**After**
```python
# One rule decides both labels: a story either carries exposure or it is enabling work.
has_exposure = result["exposure_cop_m"] > 0
if "exposure_type" not in result.columns:
    result["exposure_type"] = has_exposure.map({True: "direct", False: "enabling"})
result["priority_tier"] = has_exposure.map({True: "Risk-Bearing", False: "Enabling"})
```
```python
raw_total = float(ordered["exposure_cop_m"].sum())  # double-counted, computed from the data
f"... (COP {raw_total:,.1f}M raw sum vs. COP {direct_total:,.1f}M net portfolio) and ranks stories by exposure, breaking ties with **Exposure Efficiency (`COP M / SP`)**.\n"
```

**Result**
- Two duplicated lambdas replaced by one condition; no behaviour change in ranking, tiers, or direct total (COP 77,000M).
- The reported raw sum is now derived from the data (COP 289,800.0M) and `docs/evidence/backlog_prioritization.md` was regenerated.
- Two new tests added first (`test_exposure_type_is_derived_when_column_is_absent`, `test_export_reports_raw_sum_computed_from_data`); the suite went from `1 failed, 6 passed` to `7 passed`.

### Additional cleanup: repository hygiene (PR #15)
**Commit:** `4aba4ab` — `chore: move .gitignore to repo root and untrack compiled .pyc files` (Cristian Vega)
- `.gitignore` moved to the repository root so it actually applies, and compiled `.pyc` files removed from version control. This reduces noise in diffs and avoids conflicts between team members.