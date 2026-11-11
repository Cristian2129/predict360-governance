# Technical Specification: FinBank Predict360 Evidence System

PCM Analytics · Version of 2026-11-10

## 1. Purpose, scope and guiding principle

This document specifies the evidence system that PCM Analytics delivers to FinBank to plan, prepare, evaluate and audit delinquency and churn predictions. The system does not train a model.

**What FinBank asked for (client brief)**

> At FinBank S.A. we manage a COP 420,000M portfolio and 125,000 clients, but we lack the planning and methodology to structure and implement predictive analytics projects:
>
> 1. No early delinquency prediction: we do not predict which new clients will fall into arrears (COP 58,800M at risk for lack of predictive alerts at 30/60 days).
> 2. No churn prediction: we do not anticipate which preferred clients will cancel their loans (COP 18,200M in losses for not predicting attrition three months in advance).
>
> We are looking for a consulting firm to organize the project-management planning of a 12-week predictive analytics initiative (governance, scope, a COP 180,000,000 budget and an agile modeling board). We require an executive Project Charter, an agile work plan and a 5-minute pitch.

**How we respond.** FinBank is not asking for a model. It is asking for the planning and the methodology to implement one. So we deliver what is missing before any model exists, plus the way to check whether a model is worth using.

| FinBank problem | What we deliver | What remains with FinBank |
| --- | --- | --- |
| Early delinquency (COP 58,800M, 30/60-day alerts) | Problem specification, data contracts, evaluator in COP, reconciliation against 58,800M | Train the model on its real data and run preventive collections |
| Preferred-client churn (COP 18,200M, 3 months ahead) | Problem specification, data contracts, evaluator in COP, reconciliation against 18,200M | Train the model and run the retention offer |

**Guiding principle.** Real data never leaves the bank; the system travels. We test it with synthetic data, and FinBank runs it on its own data by changing only the configuration file (`synthetic.yaml` to `real.yaml`).

The team approved this principle on November 10. **How it is enforced:** the pipeline runs inside FinBank with `config/real.yaml`, the pseudonymization key (HMAC) belongs to FinBank, and only aggregates leave the bank (manifest, model card, metrics and `dashboard_data.json`), never client-level rows. **How it is tested without real data:** the synthetic data reproduces the client's figures (58,800M and 18,200M) and the reconciliation step checks them on every run. Two alternatives were rejected because both break the principle: taking a pseudonymized sample out of the bank so that we train the model, and using a remote data store (DVC-style).

**What we do not deliver.** A trained model, loss estimates (58,800M and 18,200M are exposure at risk, not loss), live deployment or production monitoring (out of scope per the Charter), or a legal opinion on Ley 1581.

## 2. Problem specification: early delinquency

The delinquency problem is to predict, at a cut-off date T, which active loans will become delinquent within the next 30 or 60 days, so that Collections can contact them first. Values marked as assumptions are set by the team and justified in section 12.

| Element | Definition |
| --- | --- |
| Unit of analysis | One active loan per client (pseudonymized `client_id`). If a client has several loans, the contract defines how they are aggregated |
| Cut-off date T | Set per run in the configuration. Everything used for prediction is dated T or earlier |
| Cohort | Loans active at T and not in arrears at T. Loans cancelled or written off before T are excluded |
| Delinquency event | The loan reaches at least `dpd_min` days past due. Assumption: `dpd_min` = 30 days |
| Alert horizons | H = 30 days and H = 60 days: the lead time with which we want to warn |
| Label | `delinquency_30` (or `delinquency_60`) = 1 if the first event date falls in (T, T + H]; otherwise 0 |
| Label maturity | A row is labeled only if observation reaches at least T + H. Other rows are excluded and counted in the funnel |
| History window | Features computed from the 12 months before T (assumption) |
| Model output | Probability between 0 and 1 per loan and horizon |

**Anti-leakage rules**

- No feature may use information after T, including collection actions taken after T.
- The train/evaluation split is by time, never random.
- Imputation, scaling and feature selection are fitted on the training period only.

**Intervention.** An alert turns into a preventive call. If the call prevents delinquency, the label stays at 0 and the model appears to have failed. So every contacted client is recorded (`intervened`, date and type), and a random control group is left uncontacted (assumption: 5% of alerted clients) to measure real effectiveness.

**Candidate predictors** (FinBank confirms the source and availability of each)

| Group | Examples |
| --- | --- |
| Payment behavior | Prior arrears, maximum days past due in 12 months, partial payments |
| Credit usage | Line utilization, balance, exposure in COP |
| Relationship with the bank | Client and loan tenure, remaining term, active products |
| Repayment capacity | Income or available proxy, installment-to-income ratio |

