"""Banking-footprint features from a hAPI proponent snapshot.

Layer 1 (`banking_features`): the full, versioned feature vector from
`BCBData.Accounts` (Banco de Portugal account map): relationship depth and
age, account-type mix (deposits, savings, investments, credit facilities,
cards), institution spread, and recent opening activity.
Layer 2 (`display_profile` / `render_profile_text`): the client/analyst view.

Input: the parsed snapshot JSON (the `value` document of a proponent), as
captured at application time. Only `BCBData` is read; the reference date is
`BCBData.DocumentDate`.

Conventions:
- Missing/uncomputable values are None, never 0. Presence flags say why.
- The account map lists only OPEN accounts (zero CloseDate in 6,933 records
  of data_full.csv): closures and churn are NOT observable; only openings.
- Type/mix counts cover accounts where the proponent is "Titular" (owner).
  Other relations are reported separately (`n_as_authorized`,
  `n_as_beneficial_owner`): access to money, not ownership.

Stdlib only. Sibling projects: ../expenses/ .. ../affordability/.
"""

FEATURES_VERSION = "1.0.0"

TITULAR = "Titular"
RECENT_MONTHS = 12


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _month_index(iso_date):
    return int(iso_date[:4]) * 12 + int(iso_date[5:7]) - 1


def _ym(month_index):
    if month_index is None:
        return None
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def _round(value, ndigits=1):
    return None if value is None else round(value, ndigits)


def banking_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}
    bcb = profile.get("BCBData") or {}
    accounts = bcb.get("Accounts") or []
    doc = bcb.get("DocumentDate")
    ref = _month_index(doc) if doc else None

    out["reference_date"] = doc[:10] if doc else None
    out["has_bcb_data"] = int(bool(accounts))
    out["n_accounts"] = len(accounts) or None

    fields = ["n_as_titular", "n_as_authorized", "n_as_beneficial_owner",
              "n_current_accounts", "n_term_deposits", "n_investment_accounts",
              "n_payment_accounts", "n_credit_facilities", "n_card_accounts",
              "has_savings", "has_investments", "n_institutions",
              "main_institution_share", "oldest_account_years",
              "newest_account_months", "n_opened_12m", "n_credit_opened_12m"]
    for f in fields:
        out[f] = None
    if not accounts:
        return out

    own = [a for a in accounts if a.get("AccountRelation") == TITULAR]
    out["n_as_titular"] = len(own) or None
    out["n_as_authorized"] = sum(
        1 for a in accounts
        if (a.get("AccountRelation") or "").startswith("Autorizado")) or None
    out["n_as_beneficial_owner"] = sum(
        1 for a in accounts
        if a.get("AccountRelation") == "Beneficiário efetivo") or None
    if not own:
        return out

    def n_where(pred):
        return sum(1 for a in own if pred(a))

    out["n_current_accounts"] = n_where(
        lambda a: a.get("SubType") == "Depósito à ordem")
    out["n_term_deposits"] = n_where(
        lambda a: a.get("SubType") in ("Depósito a prazo",
                                       "Depósito com pré-aviso"))
    out["n_investment_accounts"] = n_where(
        lambda a: a.get("AccountType") == "Instrumentos financeiros")
    out["n_payment_accounts"] = n_where(
        lambda a: a.get("AccountType") == "Pagamento")
    out["n_credit_facilities"] = n_where(
        lambda a: a.get("AccountType") == "Abertura de crédito")
    out["n_card_accounts"] = n_where(lambda a: a.get("SubType") == "Cartão")
    out["has_savings"] = int(out["n_term_deposits"] > 0)
    out["has_investments"] = int(out["n_investment_accounts"] > 0)

    institutions = {}
    for a in own:
        code = a.get("InstitutionCode")
        if code:
            institutions[code] = institutions.get(code, 0) + 1
    out["n_institutions"] = len(institutions) or None
    if institutions:
        out["main_institution_share"] = _round(
            max(institutions.values()) / len(own), 3)

    opens = [_month_index(a["OpenDate"]) for a in own if a.get("OpenDate")]
    if opens and ref is not None:
        out["oldest_account_years"] = _round((ref - min(opens)) / 12)
        out["newest_account_months"] = ref - max(opens)
        out["n_opened_12m"] = sum(1 for m in opens
                                  if ref - m < RECENT_MONTHS)
        out["n_credit_opened_12m"] = sum(
            1 for a in own
            if a.get("OpenDate")
            and ref - _month_index(a["OpenDate"]) < RECENT_MONTHS
            and a.get("AccountType") == "Abertura de crédito")
    return out


