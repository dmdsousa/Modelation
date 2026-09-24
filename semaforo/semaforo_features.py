"""Semáforo por secção: triagem verde/amarelo/vermelho/cinzento.

Consome os oito vetores dos pacotes (via `proponent_profile`) e atribui a
cada secção do relatório uma cor de TRIAGEM com razões rastreáveis:

- VERDE     nada exige atenção neste bloco
- AMARELO   rever este bloco antes de decidir
- VERMELHO  atenção crítica: regra dura ou posição extrema face à população
- CINZENTO  sem dados para avaliar (nunca penaliza: ver contrato completeness)

NÃO é um score de crédito nem uma recomendação de aprovar/recusar: sem
outcomes suficientes, as regras são de política e de posição relativa, não
estatísticas de incumprimento.

Duas famílias de regras:
1. ABSOLUTAS, onde a cor não depende dos outros: insolvência confirmada,
   incumprimento ativo, empregador extinto, núcleo de dados incompleto.
2. RELATIVAS À POPULAÇÃO, para métricas contínuas: cortes no P75 (amarelo)
   e P90 (vermelho) da distribuição de data_full.csv, congelados em
   `BENCHMARKS` (recalibrar quando a base de referência mudar bumpa a
   versão). Cada razão diz a posição: "pior que 75% da população".

Nota de calibração: nesta população a carga mediana é 113% do rendimento
(artefacto despesas-do-agregado vs rendimento-individual, ver spec da
affordability), pelo que um residual negativo comum vale AMARELO; VERMELHO
fica reservado ao extremo populacional (P90).

Stdlib only. Consumidor: affordability/render_full_report (cabeçalhos e
bloco SEMÁFORO).
"""

FEATURES_VERSION = "1.1.0"

# Percentis da população de referência: data_full.csv, 565 proponentes,
# congelados em 2026-09-15. n por métrica varia (ver spec).
BENCHMARKS = {
    "dsti_p75": 0.5748, "dsti_p90": 0.8346,
    "burden_p75": 1.6720, "burden_p90": 2.4580,
    "revolving_share_p75": 0.2473,
    "crc_opened_12m_p90": 5,
    "monthly_cv_p90": 0.8839,
    "monthly_expenses_p90": 1840.75,
    "tenure_p25_months": 9,
    "variable_share_p90": 0.2072,
    "irs_yoy_p10": -0.1980,
    "bank_credit_12m_p90": 5,
}

VERDE, AMARELO, VERMELHO, CINZENTO = "VERDE", "AMARELO", "VERMELHO", "CINZENTO"

# Posicionamento contra a base (v1.1.0): grelhas completas de percentis,
# geradas em population_grids.py. Metricas de rendimento comparam-se dentro
# da mesma income_basis; sem grelha aplicavel, a posicao fica omissa.
from population_grids import GRIDS, GRID_POINTS  # noqa: E402


def percentile_rank(value, key):
    """Percentil (0-100, interpolado) de `value` na grelha `key`; None se
    a grelha nao existir ou o valor for None."""
    grid = GRIDS.get(key)
    if grid is None or value is None:
        return None
    if value <= grid[0]:
        return 0
    if value >= grid[-1]:
        return 100
    for i in range(1, len(grid)):
        if value <= grid[i]:
            lo, hi = grid[i - 1], grid[i]
            frac = 0.0 if hi == lo else (value - lo) / (hi - lo)
            return round(GRID_POINTS[i - 1]
                         + frac * (GRID_POINTS[i] - GRID_POINTS[i - 1]))
    return 100


def _eur0(v):
    return f"{v:,.0f}".replace(",", ".") + " EUR"


def _pos(label, shown, value, key):
    p = percentile_rank(value, key)
    return None if p is None else f"{label} {shown} = P{p}"

CONFIRMED_ADVERSE = {"at_debt_certificate", "ss_debt_certificate",
                     "debt_executions", "insolvency_confirmed",
                     "public_debts"}

SECTIONS = ["sintese", "dados", "adversos", "rendimento", "emprego",
            "responsabilidades", "banca", "despesas"]


def _status(cor, razoes, posicao=None):
    return {"cor": cor, "razoes": razoes,
            "posicao": [x for x in (posicao or []) if x]}


