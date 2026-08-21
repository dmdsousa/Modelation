"""Income features from a hAPI proponent snapshot.

Layer 1 (`income_features`): the full, versioned feature vector combining the
snapshot's income sources: IRS declarations (annual, gross, household),
NetSalary (monthly, net, employer-declared), Social Security payments,
hAPI CalculatedIncomes, self-employment activity and invoicing, pensions.
Consumers: the credit score model (as input features) and layer 2.
Layer 2 (`display_profile` / `render_profile_text`): the client/analyst view.

Input: the parsed snapshot JSON (the `value` document of a proponent), as
captured at application time.

Conventions:
- Missing/uncomputable values are None, never 0. Presence flags say why.
- Monetary values are EUR. "6m" averages cover the last 6 recorded months of
  that source (not calendar months back from today).
- Sources measure different things: IRS is annual GROSS and covers the whole
  declaration (both holders for couples); NetSalary is monthly NET for the
  proponent. They are reported side by side, never mixed silently.
- Sub-1-EUR annual IRS declarations are data artifacts and count as missing
  (same rule as the expenses contract).
- Monthly-series entries with Month = 0 (annual aggregates / bonus rows in
  NetSalary and SSPayments) are excluded from monthly averages.

Stdlib only. Sibling projects: ../expenses/, ../liabilities/.
"""

FEATURES_VERSION = "1.0.0"

TAIL_MONTHS = 6


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def _ym(year, month):
    if not year or not month:
        return None
    return f"{int(year):04d}-{int(month):02d}"


