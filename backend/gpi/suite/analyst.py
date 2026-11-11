"""Assistente de Inteligência do GPI — interface analítica sobre os mecanismos REAIS do sistema.

Pergunta → interpretação (regras) → ferramenta interna do GPI (SQL + cálculos determinísticos já existentes) → evidências →
resposta explicável (conclusão, dados, métricas, fontes, período, confiança, limitações, próximas investigações).
A IA local (llama.cpp + GGUF, módulo ai.runtime) é OPCIONAL e só reescreve a conclusão em linguagem natural a partir dos
fatos calculados; números que não existam nos fatos são removidos (verificação). Sem modelo instalado, a resposta
estruturada é devolvida igual (Modo Essencial). Nenhuma pesquisa não executada é relatada como feita."""
from __future__ import annotations

import json
import re

from ..ai.assistant import THINK_RX

INTENTS = [
    ("trade_growth", re.compile(r"(cresc|aument|subi|evolu).{0,60}(importa)|(importa).{0,60}(cresc|aument|subi)", re.I)),
    ("company", re.compile(r"(fornecedor|exportador|embarque|importador|empresa|concorrente).{0,80}(empresa|embarque|importador)|"
                           r"embarques? (?:p[úu]blicos? )?(?:da|de|associad)", re.I)),
    ("compare", re.compile(r"\bcompar", re.I)),
    ("evidence", re.compile(r"evid[êe]ncias?.{0,40}(sustent|apoi|oportunidade)", re.I)),
    ("worth", re.compile(r"(vale (?:a pena )?investigar|vale importar|devo importar|investigar a importa)", re.I)),
    ("strongest_growth", re.compile(r"(investigad|monitorad).{0,80}(cresc|evid[êe]ncia)", re.I)),
    ("attention", re.compile(r"(aten[çc][ãa]o|em alta|tend[êe]ncia|mais pesquisad|mais comentad|emergent|internet)", re.I)),
]
HELP = ["Quais categorias aumentaram suas importações nos últimos 12 meses?",
        "Quais fornecedores aparecem nos embarques associados à empresa \"ACME Imports\"?",
        "Quais produtos estão recebendo atenção na internet?", "Vale investigar a importação de uma máquina de waffle?",
        "Compare carregadores GaN 65W encontrados no eBay.", "Quais evidências sustentam a oportunidade de air fryer?",
        "Quais produtos investigados apresentam evidências mais fortes de crescimento?"]


def intent(q: str) -> str:
    for name, rx in INTENTS:
        if rx.search(q or ""):
            return name
    return "unknown"


def _ans(ferramenta, conclusao, dados=None, metricas=None, fontes=None, periodo=None, confianca="baixa", limitacoes=None,
         proximas=None, executado=True):
    return {"ferramenta": ferramenta, "consulta_executada": executado, "conclusao": conclusao, "dados_utilizados": dados or [],
            "metricas": metricas or {}, "fontes": fontes or [], "periodo": periodo, "confianca": confianca,
            "limitacoes": limitacoes or [], "proximas_investigacoes": proximas or []}


def _load(db, name):
    from . import targeted as TG
    return TG._load(db, name)


def _product_from(q: str):
    from ..intel import understanding as U
    t = re.sub(r"(?i)\b(vale (?:a pena )?investigar|a importa[çc][ãa]o de|importa[çc][ãa]o|quais|evid[êe]ncias|sustentam|"
               r"a oportunidade de|a oportunidade|oportunidade|compare|encontrad[oa]s? no ebay|no ebay|no mercado livre|de uma|de um|esta|desta|"
               r"sobre)\b", " ", q or "")
    t = re.sub(r"[?!.,;:\"]", " ", t).strip()
    for txt in (t, q or ""):
        for lang in ("pt", "en"):
            u = U.understand(txt, lang)
            if u.get("produto_id"):
                return u["produto_id"], t
    return None, t


