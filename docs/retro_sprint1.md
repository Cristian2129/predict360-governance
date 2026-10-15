# Sprint 1 Retrospective — PCM Analytics (FinBank Predict360)

- **Date:** *15/10/2026*
- **Participants:** Cristian Vega, Paula Gacha, Marco Jimenez
- **Format:** Start / Stop / Continue

## Sprint 1 in numbers
- **Planned:** 15 SP (US-06, US-02, US-03 P1, US-01).
- **Completed:** see `reports/figures/velocity_comparison.png` and `burndown_sprint1.png` (generated from `docs/sprint_log.csv`).

## What went well / Continue
- TDD cycle on every module (`test:` → `feat:`), with all tests passing before opening the PR.
- Pull Request template with the DoD checklist and peer review on every change.
- Exposure-based prioritization gave an objective order for the backlog (COP 77,000M net exposure, no double counting).
- Data-quality gate found the churn gap (12% missing `tenure_months`) instead of hiding it.

## What did not work / Stop
- Waiting for an external sponsor signature to close stories: in the Cut 1 simulation, 3 of 4 stories stayed blocked. Fixed by recording sponsor feedback in the Sprint Review minutes (DoD Option B).
- Over-committing: the initial Sprint 1 load was 21 SP against a ~9 SP average. Re-estimated to 15 SP (US-01 from 5 to 2 SP, US-03 split in two parts).
- Merging a PR with conflicts into `main` (PR #2 was merged and then reverted).
- Keeping the CI workflow inside a subfolder, which stopped GitHub Actions from running until it was moved to the repository root.

## What to try / Start
- Fill the Daily Scrum log for every team member, every day.
- Update `docs/sprint_log.csv` the same day a story closes, so Velocity and Burndown are not zero.
- Capture pairing evidence (commit hash or screenshot) at the end of each session.
- Rebase on `main` before opening a PR to avoid conflicts.

## Action items
| Action | Owner | Due |
| :--- | :--- | :--- |
| Keep `sprint_log.csv` updated when a card moves to Done | Marco Jimenez | Sprint 2 |
| Log pairing evidence after each session | Whole team | Sprint 2 |
| Rebase on `main` before every PR | Whole team | Sprint 2 |
