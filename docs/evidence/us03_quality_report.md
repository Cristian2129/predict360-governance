# US-03 P1 — Data Quality Audit

Author: Paula Gacha | FinBank Predict360

Proposed thresholds: 0% missing in critical fields; 5% in other fields; 0 invalid types; 0 risk scores outside [0, 1].

| Source | Rows | Status | Issues |
| --- | ---: | :---: | ---: |
| backlog | 11 | PASS | 0 |
| delinquency | 500 | PASS | 0 |
| churn | 200 | FAIL | 1 |

## backlog: PASS

- No threshold violations detected.

## delinquency: PASS

- No threshold violations detected.

## churn: FAIL

- Missing `tenure_months`: 24/200 (12.00%, limit 5.0%).
- Issue: tenure_months: 12.00% missing (limit 5.0%)

## Interpretation

A FAIL in churn is an expected business finding when 12% of tenure_months are empty; do not edit or hide the synthetic data. The Python tests can pass while the data-quality gate reports FAIL.
