"""Montagem das respostas da API de inteligência de mercado (somente leitura)."""
from __future__ import annotations

import numpy as np

from . import automl, intel
from .store import KINDS, RELIABILITY, MarketStore


def _clean(o):
    return automl._clean(o)


def sources(store: MarketStore, connectors, ctx_cfg: dict, creds=None) -> list[dict]:
    st = store.source_status()

    class C:  # contexto mínimo para available()
        cfg = ctx_cfg
    C.creds = creds

    out = []
    for c in connectors:
        info = c.info()
        s = st.get(c.id) or {}
        if not c.available(C):
            state = "restrita"
        else:
            state = s.get("state") or "nao_testada"
        info.update(estado=state, validada=bool(s.get("validated")), mensagem=s.get("message"),
                    ultima_tentativa=s.get("last_attempt"), ultima_coleta=s.get("last_success"),
                    registros=s.get("records", 0), cobertura=[s.get("coverage_start"), s.get("coverage_end")],
                    falhas_seguidas=s.get("failures", 0))
        out.append(info)
    return out


def series_payload(store: MarketStore, sid: int) -> dict | None:
    meta = store.get_series(sid)
    if not meta:
        return None
    obs = store.obs_detail(sid)
    fc = automl.latest(store, sid)
    return _clean({"meta": meta, "tipo_descricao": KINDS.get(meta["kind"]),
                   "confiabilidade_descricao": RELIABILITY.get(meta["reliability"]),
                   "labels": [o["ref_date"][:7] if meta["freq"] == "M" else o["ref_date"] for o in obs],
                   "valores": [o["value"] for o in obs],
                   "revisoes": sum(o["revision"] > 0 for o in obs),
                   "ultima_coleta": max((o["collected_at"] for o in obs), default=None),
                   "previsao": fc})


def _resolve(items_by_key, keys):
    return [items_by_key[k] for k in keys if k in items_by_key]


