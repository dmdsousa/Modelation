"""Semáforo por secção: triagem verde/amarelo/vermelho/cinzento, com
comparação profunda contra a base de referência.

Consome os vetores dos pacotes (via `proponent_profile`) e produz, por
secção do relatório:

- COR de triagem: VERDE (nada exige atenção), AMARELO (rever), VERMELHO
  (regra dura ou extremo populacional), CINZENTO (sem dados: nunca penaliza).
- RAZÕES da cor, rastreáveis a campos.
- POSIÇÃO contra a base: percentil exato por métrica-chave, com marca de
  direção de risco ([atenção] no extremo desfavorável, [favorável] no
  oposto), porque P89 em revolving é mau e P89 em antiguidade bancária é bom
  e o leitor não deve precisar de o saber de cor.

E, transversal às secções:

- PARES: as métricas de affordability posicionadas também entre proponentes
  de rendimento semelhante (tercis dentro da mesma income_basis), porque a
  base inteira mistura realidades.
- VIZINHOS: os 20 proponentes mais parecidos da base (rendimento, idade,
  dívida, despesa, na mesma basis) e os seus desfechos: taxa de
  incumprimento CRC, registos adversos, sobra mediana.
- ASSINATURA: as três características que mais afastam a pessoa da mediana
  da base, com direção.

NÃO é um score de crédito nem uma recomendação: as regras são de política e
posição relativa. Grelhas, pares e vizinhos vêm de `population_grids.py`
(GERADO a partir da base; regenerar quando a base mudar bumpa a versão).

Stdlib only. Consumidor: affordability/render_full_report.
"""

from population_grids import (DEFAULT_PROXIMITY_GRIDS, DEFAULT_PROXIMITY_K,
                              DEFAULT_PROXIMITY_STATS, GRID_POINTS, GRIDS,
                              NEIGH_FEATURES, NEIGHBOURS, PEER_CUTS,
                              PEER_GRIDS, PEER_N)

FEATURES_VERSION = "1.3.0"

# Benchmarks de cor (P75/P90 da base, congelados 2026-09-15): as REGRAS de
# cor mantêm-se as da v1.0.0; o posicionamento é aditivo.
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

CONFIRMED_ADVERSE = {"at_debt_certificate", "ss_debt_certificate",
                     "debt_executions", "insolvency_confirmed",
                     "public_debts"}

SECTIONS = ["sintese", "dados", "adversos", "rendimento", "emprego",
            "responsabilidades", "banca", "despesas"]

# direção do risco por métrica (base da grelha, sem sufixo de basis):
# True = quanto mais alto, pior
HIGH_IS_BAD = {
    "burden_ratio": True, "dsti": True, "effort_rate": True,
    "residual_income": False, "monthly_income": False, "irs_yoy": False,
    "total_debt": True, "debt_service": True, "revolving_share": True,
    "crc_opened_12m": True, "oldest_account_years": False,
    "bank_credit_12m": True, "monthly_expenses": True, "monthly_cv": True,
    "tenure_months": False,
}
EXTREME_HI, EXTREME_LO = 85, 15
K_VIZINHOS = 20


def percentile_rank(value, key, grids=None):
    """Percentil (0-100, interpolado) de `value` na grelha `key`."""
    grid = (grids or GRIDS).get(key)
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


def _mark(metric, p):
    """Marca de direção nos extremos: [atenção] / [favorável]."""
    if p is None:
        return ""
    bad_high = HIGH_IS_BAD.get(metric)
    if bad_high is None:
        return ""
    if (p >= EXTREME_HI and bad_high) or (p <= EXTREME_LO and not bad_high):
        return " [atenção]"
    if (p >= EXTREME_HI and not bad_high) or (p <= EXTREME_LO and bad_high):
        return " [favorável]"
    return ""


def _pos(label, shown, value, key, metric, grids=None):
    """Uma entrada de posicionamento: texto + material para a assinatura."""
    p = percentile_rank(value, key, grids)
    if p is None:
        return None
    return {"text": f"{label} {shown} = P{p}{_mark(metric, p)}",
            "label": label, "p": p, "metric": metric}


