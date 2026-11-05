"""Inteligência de Oportunidades e Insights do GPI (v0.7.1).

Tudo é DETERMINÍSTICO, calculado a partir dos indicadores das séries coletadas (trends.indicators), das previsões
validadas por backtesting e dos scores por produto. Nenhuma LLM gera números ou conclusões.

Situação do produto (critérios documentados em docs/ML_VALIDATION.md):
* EVIDÊNCIA INSUFICIENTE — sem série elegível: mensal com < 6 meses ou base (mediana) abaixo do mínimo da métrica;
  diária com < 28 dias de histórico e < 5 dias em alta no último mês.
* EMERGENTE — primeira observação recente (≤ 3 meses / ≤ 30 dias) ou alta > 15% ainda sem significância estatística.
* ACELERAÇÃO — tendência significativa de alta (Mann-Kendall/Theil-Sen) com aceleração > 10 p.p. e base suficiente.
* CRESCIMENTO CONSISTENTE — tendência significativa de alta (ano contra ano em séries sazonais).
* POSSÍVEL SATURAÇÃO — crescimento com desaceleração > 10 p.p. e nível perto do máximo histórico.
* DECLÍNIO — tendência significativa de queda ou variação < −15%.
* SAZONAL — sazonalidade significativa sem tendência.
* ESTÁVEL — demais casos com evidência suficiente.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

STATUS = {"emergente": "EMERGENTE", "crescimento": "EMERGENTE", "crescimento consistente": "CRESCIMENTO CONSISTENTE",
          "crescimento acelerado": "ACELERAÇÃO", "estável": "ESTÁVEL", "sazonal": "SAZONAL",
          "possível saturação": "POSSÍVEL SATURAÇÃO", "declínio": "DECLÍNIO", "sem dados": "EVIDÊNCIA INSUFICIENTE",
          "presença recorrente": "ESTÁVEL", "possível declínio": "POSSÍVEL DECLÍNIO",
          "variação não confirmada": "VARIAÇÃO NÃO CONFIRMADA", "mudança na fonte": "MUDANÇA NA FONTE"}
GROWING = {"EMERGENTE", "CRESCIMENTO CONSISTENTE", "ACELERAÇÃO"}
KIND_RANK = {"busca": 0, "busca_ranking": 1, "atencao": 2, "popularidade": 3}
NEXT = {"ACELERAÇÃO": "Investigar preços, concorrência, especificações e fornecedores; acompanhar se a aceleração se mantém.",
        "CRESCIMENTO CONSISTENTE": "Investigar preços, concorrência, especificações, fornecedores e requisitos de importação.",
        "EMERGENTE": "Acompanhar mais períodos e buscar confirmação em outra fonte antes de investir esforço comercial.",
        "SAZONAL": "Planejar a investigação para antes do pico sazonal; comparar anos para separar sazonalidade de tendência.",
        "ESTÁVEL": "Demanda estável: avaliar diferenciação, preço e concorrência.",
        "POSSÍVEL SATURAÇÃO": "Cautela: verificar concorrência e se o crescimento está perdendo força.",
        "DECLÍNIO": "Baixa prioridade enquanto a queda persistir.",
        "EVIDÊNCIA INSUFICIENTE": "Coletar mais dados (mais períodos ou outra fonte) antes de qualquer conclusão.",
        "POSSÍVEL DECLÍNIO": "Acompanhar: a queda ainda não é estatisticamente confirmada.",
        "VARIAÇÃO NÃO CONFIRMADA": "Aguardar novos períodos: a variação não é significativa nem persistente.",
        "MUDANÇA NA FONTE": "Desconsiderar como sinal do produto: a fonte inteira mudou de patamar."}


def _sufficient(s: dict) -> bool:
    ind = s.get("ind") or {}
    if s.get("period") == "dia":
        return (ind.get("dias_historico") or 0) >= 28 or (ind.get("dias_em_alta_30d") or 0) >= 5
    return (ind.get("n") or 0) >= 6 and bool(ind.get("base_suficiente", True))


def series_status(s: dict) -> str:
    if not _sufficient(s):
        return "EVIDÊNCIA INSUFICIENTE"
    # v0.8.1: atenção pública (Wikipédia, notícias) não classifica demanda — nem crescimento, nem declínio, nem sazonalidade
    if (s.get("metrica") or {}).get("tipo") not in ("busca", "busca_ranking"):
        return "EVIDÊNCIA INSUFICIENTE"
    return STATUS.get((s.get("ind") or {}).get("classe"), "ESTÁVEL")


def _main_series(lst: list[dict]) -> dict | None:
    def key(s):
        k = KIND_RANK.get((s.get("metrica") or {}).get("tipo"), 9)
        return (not _sufficient(s), s.get("country") != "BR", k, -((s.get("ind") or {}).get("n") or 0))
    return min(lst, key=key) if lst else None


def _vol_label(v):
    if v is None:
        return None
    return "baixa" if v < 0.2 else "moderada" if v < 0.5 else "alta"


def _persist(ind: dict) -> tuple[int, int] | None:
    vals = ind.get("valores")
    if ind.get("persistencia") is None or not vals or len(vals) < 5:
        return None
    tail = np.asarray(vals[-13:], float)
    d = np.diff(tail)
    return int((d > 0).sum()), int(len(d))


def _forecast_view(fc_list: list[dict]) -> dict | None:
    for f in fc_list:
        if f.get("status") != "prevista" or not f.get("previsao"):
            continue
        hist = np.asarray(f.get("valores") or [], float)
        if len(hist) < 3:
            continue
        base, fut = float(hist[-3:].mean()), float(np.mean(f["previsao"][:3]))
        rel = (fut / base - 1) if base > 0 else None
        width = None
        if f.get("hi80") and f.get("lo80") and fut > 0:
            width = float(np.mean(np.asarray(f["hi80"][:3]) - np.asarray(f["lo80"][:3]))) / fut
        direcao = "crescimento provável" if (rel or 0) > 0.05 else "queda provável" if (rel or 0) < -0.05 else "estabilidade provável"
        return {"texto": direcao + (", com incerteza" if (width or 0) > 0.3 else ""), "variacao_prevista_3p": rel,
                "largura_relativa_80": width, "modelo": f.get("modelo_nome") or f.get("modelo"), "qualidade": f.get("qualidade"),
                "baseline": bool(f.get("baseline_selecionado") or f.get("modelo") == "naive"),
                "metricas": {k: (f.get("metricas") or {}).get(k) for k in ("wape", "mae", "rmsse", "fva_vs_naive", "cobertura_80")}}
    return None


def product_insight(pid: str, lst: list[dict], score: dict, fc: dict, prod: dict, compliance: dict | None = None) -> dict:
    main = _main_series(lst)
    status = series_status(main) if main else "EVIDÊNCIA INSUFICIENTE"
    ind = (main or {}).get("ind") or {}
    growth = ind.get("crescimento")
    grow_sources = sorted({s.get("fonte_nome") or s["source"] for s in lst if _sufficient(s) and series_status(s) in GROWING})
    all_sources = sorted({s.get("fonte_nome") or s["source"] for s in lst})
    pers = _persist(ind)
    vol = ind.get("volatilidade")
    fcv = _forecast_view([fc[s["id"]] for s in lst if s["id"] in fc])
    conf_num = float(ind.get("confianca_classificacao") or 0) * 0.6 + 0.4 * min(1.0, len(grow_sources or all_sources) / 3)
    if status == "EVIDÊNCIA INSUFICIENTE":
        conf_num = min(conf_num, 0.3)
    confianca = "alta" if conf_num >= 0.65 else "moderada" if conf_num >= 0.4 else "baixa"
    base = ind.get("base_crescimento") or ("últimos 30 dias contra os 30 anteriores" if (main or {}).get("period") == "dia" else None)
    parts = []
    if status in GROWING:
        parts.append(f"O produto apresenta {status.lower()} nas observações disponíveis"
                     + (f" ({len(grow_sources)} fonte(s) com sinal de alta)" if grow_sources else "") + ".")
    elif status == "EVIDÊNCIA INSUFICIENTE":
        parts.append("Ainda não há dados suficientes para classificar a tendência deste produto.")
    else:
        parts.append(f"Situação atual: {status.lower()}.")
    if (ind.get("n") or 0) and (ind.get("n") or 0) < 12 and status != "EVIDÊNCIA INSUFICIENTE":
        parts.append("O histórico ainda é limitado e a tendência precisa ser confirmada em períodos adicionais.")
    if len(all_sources) == 1 and status in GROWING:
        parts.append("Há evidência em uma única fonte; procure confirmação em outra fonte independente.")
    if vol is not None and vol >= 0.5:
        parts.append("A volatilidade é alta: parte do movimento pode ser passageira.")
    if ind.get("sazonalidade") and (ind["sazonalidade"] or {}).get("significativa"):
        parts.append("Há sazonalidade: compare o mesmo período de anos diferentes.")
    if fcv and fcv["baseline"]:
        parts.append("Nenhum modelo superou o baseline simples no backtesting; a previsão usa o baseline.")
    lim = ["Interesse de pesquisa, atenção e menções não são unidades vendidas; nenhuma conversão para vendas é feita."]
    if not fcv:
        lim.append("Sem previsão validada (exige série mensal longa e backtesting).")
    if not score.get("componentes", {}).get("concorrencia_baixa") is not None:
        pass
    return {
        "produto_id": pid, "nome": prod.get("canonical") or (main or {}).get("nome") or pid, "categoria": prod.get("category"),
        "familia": prod.get("family"), "nivel": prod.get("level"), "variante": prod.get("canonical") if prod.get("level") == "variante" else None,
        "situacao": status, "serie_principal": {"fonte": (main or {}).get("fonte_nome"), "pais": (main or {}).get("pais_nome"),
                                                 "metrica": ((main or {}).get("metrica") or {}).get("rotulo"),
                                                 "periodo": f"{ind.get('primeiro') or '—'} a {ind.get('ultimo') or '—'}",
                                                 "observacoes": ind.get("n")} if main else None,
        "crescimento_recente": growth, "base_crescimento": base,
        "crescimentos_janelas": {k: ind.get(k) for k in ("crescimento_7d", "crescimento_30d", "crescimento_90d", "crescimento_3m",
                                                         "crescimento_12m") if ind.get(k) is not None},
        "aceleracao": ind.get("aceleracao"), "persistencia": {"positivos": pers[0], "periodos": pers[1]} if pers else None,
        "fontes_com_evidencia": len(grow_sources), "fontes": all_sources, "volatilidade": vol, "volatilidade_rotulo": _vol_label(vol),
        "sazonal": bool((ind.get("sazonalidade") or {}).get("significativa")) if ind.get("sazonalidade") else False,
        "mudancas_patamar": ind.get("pontos_mudanca") or [], "anomalias": ind.get("anomalias") or [],
        "previsao": fcv, "confianca": confianca, "confianca_valor": round(conf_num, 2),
        "opportunity_score": score.get("opportunity_score"), "evidence_coverage": score.get("evidence_coverage"),
        "forecast_confidence": score.get("forecast_confidence"), "import_readiness": score.get("import_readiness"),
        "concorrencia": (score.get("componentes") or {}).get("concorrencia_baixa"),
        "prontidao_regulatoria": compliance, "sinal_internacional": score.get("sinal_internacional"),
        "analise": " ".join(parts), "proxima_acao": NEXT[status], "limitacoes": lim + (score.get("riscos") or [])[:4],
    }


def _compliance_summary(db) -> dict:
    out = {}
    try:
        rows = db.query("SELECT product_id, id, criado_em, resultado FROM compliance_analyses WHERE product_id IS NOT NULL ORDER BY id")
    except Exception:  # noqa: BLE001
        return out
    import json
    for r in rows:
        try:
            res = json.loads(r["resultado"])
            out[r["product_id"]] = {"analise_id": r["id"], "data": r["criado_em"],
                                    "resumo": {o["orgao"]: o["pior_estado"] for o in res.get("por_orgao", [])}}
        except ValueError:
            continue
    return out


def build(result: dict, db, catalog_products: dict) -> dict:
    """Insights para todos os produtos + agrupamentos da página Inteligência de Oportunidades."""
    by = defaultdict(list)
    for s in result.get("series", []):
        by[s["product_id"]].append(s)
    comp = _compliance_summary(db)
    fam_of = lambda pid: (pid or "").split(":")[0]   # noqa: E731
    items = []
    for pid, lst in by.items():
        sc = (result.get("scores") or {}).get(pid) or {}
        items.append(product_insight(pid, lst, sc, result.get("previsoes") or {}, catalog_products.get(pid, {}),
                                     comp.get(pid) or comp.get(fam_of(pid))))
    items.sort(key=lambda x: (-(x["opportunity_score"] or -1), x["nome"]))
    G = lambda cond: [i for i in items if cond(i)]   # noqa: E731
    comps = result.get("comparacoes") or {}
    us_first = []
    for i in items:
        for c in comps.get(i["produto_id"], []):
            if c.get("significativa") and c.get("estavel") and ((c["a"] == "US" and c["lag"] > 0) or (c["b"] == "US" and c["lag"] < 0)):
                us_first.append({**i, "lead_lag": c})
                break
    groups = {
        "crescendo": G(lambda i: i["situacao"] in GROWING),
        "perdendo_interesse": G(lambda i: i["situacao"] in ("DECLÍNIO", "POSSÍVEL SATURAÇÃO")),
        "crescimento_consistente": G(lambda i: i["situacao"] in ("CRESCIMENTO CONSISTENTE", "ACELERAÇÃO")
                                     and (i["persistencia"] or {}).get("positivos", 0) >= 0.6 * max(1, (i["persistencia"] or {}).get("periodos", 1))),
        "possiveis_modismos": G(lambda i: i["situacao"] == "EMERGENTE" and (i["volatilidade_rotulo"] == "alta" or i["fontes_com_evidencia"] <= 1)),
        "sazonais": G(lambda i: i["sazonal"] or i["situacao"] == "SAZONAL"),
        "eua_antes_do_brasil": us_first,
        "multiplas_fontes": G(lambda i: i["fontes_com_evidencia"] >= 2),
        "merecem_investigacao": G(lambda i: i["situacao"] in GROWING and (i["opportunity_score"] or 0) >= 55
                                  and (i["evidence_coverage"] or 0) >= 40),
        "precisam_mais_dados": G(lambda i: i["situacao"] == "EVIDÊNCIA INSUFICIENTE" or (i["evidence_coverage"] or 0) < 40),
    }
    return {"itens": items, "grupos": {k: [x["produto_id"] for x in v] for k, v in groups.items()},
            "contagens": {k: len(v) for k, v in groups.items()}, "clusters": clusters(items),
            "gerado_em": result.get("gerado_em"),
            "aviso": "Opportunity Score prioriza investigação; não é probabilidade de sucesso, margem ou quantidade de compra. "
                     "Falta de dados reduz cobertura e confiança — não é baixa demanda."}


CL_NAMES = [("Produtos com crescimento acelerado", lambda c: c["crescimento"] > 0.3 and c["aceleracao"] > 0.05),
            ("Produtos emergentes e voláteis", lambda c: c["crescimento"] > 0.1 and c["volatilidade"] >= 0.5),
            ("Produtos com crescimento estável", lambda c: c["crescimento"] > 0.05 and c["volatilidade"] < 0.5),
            ("Produtos sazonais", lambda c: c["sazonalidade"] >= 0.5),
            ("Produtos em possível declínio", lambda c: c["crescimento"] < -0.05),
            ("Produtos estáveis", lambda c: True)]


def clusters(items: list[dict], seed: int = 42) -> dict:
    """K-Means sobre atributos padronizados (sem misturar unidades: só taxas e índices adimensionais).
    k escolhido pelo silhouette (2..5). Nomes só a partir dos centróides; evidência insuficiente fica em grupo à parte."""
    ok = [i for i in items if i["situacao"] != "EVIDÊNCIA INSUFICIENTE" and i["crescimento_recente"] is not None]
    insuf = [i["produto_id"] for i in items if i not in ok]
    base = {"metodo": "K-Means (atributos padronizados)", "grupos": [], "evidencia_insuficiente": insuf}
    if len(ok) < 6:
        return {**base, "aviso": f"apenas {len(ok)} produto(s) com evidência suficiente: agrupamento não calculado (mínimo 6)."}
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler
    feats = ["crescimento", "volatilidade", "aceleracao", "persistencia", "sazonalidade"]
    raw = np.array([[max(-1.0, min(3.0, i["crescimento_recente"] or 0)), min(2.0, i["volatilidade"] or 0), i["aceleracao"] or 0,
                     ((i["persistencia"] or {}).get("positivos", 0) / max(1, (i["persistencia"] or {}).get("periodos", 1))),
                     1.0 if i["sazonal"] else 0.0] for i in ok])
    X = StandardScaler().fit_transform(raw)
    best = None
    for k in range(2, min(5, len(ok) - 1) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X)
        if len(set(km.labels_)) < 2:
            continue
        s = float(silhouette_score(X, km.labels_))
        if best is None or s > best[0]:
            best = (s, k, km)
    if best is None:
        return {**base, "aviso": "dados sem estrutura de grupos detectável"}
    s, k, km = best
    groups = []
    for g in range(k):
        idx = [j for j in range(len(ok)) if km.labels_[j] == g]
        cen = {f: float(np.mean(raw[idx, n])) for n, f in enumerate(feats)}
        name = next(nm for nm, cond in CL_NAMES if cond(cen))
        groups.append({"nome": name, "centroide": {f: round(v, 3) for f, v in cen.items()},
                       "produtos": [ok[j]["produto_id"] for j in idx], "nomes": [ok[j]["nome"] for j in idx]})
    seen = {}
    for g in sorted(groups, key=lambda g: -g["centroide"]["crescimento"]):
        if g["nome"] in seen:                       # nomes repetidos: distingue pelo crescimento médio do grupo (sem inventar rótulos)
            g["nome"] = f"{g['nome']} (crescimento médio {g['centroide']['crescimento'] * 100:+.0f}%)"
            first = seen[g["nome"].split(" (")[0]]
            if "(" not in first["nome"]:
                first["nome"] = f"{first['nome']} (crescimento médio {first['centroide']['crescimento'] * 100:+.0f}%)"
        else:
            seen[g["nome"]] = g
    return {**base, "k": k, "silhouette": round(s, 3), "grupos": groups,
            "qualidade": "boa" if s >= 0.5 else "razoável" if s >= 0.25 else "fraca (grupos pouco separados)"}
