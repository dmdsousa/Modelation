"""Employment-stability features from a hAPI proponent snapshot.

Layer 1 (`employment_features`): the full, versioned feature vector combining
`LastJobInfo.Job` (employer, tenure, first/last payment), `Income.workDependent`
(Social Security income records: qualification, paying entities),
`EndOfWorkContractsList` (contract terminations) and the NetSalary series
(continuity). Consumers: the credit score model and layer 2.
Layer 2 (`display_profile` / `render_profile_text`): the client/analyst view.

Input: the parsed snapshot JSON (the `value` document of a proponent), as
captured at application time.

Conventions:
- Missing/uncomputable values are None, never 0. Presence flags say why.
- Employment data arrives through the Social Security gate (see the
  completeness contract): absence usually means no data access, not
  unemployment. `has_employment_data` distinguishes the two readings.
- The reference month (`anchor_month`) is the latest month observed across
  salary and workDependent records; recency measures use it.
- "Main job" = the job record with the longest Duration.

Stdlib only. Sibling projects: ../expenses/, ../liabilities/, ../incomes/,
../completeness/.
"""

FEATURES_VERSION = "1.0.0"

RECENT_TERMINATION_MONTHS = 24


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _ym(month_index):
    if month_index is None:
        return None
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def _pay_month(payment):
    if not payment or not payment.get("Year") or not payment.get("Month"):
        return None
    return int(payment["Year"]) * 12 + int(payment["Month"]) - 1


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def employment_features(profile):
    """Full layer-1 feature vector (dict) from a parsed snapshot document."""
    out = {"features_version": FEATURES_VERSION}

    jobs = _dig(profile, "LastJobInfo", "Job") or []
    wd = [_dig(e, "Income") for e in
          (_dig(profile, "Income", "workDependent") or [])]
    wd = [e for e in wd if e]
    terminations = profile.get("EndOfWorkContractsList") or []
    salary = profile.get("NetSalary") or []

    out["has_employment_data"] = int(bool(jobs or wd or salary))
    out["n_job_records"] = len(jobs) or None

    # anchor: latest observed month across salary and SS income records
    months = [int(e["Year"]) * 12 + int(e["Month"]) - 1
              for src in (salary, wd) for e in src
              if e.get("Year") and e.get("Month")]
    anchor = max(months) if months else None
    out["anchor_month"] = _ym(anchor)

    fields = ["employer_active", "employer_region", "employer_cae",
              "tenure_months", "job_first_payment_month",
              "job_last_payment_month", "first_payment_amount",
              "last_payment_amount", "salary_growth_over_tenure",
              "n_paying_entities", "is_board_member",
              "n_terminations", "last_termination_month",
              "months_since_last_termination", "terminations_last_24m",
              "salary_streak_months", "salary_gap_months"]
    for f in fields:
        out[f] = None

    # main job = longest Duration
    if jobs:
        main = max(jobs, key=lambda j: j.get("Duration") or 0)
        company = main.get("Company") or {}
        out["employer_active"] = int(company.get("status") == "active")
        out["employer_region"] = _dig(company, "geo", "region") or None
        cae = company.get("cae") or []
        out["employer_cae"] = cae[0] if cae else None
        out["tenure_months"] = main.get("Duration")
        first, last = main.get("FirstPayment"), main.get("LastPayment")
        out["job_first_payment_month"] = _ym(_pay_month(first))
        out["job_last_payment_month"] = _ym(_pay_month(last))
        out["first_payment_amount"] = _round((first or {}).get("Amount"))
        out["last_payment_amount"] = _round((last or {}).get("Amount"))
        fa, la = out["first_payment_amount"], out["last_payment_amount"]
        # growth only between FULL months: a partial first month (admission
        # mid-month, Days < 28) would fake spectacular growth
        full_months = ((first or {}).get("Days", 0) >= 28
                       and (last or {}).get("Days", 0) >= 28)
        if fa and la and fa > 0 and full_months:
            out["salary_growth_over_tenure"] = _round(la / fa - 1, 4)

    # SS income records: employer diversity + qualification
    if wd:
        out["n_paying_entities"] = len({e.get("PayingEntityNISS")
                                        for e in wd
                                        if e.get("PayingEntityNISS")}) or None
        out["is_board_member"] = int(any(e.get("QualificationType") == "MOE"
                                         for e in wd))

    # contract terminations
    term_months = [int(t["EndDate"][:4]) * 12 + int(t["EndDate"][5:7]) - 1
                   for t in terminations if t.get("EndDate")]
    out["n_terminations"] = len(term_months) or None
    if term_months:
        last_term = max(term_months)
        out["last_termination_month"] = _ym(last_term)
        if anchor is not None:
            out["months_since_last_termination"] = anchor - last_term
            out["terminations_last_24m"] = sum(
                1 for m in term_months
                if anchor - m < RECENT_TERMINATION_MONTHS)

    # salary continuity (Month=0 aggregate rows excluded)
    sal_m = sorted({int(e["Year"]) * 12 + int(e["Month"]) - 1
                    for e in salary if e.get("Year") and e.get("Month")})
    if sal_m:
        out["salary_gap_months"] = (sal_m[-1] - sal_m[0] + 1 - len(sal_m)
                                    if len(sal_m) > 1 else 0)
        streak = 1
        for prev, cur in zip(reversed(sal_m[:-1]), reversed(sal_m[1:])):
            if cur - prev == 1:
                streak += 1
            else:
                break
        out["salary_streak_months"] = streak
    return out


