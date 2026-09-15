"""Adverse-records features from a hAPI proponent snapshot.

Layer 1 (`adverse_features`): the full, versioned feature vector for hard
distress markers: debt-nonexistence certificates (AT and Social Security),
debt execution proceedings, insolvency proceedings, and public-debt records.
Rare events, but each is near-dispositive for credit; they are the natural
hard rules of a scorecard.
Layer 2 (`display_profile` / `render_profile_text`): the client/analyst view.

Input: the parsed snapshot JSON (the `value` document of a proponent), as
captured at application time.

The insolvency subtlety this module exists to get right: proceedings returned
by the search do NOT all belong to the proponent as debtor. Each proceeding
lists parties with roles; the proponent may be the Insolvente (the insolvent
one), a creditor/petitioner, or not identifiable at all. Levels:

- confirmed:   the proponent's NIF appears as "Insolvente" in a proceeding.
- flagged:     the provider flag (BorrowerMetaInformation.hasInsolvencies)
               is "true" but no party match confirms the role: verify
               manually before acting.
- proceedings_only: proceedings were returned but the flag is "false" and
               the proponent is not an identifiable party: search noise or
               third-party connection; NOT an adverse marker.
- none:        nothing returned.

Conventions:
- Missing/uncomputable values are None, never 0. Presence flags say why.
- BorrowerMetaInformation flags are strings ("true"/"false"/None) and are
  parsed accordingly.

Stdlib only. Sibling projects: ../expenses/, ../liabilities/, ../incomes/,
../completeness/, ../employment/.
"""

FEATURES_VERSION = "1.0.0"

NO_ASSETS_REASON = "Inexistência de bens"
DISCHARGE_MARKER = "Exoneração"          # debt-discharge acts (CIRE)
PERSONAL_INSOLVENCY = "pessoa singular"


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _flag(value):
    """BorrowerMetaInformation flags are strings: 'true'/'false'/None."""
    if value == "true":
        return 1
    if value == "false":
        return 0
    return None