def _opp_rows(db):
    opp = _load(db, "opportunity3")
    if opp is None:
        from ..market.reviews2 import competition
        from ..products import opportunity3 as O3
        opp = O3.build(_load(db, "consumer") or {}, _load(db, "social"), _load(db, "reviews2"), _load(db, "competition") or competition(db), db)
    return opp.get("produtos") or []


def _row_for(db, pid):
    rows = _opp_rows(db)
    head = pid.split(":")[0]
    return next((r for r in rows if r["product_id"] == pid), None) or next((r for r in rows if r["product_id"].split(":")[0] == head), None)


# --------------------------------------------------------------------------------------------------- ferramentas
def t_trade_growth(db, q):
    from . import trade as TR
    cg = TR.category_growth(db, 50)
    items = cg["itens"]
    cat = None
    for c in ("eletroport", "eletr", "brinquedo", "ferrament", "cozinha", "beleza", "automot", "ilumina", "têxt", "telefon"):
        if c in (q or "").lower():
            cat = c
    if cat:
        items = [i for i in items if cat in (i.get("categoria") or "").lower() or cat in (i.get("descricao") or "").lower()]
    if not items:
        return _ans("Comércio exterior — crescimento de categorias", cg["vazio"] or "Nenhuma posição SH4 com os filtros e ≥ 24 meses de dados.",
                    fontes=[cg["fonte"]], limitacoes=[cg["aviso"]], proximas=["Sincronize o Comex Stat (Central de Integrações → Sincronização)."],
                    executado=bool(cg["itens"]) or cg["vazio"] is None)
    top = [i for i in items if (i["variacao_12m_pct"] or 0) > 0][:8]
    concl = ("Posições SH4 com maior crescimento das importações brasileiras (12 meses vs. 12 anteriores, US$ FOB): " +
             "; ".join(f"{i['codigo']} {i['descricao'][:50]} {i['variacao_12m_pct']:+.1f}%" for i in top) + ".") if top else \
        "Nenhuma posição com crescimento positivo no período."
    return _ans("Comércio exterior — crescimento de categorias", concl, dados=top,
                metricas={"posicoes_avaliadas": len(cg["itens"]), "filtro_categoria": cat}, fontes=[cg["fonte"]],
                periodo=f"12 meses até {top[0]['ate']}" if top else None, confianca="alta" if top else "média",
                limitacoes=[cg["aviso"], "Crescimento de importação da classificação ≠ crescimento de procura de um produto."],
                proximas=["Abra Trade Intelligence e detalhe o código por NCM 8 dígitos e país de origem."])


def t_company(db, q):
    from . import shipments as SH
    m = re.search(r"[\"“'']([^\"”'']{2,120})[\"”'']", q or "") or re.search(r"(?:empresa|importador[a]?|concorrente)\s+([A-Z0-9][\w&.,\- ]{2,80})", q or "")
    if not m:
        return _ans("Embarques — investigação de empresa", "Informe o nome da empresa entre aspas (ex.: \"ACME Imports Inc\").",
                    executado=False, limitacoes=["Nenhuma consulta foi executada."])
    r = SH.investigate_company(db, m.group(1).strip())
    if not r.get("embarques"):
        return _ans("Embarques — investigação de empresa", SH.NO_DATA, dados=r.get("nomes_parecidos_nao_unidos"),
                    fontes=[f["fonte"] for f in r.get("fontes_consultadas", [])], confianca="—", limitacoes=r.get("limitacoes"),
                    proximas=["Importe B/L/manifestos (PDF, CSV, XLSX) obtidos legitimamente em Trade Intelligence → Empresas e embarques."])
    k = "fornecedores_observados" if "fornecedores_observados" in r else "clientes_observados"
    sup = r[k][:8]
    return _ans("Embarques — investigação de empresa",
                f"{r['resultado']} Parceiros documentados: " + "; ".join(f"{s['empresa']} ({s['embarques']})" for s in sup) + ".",
                dados=sup, metricas={"embarques": len(r["embarques"]), "concentracao_hhi": r["concentracao_parceiros_hhi"],
                                     "categorias": r["categorias"][:5]},
                fontes=[e["fonte"] for e in r["evidencias"]], periodo=(r.get("evolucao") or {}).get("periodo"), confianca=r["confianca"],
                limitacoes=r["limitacoes"], proximas=["Verifique a identidade dos parceiros no cadastro (nomes parecidos não são unidos)."])


