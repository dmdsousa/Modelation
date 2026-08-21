# Incomes Features v1.0.0

Contract for the income feature vector computed from a hAPI proponent
snapshot. Reference implementation: `incomes_features.py` (stdlib-only
Python). Research record: `incomes_analysis.ipynb`. Sibling contracts:
`../expenses/FEATURES_SPEC.md` and `../liabilities/LIABILITIES_SPEC.md`;
the three vectors share the architecture and are consumed together by the
credit score model and the client-facing view.

## Architecture

```
snapshot JSON (value document, captured at application time)
        |
        v
income_features()     ->  LAYER 1: full feature vector (~40 fields, versioned)
        |                     |
        |                     +--> credit score model (training + serving input)
        v
display_profile() /
render_profile_text() ->  LAYER 2: client/analyst view (headline + detail + pt-PT text)
```

## Input contract

One parsed snapshot document per proponent. Keys read: `IRSTaxDeclarationDetails`
and `...PreviousYear` (Total, Year, AnnexA, AnnexB), `NetSalary[]`,
`SSPayments.Payments[]`, `CalculatedIncomes`, `ActivityRegistration`,
`InvoicesList[]`, `Income.Pension[]`, `LastJobInfo.Job[]`.

## Core rules

1. **Sources are never mixed silently.** IRS is annual, GROSS, and
   household-wide (couples declare together); NetSalary is monthly, NET,
   proponent-only. Each is reported in its own fields;
   `salary_vs_irs_ratio` makes the cross-source comparison explicit.
2. **Month = 0 entries** in monthly series (annual aggregates / bonus rows in
   NetSalary and SSPayments) are excluded from monthly averages.
3. **Sub-1-EUR annual IRS declarations count as missing** (data artifacts;
   same rule as the expenses contract).
4. "6m" averages cover the **last 6 recorded months of that source**, not
   calendar months back from the snapshot date.
5. Missing or uncomputable is always `null`, never 0.

## Layer 1 field reference

### IRS (annual, gross, household)

| field | definition |
|---|---|
| `irs_income_source` | `current_declaration` / `previous_declaration` / `missing` |
| `irs_year`, `irs_total_income` | Year and `Total.Income` of the best-available declaration |
| `monthly_income_irs` | `irs_total_income / 12` |
| `irs_prev_year`, `irs_total_income_prev` | Previous-year declaration |
| `irs_yoy_growth` | `current / previous - 1`; only when the current declaration exists |
| `irs_annex_a_income` | Annex A total (dependent work) |
| `irs_annex_b_income` | Annex B total (self-employment / business) |
| `self_employed_share` | `B / (A + B)` |
| `irs_holder_b_income`, `irs_is_joint` | Second holder's annex income; 1 if > 0 (joint declaration) |

### Salary (monthly, net, proponent)

| field | definition |
|---|---|
| `has_salary_data`, `salary_months_covered`, `last_salary_month` | Series presence and reach |
| `avg_net_salary_6m`, `avg_gross_salary_6m` | Means over the last 6 recorded months |
| `latest_net_salary` | Most recent month's net |
| `variable_income_share_6m` | Variable component / net, last 6 months |

### Social Security, precomputed, self-employment, pension, employment

| field | definition |
|---|---|
| `has_ss_data`, `ss_months_covered`, `last_ss_month`, `avg_ss_amount_6m` | SS declared remuneration |
| `avg_regular_income_6m` / `_12m`, `avg_variable_income_6m`, `avg_pension_income_6m`, `avg_invoices_income_6m`, `last_regular_income_month` | hAPI `CalculatedIncomes` pass-through |
| `has_activity_registration`, `activity_open`, `activity_start_year`, `activity_tax_category` | Self-employment registration; open = no `IRSActivity.EndDate` |
| `has_invoices`, `invoices_months_covered`, `last_invoice_month`, `invoices_total_12m` | Self-employed invoicing (last 12 recorded months) |
| `has_pension`, `latest_pension_value` | Pension records or precomputed pension average |
| `n_job_records`, `employer_active` | Employment records; employer status "active" |

### Coherence

| field | definition |
|---|---|
| `n_income_sources` | Independent sources present, 0-5: IRS, salary, SS, invoices, pension |
| `salary_vs_irs_ratio` | Gross salary annualized / IRS total. Far from 1.0 flags income change, other sources, or a joint declaration |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: `headline` (12 fields), `detail`, `caveats` (pt-PT).
- `render_profile_text(features)`: pt-PT plain text: headline sentence built
  from the best-available monthly figure (salary, then SS regular income,
  then IRS/12), then labeled lines (Salário, Variável, IRS + Evolução,
  Atividade independente, Faturação, Pensão, Coerência, Fontes) and the
  gross-vs-net caveat. Purely mechanical, no judgment words, no score.

## Edge cases

| case | behaviour |
|---|---|
| No sources at all | All fields null, `n_income_sources = 0`; text: "Sem rendimento verificável nas fontes disponíveis." |
| IRS missing, salary present | Headline uses salary; IRS lines omitted |
| Only previous-year IRS | Used with `irs_income_source = previous_declaration`; `irs_yoy_growth` null |
| Activity registered but ended | `activity_open = 0`, rendered "cessada" |

## Versioning policy

Same as the sibling contracts: semver, any formula/threshold/rule change bumps
`FEATURES_VERSION`, consumers pin a version.

## Validation

Verified against an independent pandas implementation across all 565
proponents (salary/SS averages and coverage, invoice totals, IRS rule): 738
comparisons, zero mismatches at 0.015 EUR tolerance (which absorbs
banker's-rounding ties on averages). The validation runs as the final cell of
`incomes_analysis.ipynb`.

## Known limitations

1. Salary and SS series end at extraction; freshness relative to application
   date must be judged via `last_salary_month` / `last_ss_month`.
2. IRS household totals cannot be split per person beyond the holder A/B
   annex breakdown.
3. `EndOfWorkContractsList` (employment terminations) is not yet parsed;
   candidate for v1.1 as an income-stability signal.
4. `salary_vs_irs_ratio` compares adjacent but not identical periods (last 6
   observed months vs the declaration year).