def overview(store: MarketStore) -> dict:
    opp = store.load_result("opportunities") or {}
    disc = store.load_result("discovery_headings") or {}
    clus = store.load_result("clusters") or {}
    items = opp.get("itens", [])
    byk = {i["product_key"]: i for i in items}
    rk = opp.get("rankings", {})
    slim = lambda r: {k: r.get(k) for k in ("product_key", "nome", "categoria", "score", "rotulo", "crescimento_12m",
                                             "tipo_sinal", "fontes", "serie_principal", "evidencias", "riscos")}
    out = {
        "gerado_em": opp.get("_gerado_em"),
        "n_series": store.db.query("SELECT COUNT(*) AS n FROM market_series")[0]["n"],
        "n_obs": store.db.query("SELECT COUNT(*) AS n FROM market_obs")[0]["n"],
        "n_produtos": len(items),
        "rankings": {k: [slim(x) for x in _resolve(byk, v)] for k, v in rk.items() if k != "categorias_aceleracao"},
        "categorias_aceleracao": rk.get("categorias_aceleracao", []),
        "top": [slim(x) for x in items[:20]],
        "descoberta": {"total": disc.get("total_posicoes"), "criterio": disc.get("criterio"),
                       "prioritarias": disc.get("prioritarias", [])[:30],
                       "novas_categorias": disc.get("novas_categorias", [])[:15]},
        "clusters": {k: clus.get(k) for k in ("k", "silhueta", "clusters", "aviso")},
        "pesos": opp.get("pesos"), "cambio_cny_12m": opp.get("cambio_cny_12m"),
    }
    # Brasil
    ibge = [s for s in store.series(source="ibge_pmc")]
    out["brasil_ibge"] = [{"id": s["id"], "nome": s["product_name"], "crescimento_12m": intel.yoy(intel.monthly(store, s["id"])),
                           "fim": s["fim"]} for s in ibge]
    ptax = {}
    for s in store.series(source="bcb_ptax"):
        if s["freq"] == "D":
            v = store.values(s["id"])
            if len(v):
                ptax[s["series_key"].split(":")[2]] = {"valor": float(v.iloc[-1]), "data": v.index[-1], "id": s["id"],
                                                        "var_12m": float(v.iloc[-1] / v.iloc[max(0, len(v) - 250)] - 1)}
    out["cambio"] = ptax
    # China: preços indicativos e participação
    china = []
    for s in store.series(source="gpi"):
        if s["series_key"].startswith("gpi:unitvalue:china:"):
            v = intel.monthly(store, s["id"])
            if len(v) >= 13:
                china.append({"codigo": s["series_key"].split(":")[-1], "nome": s["product_name"],
                              "categoria": s["category"], "preco_kg": float(v.iloc[-3:].mean()),
                              "var_preco_12m": intel.yoy(v), "id": s["id"]})
    out["china_precos"] = sorted(china, key=lambda r: r["codigo"])
    # comparações entre países (Comtrade + Brasil)
    comp = {}
    for s in store.series(source="comtrade"):
        g = intel.yoy(intel.monthly(store, s["id"]))
        comp.setdefault(s["product_key"], {})[s["country"]] = g
    out["paises"] = [{"product_key": k, "nome": (byk.get(k) or {}).get("nome", k), "crescimento": v,
                      "brasil": (byk.get(k) or {}).get("crescimento_12m")} for k, v in comp.items()]
    # ML
    fc = store.db.query("SELECT af.series_id, af.payload, s.series_key, s.product_name, s.indicator, s.country "
                        "FROM auto_forecasts af JOIN market_series s ON s.id = af.series_id "
                        "WHERE af.id IN (SELECT MAX(id) FROM auto_forecasts GROUP BY series_id)")
    import json
    ml = {"total": len(fc), "por_modelo": {}, "por_qualidade": {}, "exploratorias": 0, "destaques": []}
    for r in fc:
        p = json.loads(r["payload"])
        if p["status"] != "prevista":
            ml["exploratorias"] += 1
            continue
        ml["por_modelo"][p["modelo_nome"]] = ml["por_modelo"].get(p["modelo_nome"], 0) + 1
        ml["por_qualidade"][p["qualidade"]] = ml["por_qualidade"].get(p["qualidade"], 0) + 1
        if r["series_key"].startswith("comex:china:"):
            hist12 = sum(p["valores"][-12:])
            fut = sum(p["previsao"])
            ml["destaques"].append({"id": r["series_id"], "nome": r["product_name"], "modelo": p["modelo_nome"],
                                    "qualidade": p["qualidade"], "wape": (p.get("metricas") or {}).get("wape"),
                                    "variacao_prevista": fut / hist12 - 1 if hist12 else None, "tipo": p["tipo"]})
    ml["destaques"].sort(key=lambda r: -(r["variacao_prevista"] or -9))
    out["ml"] = ml
    return _clean(out)


def product(store: MarketStore, key: str) -> dict | None:
    opp = store.load_result("opportunities") or {}
    item = next((i for i in opp.get("itens", []) if i["product_key"] == key), None)
    prof = next((p for p in (store.load_result("profiles") or []) if p["product_key"] == key), None)
    series = store.series(product_key=key)
    if not item and not series:
        return None
    return _clean({"oportunidade": item, "perfil": prof, "pesos": opp.get("pesos"),
                   "series": [{k: s[k] for k in ("id", "series_key", "source", "indicator", "kind", "country", "unit",
                                                 "n_obs", "inicio", "fim", "reliability")} for s in series]})


def search(store: MarketStore, q: str) -> list[dict]:
    from .taxonomy import similarity, normalize_name
    items = (store.load_result("opportunities") or {}).get("itens", [])
    qn = normalize_name(q)
    scored = []
    for it in items:
        names = [it.get("nome") or "", it.get("nome_en") or "", it.get("nome_zh") or "", it["product_key"]]
        sim = max(similarity(q, n) for n in names if n) if q else 1
        if qn and any(qn in normalize_name(n) for n in names if n):
            sim = max(sim, 0.9)
        if sim >= 0.35 or q in it["product_key"]:
            scored.append((sim, it))
    scored.sort(key=lambda t: (-t[0], -(t[1]["score"] or 0)))
    return _clean([{k: it.get(k) for k in ("product_key", "nome", "categoria", "score", "rotulo", "crescimento_12m",
                                           "tipo_sinal", "fontes")} for _, it in scored[:50]])


