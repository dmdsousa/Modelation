# Completeness Features v1.2.0

Contract for the data-completeness vector computed from a hAPI proponent
snapshot. Reference implementation: `completeness_features.py` (stdlib-only
Python). Research record: `completeness_analysis.ipynb`. This is the
cross-cutting layer over the three profile contracts (`../expenses/`,
`../liabilities/`, `../incomes/`): consumers read it FIRST to know how much
of the profile to trust and why parts are absent.

## The model of absence

Completeness is not one score. Measured on 565 snapshots, absence has three
different meanings:

| kind | sources | meaning of absence |
|---|---|---|
| **Core** (95-100% coverage) | CRC, personal data, e-fatura, IRS, IRS debt certificate, BCB accounts | Extraction defect. Flag and refetch. |
| **Social Security block** (~39%, co-occur 94-98%) | NetSalary, SSPayments, CalculatedIncomes, LastJobInfo | One gate, open or closed. A **data-access artifact, not a personal trait** (see evidence below). Closed = income rests on IRS alone (annual, lagged): you know less, the person is not different. |
| **Situational** | activity registration, invoices, renter contracts, pension | **At most weakly descriptive** (see evidence below). Never treat absence as a person-level signal without the measurements to back it. |

## Extraction telemetry (v1.2.0)

`ServicesResults` logs every extraction service call with an error code. The
taxonomy, validated against the sources themselves (the rent service returns
no-data for exactly the 436 proponents without contracts; terminations match
exactly):

| code | meaning | status |
|---|---|---|
| 200 | data returned | `ok` |
| 484 | **no data exists** (a normal outcome, not a failure) | `no_data` |
| 481/482/485/486/487 | technical error; a failure only if the service never reached 200 or 484 (LoginValidator always recovered via retries) | `failed` |

Fields: `n_services_called` / `_ok` / `_no_data` / `_failed`,
`failed_services`, `refetch_recommended`, per-source statuses (`rent_fetch`,
`invoices_fetch`, `terminations_fetch`, `activity_fetch`), `is_landlord`
(landlord-contract service returned data), and **`ss_gate_cause`**:

| cause | meaning | n (data_full) |
|---|---|---|
| `open` | SS block present | 227 |
| `not_attempted` | the SS services were never invoked: credentials/consent absent. The gate is a **collection-scope decision**, not a data failure | 329 |
| `fetched_but_empty` | services returned 200 but the source stayed empty: investigate | 6 |
| `no_data` | services answered: nothing exists | 3 |

45 proponents carry at least one genuine technical failure
(`refetch_recommended = 1`), including failures of `getNetSalary` itself.

## Measured meaning of absence (evidence, data_full.csv, 565 proponents)

Claims about what absence "means" were tested by crossing the completeness
flags against the expenses, liabilities and incomes vectors:

- **SS gate cause is now measured** (v1.2.0): 329 of 338 closed gates are
  `not_attempted`: the services were never invoked. Combined with the parity
  evidence below, the gate is a collection-scope artifact end to end.
- **SS gate is not self-employment**: annex B income present 16% (gate
  closed) vs 15% (open); B-dominant declarations 5% vs 7%; open activity 16%
  vs 17%. Similar median income (16.4k vs 17.4k) and age (40 vs 35);
  significant-default rate identical (7% both); any-default 18% vs 14.5%
  (weak). The only large difference, employer info, arrives through the gate
  itself and is circular.
- **Renter contract is weakly descriptive**: renters hold mortgages at 6% vs
  17% for non-renters. But 362 of 565 have neither contract nor mortgage, so
  absence mostly means "housing situation unobserved".
- **Pension** (n=9) is too thin to interpret; one 77-year-old shows no
  pension record, so absence does not even reliably mean "not a pensioner".
- **`income_verification = none` (n=15)**: these proponents have CRC
  histories up to 27.8 years and normal e-fatura spending. Absence of all
  income sources with visible economic life is a suspected collection gap,
  exposed as `income_none_suspect_gap`.
- **Missingness barely predicts default**: `has_ss_block`, renter, invoices
  vs `default_any` give AUC 0.51-0.53. Do not use missingness as a risk
  signal in this data.

## Layer 1 field reference

### Core

| field | definition |
|---|---|
| `has_crc`, `has_personal_data`, `has_efatura`, `has_irs`, `has_irs_no_debt_cert`, `has_bcb_accounts` | Presence of each core source (`has_irs` requires a usable declaration >= 1 EUR, current or previous year) |
| `n_core_present` | 0-6 |
| `core_complete` | 1 if all six present |
| `missing_core` | Semicolon list of missing core sources, `null` if complete |

### Social Security block

| field | definition |
|---|---|
| `has_net_salary`, `has_ss_payments`, `has_calculated_incomes`, `has_job_info` | Individual members |
| `has_ss_block` | Gate flag: salary or SS payments present |
| `ss_block_complete` | All four members present |
| `n_salary_months` | Salary series length (Month = 0 rows excluded) |

### Situational

