# US-03 P1 — Source Inventory and Quality Thresholds

Author: Paula Gacha — PCM Analytics | Sprint 1 | 5 story points

## 1. Source inventory

These files are **synthetic** and generated with `python src/predict360/make_synthetic.py`; they are not real bank records. Expected counts come from the generator code.

| File / source | Expected rows | Goal | Key columns | Owner / related story |
| --- | ---: | --- | --- | --- |
| `data/synthetic/backlog.csv` | 11 | Prioritize project work by exposure and story points | `story_id`, `title`, `domain`, `exposure_type`, `exposure_cop_m`, `sp`, `sprint` | US-02 / governance |
| `data/synthetic/delinquency_sample.csv` | 500 | EarlyRisk sample to verify delinquency indicators and exposure | `client_hash_id`, `days_past_due`, `risk_score`, `client_balance_cop_m`, `client_exposure_cop_m`, `sampling_weight`, `exposure_cop_m` | US-04 / delinquency |
| `data/synthetic/churn_sample.csv` | 200 | StayBank sample to verify tenure and churn probability | `client_hash_id`, `tenure_months`, `churn_probability`, `client_exposure_cop_m`, `sampling_weight`, `exposure_cop_m` | US-03 / churn |

**Important:** `exposure_cop_m` is **already expanded** for the sample; do not multiply it by `sampling_weight` again.

## 2. Proposed quality thresholds (requires team acceptance)

| Quality rule | Threshold | Why |
| --- | --- | --- |
| Missing values in critical columns (`client_hash_id`, `story_id`, `risk_score`, `churn_probability`, `exposure_cop_m`) | 0% | Identification and risk/exposure measures are essential |
| Missing values in other fields, including `tenure_months` | At most 5% | Allows limited missingness but exposes meaningful gaps |
| `risk_score` and `churn_probability` | Inclusive range 0 to 1 | Probability/risk score scale |
| Wrong data types | 0 invalid values | Strings must not replace numeric or integer measurements |
| Required columns absent | 0 missing columns | A necessary input cannot be silently ignored |
| Empty data source | 0 empty files accepted | An empty source cannot be audited usefully |

These are **proposed project rules**, not pre-existing requirements verified in the Canva page. If the professor or product owner specifies a different tolerance, update the threshold and the test together through review.

## 3. Detected issue / expected result

The synthetic churn generator creates **24 missing `tenure_months` values out of 200**, equal to **12%**. With the agreed proposed maximum of 5%, churn **FAILS**. This is precisely the problem the module should identify. The tool does **not** impute or delete rows.

Expected baseline: backlog **PASS**, delinquency **PASS**, churn **FAIL**. A quality-gate failure is compatible with all `pytest` tests passing.

## 4. Reporting and next action

Execute `python -m src.predict360.quality` to create `docs/evidence/us03_quality_report.md`. Record the 12% gap, its possible impact on StayBank, and recommend validation of the source and an agreed treatment strategy before modeling. Keep the original synthetic data unchanged.