def t_attention(db, q):
    rows = _opp_rows(db)
    groups = {"Mais pesquisados (volume de busca verificado)": [r for r in rows if "consumer_search_strength" in r["dimensoes"]],
              "Crescimento de atenção (histórico suficiente)": [r for r in rows if (r["dimensoes"].get("trend_persistence") or 0) >= 60],
              "Mais comentados (menções sociais permitidas)": [r for r in rows if "social_momentum" in r["dimensoes"]],
              "Produtos com oferta relevante (anúncios ≠ demanda)": [r for r in rows if r.get("oferta_observada")],
              "Produtos para investigação (elegíveis)": [r for r in rows if r.get("elegivel_para_decisao")]}
    out = {k: [{"produto": r["nome"], "produto_id": r["product_id"], "indice": r.get("indice"), "prioridade": r["prioridade"]}
               for r in sorted(v, key=lambda r: -(r.get("indice") or r.get("indice_parcial") or 0))[:8]] for k, v in groups.items()}
    new = [r for r in rows if (r.get("explicacao") or {}).get("dimensoes_ausentes") is not None and r.get("oferta_observada")
           and all((o.get("dias_observados") or 0) <= 1 for o in r["oferta_observada"])]
    out["Produtos emergentes (identificados recentemente — 1 coleta)"] = [{"produto": r["nome"], "produto_id": r["product_id"]} for r in new[:8]]
    filled = {k: v for k, v in out.items() if v}
    if not filled:
        return _ans("Tendências de produtos", "Sem sinais de atenção calculados: sincronize as fontes de busca/marketplaces ou rode pesquisas.",
                    limitacoes=["Nenhum ranking é exibido sem métrica legítima da fonte."], executado=True)
    concl = " ".join(f"{k}: {', '.join(x['produto'] for x in v[:4])}." for k, v in filled.items())
    return _ans("Tendências de produtos", concl, dados=filled, metricas={k: len(v) for k, v in groups.items()},
                fontes=["Opportunity Engine 3.0 (resultados em cache do GPI)"], confianca="média",
                limitacoes=["Grupos só aparecem quando a métrica existe; anúncios não são demanda; atenção ≠ intenção de compra."],
                proximas=["Pesquise os produtos listados em Pesquisa de Produtos (rápida/completa)."])