def _sintese(a):
    if a["residual_income"] is None or a["monthly_income"] is None:
        return _status(CINZENTO, ["sem rendimento ou despesas para avaliar"])
    razoes, cor = [], VERDE
    if a["burden_ratio"] is not None and a["burden_ratio"] >= BENCHMARKS["burden_p90"]:
        cor = VERMELHO
        razoes.append(f"gastos conhecidos são {a['burden_ratio']:.0%} do "
                      "rendimento: pior que 90% da população")
    if a["dsti"] is not None and a["dsti"] >= BENCHMARKS["dsti_p90"]:
        cor = VERMELHO
        razoes.append(f"DSTI {a['dsti']:.0%}: pior que 90% da população")
    if cor != VERMELHO:
        if a["residual_income"] < 0:
            cor = AMARELO
            razoes.append("o orçamento não fecha com os dados visíveis "
                          "(comum nesta população: ver caveat "
                          "agregado-vs-individual)")
        if a["dsti"] is not None and a["dsti"] >= BENCHMARKS["dsti_p75"]:
            cor = AMARELO
            razoes.append(f"DSTI {a['dsti']:.0%}: pior que 75% da população")
    basis = a["income_basis"]
    posicao = [
        _pos("carga", f"{a['burden_ratio']:.0%}" if a["burden_ratio"] is not None else "",
             a["burden_ratio"], f"burden_ratio__{basis}"),
        _pos("DSTI", f"{a['dsti']:.0%}" if a["dsti"] is not None else "",
             a["dsti"], f"dsti__{basis}"),
        _pos("esforço", f"{a['effort_rate']:.0%}" if a["effort_rate"] is not None else "",
             a["effort_rate"], f"effort_rate__{basis}"),
        _pos("sobra", _eur0(a["residual_income"]) if a["residual_income"] is not None else "",
             a["residual_income"], f"residual_income__{basis}"),
    ]
    if any(posicao):
        posicao.append(f"(base {basis})")
    return _status(cor, razoes or ["carga e sobra dentro do comum"], posicao)


def _dados(c):
    razoes, cor = [], VERDE
    if not c["core_complete"]:
        cor = VERMELHO
        razoes.append("dados de base incompletos: repetir a recolha "
                      f"(falta: {c['missing_core']})")
    if c["refetch_recommended"]:
        cor = VERMELHO
        razoes.append("falha técnica de recolha em "
                      f"{c['n_services_failed']} serviços")
    if c.get("income_none_suspect_gap"):
        cor = VERMELHO
        razoes.append("sem rendimento verificável apesar de vida económica "
                      "visível: provável falha de recolha")
    if cor == VERDE and c["n_consistency_flags"]:
        cor = AMARELO
        razoes.append(f"{c['n_consistency_flags']} inconsistência(s) entre "
                      "fontes (79% da população não tem nenhuma)")
    return _status(cor, razoes or ["fontes completas e coerentes"])


def _adversos(adv):
    markers = set((adv["adverse_markers"] or "").split(";")) - {""}
    if markers & CONFIRMED_ADVERSE:
        return _status(VERMELHO,
                       ["marcadores confirmados: regra dura: "
                        + ", ".join(sorted(markers & CONFIRMED_ADVERSE))])
    if "insolvency_flagged_unconfirmed" in markers:
        return _status(AMARELO, ["insolvência assinalada por confirmar: "
                                 "verificação manual obrigatória"])
    return _status(VERDE, ["sem registos adversos (90% da população também "
                           "não tem)"])


def _rendimento(i, c):
    if c["income_verification"] == "none":
        return _status(VERMELHO, ["nenhuma fonte de rendimento verificável"])
    razoes, cor = [], VERDE
    if c["income_verification"] == "irs_only":
        cor = AMARELO
        razoes.append("rendimento assenta só no IRS (anual, desfasado); sem "
                      "acesso à Seg. Social")
    if (i["irs_yoy_growth"] is not None
            and i["irs_yoy_growth"] <= BENCHMARKS["irs_yoy_p10"]):
        cor = AMARELO
        razoes.append(f"rendimento caiu {i['irs_yoy_growth']:.0%} face ao "
                      "ano anterior: pior que 90% da população")
    if (i["variable_income_share_6m"] is not None
            and i["variable_income_share_6m"] >= BENCHMARKS["variable_share_p90"]):
        cor = AMARELO
        razoes.append(f"{i['variable_income_share_6m']:.0%} do salário é "
                      "variável: acima de 90% da população")
    basis = None
    if i["avg_net_salary_6m"]:
        basis, val = "salary_net", i["avg_net_salary_6m"]
    elif i["monthly_income_irs"] and not i["avg_regular_income_6m"]:
        basis, val = "irs_gross", i["monthly_income_irs"]
    posicao = []
    if basis:
        posicao.append(_pos("rendimento", f"{_eur0(val)}/mês", val,
                            f"monthly_income__{basis}"))
        if posicao[-1]:
            posicao[-1] += f" (base {basis})"
    posicao.append(_pos("evolução",
                        f"{i['irs_yoy_growth']:+.0%}" if i["irs_yoy_growth"] is not None else "",
                        i["irs_yoy_growth"], "irs_yoy"))
    return _status(cor, razoes or ["rendimento verificado e estável"], posicao)


