# Liabilities Features v1.0.0

Contract for the liabilities feature vector computed from a hAPI proponent
snapshot's `CRCData` (Banco de Portugal credit register). Reference
implementation: `liabilities_features.py` (stdlib-only Python). Research
record: `liabilities_analysis.ipynb`. Sibling contract: the expenses features
(`../expenses/FEATURES_SPEC.md`); the two vectors share the architecture and
are consumed together by the credit score model and the client-facing view.

## Architecture

```
snapshot JSON (value document, captured at application time)
        |
        v
liability_features()  ->  LAYER 1: full feature vector (~40 fields, versioned)
        |                     |
        |                     +--> credit score model (training + serving input)
        v
display_profile() /
render_profile_text() ->  LAYER 2: client/analyst view (headline + detail + pt-PT text)
```

## Input contract

One parsed snapshot document per proponent. Only `CRCData` is read:
`DocumentDate` (the vector's reference date) and `Liabilities[]` with fields
`Product`, `BeginDate`, `EndDate`, `TotalDebt`, `TotalDefault`,
`DefaultInitialDate`, `Installment`, `Potential`, `InstitutionCode`,
`ResponsabilityType`, `Debtors`, `InLitigation`.

`InstallmentType` is deliberately NOT used: it carries extraction artifacts
("Legenda", "Data de Emissão:", "Tipo de responsabilidade").

## Core rules

1. **Debtor vs guarantor**: all totals (debt, installments, potential,
   defaults, product mix, timeline) cover only entries where
   `ResponsabilityType == "Devedor"`. Guarantor entries ("Avalista / fiador")
   are reported separately as `guarantor_n` / `guarantor_exposure`
   (TotalDebt + Potential of those entries): contingent exposure, not own debt.
2. **Reference date** = `CRCData.DocumentDate`. Ages, "opened last 12 months"
   and maturities are measured against it, so the vector is point-in-time.
3. **Null `Installment` counts as 0** and is tallied in
   `n_missing_installment` (common on cards/overdrafts): `total_installment`
   understates true debt service for card-heavy profiles.
4. Missing or uncomputable is always `null`, never 0.

## Product families

`PRODUCT_FAMILY` maps every register product to one of: `mortgage` (incl.
"Crédito conexo"), `personal`, `card`, `auto` (incl. leasing), `revolving`
(credit lines, overdrafts, "ultrapassagens"), `business` (incl. factoring and
confirming), `guarantee_given`, `other` (unmapped; currently only
"Outros créditos").

## Layer 1 field reference

### Exposure

| field | definition |
|---|---|
| `reference_date` | `CRCData.DocumentDate`, YYYY-MM-DD |
| `has_crc_data` | 1 if any liabilities exist |
| `n_liabilities` | All register entries (debtor + guarantor) |
| `n_active` | Debtor entries with `TotalDebt > 0` |
| `n_institutions` | Distinct `InstitutionCode` among debtor entries |
| `total_debt` | Sum of debtor `TotalDebt` |
| `total_installment` | Sum of debtor `Installment` (EUR/month; rule 3) |
| `total_potential` | Sum of debtor `Potential` (undrawn limits/lines) |
| `n_missing_installment` | Debtor entries with null `Installment` |
| `n_joint` | Debtor entries with `Debtors >= 2` |

### Product mix

| field | definition |
|---|---|
| `debt_<family>` / `n_<family>` | `TotalDebt` sum and count per family (8 families) |
| `has_mortgage` | 1 if any mortgage-family entry |
| `revolving_debt_share` | (card + revolving debt) / `total_debt`; expensive-debt marker |

### Timeline

| field | definition |
|---|---|
| `oldest_credit_years` | Years from earliest `BeginDate` to reference date (history length) |
| `newest_credit_months` | Months since the most recent `BeginDate` |
| `n_opened_12m` | Credits with `BeginDate` within 12 months of reference (credit appetite) |
| `latest_maturity_years` | Years to the furthest dated `EndDate` |
| `n_open_ended` | Entries with `EndDate = 9999-12-31` (revolving) |

### Risk markers

| field | definition |
|---|---|
| `n_in_default` | Debtor entries with `TotalDefault > 0` |
| `total_default` | Sum of debtor `TotalDefault` |
| `default_debt_share` | `total_default / total_debt` |
| `first_default` | Earliest `DefaultInitialDate` (YYYY-MM) among entries in default |
| `months_in_default` | Months from `first_default` to reference date |
| `any_litigation` | 1 if any debtor entry `InLitigation` |
| `guarantor_n` / `guarantor_exposure` | Guarantor entries and their TotalDebt + Potential |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: `headline` (13 fields: totals, defaults,
  guarantor, reference date), `detail` (the rest), `caveats` (pt-PT display
  texts).
- `render_profile_text(features)`: pt-PT plain text: a headline sentence
  ("Tem 5 créditos ativos em 4 instituições: ... Sem incumprimento registado."
  or "EM INCUMPRIMENTO: ..."), a labeled block (Dívida total, Prestações,
  Composição, Histórico, Potencial, Incumprimento, Litígio, Como avalista),
  and the CRC caveat line. Purely mechanical: every sentence traces to a
  field; no judgment words, no score.

## Edge cases

| case | behaviour |
|---|---|
| No liabilities | `has_crc_data = 0`, everything else `null`; text says "Sem responsabilidades de crédito registadas na CRC." |
| Only guarantor entries | Debtor totals are 0/None; guarantor fields populated |
| `Potential` below 1 EUR | Suppressed from the text (still in the vector) |
| Missing `DocumentDate` | `reference_date` null; timeline fields null |

## Versioning policy

Same as the expenses contract: `FEATURES_VERSION` is semver; any change to a
formula, threshold, family mapping, or rule bumps it; consumers pin a version.

## Validation

Verified against an independent pandas implementation across all 565
proponents (11 core fields: totals, counts, defaults, guarantor, mortgage
debt, opened-12m): zero mismatches. The validation also runs as the final
cell of `liabilities_analysis.ipynb`.

## Known limitations

1. `total_installment` understates debt service where installments are
   unreported (rule 3); `n_missing_installment` flags how much.
2. The register shows granted credit only; no application/rejection history.
3. Guarantee collateral detail (`Guarantees`) is not yet parsed into the
   vector; only exposure via `Potential` is counted.
