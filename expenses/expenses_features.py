"""Expenses behaviour features from a hAPI proponent snapshot.

Layer 1 (`behaviour_features`): the full, versioned feature vector.
Consumers: the credit score model (as input features) and layer 2.
Layer 2 (`display_profile`): the client/analyst-facing projection.

Input: the parsed snapshot JSON (the `value` document of a proponent),
as captured at application time. No other data source is touched, so the
vector is point-in-time by construction.

Conventions:
- Missing/uncomputable values are None, never 0. Presence flags say why.
- Monetary values are EUR. Monthly figures are per calendar month.
- The observation window is the receipt months minus the first and the
  last month (both partial: the window starts at the first receipt and
  ends at snapshot creation mid-month; keeping them would deflate edge
  months and inflate volatility).

Stdlib only. Logic validated against expenses_model.ipynb (sections 4-6).
"""

import math
from statistics import stdev

FEATURES_VERSION = "1.1.0"

ONE_OFF_EUR = 1000.0
MIN_OBS_MONTHS = 3
COUPLE = {"Casado", "Unido de facto"}
MORTGAGE = "Crédito à habitação"

SECTOR_MAP = {
    "Alojamento, restauração e similares": "food_dining",
    "Saúde": "health",
    "Atividades veterinárias": "health",
    "Ginásios": "health",
    "Lares": "health",
    "Manutenção e reparação de veículos automóveis": "transport",
    "Manutenção e reparação de motociclos, de suas peças e acessórios": "transport",
    "Aquisição de passes mensais ou de bilhetes para utilização de "
    "transportes públicos coletivos": "transport",
    "Educação": "education",
    "Comércio a retalho de livros": "education",
    "Jornais e Revistas": "education",
    "Atividades de salões de cabeleireiro e institutos de beleza": "personal_care",
    "Imóveis": "housing",
    "Atividades artísticas e literárias": "leisure",
}
CATEGORIES = ["food_dining", "health", "transport", "education", "housing",
              "personal_care", "leisure", "other_retail", "uncategorized"]

# expected_expenses model: Ridge on log(monthly_expenses), frozen 2026-08-13,
# trained on 562 proponents (data_full.csv). See notebook section 5.
EXPECTED_MODEL = {
    "features": ["irs_income", "crc_total_installment", "crc_has_mortgage",
                 "is_couple", "age"],
    "impute_medians": {"irs_income": 16657.51, "crc_total_installment": 499.16,
                       "crc_has_mortgage": 0.0, "is_couple": 0.0, "age": 37.0},
    "scale_means": {"irs_income": 21731.42032, "crc_total_installment": 585.845071,
                    "crc_has_mortgage": 0.160142, "is_couple": 0.325623,
                    "age": 38.352313},
    "scale_stds": {"irs_income": 16398.635662, "crc_total_installment": 448.072258,
                   "crc_has_mortgage": 0.366738, "is_couple": 0.468607,
                   "age": 11.77852},
    "coefs": {"irs_income": 0.146074, "crc_total_installment": 0.280072,
              "crc_has_mortgage": 0.022246, "is_couple": -0.03387,
              "age": 0.048917},
    "intercept": 6.656954,
}


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _month_index(iso_date):
    """'2025-08-02T...' -> 2025*12 + 7 (integer month index)."""
    return int(iso_date[:4]) * 12 + int(iso_date[5:7]) - 1


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def _expected_expenses(vector):
    m = EXPECTED_MODEL
    z = 0.0
    for f in m["features"]:
        v = vector.get(f)
        if v is None:
            v = m["impute_medians"][f]
        z += m["coefs"][f] * (v - m["scale_means"][f]) / m["scale_stds"][f]
    return math.exp(m["intercept"] + z)