def _monthly_tail(entries, value_key):
    """Sort monthly entries by (Year, Month); return (sorted, last TAIL_MONTHS)."""
    dated = [e for e in entries if e.get("Year") and e.get("Month")]
    dated.sort(key=lambda e: (e["Year"], e["Month"]))
    return dated, dated[-TAIL_MONTHS:]


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def income_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}

    # --- IRS declarations (annual, gross, household-level) ---
    cur = profile.get("IRSTaxDeclarationDetails") or {}
    prev = profile.get("IRSTaxDeclarationDetailsPreviousYear") or {}
    irs = _dig(cur, "Total", "Income")
    irs_year = cur.get("Year")
    income_source = "current_declaration"
    if irs is None:
        irs, irs_year = _dig(prev, "Total", "Income"), prev.get("Year")
        income_source = "previous_declaration" if irs is not None else "missing"
    if irs is not None and irs < 1:
        irs, irs_year, income_source = None, None, "missing"

    irs_prev = _dig(prev, "Total", "Income")
    out["irs_income_source"] = income_source
    out["irs_year"] = irs_year
    out["irs_total_income"] = _round(irs)
    out["monthly_income_irs"] = _round(irs / 12) if irs else None
    out["irs_prev_year"] = prev.get("Year") if irs_prev is not None else None
    out["irs_total_income_prev"] = _round(irs_prev)
    out["irs_yoy_growth"] = (
        _round(irs / irs_prev - 1, 4)
        if irs and irs_prev and irs_prev >= 1
        and income_source == "current_declaration" else None)

    annex_src = cur if income_source == "current_declaration" else prev
    annex_a = _dig(annex_src, "AnnexA", "AnnexTotal", "Income")
    annex_b = _dig(annex_src, "AnnexB", "AnnexTotal", "Income")
    out["irs_annex_a_income"] = _round(annex_a)   # dependent work
    out["irs_annex_b_income"] = _round(annex_b)   # self-employment/business
    ab = (annex_a or 0) + (annex_b or 0)
    out["self_employed_share"] = _round((annex_b or 0) / ab, 4) if ab > 0 else None
    holder_b = ((_dig(annex_src, "AnnexA", "AnnexTotal", "TotalHolderB", "Income") or 0)
                + (_dig(annex_src, "AnnexB", "AnnexTotal", "TotalHolderB", "Income") or 0))
    out["irs_holder_b_income"] = _round(holder_b)
    out["irs_is_joint"] = int(holder_b > 0) if irs is not None else None

    # --- NetSalary (monthly, net, proponent-level) ---
    salary_all, salary_tail = _monthly_tail(profile.get("NetSalary") or [],
                                            "NetSalary")
    out["has_salary_data"] = int(bool(salary_all))
    out["salary_months_covered"] = len(salary_all) or None
    out["last_salary_month"] = (_ym(salary_all[-1]["Year"], salary_all[-1]["Month"])
                                if salary_all else None)
    out["avg_net_salary_6m"] = _round(_avg([e.get("NetSalary") for e in salary_tail]))
    out["avg_gross_salary_6m"] = _round(_avg([e.get("GrossSalary") for e in salary_tail]))
    out["latest_net_salary"] = (_round(salary_all[-1].get("NetSalary"))
                                if salary_all else None)
    net_sum = sum(e.get("NetSalary") or 0 for e in salary_tail)
    var_sum = sum(e.get("VariableIncomeNetAmount") or 0 for e in salary_tail)
    out["variable_income_share_6m"] = (_round(var_sum / net_sum, 4)
                                       if net_sum > 0 else None)

    # --- Social Security payments (monthly declared remuneration) ---
    ss_all, ss_tail = _monthly_tail(
        (profile.get("SSPayments") or {}).get("Payments") or [], "Amount")
    out["has_ss_data"] = int(bool(ss_all))
    out["ss_months_covered"] = len(ss_all) or None
    out["last_ss_month"] = (_ym(ss_all[-1]["Year"], ss_all[-1]["Month"])
                            if ss_all else None)
    out["avg_ss_amount_6m"] = _round(_avg([e.get("Amount") for e in ss_tail]))

    # --- hAPI precomputed (pass-through) ---
    ci = profile.get("CalculatedIncomes") or {}
    out["avg_regular_income_6m"] = _round(ci.get("AVGRegularIncome6Month"))
    out["avg_regular_income_12m"] = _round(ci.get("AVGRegularIncome12Month"))
    out["avg_variable_income_6m"] = _round(ci.get("AVGVariableIncome6Month"))
    out["avg_pension_income_6m"] = _round(ci.get("AVGPensionIncome6Month"))
    out["avg_invoices_income_6m"] = _round(ci.get("AVGInvoicesIncome6Month"))
    out["last_regular_income_month"] = _ym(ci.get("LastRegularIncomeYear"),
                                           ci.get("LastRegularIncomeMonth"))

    # --- self-employment: activity registration + invoicing ---
    activity = profile.get("ActivityRegistration") or {}
    out["has_activity_registration"] = int(bool(activity.get("StartDate")))
    irs_act = activity.get("IRSActivity") or {}
    out["activity_open"] = (int(not irs_act.get("EndDate"))
                            if activity.get("StartDate") else None)
    out["activity_start_year"] = (int(activity["StartDate"][:4])
                                  if activity.get("StartDate") else None)
    out["activity_tax_category"] = activity.get("TaxCategory") or None

    invoices_all, _ = _monthly_tail(profile.get("InvoicesList") or [],
                                    "TotalAmount")
    out["has_invoices"] = int(bool(invoices_all))
    out["invoices_months_covered"] = len(invoices_all) or None
    out["last_invoice_month"] = (_ym(invoices_all[-1]["Year"],
                                     invoices_all[-1]["Month"])
                                 if invoices_all else None)
    out["invoices_total_12m"] = (_round(sum(e.get("TotalAmount") or 0
                                            for e in invoices_all[-12:]))
                                 if invoices_all else None)

    # --- pension ---
    pension = (profile.get("Income") or {}).get("Pension") or []
    pension_values = [_dig(e, "Income", "Value") for e in pension]
    out["has_pension"] = int(bool(pension) or bool(ci.get("AVGPensionIncome6Month")))
    out["latest_pension_value"] = _round(pension_values[-1]) if pension_values else None

    # --- employment record ---
    jobs = (profile.get("LastJobInfo") or {}).get("Job") or []
    out["n_job_records"] = len(jobs)
    out["employer_active"] = (int(any(_dig(j, "Company", "status") == "active"
                                      for j in jobs)) if jobs else None)

    # --- coherence across sources ---
    sources = [irs is not None, bool(salary_all), bool(ss_all),
               bool(invoices_all), out["has_pension"] == 1]
    out["n_income_sources"] = sum(sources)
    out["salary_vs_irs_ratio"] = (
        _round(out["avg_gross_salary_6m"] * 12 / irs, 4)
        if out["avg_gross_salary_6m"] and irs else None)
    return out


HEADLINE_FIELDS = [
    "avg_net_salary_6m", "last_salary_month", "monthly_income_irs",
    "irs_total_income", "irs_year", "irs_yoy_growth", "self_employed_share",
    "n_income_sources", "activity_open", "has_pension", "employer_active",
    "irs_income_source",
]

