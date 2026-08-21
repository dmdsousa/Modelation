# Adverse Records Features v1.0.0

Contract for the adverse-records vector computed from a hAPI proponent
snapshot. Reference implementation: `adverse_features.py` (stdlib-only
Python). Research record: `adverse_analysis.ipynb`. Sixth sibling of the
package family.

Purpose: hard distress markers from public records. Rare (57 of 565
proponents carry any) but each is near-dispositive for credit. Intended use:
**scorecard hard rules with manual verification**, not statistical features.

## Architecture

```
snapshot JSON (value document, captured at application time)
        |
        v
adverse_features()    ->  LAYER 1: full feature vector (~22 fields, versioned)
        |                     |
        |                     +--> credit decisioning (hard rules) + layer 2
        v
display_profile() /
render_profile_text() ->  LAYER 2: client/analyst view (headline + detail + pt-PT text)
```

## Input contract

Keys read: `IRSNonDebtCertificateData` / `SSNonDebtCertificateData`
(`HasDebts`, `DocumentDate`), `BorrowerMetaInformation` (string flags
`hasExecutions`, `hasInsolvencies`, `hasATPublicDebts`, `hasSSPublicDebts`),
`DebtExecutionProceedingList[]` (`DebtAmount`, `Reason`,
`ProceedingEndDate`), `InsolvencyProceedingsList[]` (`Type`, `Act`, `Date`,
`Debtors[]` with roles), `SocialSecurityPublicDebts[]` (`Min`/`Max` bands),
`TaxAuthorityPublicDebts[]`, `PersonalData.NIF` (hashed, for role matching).

## The insolvency role model (the reason this module exists)

Proceedings returned by the search do NOT all belong to the proponent as
debtor: parties carry roles, and naive counting marks creditors and third
parties as insolvent. `insolvency_level`:

| level | rule | n (data_full) | adverse? |
|---|---|---|---|
| `confirmed` | proponent's NIF appears as "Insolvente" in a proceeding's Debtors | 11 | yes |
| `flagged` | provider flag "true" but no party match | 10 | yes, **manual verification required** |
| `proceedings_only` | proceedings returned, flag "false", proponent not a party | 11 | **no** |
| `none` | nothing returned | 533 | no |

## Layer 1 field reference

### Certificates and flags

| field | definition |
|---|---|
| `irs_cert_has_debts`, `irs_cert_month` | AT debt-nonexistence certificate: 1 = owes the tax authority |
| `ss_cert_has_debts`, `ss_cert_month` | Same for Social Security |
| `flag_executions`, `flag_insolvencies`, `flag_at_public_debts`, `flag_ss_public_debts` | Provider flags, parsed from string "true"/"false"/None |

### Executions

| field | definition |
|---|---|
| `n_execution_proceedings` | Debt execution proceedings |
| `execution_debt_total` | Summed `DebtAmount` |
| `execution_no_assets` | 1 if any ended for "Inexistência de bens" (no seizable assets: the debt persists) |
| `last_execution_end_month` | Most recent proceeding end |

### Insolvencies

| field | definition |
|---|---|
| `insolvency_level` | See role model above |
| `n_insolvency_proceedings` | All proceedings returned by the search |
| `n_insolvencies_as_insolvent` | Proceedings where the proponent is the Insolvente |
| `insolvency_personal` | 1 = "pessoa singular" type (vs company), only when confirmed |
| `has_debt_discharge_act` | 1 if any act mentions "Exoneração" (debt discharge) |
| `last_insolvency_act_month` | Most recent act date |

### Public debts and summary

| field | definition |
|---|---|
| `ss_public_debt_max` | Upper bound of the registered SS debt band |
| `n_at_public_debts` | AT public-debt records |
| `adverse_markers` | Semicolon list: `at_debt_certificate`, `ss_debt_certificate`, `debt_executions`, `insolvency_confirmed`, `insolvency_flagged_unconfirmed`, `public_debts` |
| `n_adverse_markers`, `any_adverse` | Count and 0/1 summary |
| `features_version` | Semver stamped into every vector |

## Layer 2

- `display_profile(features)`: `headline` (10 fields), `detail`, `caveats` (pt-PT).
- `render_profile_text(features)`: pt-PT analysis: headline ("REGISTOS
  ADVERSOS (n): ..." or "Sem registos adversos"), then Certidões, Execuções
  (with the no-assets warning), Insolvência (level-aware wording, including
  the explicit "não é marcador adverso" for `proceedings_only` and "VERIFICAR
  MANUALMENTE" for `flagged`), Dívidas públicas, and the hard-rules caveat.

## Population reference (data_full.csv, 565 proponents)

`any_adverse`: 57 (10.1%). Markers: AT debt certificate 38, insolvency
confirmed 11, insolvency flagged 10, executions 5 (totaling 4.7k-23k EUR,
one "Inexistência de bens"), SS public debt band 1 (25k-50k).

**Adverse records and CRC defaults are complementary, not redundant**: 47
adverse-marked proponents have no CRC default, and 83 CRC defaulters carry no
adverse marker; the CRC-default rate among adverse-marked (18%) is barely
above population (16%). They observe different distress channels (tax/legal
vs bank credit), so a scorecard needs both.

## Versioning policy

Same as the sibling contracts: semver; any change to role rules, marker
definitions, or thresholds bumps `FEATURES_VERSION`; consumers pin.

## Validation

Verified against an independent recomputation across all 565 proponents
(2,260 comparisons: levels, role counts, execution totals, certificates,
flag parsing): zero mismatches. The validation runs as the final cell of
`adverse_analysis.ipynb`.

## Known limitations

1. Role matching depends on hashed-NIF equality; the 10 `flagged` cases could
   not be confirmed or refuted from the party lists: hence the mandatory
   manual check.
2. Insolvency `Act` strings are free-text court publications; only closure
   and discharge are pattern-matched.
3. SS public debts arrive as bands (`Min`/`Max`), not exact amounts.
4. Certificates reflect the extraction date; a debt settled since would still
   show.
