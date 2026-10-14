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
  - *What I did:* 
  - *What I will do:* 
  - *Impediments:*