def forecasts(store: MarketStore) -> list[dict]:
    import json
    rows = store.db.query("SELECT af.series_id, af.created_at, af.payload, s.series_key, s.product_name, s.indicator,"
                          " s.country, s.source, s.unit, s.product_key FROM auto_forecasts af JOIN market_series s"
                          " ON s.id = af.series_id WHERE af.id IN (SELECT MAX(id) FROM auto_forecasts GROUP BY series_id)")
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        hist12 = sum(p["valores"][-12:]) if p.get("valores") else None
        fut = sum(p.get("previsao") or []) if p["status"] == "prevista" else None
        out.append({"id": r["series_id"], "nome": r["product_name"] or r["indicator"], "indicador": r["indicator"],
                    "pais": r["country"], "fonte": r["source"], "unidade": r["unit"], "tipo": p["tipo"],
                    "status": p["status"], "modelo": p.get("modelo_nome"), "qualidade": p.get("qualidade"),
                    "wape": (p.get("metricas") or {}).get("wape"), "fva": (p.get("metricas") or {}).get("fva_vs_naive"),
                    "meses": (p.get("perfil") or {}).get("n"), "criada_em": r["created_at"],
                    "variacao_prevista": (fut / hist12 - 1) if (fut is not None and hist12) else None,
                    "limitacao": p.get("limitacao")})
    return _clean(sorted(out, key=lambda r: (r["tipo"], r["nome"] or "")))


# ------------------------------------------------------------------------- Fase 3
def _names(store):
    return {p["product_key"]: p.get("name_pt") or p.get("name_en") or p["product_key"] for p in store.products()}


def youtube(store: MarketStore) -> dict:
    yt = store.load_result("youtube") or {"produtos": [], "total_videos": 0}
    names = _names(store)
    for p in yt["produtos"]:
        p["nome"] = names.get(p["product_key"], p["product_key"])
    from datetime import date
    yt["cota_hoje"] = store.db.query("SELECT COALESCE(SUM(units), 0) AS u FROM api_quota WHERE provider = 'youtube' AND day = ?",
                                     (date.today().isoformat(),))[0]["u"]
    return _clean(yt)


def reviews(store: MarketStore) -> dict:
    return _clean(store.load_result("reviews") or {"produtos": [], "total_opinioes": 0})