**Operational alert** (assumptions): weekly frequency; target population = the K loans with the highest score (K = weekly capacity of the Collections team); the owner of the intervention at FinBank is to be defined.

## 3. Problem specification: preferred-client churn

The churn problem is to predict, at a cut-off date T, which preferred clients will cancel their loan in the next 3 months, so that retention can be offered in time. Values marked as assumptions are set by the team and justified in section 12.

| Element | Definition |
| --- | --- |
| Unit of analysis | One preferred client with an active loan (pseudonymized `client_id`) |
| Preferred segment | Top 10% of clients by exposure (12,500 clients). Configurable |
| Cut-off date T | Set per run. Everything used for prediction is dated T or earlier |
| Churn event | Voluntary early cancellation of the loan (`cancellation_date`). Assumption: natural loan maturity does not count as churn |
| Horizon | 90 days after T, the 3-month lead time FinBank asked for |
| Label | `churn_3m` = 1 if `cancellation_date` falls in (T, T + 90 days]; otherwise 0 |
| Label maturity | A row is labeled only if observation reaches at least T + 90 days. Other rows are excluded and counted |
| Exclusions | Clients already cancelled before T, and loans maturing within the horizon |
| Model output | Probability between 0 and 1 per client |

**Anti-leakage rules.** Same as for delinquency: features up to T, time-based split, transformations fitted on training only.

**Intervention.** A retention offer changes client behavior. If the offer works, the client does not cancel and the model appears to have failed. `intervened` is recorded with offer type and date, and a no-offer control group is kept (assumption: 5%). The offer success rate used by the simulator must come from that control group.

**Candidate predictors** (FinBank confirms the source and availability of each)

| Group | Examples |
| --- | --- |
| Relationship with the bank | Tenure, active products, changes in usage |
| Loan terms | Rate versus current market rate, extraordinary prepayments, remaining term |
| Service | Recent claims, complaints or contacts |
| Value | Exposure in COP, balance and its trend |

**Operational offer** (assumptions): retention is offered 3 months before the likely cancellation date, with a retention budget and a cap on offers per period set by FinBank. The owner of the offer is the retention manager.

**Known data issue.** In the synthetic churn data, 12% of `tenure_months` is missing against a 5% threshold. It is kept on purpose (risk R-01): it is not imputed, it is flagged with an indicator and evaluated as its own slice.

## 4. Bridge between ML metrics and business metrics

A model is judged in two steps: first, how much exposure in COP its ranking captures in the top K; then, how much net value it leaves under assumptions provided by FinBank. The first part is measured with data; the second requires explicit assumptions.

**Chain of reasoning:** business metric ← effectiveness of the action ← exposure captured in the top K ← ranking quality (PR-AUC, lift, precision and recall@K, calibration).

**Formulas.** Let y be the event (1 or 0), E the exposure in COP, K the number of clients contacted, e the effectiveness of the action, c the cost per contact and l the share of exposure lost if the event occurs (assumption: 1).

```latex
\text{capture}(K) = \frac{\sum_{i \in \text{top-}K} E_i \, y_i}{\sum_{i} E_i \, y_i}
```

```latex
\text{net value}(K) = e \cdot l \cdot \sum_{i \in \text{top-}K} E_i \, y_i \; - \; c \cdot K
```

```latex
K^{*} = \arg\max_{K} \; \text{net value}(K)
```

K* is the break-even point: the cut-off beyond which calling one more client costs more than it recovers.

**Test case (exact figures).** 1,000 clients, K = 100, 50 events of 10M each (500M in total), 40% effectiveness, COP 20,000 per call and l = 1.

| Strategy | Exposure capture | Exposure captured | Net value |
| --- | --- | --- | --- |
| Random | 10% | 50M | 18M |
| Simple rule | 30% | 150M | 58M |
| Model | 60% | 300M | 118M |

The model's net value is 0.40 × 300M − 100 × 20,000 = 118M. This case is the evaluator's unit test.

**Translation by objective**

| Business objective | Decision | Business metric | Model metric | What FinBank provides |
| --- | --- | --- | --- | --- |
| Reduce early delinquency (COP 58,800M) | Preventive collections for K clients per week | Net loss avoided | Top-K capture, lift, PR-AUC | Contact effectiveness, cost per call, capacity K |
| Retain preferred clients (COP 18,200M) | Retention offer 3 months ahead | Net value protected | Top-K capture, precision, PR-AUC | Offer success rate and cost, budget |

**Dashboard stress parameters:** weekly capacity K, action budget cap, effectiveness, cost per contact and false-positive penalty (the cost of bothering a client who was not going to default or cancel). Effectiveness must come from the control group described in sections 2 and 3.

**Caveat.** 58,800M and 18,200M are exposure at risk, not loss. Net value is an estimate conditional on the assumptions and is always shown next to them.