def behaviour_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}

    # --- capacity / household (independent of receipts) ---
    cur = profile.get("IRSTaxDeclarationDetails") or {}
    prev = profile.get("IRSTaxDeclarationDetailsPreviousYear") or {}
    irs = _dig(cur, "Total", "Income")
    income_source = "current_declaration"
    if irs is None:
        irs = _dig(prev, "Total", "Income")
        income_source = "previous_declaration" if irs is not None else "missing"
    if irs is not None and irs < 1:
        # zero or sub-1-EUR annual declarations are data artifacts, not income
        irs, income_source = None, "missing"
    marital = cur.get("MaritalStatus") or prev.get("MaritalStatus")
    liabs = _dig(profile, "CRCData", "Liabilities") or []

    out["irs_income"] = _round(irs)
    out["income_source"] = income_source
    out["monthly_income"] = _round(irs / 12) if irs else None
    out["n_dependents"] = len(cur.get("Dependents") or [])
    out["is_couple"] = None if marital is None else int(marital in COUPLE)
    out["age"] = _dig(profile, "PersonalTaxData", "BirthDate")
    out["crc_total_installment"] = _round(sum((liab.get("Installment") or 0) for liab in liabs))
    out["crc_n_active"] = sum(1 for liab in liabs if (liab.get("TotalDebt") or 0) > 0)
    out["crc_has_mortgage"] = int(any(liab.get("Product") == MORTGAGE for liab in liabs))
    out["is_renter"] = int(bool(profile.get("RenterContractList")))

    # --- spend behaviour from e-fatura receipts ---
    receipts = profile.get("ExpensesList") or []
    spend_fields = ["window_start", "window_end", "months_observed", "receipts_count",
                    "kept_total", "monthly_expenses", "monthly_std", "monthly_cv",
                    "expenses_over_1000_count", "expenses_over_1000_total",
                    "expenses_over_1000_share"] + [f"share_{c}" for c in CATEGORIES]
    for f in spend_fields:
        out[f] = None
    out["has_spend_data"] = 0

    parsed = [(_month_index(r["IssuanceDate"]), float(r["Amount"]), r.get("Sector"))
              for r in receipts if r.get("IssuanceDate") and r.get("Amount") is not None]
    if parsed:
        lo, hi = min(m for m, _, _ in parsed), max(m for m, _, _ in parsed)
        start, end = lo + 1, hi - 1  # drop partial edge months
        window = [(m, a, s) for m, a, s in parsed if start <= m <= end]
        n_months = end - start + 1
        if n_months >= MIN_OBS_MONTHS and window:
            kept = [(m, a, s) for m, a, s in window if a < ONE_OFF_EUR]
            over = [a for _, a, _ in window if a >= ONE_OFF_EUR]
            kept_total = sum(a for _, a, _ in kept)
            window_total = kept_total + sum(over)
            monthly = kept_total / n_months

            by_month = {m: 0.0 for m in range(start, end + 1)}
            for m, a, _ in kept:
                by_month[m] += a
            m_std = stdev(by_month.values()) if len(by_month) > 1 else None

            out["window_start"] = f"{start // 12:04d}-{start % 12 + 1:02d}"
            out["window_end"] = f"{end // 12:04d}-{end % 12 + 1:02d}"
            out["months_observed"] = n_months
            out["receipts_count"] = len(window)
            out["kept_total"] = _round(kept_total)
            out["monthly_expenses"] = _round(monthly)
            out["monthly_std"] = _round(m_std)
            out["monthly_cv"] = _round(m_std / monthly, 3) if m_std is not None and monthly > 0 else None
            out["expenses_over_1000_count"] = len(over)
            out["expenses_over_1000_total"] = _round(sum(over))
            out["expenses_over_1000_share"] = (
                _round(sum(over) / window_total, 4) if window_total > 0 else None)
            out["has_spend_data"] = 1

            by_cat = {c: 0.0 for c in CATEGORIES}
            for _, a, s in kept:
                cat = "uncategorized" if s is None else SECTOR_MAP.get(s, "other_retail")
                by_cat[cat] += a
            for c in CATEGORIES:
                out[f"share_{c}"] = _round(by_cat[c] / kept_total, 4) if kept_total > 0 else None

    # --- housing: rent from active tenant contracts (owner: this package) ---
    # RenterContractList entries are tenant contracts (role verified via
    # PersonalTaxData.Nif in RenterList, 135/135 in data_full.csv). Active =
    # monthly frequency and not ended before the last receipt month.
    anchor = out["window_end"]
    if anchor is None:
        crc_doc = _dig(profile, "CRCData", "DocumentDate")
        anchor = crc_doc[:7] if crc_doc else None
    rent_total, n_rent, rent_purpose = 0.0, 0, None
    for c in profile.get("RenterContractList") or []:
        if c.get("Frequency") != "Mensal" or not c.get("ContractValue"):
            continue
        end = (c.get("EndDate") or "")[:7]
        if end and anchor and end < anchor:
            continue
        rent_total += c["ContractValue"]
        n_rent += 1
        rent_purpose = rent_purpose or c.get("Purpose")
    out["rent_monthly"] = _round(rent_total) if n_rent else None
    out["n_active_rent_contracts"] = n_rent or None
    out["rent_purpose"] = rent_purpose
    out["monthly_expenses_incl_rent"] = (
        _round(out["monthly_expenses"] + (out["rent_monthly"] or 0))
        if out["monthly_expenses"] is not None else None)

    # --- model-derived and ratio features ---
    out["expected_expenses"] = _round(_expected_expenses(out))
    me, mi = out["monthly_expenses"], out["monthly_income"]
    inst = out["crc_total_installment"]
    out["overspend_ratio"] = (
        _round(me / out["expected_expenses"], 3)
        if me is not None and out["expected_expenses"] else None)
    out["dsti"] = _round(inst / mi, 3) if mi else None
    out["eti"] = _round(me / mi, 3) if mi and me is not None else None
    out["residual_income"] = _round(mi - inst - me) if mi and me is not None else None
    return out