def _emprego(e):
    if not e["has_employment_data"]:
        return _status(CINZENTO, ["sem dados de emprego (gate da Seg. "
                                  "Social fechado): não penaliza"])
    razoes, cor = [], VERDE
    if e["employer_active"] == 0:
        cor = VERMELHO
        razoes.append("a empresa do empregador principal já não está ativa")
    if cor != VERMELHO:
        if (e["tenure_months"] is not None
                and e["tenure_months"] <= BENCHMARKS["tenure_p25_months"]):
            cor = AMARELO
            razoes.append(f"antiguidade {e['tenure_months']} meses: no "
                          "quartil mais baixo da população")
        if e["terminations_last_24m"]:
            cor = AMARELO
            razoes.append(f"{e['terminations_last_24m']} fim(ns) de contrato "
                          "nos últimos 24 meses")
        if (e["salary_gap_months"] or 0) >= 2:
            cor = AMARELO
            razoes.append(f"{e['salary_gap_months']} meses em falta na série "
                          "de salários")
    posicao = [_pos("antiguidade", f"{e['tenure_months']} meses" if e["tenure_months"] is not None else "",
                    e["tenure_months"], "tenure_months")]
    return _status(cor, razoes or ["emprego estável"], posicao)


def _responsabilidades(liab):
    razoes, cor = [], VERDE
    if (liab["n_in_default"] or 0) > 0:
        cor = VERMELHO
        razoes.append(f"incumprimento ativo na CRC: "
                      f"{liab['n_in_default']} crédito(s)")
    if liab["any_litigation"]:
        cor = VERMELHO
        razoes.append("crédito em litígio judicial")
    if cor != VERMELHO:
        if (liab["revolving_debt_share"] or 0) >= BENCHMARKS["revolving_share_p75"]:
            cor = AMARELO
            razoes.append(f"{liab['revolving_debt_share']:.0%} da dívida é "
                          "cartões/descobertos: pior que 75% da população")
        if (liab["n_opened_12m"] or 0) >= BENCHMARKS["crc_opened_12m_p90"]:
            cor = AMARELO
            razoes.append(f"{liab['n_opened_12m']} créditos novos em 12 "
                          "meses: acima de 90% da população")
        if liab["guarantor_exposure"]:
            cor = AMARELO
            razoes.append("exposição contingente como avalista")
    posicao = [
        _pos("dívida", _eur0(liab["total_debt"]) if liab["total_debt"] is not None else "",
             liab["total_debt"], "total_debt"),
        _pos("prestações", f"{_eur0(liab['total_installment'])}/mês" if liab["total_installment"] is not None else "",
             liab["total_installment"], "debt_service"),
        _pos("revolving", f"{liab['revolving_debt_share']:.0%}" if liab["revolving_debt_share"] is not None else "",
             liab["revolving_debt_share"], "revolving_share"),
        _pos("novos 12m", str(liab["n_opened_12m"]) if liab["n_opened_12m"] is not None else "",
             liab["n_opened_12m"], "crc_opened_12m"),
    ]
    return _status(cor, razoes or ["dívida servida sem sinais de tensão"], posicao)