CAVEATS = {
    "irs_total_income": "Declaração anual, valores brutos; em casais inclui os "
                        "dois titulares.",
    "avg_net_salary_6m": "Média dos últimos 6 meses registados, valores "
                         "líquidos, apenas do proponente.",
    "salary_vs_irs_ratio": "Salário bruto anualizado / IRS. Longe de 1 pode "
                           "indicar mudança de rendimento, outras fontes, ou "
                           "declaração conjunta.",
    "n_income_sources": "Fontes independentes presentes: IRS, salário, "
                        "Segurança Social, faturação, pensão.",
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


IRS_SOURCE_PT = {
    "current_declaration": "declaração atual",
    "previous_declaration": "declaração anterior",
    "missing": "em falta",
}


def render_profile_text(features):
    """Plain-text rendering of the income profile for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field.
    No judgment words, no score.
    """
    lines = []
    sal, irs = features["avg_net_salary_6m"], features["irs_total_income"]

    if sal is not None:
        head = (f"Rende cerca de {_eur(sal)}/mês líquidos (salário, média de 6 "
                f"meses; último registo {features['last_salary_month']}).")
    elif features["avg_regular_income_6m"]:
        head = (f"Rendimento regular de {_eur(features['avg_regular_income_6m'])}"
                "/mês (média de 6 meses, Segurança Social).")
    elif irs is not None:
        head = (f"Sem registos mensais de salário; IRS indica "
                f"{_eur(features['monthly_income_irs'])}/mês brutos.")
    else:
        head = "Sem rendimento verificável nas fontes disponíveis."
    if irs is not None:
        head += (f" IRS {features['irs_year']}: {_eur(irs)} anuais BRUTOS"
                 + (" (declaração conjunta: soma os dois titulares)."
                    if features["irs_is_joint"] else "."))
    lines.append(head)
    lines.append("")

    if features["has_salary_data"]:
        line = (f"  Salário          {_eur(sal)}/mês líquidos "
                f"(bruto {_eur(features['avg_gross_salary_6m'])}), "
                f"{features['salary_months_covered']} meses de histórico")
        lines.append(line)
        if features["variable_income_share_6m"]:
            lines.append(f"  Variável         "
                         f"{features['variable_income_share_6m']:.0%} do "
                         "líquido é remuneração variável")
    if irs is not None:
        comp = []
        if features["irs_annex_a_income"]:
            comp.append(f"trabalho dependente {_eur(features['irs_annex_a_income'])}")
        if features["irs_annex_b_income"]:
            comp.append(f"independente {_eur(features['irs_annex_b_income'])}")
        lines.append(f"  IRS {features['irs_year']}         {_eur(irs)} "
                     f"brutos/ano "
                     f"({IRS_SOURCE_PT[features['irs_income_source']]})"
                     + (f": {', '.join(comp)}" if comp else ""))
        if features["irs_yoy_growth"] is not None:
            lines.append(f"  Evolução         {features['irs_yoy_growth']:+.0%} "
                         f"face a {features['irs_prev_year']}")
    if features["activity_open"] is not None:
        status = "aberta" if features["activity_open"] else "cessada"
        line = (f"  Ativ. independ.  {status} "
                f"(desde {features['activity_start_year']}"
                + (f", {features['activity_tax_category']}"
                   if features["activity_tax_category"] else "") + ")")
        lines.append(line)
        if features["invoices_total_12m"]:
            lines.append(f"  Faturação        "
                         f"{_eur(features['invoices_total_12m'])} nos últimos "
                         f"12 meses registados")
    if features["has_pension"]:
        lines.append(f"  Pensão           "
                     f"{_eur(features['latest_pension_value'] or features['avg_pension_income_6m'])}"
                     "/mês")
    if features["salary_vs_irs_ratio"] is not None:
        lines.append(f"  Coerência        salário bruto anualizado = "
                     f"{features['salary_vs_irs_ratio']:.2f}x o IRS")
    lines.append(f"  Fontes           {features['n_income_sources']} de 5 "
                 "(IRS, salário, Seg. Social, faturação, pensão)")
    lines.append("")
    lines.append("  IRS é anual e bruto (casais: ambos os titulares); salário é "
                 "mensal, líquido e só do proponente.")
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
            vec = income_features(json.loads(row["value"]))
            print(f"--- {row['uuid'][:8]} ---")
            print(render_profile_text(vec))
            print()