def _ym(iso_date):
    return f"{iso_date[:4]}-{iso_date[5:7]}" if iso_date else None


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def adverse_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}
    meta = profile.get("BorrowerMetaInformation") or {}
    my_nif = _dig(profile, "PersonalData", "NIF")

    # ---------- debt-nonexistence certificates ----------
    irs_cert = profile.get("IRSNonDebtCertificateData") or {}
    ss_cert = profile.get("SSNonDebtCertificateData") or {}
    out["irs_cert_has_debts"] = (int(irs_cert["HasDebts"])
                                 if irs_cert.get("HasDebts") is not None
                                 else None)
    out["irs_cert_month"] = _ym(irs_cert.get("DocumentDate"))
    out["ss_cert_has_debts"] = (int(ss_cert["HasDebts"])
                                if ss_cert.get("HasDebts") is not None
                                else None)
    out["ss_cert_month"] = _ym(ss_cert.get("DocumentDate"))

    # ---------- provider flags ----------
    out["flag_executions"] = _flag(meta.get("hasExecutions"))
    out["flag_insolvencies"] = _flag(meta.get("hasInsolvencies"))
    out["flag_at_public_debts"] = _flag(meta.get("hasATPublicDebts"))
    out["flag_ss_public_debts"] = _flag(meta.get("hasSSPublicDebts"))

    # ---------- debt execution proceedings ----------
    execs = profile.get("DebtExecutionProceedingList") or []
    out["n_execution_proceedings"] = len(execs) or None
    out["execution_debt_total"] = (_round(sum((e.get("DebtAmount") or 0)
                                               for e in execs))
                                   if execs else None)
    out["execution_no_assets"] = (int(any(e.get("Reason") == NO_ASSETS_REASON
                                          for e in execs))
                                  if execs else None)
    exec_ends = [e["ProceedingEndDate"] for e in execs
                 if e.get("ProceedingEndDate")]
    out["last_execution_end_month"] = _ym(max(exec_ends)) if exec_ends else None

    # ---------- insolvency proceedings, with role resolution ----------
    procs = profile.get("InsolvencyProceedingsList") or []
    out["n_insolvency_proceedings"] = len(procs) or None
    my_procs, discharge, personal, dates = [], False, False, []
    for proc in procs:
        is_mine = any(d.get("NIF") == my_nif and d.get("Type") == "Insolvente"
                      for d in (proc.get("Debtors") or []))
        if is_mine:
            my_procs.append(proc)
            if PERSONAL_INSOLVENCY in (proc.get("Type") or ""):
                personal = True
        if proc.get("Date"):
            dates.append(proc["Date"])
        if DISCHARGE_MARKER in (proc.get("Act") or ""):
            discharge = True

    if my_procs:
        out["insolvency_level"] = "confirmed"
    elif out["flag_insolvencies"] == 1:
        out["insolvency_level"] = "flagged"
    elif procs:
        out["insolvency_level"] = "proceedings_only"
    else:
        out["insolvency_level"] = "none"
    out["n_insolvencies_as_insolvent"] = len(my_procs) or None
    out["insolvency_personal"] = (int(personal)
                                  if out["insolvency_level"] == "confirmed"
                                  else None)
    out["has_debt_discharge_act"] = (int(discharge) if procs else None)
    out["last_insolvency_act_month"] = _ym(max(dates)) if dates else None

    # ---------- public debts ----------
    ss_debts = profile.get("SocialSecurityPublicDebts") or []
    at_debts = profile.get("TaxAuthorityPublicDebts") or []
    out["ss_public_debt_max"] = (_round(max((d.get("Max") or 0)
                                            for d in ss_debts))
                                 if ss_debts else None)
    out["n_at_public_debts"] = len(at_debts) or None

    # ---------- summary ----------
    markers = []
    if out["irs_cert_has_debts"]:
        markers.append("at_debt_certificate")
    if out["ss_cert_has_debts"]:
        markers.append("ss_debt_certificate")
    if out["flag_executions"] or execs:
        markers.append("debt_executions")
    if out["insolvency_level"] == "confirmed":
        markers.append("insolvency_confirmed")
    elif out["insolvency_level"] == "flagged":
        markers.append("insolvency_flagged_unconfirmed")
    if ss_debts or at_debts or out["flag_ss_public_debts"] == 1 \
            or out["flag_at_public_debts"] == 1:
        markers.append("public_debts")
    out["adverse_markers"] = ";".join(markers) if markers else None
    out["n_adverse_markers"] = len(markers)
    out["any_adverse"] = int(bool(markers))
    return out


HEADLINE_FIELDS = [
    "any_adverse", "n_adverse_markers", "adverse_markers", "insolvency_level",
    "irs_cert_has_debts", "ss_cert_has_debts", "n_execution_proceedings",
    "execution_debt_total", "last_insolvency_act_month", "irs_cert_month",
]

CAVEATS = {
    "insolvency_level": "confirmed = o NIF da pessoa consta como Insolvente "
                        "num processo; flagged = assinalado pelo fornecedor "
                        "mas sem confirmação nas partes do processo, "
                        "verificar manualmente; proceedings_only = processos "
                        "devolvidos pela pesquisa sem papel identificável da "
                        "pessoa, NÃO é marcador adverso.",
    "irs_cert_has_debts": "Certidão de não dívida à Autoridade Tributária na "
                          "data indicada.",
    "execution_no_assets": "Execução terminada por inexistência de bens "
                           "penhoráveis: a dívida persiste.",
    "any_adverse": "Marcadores raros mas quase decisivos; tratar como regras "
                   "duras do scorecard, não como features estatísticas.",
}

