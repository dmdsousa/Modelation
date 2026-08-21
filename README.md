# Modelation

Feature packages over hAPI proponent snapshots for credit analysis. Each
package reads the raw snapshot JSON (the `value` document captured at
application time) and produces a **layer 1** versioned feature vector (for
the future credit score model) and a **layer 2** human-readable analysis in
pt-PT (for analysts, via the beta). The affordability package joins them all
into one `full_report` per proponent.

## Packages

| package | module | what it measures |
|---|---|---|
| `expenses/` | `expenses_features.py` | recurring monthly spend from e-fatura, expected-expenses model, behaviour metrics, rent from tenant contracts |
| `liabilities/` | `liabilities_features.py` | CRC exposure, product mix, timeline, defaults, guarantor exposure |
| `incomes/` | `incomes_features.py` | IRS, salary, Social Security, self-employment, pension, cross-source coherence |
| `completeness/` | `completeness_features.py` | core presence, the SS data gate, series integrity, consistency flags, extraction telemetry, analysis readiness |
| `employment/` | `employment_features.py` | tenure, employer status, salary growth and continuity, terminations |
| `adverse/` | `adverse_features.py` | debt certificates, executions, role-resolved insolvencies, public debts (scorecard hard rules) |
| `banking/` | `banking_features.py` | account mix, relationship age, institution spread, recent openings |
| `affordability/` | `affordability_features.py` | synthesis: income basis, commitments, expenses floor, residual; `proponent_profile()` and `render_full_report()` |

Every package ships: the stdlib-only module, a `*_SPEC.md` engineering
contract (field definitions, rules, validation record), and an analysis
notebook (`*_analysis.ipynb`; `expenses/expenses_model.ipynb` is the original
research record). All numeric fields were validated against independent
recomputations with zero mismatches; see each spec's Validation section.

## Layout

```
Modelation/
├── data/                 raw extractions (gitignored, see below)
├── <package>/            module + spec + notebook per package
├── ROADMAP.md            shipped work, next steps, standing constraints
└── proponent_profiles.csv  combined per-proponent output (gitignored)
```

## Data setup (nothing in git)

No CSV enters the repository (`.gitignore` blocks `data/` and `*.csv`):
raw extractions and every generated per-proponent CSV contain personal
financial records. To work locally, place the extraction export at:

```
data/data_full.csv    # columns: uuid, value (snapshot JSON), created, ... 
```

Notebook outputs are cleared before committing (they embed real data);
re-run any notebook to regenerate them.

## Usage

Modules are dependency-free Python (stdlib only); notebooks additionally use
pandas, scikit-learn and matplotlib (Python 3.11+).

```python
import json, sys
sys.path.insert(0, "affordability")
from affordability_features import proponent_profile, render_full_report

profile = json.loads(snapshot_value_json)
vectors = proponent_profile(profile)     # all package vectors, keyed by name
print(render_full_report(profile, vectors))  # the complete pt-PT analysis
```

## Constraints (read before modeling)

See `ROADMAP.md`: no automated credit decisioning until the data gates are
met; missingness is not a risk signal; adverse markers are hard rules with
manual verification; the historical CRC in the current extraction is
corrupted for pulls created before 2026-08-07 and needs re-extraction before
any point-in-time work.
