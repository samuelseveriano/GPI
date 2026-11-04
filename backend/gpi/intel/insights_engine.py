"""GPI Insights Engine (v0.8, seções 3·Etapa 5, 12, 13, Gate 6).

Regras determinísticas: o texto é montado a partir dos números já calculados pelo PIFE. Nenhuma LLM gera números,
evidências ou conclusões; a IA local (opcional) só pode reescrever o texto, nunca os campos.

Cada insight tem: produto, mercado, indicador, fonte, período, evidência, método, interpretação, confiança, limitações,
próxima investigação — e responde: o que aconteceu? qual é a evidência? o que significa? qual é a incerteza? o que
investigar agora? — com os IDs das observações usadas.
"""
from __future__ import annotations

import numpy as np

from .fusion import CLASS_DEF, GROWING, INTERMEDIATE

FIELDS = ("produto", "mercado", "indicador", "fonte", "periodo", "evidencia", "metodo", "interpretacao", "confianca",
          "limitacoes", "proxima_investigacao")


def _pct(v):
    return None if v is None else f"{v * 100:+.0f}%"


def _main(p: dict) -> dict | None:
    order = {"COMMERCIAL_SEARCH_INTENT": 0, "SEARCH_INTEREST": 0, "PUBLIC_ATTENTION": 2}
    evs = [e for e in p["evidencias"] if e["tipo"] in order]
    if not evs:
        return None
    return min(evs, key=lambda e: (order[e["tipo"]], e["pais"] != "BR", -(e["observacoes_n"] or 0)))


def _evidence_text(e: dict) -> str:
    d = e["derivado"]
    if e["metrica"] == "posicao_tendencia":
        s = f"Presente no ranking de mais buscados do Mercado Livre em {d['semanas_presente']} de {d['semanas_coletadas']} semana(s) coletada(s)"
        if d.get("melhor_posicao"):
            s += f"; melhor posição {d['melhor_posicao']}, posição média {d['posicao_media']}"
        return s + "."
    if e["frequencia"] == "dia":
        return f"{d.get('dias_em_alta_30d') or 0} dia(s) na lista de alta nos últimos 30 dias ({e['indicador']})."
    parts = [f"{e['indicador']} ({e['fonte_nome']}, {e['mercado']}): {e['observacoes_n']} período(s) mensais"]
    if d.get("momentum") is not None:
        parts.append(f"variação {_pct(d['momentum'])} ({d.get('base_momentum') or '3 meses'})")
    if d.get("atencao_relativa") is not None:
        parts.append(f"{_pct(d['atencao_relativa'])} em relação à mediana dos artigos do mesmo idioma ({_pct(d['mediana_coorte'])})")
    tt = d.get("tendencia") or {}
    if tt.get("p_valor") is not None:
        parts.append(f"tendência {'significativa' if tt.get('significativa') else 'não significativa'} (p = {tt['p_valor']:.3f})")
    return "; ".join(parts) + "."


def _method(e: dict) -> str:
    if e["metrica"] == "posicao_tendencia":
        return "Persistência semanal e posição no ranking (uma observação por semana; sem % de volume)."
    if e["frequencia"] == "dia":
        return "Contagem de dias em lista de alta (presença; sem % de volume)."
    return ("Variação recente (3 meses ou ano contra ano), teste de tendência Mann-Kendall/Theil-Sen"
            + (", comparação com a mediana dos artigos do mesmo idioma" if e["metrica"] == "visualizacoes" else "") + ".")


def confidence(p: dict, main: dict | None) -> tuple[str, float]:
    cov = (p["indices"].get("evidence_coverage") or 0) / 100
    n = (main or {}).get("observacoes_n") or 0
    sig = bool(((main or {}).get("derivado") or {}).get("tendencia", {}) and main["derivado"]["tendencia"].get("significativa"))
    v = 0.45 * cov + 0.25 * min(1.0, n / 24) + 0.15 * sig + 0.15 * p["confirmacao_cruzada"]["confirmado"]
    if p["situacao"] in ("EVIDÊNCIA INSUFICIENTE", "NOVO SINAL COMERCIAL", "ATENÇÃO PÚBLICA EM ALTA"):
        v = min(v, 0.3)
    if p.get("correspondencia") and not p["correspondencia"]["confiavel"]:
        v = min(v, 0.3)
    return ("alta" if v >= 0.65 else "moderada" if v >= 0.4 else "baixa"), round(v, 2)


