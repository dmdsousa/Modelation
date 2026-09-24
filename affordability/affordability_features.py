"""Affordability synthesis from a hAPI proponent snapshot.

The seventh package joins the six sibling vectors (completeness, adverse,
incomes, employment, liabilities, expenses) into the affordability story:
best-available monthly income, contractual commitments (debt service + rent),
the invoiced-expenses floor, and what remains.

Layer 1 (`affordability_features`): the synthesis vector. It computes nothing
the siblings already compute; it selects, combines, and derives ratios,
carrying explicit basis/quality fields so no number hides its provenance.
`proponent_profile` returns all seven vectors; `render_full_report` produces
the complete pt-PT analysis (synthesis first, then each package's text).

Income basis (priority order, recorded in `income_basis`):
1. salary_net: 6-month average net salary (verified, monthly, proponent-only)
2. ss_regular: Social Security regular-income 6-month average
3. irs_gross: IRS annual / 12 (GROSS and household-wide: ratios on this basis
   are not comparable to net-based ones; the field says which basis is live)

Rent: RenterContractList contracts are tenant contracts (verified: the
proponent's PersonalTaxData.Nif appears in RenterList for all 135 contracts
in data_full.csv; note the list NIFs do NOT match PersonalData.NIF, which
uses a different encoding). Active monthly contracts are summed.

Residual income = income - debt service - rent - invoiced expenses floor.
Still optimistic: utilities and non-invoiced spend remain unobserved.

Stdlib only.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _sib in ("expenses", "liabilities", "incomes", "completeness",
             "employment", "adverse", "banking", "semaforo"):
    _p = os.path.join(_HERE, "..", _sib)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adverse_features import adverse_features                    # noqa: E402
from adverse_features import render_profile_text as _t_adverse   # noqa: E402
from banking_features import banking_features                    # noqa: E402
from banking_features import render_profile_text as _t_bank      # noqa: E402
from completeness_features import completeness_features          # noqa: E402
from completeness_features import render_profile_text as _t_comp  # noqa: E402
from employment_features import employment_features              # noqa: E402
from employment_features import render_profile_text as _t_empl   # noqa: E402
from expenses_features import behaviour_features                 # noqa: E402
from expenses_features import render_profile_text as _t_exp      # noqa: E402
from incomes_features import income_features                     # noqa: E402
from incomes_features import render_profile_text as _t_inc       # noqa: E402
from liabilities_features import liability_features              # noqa: E402
from liabilities_features import render_profile_text as _t_liab  # noqa: E402
from semaforo_features import semaforo, semaforo_features         # noqa: E402
from semaforo_features import render_semaforo_text                # noqa: E402

FEATURES_VERSION = "1.4.0"


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def affordability_features(profile, vectors=None):
    """Synthesis vector. `vectors` may pass precomputed sibling vectors
    ({'completeness':..., 'incomes':..., ...}) to avoid recomputation."""
    v = vectors or {}
    comp = v.get("completeness") or completeness_features(profile)
    inc = v.get("incomes") or income_features(profile)
    liab = v.get("liabilities") or liability_features(profile)
    exp = v.get("expenses") or behaviour_features(profile)
    adv = v.get("adverse") or adverse_features(profile)
    empl = v.get("employment") or employment_features(profile)

    out = {"features_version": FEATURES_VERSION}

    # ---------- income: best available basis ----------
    if inc["avg_net_salary_6m"]:
        income, basis = inc["avg_net_salary_6m"], "salary_net"
    elif inc["avg_regular_income_6m"]:
        income, basis = inc["avg_regular_income_6m"], "ss_regular"
    elif inc["monthly_income_irs"]:
        income, basis = inc["monthly_income_irs"], "irs_gross"
    else:
        income, basis = None, "none"
    out["monthly_income"] = _round(income)
    out["income_basis"] = basis

    # ---------- commitments and floor ----------
    debt_service = liab["total_installment"]
    out["debt_service"] = debt_service
    # rent is owned by the expenses package (v1.1.0+); carried through here
    rent = exp["rent_monthly"]
    out["rent_monthly"] = rent
    out["n_active_rent_contracts"] = exp["n_active_rent_contracts"]
    out["rent_purpose"] = exp["rent_purpose"]
    out["expenses_floor"] = exp["monthly_expenses"]

    committed = (debt_service or 0) + (rent or 0)
    out["committed_outgoings"] = _round(committed)

    # ---------- ratios ----------
    if income and income > 0:
        out["dsti"] = _round((debt_service or 0) / income, 3)
        out["effort_rate"] = _round(committed / income, 3)
        out["rent_to_income"] = (_round(rent / income, 3)
                                 if rent is not None else None)
        floor = out["expenses_floor"]
        if floor is not None:
            outgoings = committed + floor
            out["total_outgoings_floor"] = _round(outgoings)
            out["residual_income"] = _round(income - outgoings)
            out["residual_ratio"] = _round((income - outgoings) / income, 3)
            out["burden_ratio"] = _round(outgoings / income, 3)
        else:
            for f in ("total_outgoings_floor", "residual_income",
                      "residual_ratio", "burden_ratio"):
                out[f] = None
    else:
        for f in ("dsti", "effort_rate", "rent_to_income",
                  "total_outgoings_floor", "residual_income",
                  "residual_ratio", "burden_ratio"):
            out[f] = None

    # ---------- carried context (provenance stays in the siblings) ----------
    out["income_verification"] = comp["income_verification"]
    out["can_full_affordability"] = comp["can_full_affordability"]
    out["n_consistency_flags"] = comp["n_consistency_flags"]
    out["any_adverse"] = adv["any_adverse"]
    out["adverse_markers"] = adv["adverse_markers"]
    out["in_default_now"] = int((liab["n_in_default"] or 0) > 0)
    out["guarantor_exposure"] = liab["guarantor_exposure"]
    out["expenses_cv"] = exp["monthly_cv"]
    out["employer_active"] = empl["employer_active"]
    out["tenure_months"] = empl["tenure_months"]
    # household: decisive context for reading the ratios
    out["irs_is_joint"] = inc["irs_is_joint"]
    out["n_dependents"] = exp["n_dependents"]
    return out


HEADLINE_FIELDS = [
    "monthly_income", "income_basis", "debt_service", "rent_monthly",
    "expenses_floor", "dsti", "effort_rate", "burden_ratio",
    "residual_income", "irs_is_joint", "n_dependents",
    "income_verification", "any_adverse", "in_default_now",
    "n_consistency_flags",
]

CAVEATS = {
    "income_basis": "salary_net = média líquida 6 meses (verificada); "
                    "ss_regular = rendimento regular Seg. Social; irs_gross = "
                    "IRS anual/12, BRUTO e do agregado: rácios nesta base não "
                    "são comparáveis aos de base líquida.",
    "expenses_floor": "Despesa faturada (e-fatura): exclui contas de serviços "
                      "e consumo não faturado. O residual real é inferior.",
    "rent_monthly": "Contratos de arrendamento ativos como inquilino "
                    "(papel verificado nos contratos).",
    "residual_income": "rendimento - prestações - renda - piso de despesas. "
                       "Otimista pela natureza de piso das despesas.",
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
    return "n/d" if value is None else f"{value:,.0f}".replace(",", ".") + " EUR"


BASIS_PT = {
    "salary_net": "salário líquido, média 6 meses",
    "ss_regular": "rendimento regular Seg. Social, média 6 meses",
    "irs_gross": "IRS anual/12, BRUTO e do agregado",
    "none": "sem base de rendimento",
}


def render_profile_text(features):
    """Plain-text affordability synthesis for humans (pt-PT)."""
    f = features
    lines = []

    if f["monthly_income"] is None:
        lines.append("Não é possível avaliar a capacidade financeira: sem "
                     "rendimento verificável em nenhuma fonte.")
    elif f["residual_income"] is None:
        lines.append(f"Rendimento {_eur(f['monthly_income'])}/mês "
                     f"({BASIS_PT[f['income_basis']]}); avaliação incompleta: "
                     "sem dados de despesas.")
    else:
        neg = f["residual_income"] < 0
        base = (f"Rendimento {_eur(f['monthly_income'])}/mês "
                f"({BASIS_PT[f['income_basis']]}). ")
        if neg:
            base += ("Os gastos conhecidos (créditos, renda e despesas com "
                     "fatura) JÁ ULTRAPASSAM o rendimento em "
                     f"{_eur(-f['residual_income'])}/mês.")
        else:
            base += ("Depois de pagar créditos, renda e as despesas "
                     "comprovadas por fatura, sobram no máximo "
                     f"{_eur(f['residual_income'])}/mês "
                     f"({f['residual_ratio']:.0%} do rendimento).")
        lines.append(base)
    warn = []
    if f["any_adverse"]:
        warn.append("registos adversos")
    if f["in_default_now"]:
        warn.append("incumprimento ativo na CRC")
    if warn:
        lines[-1] += " ATENÇÃO: " + " e ".join(warn) + "."
    lines.append("")

    lines.append(f"  Rendimento       {_eur(f['monthly_income'])}/mês "
                 f"({BASIS_PT[f['income_basis']]})")
    if f["irs_is_joint"] is not None:
        agregado = ("declaração conjunta (2 titulares)" if f["irs_is_joint"]
                    else "titular único")
        nd = f["n_dependents"] or 0
        agregado += (", sem dependentes" if nd == 0 else
                     f", {nd} dependente" + ("s" if nd > 1 else ""))
        lines.append(f"  Agregado         {agregado}")
    ds = f"  Créditos         {_eur(f['debt_service'])}/mês em prestações"
    if f["dsti"] is not None:
        ds += f", ou seja {f['dsti']:.0%} do rendimento (DSTI)"
    lines.append(ds)
    if f["rent_monthly"] is not None:
        rt = f"  Renda            {_eur(f['rent_monthly'])}/mês"
        if f["rent_to_income"] is not None:
            rt += f" ({f['rent_to_income']:.0%} do rendimento)"
        lines.append(rt)
    if f["effort_rate"] is not None:
        lines.append(f"  Taxa de esforço  {f['effort_rate']:.0%} do rendimento "
                     "em compromissos contratuais (créditos + renda)")
    if f["expenses_floor"] is not None:
        lines.append(f"  Despesas         pelo menos "
                     f"{_eur(f['expenses_floor'])}/mês (conta apenas o que "
                     "tem fatura)")
    if f["burden_ratio"] is not None:
        if f["residual_income"] < 0:
            concl = (f"os gastos conhecidos são {f['burden_ratio']:.0%} do "
                     "rendimento: o orçamento não fecha com os dados "
                     "visíveis")
        else:
            concl = (f"os gastos conhecidos consomem {f['burden_ratio']:.0%} "
                     f"do rendimento; sobram no máximo "
                     f"{_eur(f['residual_income'])}/mês")
        lines.append(f"  Conclusão        {concl}")
    if f["guarantor_exposure"]:
        lines.append(f"  Aval a terceiros {_eur(f['guarantor_exposure'])} "
                     "que a pessoa terá de pagar SE o devedor principal "
                     "falhar (não contado acima)")
    lines.append("")
    lines.append("  Como ler: as despesas contam só o que foi comunicado ao "
                 "e-fatura (prestações de crédito, transferências e compras "
                 "sem fatura ficam de fora), por isso o que sobra na "
                 "realidade é MENOS do que o indicado. E atenção à fonte do "
                 "rendimento: salário líquido individual e IRS bruto do "
                 "agregado dão percentagens que não se podem comparar "
                 "diretamente entre pessoas.")
    return "\n".join(lines)


SECTION_ORDER = [
    ("DADOS", "completeness", _t_comp, completeness_features),
    ("REGISTOS ADVERSOS", "adverse", _t_adverse, adverse_features),
    ("RENDIMENTO", "incomes", _t_inc, income_features),
    ("EMPREGO", "employment", _t_empl, employment_features),
    ("RESPONSABILIDADES", "liabilities", _t_liab, liability_features),
    ("BANCA", "banking", _t_bank, banking_features),
    ("DESPESAS", "expenses", _t_exp, behaviour_features),
]


SEMAFORO_KEY = {"SÍNTESE (AFFORDABILITY)": "sintese", "DADOS": "dados",
                "REGISTOS ADVERSOS": "adversos", "RENDIMENTO": "rendimento",
                "EMPREGO": "emprego", "RESPONSABILIDADES": "responsabilidades",
                "BANCA": "banca", "DESPESAS": "despesas"}


def proponent_profile(profile):
    """All package vectors for one snapshot, plus the semaforo."""
    vectors = {name: build(profile)
               for _, name, _, build in SECTION_ORDER}
    vectors["affordability"] = affordability_features(profile, vectors)
    vectors["semaforo"] = semaforo_features(vectors)
    return vectors


def render_full_report(profile, vectors=None):
    """The complete pt-PT analysis: semaforo, synthesis, then each package."""
    v = vectors or proponent_profile(profile)
    st = semaforo({k: v[k] for k in v if k != "semaforo"})
    parts = ["================ SEMÁFORO ================",
             render_semaforo_text(st, {k: v[k] for k in v
                                       if k != "semaforo"}),
             "================ SÍNTESE (AFFORDABILITY): "
             f"{st['sintese']['cor']} ================",
             render_profile_text(v["affordability"])]
    for title, name, render, _ in SECTION_ORDER:
        cor = st[SEMAFORO_KEY[title]]["cor"]
        parts.append(f"================ {title}: {cor} ================")
        parts.append(render(v[name]))
    return "\n\n".join(parts)


if __name__ == "__main__":
    import csv
    import json

    path = sys.argv[1] if len(sys.argv) > 1 else "../data/data_full.csv"
    csv.field_size_limit(sys.maxsize)
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            print(render_full_report(json.loads(row["value"])))
            break
