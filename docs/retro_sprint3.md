# Sprint 3 Retrospective — PCM Analytics (FinBank Predict360)

- **Date:** 2026-11-14
- **Participants:** Cristian Vega, Paula Gacha, Marco Jimenez
- **Format:** Start / Stop / Continue


## Sprint 3 in numbers

- **Committed:** 16 SP (US-04 P2, US-05, US-10) against a capacity of about 14 SP: the overcommitment was declared at planning.
- **Completed:** see `docs/sprint_log.csv` once the stories with evidence are marked Done. No story is marked Done without its evidence («No attachment, no Done»).
- **Cost and schedule:** read SPI, CPI and EAC from the Gestión view of the run (generated from `docs/hours_log.csv` and `docs/sprint_log.csv`); no figure is typed here. While the sprint was open, its EV was zero and the EAC rose above the ceiling; that is how binary DoD earned value behaves, not a cost overrun.

## Declared deviations

1. **Sprint close moved from Thursday 12 to Saturday 14 November.** One declared deviation, decided on 13 November.
2. **Code freeze and official run moved after the visual redesign** (team decision, 14 November). The official run hashes `index.html`, so it must run on the final design. The report is due on 18 November.
3. **Scope change CR-01** (US-10, web control tower) approved and paid from the contingency: it moved from the reserve into the BAC.

## What went well / Continue

- Strict TDD with one block per branch and small PRs.
- Figures come from the pipeline and are checked by Gate 3; the dashboard has a trace for every registered figure.
- Honest verdicts: insufficient evidence is reported as such, and the simulator never changes the verdict.
- *(team)*

## What did not work / Stop

- Overcommitting a sprint by bringing a story forward (US-05) and adding a scope change (US-10) in the same sprint.

## What to try / Start

- Close stories as soon as their evidence exists, so earned value does not wait for the last day.
- *(team)*

## Cut and carried over

| Item | Cut line | Where it goes |
| --- | --- | --- |
| Slices and score stability (B8c) | 2 | Sprint 4 |
| «Entrega a FinBank» tab and «break the data» button (B12d) | 1 | Sprint 4 |
| Visual redesign for the presentation | — | Before the official run |
| US-09 | — | Sprint 6 (as planned) |

## Known debt (to tell in the report as a lesson)

- `docs/dailies.md`: repeated dates, 300 vs 500 rows, mentions an `impediment_tracker.py` that does not exist.
- `docs/xp_log.md`: PR numbers that do not match.
- `data/risk_reviews.csv` is empty: the dashboard shows «Sin revisiones registradas».
- Fixed in this sprint: versioned `__pycache__` (PR #24) and `sprint_log.csv` against the Sprint 2 report (12 November).
 |
