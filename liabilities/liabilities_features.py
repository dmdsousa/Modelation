"""Liabilities behaviour features from a hAPI proponent snapshot.

Layer 1 (`liability_features`): the full, versioned feature vector computed
from `CRCData` (Banco de Portugal credit register) in the snapshot.
Consumers: the credit score model (as input features) and layer 2.
Layer 2 (`display_profile` / `render_profile_text`): the client/analyst view.

Input: the parsed snapshot JSON (the `value` document of a proponent), as
captured at application time. Only `CRCData` is read, so the vector is
point-in-time by construction (the register state at `CRCData.DocumentDate`,
which is the vector's reference date).

Conventions:
- Missing/uncomputable values are None, never 0. Presence flags say why.
- Monetary values are EUR; `total_installment` is EUR/month.
- Totals (debt, installments, potential, defaults) cover only entries where
  the proponent is the debtor ("Devedor"). Guarantor entries
  ("Avalista / fiador") are reported separately as contingent exposure.
- Null `Installment` counts as 0 and is tallied in `n_missing_installment`
  (common on cards/overdrafts, so debt service is understated for
  card-heavy profiles).

Stdlib only. Sibling project: ../expenses/expenses_features.py.
"""

FEATURES_VERSION = "1.0.0"

DEBTOR = "Devedor"
OPEN_ENDED = "9999-12-31"

# Product -> family. Unmapped products fall to "other".
PRODUCT_FAMILY = {
    "Crédito à habitação": "mortgage",
    "Crédito conexo": "mortgage",
    "Crédito pessoal": "personal",
    "Crédito não renovável": "personal",
    "Cartão de crédito": "card",
    "Cartão de crédito - com período de free-float": "card",
    "Cartão de crédito - sem período de free-float": "card",
    "Cartão de crédito - cartão de débito diferido": "card",
    "Crédito automóvel (excluíndo locações financeiras)": "auto",
    "Locação financeira mobiliária": "auto",
    "Crédito renovável - Linha de crédito": "revolving",
    "Crédito renovável - conta corrente bancária": "revolving",
    "Crédito renovável, com exceção de descobertos e cartão de crédito.": "revolving",
    "Ultrapassagens de crédito": "revolving",
    "Facilidades de descoberto": "revolving",
    "Facilidades de descoberto - com domiciliação de ordenado e prazo de "
    "reembolso igual ou inferior a um": "revolving",
    "Facilidades de descoberto - com domiciliação de ordenado e prazo de "
    "reembolso superior a um mês": "revolving",
    "Facilidades de descoberto - sem domiciliação de ordenado e prazo de "
    "reembolso igual ou inferior a um": "revolving",
    "Facilidades de descoberto - sem domiciliação de ordenado e prazo de "
    "reembolso superior a um mês": "revolving",
    "Financiamento à atividade empresarial": "business",
    "Factoring": "business",
    "Confirming": "business",
    "Desconto e outros créditos titulados por efeitos": "business",
    "Outros avales e garantias bancárias prestadas": "guarantee_given",
    "Avales e garantias bancárias prestadas a favor de outras instituições "
    "participantes": "guarantee_given",
}
FAMILIES = ["mortgage", "personal", "card", "auto", "revolving", "business",
            "guarantee_given", "other"]


def _month_index(iso_date):
    """'2021-06-07' or '2021-06-07T...' -> integer month index."""
    return int(iso_date[:4]) * 12 + int(iso_date[5:7]) - 1


