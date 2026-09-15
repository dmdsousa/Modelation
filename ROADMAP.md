# Modelation roadmap

Updated 2026-08-18. Six feature packages built over data/data_full.csv (565
proponents). Each follows the standard template: stdlib module (layer 1
versioned vector + layer 2 pt-PT text), independent validation with zero
mismatches, per-proponent CSV, analysis notebook, spec + published artifact.
The combined per-proponent payload lives in proponent_profiles.csv (230
columns, six pt-PT text blocks per person).

## Shipped

| package | version | contents | key findings |
|---|---|---|---|
| expenses/ | 1.1.0 | recurring monthly spend from e-fatura, expected-expenses model, behaviour metrics, rent from tenant contracts (v1.1.0) | model R2 0.35 held-out; overspend-vs-peers does NOT mark defaulters; strain and spend rigidity weakly do |
| liabilities/ | 1.0.0 | CRC exposure, product mix, timeline, defaults, guarantor exposure | median 26k debt, 498 EUR/month installments; 93 with some default |
| incomes/ | 1.0.0 | IRS, salary, SS, self-employment, pension, cross-source coherence | 12 with zero verifiable income; salary/IRS coherence ratio surfaces joint declarations |
| completeness/ | 1.2.0 | core presence, SS gate, series integrity, consistency flags, analysis readiness, extraction telemetry (v1.2.0) | SS gate cause MEASURED: 329 of 338 closed gates = services never invoked (collection scope); 484 = no-data-exists; 45 proponents need refetch |
| employment/ | 1.0.0 | tenure, employer status, salary growth/continuity, terminations | 71 with main employer no longer active; 86 terminations in last 24m |
| adverse/ | 1.0.0 | certificates, executions, role-resolved insolvencies, public debts | 57 (10.1%) with markers; adverse and CRC defaults are complementary channels (47 vs 83 non-overlap) |
| banking/ | 1.0.0 | account mix, relationship age, institution spread, recent openings; only open accounts visible | median relationship 13.8 years; 207 with savings, 165 with investments; 471 opened credit facilities in last 12m |
| affordability/ | 1.3.0 | synthesis: income basis, commitments incl. rent, expenses floor, residual; proponent_profile() and the unified pt-PT report (SEMÁFORO block + colored section headers) | median residual -177 EUR (60% negative): read with the household-vs-individual basis caveat |
| semaforo/ | 1.0.0 | per-section triage colors: absolute hard rules + population-relative P75/P90 cuts (frozen benchmarks); reasons in pt-PT; CINZENTO never penalizes gated absence | every section discriminates: e.g. síntese 217/256/75/17 (V/A/V/C); no aggregate color by design |

## Next steps (recommended order)

1. **Beta integration**: the analyst-facing product exists in
   proponent_profiles.csv; engineering wires the six modules into serving
   (each is a stdlib-only function snapshot -> vector + text) and adds the
   structured feedback capture (per-case agree/disagree), which accumulates
   the labeled data every model below is starved of.
2. **Supervised risk model, gated on data**: needs a few thousand
   proponents, 200+ defaults, point-in-time CRC re-extraction, out-of-time
   validation. Re-run notebook section 6 of expenses/ when the gates are met.

## Standing constraints

- No automated credit decisioning until the data gates in step 2 are met
  (expenses/FEATURES_SPEC.md and expenses_model.ipynb section 6 document why).
- Missingness must not be used as a risk signal (completeness spec,
  "Measured meaning of absence": AUC 0.51-0.53).
- Adverse markers are hard rules with manual verification for `flagged`
  insolvencies, never statistical features (adverse spec).
- The CRC history in data_full.csv is corrupted for pulls created before
  2026-08-07 (current CRC copied into historical slots); any point-in-time
  work needs re-extraction first.