## 5. Data and lineage standard

Every reported figure must be traceable to a file, a contract version, a commit and a hash, and personal data is handled with the minimum necessary. This section defines how.

**Data zones**

| Zone | Contents | Rule |
| --- | --- | --- |
| Source | FinBank systems | Outside the scope of our code |
| RAW | Exact copy of the extract, with its `sha256` | Read-only: the system refuses to overwrite |
| CURATED | Validated, typed, de-duplicated and pseudonymized data | Contract columns only (minimization) |
| LABELED | Table with labels computed per the specification | Mature, in-cohort rows only |
| SCORES | Model predictions in long format | Joined to the labeled table on `client_id` |
| OUTPUTS | Evaluation, evidence record, manifest and dashboard data | Each file references its manifest |

**Personal data handling**

| Topic | Rule |
| --- | --- |
| Pseudonymization | `client_id` = HMAC-SHA256 with a key held by FinBank (environment variable, never in the repository). The original identifier never leaves the bank |
| Minimization | Columns not in the contract are dropped |
| Retention | RAW is kept for a period set by FinBank (`retention_days` parameter); everything else can be regenerated |
| Access | Three roles: data owner (FinBank), analyst and auditor. The auditor reads outputs and manifests only |
| Data subject rights | A record can be located and deleted through the pseudonymized identifier; the lookup table exists only inside the bank |
| Legal framework | Ley 1581 de 2012 (Habeas Data) and Ley 1266 de 2008. A gap report (G01 to G07) is delivered, not a legal opinion |

**Lineage manifest per run.** Written to `runs/<run_id>/manifest.json` and appended to `lineage_log.jsonl`, an append-only log.

```json
{
  "run_id": "20261112T1530-a1b2c3",
  "config": "synthetic.yaml",
  "commit": "<git sha>",
  "snapshot_date": "2026-03-31",
  "sources": [{"name": "delinquency", "file": "raw/delinquency.csv", "sha256": "...", "rows": 500}],
  "contract_versions": {"delinquency": "v1", "churn": "v1", "scores": "v1", "model_card": "v1"},
  "gates": {"gate1": "PASS", "gate2": "PASS", "gate3": "PASS"},
  "waivers": [],
  "scores_sha256": "...",
  "parameters": {"horizons": [30, 60, 90], "seed": 42}
}
```

**Scope of the hash.** `sha256` proves that a file did not change, but it does not keep earlier versions of the data. We do not use a DVC-style remote store because it contradicts the principle that data does not leave the bank. This limit is stated explicitly.

## 6. Data contracts

A contract fixes the columns, types and rules of each table entering the system, and Gate 1 enforces it. Names are a proposal and are aligned with the repository's current CSV files before publishing.

**delinquency_v1 (loans active at T)**

| Column | Type | Rule |
| --- | --- | --- |
| `client_id` | text (hash) | Required, unique |
| `snapshot_date` | date | Required. Cut-off date T |
| `exposure_cop_m` | decimal | Required, greater than 0 |
| `weight` | decimal | Required, greater than 0. Number of clients the row represents |
| `origination_date` | date | Required, before T |
| `utilization` | decimal | Between 0 and 1.5 |
| `prior_late_12m` | integer | Greater than or equal to 0 |
| `max_dpd_12m` | integer | Greater than or equal to 0 |
| `tenure_months` | integer | Up to 5% nulls |
| `first_delinquency_date` | date | May be empty; if present, after T |
| `observation_end_date` | date | Required, after T |

**churn_v1 (preferred clients active at T)**

| Column | Type | Rule |
| --- | --- | --- |
| `client_id` | text (hash) | Required, unique |
| `snapshot_date` | date | Required. Cut-off date T |
| `exposure_cop_m` | decimal | Required, greater than 0 |
| `weight` | decimal | Required, greater than 0 |
| `tenure_months` | integer | Up to 5% nulls |
| `products_active` | integer | Greater than or equal to 1 |
| `cancellation_date` | date | May be empty; if present, after T |
| `observation_end_date` | date | Required, after T |

**scores_v1 (predictions in long format, one row per client and model)**

| Column | Type | Rule |
| --- | --- | --- |
| `client_id` | text (hash) | Must exist in the labeled table |
| `model_id` | text | Must exist in an admitted model card |
| `snapshot_date` | date | Equal to the run's cut-off date |
| `horizon_days` | integer | 30, 60 or 90 |
| `score` | decimal | Between 0 and 1, no nulls |
| `intervened` | 0 or 1 | Optional. Flags whether the client was contacted |

Long format makes it possible to evaluate any number of models without changing the contract.

**model_card_v1 (model card, JSON)**

