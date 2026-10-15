# Sprint 2 Retrospective — PCM Analytics (FinBank Predict360)

- **Date:** 2026-10-15
- **Participants:** Cristian Vega, Paula Gacha, Marco Jimenez
- **Format:** Start / Stop / Continue

## Sprint 2 in numbers
- **Planned:** 13 SP (US-03 P2, US-04 P1, US-07).
- **Completed:** 13 SP (100%) — see `reports/figures/velocity_comparison.png` and `burndown_sprint2.png` (generated from `docs/sprint_log.csv`).

## What went well / Continue
- **Fixed Pair Programming commit attribution from Sprint 1:** In Sprint 1 we were not properly formatting `Co-authored-by:` trailers (or used unverified emails), which left pairing sessions without automatic GitHub attribution. In Sprint 2 we standardized `Co-authored-by:` commit trailers using each teammate's exact Git email (`git log --format="%an <%ae>"`), ensuring verifiable co-authored hashes in GitHub and `docs/xp_log.md`.
- `reconcile.py` (US-04 P1) built with TDD and pairing; the synthetic delinquency exposure reconciles to COP 58,800.00M (difference 0.000000M, PASS).
- Ley 1581 gap report produced with 7 gaps, priorities and an action plan, clearly stating it is not a legal opinion about FinBank.
- Refactors done in their own branches (`refactor/exposure-simple-design`) with tests kept green and co-authored commits properly recorded.

## What did not work / Stop
- Reporting numbers typed by hand: the backlog report said COP 231,000M raw sum while the data sums to COP 289,800M. Found during the `exposure.py` refactor.
- The report text said "ranked by efficiency" while the code ranks by exposure first. Documentation and code drifted apart.
- Typos and unclear English in documents (planning minutes, gap report) because documents were not peer-reviewed like code.
- Story ownership concentrated in one person: 8 of the 13 SP in Sprint 2 were owned by Paula.

## What to try / Start
- Derive every reported figure from the data (no hardcoded totals).
- Review documents in PRs with the same rigor as code, including verifying `Co-authored-by:` trailers on paired commits before merging.
- Balance story ownership across the three roles in Sprint 3.
- Keep `sprint_log.csv` and the Trello board consistent before each Sprint Review.

## Action items
| Action | Owner | Due |
| :--- | :--- | :--- |
| Peer-review documentation and verify `Co-authored-by:` trailers in every PR | Whole team | Sprint 3 |
| Balance story ownership in Sprint 3 Planning | Cristian Vega | Sprint 3 |
| Check `sprint_log.csv` against the board before each review | Marco Jimenez | Sprint 3 |