def _banca(b):
    if not b["has_bcb_data"] or not b["n_as_titular"]:
        return _status(CINZENTO, ["sem contas como titular no mapa"])
    razoes, cor = [], VERDE
    if (b["n_credit_opened_12m"] or 0) >= BENCHMARKS["bank_credit_12m_p90"]:
        cor = AMARELO
        razoes.append(f"{b['n_credit_opened_12m']} aberturas de crédito em "
                      "12 meses: acima de 90% da população")
    posicao = [
        _pos("antiguidade", f"{b['oldest_account_years']:.0f} anos" if b["oldest_account_years"] is not None else "",
             b["oldest_account_years"], "oldest_account_years"),
        _pos("aberturas 12m", str(b["n_credit_opened_12m"]) if b["n_credit_opened_12m"] is not None else "",
             b["n_credit_opened_12m"], "bank_credit_12m"),
    ]
    return _status(cor, razoes or ["pegada bancária sem sinais de tensão"], posicao)


def _despesas(e):
    if not e["has_spend_data"]:
        return _status(CINZENTO, ["sem dados de e-fatura"])
    razoes, cor = [], VERDE
    if (e["monthly_cv"] or 0) >= BENCHMARKS["monthly_cv_p90"]:
        cor = AMARELO
        razoes.append(f"variação mensal {e['monthly_cv']:.0%}: mais "
                      "irregular que 90% da população")
    if (e["monthly_expenses"] or 0) >= BENCHMARKS["monthly_expenses_p90"]:
        cor = AMARELO
        razoes.append("nível de despesa acima de 90% da população (ler em "
                      "conjunto com o rendimento, na SÍNTESE)")
    if (e["months_observed"] or 0) < 6 and e["has_spend_data"]:
        cor = AMARELO
        razoes.append(f"apenas {e['months_observed']} meses observados")
    posicao = [
        _pos("despesa", f"{_eur0(e['monthly_expenses'])}/mês" if e["monthly_expenses"] is not None else "",
             e["monthly_expenses"], "monthly_expenses"),
        _pos("volatilidade", f"{e['monthly_cv']:.0%}" if e["monthly_cv"] is not None else "",
             e["monthly_cv"], "monthly_cv"),
    ]
    return _status(cor, razoes or ["padrão de despesa dentro do comum"], posicao)


def semaforo(vectors):
    """Cores por secção a partir dos vetores de proponent_profile()."""
    return {
        "sintese": _sintese(vectors["affordability"]),
        "dados": _dados(vectors["completeness"]),
        "adversos": _adversos(vectors["adverse"]),
        "rendimento": _rendimento(vectors["incomes"], vectors["completeness"]),
        "emprego": _emprego(vectors["employment"]),
        "responsabilidades": _responsabilidades(vectors["liabilities"]),
        "banca": _banca(vectors["banking"]),
        "despesas": _despesas(vectors["expenses"]),
    }


def semaforo_features(vectors):
    """Vetor plano (para CSV/serving): <seccao>_cor e <seccao>_razoes."""
    st = semaforo(vectors)
    out = {"features_version": FEATURES_VERSION}
    for name in SECTIONS:
        out[f"{name}_cor"] = st[name]["cor"]
        out[f"{name}_razoes"] = "; ".join(st[name]["razoes"])
        out[f"{name}_posicao"] = "; ".join(st[name].get("posicao") or []) or None
    out["n_vermelhos"] = sum(1 for s in st.values() if s["cor"] == VERMELHO)
    out["n_amarelos"] = sum(1 for s in st.values() if s["cor"] == AMARELO)
    return out


TITULO_PT = {
    "sintese": "SÍNTESE", "dados": "DADOS", "adversos": "REGISTOS ADVERSOS",
    "rendimento": "RENDIMENTO", "emprego": "EMPREGO",
    "responsabilidades": "RESPONSABILIDADES", "banca": "BANCA",
    "despesas": "DESPESAS",
}


def render_semaforo_text(statuses):
    """Bloco SEMÁFORO em texto (pt-PT), uma linha por secção."""
    lines = []
    for name in SECTIONS:
        s = statuses[name]
        lines.append(f"  {TITULO_PT[name]:18s}{s['cor']:9s} "
                     + "; ".join(s["razoes"]))
        if s.get("posicao"):
            lines.append(" " * 20 + "posição: " + "; ".join(s["posicao"]))
    lines.append("")
    lines.append("  Triagem, não veredicto: VERMELHO = atenção crítica, "
                 "AMARELO = rever, CINZENTO = sem dados (não penaliza). "
                 "P50 = mediana da base (data_full.csv, 565): P90 = pior/mais "
                 "alto que 90% da base. Rendimento compara-se dentro da "
                 "mesma base.")
    return "\n".join(lines)