| Field | Contents |
| --- | --- |
| `model_id`, `created_at`, `run_by`, `target` | Identity: who, when, and whether it targets delinquency or churn |
| `spec_version` | Version of the problem specification |
| `dataset_hash`, `snapshot_date` | Hash of the scores table and cut-off date |
| `train_end_date`, `eval_start_date` | End of training and start of evaluation |
| `preprocessing_fit_on` | Declaration that transformations were fitted on training data only |
| `commit`, `libs`, `seed` | Code and environment |
| `algorithm`, `hyperparameters`, `features` | Which model it is and which features it uses |
| `ranking_policy` | How it ranks (for example, by probability or by probability × exposure) |
| `baselines_compared` | Baselines it was evaluated against |
| `intervention_handling` | How intervened clients were treated |
| `status` | candidate, shadow, pilot, approved or retired |
| `approved_by` | Who approved the last status change |

## 7. `make_synthetic` v2

Version 2 keeps the figures that already reconcile and adds dates, events, a risk signal and scores, so that there is something to predict and something to evaluate. The scores are simulated, not trained models, and are declared as such.

**Kept**

- Seed 42 and reproducible generation.
- Delinquency: 500 rows with weight 250 (125,000 clients) summing to 58,800M of exposure.
- Churn: 200 rows with weight 62.5 summing to 18,200M of exposure.
- 12% of `tenure_months` missing in churn, on purpose (risk R-01).

**Added**

| Element | How it is generated |
| --- | --- |
| `client_id` | Raw identifier → HMAC-SHA256 with an environment key. The raw identifier is never written to disk |
| Dates | `snapshot_date` (T), `origination_date` and `observation_end_date`, with parameters in `config/synthetic.yaml` |
| Exposure | Heavy-tailed distribution (many small loans, few large ones), rescaled so the sum is exactly 58,800M and 18,200M |
| Latent risk | Hidden variable computed from `utilization`, `prior_late_12m`, `tenure_months` and noise |
| Event | Drawn with probability equal to the sigmoid of the latent risk. The base rate is calibrated with a parameter. The event date falls within the observation window |
| Immature rows | A small share with `observation_end_date` earlier than T + H, to check that labeling excludes them |
| Preferred segment | The churn population is the top 10% of clients by exposure (configurable) |
| Scores | Three simulated models in long format (see below) |

**Simulated scores**

| `model_id` | How it is built | What it should show |
| --- | --- | --- |
| `baseline_rule` | Simple rule on a single observable variable (for example, prior arrears) plus noise | The baseline |
| `model_a` | Probability from the latent risk plus noise. Ranks by probability | Higher recall in number of clients |
| `model_b` | Probability multiplied by exposure, normalized to [0, 1]. Ranks by expected loss | Higher exposure captured in COP |

The difference between A and B comes from the ranking criterion and is not forced. Whatever figures result are the ones reported, and the generator is open for inspection. A noise parameter keeps the scores from being an oracle of the event.

**Defective files for demos** (`--defect <type>`)

| Type | What it breaks | Rule that catches it |
| --- | --- | --- |
| `critical_nulls` | Nulls in a required column | Gate 1: not null |
| `schema` | A missing column or a changed type | Gate 1: schema |
| `duplicate_ids` | Two rows with the same `client_id` | Gate 1: uniqueness |
| `score_out_of_range` | A score above 1 or negative | Gate 1 on `scores_v1` |
| `exposure_mismatch` | The sum drifts away from 58,800M | Reconciliation |
| `overlapping_split` | `train_end_date` after `eval_start_date` in the model card | Model card admission |

**Tests for make_synthetic.** The same seed produces the same files; exposure sums reconcile within 0.01M; `tenure_months` missingness is 12%; immature rows exist and are excluded; base rates stay within the parameter ranges; no raw identifier appears in the files.

## 8. Pipeline, station by station

A single command, `run_pipeline.py --config config/synthetic.yaml`, runs twelve stations and writes everything to `runs/<run_id>/`; with `real.yaml` it runs the same way inside the bank. There are three gates: Gate 1 (data), Gate 2 (model card admission) and Gate 3 (consistency).

The run moves through the stations in order; the gates at stations 2, 7 and 11 stop the run or reject the model if a condition is not met.