def _status(cor, razoes, posicao=None):
    entries = [e for e in (posicao or []) if e]
    return {"cor": cor, "razoes": razoes,
            "posicao": [e["text"] if isinstance(e, dict) else e
                        for e in entries],
            "_entries": [e for e in entries if isinstance(e, dict)]}


# ---------------------------------------------------------------- secções

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
        _pos("carga", f"{a['burden_ratio']:.0%}", a["burden_ratio"],
             f"burden_ratio__{basis}", "burden_ratio")
        if a["burden_ratio"] is not None else None,
        _pos("DSTI", f"{a['dsti']:.0%}", a["dsti"],
             f"dsti__{basis}", "dsti") if a["dsti"] is not None else None,
        _pos("esforço", f"{a['effort_rate']:.0%}", a["effort_rate"],
             f"effort_rate__{basis}", "effort_rate")
        if a["effort_rate"] is not None else None,
        _pos("sobra", _eur0(a["residual_income"]), a["residual_income"],
             f"residual_income__{basis}", "residual_income"),
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
    posicao = []
    if i["avg_net_salary_6m"]:
        e = _pos("rendimento", f"{_eur0(i['avg_net_salary_6m'])}/mês",
                 i["avg_net_salary_6m"], "monthly_income__salary_net",
                 "monthly_income")
        if e:
            e["text"] += " (base salary_net)"
            posicao.append(e)
    elif i["monthly_income_irs"] and not i["avg_regular_income_6m"]:
        e = _pos("rendimento", f"{_eur0(i['monthly_income_irs'])}/mês",
                 i["monthly_income_irs"], "monthly_income__irs_gross",
                 "monthly_income")
        if e:
            e["text"] += " (base irs_gross)"
            posicao.append(e)
    if i["irs_yoy_growth"] is not None:
        posicao.append(_pos("evolução", f"{i['irs_yoy_growth']:+.0%}",
                            i["irs_yoy_growth"], "irs_yoy", "irs_yoy"))
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
    posicao = [_pos("antiguidade", f"{e['tenure_months']} meses",
                    e["tenure_months"], "tenure_months", "tenure_months")
               if e["tenure_months"] is not None else None]
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
        _pos("dívida", _eur0(liab["total_debt"]), liab["total_debt"],
             "total_debt", "total_debt")
        if liab["total_debt"] is not None else None,
        _pos("prestações", f"{_eur0(liab['total_installment'])}/mês",
             liab["total_installment"], "debt_service", "debt_service")
        if liab["total_installment"] is not None else None,
        _pos("revolving", f"{liab['revolving_debt_share']:.0%}",
             liab["revolving_debt_share"], "revolving_share",
             "revolving_share")
        if liab["revolving_debt_share"] is not None else None,
        _pos("novos 12m", str(liab["n_opened_12m"]), liab["n_opened_12m"],
             "crc_opened_12m", "crc_opened_12m")
        if liab["n_opened_12m"] is not None else None,
    ]
    return _status(cor, razoes or ["dívida servida sem sinais de tensão"],
                   posicao)


def _banca(b):
    if not b["has_bcb_data"] or not b["n_as_titular"]:
        return _status(CINZENTO, ["sem contas como titular no mapa"])
    razoes, cor = [], VERDE
    if (b["n_credit_opened_12m"] or 0) >= BENCHMARKS["bank_credit_12m_p90"]:
        cor = AMARELO
        razoes.append(f"{b['n_credit_opened_12m']} aberturas de crédito em "
                      "12 meses: acima de 90% da população")
    posicao = [
        _pos("antiguidade", f"{b['oldest_account_years']:.0f} anos",
             b["oldest_account_years"], "oldest_account_years",
             "oldest_account_years")
        if b["oldest_account_years"] is not None else None,
        _pos("aberturas 12m", str(b["n_credit_opened_12m"]),
             b["n_credit_opened_12m"], "bank_credit_12m", "bank_credit_12m")
        if b["n_credit_opened_12m"] is not None else None,
    ]
    return _status(cor, razoes or ["pegada bancária sem sinais de tensão"],
                   posicao)


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
        _pos("despesa", f"{_eur0(e['monthly_expenses'])}/mês",
             e["monthly_expenses"], "monthly_expenses", "monthly_expenses")
        if e["monthly_expenses"] is not None else None,
        _pos("volatilidade", f"{e['monthly_cv']:.0%}", e["monthly_cv"],
             "monthly_cv", "monthly_cv")
        if e["monthly_cv"] is not None else None,
    ]
    return _status(cor, razoes or ["padrão de despesa dentro do comum"],
                   posicao)


