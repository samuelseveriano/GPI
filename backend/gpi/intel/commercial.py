"""Camada de inteligência comercial (v0.8.1): classes de evidência A–F, coberturas com fórmula, nova estrutura de scores,
três níveis do dossiê, radar de candidatos e alertas comerciais/estatísticos/de qualidade.

Regras: grupos de evidência não são intercambiáveis; dados ausentes NÃO recebem nota neutra; Wikipédia sozinha nunca gera
ranking comercial; o score é prioridade de investigação, não probabilidade de sucesso.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import semantics as S

EVIDENCE_CLASS = {S.DEMAND: ("A", "Demanda efetiva"), S.COMMERCIAL: ("B", "Intenção comercial"),
                  S.SEARCH: ("C", "Interesse de pesquisa"), S.SOCIAL: ("D", "Atenção social"),
                  S.PUBLIC: ("E", "Atenção pública"), S.TRADE: ("F", "Comércio exterior"),
                  S.OFFER: ("—", "Oferta e preços"), S.MACRO: ("—", "Contexto macroeconômico")}
DEMAND_SIDE = (S.DEMAND, S.COMMERCIAL, S.SEARCH)
STATUS = ("calculável", "parcial", "evidência insuficiente", "não avaliado")


def evidence_class(tipo: str | None) -> dict:
    c, n = EVIDENCE_CLASS.get(tipo, ("—", "não classificado"))
    return {"classe": c, "classe_nome": n}


# --------------------------------------------------------------------------------------------- coberturas (seção 6)
def coverage(products: dict, monitored: int, geo_markets=("BR", "US", "CN")) -> dict:
    n = max(1, monitored)
    any_ev = sum(1 for p in products.values() if p["evidencias"])
    comm = sum(1 for p in products.values() if any(e["tipo"] in (S.COMMERCIAL, S.SEARCH, S.DEMAND) and _eligible_signal(e)
                                                   for e in p["evidencias"]))
    fc = sum(1 for p in products.values() if any(e["elegibilidade"].get("previsao") for e in p["evidencias"]))
    per_obs = per_exp = 0
    for p in products.values():
        for e in p["evidencias"]:
            if e["frequencia"] == "mes" and e.get("observacoes_n"):
                per_obs += int(e.get("completude_n") or e["observacoes_n"])
                per_exp += int(e["observacoes_n"])
    geo = {}
    for m in geo_markets + tuple(k for k in ("LANG:pt", "LANG:en", "LANG:zh")):
        geo[m] = {"produtos_com_dados": sum(1 for p in products.values() if any(e.get("pagina") == m for e in p["evidencias"])),
                  "com_evidencia_de_demanda": sum(1 for p in products.values() if any(e.get("pagina") == m and e["tipo"] in DEMAND_SIDE
                                                                                     for e in p["evidencias"])),
                  "dimensao": "público linguístico" if m.startswith("LANG:") else "mercado geográfico"}
    pct = lambda a: round(100 * a / n, 1)   # noqa: E731
    return {
        "catalogo": {"valor": pct(any_ev), "numerador": any_ev, "denominador": n,
                     "formula": "produtos com qualquer evidência coletada ÷ produtos monitorados"},
        "comercial": {"valor": pct(comm), "numerador": comm, "denominador": n,
                      "formula": "produtos com sinal ELEGÍVEL de intenção comercial ou interesse de pesquisa (classes A–C) ÷ produtos monitorados",
                      "exclui": "atenção pública (Wikipédia, notícias), atenção social e comércio exterior"},
        "temporal": {"valor": round(100 * per_obs / per_exp, 1) if per_exp else None, "numerador": per_obs, "denominador": per_exp,
                     "formula": "meses com valor ÷ meses do intervalo de cada série mensal (todas as séries)"},
        "geografica": {"por_mercado": geo, "formula": "produtos com dados por mercado geográfico e por público linguístico (separados)"},
        "previsao": {"valor": pct(fc), "numerador": fc, "denominador": n,
                     "formula": "produtos com ao menos uma série elegível para previsão (Gate 4) ÷ produtos monitorados"},
        "nota": "A cobertura comercial não inclui fontes que não medem intenção comercial; incluí-las aumentaria o número "
                "artificialmente."}


def _eligible_signal(e: dict) -> bool:
    if e["tipo"] == S.COMMERCIAL:
        return (e["derivado"].get("semanas_presente") or 0) >= 1
    if e["frequencia"] == "dia":
        return (e["derivado"].get("dias_em_alta_30d") or 0) >= 1
    return bool(e["elegibilidade"].get("tendencia"))


# --------------------------------------------------------------------------------------------- scores (seção 7)
def scores(p: dict) -> dict:
    """Componentes separados, cada um com status. Ausência de dado = 'não avaliado' (nunca 50)."""
    evs = p["evidencias"]
    dem = [e for e in evs if e["tipo"] in DEMAND_SIDE]
    comm = [e for e in evs if e["tipo"] == S.COMMERCIAL]
    out = {}

    def put(k, v, status, como, motivo=None):
        out[k] = {"valor": None if v is None else round(float(v), 1), "status": status, "como": como, "motivo": motivo}
    ml = comm[0]["derivado"] if comm else None
    if ml:
        v = 100 * (ml.get("persistencia") or 0) * (1 - 0.5 * ((ml.get("posicao_media") or 50) - 1) / 49)
        st = "calculável" if (ml.get("semanas_presente") or 0) >= 4 else "parcial"
        put("commercial_evidence", min(v, 40) if (ml.get("semanas_presente") or 0) == 1 else v, st,
            "100 × persistência no ranking × (1 − 0,5·(posição média − 1)/49); 1ª semana limitada a 40")
    else:
        put("commercial_evidence", None, "não avaliado", "ranking comercial", "produto não apareceu em ranking comercial coletado")
    mom = [e for e in dem if e["frequencia"] == "mes" and e["derivado"].get("momentum") is not None and e["elegibilidade"].get("tendencia")]
    if mom:
        e = max(mom, key=lambda e: e["observacoes_n"] or 0)
        g = e["derivado"]["momentum"]
        put("momentum", max(-100.0, min(100.0, 100 * g)), "calculável" if (e["observacoes_n"] or 0) >= 12 else "parcial",
            f"variação % da série elegível de {e['tipo_rotulo'].lower()} ({e['fonte_nome']}, {e['mercado']})")
    elif ml and ml.get("variacao_posicao") is not None:
        put("momentum", None, "evidência insuficiente", "ranking", "ranking não tem volume: mostra ganho de posição "
            f"({ml['variacao_posicao']:+d} posições), não crescimento percentual")
    else:
        put("momentum", None, "não avaliado", "série elegível de pesquisa ou demanda",
            "nenhuma série elegível de pesquisa/demanda (atenção pública não conta)")
    pers = [e["derivado"].get("persistencia") for e in dem if e["derivado"].get("persistencia") is not None]
    if ml:
        put("persistence", 100 * (ml.get("persistencia") or 0), "calculável" if (ml.get("semanas_coletadas") or 0) >= 4 else "parcial",
            "semanas presente ÷ semanas coletadas no ranking")
    elif pers:
        put("persistence", 100 * max(pers), "calculável", "fração de variações mensais positivas (12 meses)")
    else:
        put("persistence", None, "não avaliado", "série de demanda", "sem série de demanda com histórico")
    pos = p["confirmacao_cruzada"]["fontes_independentes_positivas"]
    srcs = {e["fonte"] for e in dem}
    if len(srcs) >= 2:
        put("cross_source_confirmation", 100 if len(pos) >= 2 else 50 if pos else 0, "calculável",
            "fontes independentes de demanda com sinal positivo (2+ = confirmado)")
    else:
        put("cross_source_confirmation", None, "evidência insuficiente" if srcs else "não avaliado",
            "fontes independentes de demanda", "há uma única fonte de demanda" if srcs else "nenhuma fonte de demanda")
    cov = p["indices"].get("evidence_coverage") or 0
    put("data_confidence", cov, "calculável" if cov >= 40 else "parcial" if cov > 0 else "evidência insuficiente",
        "Evidence Coverage: quantidade, diversidade e histórico das evidências elegíveis")
    ir = p["indices"].get("import_readiness")
    if not ir:      # 0 = nenhum item documentado: é ausência de informação, não prontidão baixa
        put("import_readiness", None, "não avaliado", "itens técnicos, comerciais e regulatórios documentados",
            "nenhuma informação técnica, comercial ou regulatória registrada (NCM, conformidade, preços)")
    else:
        put("import_readiness", ir, "calculável", "itens técnicos, comerciais e regulatórios documentados")
    parts = [(0.45, out["commercial_evidence"]["valor"]), (0.30, None if out["momentum"]["valor"] is None else 50 + out["momentum"]["valor"] / 2),
             (0.25, out["persistence"]["valor"])]
    have = [(w, v) for w, v in parts if v is not None]
    if not dem:
        put("investigation_priority", None, "evidência insuficiente", "prioridade",
            "sem evidência de demanda (só atenção pública/social/comércio exterior) — pode entrar na fila PRELIMINAR")
    elif not have:
        put("investigation_priority", None, "evidência insuficiente", "prioridade", "evidência de demanda sem histórico suficiente")
    else:
        base = sum(w * v for w, v in have) / sum(w for w, _ in have)
        conf = 0.6 + 0.4 * cov / 100
        st = "calculável" if len(have) == 3 and cov >= 40 else "parcial"
        put("investigation_priority", base * conf, st,
            "média ponderada dos componentes DISPONÍVEIS (evidência comercial 45%, momentum 30%, persistência 25%) × (0,6 + 0,4 × confiança). "
            "Componentes ausentes não entram como 50.")
    out["aviso"] = "Prioridade de investigação — não é probabilidade de sucesso nem estimativa de margem (sem preço e custo)."
    return out


# --------------------------------------------------------------------------------------------- três níveis (seção 4)
def levels(p: dict) -> dict:
    """Nível 1 = o que foi coletado; nível 2 = o que os dados permitem concluir; nível 3 = o que investigar.
    Cada nível só é gerado quando o anterior tem sustentação: nada do nível 1 vira conclusão de nível 2/3."""
    name = p["identificacao"]["produto"]
    n1, n2, n3 = [], [], []
    for e in p["evidencias"]:
        d = e["derivado"]
        ec = evidence_class(e["tipo"])
        if e["metrica"] == "posicao_tendencia":
            n1.append(f"{name} apareceu no ranking de mais buscados do Mercado Livre em {d.get('semanas_presente')} de "
                      f"{d.get('semanas_coletadas')} semana(s) coletada(s) (melhor posição {d.get('melhor_posicao')}).")
            if (d.get("semanas_presente") or 0) >= 4:
                vp = d.get("variacao_posicao")
                n2.append(f"{name} permaneceu no ranking por {d['semanas_presente']} semanas (persistência "
                          f"{(d.get('persistencia') or 0):.0%})" + (f", com {'melhoria' if vp > 0 else 'piora' if vp < 0 else 'estabilidade'} "
                                                                   f"de posição relativa ({vp:+d})" if vp is not None else "") + ".")
        elif e["frequencia"] == "dia":
            n1.append(f"{name}: {d.get('dias_em_alta_30d') or 0} dia(s) em lista de alta nos últimos 30 dias ({e['fonte_nome']}).")
        else:
            n1.append(f"{name}: {e['observacoes_n']} período(s) de {e['indicador']} ({e['fonte_nome']}, {e['mercado']}) — "
                      f"classe {ec['classe']} ({ec['classe_nome']}).")
            tt = d.get("tendencia") or {}
            if e["elegibilidade"].get("tendencia") and tt.get("p_valor") is not None:
                sig = tt.get("significativa_bh", tt.get("significativa"))
                fen = "atenção" if e["tipo"] in (S.PUBLIC, S.SOCIAL) else "interesse de pesquisa" if e["tipo"] == S.SEARCH else "a métrica"
                n2.append(f"{e['indicador']} ({e['mercado']}): {'tendência ' + tt.get('direcao', '') + ' estatisticamente significativa' if sig else 'sem tendência significativa'}"
                          f" em {fen} (p = {tt['p_valor']:.3f}" + (f", ajustado BH {tt['p_ajustado_bh']:.3f}" if tt.get("p_ajustado_bh") is not None else "")
                          + f"). Fenômeno estudado: {e['tipo_rotulo'].lower()} — {e['nao_e']}.")
    st = p["situacao"]
    if st in ("INTERESSE RECORRENTE",):
        n3.append("O produto apresenta interesse comercial recorrente. Recomenda-se investigar preços, concorrentes, fornecedores e custos de importação.")
    elif st in ("CRESCIMENTO CONSISTENTE", "ACELERAÇÃO") and any(e["tipo"] in DEMAND_SIDE for e in p["evidencias"]):
        n3.append("Há crescimento estatisticamente sustentado em evidência de demanda. Recomenda-se investigação comercial completa "
                  "(preços, concorrência, fornecedores, requisitos regulatórios).")
    elif st in ("NOVO SINAL COMERCIAL", "SINAL EM OBSERVAÇÃO", "EMERGENTE"):
        n3.append("Sinal preliminar: acompanhar a persistência e, em paralelo, levantar preços e concorrência — sem afirmar crescimento sustentado.")
    elif st == "ATENÇÃO PÚBLICA EM ALTA":
        n3.append("Só há atenção pública: verificar se existe intenção comercial (ranking ou buscas) antes de qualquer investigação de importação.")
    return {"nivel1_evidencia_observada": n1 or ["Nenhuma evidência coletada."],
            "nivel2_analise_estatistica": n2 or ["Os dados ainda não permitem conclusões estatísticas (histórico insuficiente ou métrica sem tendência)."],
            "nivel3_inteligencia_comercial": n3 or [p["proxima_acao"]]}


# --------------------------------------------------------------------------------------------- radar de candidatos (seção 26)
RADAR_STATES = ["Novo sinal", "Em observação", "Evidência comercial recorrente", "Investigação recomendada",
                "Investigação iniciada", "Aguardando dados", "Concluído"]


def candidate_state(p: dict, inv: dict | None, sc: dict) -> tuple[str, str]:
    if inv:
        e = inv["estado"]
        if e in ("Concluído", "Arquivado"):
            return "Concluído", "investigação encerrada na lista"
        if e == "Aguardando dados":
            return "Aguardando dados", "marcado na lista de investigação"
        if e not in ("Novo sinal", "Em observação"):
            return "Investigação iniciada", f"lista de investigação: {e}"
    st = p["situacao"]
    pri = sc["investigation_priority"]
    if pri["valor"] is not None and pri["valor"] >= 55 and st in ("INTERESSE RECORRENTE", "CRESCIMENTO CONSISTENTE", "ACELERAÇÃO"):
        return "Investigação recomendada", f"prioridade {pri['valor']:.0f} ({pri['status']})"
    if st == "INTERESSE RECORRENTE":
        return "Evidência comercial recorrente", "presença recorrente em ranking comercial"
    if st in ("NOVO SINAL COMERCIAL", "EMERGENTE"):
        return "Novo sinal", "primeira observação — sem histórico"
    if st in ("SINAL EM OBSERVAÇÃO", "SINAL INTERMITENTE", "ATENÇÃO PÚBLICA EM ALTA") or pri["valor"] is not None:
        return "Em observação", "sinal interessante, ainda insuficiente"
    return "", ""


def radar(products: dict, investigations: list[dict]) -> list[dict]:
    invs = {}
    for i in investigations:
        if i.get("produto_id"):
            invs.setdefault(i["produto_id"], i)
    out = []
    for pid, p in products.items():
        sc = p.get("pontuacao") or scores(p)
        stt, why = candidate_state(p, invs.get(pid), sc)
        if not stt:
            continue
        main = next((e for e in p["evidencias"] if e["tipo"] in DEMAND_SIDE), None) or (p["evidencias"] or [None])[0]
        out.append({"produto_id": pid, "produto": p["identificacao"]["produto"], "estado": stt, "motivo": why,
                    "situacao": p["situacao"], "mercado": (main or {}).get("mercado"),
                    "sinal": (main or {}).get("indicador"), "evidencia": evidence_class((main or {}).get("tipo"))["classe_nome"],
                    "persistencia": (sc["persistence"] or {}).get("valor"), "confianca": sc["data_confidence"]["status"],
                    "prioridade": sc["investigation_priority"]["valor"], "prioridade_status": sc["investigation_priority"]["status"],
                    "incerteza": p["definicao_situacao"], "proxima_acao": p["proxima_acao"]})
    order = {s: i for i, s in enumerate(["Investigação recomendada", "Evidência comercial recorrente", "Investigação iniciada",
                                         "Novo sinal", "Em observação", "Aguardando dados", "Concluído"])}
    out.sort(key=lambda r: (order.get(r["estado"], 9), -(r["prioridade"] or -1)))
    return out


# --------------------------------------------------------------------------------------------- alertas (seção 16)
SEV = {"alta": 0, "média": 1, "baixa": 2}


def alerts(products: dict, gate1: dict, sources: list[dict], today: date, recent_days: int = 120) -> dict:
    """Alertas COMERCIAIS, ESTATÍSTICOS e de QUALIDADE; agrupados por produto e tipo; só eventos recentes no painel."""
    cut = (today - timedelta(days=recent_days)).isoformat()
    items = []
    for pid, p in products.items():
        name = p["identificacao"]["produto"]
        cat = p["identificacao"].get("categoria")
        for e in p["evidencias"]:
            d = e["derivado"]
            base = {"produto_id": pid, "produto": name, "categoria": cat, "mercado": e.get("mercado"), "fonte": e["fonte_nome"],
                    "classe_evidencia": evidence_class(e["tipo"])["classe_nome"]}
            if e["tipo"] == S.COMMERCIAL:
                sp = d.get("semanas_presente") or 0
                if sp == 1:
                    items.append({**base, "categoria_alerta": "comercial", "tipo": "entrou em ranking comercial", "severidade": "média",
                                  "data": (p.get("linhagem") or {}).get("ids", [""])[0].split("|")[2] if (p.get("linhagem") or {}).get("ids") else None,
                                  "motivo": "primeira presença no ranking do Mercado Livre", "evidencia": f"melhor posição {d.get('melhor_posicao')}",
                                  "acao": "acompanhar as próximas semanas"})
                elif sp >= 4 and (d.get("persistencia") or 0) >= 0.5:
                    items.append({**base, "categoria_alerta": "comercial", "tipo": "persistência em ranking comercial", "severidade": "alta",
                                  "data": d.get("ultima_semana"), "motivo": f"{sp} semanas no ranking",
                                  "evidencia": f"persistência {d.get('persistencia'):.0%}", "acao": "investigar preços e concorrência"})
                continue
            stat_w = 0.5 if e["tipo"] in (S.PUBLIC, S.SOCIAL) else 1.0
            for kind, key in (("mudança de patamar", "mudancas_patamar"), ("anomalia", "anomalias")):
                ev = [x for x in (d.get(key) or []) if x and str(x) + "-01" >= cut[:7] + "-01"]
                if ev:
                    items.append({**base, "categoria_alerta": "estatístico", "tipo": kind, "severidade": "média" if stat_w == 1 else "baixa",
                                  "data": ev[-1], "motivo": f"{kind} em {e['indicador']}", "evidencia": f"{len(d.get(key) or [])} ocorrência(s) no histórico",
                                  "acao": "verificar a causa antes de interpretar como mudança de demanda" if stat_w == 1 else
                                          "atenção pública: não indica mudança de demanda", "historico": len(d.get(key) or [])})
            if d.get("reversao"):
                items.append({**base, "categoria_alerta": "estatístico", "tipo": "possível reversão", "severidade": "média" if stat_w == 1 else "baixa",
                              "data": e.get("periodo", "").split(" a ")[-1], "motivo": f"tendência passou de {d['reversao']['de']} para {d['reversao']['para']}",
                              "evidencia": f"inclinação {d['reversao']['inclinacao_anterior']:+.1%}/mês → {d['reversao']['inclinacao_recente']:+.1%}/mês",
                              "acao": "acompanhar os próximos meses"})
            if (d.get("sazonalidade") or {}).get("classificacao") == "possível":
                pass
        mq = p.get("correspondencia")
        if mq and not mq.get("confiavel"):
            items.append({"produto_id": pid, "produto": name, "categoria": cat, "categoria_alerta": "qualidade", "tipo": "associação ambígua",
                          "severidade": "média", "data": None, "fonte": "—", "mercado": None,
                          "motivo": f"apenas {(mq.get('fracao_confirmada') or 0):.0%} dos termos têm correspondência confirmada",
                          "evidencia": str(mq.get("por_estado")), "acao": "revisar a associação dos termos no Catálogo"})
    for c in (gate1 or {}).get("verificacoes", []):
        if not c["ok"]:
            items.append({"produto_id": None, "produto": "—", "categoria": None, "categoria_alerta": "qualidade", "tipo": "integridade dos dados",
                          "severidade": "alta" if c.get("severidade") == "erro" else "média", "data": today.isoformat(), "fonte": "Gate 1",
                          "mercado": None, "motivo": c["verificacao"], "evidencia": c["detalhe"], "acao": "ver Qualidade dos Dados"})
    failed = [s["id"] for s in sources if s.get("estado") == "falhou"]
    if failed:          # um único alerta para todas as fontes com falha (evita poluição)
        items.append({"produto_id": None, "produto": "Fontes de dados", "categoria": None, "categoria_alerta": "qualidade",
                      "tipo": "erro de coleta", "severidade": "média", "data": today.isoformat(), "fonte": ", ".join(failed),
                      "mercado": None, "motivo": f"{len(failed)} fonte(s) com a última coleta falha: {', '.join(failed)}",
                      "evidencia": "situação gravada das fontes", "acao": "Sincronização → Tentar novamente fontes com falha"})
    for s in sources:
        if s.get("estado") == "falhou":
            continue
        elif s.get("ultima_coleta_ok") and s["ultima_coleta_ok"][:10] < (today - timedelta(days=30)).isoformat():
            items.append({"produto_id": None, "produto": "—", "categoria": None, "categoria_alerta": "qualidade", "tipo": "fonte desatualizada",
                          "severidade": "baixa", "data": s["ultima_coleta_ok"][:10], "fonte": s["id"], "mercado": None,
                          "motivo": "última coleta bem-sucedida há mais de 30 dias", "evidencia": s["ultima_coleta_ok"], "acao": "sincronizar a fonte"})
    grouped = {}
    for a in items:                                  # agrupa repetidos do mesmo produto/tipo/fonte
        k = (a.get("produto_id"), a["tipo"], a.get("fonte"))
        g = grouped.get(k)
        if g:
            g["ocorrencias"] += 1
            if (a.get("data") or "") > (g.get("data") or ""):
                g["data"] = a.get("data")
        else:
            grouped[k] = {**a, "ocorrencias": 1}
    out = sorted(grouped.values(), key=lambda a: (SEV[a["severidade"]], {"comercial": 0, "qualidade": 1, "estatístico": 2}[a["categoria_alerta"]],
                                                  -(int(str(a.get("data") or "0")[:4] or 0))))
    cnt = defaultdict(int)
    for a in out:
        cnt[a["categoria_alerta"]] += 1
    return {"itens": out, "contagem": dict(cnt), "janela_dias": recent_days,
            "filtros": {"mercado": sorted({a["mercado"] for a in out if a.get("mercado")}),
                        "categoria": sorted({a["categoria"] for a in out if a.get("categoria")}),
                        "tipo": sorted({a["tipo"] for a in out}), "fonte": sorted({a["fonte"] for a in out if a.get("fonte")})},
            "nota": f"Só eventos dos últimos {recent_days} dias; alertas repetidos do mesmo produto, tipo e fonte são agrupados. "
                    "Alertas de atenção pública têm severidade baixa e não indicam demanda."}
