# Banking Footprint Features v1.0.0

Contract for the banking-footprint vector computed from a hAPI proponent
snapshot's `BCBData.Accounts` (Banco de Portugal account map). Reference
implementation: `banking_features.py` (stdlib-only Python). Research record:
`banking_analysis.ipynb`. Eighth sibling of the package family.

## Architecture

```
snapshot JSON (value document, captured at application time)
        |
        v
banking_features()    ->  LAYER 1: full feature vector (~20 fields, versioned)
        |                     |
        |                     +--> credit score model (training + serving input)
        v
display_profile() /
render_profile_text() ->  LAYER 2: client/analyst view (headline + detail + pt-PT text)
```

## Input contract

Keys read: `BCBData.DocumentDate` (the reference date) and
`BCBData.Accounts[]` with `AccountType`, `SubType`, `AccountRelation`,
`OpenDate`, `CloseDate`, `InstitutionCode`, `InstitutionName`.

## Core rules

1. **The map lists only OPEN accounts** (0 of 6,933 records in data_full.csv
   carry a CloseDate): closures and churn are NOT observable; only openings
   are. Never interpret a small footprint as "closed accounts".
2. **Type/mix counts cover "Titular" accounts** (ownership). Other relations
   are reported separately: `n_as_authorized` (authorized to move third-party
   accounts) and `n_as_beneficial_owner`: access to money, not ownership.
3. **Card accounts are a subset of credit facilities**: every
   `SubType = "Cartão"` record is `AccountType = "Abertura de crédito"`
   (1,776 of 1,776). `n_card_accounts` and `n_credit_facilities` overlap by
   design; do not sum them.
4. **Unidentified institutions**: 203 credit-facility records carry no
   institution code or name; they count in type totals but not in
   `n_institutions`.
5. Missing or uncomputable is always `null`, never 0.

## Layer 1 field reference

| field | definition |
|---|---|
| `reference_date` | `BCBData.DocumentDate` |
| `has_bcb_data`, `n_accounts` | Presence and total records (all relations) |
| `n_as_titular`, `n_as_authorized`, `n_as_beneficial_owner` | Role split |
| `n_current_accounts` | Titular "Depósito à ordem" |
| `n_term_deposits`, `has_savings` | Term/notice deposits: a savings marker |
| `n_investment_accounts`, `has_investments` | "Instrumentos financeiros": a wealth marker |
| `n_payment_accounts` | Payment institutions |
| `n_credit_facilities` | "Abertura de crédito" (includes cards) |
| `n_card_accounts` | `SubType = Cartão` subset |
| `n_institutions` | Distinct identified institutions (titular) |
| `main_institution_share` | Accounts at the top institution / titular accounts; 1.0 = single-bank |
| `oldest_account_years` | Age of the oldest titular account: relationship length |
| `newest_account_months`, `n_opened_12m` | Recency of openings |
| `n_credit_opened_12m` | Credit facilities opened in the last 12 months: recent credit appetite, corroborates the CRC's `n_opened_12m` |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: headline (11 fields), detail, caveats (pt-PT).
- `render_profile_text(features)`: pt-PT analysis: headline (institutions,
  relationship age, account count, savings/investment markers, recent credit
  openings), then Contas (mix), Concentração, Histórico, Outros papéis, and
  the open-accounts-only caveat.

## Population reference (data_full.csv, 565 proponents)

556 with titular accounts. Median relationship age 13.8 years (max 44).
Savings 207, investment accounts 165, single-bank 13; 471 opened at least
one credit facility in the last 12 months (consistent with a population of
recent credit applicants).

## Versioning policy

Same as the sibling contracts: semver; consumers pin.

## Validation

4,448 independent pandas comparisons across all 565 proponents (role split,
type counts, institutions with the empty-code rule, relationship age, recent
openings): zero mismatches. The validation runs as the final cell of
`banking_analysis.ipynb`.

## Known limitations

1. No balances or turnover: the map shows existence, not usage or wealth
   amounts.
2. No closures (rule 1): churn is invisible.
3. 203 credit facilities lack institution identity.
4. `main_institution_share` counts accounts, not money.