def insight(p: dict) -> dict:
    main = _main(p)
    st = p["situacao"]
    conf, cv = confidence(p, main)
    ident = p["identificacao"]
    if not main:
        what = "Não há série de pesquisa, sinal comercial ou atenção pública associada a este produto."
        evid = "Nenhuma evidência elegível."
    else:
        what = f"{CLASS_DEF[st]}"
        evid = _evidence_text(main)
    meaning = {
        "NOVO SINAL COMERCIAL": "O produto apresenta presença numa lista de pesquisas populares, mas ainda não possui histórico suficiente para confirmar crescimento sustentado.",
        "ATENÇÃO PÚBLICA EM ALTA": "Há mais leitura/notícia sobre o produto do que sobre os demais, o que NÃO comprova intenção de compra.",
        "VARIAÇÃO NÃO CONFIRMADA": "A queda recente não é estatisticamente significativa nem persistente; ainda não indica perda de interesse.",
        "EVIDÊNCIA INSUFICIENTE": "Ausência de dados não indica baixa demanda: só não há base para concluir.",
    }.get(st) or ("Há sinal de aumento de interesse de pesquisa/comercial nas fontes elegíveis." if st in GROWING else
                  "O interesse se mantém sem tendência definida." if st == "ESTÁVEL" else
                  "O interesse se repete em épocas do ano; separar sazonalidade de tendência." if st == "SAZONAL" else
                  "O interesse caiu de forma estatisticamente consistente." if st == "DECLÍNIO" else CLASS_DEF[st])
    lim = ["Pesquisas, rankings e atenção não são unidades vendidas; nenhuma conversão para vendas é feita."]
    if main and main.get("nao_e"):
        lim.append(f"{main['tipo_rotulo']}: {main['nao_e']}.")
    if not p["confirmacao_cruzada"]["confirmado"]:
        lim.append("Sem confirmação por duas fontes independentes de demanda.")
    for k, v in (p.get("indices_motivos") or {}).items():
        if k in ("forecast_confidence",):
            lim.append(f"Sem previsão: {v}.")
    if p.get("correspondencia") and not p["correspondencia"]["confiavel"]:
        lim.append("Parte dos termos associados ao produto tem correspondência não confirmada.")
    unc = (f"Confiança {conf}: cobertura de evidências {p['indices']['evidence_coverage']:.0f}/100"
           + (f", {main['observacoes_n']} observação(ões)" if main else "")
           + ("; confirmado por fontes independentes" if p["confirmacao_cruzada"]["confirmado"] else "; fonte única de demanda" if main else "") + ".")
    obs = (main or {}).get("observacoes") or ((p.get("linhagem") or {}).get("ids") or [])[:12]
    out = {"produto_id": p["produto_id"], "produto": ident["produto"], "mercado": (main or {}).get("mercado") or "—",
           "indicador": (main or {}).get("indicador") or "—", "fonte": (main or {}).get("fonte_nome") or "—",
           "periodo": (main or {}).get("periodo") or "—", "evidencia": evid, "metodo": _method(main) if main else "—",
           "interpretacao": meaning, "confianca": conf, "confianca_valor": cv, "limitacoes": lim,
           "proxima_investigacao": p["proxima_acao"], "situacao": st,
           "perguntas": {"o_que_aconteceu": what, "qual_a_evidencia": evid, "o_que_significa": meaning,
                         "qual_a_incerteza": unc, "o_que_investigar": p["proxima_acao"]},
           "observacoes_ids": obs, "observacoes_total": ((p.get("linhagem") or {}).get("total")),
           "gerado_por": "regras determinísticas do GPI (sem IA)"}
    return out


def gate6(insights: list[dict]) -> dict:
    bad = [i["produto_id"] for i in insights if any(not i.get(f) or i.get(f) == "—" for f in FIELDS if f not in ("mercado", "indicador",
           "fonte", "periodo", "metodo")) or (i["situacao"] != "EVIDÊNCIA INSUFICIENTE" and not i["observacoes_ids"])]
    return {"gate": 6, "nome": "Interpretação comercial", "status": "aprovado" if not bad else "reprovado",
            "insights": len(insights), "sem_campos_obrigatorios_ou_evidencia": bad[:30]}


