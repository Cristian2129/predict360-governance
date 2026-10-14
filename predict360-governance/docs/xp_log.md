# Bitácora Técnica de Prácticas XP — PCM Analytics (FinBank Predict360)

Registro de trazabilidad de las 4 prácticas de *Extreme Programming (XP)* ejecutadas durante los Sprints 1 y 2.

## 1. Pair Programming & Modeling
| Sesión | Sprint | Módulo / Tarea | Piloto | Copiloto | Commit Hash (`Co-authored-by:`) | Evidencia |
| :---: | :---: | :--- | :--- | :--- | :--- | :--- |
| 1 | Sprint 1 | `sprint_metrics.py` (US-06) | Cristian Vega | Marco Jimenez | *Pendiente* | `docs/pairing/session1_metrics.png` |
| 2 | Sprint 1 | `quality.py` (US-03 P1) | Paula Gacha | Cristian Vega | *Pendiente* | `docs/pairing/session2_quality.png` |
| 3 | Sprint 2 | `reconcile.py` (US-04 P1) | Paula Gacha | Marco Jimenez | *Pendiente* | `docs/pairing/session3_reconcile.png` |
| 4 | Sprint 2 | Refactor `quality.py` | Paula Gacha | Cristian Vega | *Pendiente* | `docs/pairing/session4_refactor.png` |

## 2. Test-Driven Development (TDD)
- **Suite de pruebas:** Ubicada en `tests/` y ejecutada automáticamente con `pytest` en cada PR mediante GitHub Actions.
- **Ciclo aplicado:** `test:` (rojo) $\rightarrow$ `feat:` (verde) $\rightarrow$ `refactor:` (limpieza manteniendo tests en verde).

## 3. Integración Continua & Propiedad Colectiva (Pull Requests)
| PR # | Rama | Historia | Autor | Revisor que aprueba | Estado CI |
| :---: | :--- | :--- | :--- | :--- | :---: |
| #1 | `feature/us-06-sprint-metrics` | US-06 | Cristian / Marco | Paula Gacha | *Pendiente* |
| #2 | `feature/us-02-exposure-ordering` | US-02 | Marco / Cristian | Cristian / Marco | *Pendiente* |
| #3 | `feature/us-03-data-quality` | US-03 P1 | Paula Gacha | Marco Jimenez | *Pendiente* |
| #4 | `feature/us-04-reconcile-baseline` | US-04 P1 | Paula Gacha | Cristian Vega | *Pendiente* |
| #5 | `refactor/quality-simple-design` | US-03 / XP-04 | Paula Gacha | Cristian Vega | *Pendiente* |

## 4. Diseño Simple & Refactoring (Antes vs. Después)
