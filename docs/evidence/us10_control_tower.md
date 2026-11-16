# US-10 — Web control tower (CR-01)

Sprint 3 · 5 SP · Academic request, scope change CR-01 paid from the contingency · Owners: Cristian Vega (shell, export, trace, simulator), Paula Gacha (Models view), Marco Jimenez (Management view)

## Acceptance criteria and evidence

| Criterion | How it is met | Evidence |
| --- | --- | --- |
| The dashboard reads one JSON with a versioned contract, aggregates only | `dashboard_data_v1` contract and validator; written by the pipeline inside the run before the manifest closes | PR #33, #39 · `tests/test_dashboard_contract.py`, `tests/test_export_dashboard_data.py` |
| One self-contained page, no network, no hand-written figures | `dashboard_render.py` renders `index.html` with inline CSS and SVG; a test forbids client figures in the source | PR #34 · `tests/test_dashboard_render.py` |
| Every figure can be traced to its origin | Trace per registered figure: output file and hash, path, script, commit, sources; Datos y linaje view | PR #40 |
| Stress simulator that matches the evaluator | `simulator.js` mirrors the evaluator formulas and K rule; parity tested with Node 20 in CI and self-checked in the browser; marked as a hypothetical scenario that never changes the verdict | PR #41 · `tests/test_simulator_parity.py` |
| Views answer one question each | Resumen; Datos (can the data be trusted?); Modelos (which model ranks best and is the evidence enough?); Estrés; Gestión (EVM against the ceiling, velocity, risks) | PR #44, #45, Data view PR |
| Only checked pages are published | `publish_pages.py`: fixture with a loud banner until the official run exists; then the official page only if the lineage chain and the page hashes verify | PR #39 · `tests/test_publish_pages.py` |

