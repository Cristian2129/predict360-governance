# US-04 P2 — EarlyRisk: 30/60-day specification and labeled dataset

Sprint 3 · 3 SP · Owners: Paula Gacha (labeling), Marco Jimenez (Gate 1), Cristian Vega (config and synthetic data)

## Acceptance criteria and evidence

| Criterion | How it is met | Evidence |
| --- | --- | --- |
| The delinquency event is specified in configuration, not in code | `config/assumptions.yaml` (DPD threshold, 30/60-day horizons) and contract `config/contracts/delinquency_v1.yaml` | PR #19 |
| Labels `delinquency_30` and `delinquency_60` are built without leakage | `labeling.py`: an event dated on or before the cut-off T is rejected; rows whose observation window is not complete are excluded per horizon, never labeled 0 | PR #26 · `tests/test_labeling.py` |
| Every exclusion is counted | Labeling funnel per table (input → cohort → immature → labeled) with rows and clients; the cohort step that needs `current_dpd` is reported as *not verifiable* and becomes a `delinquency_v2` request to FinBank | `labeling_funnel.json` in every run · Datos view of the dashboard |
| Data is validated before use (Gate 1) | `quality.py`: Great Expectations-style rules from the contracts; a non-critical failure continues only with a written, unexpired waiver | PR #23 · `tests/test_quality_gate1.py` |
| Delinquency exposure reconciles with the client figure | `reconcile.py` runs in every pipeline run against `reconciliation.delinquency_expected_cop_m` | `reconciliation.json` · Resumen view |
| Only synthetic data in the repository; the HMAC key never versioned | `make_synthetic.py` v2 (seed 42, LF line endings so hashes do not depend on the OS); demo key public and refused outside synthetic configs | PR #20, #21, #22, #25 · `tests/test_make_synthetic.py`, `tests/test_config.py` |

## How to reproduce

```
PYTHONPATH=. python -m src.predict360.run_pipeline --config config/synthetic.yaml
PYTHONPATH=. pytest tests/test_labeling.py tests/test_quality_gate1.py tests/test_reconcile.py -v
```

Figures are read from the run folder (`runs/<run_id>/`), never typed here.

## Screenshots

- [ ] Datos view: Gate 1 verdict and labeling funnel (attach)
- [ ] Test run output (attach)

## Known limits

- The cohort filter (not in arrears at T) cannot be verified until FinBank adds `current_dpd` (`delinquency_v2`).
