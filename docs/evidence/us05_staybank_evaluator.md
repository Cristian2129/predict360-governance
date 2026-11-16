# US-05 — StayBank and model registry: churn labels, model cards, evaluator in COP

Sprint 3 (brought forward from Sprint 4) · 8 SP · Owners: Paula Gacha (labeling, cards, evaluator), Marco Jimenez (lineage, reconciliation, Gate 3), Cristian Vega (pipeline)

## Acceptance criteria and evidence

| Criterion | How it is met | Evidence |
| --- | --- | --- |
| Churn label `churn_3m` defined as voluntary early cancellation within 90 days, preferred segment by exposure | `labeling.py` (churn) with the assumptions in `config/assumptions.yaml`; natural maturity excluded (needs `maturity_date`, requested as `churn_v2`) | PR #26 · `tests/test_labeling.py` |
| Churn exposure reconciles with the client figure | `reconcile.py` (churn) | PR #27 · `tests/test_reconcile.py` |
| A model enters evaluation only with an admissible card (Gate 2) | `model_card.py`: complete card, traceable to the scores hash, temporal split, preprocessing fitted on training only, statuses backed by an approver | PR #28 · `tests/test_model_card.py` |
| Gate 2 is shown rejecting a leaky model | Demo card `delinquency_model_c` (synthetic only), rejected for exactly one reason, `temporal_split`, and labelled as a demonstration on the dashboard | PR #42 |
| Any model is evaluated in COP against random and the baseline rule | `evaluator.py`: capture curve, net value at the capacity K (one K rule shared with the dashboard simulator), K*, precision/recall/lift, PR-AUC, Brier, calibration | PR #29, #32, #35 · `tests/test_evaluator.py` |
| Mandatory test case | 1,000 clients, K = 100, 50 events of 10 M, effectiveness 40 %, cost 20,000 → random 18, rule 58, model 118 (COP M net value) | `tests/test_evaluator.py`, `tests/test_simulator_parity.py` |
| The verdict needs evidence, not a point estimate | Paired bootstrap of the net value difference against the rule; delinquency must win at 30 and 60 days; the highest verdict is «authorized for shadow deployment» | PR #35 · `evaluation.json` · Modelos view |
| Every run is traceable and every cited figure is checked (Gate 3) | `lineage.py`: manifest per run and append-only, hash-chained `lineage_log.jsonl`; `consistency.py`: registered figures and citations | PR #31, #36 · `tests/test_lineage.py`, `tests/test_consistency.py` |
| One command runs every station and writes the evidence record | `run_pipeline.py`; official run refused with uncommitted code or real data | PR #37 · `tests/test_run_pipeline.py` |

## How to reproduce

```
PYTHONPATH=. python -m src.predict360.run_pipeline --config config/synthetic.yaml
PYTHONPATH=. pytest tests/test_model_card.py tests/test_evaluator.py tests/test_consistency.py tests/test_lineage.py -v
```


## Honest reading of the result

The scores are simulated, not trained models. With the synthetic data no model is authorized: the point estimate of a model can exceed the rule while its paired interval still crosses zero, so the evidence is insufficient. Slices (B8c) were cut and stay pending.
