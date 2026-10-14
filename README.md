# FinBank Predict360 — Governance & Analytical Quality Toolkit (Cut 2: Scrum + XP)

Official repository of **PCM Analytics** (Paula Gacha, Cristian Vega, Marco Jimenez) for the execution of **Sprints 1 and 2** of the **FinBank Predict360** project in *Gestión, Metodologías Ágiles y Capstone (GMAC)*.

## 1. Purpose of the Increment
Following the scope approved in the *Project Charter* (*"We govern by exposure and close by evidence"*), this repository implements a reproducible Python toolkit to:
- **`exposure.py` (US-02):** Automatically prioritize the Product Backlog by quantified financial exposure (COP 58,800M in Early Delinquency ranked ahead of COP 18,200M in Churn; non-exposure items flagged as *Enabling*).
- **`quality.py` (US-03):** Audit each data source against explicit quality thresholds (missing values, out-of-range risk scores, data types) and return a *pass/fail* status.
- **`sprint_metrics.py` (US-06):** Read `docs/sprint_log.csv`, compute team Velocity and Burndown curves, and generate the official report charts.
- **`reconcile.py` (US-04):** Verify that the synthetic credit portfolio reconciles against the COP 58,800M delinquency exposure within the defined tolerance.


## 2. Team Working Rules (Scrum + XP)
- **Protected `main` Branch:** All changes enter via *Pull Request (PR)* with at least **1 peer approval**. No author approves their own PR.
- **Branch Naming Convention:** `feature/us-XX-short-name` or `refactor/short-name`.
- **TDD Commit History:** Every technical module follows the strict cycle: first a `test:` commit (failing unit test), then a `feat:` commit (implementation passing in green), and `refactor:` when applicable.
- **Pair Programming:** Sessions alternate *Driver* and *Navigator* roles, logged in `docs/xp_log.md` and recorded via the `Co-authored-by:` commit trailer.
- **Definition of Done (DoD):** 100% of acceptance criteria completed, verifiable evidence attached on Trello and in `docs/evidence/`, `pytest` unit tests passing in green, PR reviewed/approved, and increment presented in the *Sprint Review*.

## 3. Local Execution
```bash
pip install -r requirements.txt
python src/predict360/make_synthetic.py
PYTHONPATH=. pytest tests/ -v
python src/predict360/sprint_metrics.py