# ------------------------------------------------ comparações transversais

def _peer_cell(basis, income):
    cuts = PEER_CUTS.get(basis)
    if cuts is None or income is None:
        return None
    return "baixo" if income <= cuts[0] else \
           "medio" if income <= cuts[1] else "alto"


PEER_LABEL = {"baixo": "rendimento baixo", "medio": "rendimento médio",
              "alto": "rendimento alto"}


def pares(vectors):
    """Métricas de affordability posicionadas entre rendimentos semelhantes
    (tercil de rendimento dentro da mesma income_basis)."""
    a, liab, e = (vectors["affordability"], vectors["liabilities"],
                  vectors["expenses"])
    basis = a["income_basis"]
    cell = _peer_cell(basis, a["monthly_income"])
    if cell is None:
        return None
    n = PEER_N.get(f"{basis}__{cell}")
    entries = []
    for label, shown, value, metric in (
            ("carga", f"{a['burden_ratio']:.0%}" if a["burden_ratio"] is not None else None,
             a["burden_ratio"], "burden_ratio"),
            ("dívida", _eur0(liab["total_debt"]) if liab["total_debt"] is not None else None,
             liab["total_debt"], "total_debt"),
            ("despesa", f"{_eur0(e['monthly_expenses'])}/mês" if e["monthly_expenses"] is not None else None,
             e["monthly_expenses"], "monthly_expenses"),
            ("sobra", _eur0(a["residual_income"]) if a["residual_income"] is not None else None,
             a["residual_income"], "residual_income")):
        if shown is None:
            continue
        p = percentile_rank(value, f"{metric}__{basis}__{cell}", PEER_GRIDS)
        if p is not None:
            entries.append(f"{label} {shown} = P{p}{_mark(metric, p)}")
    if not entries:
        return None
    return {"grupo": f"{PEER_LABEL[cell]} (base {basis}, n={n})",
            "posicao": entries}