def _ym(month_index):
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def liability_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}

    crc = profile.get("CRCData") or {}
    liabs = crc.get("Liabilities") or []
    doc_date = crc.get("DocumentDate") or None
    ref = _month_index(doc_date) if doc_date else None

    out["reference_date"] = doc_date[:10] if doc_date else None
    out["has_crc_data"] = int(bool(liabs))
    out["n_liabilities"] = len(liabs)

    fields = (["n_active", "n_institutions", "total_debt", "total_installment",
               "total_potential", "n_missing_installment", "n_joint",
               "revolving_debt_share", "has_mortgage",
               "oldest_credit_years", "newest_credit_months", "n_opened_12m",
               "latest_maturity_years", "n_open_ended",
               "n_in_default", "total_default", "default_debt_share",
               "first_default", "months_in_default", "any_litigation",
               "guarantor_n", "guarantor_exposure"]
              + [f"debt_{f}" for f in FAMILIES] + [f"n_{f}" for f in FAMILIES])
    for f in fields:
        out[f] = None
    if not liabs:
        return out

    debtor = [liab for liab in liabs if liab.get("ResponsabilityType") == DEBTOR]
    guarantor = [liab for liab in liabs if liab.get("ResponsabilityType") != DEBTOR]

    out["n_active"] = sum(1 for liab in debtor if (liab.get("TotalDebt") or 0) > 0)
    out["n_institutions"] = len({liab.get("InstitutionCode") for liab in debtor
                                 if liab.get("InstitutionCode")})
    total_debt = sum((liab.get("TotalDebt") or 0) for liab in debtor)
    out["total_debt"] = _round(total_debt)
    out["total_installment"] = _round(sum((liab.get("Installment") or 0)
                                          for liab in debtor))
    out["total_potential"] = _round(sum((liab.get("Potential") or 0)
                                        for liab in debtor))
    out["n_missing_installment"] = sum(1 for liab in debtor
                                       if liab.get("Installment") is None)
    out["n_joint"] = sum(1 for liab in debtor if (liab.get("Debtors") or 1) >= 2)

    # product families (debtor entries only)
    fam_debt = {f: 0.0 for f in FAMILIES}
    fam_n = {f: 0 for f in FAMILIES}
    for liab in debtor:
        fam = PRODUCT_FAMILY.get(liab.get("Product"), "other")
        fam_debt[fam] += liab.get("TotalDebt") or 0
        fam_n[fam] += 1
    for f in FAMILIES:
        out[f"debt_{f}"] = _round(fam_debt[f])
        out[f"n_{f}"] = fam_n[f]
    out["has_mortgage"] = int(fam_n["mortgage"] > 0)
    out["revolving_debt_share"] = (
        _round((fam_debt["card"] + fam_debt["revolving"]) / total_debt, 4)
        if total_debt > 0 else None)

    # timeline (debtor entries; reference = CRC DocumentDate)
    begins = [_month_index(liab["BeginDate"]) for liab in debtor if liab.get("BeginDate")]
    if begins and ref is not None:
        out["oldest_credit_years"] = _round((ref - min(begins)) / 12, 1)
        out["newest_credit_months"] = ref - max(begins)
        out["n_opened_12m"] = sum(1 for b in begins if ref - b < 12)
    maturities = [_month_index(liab["EndDate"]) for liab in debtor
                  if liab.get("EndDate") and liab["EndDate"] != OPEN_ENDED]
    out["n_open_ended"] = sum(1 for liab in debtor if liab.get("EndDate") == OPEN_ENDED)
    if maturities and ref is not None:
        out["latest_maturity_years"] = _round((max(maturities) - ref) / 12, 1)

    # defaults (debtor entries)
    in_def = [liab for liab in debtor if (liab.get("TotalDefault") or 0) > 0]
    out["n_in_default"] = len(in_def)
    total_default = sum((liab.get("TotalDefault") or 0) for liab in in_def)
    out["total_default"] = _round(total_default)
    out["default_debt_share"] = (_round(total_default / total_debt, 4)
                                 if total_debt > 0 else None)
    def_dates = [_month_index(liab["DefaultInitialDate"]) for liab in in_def
                 if liab.get("DefaultInitialDate")]
    if def_dates:
        out["first_default"] = _ym(min(def_dates))
        if ref is not None:
            out["months_in_default"] = ref - min(def_dates)
    out["any_litigation"] = int(any(liab.get("InLitigation") for liab in debtor))

    # contingent exposure as guarantor (avalista / fiador)
    out["guarantor_n"] = len(guarantor)
    out["guarantor_exposure"] = _round(sum(
        (liab.get("TotalDebt") or 0) + (liab.get("Potential") or 0) for liab in guarantor))
    return out


HEADLINE_FIELDS = [
    "total_debt", "total_installment", "n_active", "n_institutions",
    "has_mortgage", "revolving_debt_share", "n_opened_12m",
    "oldest_credit_years", "total_default", "n_in_default", "any_litigation",
    "guarantor_n", "reference_date",
]

