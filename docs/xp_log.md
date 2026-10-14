# XP Practices Technical Log — PCM Analytics (FinBank Predict360)

Traceability record of the 4 *Extreme Programming (XP)* engineering practices executed during Sprints 1 and 2.

## 1. Pair Programming & Modeling
| Session | Sprint | Module / Task | Driver | Navigator | Commit Hash (`Co-authored-by:`) | Evidence |
| :---: | :---: | :--- | :--- | :--- | :--- | :--- |
| 1 | Sprint 1 | `sprint_metrics.py` (US-06) | Marco Jimenez | Cristian Vega | *Pending* |  |
| 2 | Sprint 1 | `quality.py` (US-03 P1) | Paula Gacha | Cristian Vega | *Pending* | |
| 3 | Sprint 2 | `reconcile.py` (US-04 P1) | Paula Gacha | Marco Jimenez | *Pending* |  |
| 4 | Sprint 2 | Refactor `quality.py` | Paula Gacha | Cristian Vega | *Pending* | |

## 2. Test-Driven Development (TDD)
- **Test Suite:** Located in `tests/` and executed automatically via `pytest` on every Pull Request through GitHub Actions (`ci.yml`).
- **Enforced Cycle:** `test:` (red) $\rightarrow$ `feat:` (green) $\rightarrow$ `refactor:` (clean design while keeping all tests green).

## 3. Continuous Integration & Collective Ownership (Pull Requests)
| PR # | Branch | Story | Author | Approving Reviewer | CI Status |
| :---: | :--- | :--- | :--- | :--- | :---: |
| #1 | `feature/us-06-sprint-metrics` | US-06 | Marco Jimenez | Paula Gacha | *Pending* |
| #2 | `feature/us-02-exposure-ordering` | US-02 | Cristian Vega | Marco Jimenez | *Pending* |
| #3 | `feature/us-03-data-quality` | US-03 P1 | Paula Gacha | Marco Jimenez | *Pending* |
| #4 | `feature/us-04-reconcile-baseline` | US-04 P1 | Paula Gacha | Cristian Vega | *Pending* |
| #5 | `refactor/quality-simple-design` | US-03 / XP-04 | Paula Gacha | Cristian Vega | *Pending* |

## 4. Simple Design & Refactoring (Before vs. After)
