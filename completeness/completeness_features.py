"""Data-completeness features from a hAPI proponent snapshot.

Cross-cutting layer over the three profile projects (expenses, liabilities,
incomes): before reading any profile, the analyst and the credit score model
need to know how much of the snapshot can be trusted, and why parts are
absent.

Completeness decomposes into FIVE signals, all measured per proponent:

1. CORE presence (CRC, personal data, e-fatura, IRS, debt certificate, BCB
   accounts): 95-100% coverage; a miss is an extraction defect.
2. The SOCIAL SECURITY gate (salary, SS payments, calculated incomes, job
   info; co-occur 94-98%). Measured against the other vectors it is a
   DATA-ACCESS ARTIFACT, not a personal trait: both sides show the same
   self-employment rates, incomes and significant-default rates.
3. SERIES INTEGRITY: monthly sources are checked for holes inside their own
   span (salary holes = employment interruptions or collection gaps),
   cross-source month alignment (salary vs SS), and whether spending data
   continues after income data stops.
4. CROSS-SOURCE CONSISTENCY: contradictions between sources (open activity
   with no self-employment income anywhere, invoicing without a registered
   activity, CRC debt with no bank accounts, salary with no employer or no
   Annex A, stale IRS).
5. ANALYSIS READINESS: which downstream analyses this snapshot can support
   (expenses profile, liabilities profile, salary verification, DSTI, full
   affordability).

Situational sources (activity, invoices, renter contracts, pension) are at
most weakly descriptive of the person; missingness barely predicts default
(AUC 0.51-0.53). Evidence: spec, "Measured meaning of absence".

Stdlib only. Sibling projects: ../expenses/, ../liabilities/, ../incomes/.
"""

FEATURES_VERSION = "1.2.0"

CORE_SOURCES = ["crc", "personal_data", "efatura", "irs", "irs_no_debt_cert",
                "bcb_accounts"]
SS_BLOCK = ["net_salary", "ss_payments", "calculated_incomes", "job_info"]

# Extraction telemetry (ServicesResults) taxonomy, validated on data_full.csv:
# ErrorCode 200 = data returned; 484 = NO DATA EXISTS (e.g. the rent service
# returns 484 for exactly the 436 proponents without contracts); other codes
# (481/482/485/486/487) are technical; a service that never reached 200 nor
# 484 is a genuine fetch failure. LoginValidator always recovered via retries.
NO_DATA_CODE = "484"
SS_SERVICES = ["getMonthlyContributoryCareerCertificate", "getLastestPayments",
               "getLastJobDuration"]
SOURCE_SERVICES = {
    "rent": ["getRenterHouseRentContract"],
    "invoices": ["getGreenReceiptsInvoices", "getInvoices"],
    "terminations": ["getEndOfWorkContractsList"],
    "activity": ["getActivityStartCertificate"],
}


def _service_status(codes):
    """One service's outcome from the set of its call ErrorCodes."""
    if codes is None:
        return "not_called"
    if "200" in codes:
        return "ok"
    if codes <= {NO_DATA_CODE}:
        return "no_data"
    return "failed"


def _best_status(calls, names):
    """Combined outcome over a set of services feeding one source."""
    statuses = [_service_status(calls.get(n)) for n in names]
    for s in ("ok", "no_data", "failed"):
        if s in statuses:
            return s
    return "not_called"

MIN_EXPENSE_MONTHS = 3      # expenses profile needs at least this window
DIVERGENCE_ALERT = 3        # salary/SS month sets differing by >= this
SPEND_AFTER_INCOME_ALERT = 3  # receipts continuing >= this after income stops
IRS_LAG_ALERT_YEARS = 2


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


def _month_set(entries):
    """Distinct month indexes from entries with Year/Month (Month=0 excluded)."""
    return sorted({int(e["Year"]) * 12 + int(e["Month"]) - 1
                   for e in entries if e.get("Year") and e.get("Month")})


def _gaps(months):
    """Months missing inside the observed span (0 when contiguous or short)."""
    if len(months) < 2:
        return 0
    return months[-1] - months[0] + 1 - len(months)