`has_activity_registration`, `has_invoices`, `has_renter_contracts`,
`has_pension`: presence flags only; no score aggregates them.

### Regime

| field | definition |
|---|---|
| `income_verification` | `ss_verified` (gate open) / `irs_only` / `none`. The single most consequential distinction for downstream analysis: it determines what can be known, not who the person is |
| `income_none_suspect_gap` | 1 when `income_verification = none` but CRC or e-fatura shows economic life: a suspected collection failure rather than a person without income |

### Inventory and series integrity (v1.1.0)

Presence alone is shallow; these fields quantify each source and check its
internal continuity:

| field | definition |
|---|---|
| `n_crc_liabilities`, `n_bcb_accounts`, `n_receipts`, `n_receipt_months`, `n_invoice_months` | Quantities per source |
| `salary_first_month`, `n_salary_months`, `salary_gap_months` | Salary series span and **holes inside it** (months missing between first and last: employment interruption or collection gap) |
| `n_ss_months`, `ss_gap_months` | Same for Social Security payments |
| `receipt_gap_months` | Months with zero receipts inside the e-fatura span |
| `salary_ss_divergence_months` | Size of the symmetric difference between salary months and SS months (0-1 = normal reporting lag) |
| `spend_after_income_months` | How many months receipts continue after the last income record: income data stopped, life did not |
| `irs_lag_years` | Anchor year minus the IRS declaration year (1 = normal) |

### Cross-source consistency (v1.1.0)

`consistency_flags` (semicolon list) and `n_consistency_flags` encode
contradictions to resolve before trusting the profile. Flags and their
prevalence in data_full.csv:

| flag | trigger | n |
|---|---|---|
| `salary_series_has_holes` | >= 2 months missing inside the salary span | 40 |
| `salary_ss_divergence` | salary and SS months differ by >= 3 | 38 |
| `irs_stale_2y_plus` | IRS lag >= 2 years | 26 |
| `open_activity_without_self_employment_income` | open activity, no Annex B, no invoices | 19 |
| `invoices_without_activity_registration` | invoicing without registered activity | 10 |
| `crc_debt_without_bcb_accounts` | CRC liabilities but no bank accounts | 9 |
| `income_series_stopped_early` | receipts continue >= 3 months past last income record | 4 |
| `salary_without_job_info` | salary series but no employer record | 3 |
| `salary_without_irs_annex_a` | salary series but empty IRS Annex A | 1 |

### Analysis readiness (v1.1.0)

| field | definition |
|---|---|
| `can_expenses_profile` | >= 3 months of receipts |
| `can_liabilities_profile` | CRC liabilities present |
| `can_salary_verification` | Salary series present |
| `can_dsti` | CRC plus (IRS or salary) |
| `can_full_affordability` | Expenses profile plus DSTI |
| `n_analyses_possible` | 0-5 |

### Freshness

| field | definition |
|---|---|
| `data_anchor_month` | Newest month observed in any dated source of this snapshot (extraction-relative anchor) |
| `last_receipt_month`, `last_salary_month`, `last_ss_month`, `crc_reference_month`, `irs_year` | Last observed period per source |
| `efatura_staleness_months`, `salary_staleness_months`, `ss_staleness_months`, `crc_staleness_months` | `data_anchor_month` minus the source's last month |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: `headline` (10 fields), `detail`, `caveats` (pt-PT).
- `render_profile_text(features)`: the pt-PT data-quality analysis shown at
  the top of a profile: a headline (completeness + verification regime +
  inconsistency count), then labeled lines: Núcleo, Inventário (quantities,
  spans and holes per source), Seg. Social (series continuity and salary/SS
  alignment), Continuidade (when income data stops before observed life),
  Situacional, Inconsistências (each flag spelled out in words), and
  Análises (which downstream analyses are possible vs blocked). Purely
  mechanical: every sentence traces to a field.

## Deliberate non-features

No aggregate completeness score is produced. A source-count score would
punish non-renters and non-pensioners while hiding the one distinction that
matters (`income_verification`). Consumers wanting a gate should use
`core_complete` and `income_verification` directly.

## Population reference (data_full.csv, 565 proponents)

- `core_complete`: 531 (94%). Missing-core breakdown: IRS 17, IRS+BCB 6,
  certificates 4, BCB 3, e-fatura 2, multi-source 2.
- `income_verification`: ss_verified 227, irs_only 323, none 15.

## Versioning policy

Same as the sibling contracts: semver; any change to source lists, gate
definitions, or freshness rules bumps `FEATURES_VERSION`; consumers pin.

## Validation

Verified against an independent recomputation across all 565 proponents
(2,825 comparisons in the notebook; 4,173 in the build check including
staleness dates): zero mismatches. The validation runs as the final cell of
`completeness_analysis.ipynb`.

## Known limitations

1. Staleness is extraction-relative (vs `data_anchor_month`), not wall-clock;
   the serving system should additionally compare the anchor to the
   application date.
2. The SS-gate interpretation (consent/permission) is inferred from
   co-occurrence, not from an explicit consent flag in the snapshot.
3. BCB account *content* is not assessed, only presence.
