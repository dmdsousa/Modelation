# Expenses Features v1.1.0

Contract for the expenses behaviour feature vector computed from a hAPI proponent
snapshot. Reference implementation: `expenses_features.py` (stdlib-only Python).
Research record: `expenses_model.ipynb`.

## Architecture

```
snapshot JSON (value document, captured at application time)
        |
        v
behaviour_features()  ->  LAYER 1: full feature vector (~35 fields, versioned)
        |                     |
        |                     +--> credit score model (training + serving input)
        v
display_profile()     ->  LAYER 2: client/analyst view (headline + detail + caveats)
```

Layer 1 is the single source of truth. Layer 2 is a pure projection of it and
computes nothing of its own. The credit score model consumes the full vector;
feature selection happens at that model's training time, not here.

## Input contract

One parsed snapshot document per proponent (the `value` JSON), as captured at
application time. Keys used: `ExpensesList`, `IRSTaxDeclarationDetails`,
`IRSTaxDeclarationDetailsPreviousYear`, `PersonalTaxData.BirthDate` (holds an
anonymized age), `CRCData.Liabilities`, `RenterContractList`. No other data
source is touched, so the vector is point-in-time by construction.

## Observation window

- Receipt months from first to last receipt, **minus the first and the last
  month**. Both are partial (the window opens at the first receipt and closes at
  snapshot creation mid-month); keeping them deflates edge months and inflates
  volatility.
- Minimum **3** full months (`MIN_OBS_MONTHS`), otherwise all spend fields are
  `null` and `has_spend_data = 0`.
- Receipts with `Amount >= 1000 EUR` (`ONE_OFF_EUR`) are excluded from recurring
  spend and reported separately as `expenses_over_1000_*`.

## Layer 1 field reference

Missing or uncomputable is always `null`, never 0. Money in EUR; monthly figures
per calendar month.

### Capacity and household

| field | definition |
|---|---|
| `irs_income` | Annual income from `IRSTaxDeclarationDetails.Total.Income`, falling back to the previous-year declaration. `null` if absent or below 1 EUR (sub-1-EUR declarations are data artifacts) |
| `income_source` | `current_declaration`, `previous_declaration`, or `missing` |
| `monthly_income` | `irs_income / 12` |
| `n_dependents` | Length of the IRS `Dependents` list (empty = 0) |
| `is_couple` | 1 if `MaritalStatus` in {Casado, Unido de facto}, 0 otherwise, `null` if missing |
| `age` | `PersonalTaxData.BirthDate` (already an age) |
| `crc_total_installment` | Sum of `Installment` over all current CRC liabilities (`null` installments count as 0, so card-heavy profiles understate) |
| `crc_n_active` | Liabilities with `TotalDebt > 0` |
| `crc_has_mortgage` | 1 if any liability product is "Crédito à habitação" |
| `is_renter` | 1 if `RenterContractList` is non-empty |

### Spend behaviour (e-fatura, observation window only)

| field | definition |
|---|---|
| `window_start`, `window_end` | `YYYY-MM` bounds of the trimmed window |
| `months_observed` | Window length in months |
| `receipts_count` | Receipts inside the window |
| `kept_total` | Sum of sub-1000 receipts in the window |
| `monthly_expenses` | `kept_total / months_observed`. **A floor**: e-fatura misses rent, most utilities, and loan payments |
| `monthly_std` | Sample std of the monthly totals (empty months count as 0) |
| `monthly_cv` | `monthly_std / monthly_expenses`. Low = rigid, every month equally committed; high = lumpy, discretionary slack |
| `expenses_over_1000_count` / `_total` / `_share` | Receipts >= 1000 EUR in the window: count, summed EUR, share of window spend |
| `share_food_dining` ... `share_uncategorized` | Nine category shares of `kept_total`, summing to 1. Sector mapping per `SECTOR_MAP`; "Outros" -> `other_retail`, null sector -> `uncategorized` (together ~88% of spend) |
| `has_spend_data` | 1 if the spend block was computable |

### Housing (v1.1.0: this package owns rent)

| field | definition |
|---|---|
| `rent_monthly` | Summed monthly rent from active tenant contracts in `RenterContractList` (tenant role verified via `PersonalTaxData.Nif` in `RenterList`, 135/135 in data_full.csv). Active = monthly frequency and not ended before the window end (fallback anchor: CRC document month when no receipts exist) |
| `n_active_rent_contracts`, `rent_purpose` | Contract count and purpose |
| `monthly_expenses_incl_rent` | `monthly_expenses + rent_monthly` (rent 0 when no contract): the rent-inclusive floor |

### Model-derived and ratios

| field | definition |
|---|---|
| `expected_expenses` | Typical recurring spend for this capacity profile. Frozen Ridge on log(monthly_expenses); see below |
| `overspend_ratio` | `monthly_expenses / expected_expenses` |
| `dsti` | `crc_total_installment / monthly_income` |
| `eti` | `monthly_expenses / monthly_income` |
| `residual_income` | `monthly_income - crc_total_installment - monthly_expenses`. Negative = no visible margin |
| `features_version` | Semver string stamped into every vector |

## expected_expenses model

Ridge regression on `log(monthly_expenses)`, inputs `irs_income`,
`crc_total_installment`, `crc_has_mortgage`, `is_couple`, `age` (median
imputation, standardization). Frozen 2026-08-13, trained on 562 proponents.
Held-out performance: R2(log) 0.35, MAE ~411 EUR, ~31% typical relative error;
known to compress extremes (overpredicts low spenders, underpredicts high).
Parameters are embedded as constants in `expenses_features.py`
(`EXPECTED_MODEL`); retraining means a new `features_version`.

## Layer 2: display profile

`display_profile(features)` returns:

- `headline`: `monthly_expenses`, `monthly_income`, `crc_total_installment`,
  `dsti`, `eti`, `residual_income`, `monthly_cv`, `expenses_over_1000_total`,
  `months_observed`, `receipts_count`, `income_source`
- `detail`: every other layer-1 field
- `caveats`: display texts per field (expenses floor, income lag, residual
  reading, cv reading)

No score, probability, or approve/reject indication is produced anywhere.
The numbers describe; the human judges.

## Edge cases

| case | behaviour |
|---|---|
| No `ExpensesList` | Spend fields `null`, `has_spend_data = 0`; capacity fields still computed |
| Window < 3 full months | Same as above |
| All receipts >= 1000 EUR | `monthly_expenses = 0` is possible; `monthly_cv` is `null` |
| `irs_income` missing or <= 0 | `monthly_income`, `dsti`, `eti`, `residual_income` are `null`; `income_source = "missing"` |
| Missing model inputs | `expected_expenses` still computed via embedded imputation medians |

## Versioning policy

- `FEATURES_VERSION` follows semver. Any change to a formula, threshold, window
  rule, sector mapping, or the embedded model bumps the version.
- Vectors are stored with their version; the credit score model trains and
  serves against a pinned version. Silent redefinition is the failure mode this
  exists to prevent.

## Validation

The reference implementation was verified field-by-field against an independent
pandas implementation across all 562 proponents with usable windows in
`data_full.csv`: zero mismatches. The embedded model reproduces the sklearn
pipeline's predictions exactly on the training population.

## Known limitations (inherited by all consumers)

1. e-fatura captures invoiced spend only: `monthly_expenses` is a lower bound.
2. IRS income is annual and lagged relative to the spend window.
3. Population self-selects (people who ask for invoices with their NIF).
4. Behaviour-vs-default evidence so far is current-status association on 24-76
   defaulters (notebook section 6), not a point-in-time PD model. No automated
   decisioning until the data gates in that section are met.