HEADLINE_FIELDS = [
    "monthly_expenses", "monthly_income", "crc_total_installment",
    "dsti", "eti", "residual_income", "monthly_cv", "expenses_over_1000_total",
    "months_observed", "receipts_count", "income_source",
]

CAVEATS = {
    "monthly_expenses": "Invoiced spend only (e-fatura). Excludes rent, most "
                        "utilities and loan payments. Read as a floor.",
    "monthly_income": "Latest IRS annual declaration / 12. May lag reality.",
    "residual_income": "monthly_income - installments - monthly_expenses. "
                       "Negative = no visible margin.",
    "monthly_cv": "Month-to-month swing as a share of the average. Low = every "
                  "month equally committed (rigidity), high = lumpy/discretionary.",
}


def display_profile(features):
    """Layer-2 projection: headline block, detail block, caveats."""
    detail_fields = [k for k in features
                     if k not in HEADLINE_FIELDS and k != "features_version"]
    return {
        "headline": {k: features[k] for k in HEADLINE_FIELDS},
        "detail": {k: features[k] for k in detail_fields},
        "caveats": CAVEATS,
        "features_version": features["features_version"],
    }


def _eur(value):
    """PT-formatted amount: 1.475 EUR (dot as thousands separator)."""
    return "n/d" if value is None else f"{value:,.0f}".replace(",", ".") + " EUR"


def _n(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


INCOME_SOURCE_PT = {
    "current_declaration": "declaração atual",
    "previous_declaration": "declaração anterior",
    "missing": "em falta",
}


def render_profile_text(features):
    """Plain-text rendering of the profile for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field; thresholds for
    wording (rígida/típica/irregular) come from the population quartiles
    measured in the research notebook. No judgment words, no score.
    """
    me = features["monthly_expenses"]
    lines = []

    # Spending only: income, DSTI and what remains live in the affordability
    # synthesis, which owns the income-basis choice. Keeping them here too
    # produced two contradictory affordability readings in one report.
    if me is not None:
        cv = features["monthly_cv"]
        head = (f"Despesas comprovadas por fatura: pelo menos {_eur(me)}/mês"
                + (f", com variação mensal de {cv:.0%} em torno da média"
                   if cv is not None else "") + ".")
        lines.append(head)
    else:
        lines.append("Sem dados de e-fatura para avaliar as despesas.")
    lines.append("")

    if features["has_spend_data"]:
        lines.append(f"  Despesas          pelo menos {_eur(me)}/mês "
                     f"(apenas o que tem fatura), medido em "
                     f"{_n(features['months_observed'], 'mês', 'meses')}, "
                     f"{_n(features['receipts_count'], 'fatura', 'faturas')}")
    if features["rent_monthly"] is not None:
        lines.append(f"  Renda (contrato)  {_eur(features['rent_monthly'])}"
                     f"/mês em "
                     + _n(features["n_active_rent_contracts"],
                          "contrato ativo", "contratos ativos"))
        if features["monthly_expenses_incl_rent"] is not None:
            lines.append(f"  Total com renda   pelo menos "
                         f"{_eur(features['monthly_expenses_incl_rent'])}/mês")
    cv = features["monthly_cv"]
    if cv is not None:
        word = "rígida" if cv < 0.35 else ("típica" if cv < 0.6 else "irregular")
        lines.append(f"  Volatilidade      {cv:.2f} ({word})")
    if features["expenses_over_1000_total"]:
        lines.append(f"  Compras avultadas {_eur(features['expenses_over_1000_total'])} "
                     f"no total ({_n(features['expenses_over_1000_count'], 'fatura', 'faturas')} "
                     ">= 1.000 EUR)")
    lines.append("")
    lines.append("  Como ler: só conta despesa com fatura (e-fatura); a renda "
                 "aparece em linha própria quando há contrato registado; "
                 "contas de serviços e prestações de crédito ficam de fora, "
                 "pelo que o gasto real é superior ao indicado.")
    return "\n".join(lines)


if __name__ == "__main__":
    import csv
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "../data/data_full.csv"
    csv.field_size_limit(sys.maxsize)
    with open(path, newline="") as fh:
        seen = set()
        for row in csv.DictReader(fh):
            if row["uuid"] in seen:
                continue
            seen.add(row["uuid"])
            if len(seen) > 3:
                break
            vec = behaviour_features(json.loads(row["value"]))
            print(f"--- {row['uuid'][:8]} ---")
            print(json.dumps(display_profile(vec)["headline"], indent=2))