def compare(store: MarketStore, keys: list[str]) -> dict:
    from .content_intel import extract_attributes
    from .content_store import ContentStore
    opp = {i["product_key"]: i for i in (store.load_result("opportunities") or {}).get("itens", [])}
    prof = {p["product_key"]: p for p in (store.load_result("profiles") or [])}
    rv = {p["product_key"]: p for p in (store.load_result("reviews") or {}).get("produtos", [])}
    yt = {p["product_key"]: p for p in (store.load_result("youtube") or {}).get("produtos", [])}
    names = _names(store)
    cs = ContentStore(store.db)
    cols, rows = [], {}

    def put(attr, i, valor, fonte=None, conf=None, url=None):
        rows.setdefault(attr, [None] * len(keys))[i] = {"valor": valor, "fonte": fonte, "confiabilidade": conf, "url": url}

    for i, k in enumerate(keys):
        o, p, r, y = opp.get(k, {}), prof.get(k, {}), rv.get(k), yt.get(k)
        cols.append({"product_key": k, "nome": o.get("nome") or names.get(k, k), "categoria": o.get("categoria")})
        nd = "não disponível em fontes autorizadas"
        put("Marca", i, nd, conf="—")
        put("Modelo", i, nd, conf="—")
        texts = [{"texto": f"{c['title'] or ''} {c['text'] or ''}", "fonte": c["source"], "url": c["url"]}
                 for c in cs.items(product_key=k, limit=400, exclude_sources=("youtube",))]
        attrs = extract_attributes(texts)
        labels = {"capacidade": "Capacidade", "potencia": "Potência", "voltagem": "Voltagem", "dimensoes": "Dimensões",
                  "garantia": "Garantia", "material": "Materiais"}
        for a, lab in labels.items():
            if a in attrs:
                v = attrs[a]
                put(lab, i, " · ".join(f"{x['valor']} ({x['mencoes']}×)" for x in v), v[0]["fonte"],
                    "C — extraído de texto; pode misturar modelos diferentes", v[0]["url"])
            else:
                put(lab, i, "não encontrado", conf="—")
        g = p.get("interesse_pt_12m") if p.get("interesse_pt_12m") is not None else (p.get("crescimento_12m") if k.startswith("wiki:") else None)
        put("Interesse (Wikipédia pt, 12 meses)", i, g, "wikimedia", "B")
        imp = o.get("importacao_relacionada") or ([{"codigo": k[4:], "nivel_12m": o.get("nivel_12m"), "crescimento_12m": o.get("crescimento_12m")}]
                                                 if k.startswith("sh4:") else [])
        if imp:
            tot = sum((x.get("nivel_12m") or 0) for x in imp)
            put("Importações da China (12 meses)", i, f"US$ {tot / 1e6:,.1f} milhões".replace(",", "X").replace(".", ",").replace("X", "."),
                "comexstat", "A — posições SH4: " + ", ".join(x["codigo"] for x in imp))
            put("Crescimento das importações", i, imp[0].get("crescimento_12m"), "comexstat", "A")
            price = None
            for x in imp:
                s = next((s for s in store.series(source="gpi") if s["series_key"] == f"gpi:unitvalue:china:{x['codigo']}"), None)
                if s:
                    v = store.values(s["id"])
                    if len(v):
                        price = float(v.iloc[-3:].mean())
                        break
            put("Preço indicativo de importação (US$/kg, China)", i,
                None if price is None else f"US$ {price:,.2f}/kg".replace(",", "X").replace(".", ",").replace("X", "."), "comexstat (derivado)", "A — média da posição SH4, não é cotação")
        else:
            put("Importações da China (12 meses)", i, None, conf="—")
        if r:
            put("Avaliações (opiniões analisadas)", i, f"{r['n']} — {r['positivos']} positivas, {r['negativos']} negativas",
                ", ".join(r["fontes"]), "B — NLP local")
            put("Principais elogios", i, ", ".join(e["aspecto"] for e in r["elogios"][:3]) or "—", ", ".join(r["fontes"]), "B — NLP local")
            put("Principais reclamações", i, ", ".join(e["aspecto"] for e in r["problemas"][:3]) or "—", ", ".join(r["fontes"]), "B — NLP local")
        else:
            put("Avaliações (opiniões analisadas)", i, "sem opiniões coletadas", conf="—")
        if y:
            put("YouTube (vídeos · visualizações)", i, f"{y['videos']} vídeos · {y['visualizacoes_total']:,} visualizações".replace(",", "."),
                "youtube", "B — dados públicos do YouTube, exibidos sem combinação")
        put("Score de oportunidade", i, o.get("score"), "GPI", f"cobertura {o.get('cobertura', 0):.0%}, confiança {o.get('confianca_rotulo', '—')}" if o else "—")
        put("Possíveis fornecedores", i, "sem fonte autorizada (Alibaba/AliExpress exigem credenciais aprovadas)", conf="—")
    return _clean({"produtos": cols, "linhas": [{"atributo": a, "valores": v} for a, v in rows.items()],
                   "aviso": "Nenhuma especificação é inventada: atributos sem fonte aparecem como não disponíveis."})


def marketplaces(store: MarketStore, connectors, cfg, creds) -> dict:
    src = {s["id"]: s for s in sources(store, connectors, cfg, creds)}
    ml = [s for s in store.series(source="mercadolivre")]
    trends = []
    for s in ml:
        v = store.values(s["id"])
        if len(v):
            trends.append({"termo": s["product_name"], "posicao": float(v.iloc[-1]), "semanas": len(v),
                           "primeira": v.index[0], "id": s["id"]})
    trends.sort(key=lambda r: r["posicao"])
    ids = ["mercadolivre", "amazon_br", "amazon_us", "shopee", "aliexpress", "alibaba", "taobao", "comparadores"]
    return _clean({"tendencias_ml": trends[:50], "fontes": [src[i] for i in ids if i in src]})