# --------------------------------------------------------------------------------------------- ranking e grupos
def investigate_rank(products: dict) -> list[dict]:
    rows = []
    for p in products.values():
        idx = p["indices"]
        if idx.get("opportunity_score") is None:
            continue
        ok_match = not p.get("correspondencia") or p["correspondencia"]["confiavel"]
        confirmed = (p["situacao"] in GROWING | {"INTERESSE RECORRENTE"} and idx["opportunity_score"] >= 55
                     and idx["evidence_coverage"] >= 40 and ok_match)
        main = _main(p)
        d = (main or {}).get("derivado") or {}
        rows.append({"produto_id": p["produto_id"], "produto": p["identificacao"]["produto"], "pais": (main or {}).get("mercado"),
                     "indicador": (main or {}).get("indicador"), "crescimento": d.get("momentum"),
                     "persistencia": d.get("persistencia", d.get("persistencia")), "fontes": len(p["fontes"]),
                     "fontes_nomes": p["fontes"], "confianca": confidence(p, main)[0], "situacao": p["situacao"],
                     "opportunity_score": idx["opportunity_score"], "evidence_coverage": idx["evidence_coverage"],
                     "proxima_acao": p["proxima_acao"], "nivel": "investigar" if confirmed else "observar",
                     "motivo_nivel": None if confirmed else (
                         "correspondência de produto não confirmada" if not ok_match else
                         "cobertura de evidências < 40" if idx["evidence_coverage"] < 40 else
                         "prioridade < 55" if idx["opportunity_score"] < 55 else f"situação: {p['situacao'].lower()}")})
    rows.sort(key=lambda r: (r["nivel"] != "investigar", -r["opportunity_score"]))
    return rows


def groups(products: dict) -> dict:
    G = lambda f: sorted(pid for pid, p in products.items() if f(p))   # noqa: E731
    return {
        "novo_sinal_comercial": G(lambda p: p["situacao"] == "NOVO SINAL COMERCIAL"),
        "emergentes": G(lambda p: p["situacao"] == "EMERGENTE"),
        "em_observacao": G(lambda p: p["situacao"] in ("SINAL EM OBSERVAÇÃO", "SINAL INTERMITENTE")),
        "interesse_recorrente": G(lambda p: p["situacao"] == "INTERESSE RECORRENTE"),
        "crescimento_consistente": G(lambda p: p["situacao"] in ("CRESCIMENTO CONSISTENTE", "ACELERAÇÃO")),
        "confirmados_fontes_independentes": G(lambda p: p["confirmacao_cruzada"]["confirmado"]),
        "sazonais": G(lambda p: p["situacao"] == "SAZONAL"),
        "variacao_nao_confirmada": G(lambda p: p["situacao"] == "VARIAÇÃO NÃO CONFIRMADA"),
        "declinio": G(lambda p: p["situacao"] in ("DECLÍNIO", "POSSÍVEL SATURAÇÃO")),
        "somente_atencao_publica": G(lambda p: p["situacao"] == "ATENÇÃO PÚBLICA EM ALTA"),
        "evidencia_insuficiente": G(lambda p: p["situacao"] == "EVIDÊNCIA INSUFICIENTE"),
    }


# --------------------------------------------------------------------------------------------- clusters (seção 12)
CL_RULES = [("Crescimento consistente", lambda c: c["crescimento"] > 0.1 and c["persistencia"] >= 0.55 and c["volatilidade"] < 0.5),
            ("Emergentes", lambda c: c["recencia"] >= 0.5 and c["crescimento"] > 0.05),
            ("Voláteis", lambda c: c["volatilidade"] >= 0.5),
            ("Sazonais", lambda c: c["sazonalidade"] >= 0.5),
            ("Em declínio", lambda c: c["crescimento"] < -0.1 and c["persistencia"] < 0.45),
            ("Estáveis", lambda c: True)]
FEATS = ["crescimento", "aceleracao", "persistencia", "volatilidade", "sazonalidade", "estabilidade", "recencia", "cobertura"]