def t_product(db, q, kind):
    from . import trade as TR
    pid, term = _product_from(q)
    if not pid:
        return _ans("Produto", f"Não identifiquei o produto em \"{term[:80]}\". Informe o nome (ex.: carregador GaN 65W).", executado=False)
    row = _row_for(db, pid)
    comp = [c for c in ((_load(db, "competition") or {}).get("itens") or []) if c["product_id"].split(":")[0] == pid.split(":")[0]]
    cc = TR.candidate_codes(db, term)
    tstats = []
    for c in cc["candidatos"][:2]:
        rows = TR.stored(db, "BR", c["codigo"]) or TR.local_sh4(db, c["codigo"])
        if rows:
            an = TR.analyze([r for r in rows if r["partner"] != "China"] if rows and "fetched_at" not in rows[0] else rows)
            tstats.append({"codigo": c["codigo"], "variacao_12m_pct": an["variacoes"].get("variacao_12m_pct"),
                           "ultimos_12m_usd": an["variacoes"].get("ultimos_12m_usd")})
    dados = {"oportunidade": row and {k: row.get(k) for k in ("prioridade", "indice", "indice_parcial", "elegivel_para_decisao",
                                                             "tipos_de_evidencia", "explicacao")},
             "oferta_observada": comp, "comercio_exterior_categoria": tstats}
    lim = ["Anúncios são oferta observada, não vendas.", TR.SCOPE_WARN]
    if kind == "compare":
        if not comp:
            return _ans("Comparação de anúncios", "Nenhum anúncio coletado deste produto. Rode uma pesquisa (eBay/Mercado Livre) primeiro.",
                        executado=True, limitacoes=lim)
        concl = " ".join(f"{c['mercado']} ({c['fonte']}): {c['anuncios_elegiveis']} anúncios elegíveis de {c['anuncios']}, "
                         f"preço/unid. {c['preco_min']}–{c['preco_max']} (mediana {c['preco_mediano']}) {c['moeda']}, "
                         f"{c['concorrentes_observados']} vendedores, {c['marcas_distintas']} marcas." for c in comp)
        return _ans("Comparação de anúncios", concl, dados=comp, fontes=sorted({c["fonte"] for c in comp}),
                    periodo=", ".join(f"{c['primeira_coleta']}→{c['ultima_coleta']}" for c in comp),
                    confianca="média" if any(c["anuncios_elegiveis"] >= 10 for c in comp) else "baixa", limitacoes=lim,
                    proximas=["Use o Comparador (até 5 anúncios) para diferenças técnicas declaradas."])
    if not row and not comp and not tstats:
        return _ans("Oportunidade", "Evidência insuficiente — investigação recomendada. Não há dados do produto no GPI.",
                    executado=True, limitacoes=lim, proximas=[f"Rode Pesquisa de Produtos para \"{term}\"."])
    parts = []
    if row:
        parts.append(f"Opportunity Engine: prioridade {row['prioridade']}" +
                     (f", índice {row['indice']:.0f}" if row.get("indice") is not None else
                      " — índice parcial, não elegível (Evidência insuficiente — investigação recomendada)") + ".")
        ev = [k for k, v in (row.get("tipos_de_evidencia") or {}).items() if v and k != "Evidência insuficiente"]
        if ev:
            parts.append("Evidências presentes: " + ", ".join(ev) + ".")
        comps = (row.get("explicacao") or {}).get("componentes") or []
        if kind == "evidence" and comps:
            parts.append("Componentes: " + "; ".join(f"{c['dimensao']} = {c['valor']:.0f}" for c in comps if c.get("valor") is not None) + ".")
    for t in tstats:
        if t["variacao_12m_pct"] is not None:
            parts.append(f"Categoria (SH {t['codigo']}, Brasil): {t['variacao_12m_pct']:+.1f}% nas importações em 12 meses (classificação ampla).")
    for c in comp:
        parts.append(f"Oferta {c['mercado']}: {c['anuncios_elegiveis']} anúncios elegíveis, mediana {c['preco_mediano']} {c['moeda']}.")
    conf = "alta" if row and row.get("elegivel_para_decisao") else "baixa"
    return _ans("Oportunidade" if kind != "evidence" else "Evidências da oportunidade", " ".join(parts), dados=dados,
                fontes=["Opportunity Engine 3.0", "Comex Stat (séries locais)", *sorted({c["fonte"] for c in comp})], confianca=conf,
                limitacoes=lim + ([] if conf == "alta" else ["Score não elegível para decisão: faltam dimensões de demanda."]),
                proximas=["Pesquisa completa do produto", "Trade Intelligence: NCM 8 dígitos × país", "Fornecedores e regulatório"])