| # | Station | Input | What it does | Output | Tests |
| --- | --- | --- | --- | --- | --- |
| 1 | Ingest (RAW) | Source files | Copies to a read-only zone, computes `sha256`, records date and version | `raw/`, manifest entry | Does not overwrite; hash matches |
| 2 | Validate (Gate 1) | RAW and contracts | Applies rules in Expectations-style naming: schema, nulls, uniqueness, ranges, date logic | `gate1_report.json` | Every defective file type is rejected |
| 3 | Curate | Validated RAW | Types columns, removes duplicates, pseudonymizes, drops columns outside the contract, flags missing values without imputing | `curated/` | No raw ID remains; missing values flagged |
| 4 | Label | CURATED and specification | `labeling.py` computes `delinquency_30`, `delinquency_60`, `churn_3m` and drops immature rows | Labeled table, funnel and base rates | A label never uses data after its window |
| 5 | Features (specification only) | FinBank feature table | `check_point_in_time` rejects features dated after T | Guard report | Rejects a future-dated feature |
| 6 | Score intake | `scores_v1` | Validates against the labeled table and computes the `sha256` of the scores | Hash in the manifest | Unknown IDs or out-of-range scores fail |
| 7 | Model card admission (Gate 2) | Model card JSON | Validates contract, hash and temporal split; checks status | `admission.json` with ADMITTED or REJECTED and reasons | Cards with missing fields, a different hash or overlapping dates are rejected |
| 8 | Evaluate | Admitted scores | Metrics, baselines, slices, COP capture curve, net value and K* | `evaluation.json` | Exact 118M case |
| 9 | Reconcile | CURATED | Compares exposure with 58,800M and 18,200M, tolerance 0.01M | `reconciliation.json` | Passes on clean data and fails with `exposure_mismatch` |
| 10 | Project management | `sprint_log`, hours, 180M baseline | PV, EV, AC, SPI, CPI and EAC; flags estimated hours | `management.json` | Cases with hand-computed values |
| 11 | Consistency (Gate 3) | Figures cited in reports | Fails if any figure differs from the computed one | `consistency.json` | An altered figure makes it fail |
| 12 | Evidence record and export | All of the above | Closes the manifest, writes the evidence record and `dashboard_data.json` | `evidence_record.json`, `dashboard_data.json` | The file meets its contract |

**Gate rule.** A broken critical column in Gate 1 stops the run. A non-critical finding, such as the 12% of `tenure_months` missing in churn, continues only with a written waiver recorded in the manifest (`waivers`).

## 9. Model admission and standard evaluator

A model enters evaluation only if its model card meets the admission rules, and it moves to the next status only with the matching evidence. The evaluator measures every admitted model with the same criteria.

**Admission rules (Gate 2)**

| Rule | What is checked | Result if it fails |
| --- | --- | --- |
| Complete card | All `model_card_v1` fields present and valid | REJECTED: incomplete card |
| Traceability | `dataset_hash` equals the scores hash in the manifest | REJECTED: not traceable |
| Temporal split | `train_end_date` before `eval_start_date` | REJECTED: non-temporal split |
| Transformations | `preprocessing_fit_on` declares training only | REJECTED: possible leakage |
| Intervention | `intervention_handling` declared | WARNING recorded |
| Baselines | `baselines_compared` includes random and a heuristic rule | WARNING recorded |

The last two rules become rejections if FinBank configures them that way. The split and the transformations are declared in the card: the system checks the dates, but it cannot prove by itself how an external model was fitted.

**Model card statuses and evidence to advance**

| Status | Meaning | Evidence to move to the next one |
| --- | --- | --- |
| `candidate` | Card admitted and evaluated offline | Beats the baselines per the configured threshold |
| `shadow` | Scores the live flow without triggering actions | Shadow-period report: volume, alert consistency against the current rule, and score stability |
| `pilot` | Limited actions, with a control group | Effectiveness measured against the control |
| `approved` | Authorized by the FinBank committee | Signed decision |
| `retired` | Out of use | Reason recorded |

The dashboard decision never says "goes to production": at most it says "authorized for shadow deployment". Live deployment is outside the Charter's scope, so shadow, pilot and approval are criteria and a plan for FinBank, not tools we deliver.

**Standard evaluator (`evaluator.py`)**

| Block | What it computes |
| --- | --- |
| Ranking metrics | PR-AUC, lift, precision and recall at K, over a grid of K values |
| Calibration | Brier score and a table by probability decile |
| Business | Exposure captured in COP, cumulative capture curve, net value and K* using the assumptions in `config/assumptions.yaml` |
| Baselines | Random (expected capture equal to K%), heuristic rule and, if FinBank provides one, a simple linear model |
| Slices | The same metrics by exposure (quartiles), tenure, and the group with missing `tenure_months`. Each slice shows its n and a bootstrap confidence interval; slices below the global value are flagged. No slice with fewer than 30 clients is published |
| Promotion rule | A model beats the baseline only if its net value in COP is higher at the chosen K by a configurable margin and the intervals do not overlap |
| Stress | Recomputes net value when moving capacity, budget, effectiveness, cost and false-positive penalty |
| Intervened clients | Option to exclude or compare separately the clients with `intervened` = 1 |

**Key test.** The exact case from section 4 (1,000 clients, K = 100) must yield 18M, 58M and 118M. A perfect model must capture 100% and a random one must land close to K%.