HEADLINE_FIELDS = [
    "has_employment_data", "employer_active", "tenure_months",
    "salary_growth_over_tenure", "salary_streak_months", "salary_gap_months",
    "n_terminations", "months_since_last_termination", "terminations_last_24m",
    "is_board_member", "n_paying_entities", "anchor_month",
]

CAVEATS = {
    "has_employment_data": "Os dados de emprego chegam pelo acesso à Segurança "
                           "Social: a ausência normalmente significa falta de "
                           "acesso aos dados, não desemprego.",
    "tenure_months": "Antiguidade no empregador principal (registo com maior "
                     "duração), em meses.",
    "salary_growth_over_tenure": "Último pagamento / primeiro pagamento - 1, "
                                 "no empregador principal. Não anualizado.",
    "n_terminations": "Fins de contrato registados na Segurança Social; podem "
                      "ser antigos: ver months_since_last_termination.",
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
    """Plain-text employment-stability analysis for humans (pt-PT).

    Purely mechanical: every sentence traces to a layer-1 field.
    """
    f = features
    if not f["has_employment_data"]:
        return ("Sem registos de emprego nas fontes disponíveis (dados de "
                "emprego dependem do acesso à Segurança Social: ausência não "
                "significa desemprego).\n\n"
                "  Dados da Segurança Social.")

    lines = []
    head_parts = []
    if f["tenure_months"] is not None:
        years = f["tenure_months"] / 12
        tenure = (_n(f["tenure_months"], "mês", "meses")
                  if f["tenure_months"] < 24 else f"{years:.0f} anos")
        status = ("ativa" if f["employer_active"] else
                  "INATIVA" if f["employer_active"] is not None else "n/d")
        head_parts.append(f"{tenure} de casa no empregador principal "
                          f"(empresa {status})")
    if f["salary_streak_months"]:
        head_parts.append("salário contínuo há "
                          + _n(f["salary_streak_months"], "mês", "meses"))
    if f["is_board_member"]:
        head_parts.append("membro de órgão estatutário (MOE)")
    head = ("Emprego: " + "; ".join(head_parts) + "."
            if head_parts else "Registos de emprego presentes mas escassos.")
    if f["n_terminations"]:
        recent = f["terminations_last_24m"] or 0
        head += (f" {_n(f['n_terminations'], 'fim de contrato registado', 'fins de contrato registados')}"
                 + (f", {recent} nos últimos 24 meses."
                    if recent else
                    f", o último há {f['months_since_last_termination']} meses."))
    else:
        head += " Sem fins de contrato registados."
    lines.append(head)
    lines.append("")

    if f["tenure_months"] is not None:
        emp = [f"antiguidade {_n(f['tenure_months'], 'mês', 'meses')} "
               f"({f['job_first_payment_month']} a {f['job_last_payment_month']})"]
        if f["employer_region"]:
            emp.append(f"região {f['employer_region']}")
        if f["employer_active"] is not None:
            emp.append("empresa ativa" if f["employer_active"]
                       else "empresa NÃO ativa")
        lines.append(f"  Empregador       {'; '.join(emp)}")
    if f["salary_growth_over_tenure"] is not None:
        lines.append(f"  Progressão       {f['salary_growth_over_tenure']:+.0%} "
                     f"desde a admissão ({_eur(f['first_payment_amount'])} -> "
                     f"{_eur(f['last_payment_amount'])}, valores brutos)")
    if f["n_paying_entities"]:
        lines.append(f"  Entidades        "
                     f"{_n(f['n_paying_entities'], 'entidade pagadora', 'entidades pagadoras')} "
                     "nos registos da Seg. Social")
    if f["salary_streak_months"] is not None:
        cont = "contínuo há " + _n(f["salary_streak_months"], "mês", "meses")
        if f["salary_gap_months"]:
            cont += (f"; {f['salary_gap_months']} meses em falta no histórico "
                     "(interrupções ou falhas de recolha)")
        lines.append(f"  Continuidade     {cont}")
    if f["n_terminations"]:
        lines.append(f"  Fins de contrato {f['n_terminations']} no total, "
                     f"último em {f['last_termination_month']} "
                     f"(há {f['months_since_last_termination']} meses)")
    lines.append("")
    lines.append("  Dados da Segurança Social; a antiguidade cobre apenas o "
                 "período com registos observáveis.")
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
            if len(seen) > 4:
                break
            vec = employment_features(json.loads(row["value"]))
            print(f"--- {row['uuid'][:8]} ---")
            print(render_profile_text(vec))
            print()
