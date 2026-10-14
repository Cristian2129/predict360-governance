# Sprint 1 Planning Minutes — PCM Analytics (FinBank Predict360)

- **Date & Time:** Tuesday, October 13, 20:00
- **Participants:** Cristian Vega (Project Leader), Paula Gacha (Business Analyst), Marco Jimenez (Scrum Facilitator)
- **Sprint 1 Goal:** Establish and operationalizrine the governance method, exposure-based prioritization, data quality auditing, and evidence-based closure with automated unit tests (TDD).

---

## 1. Governance Agreements & Definition of Done (DoD) Update
After reviewing the bottleneck observed dug the Cut 1 simulation (where 3 out of 4 stories remained held waiting for external sponsor signature), the team formally agrees to:
1. **Closure Rule Update (Option B):** Sponsor feedback is recorded directly in the review minutes during the *Sprint Review* ceremony. Accordingly, Acceptance Criterion #4 of US-01 on the board is updated from *"Signed off by the sponsor before the end of Week 2"* to *"Presented in the Sprint Review with sponsor feedback logged in the review minutes"*.
2. **Board WIP Control:** A strict work-in-progress limit (WIP Max = 3) is configured and displayed on the `In Progress` list.

---

## 2. Capacity Re-estimation & Sprint 1 Scope
In the initial Cut 1 proposal, **21 SP** were projected for Sprint 1, noting that this initial load exceeded the project average (~9 SP) and would be recalibrated. For the compressed execution:
- **US-01 (Governance framework):** Re-estimated from **5 SP to 2 SP**, since the RACI matrix was already drafted during Cut 1 and only the six-sprint meeting cadence and final evidence attachment remain.
- **US-03 (Data readiness & quality thresholds — 8 SP total):** Split into two parts to guarantee verifiable closures:
  - **US-03 (Part 1 — 5 SP in Sprint 1):** Data source inventory, threshold definitions, and automated `quality.py` module with unit tests.
  - **US-03 (Part 2 — 3 SP in Sprint 2):** Ley 1581 de 2012 compliance review and Gap Report with mitigations.

---

## 3. Committed Sprint 1 Backlog (Estimated Velocity: 15 SP)

| Story ID | User Story Title | Owner | SP | Verifiable Deliverable (DoD) |
| :--- | :--- | :--- | :---: | :--- |
| **US-06** | Evidence-based sprint closure mechanism | Marco Jimenez | 5 | Board with WIP=3, DoR/DoD published, and `sprint_metrics.py` with tests. |
| **US-02** | Exposure-based backlog prioritization | Cristian Vega | 3 | Documented prioritization rule and `exposure.py` with `pytest` tests. |
| **US-03 (P1)** | Data readiness & quality thresholds (Part 1) | Paula Gacha | 5 | Source inventory, thresholds, and `quality.py` with `pytest` tests. |
| **US-01** | Governance framework (RACI & cadence) | Cristian Vega | 2 | RACI matrix + 6-sprint cadence in `docs/evidence/raci_governance.md`. |
| **TOTAL** | **4 Committed Stories** | **PCM Team** | **15 SP** | **100% with TDD validation and approved Pull Request.** |