## 10. Good-practice controls and scope limits

Six typical risks of ML systems in production, taken from Huyen (2022), have a control in this design; four are implemented in code and two remain as a plan. The reference is used as a good-practice framework, not as a standard FinBank must comply with.

| Risk | What happens | Control in our design | Where |
| --- | --- | --- | --- |
| Delayed labels | 30/60-day delinquency and 3-month churn take time to confirm, so accuracy cannot be measured in real time | Label maturity in labeling. Monitoring through proxy indicators (input validation and score distribution stability with KS or quantiles) remains a plan | Sections 2, 3 and 8. Plan in the roadmap (US-09) |
| Data leakage | A model looks perfect in validation and fails in production | Temporal split required in the card, point-in-time guard on features, transformations fitted on training only | Stations 5 and 7 |
| Aggregate evaluation hides failures | A good average can hide a badly served group (Simpson's paradox) | Slice metrics with n and intervals | Station 8 |
| No baselines | A complex model is not justified if it does not beat what already exists | Random, heuristic rule and optional linear model, with a promotion rule | Station 8 |
| Intervention contaminates labels | If the call prevents delinquency, the model appears to have failed | `intervened` column, control group and effectiveness measured against it | Sections 2, 3 and 6 |
| Going straight to production | A model can behave differently on real data | `shadow` status as a mandatory gate before `pilot` and `approved` | Section 9. Criteria for FinBank |

**Scope limits (Charter, risk R-03).** The trained model, integration with banking systems, live deployment and production monitoring are outside the engagement. That is why shadow mode and score stability are delivered as criteria and a plan, and a demonstration stability function is implemented in code only if time allows.

**Reference.** Huyen, C. (2022). *Designing machine learning systems*. O'Reilly Media.

## 11. Committee web dashboard

The dashboard is a static page, with no server, that reads `dashboard_data.json` and presents the system as a committee console: it supports the guided walkthrough for FinBank's risk committee and is the product FinBank keeps for day-to-day review.

**Two modes**

| Mode | Audience | How it is used |
| --- | --- | --- |
| Guided | Steering or risk committee session | A 6-step walkthrough, one click per step; it is the demo itself |
| Explore | FinBank analysts after handover | Free tabs, adjustable controls and the management view |

**Views and the data behind them**

| View | What it shows | Section of `dashboard_data.json` |
| --- | --- | --- |
| Summary | Delinquency and churn exposure, reconciliation, status of the three gates, last run | `meta`, `exposure`, `gates` |
| Data and lineage | Missing values per column, failed rules, run manifest | `quality`, `lineage` |
| Models | Model cards and statuses, comparison with baselines, slices, COP capture curve | `models` |
| Stress | Simulator with capacity, budget, effectiveness, cost, false-positive penalty and K* | `models`, `assumptions` |
| Management | Burndown, velocity, earned value, SPI, CPI, EAC and risks | `management` |
| Handover to FinBank | Runbook checklist to move from synthetic to real data | `handover` |

**Distinctive features**

1. **Trace this figure.** One click on any number opens its lineage: source file, script that computed it, commit and hash.
2. **Decision and stress simulator.** Moves the assumptions and recomputes net value in COP and K*.
3. **Exposure capture curve in COP.** Compares the baseline rule with the demo models.
4. **Visible admission.** An invalid model card shows as rejected, with its reason.
5. **Committee decision.** Generates the evidence record, with "authorized for shadow deployment" as the strongest possible verdict.
6. **Break the data** (optional). Injects a defective file and shows which rule failed and how the gate turns red.
7. **Permanent synthetic-data banner** and a data-source selector.

**Guided mode in 6 steps**

1. Run the pipeline with one command and refresh the dashboard.
2. Break the data and watch Gate 1 reject it.
3. Trace the 58,800M back to its source.
4. Compare models, review slices and see a card without traceability rejected.
5. Move the simulator and watch net value and K*.
6. Management view, evidence record and the consistency gate.

**`dashboard_data.json` contract**

| Key | Contents |
| --- | --- |
| `meta` | `run_id`, date, `commit`, `synthetic` (true or false), contract versions |
| `exposure` | Delinquency and churn exposure, expected and observed, and the reconciliation result |
| `gates` | Status of each gate with its list of rules and their results |
| `quality` | Missing values per column against their threshold |
| `lineage` | Run manifest and the origin of each figure (`figure_id`, file, script, commit, hash) |
| `models` | Cards, metrics, capture curve, slices and status of each model |
| `assumptions` | Effectiveness, cost, capacity, budget, penalty and loss share l, each with its type |
| `management` | Burndown, velocity, PV, EV, AC, SPI, CPI, EAC and risks |
| `handover` | Runbook steps and their status |

Only aggregates go into this file, never client-level rows.

**Definition of Done for the dashboard.** Reads the pipeline file with no hand-typed figures; shows the synthetic-data banner; every figure has its trace; opens from a local file without network access and from its link; renders well on a projector and on a phone; the generator and the contract tests are in the repository.

**Priority.** Mandatory: guided mode, figure tracing, simulator and capture curve. First to be cut: break the data and the handover view.

## 12. Tests, code by file and roadmap

The build is about 41 hours of work split among the three team members until the code freeze on Saturday, November 14, and every piece lands with its tests green.

**Tests and CI.** Everything runs with pytest on GitHub Actions (Python 3.13). Beyond the module tests in sections 7 to 9, CI runs `run_pipeline.py` with `synthetic.yaml` and checks that `dashboard_data.json` meets its contract. The clean-clone test on Monday, November 16 is done by someone other than the author of the code.

**Code by file**

| File | What it does | Status | Owner | Hours |
| --- | --- | --- | --- | --- |
| `config/*.yaml` and contracts | Parameters and the four contracts | New | Cristian | 2 |
| `make_synthetic.py` | Dates, events, latent risk, scores and defective files | Modified | Cristian | 3 |
| `run_pipeline.py` and `export_dashboard_data.py` | Orchestrates the stations and writes the dashboard data | New | Cristian | 3 |
| `dashboard/` | The dashboard page | New | Cristian (Models tab: Paula; Management tab: Marco) | 8 + 2 |
| `labeling.py` | Window labels, maturity and anti-leakage guard | New | Paula | 3 |
| `model_card.py` | Card admission, temporal split and statuses | New | Paula | 2 |
| `evaluator.py` | Metrics, baselines, slices, COP capture, net value and K* | New | Paula (slices with Marco) | 8.5 |
| `quality.py` | Expectations-style rules for Gate 1 | Modified | Marco | 2 |
| `lineage.py` | Manifest and append-only log | New | Marco | 2 |
| `reconcile.py` | Adds churn reconciliation | Modified | Marco | 1 |
| `budget_schedule.py` | PV, EV, AC, SPI, CPI and EAC | New | Marco | 3 |
| `consistency.py` | Gate 3 | New | Marco | 2 |

In addition, Paula writes the specification for sections 2 and 3, and Marco records each person's actual hours. `exposure.py`, `sprint_metrics.py` and `risk_register.py` stay as they are.

**Roadmap**

| Date | Work | Owners |
| --- | --- | --- |
| Tue, Nov 10 | Contracts and configuration, `make_synthetic` v2, specification and `labeling.py`, hour log, `budget_schedule.py` and `quality.py` | Cristian, Paula, Marco |
| Wed, Nov 11 | `model_card.py` and `evaluator.py`, `run_pipeline.py` and export, `lineage.py`, `reconcile.py` and `consistency.py` | Paula, Cristian, Marco |
| Thu, Nov 12 | Dashboard connected to real outputs; Sprint Review, retrospective, `sprint_log`, burndown and budget with actual hours. Sprint 3 closes | Cristian, Marco |
| Fri, Nov 13 | Handover runbook and guided-mode script; dry run | All three |
| Sat, Nov 14 | Code freeze: critical fixes only | All |
| Mon, Nov 16 | Cross-check of figures, clean-clone test and dashboard check on projector, phone and offline | Marco and Paula |
| Tue, Nov 17 | Backup recording of the guided walkthrough | All |

**Cut lines** (what goes first if time runs short)

1. The break-the-data button and the handover view.
2. Slices and the score stability function.
3. Treatment of intervened clients in the evaluator (the column stays in the contract), the second demo model and churn reconciliation.
4. Automatic baselines: only the baseline rule remains.
5. Never cut: model card with temporal split and statuses, Gate 1, delinquency reconciliation, evaluator with COP capture, figure tracing, Gate 3, and the Sprint 3 close with agile metrics, budget and retrospective.

**Integration with FinBank's models**

The system does not sit inside the model; it sits around it, as the referee. FinBank trains with its own tools (Python, R, SAS) and connects with us through files.

1. FinBank runs `run_pipeline.py --config config/real.yaml` on its extract. The output is the labeled table: pseudonymized client, cut-off date T, `delinquency_30`, `delinquency_60`, `churn_3m`, `intervened` and the temporal split.
2. In its own environment, FinBank joins its features (all dated up to T), trains on the training split and scores the evaluation split.
3. It exports the scores table in `scores_v1` format and the model card in `model_card_v1` format.
4. The pipeline admits or rejects the card (Gate 2), evaluates against the baselines, computes capture in COP and issues the decision.

Feature engineering and training belong to FinBank. The weak point is the exchange format, because it is tested only with the simulated scores from `make_synthetic`; that is why the runbook includes a short example of exporting to `scores_v1`. There is no connection to production systems (out of scope, R-03).

**Project assumptions**

The team sets the assumptions and justifies each one. There are three types: business (validated by the FinBank sponsor before real use), design (proposed by PCM Analytics) and simulation (used only for the example and declared illustrative). All of them live in `config/assumptions.yaml`, not in the code: changing them does not change the system. The dashboard shows them next to every COP figure, and the simulator lets users move them.

| # | Assumption | Value set | Type | Rationale |
| --- | --- | --- | --- | --- |
| 1 | Days past due that count as delinquency | 30 or more | Business | First delinquency bucket; an early warning makes sense before 60 or 90 days |
| 2 | Delinquency alert horizons | 30 and 60 days | Business | Stated verbatim in the client brief |
| 3 | Churn definition | Voluntary early cancellation within 90 days; natural maturity does not count | Business | The client asks for 3 months' lead time; a maturity is not a decision that can be retained |
| 4 | Preferred segment | Top 10% of clients by exposure (12,500 clients) | Business | Matches the synthetic churn data (200 rows × 62.5). Tenure is not usable as the criterion because 12% of `tenure_months` is missing |
| 5 | Feature history window | 12 months | Design | Covers a full annual cycle and its seasonality |
| 6 | No-intervention control group | 5%, random | Design | Measures the effect of the action without leaving many clients unmanaged |
| 7 | Share of exposure lost if the event occurs | 1 | Simulation | Upper-bound scenario; 58,800M and 18,200M are exposure, not loss. The simulator allows lowering it |
| 8 | Alert frequency and capacity K | Weekly; default K = 10% of evaluated clients | Design | Collections working rhythm; K moves in the simulator and K* comes from the calculation |
| 9 | Action effectiveness and cost per contact | 40% and COP 20,000 | Simulation | Test-case values with no source; declared illustrative |
| 10 | Reconciliation tolerance | COP 0.01M | Design | Rounding of the published figure; already used in `reconcile.py` |
| 11 | Condition to beat the baseline | Higher net value than the baseline rule at the chosen K | Design | The criterion is measured in COP, not only in classification metrics |
| 12 | RAW retention period | Empty parameter in `config/real.yaml` | Business | Depends on FinBank's data policy (Ley 1581); we do not set it because we do not give legal advice |

**Sprint 3 composition (decided on November 10)**

| Story | SP | Decision |
| --- | --- | --- |
| US-04-P2 | 3 | In |
| US-05 (pipeline and evaluator) | 8 | In; absorbs the model registry (3 SP) because the model card is part of the evaluator. Recorded as a merge |
| US-10 Web control tower | 5 | In, as a new story from change request CR-01 |
| US-09 (partial) | 3 | Returns to its original sprint (Sprint 6) |
| **Committed** | **16** | Against a capacity of about 14: a 2 SP overcommit is declared. If time runs short, the dashboard extras are cut first |

The Charter defines two-week sprints; this one is compressed into four days (November 9 to 12) and pulls forward parts of Sprints 4 and 6. Everything is recorded as replanning.

**US-10: Web control tower (5 SP)**

- Story: "As a FinBank risk committee member, I want a web dashboard that shows exposure, gate status, lineage and model evaluation in COP, so that I can audit every figure and decide on a model without reading code."
- Origin: change request CR-01. It was not part of FinBank's original brief and is funded from the Charter's contingency reserve (COP 20M).
- Acceptance criteria: reads `dashboard_data.json` with no hand-typed figures; 6-step guided mode; every figure traceable; simulator and capture curve in COP; synthetic-data banner; opens offline.
- Outside the DoD: the break-the-data button and the handover tab.

**Hours and cost scale**

- Team capacity is 12 hours per person per sprint (part-time): 36 hours per sprint for the team.
- The Charter plans 1,620 consultant hours (180M ÷ COP 111,111), that is, 90 hours per person per sprint. The declared scale is k = 90 ÷ 12 = 7.5: one logged hour equals 7.5 consultant hours, or COP 833,333.
- The numbers close: 6 sprints × 36 h × 7.5 = 1,620 h = 180M.
- Earned value: AC = logged hours × 7.5 × 111,111; EV = sprint PV × % of SP closed with DoD; SPI = EV ÷ PV; CPI = EV ÷ AC; EAC = BAC ÷ CPI.
- Hours for Sprints 1 and 2 are reconstructed from calendars, messages and commits and flagged as estimated. From November 11, each person logs hours daily.
- Sprint 3 is expected to run over plan (about 51 actual hours against 36, an AC close to 42.5M against a PV of 30M). The work pulled forward from Sprints 4 and 6 and change request CR-01 explain it, and the contingency reserve covers it.
