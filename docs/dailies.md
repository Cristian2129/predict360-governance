# Daily Scrum Log — PCM Analytics (FinBank Predict360)

Synchronization record across Sprints 1 and 2.

## Sprint 1
### Daily 1 — 2026-10-14 09:00 COT
- **Cristian Vega (Project Leader):**
  - *What I did:* Built `src/predict360/make_synthetic.py` and documented the RACI governance framework (`docs/evidence/raci_governance.md`) and Sprint 1 Planning minutes, and opened PR #1 for **US-01**. Fixed the repository root path so GitHub Actions (`pytest-validation` on Python 3.13) executes automatically on every Pull Request.
  - *What I will do:* Pair with Marco Jimenez on **US-06** (`sprint_metrics.py`) and develop the exposure prioritization logic (`exposure.py`) for **US-02**.
  - *Impediments:* GitHub Actions did not trigger initially because `.github/workflows/ci.yml` was nested inside a subfolder (`predict360-governance/`); resolved via `git mv` to the repository root.
- **Paula Gacha (Business Analyst):**
  - *What I did:* Audited the synthetic datasets generated in **US-01** (`delinquency_sample.csv` with 300 rows and `churn_sample.csv` with 200 rows) and wrote the unit tests in `tests/test_quality.py` for **US-03 P1** to enforce the 5.0% missing-value threshold, type validation, and range checks.
  - *What I will do:* Implement `src/predict360/quality.py` to pass the TDD suite, generate the Sprint 1 data inventory report (`docs/evidence/data_inventory_s1.md`), and open the Pull Request for **US-03 P1**.
  - *Impediments:* Confirmed that `tenure_months` in `churn_sample.csv` (StayBank, COP 18,200.0M) has a **12.0% missing rate**, exceeding the 5.0% governance threshold and triggering risk **R-01** (`BLOCKED_R01`).
- **Marco Jimenez (Scrum Facilitator):**
  - *What I did:* Created the `feature/us-06-sprint-metrics` branch and implemented velocity and burndown calculations, chart generation, and unit tests for US-06. Adapted the code to the real `sprint_log.csv` format and opened the Pull Request.
  - *What I will do:* Resolve the PR conflicts with `main`, confirm tests and CI pass, upload evidence to `docs/evidence/`, and request Cristian's review.
  - *Impediments:* PR conflicts with `main` (PR #2 was merged and reverted earlier), and `sprint_log.csv` had no `Done` stories, so completed velocity showed 0.

## Sprint 2
### Daily 2 — 2026-10-14 09:00 COT
- **Cristian Vega (Project Leader):**
  - *What I did:* Completed **US-02** (`src/predict360/exposure.py` and `tests/test_exposure.py`) separating `direct`, `umbrella`, and `enabling` exposures (COP 77,000.0M net direct portfolio), merged the Sprint 1 PRs into `main`, and facilitated the Sprint 2 Planning (`docs/sprint2_planning.md`).
  - *What I will do:* Refactor `exposure.py` (single exposure rule, raw total computed from data) and review Paula's PRs.
  - *Impediments:* Internal audit of `backlog_prioritization.md` and `exposure.py` revealed a hardcoded raw sum (`COP 231,000M` instead of the true `COP 289,800M` column sum) and a duplicated lambda between `priority_tier` and the default `exposure_type`.
- **Paula Gacha (Business Analyst):**
  - *What I did:* Wrote the Ley 1581 privacy review and gap report (US-03 P2) in `docs/evidence/us03_p2_ley1581_gap_report.md`.
  - *What I will do:* Pair with Marco on `reconcile.py` (US-04 P1) following TDD.
  - *Impediments:* StayBank (`churn_sample.csv`) cannot enter direct modeling until the median imputation protocol for `tenure_months` (`R-01`) and the pseudonymized hash validation (`CLI_`, `PREF_` under Law 1581 / `R-04`) are formally signed off in the PR review.
- **Marco Jimenez (Scrum Facilitator):**
  - *What I did:* Resolved the merge conflicts on `feature/us-06-sprint-metrics`, verified green CI checks on `main`, and documented the Sprint 1 Retrospective (`docs/retro_sprint1.md`) and RACI tracking baselines.
  - *What I will do:* Pair with Paula on `reconcile.py`; start the risk register on the `Blocked/Risks` list (US-07).
  - *Impediments:* Need to keep the **US-07** implementation decoupled from `make_synthetic.py` and `backlog.csv` so it does not create merge conflicts with `reconcile.py` or the ongoing refactoring branches.

### Daily 3 — 2026-10-15 09:00 COT
- **Cristian Vega (Project Leader):**
  - *What I did:* Refactored `exposure.py`: removed the duplicated rule, fixed the hardcoded raw total (231,000M → 289,800M computed from data), regenerated `backlog_prioritization.md`.
  - *What I will do:* Open the `refactor/` PR and request review.
  - *Impediments:* None on `exposure.py` (all unit tests pass); only pending the final commit hashes from Pairing Session 4 (`refactor/quality-simple-design`) to close Section 1 and Section 4 of `docs/xp_log.md`.
- **Paula Gacha (Business Analyst):**
  - *What I did:* Finished `reconcile.py` with tests; reconciliation PASS (COP 58,800.00M, difference 0.000000M) saved in `docs/evidence/us04_reconciliation.md`.
  - *What I will do:* Refactor `quality.py` with Cristian (pairing session 4) and open the PR.
  - *Impediments:* In `src/predict360/quality.py`, `_is_valid_type` is currently evaluated twice per value during the range check inside `audit_source`; we need to extract the missing, type, and range checks into single-responsibility helper functions without breaking the existing test suite.
- **Marco Jimenez (Scrum Facilitator):**
  - *What I did:* Completed **US-07** (`impediment_tracker.py` and `tests/test_impediment_tracker.py`) validating the 24-hour SLA governance gate (`response_hours <= 24.0`, assigned owner, and mitigation action) and Expected Monetary Value (`emv_cop_m`) prioritization across `R-01` to `R-04`, generating `docs/evidence/risk_register.md`.
  - *What I will do:* Update `sprint_log.csv`, generate the Burndown and Velocity charts, and prepare the Sprint Review.
  - *Impediments:* `docs/sprint_log.csv` still listed `US-03-P1` as `In_Progress` and Sprint 2 stories as `Planned`, causing Sprint 2 velocity to compute as 0; updating all completed stories to `Done` before running `sprint_metrics.py` so the PNG charts in `reports/figures/` render accurately.