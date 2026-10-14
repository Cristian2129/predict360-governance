# Daily Scrum Log — PCM Analytics (FinBank Predict360)

Synchronization record across Sprints 1 and 2.

## Sprint 1
### Daily 1 — [Date / Time]
- **Cristian Vega (Project Leader):**
  - *What I did:* Built `src/predict360/make_synthetic.py` and documented the RACI governance framework (`docs/evidence/raci_governance.md`) and Sprint 1 Planning minutes, and opened PR #1 for **US-01**. Fixed the repository root path so GitHub Actions (`pytest-validation` on Python 3.13) executes automatically on every Pull Request.
  - *What I will do:* Pair with Marco Jimenez on **US-06** (`sprint_metrics.py`) and develop the exposure prioritization logic (`exposure.py`) for **US-02**.
  - *Impediments:* GitHub Actions did not trigger initially because `.github/workflows/ci.yml` was nested inside a subfolder (`predict360-governance/`); resolved via `git mv` to the repository root.
- **Paula Gacha (Business Analyst):**
  - *What I did:* 
  - *What I will do:* 
  - *Impediments:* 
- **Marco Jimenez (Scrum Facilitator):**
  - *What I did:* Created the `feature/us-06-sprint-metrics` branch and implemented velocity and burndown calculations, chart generation, and unit tests for US-06. Adapted the code to the real `sprint_log.csv` format and opened the Pull Request.
  - *What I will do:* Resolve the PR conflicts with `main`, confirm tests and CI pass, upload evidence to `docs/evidence/`, and request Cristian's review.
  - *Impediments:* PR conflicts with `main` (PR #2 was merged and reverted earlier), and `sprint_log.csv` has no `Done` stories, so completed velocity shows 0.
