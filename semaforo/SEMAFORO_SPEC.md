# Semáforo v1.0.0

Contract for the per-section triage colors over the package vectors.
Reference implementation: `semaforo_features.py` (stdlib-only Python).
Consumed by `affordability/render_full_report()` (SEMÁFORO block at the top
of every report plus the color in each section header).

## What it is, and is not

A **triage** aid for analysts: VERDE = nothing needs attention in this
block, AMARELO = review before deciding, VERMELHO = critical attention (a
hard rule fired or the proponent sits at the population extreme), CINZENTO =
no data to assess (**never penalizes**: the SS gate is a collection-scope
artifact, see the completeness spec). It is NOT a credit score, NOT a
probability, NOT an approve/reject recommendation: without outcome data the
rules are policy and relative position, not default statistics. Every color
ships with its reasons in pt-PT, each traceable to a layer-1 field.

## Two rule families

1. **Absolute**: color independent of the population: confirmed adverse
   markers, active CRC default or litigation, employer company inactive,
   incomplete data core, technical fetch failures.
2. **Population-relative** ("compara com o resto dos dados"): continuous
   metrics cut at the reference population's P75 (AMARELO) and P90
   (VERMELHO), frozen in `BENCHMARKS` (data_full.csv, 565 proponents,
   2026-09-15). Recalibrating against a new reference population bumps
   `FEATURES_VERSION`.

Calibration note that motivated the relative design: this population's
median burden is 113% of income and median DSTI 37% (household-expenses vs
individual-income artifact, see the affordability spec), so classic absolute
thresholds would mark most proponents red and triage nothing. Hence: a
common negative residual is AMARELO; VERMELHO is reserved for the P90
extreme.

## Rules per section

| section | VERMELHO | AMARELO | CINZENTO |
|---|---|---|---|
| SÍNTESE | burden >= P90 (2.46) or DSTI >= P90 (0.83) | residual < 0; DSTI >= P75 (0.57) | residual not computable |
| DADOS | core incomplete; technical fetch failure; income-none suspect gap | any consistency flag (79% of population has none) | never |
| ADVERSOS | any confirmed marker (certificates, executions, confirmed insolvency, public debts) | flagged-unconfirmed insolvency (manual check) | never |
| RENDIMENTO | no verifiable income | IRS-only; YoY drop <= P10 (-20%); variable share >= P90 (21%) | never |
| EMPREGO | employer company not active | tenure <= P25 (9m); termination in 24m; salary-series holes >= 2 | no employment data (SS gate) |
| RESPONSABILIDADES | active default; litigation | revolving share >= P75 (25%); >= 5 credits opened in 12m (P90); guarantor exposure | never |
| BANCA | never (no balances: no honest red) | >= 5 credit openings in 12m (P90) | no titular accounts |
| DESPESAS | never alone (level only means something vs income: SÍNTESE) | cv >= P90 (0.88); level >= P90 (1,841 EUR); < 6 observed months | no e-fatura |

## API and fields

- `semaforo(vectors)` -> `{section: {cor, razoes[]}}` (vectors from
  `proponent_profile`).
- `semaforo_features(vectors)` -> flat vector for CSV/serving:
  `<section>_cor`, `<section>_razoes` (joined pt-PT reasons), plus
  `n_vermelhos`, `n_amarelos`. **No aggregate color**: mixing data-quality
  colors (DADOS) with risk colors (ADVERSOS) in one light hides more than it
  shows; the block itself is the summary.
- `render_semaforo_text(statuses)` -> the pt-PT block.

## Population distribution (data_full.csv, 565)

| section | VERDE | AMARELO | VERMELHO | CINZENTO |
|---|---|---|---|---|
| sintese | 217 | 256 | 75 | 17 |
| dados | 407 | 95 | 63 | 0 |
| adversos | 508 | 8 | 49 | 0 |
| rendimento | 192 | 358 | 15 | 0 |
| emprego | 85 | 73 | 71 | 336 |
| responsabilidades | 287 | 185 | 93 | 0 |
| banca | 466 | 90 | 0 | 9 |
| despesas | 451 | 111 | 0 | 3 |

Every section discriminates; gray appears only where data is gated.

## Versioning policy

Semver; any rule, threshold, or benchmark change bumps `FEATURES_VERSION`;
consumers pin. Benchmarks must be recomputed when the reference population
changes materially (new extraction waves).

## Validation

1,788 independent rule re-derivations across all 565 proponents (adversos,
síntese, emprego, responsabilidades hard rules and thresholds): zero
mismatches.

## Known limitations

1. Thresholds are policy/relative, not outcome-calibrated: revisit when the
   supervised-model data gates open (ROADMAP).
2. P75/P90 cuts inherit the reference population's biases (recent credit
   applicants; household-vs-individual measurement artifact).
3. DSTI 36%/50% regulatory-style absolute cuts were deliberately NOT used
   (they would flood red here); if credit policy requires them, they belong
   in a separate policy layer, not in this triage.
