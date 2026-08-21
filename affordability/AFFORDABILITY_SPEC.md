# Affordability Synthesis v1.2.0

Contract for the affordability-synthesis vector and the unified proponent
report. Reference implementation: `affordability_features.py` (stdlib-only
Python; imports the six sibling modules). Research record:
`affordability_analysis.ipynb`. Seventh and top package of the family: it
computes nothing the siblings already compute; it selects, combines, and
derives.

## Architecture

```
snapshot JSON
   |            completeness  adverse  incomes  employment  liabilities  expenses
   |                 \\           \\        |         |            /          /
   +----------------- proponent_profile(): all seven vectors ---------------+
                                   |
                     affordability_features(): synthesis vector
                                   |
              render_full_report(): SÍNTESE + the six pt-PT sections
```

API: `affordability_features(profile, vectors=None)` (pass precomputed
sibling vectors to avoid recomputation), `proponent_profile(profile)` ->
dict of all eight vectors, `render_full_report(profile, vectors=None)` ->
the complete pt-PT analysis. Section order: SÍNTESE, DADOS, REGISTOS
ADVERSOS, RENDIMENTO, EMPREGO, RESPONSABILIDADES, BANCA, DESPESAS.
(v1.1.0 added the BANCA section from the banking package.)

## Core rules

1. **Income basis is explicit and prioritized**: `salary_net` (6-month
   average net salary) > `ss_regular` (SS regular income) > `irs_gross`
   (IRS/12, gross and household-wide) > `none`. `income_basis` states which
   is live; **ratios on different bases are not comparable across people**.
2. **Rent is a commitment, owned by the expenses package (v1.1.0+)**: the
   synthesis carries `rent_monthly` / `n_active_rent_contracts` /
   `rent_purpose` from the expenses vector instead of computing its own
   (single-owner principle). Tenant role verified via `PersonalTaxData.Nif`
   in `RenterList` (135/135 in data_full.csv; `PersonalData.NIF` uses a
   different encoding and does not match).
3. `residual_income = monthly_income - debt_service - rent_monthly -
   expenses_floor`. The floor comes from invoiced expenses, so the residual
   is optimistic.
4. Missing or uncomputable is always `null`, never 0.

## Layer 1 field reference

| field | definition |
|---|---|
| `monthly_income`, `income_basis` | Best-available monthly income and its basis |
| `debt_service` | CRC total monthly installments (liabilities vector) |
| `rent_monthly`, `n_active_rent_contracts`, `rent_purpose` | Active tenant contracts |
| `expenses_floor` | Recurring invoiced monthly spend (expenses vector) |
| `committed_outgoings` | `debt_service + rent_monthly` (contractual) |
| `dsti` | `debt_service / monthly_income` |
| `rent_to_income` | `rent_monthly / monthly_income` |
| `total_outgoings_floor`, `burden_ratio` | Commitments + expenses floor; as share of income |
| `residual_income`, `residual_ratio` | What remains, EUR and share |
| carried context | `income_verification`, `can_full_affordability`, `n_consistency_flags`, `any_adverse`, `adverse_markers`, `in_default_now`, `guarantor_exposure` (contingent, NOT in commitments), `expenses_cv`, `employer_active`, `tenure_months` |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: headline (12 fields), detail, caveats (pt-PT).
- `render_profile_text(features)`: the SÍNTESE block: income with basis,
  commitments, expenses floor, burden and residual, contingent exposure, and
  an ATENÇÃO suffix when adverse records or active CRC default exist.
- `render_full_report(profile)`: SÍNTESE plus the six package texts under
  section headers: the beta's complete per-proponent payload.

## Population reference (data_full.csv, 565 proponents)

Income basis: irs_gross 332, salary_net 218, none 15. Residual computable for
548; median **-177 EUR/month, negative for 331 (60%)**. Read that number with
the interpretation caveat below before alarm: it is a floor-vs-basis
artifact as much as a solvency statement.

## Interpretation caveat (important)

The e-fatura expenses floor can capture **household-level** spending (one
member collects the family's invoices) while `salary_net` income is
**proponent-only**; that asymmetry inflates burden for salaried members of
couples. The `irs_gross` basis has the mirror problem (household income,
gross of tax). Cross-person comparisons must condition on `income_basis`,
and negative residuals for couples deserve a household-level read (the
`is_couple` / `irs_is_joint` fields in the sibling vectors identify them).

## Versioning policy

Same as the siblings: semver; any change to basis priority, rent rules, or
formulas bumps `FEATURES_VERSION`; consumers pin. Sibling version changes
propagate through carried fields: the combined CSV records every package's
version per row.

## Validation

2,226 identity and selection checks across all 565 proponents (residual and
DSTI arithmetic identities, basis priority against the incomes vector, rent
against an independent recompute): zero mismatches. The validation runs as
the final cell of `affordability_analysis.ipynb`.

## Known limitations

1. The residual is optimistic (expenses floor) and basis-dependent (rule 1).
2. Utilities, insurance premia, and non-invoiced spend remain unobserved.
3. Rent contracts cover only registered leases; informal rent is invisible.
4. Guarantor exposure is reported but not stressed into the commitments; a
   prudent scenario add-on is a natural v1.1.