def vizinhos(vectors, k=K_VIZINHOS):
    """Os k proponentes mais parecidos da base (mesma basis; z-distância em
    rendimento, idade, dívida total e despesa) e os seus desfechos."""
    a, liab, e = (vectors["affordability"], vectors["liabilities"],
                  vectors["expenses"])
    basis = a["income_basis"]
    ref = NEIGHBOURS.get(basis)
    feats = {"monthly_income": a["monthly_income"], "age": e["age"],
             "total_debt": liab["total_debt"],
             "monthly_expenses": e["monthly_expenses"]}
    if ref is None or any(feats[f] is None for f in NEIGH_FEATURES):
        return None
    z = [(feats[f] - ref["mean"][i]) / ref["std"][i]
         for i, f in enumerate(NEIGH_FEATURES)]
    dists = []
    for j, row in enumerate(ref["rows"]):
        dj = sum((z[i] - (row[i] - ref["mean"][i]) / ref["std"][i]) ** 2
                 for i in range(len(NEIGH_FEATURES)))
        dists.append((dj, j))
    dists.sort()
    idx = [j for _, j in dists[1:k + 1]]  # o próprio é o vizinho a dist. 0
    if not idx:
        return None
    defaults = sum(ref["in_default"][j] for j in idx)
    adverse = sum(ref["any_adverse"][j] for j in idx)
    residuals = sorted(ref["residual"][j] for j in idx
                       if ref["residual"][j] is not None)
    med_res = residuals[len(residuals) // 2] if residuals else None
    return {"k": len(idx), "pct_incumprimento": round(100 * defaults / len(idx)),
            "pct_adversos": round(100 * adverse / len(idx)),
            "sobra_mediana": med_res, "basis": basis}


def proximidade_defaults(vectors):
    """Distância de semelhança entre o proponente e os incumpridores da base.

    racio = dist. média aos 5 CUMPRIDORES mais parecidos / dist. média aos 5
    INCUMPRIDORES mais parecidos (z-distância em rendimento, idade, dívida e
    despesa, na mesma income_basis). > 1 = o perfil está mais próximo dos
    incumpridores. O percentil vem da distribuição do rácio na própria base
    (leave-one-out, congelada). SEMELHANÇA DE PERFIL, NÃO PROBABILIDADE."""
    a, liab, e = (vectors["affordability"], vectors["liabilities"],
                  vectors["expenses"])
    basis = a["income_basis"]
    ref = NEIGHBOURS.get(basis)
    feats = {"monthly_income": a["monthly_income"], "age": e["age"],
             "total_debt": liab["total_debt"],
             "monthly_expenses": e["monthly_expenses"]}
    if ref is None or any(feats[f] is None for f in NEIGH_FEATURES):
        return None
    z = [(feats[f] - ref["mean"][i]) / ref["std"][i]
         for i, f in enumerate(NEIGH_FEATURES)]
    d_def, d_ok = [], []
    for j, row in enumerate(ref["rows"]):
        dj = sum((z[i] - (row[i] - ref["mean"][i]) / ref["std"][i]) ** 2
                 for i in range(len(NEIGH_FEATURES))) ** 0.5
        if dj < 1e-9:
            continue  # o próprio, quando pertence à base
        (d_def if ref["in_default"][j] else d_ok).append(dj)
    if len(d_def) < DEFAULT_PROXIMITY_K or len(d_ok) < DEFAULT_PROXIMITY_K:
        return None
    md = sum(sorted(d_def)[:DEFAULT_PROXIMITY_K]) / DEFAULT_PROXIMITY_K
    mo = sum(sorted(d_ok)[:DEFAULT_PROXIMITY_K]) / DEFAULT_PROXIMITY_K
    if md <= 0:
        return None
    racio = round(mo / md, 3)
    p = percentile_rank(racio, basis, DEFAULT_PROXIMITY_GRIDS)
    # SEM marca de risco deliberadamente: na base, o racio nao discrimina
    # incumpridores (AUC 0.496; medianas iguais 0.65). E descritivo.
    return {"racio": racio, "percentil": p, "basis": basis,
            "n_defaulters": DEFAULT_PROXIMITY_STATS[basis]["n_defaulters"]}


def assinatura(statuses, top=3):
    """As `top` métricas que mais afastam a pessoa da mediana da base."""
    entries = []
    for st in statuses.values():
        entries += st.get("_entries", [])
    scored = sorted(entries, key=lambda ent: abs(ent["p"] - 50), reverse=True)
    out = []
    for ent in scored[:top]:
        if abs(ent["p"] - 50) < 25:
            break
        high = ent["p"] > 50
        bad = HIGH_IS_BAD.get(ent["metric"])
        tone = ("" if bad is None else
                " [atenção]" if (high and bad) or (not high and not bad)
                else " [favorável]")
        direcao = "muito acima" if ent["p"] >= 85 else \
                  "acima" if high else \
                  "muito abaixo" if ent["p"] <= 15 else "abaixo"
        out.append(f"{ent['label']} {direcao} da base (P{ent['p']}){tone}")
    return out


# ------------------------------------------------------------------- API

def semaforo(vectors):
    """Cores + posições por secção a partir dos vetores."""
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
    """Vetor plano (para CSV/serving)."""
    st = semaforo(vectors)
    out = {"features_version": FEATURES_VERSION}
    for name in SECTIONS:
        out[f"{name}_cor"] = st[name]["cor"]
        out[f"{name}_razoes"] = "; ".join(st[name]["razoes"])
        out[f"{name}_posicao"] = "; ".join(st[name]["posicao"]) or None
    out["n_vermelhos"] = sum(1 for s in st.values() if s["cor"] == VERMELHO)
    out["n_amarelos"] = sum(1 for s in st.values() if s["cor"] == AMARELO)
    sig = assinatura(st)
    out["assinatura"] = "; ".join(sig) if sig else None
    pr = pares(vectors)
    out["pares_grupo"] = pr["grupo"] if pr else None
    out["pares_posicao"] = "; ".join(pr["posicao"]) if pr else None
    px = proximidade_defaults(vectors)
    out["proximidade_defaults_racio"] = px["racio"] if px else None
    out["proximidade_defaults_percentil"] = px["percentil"] if px else None
    vz = vizinhos(vectors)
    if vz:
        out["vizinhos_k"] = vz["k"]
        out["vizinhos_pct_incumprimento"] = vz["pct_incumprimento"]
        out["vizinhos_pct_adversos"] = vz["pct_adversos"]
        out["vizinhos_sobra_mediana"] = vz["sobra_mediana"]
    else:
        out["vizinhos_k"] = None
        out["vizinhos_pct_incumprimento"] = None
        out["vizinhos_pct_adversos"] = None
        out["vizinhos_sobra_mediana"] = None
    return out


TITULO_PT = {
    "sintese": "SÍNTESE", "dados": "DADOS", "adversos": "REGISTOS ADVERSOS",
    "rendimento": "RENDIMENTO", "emprego": "EMPREGO",
    "responsabilidades": "RESPONSABILIDADES", "banca": "BANCA",
    "despesas": "DESPESAS",
}


def render_semaforo_text(statuses, vectors=None):
    """Bloco SEMÁFORO em texto (pt-PT)."""
    lines = []
    sig = assinatura(statuses)
    if sig:
        lines.append("  Assinatura       destaca-se da base por: "
                     + "; ".join(sig))
        lines.append("")
    for name in SECTIONS:
        s = statuses[name]
        lines.append(f"  {TITULO_PT[name]:18s}{s['cor']:9s} "
                     + "; ".join(s["razoes"]))
        if s["posicao"]:
            lines.append(" " * 20 + "posição: " + "; ".join(s["posicao"]))
    if vectors is not None:
        pr = pares(vectors)
        if pr:
            lines.append("")
            lines.append(f"  Pares            entre {pr['grupo']}: "
                         + "; ".join(pr["posicao"]))
        vz = vizinhos(vectors)
        if vz:
            sobra = (_eur0(vz["sobra_mediana"]) + "/mês"
                     if vz["sobra_mediana"] is not None else "n/d")
            lines.append(f"  Semelhantes      os {vz['k']} mais parecidos da "
                         f"base (rendimento, idade, dívida, despesa): "
                         f"{vz['pct_incumprimento']}% em incumprimento; "
                         f"{vz['pct_adversos']}% com registos adversos; "
                         f"sobra mediana {sobra}")
        px = proximidade_defaults(vectors)
        if px:
            lado = ("MAIS PRÓXIMO dos incumpridores do que dos cumpridores"
                    if px["racio"] > 1 else
                    "mais próximo dos cumpridores do que dos incumpridores")
            lines.append(f"  Prox. defaults   rácio {px['racio']:.2f} ({lado}) "
                         f"= P{px['percentil']} "
                         f"({px['n_defaulters']} incumpridores na base "
                         f"{px['basis']}; sem sinal medido: AUC 0.50 nesta "
                         "base)")
    lines.append("")
    lines.append("  Triagem, não veredicto: VERMELHO = atenção crítica, "
                 "AMARELO = rever, CINZENTO = sem dados (não penaliza). "
                 "P50 = mediana da base (data_full.csv, 565); [atenção] / "
                 "[favorável] marcam extremos na direção do risco. "
                 "Rendimento e rácios comparam-se dentro da mesma base. "
                 "Proximidade a incumpridores é semelhança de perfil, NÃO "
                 "probabilidade de incumprimento.")
    return "\n".join(lines)