CAVEATS = {
    "total_debt": "CRC (Banco de Portugal) na data de referência. Inclui apenas "
                  "créditos onde a pessoa é devedora.",
    "total_installment": "Prestações nulas em cartões/descobertos contam como 0; "
                         "o serviço de dívida real pode ser superior.",
    "guarantor_n": "Responsabilidade contingente: só se materializa se o "
                   "devedor principal falhar.",
    "total_default": "Valores em incumprimento registados na CRC na data de "
                     "referência.",
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


FAMILY_PT = {
    "mortgage": "habitação", "personal": "pessoal", "card": "cartões",
    "auto": "automóvel", "revolving": "descobertos/renováveis",
    "business": "empresarial", "guarantee_given": "garantias prestadas",
    "other": "outros",
}


def render_profile_text(features):
    """Plain-text rendering of the liabilities profile for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field.
    No judgment words, no score.
    """
    if not features["has_crc_data"]:
        return ("Sem responsabilidades de crédito registadas na CRC.\n\n"
                "  Dados da CRC (Banco de Portugal).")

    lines = []
    td, ti = features["total_debt"], features["total_installment"]
    head = (f"Tem {_n(features['n_active'], 'crédito ativo', 'créditos ativos')} "
            f"em {_n(features['n_institutions'], 'instituição', 'instituições')}: "
            f"{_eur(td)} de dívida e {_eur(ti)}/mês de prestações.")
    nd = features["n_in_default"]
    if nd:
        head += (f" EM INCUMPRIMENTO: {_eur(features['total_default'])} em "
                 f"{_n(nd, 'crédito', 'créditos')}"
                 f" desde {features['first_default']}.")
    else:
        head += " Sem incumprimento registado."
    lines.append(head)
    lines.append("")

    lines.append(f"  Dívida total     {_eur(td)} "
                 f"({_n(features['n_liabilities'], 'registo', 'registos')}, "
                 f"{features['n_active']} ativos)")
    lines.append(f"  Prestações       {_eur(ti)}/mês"
                 + (f"  ({features['n_missing_installment']} sem valor declarado)"
                    if features["n_missing_installment"] else ""))

    fam_parts = []
    if td and td > 0:
        for fam in FAMILIES:
            share = (features[f"debt_{fam}"] or 0) / td
            if share >= 0.01:
                fam_parts.append(f"{FAMILY_PT[fam]} {share:.0%}")
    if fam_parts:
        lines.append(f"  Composição       {', '.join(fam_parts)}")

    hist = []
    if features["oldest_credit_years"] is not None:
        hist.append(f"crédito mais antigo há {features['oldest_credit_years']:.0f} anos")
    if features["n_opened_12m"]:
        hist.append(f"{_n(features['n_opened_12m'], 'novo crédito', 'novos créditos')} "
                    "nos últimos 12 meses")
    if hist:
        lines.append(f"  Histórico        {'; '.join(hist)}")

    if features["total_potential"] and features["total_potential"] >= 1:
        lines.append(f"  Potencial        {_eur(features['total_potential'])} "
                     "não utilizado (limites/linhas por usar)")

    if nd:
        lines.append(f"  Incumprimento    {_eur(features['total_default'])} em "
                     f"{_n(nd, 'crédito', 'créditos')}, desde "
                     f"{features['first_default']}"
                     f" ({features['default_debt_share']:.1%} da dívida)")
    if features["any_litigation"]:
        lines.append("  Litígio          existe crédito em litígio judicial")
    if features["guarantor_n"]:
        lines.append(f"  Como avalista    "
                     f"{_n(features['guarantor_n'], 'crédito', 'créditos')} de "
                     f"terceiros ({_eur(features['guarantor_exposure'])} de "
                     "exposição contingente)")
    lines.append("")
    lines.append(f"  Dados da CRC (Banco de Portugal) a {features['reference_date']}. "
                 "Prestações nulas em cartões/descobertos contam como 0.")
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
            vec = liability_features(json.loads(row["value"]))
            print(f"--- {row['uuid'][:8]} ---")
            print(render_profile_text(vec))
            print()