def completeness_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}

    # ---------- core presence ----------
    irs_cur = _dig(profile, "IRSTaxDeclarationDetails", "Total", "Income")
    irs_prev = _dig(profile, "IRSTaxDeclarationDetailsPreviousYear",
                    "Total", "Income")
    has_irs = ((irs_cur is not None and irs_cur >= 1)
               or (irs_prev is not None and irs_prev >= 1))
    liabs = _dig(profile, "CRCData", "Liabilities") or []
    accounts = _dig(profile, "BCBData", "Accounts") or []
    receipts = profile.get("ExpensesList") or []

    core = {
        "crc": bool(liabs),
        "personal_data": _dig(profile, "PersonalTaxData",
                              "BirthDate") is not None,
        "efatura": bool(receipts),
        "irs": has_irs,
        "irs_no_debt_cert": _dig(profile, "IRSNonDebtCertificateData",
                                 "HasDebts") is not None,
        "bcb_accounts": bool(accounts),
    }
    for k, present in core.items():
        out[f"has_{k}"] = int(present)
    out["n_core_present"] = sum(core.values())
    out["core_complete"] = int(all(core.values()))
    missing = [k for k, present in core.items() if not present]
    out["missing_core"] = ";".join(missing) if missing else None

    # ---------- inventory: quantities per source ----------
    out["n_crc_liabilities"] = len(liabs) or None
    out["n_bcb_accounts"] = len(accounts) or None
    out["n_receipts"] = len(receipts) or None

    # ---------- SS gate ----------
    salary = profile.get("NetSalary") or []
    ss = _dig(profile, "SSPayments", "Payments") or []
    block = {
        "net_salary": bool(salary),
        "ss_payments": bool(ss),
        "calculated_incomes": (profile.get("CalculatedIncomes") or {})
                              .get("AVGRegularIncome6Month") is not None,
        "job_info": bool(_dig(profile, "LastJobInfo", "Job")),
    }
    for k, present in block.items():
        out[f"has_{k}"] = int(present)
    out["has_ss_block"] = int(block["net_salary"] or block["ss_payments"])
    out["ss_block_complete"] = int(all(block.values()))

    # ---------- situational ----------
    activity = profile.get("ActivityRegistration") or {}
    activity_open = (bool(activity.get("StartDate"))
                     and not (activity.get("IRSActivity") or {}).get("EndDate"))
    invoices = profile.get("InvoicesList") or []
    out["has_activity_registration"] = int(bool(activity.get("StartDate")))
    out["has_invoices"] = int(bool(invoices))
    out["has_renter_contracts"] = int(bool(profile.get("RenterContractList")))
    out["has_pension"] = int(bool(_dig(profile, "Income", "Pension")))

    # ---------- income verification regime ----------
    if out["has_ss_block"]:
        out["income_verification"] = "ss_verified"
    elif has_irs:
        out["income_verification"] = "irs_only"
    else:
        out["income_verification"] = "none"
    out["income_none_suspect_gap"] = int(
        out["income_verification"] == "none"
        and (core["crc"] or core["efatura"]))

    # ---------- series integrity ----------
    sal_m = _month_set(salary)
    ss_m = _month_set(ss)
    rec_m = sorted({_month_index(e["IssuanceDate"]) for e in receipts
                    if e.get("IssuanceDate")})
    inv_m = _month_set(invoices)
    crc_doc = _dig(profile, "CRCData", "DocumentDate")
    crc_month = _month_index(crc_doc) if crc_doc else None

    out["n_salary_months"] = len(sal_m) or None
    out["salary_first_month"] = _ym(sal_m[0]) if sal_m else None
    out["salary_gap_months"] = _gaps(sal_m) if sal_m else None
    out["n_ss_months"] = len(ss_m) or None
    out["ss_gap_months"] = _gaps(ss_m) if ss_m else None
    out["n_receipt_months"] = len(rec_m) or None
    out["receipt_gap_months"] = _gaps(rec_m) if rec_m else None
    out["n_invoice_months"] = len(inv_m) or None
    out["salary_ss_divergence_months"] = (len(set(sal_m) ^ set(ss_m))
                                          if sal_m and ss_m else None)

    last_receipt = rec_m[-1] if rec_m else None
    last_salary = sal_m[-1] if sal_m else None
    last_ss = ss_m[-1] if ss_m else None
    last_income = max((m for m in (last_salary, last_ss) if m is not None),
                      default=None)
    out["spend_after_income_months"] = (last_receipt - last_income
                                        if last_receipt is not None
                                        and last_income is not None else None)

    # ---------- freshness ----------
    anchor = max((m for m in (last_receipt, last_salary, last_ss, crc_month)
                  if m is not None), default=None)
    out["data_anchor_month"] = _ym(anchor)
    out["last_receipt_month"] = _ym(last_receipt)
    out["last_salary_month"] = _ym(last_salary)
    out["last_ss_month"] = _ym(last_ss)
    out["crc_reference_month"] = _ym(crc_month)
    for name, m in (("efatura", last_receipt), ("salary", last_salary),
                    ("ss", last_ss), ("crc", crc_month)):
        out[f"{name}_staleness_months"] = (anchor - m
                                           if anchor is not None
                                           and m is not None else None)
    irs_year = (_dig(profile, "IRSTaxDeclarationDetails", "Year")
                if irs_cur is not None
                else _dig(profile, "IRSTaxDeclarationDetailsPreviousYear",
                          "Year") if irs_prev is not None else None)
    out["irs_year"] = irs_year
    out["irs_lag_years"] = (anchor // 12 - irs_year
                            if anchor is not None and irs_year else None)

    # ---------- cross-source consistency ----------
    annex_a = _dig(profile, "IRSTaxDeclarationDetails",
                   "AnnexA", "AnnexTotal", "Income")
    annex_b = _dig(profile, "IRSTaxDeclarationDetails",
                   "AnnexB", "AnnexTotal", "Income")
    flags = []
    if sal_m and not block["job_info"]:
        flags.append("salary_without_job_info")
    if sal_m and irs_cur is not None and not annex_a:
        flags.append("salary_without_irs_annex_a")
    if activity_open and not annex_b and not invoices:
        flags.append("open_activity_without_self_employment_income")
    if invoices and not activity.get("StartDate"):
        flags.append("invoices_without_activity_registration")
    if liabs and not accounts:
        flags.append("crc_debt_without_bcb_accounts")
    if (out["irs_lag_years"] or 0) >= IRS_LAG_ALERT_YEARS:
        flags.append("irs_stale_2y_plus")
    if (out["salary_ss_divergence_months"] or 0) >= DIVERGENCE_ALERT:
        flags.append("salary_ss_divergence")
    if (out["spend_after_income_months"] or 0) >= SPEND_AFTER_INCOME_ALERT:
        flags.append("income_series_stopped_early")
    if (out["salary_gap_months"] or 0) >= 2:
        flags.append("salary_series_has_holes")
    out["consistency_flags"] = ";".join(flags) if flags else None
    out["n_consistency_flags"] = len(flags)

    # ---------- extraction telemetry (why data is absent) ----------
    calls = {}
    for s in profile.get("ServicesResults") or []:
        name = s.get("ServiceName")
        if name:
            calls.setdefault(name, set()).add(str(s.get("ErrorCode")))
    statuses = {n: _service_status(c) for n, c in calls.items()}
    out["n_services_called"] = len(calls) or None
    out["n_services_ok"] = (sum(1 for s in statuses.values() if s == "ok")
                            or None) if calls else None
    out["n_services_no_data"] = (sum(1 for s in statuses.values()
                                     if s == "no_data")
                                 if calls else None)
    out["n_services_failed"] = (sum(1 for s in statuses.values()
                                    if s == "failed")
                                if calls else None)
    failed = sorted(n for n, s in statuses.items() if s == "failed")
    out["failed_services"] = ";".join(failed) if failed else None
    out["refetch_recommended"] = int(bool(failed))

    # cause of the SS gate, now measured instead of inferred
    if out["has_ss_block"]:
        out["ss_gate_cause"] = "open"
    else:
        ss_status = _best_status(calls, SS_SERVICES)
        out["ss_gate_cause"] = {
            "not_called": "not_attempted",   # SS services never invoked
            "no_data": "no_data",
            "failed": "fetch_failed",
            "ok": "fetched_but_empty",       # service ok, source still empty
        }[ss_status]

    for source, services in SOURCE_SERVICES.items():
        out[f"{source}_fetch"] = (_best_status(calls, services)
                                  if calls else None)
    out["is_landlord"] = (int(_service_status(
        calls.get("getLandLordHouseRentContract")) == "ok")
        if calls else None)

    # ---------- analysis readiness ----------
    can = {
        "expenses_profile": len(rec_m) >= MIN_EXPENSE_MONTHS,
        "liabilities_profile": bool(liabs),
        "salary_verification": bool(sal_m),
        "dsti": bool(liabs) and (has_irs or bool(sal_m)),
    }
    can["full_affordability"] = (can["expenses_profile"] and can["dsti"])
    for k, ok in can.items():
        out[f"can_{k}"] = int(ok)
    out["n_analyses_possible"] = sum(can.values())
    return out