def _features(p: dict) -> list[float] | None:
    evs = [e for e in p["evidencias"] if e["elegibilidade"].get("agrupamento") and e["frequencia"] != "semana"
           and e["derivado"].get("momentum") is not None]
    if not evs:
        return None
    e = max(evs, key=lambda e: e["observacoes_n"] or 0)
    d = e["derivado"]
    n = e["observacoes_n"] or 0
    seas = 1.0 if (d.get("sazonalidade") or {}).get("significativa") else 0.0
    vol = min(2.0, d.get("volatilidade") or 0.0)
    return [max(-1.0, min(3.0, d.get("momentum") or 0.0)), max(-1.0, min(1.0, d.get("aceleracao") or 0.0)),
            float(d.get("persistencia") if d.get("persistencia") is not None else 0.5), vol, seas,
            float(len(d.get("mudancas_patamar") or []) == 0), 1.0 if n <= 12 else 0.0,
            (p["indices"].get("evidence_coverage") or 0) / 100]


def clusters(products: dict, seed: int = 42) -> dict:
    """Atributos ADIMENSIONAIS (taxas, frações e indicadores 0/1), padronizados — sem misturar unidades. Compara
    K-Means, aglomerativo (Ward) e HDBSCAN (quando disponível) pelo silhouette; nomes vêm de regras sobre os centróides."""
    rows = [(pid, _features(p)) for pid, p in products.items()]
    ok = [(pid, f) for pid, f in rows if f is not None]
    insuf = sorted(pid for pid, f in rows if f is None)
    base = {"atributos": FEATS, "grupos": [], "informacao_insuficiente": insuf}
    if len(ok) < 6:
        return {**base, "aviso": f"apenas {len(ok)} produto(s) com séries elegíveis: agrupamento não calculado (mínimo 6)."}
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler
    raw = np.array([f for _, f in ok])
    X = StandardScaler().fit_transform(raw)
    X = np.nan_to_num(X)
    cands = []
    for k in range(2, min(6, len(ok) - 1) + 1):
        for name, model in (("K-Means", KMeans(n_clusters=k, n_init=10, random_state=seed)),
                            ("Hierárquico (Ward)", AgglomerativeClustering(n_clusters=k, linkage="ward"))):
            lab = model.fit_predict(X)
            if len(set(lab)) >= 2:
                cands.append((float(silhouette_score(X, lab)), name, k, lab))
    try:
        from sklearn.cluster import HDBSCAN
        lab = HDBSCAN(min_cluster_size=max(3, len(ok) // 10), copy=True).fit_predict(X)
        mask = lab >= 0
        if len(set(lab[mask])) >= 2 and mask.sum() >= 6:
            cands.append((float(silhouette_score(X[mask], lab[mask])), "HDBSCAN", len(set(lab[mask])), lab))
    except Exception:  # noqa: BLE001 — sklearn sem HDBSCAN
        pass
    if not cands:
        return {**base, "aviso": "dados sem estrutura de grupos detectável"}
    s, method, k, lab = max(cands, key=lambda c: c[0])
    comps = sorted({(c[1], c[2]): round(c[0], 3) for c in cands}.items(), key=lambda x: -x[1])[:6]
    groups = []
    for g in sorted(set(lab)):
        idx = [j for j in range(len(ok)) if lab[j] == g]
        cen = {f: float(np.mean(raw[idx, n])) for n, f in enumerate(FEATS)}
        name = "Ruído (sem grupo)" if g < 0 else next(nm for nm, cond in CL_RULES if cond(cen))
        why = [f"{f}: {cen[f]:+.2f}" if f in ("crescimento", "aceleracao") else f"{f}: {cen[f]:.2f}" for f in FEATS]
        groups.append({"nome": name, "centroide": {f: round(v, 3) for f, v in cen.items()}, "justificativa": why,
                       "produtos": [ok[j][0] for j in idx],
                       "nomes": [products[ok[j][0]]["identificacao"]["produto"] for j in idx]})
    seen = {}
    for gr in groups:
        seen.setdefault(gr["nome"], []).append(gr)
    for nm, lst in seen.items():
        if len(lst) > 1:
            for gr in lst:
                gr["nome"] = f"{nm} (crescimento médio {gr['centroide']['crescimento'] * 100:+.0f}%)"
    return {**base, "metodo": method, "k": k, "silhouette": round(s, 3),
            "qualidade": "boa" if s >= 0.5 else "razoável" if s >= 0.25 else "fraca (grupos pouco separados)",
            "comparacao_metodos": [{"metodo": m, "k": kk, "silhouette": v} for (m, kk), v in comps], "grupos": groups}
