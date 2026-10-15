# Sprint 2 Planning Minutes — PCM Analytics (FinBank Predict360)

- **Date & Time:** *15/10/2026*
- **Participants:** Cristian Vega (Project Leader), Paula Gacha (Business Analyst), Marco Jimenez (Scrum Facilitator)
- **Sprint 2 Goal:** Reconcile the synthetic EarlyRisk portfolio against the COP 58,800M delinquency exposure, review privacy gaps under Ley 1581 de 2012, and keep risks and impediments visible on the board.

---

## 1. Inputs from Sprint 1
- Sprint 1 closed with the governance baseline, the exposure-based prioritization (`exposure.py`), the data-quality gate (`quality.py`) and the sprint metrics module (`sprint_metrics.py`).
- Data-quality finding carried forward: `churn` fails the 5% threshold (24 of 200 `tenure_months` missing = 12%).
- Closure rule in force: sponsor feedback is recorded in the Sprint Review minutes (Option B, agreed in Sprint 1 Planning). WIP limit = 3.

## 2. Committed Sprint 2 Backlog (Estimated Velocity: 13 SP)

| Story ID | User Story Title | Owner | SP | Verifiable Deliverable (DoD) |
| :--- | :--- | :--- | :---: | :--- |
| **US-03 (P2)** | Data readiness: Ley 1581 compliance & gap report | Paula Gacha | 3 | `docs/evidence/us03_p2_ley1581_gap_report.md` |
| **US-04 (P1)** | EarlyRisk: delinquency baseline & early-warning requirements | Paula Gacha | 5 | `reconcile.py` with `pytest` tests and `docs/evidence/us04_reconciliation.md` |
| **US-07** | Risk and impediment visibility | Marco Jimenez | 5 | Risk register mirrored in the `Blocked/Risks` list of the board |
| **TOTAL** | **3 Committed Stories** | **PCM Team** | **13 SP** | **100% with TDD validation and approved Pull Request.** |

## 3. XP Work Planned in Sprint 2 (not story-pointed)
- Pairing session on `reconcile.py` (Paula / Marco).
- Refactor of `exposure.py` (XP-04), each in its own `refactor/` branch and PR.
- Documentation branch to close Corte 2 evidence: dailies, retrospectives, pairing log, sprint metrics.

## 4. Risks Considered
- **R-01 (Data quality):** churn gap (12% missing) must be documented, not hidden.
- **R-04 (Regulatory):** the gap report covers a synthetic dataset only; it is not a legal opinion about FinBank.