HEADLINE_FIELDS = [
    "n_accounts", "n_institutions", "oldest_account_years",
    "n_current_accounts", "has_savings", "has_investments",
    "n_credit_facilities", "n_opened_12m", "n_credit_opened_12m",
    "main_institution_share", "reference_date",
]

CAVEATS = {
    "n_accounts": "Mapa de contas do Banco de Portugal na data de referência. "
                  "Só mostra contas ABERTAS: encerramentos não são visíveis.",
    "oldest_account_years": "Idade da relação bancária mais antiga como "
                            "titular.",
    "n_credit_opened_12m": "Aberturas de crédito (linhas/facilidades) criadas "
                           "nos últimos 12 meses: apetite de crédito recente.",
    "main_institution_share": "Fração das contas na instituição principal: "
                              "1.0 = tudo num banco.",
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


def _n(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


def render_profile_text(features):
    """Plain-text banking-footprint analysis for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field.
    """
    f = features
    if not f["has_bcb_data"] or not f["n_as_titular"]:
        return ("Sem contas bancárias registadas no mapa do Banco de Portugal"
                + (" como titular." if f["has_bcb_data"] else ".") + "\n\n"
                "  O mapa só mostra contas abertas na data de referência.")

    lines = []
    head = (f"Relação bancária com "
            f"{_n(f['n_institutions'], 'instituição', 'instituições')}"
            + (f" há {f['oldest_account_years']:.0f} anos"
               if f["oldest_account_years"] is not None else "")
            + f": {_n(f['n_as_titular'], 'conta', 'contas')} como titular")
    marks = []
    if f["has_savings"]:
        marks.append("com poupança a prazo")
    if f["has_investments"]:
        marks.append("com conta de investimento")
    if marks:
        head += " (" + ", ".join(marks) + ")"
    head += "."
    if f["n_credit_opened_12m"]:
        head += (f" {_n(f['n_credit_opened_12m'], 'abertura de crédito', 'aberturas de crédito')} "
                 "nos últimos 12 meses.")
    lines.append(head)
    lines.append("")

    mix = []
    if f["n_current_accounts"]:
        mix.append(f"{f['n_current_accounts']} à ordem")
    if f["n_term_deposits"]:
        mix.append(f"{f['n_term_deposits']} a prazo (poupança)")
    if f["n_investment_accounts"]:
        mix.append(f"{f['n_investment_accounts']} de investimento")
    if f["n_payment_accounts"]:
        mix.append(f"{f['n_payment_accounts']} de pagamento")
    if f["n_credit_facilities"]:
        mix.append(f"{f['n_credit_facilities']} aberturas de crédito")
    if f["n_card_accounts"]:
        mix.append(f"{f['n_card_accounts']} de cartão")
    if mix:
        lines.append(f"  Contas           {'; '.join(mix)}")
    if f["main_institution_share"] is not None:
        conc = ("tudo numa instituição"
                if f["main_institution_share"] >= 0.999 else
                f"{f['main_institution_share']:.0%} das contas na "
                "instituição principal")
        lines.append(f"  Concentração     {conc} "
                     f"({f['n_institutions']} no total)")
    hist = []
    if f["oldest_account_years"] is not None:
        hist.append(f"conta mais antiga há {f['oldest_account_years']:.0f} "
                    "anos")
    if f["n_opened_12m"]:
        hist.append(f"{_n(f['n_opened_12m'], 'conta aberta', 'contas abertas')} "
                    "nos últimos 12 meses")
    if hist:
        lines.append(f"  Histórico        {'; '.join(hist)}")
    other = []
    if f["n_as_authorized"]:
        other.append(f"autorizado a movimentar {_n(f['n_as_authorized'], 'conta de terceiros', 'contas de terceiros')}")
    if f["n_as_beneficial_owner"]:
        other.append(f"beneficiário efetivo de {f['n_as_beneficial_owner']}")
    if other:
        lines.append(f"  Outros papéis    {'; '.join(other)}")
    lines.append("")
    lines.append("  Mapa do Banco de Portugal a "
                 f"{f['reference_date']}: só mostra contas abertas; "
                 "encerramentos não são visíveis.")
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
            vec = banking_features(json.loads(row["value"]))
            print(f"--- {row['uuid'][:8]} ---")
            print(render_profile_text(vec))
            print()