HEADLINE_FIELDS = [
    "core_complete", "missing_core", "income_verification",
    "n_consistency_flags", "consistency_flags", "n_analyses_possible",
    "salary_gap_months", "irs_lag_years", "last_salary_month",
    "crc_reference_month", "last_receipt_month", "data_anchor_month",
]

CAVEATS = {
    "core_complete": "Fontes sempre esperadas: CRC, dados pessoais, e-fatura, "
                     "IRS, certidão de dívida, Banco de Portugal. Falta = "
                     "defeito de extração, repetir a recolha.",
    "income_verification": "ss_verified = salário/descontos da Segurança "
                           "Social disponíveis; irs_only = rendimento assenta "
                           "só na declaração anual; none = sem rendimento "
                           "verificável. O acesso à Seg. Social é uma "
                           "limitação de dados, não uma característica da "
                           "pessoa.",
    "consistency_flags": "Contradições entre fontes ou séries com buracos; "
                         "cada bandeira identifica o que verificar antes de "
                         "confiar no perfil.",
    "n_analyses_possible": "De 5: perfil de despesas, responsabilidades, "
                           "verificação salarial, DSTI, affordability "
                           "completa.",
}

CORE_PT = {
    "crc": "CRC", "personal_data": "dados pessoais", "efatura": "e-fatura",
    "irs": "IRS", "irs_no_debt_cert": "certidão de dívida",
    "bcb_accounts": "contas Banco de Portugal",
}