MARKER_PT = {
    "at_debt_certificate": "dívidas à Autoridade Tributária (certidão)",
    "ss_debt_certificate": "dívidas à Segurança Social (certidão)",
    "debt_executions": "execuções de dívida",
    "insolvency_confirmed": "insolvência confirmada",
    "insolvency_flagged_unconfirmed": "insolvência assinalada (por confirmar)",
    "public_debts": "dívidas públicas registadas",
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


def _n(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


def render_profile_text(features):
    """Plain-text adverse-records analysis for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field.
    """
    f = features
    lines = []

    if f["any_adverse"]:
        named = [MARKER_PT[m] for m in f["adverse_markers"].split(";")]
        lines.append(f"REGISTOS ADVERSOS ({f['n_adverse_markers']}): "
                     + "; ".join(named) + ".")
    else:
        lines.append("Sem registos adversos nas fontes disponíveis.")
    lines.append("")

    certs = []
    if f["irs_cert_has_debts"] is not None:
        certs.append(("COM dívidas" if f["irs_cert_has_debts"] else "sem dívidas")
                     + f" à AT ({f['irs_cert_month']})")
    if f["ss_cert_has_debts"] is not None:
        certs.append(("COM dívidas" if f["ss_cert_has_debts"] else "sem dívidas")
                     + f" à Seg. Social ({f['ss_cert_month']})")
    if certs:
        lines.append(f"  Certidões        {'; '.join(certs)}")

    if f["n_execution_proceedings"]:
        ex = (f"{_n(f['n_execution_proceedings'], 'processo', 'processos')}, "
              f"{_eur(f['execution_debt_total'])} em dívida")
        if f["execution_no_assets"]:
            ex += "; terminou por INEXISTÊNCIA DE BENS (a dívida persiste)"
        if f["last_execution_end_month"]:
            ex += f"; último em {f['last_execution_end_month']}"
        lines.append(f"  Execuções        {ex}")
    elif f["flag_executions"] == 1:
        lines.append("  Execuções        assinaladas pelo fornecedor, sem "
                     "detalhe de processos")

    level = f["insolvency_level"]
    if level == "confirmed":
        kind = ("pessoal" if f["insolvency_personal"]
                else "de empresa associada")
        ins = (f"CONFIRMADA ({kind}): o NIF consta como Insolvente em "
               f"{_n(f['n_insolvencies_as_insolvent'], 'processo', 'processos')}")
        if f["has_debt_discharge_act"]:
            ins += "; há ato de exoneração do passivo"
        if f["last_insolvency_act_month"]:
            ins += f"; último ato {f['last_insolvency_act_month']}"
        lines.append(f"  Insolvência      {ins}")
    elif level == "flagged":
        lines.append("  Insolvência      assinalada pelo fornecedor mas sem "
                     "papel confirmado nas partes: VERIFICAR MANUALMENTE "
                     f"({_n(f['n_insolvency_proceedings'] or 0, 'processo devolvido', 'processos devolvidos')})")
    elif level == "proceedings_only":
        lines.append(f"  Insolvência      "
                     f"{_n(f['n_insolvency_proceedings'], 'processo devolvido', 'processos devolvidos')} "
                     "pela pesquisa sem papel identificável da pessoa: não é "
                     "marcador adverso")

    if f["ss_public_debt_max"]:
        lines.append(f"  Dívidas públicas Seg. Social até "
                     f"{_eur(f['ss_public_debt_max'])} (escalão registado)")

    lines.append("")
    lines.append("  Marcadores raros mas quase decisivos: usar como regras "
                 "duras, com verificação manual dos casos por confirmar.")
    return "\n".join(lines)


if __name__ == "__main__":
    import csv
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "../data/data_full.csv"
    csv.field_size_limit(sys.maxsize)
    shown = 0
    with open(path, newline="") as fh:
        seen = set()
        for row in csv.DictReader(fh):
            if row["uuid"] in seen:
                continue
            seen.add(row["uuid"])
            vec = adverse_features(json.loads(row["value"]))
            if vec["any_adverse"] or shown < 1:
                print(f"--- {row['uuid'][:8]} ---")
                print(render_profile_text(vec))
                print()
                shown += 1
            if shown >= 4:
                break
