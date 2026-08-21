# Employment Features v1.0.0

Contract for the employment-stability vector computed from a hAPI proponent
snapshot. Reference implementation: `employment_features.py` (stdlib-only
Python). Research record: `employment_analysis.ipynb`. Fifth sibling of the
package family (`../expenses/`, `../liabilities/`, `../incomes/`,
`../completeness/`).

## Architecture

```
snapshot JSON (value document, captured at application time)
        |
        v
employment_features() ->  LAYER 1: full feature vector (~20 fields, versioned)
        |                     |
        |                     +--> credit score model (training + serving input)
        v
display_profile() /
render_profile_text() ->  LAYER 2: client/analyst view (headline + detail + pt-PT text)
```

## Input contract

Keys read: `LastJobInfo.Job[]` (Company status/geo/cae, `Duration`,
`FirstPayment`, `LastPayment`), `Income.workDependent[]` (SS income records:
`QualificationType`, `PayingEntityNISS`), `EndOfWorkContractsList[]`
(`EndDate`), `NetSalary[]` (continuity only).

## Core rules

1. **Employment data arrives through the Social Security gate** (see the
   completeness contract): absence usually means no data access, not
   unemployment. `has_employment_data` marks proponents where any of the
   sources exist; everything else is `null` otherwise.
2. **Main job** = the `Job` record with the longest `Duration`.
3. **`salary_growth_over_tenure` requires full months**: computed only when
   both `FirstPayment` and `LastPayment` cover `Days >= 28`. A partial
   admission month fakes spectacular growth (observed: +347% from a 6-day
   first month before the guard).
4. `anchor_month` = latest month across salary and workDependent records;
   all recency measures use it. Month = 0 aggregate rows are excluded.
5. Missing or uncomputable is always `null`, never 0.

## Layer 1 field reference

### Current employment

| field | definition |
|---|---|
| `has_employment_data` | Any of jobs / SS income records / salary series present |
| `n_job_records` | `Job` entries (1 for most; up to 3 observed) |
| `employer_active` | 1 if the main employer's company status is "active". **0 is a risk marker: the employer no longer operates** |
| `employer_region`, `employer_cae` | Region and primary activity code of the main employer |
| `tenure_months` | Main job `Duration` |
| `job_first_payment_month`, `job_last_payment_month` | Span of observed payments at the main job |
| `first_payment_amount`, `last_payment_amount` | Gross amounts of those payments |
| `salary_growth_over_tenure` | `last / first - 1` (rule 3) |
| `n_paying_entities` | Distinct paying entities in SS records (2+ = multiple employers over the window) |
| `is_board_member` | 1 if any SS record is qualification MOE (board member) rather than TCO (employee) |

### Terminations and continuity

| field | definition |
|---|---|
| `n_terminations` | Contract-end records |
| `last_termination_month` | Most recent |
| `months_since_last_termination` | vs `anchor_month` |
| `terminations_last_24m` | Terminations within 24 months of the anchor |
| `salary_streak_months` | Consecutive salary months ending at the last observed month |
| `salary_gap_months` | Months missing inside the salary span (interruptions or collection gaps) |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: `headline` (12 fields), `detail`, `caveats` (pt-PT).
- `render_profile_text(features)`: pt-PT analysis: headline (tenure +
  employer status + salary continuity + terminations summary), then labeled
  lines (Empregador, Progressão, Entidades, Continuidade, Fins de contrato)
  and the SS-source caveat. The no-data case states explicitly that absence
  does not mean unemployment. Purely mechanical.

## Population reference (data_full.csv, 565 proponents)

229 with employment data (SS gate). Median tenure 26 months (max 319).
Risk-relevant states: 71 with the main employer's company **not active**, 86
with a termination in the last 24 months, salary-series holes for 54, 7 board
members, 45 with 3+ paying entities.

## Versioning policy

Same as the sibling contracts: semver; any change to rules, thresholds, or
the main-job definition bumps `FEATURES_VERSION`; consumers pin.

## Validation

Verified against an independent recomputation across all 565 proponents
(1,449 comparisons: tenure, growth with the full-month guard, terminations,
streaks, gaps): zero mismatches. The validation runs as the final cell of
`employment_analysis.ipynb`.

## Known limitations

1. Tenure covers only the observable payment window; true seniority may be
   longer.
2. `employer_active` reflects the company registry status at extraction; a
   recently failed employer may still show active.
3. Termination records carry no reason (dismissal vs resignation vs contract
   end).
4. Coverage is bounded by the SS gate (~40% of proponents).