FLAG_PT = {
    "salary_without_job_info": "há salário mas nenhum registo de empregador",
    "salary_without_irs_annex_a": "há salário mas o IRS não declara trabalho "
                                  "dependente (Anexo A vazio)",
    "open_activity_without_self_employment_income":
        "atividade independente aberta sem qualquer rendimento independente "
        "(sem Anexo B, sem faturação)",
    "invoices_without_activity_registration": "há faturação emitida sem "
                                              "atividade registada",
    "crc_debt_without_bcb_accounts": "há dívida na CRC mas nenhuma conta "
                                     "bancária no mapa do Banco de Portugal",
    "irs_stale_2y_plus": "o IRS disponível tem 2 ou mais anos de atraso",
    "salary_ss_divergence": "os meses de salário e de descontos à Seg. Social "
                            "divergem em 3 ou mais meses",
    "income_series_stopped_early": "as despesas continuam 3 ou mais meses "
                                   "depois do fim dos dados de rendimento",
    "salary_series_has_holes": "a série de salários tem meses em falta no "
                               "meio (interrupção de emprego ou falha de "
                               "recolha)",
}

ANALYSES_PT = {
    "expenses_profile": "perfil de despesas",
    "liabilities_profile": "responsabilidades",
    "salary_verification": "verificação salarial",
    "dsti": "DSTI",
    "full_affordability": "affordability completa",
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


def render_profile_text(features):
    """Plain-text data-quality analysis for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field.
    """
    f = features
    lines = []

    # headline: completeness + regime + problems, in one sentence
    if f["core_complete"]:
        head = "Dados de base completos"
    else:
        miss = [CORE_PT[m] for m in f["missing_core"].split(";")]
        head = f"DADOS DE BASE INCOMPLETOS (falta: {', '.join(miss)})"
    regime = f["income_verification"]
    if regime == "ss_verified":
        head += (f"; rendimento verificado pela Segurança Social "
                 f"({f['n_salary_months']} meses de salário, último "
                 f"{f['last_salary_month']})")
    elif regime == "irs_only":
        head += ("; SEM acesso à Segurança Social: rendimento assenta apenas "
                 f"no IRS ({f['irs_year']}, anual)")
    else:
        head += "; sem rendimento verificável em nenhuma fonte"
        if f["income_none_suspect_gap"]:
            head += (" (provável falha de recolha: há histórico de crédito "
                     "ou despesas)")
    n_flags = f["n_consistency_flags"]
    head += (f". {n_flags} inconsistência{'s' if n_flags != 1 else ''} "
             "detetada" + ("s." if n_flags != 1 else ".")
             if n_flags else ". Sem inconsistências detetadas.")
    lines.append(head)
    lines.append("")

    # core + inventory: what exists and in what quantity
    core_line = ("completo (6/6)" if f["core_complete"]
                 else f"{f['n_core_present']}/6, falta "
                      + ", ".join(CORE_PT[m]
                                  for m in f["missing_core"].split(";")))
    lines.append(f"  Núcleo           {core_line}")

    inv = []
    if f["n_crc_liabilities"]:
        inv.append(f"CRC {f['n_crc_liabilities']} registos "
                   f"({f['crc_reference_month']})")
    if f["n_receipts"]:
        gap = (", sem buracos" if not f["receipt_gap_months"]
               else f", {f['receipt_gap_months']} meses em falta")
        inv.append(f"e-fatura {f['n_receipts']} faturas em "
                   f"{f['n_receipt_months']} meses (até "
                   f"{f['last_receipt_month']}{gap})")
    if f["irs_year"]:
        lag = f["irs_lag_years"]
        inv.append(f"IRS {f['irs_year']}"
                   + (f" (desatualizado {lag} anos)" if (lag or 0) >= 2
                      else ""))
    if f["n_bcb_accounts"]:
        inv.append(f"{f['n_bcb_accounts']} contas bancárias")
    if inv:
        lines.append(f"  Inventário       {'; '.join(inv)}")

    # SS gate with series integrity
    # telemetry: why things are absent, and what to refetch
    if f["n_services_called"]:
        tel = (f"{f['n_services_called']} serviços consultados: "
               f"{f['n_services_ok']} com dados, "
               f"{f['n_services_no_data']} sem dados (inexistência real)")
        if f["n_services_failed"]:
            tel += (f", {f['n_services_failed']} FALHAS TÉCNICAS: repetir a "
                    "recolha: " + f["failed_services"].replace(";", ", "))
        lines.append(f"  Recolha          {tel}")

    if f["has_ss_block"]:
        parts = []
        if f["n_salary_months"]:
            holes = ("contínuos" if not f["salary_gap_months"]
                     else f"{f['salary_gap_months']} meses em falta no meio")
            parts.append(f"salário {f['salary_first_month']} a "
                         f"{f['last_salary_month']} "
                         f"({f['n_salary_months']} meses, {holes})")
        if f["n_ss_months"]:
            div = f["salary_ss_divergence_months"]
            align = ("" if div is None
                     else ", alinhados com o salário" if div <= 1
                     else f", divergem do salário em {div} meses")
            parts.append(f"descontos até {f['last_ss_month']}{align}")
        lines.append(f"  Seg. Social      com acesso: {'; '.join(parts)}")
    else:
        cause_pt = {
            "not_attempted": "os serviços da Seg. Social nunca foram "
                             "invocados (sem credenciais/consentimento)",
            "no_data": "os serviços responderam sem dados",
            "fetch_failed": "FALHA TÉCNICA na recolha: repetir",
            "fetched_but_empty": "os serviços responderam mas a fonte ficou "
                                 "vazia: verificar",
        }.get(f.get("ss_gate_cause"), "causa desconhecida")
        lines.append("  Seg. Social      sem acesso (salário, descontos e "
                     f"emprego indisponíveis): {cause_pt}")

    # continuity between income data and observed life
    sa = f["spend_after_income_months"]
    if sa is not None and sa >= SPEND_AFTER_INCOME_ALERT:
        lines.append(f"  Continuidade     as despesas continuam {sa} meses "
                     "depois do último registo de rendimento: os dados de "
                     "rendimento pararam, a vida não")

    situ = []
    if f["has_activity_registration"]:
        situ.append("atividade independente registada")
    if f["has_invoices"]:
        situ.append(f"faturação própria ({f['n_invoice_months']} meses)")
    if f["has_renter_contracts"]:
        situ.append("contrato de arrendamento")
    if f["has_pension"]:
        situ.append("pensão")
    if situ:
        lines.append(f"  Situacional      {'; '.join(situ)}")

    if f["consistency_flags"]:
        for i, flag in enumerate(f["consistency_flags"].split(";")):
            label = "  Inconsistências  " if i == 0 else "                   "
            lines.append(f"{label}- {FLAG_PT[flag]}")

    possible = [ANALYSES_PT[k] for k in ANALYSES_PT if f[f"can_{k}"]]
    blocked = [ANALYSES_PT[k] for k in ANALYSES_PT if not f[f"can_{k}"]]
    line = f"  Análises         possíveis: {', '.join(possible) or 'nenhuma'}"
    if blocked:
        line += f" | bloqueadas: {', '.join(blocked)}"
    lines.append(line)

    lines.append("")
    lines.append("  O acesso à Seg. Social é uma limitação de dados, não uma "
                 "característica da pessoa; a ausência de fontes situacionais "
                 "é, quando muito, fracamente descritiva.")
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
            vec = completeness_features(json.loads(row["value"]))
            print(f"--- {row['uuid'][:8]} ---")
            print(render_profile_text(vec))
            print()