def t_strongest(db, q):
    rows = _opp_rows(db)
    inv = {r["product_id"] for r in db.query("SELECT DISTINCT product_id FROM research_source_runs WHERE product_id IS NOT NULL")} \
        if db.query("SELECT name FROM sqlite_master WHERE name = 'research_source_runs'") else set()
    cand = [r for r in rows if not inv or r["product_id"] in inv or r["product_id"].split(":")[0] in {i.split(":")[0] for i in inv}] or rows
    proven = [r for r in cand if (r.get("tipos_de_evidencia") or {}).get("Crescimento comprovado")]
    elig = sorted([r for r in cand if r.get("elegivel_para_decisao")], key=lambda r: -(r.get("indice") or 0))
    if not cand:
        return _ans("Produtos investigados", "Nenhum produto investigado com indicadores calculados.", executado=True,
                    proximas=["Rode pesquisas de produtos."])
    concl = (("Com crescimento comprovado (série mensal de busca ≥ 15 meses, tendência significativa): " +
              ", ".join(r["nome"] for r in proven[:6]) + ". ") if proven else "Nenhum produto com crescimento comprovado. ") + \
            (("Maiores índices elegíveis (mesma escala 0–100): " + ", ".join(f"{r['nome']} {r['indice']:.0f}" for r in elig[:6]) + ".")
             if elig else "Nenhum índice elegível — evidência insuficiente para ranquear.")
    return _ans("Produtos investigados", concl, dados=[{"produto": r["nome"], "indice": r.get("indice"), "prioridade": r["prioridade"],
                                                        "tipos": r.get("tipos_de_evidencia")} for r in (proven + elig)[:12]],
                metricas={"investigados": len(cand), "crescimento_comprovado": len(proven), "elegiveis": len(elig)},
                fontes=["Opportunity Engine 3.0", "pesquisas salvas"], confianca="média" if elig else "baixa",
                limitacoes=["Só índices elegíveis são comparados (mesma escala); índices parciais não entram no ranking."])


TOOLS = {"trade_growth": t_trade_growth, "company": t_company, "attention": t_attention, "strongest_growth": t_strongest,
         "compare": lambda db, q: t_product(db, q, "compare"), "evidence": lambda db, q: t_product(db, q, "evidence"),
         "worth": lambda db, q: t_product(db, q, "worth")}


def ask(db, question: str, llm=None, use_llm: bool = False) -> dict:
    q = (question or "").strip()[:1000]
    it = intent(q)
    fn = TOOLS.get(it)
    if not fn:
        r = _ans("—", "Não reconheci a pergunta entre as análises disponíveis. Nada foi consultado.", executado=False,
                 proximas=HELP)
    else:
        try:
            r = fn(db, q)
        except Exception as e:  # noqa: BLE001 — a falha da ferramenta é relatada, nunca substituída por texto inventado
            r = _ans(it, f"A ferramenta falhou: {type(e).__name__}. Nenhum resultado foi produzido.", executado=False,
                     limitacoes=[str(e)[:200]])
    r.update({"pergunta": q, "intencao": it, "modo": "essencial (regras + cálculos)"})
    if use_llm and llm is not None and r["consulta_executada"]:
        try:
            st = llm.status()
            if st.get("modo_efetivo") == "ia_local":
                facts = json.dumps({k: r[k] for k in ("conclusao", "metricas", "periodo", "confianca", "limitacoes")}, ensure_ascii=False,
                                   default=str)[:6000]
                out = llm.generate([{"role": "system", "content": "Você é o analista do GPI. Reescreva a conclusão em português claro usando "
                                     "SOMENTE os fatos JSON fornecidos. Não acrescente números, fontes ou pesquisas. Máximo 5 frases."},
                                    {"role": "user", "content": f"Pergunta: {q}\nFatos: {facts}"}], f"an-{abs(hash(q))}")
                txt = THINK_RX.sub("", out.get("texto") or "").strip()
                allowed = set(re.findall(r"\d+(?:[.,]\d+)?", facts + q))
                bad = [n for n in re.findall(r"\d+(?:[.,]\d+)?", txt) if n not in allowed]
                if txt and not bad:
                    r["conclusao_ia"] = txt
                    r["modo"] = "IA local (texto verificado contra os fatos calculados)"
                else:
                    r["ia_descartada"] = "a IA local citou números ausentes dos fatos" if bad else "resposta vazia"
        except Exception as e:  # noqa: BLE001
            r["ia_descartada"] = f"IA local indisponível ({type(e).__name__})"
    return r
