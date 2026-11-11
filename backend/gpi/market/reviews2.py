"""
Review Intelligence 2.0 e Market Competition Intelligence (v0.5).

Opiniões (RSS, Google Notícias opt-in, Reddit — nunca YouTube, por política da plataforma):
* sentimento por aspecto (ABSA por léxico, módulo nlp.reviews) e ALVO separado: produto, vendedor,
  transporte, garantia, atendimento;
* agrupamento de reclamações (TF-IDF de palavras + K-Means, k por silhueta entre 2 e 6) com rótulo = termos
  mais característicos;
* problemas técnicos recorrentes (bateria, aquecimento, defeito elétrico, durabilidade com ≥ 2 menções);
* comparação entre marcas (marca extraída do texto; só marcas com ≥ 3 opiniões);
* tendência mensal das reclamações. Frequência de reclamações NÃO é taxa de defeito.

Concorrência (anúncios autorizados, ex.: eBay Browse):
* preços (mediana, quartis, dispersão), promoções (preço original > atual), condição;
* vendedores ÚNICOS (deduplicados por nome; vários anúncios do mesmo vendedor contam uma vez);
* marcas: participação nos ANÚNCIOS e índice HHI de concentração — não é participação de mercado;
* pressão competitiva (0–100) = 40% nº de vendedores únicos (log, saturando em 200) + 30% baixa concentração
  (1 − HHI) + 30% dispersão baixa de preço (preços parecidos = competição por preço). Indicativo.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict

import numpy as np

from ..nlp import reviews as R
from ..products import nlp as pnlp

TECH = ("bateria", "aquecimento", "defeito_eletrico", "durabilidade")


def review_intelligence(db, catalog) -> dict:
    rows = db.query("SELECT source, title, text, url, published_at, sentiment, sentiment_label, aspects, target "
                    "FROM content_items WHERE sentiment IS NOT NULL AND source IN ('rss', 'google_news', 'reddit')")
    by = defaultdict(list)
    for r in rows:
        txt = f"{r['title'] or ''}. {r['text'] or ''}"
        m = catalog.match(r["title"] or "") or catalog.match(txt[:300])
        if not m:
            continue
        r["aspects"] = json.loads(r["aspects"]) if r["aspects"] else {}
        r["marca"] = pnlp.extract_attributes(txt).get("marca")
        by[m["familia"]].append(r)
    prods, all_neg = [], []
    for pid, lst in by.items():
        pos, neg = Counter(), Counter()
        targets = Counter()
        months = Counter()
        for r in lst:
            for a, v in r["aspects"].items():
                (neg if v <= -0.05 else pos if v >= 0.05 else Counter())[a] += 1
            if r["sentiment_label"] == "negativo":
                targets[r["target"] or "produto"] += 1
                months[str(r["published_at"] or "")[:7]] += 1
                all_neg.append((pid, r))
        brands = defaultdict(list)
        for r in lst:
            if r["marca"]:
                brands[r["marca"]].append(r["sentiment"])
        n = len(lst)
        prods.append({
            "product_id": pid, "n": n, "suficiente": n >= 5,
            "elogios": [{"aspecto": R.ASPECT_NAMES.get(a, a), "mencoes": k} for a, k in pos.most_common(5)],
            "criticas": [{"aspecto": R.ASPECT_NAMES.get(a, a), "mencoes": k} for a, k in neg.most_common(6)],
            "problemas_tecnicos": [{"aspecto": R.ASPECT_NAMES[a], "mencoes": neg[a]} for a in TECH if neg[a] >= 2],
            "alvos": {R.TARGET_NAMES.get(t, t): k for t, k in targets.items()},
            "marcas": sorted([{"marca": b, "opinioes": len(v), "saldo": float(np.mean(v))} for b, v in brands.items() if len(v) >= 3],
                             key=lambda x: -x["opinioes"]),
            "tendencia_reclamacoes": dict(sorted(months.items())),
            "fontes": sorted({r["source"] for r in lst}),
            "exemplos": [{"titulo": r["title"], "url": r["url"], "sentimento": r["sentiment_label"], "alvo": r["target"]}
                         for r in sorted(lst, key=lambda r: r["sentiment"])[:3]]})
    prods.sort(key=lambda p: -p["n"])
    return {"produtos": prods, "clusters": complaint_clusters(all_neg),
            "aviso": "Contagens de opiniões publicadas nas fontes coletadas. Não são taxa de defeito nem satisfação do total de compradores."}


def complaint_clusters(items: list) -> dict:
    texts = [f"{r['title'] or ''} {r['text'] or ''}" for _, r in items]
    if len(texts) < 8:
        return {"aviso": f"reclamações insuficientes para agrupar ({len(texts)}; mínimo 8)", "grupos": []}
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score
    stop = list(pnlp.PT_HINTS | pnlp.EN_HINTS | {"não", "nao", "com", "uma", "the", "and", "este", "esse", "isso", "muito"})
    vec = TfidfVectorizer(max_features=2000, min_df=2, stop_words=stop, ngram_range=(1, 2), sublinear_tf=True)
    try:
        X = vec.fit_transform([pnlp.strip_accents(t.lower()) for t in texts])
    except ValueError:
        return {"aviso": "vocabulário insuficiente para agrupar", "grupos": []}
    best = None
    for k in range(2, min(6, len(texts) - 1) + 1):
        km = KMeans(n_clusters=k, n_init=5, random_state=0).fit(X)
        if len(set(km.labels_)) < 2:
            continue
        sc = silhouette_score(X, km.labels_)
        if best is None or sc > best[0]:
            best = (sc, km)
    if best is None:
        return {"aviso": "não foi possível separar grupos", "grupos": []}
    sc, km = best
    terms = np.asarray(vec.get_feature_names_out())
    groups = []
    for c in range(km.n_clusters):
        idx = np.flatnonzero(km.labels_ == c)
        top = terms[np.argsort(-km.cluster_centers_[c])[:5]].tolist()
        groups.append({"rotulo": ", ".join(top), "reclamacoes": int(len(idx)),
                       "produtos": sorted({items[i][0] for i in idx})[:8],
                       "exemplos": [{"titulo": items[i][1]["title"], "url": items[i][1]["url"]} for i in idx[:3]]})
    return {"silhueta": round(float(sc), 3), "grupos": sorted(groups, key=lambda g: -g["reclamacoes"])}


MIN_ELIGIBLE_PRESSURE = 10      # abaixo disso a pressão competitiva não é calculada (amostra insuficiente)


def _offer(db, pid: str, src: str, rows: list) -> dict | None:
    """Indicadores de OFERTA observada de um produto em UM marketplace (= um mercado): só anúncios do produto exato ou
    variante compatível (Listing Match); cabos/acessórios/outros produtos ficam fora; kits divididos por unidade."""
    from ..suite import listing_match as LM
    from ..suite.marketplace import SOURCE_MARKET
    latest = {}
    for r in rows:
        if r["item_id"] not in latest or r["day"] > latest[r["item_id"]]["day"]:
            latest[r["item_id"]] = r
    items = list(latest.values())
    cls, elig, rej = Counter(), [], []
    for r in items:
        m = LM.classify(r["title"], pid)
        cls[m["classe"]] += 1
        if m["elegivel"] and r["price"]:
            elig.append((r, m["unidades"] or 1))
        elif not m["elegivel"]:
            rej.append({"titulo": (r["title"] or "")[:120], "classe": m["classe"], "motivo": m.get("motivo")})
    curs = Counter(r["currency"] for r, _ in elig if r["currency"])
    cur = curs.most_common(1)[0][0] if curs else None
    el = [(r, u) for r, u in elig if r["currency"] == cur] if cur else elig
    unit = np.asarray([r["price"] / u for r, u in el], float)
    sellers = {(r["seller"] or "").strip().lower() for r, _ in el if r["seller"]}
    brand_ct = Counter(((r["brand"] or "").strip().lower() or "não informada") for r, _ in el)
    known = {b: k for b, k in brand_ct.items() if b != "não informada"}
    hhi = float(sum((k / sum(known.values())) ** 2 for k in known.values())) if known else None
    days = sorted({r["day"] for r in rows})
    n = len(el)
    out = {"product_id": pid, "fonte": src, "mercado": SOURCE_MARKET.get(src, "?"), "moeda": cur, "tipo_evidencia": "Oferta observada",
           "anuncios": len(items), "anuncios_elegiveis": n, "por_correspondencia": dict(cls),
           "excluidos_acessorios_incompativeis": sum(v for k, v in cls.items() if k not in LM.ELIGIBLE),
           "exemplos_excluidos": rej[:6], "vendedores_unicos": len(sellers), "concorrentes_observados": len(sellers),
           "marcas_distintas": len(known), "marcas": [{"marca": b, "anuncios": k} for b, k in brand_ct.most_common(8)],
           "hhi_marcas_anuncios": round(hhi, 3) if hhi is not None else None,
           "kits_ou_lotes": sum(1 for _, u in el if u > 1), "moedas_descartadas": sorted(set(curs) - {cur}),
           "dias_observados": len(days), "primeira_coleta": days[0] if days else None, "ultima_coleta": days[-1] if days else None,
           "preco_min": None, "preco_q1": None, "preco_mediano": None, "preco_q3": None, "preco_max": None, "dispersao_iqr_rel": None,
           "anuncios_em_promocao": sum(1 for r, _ in el if r["original_price"] and r["original_price"] > r["price"]),
           "pressao_competitiva": None, "posicionamento": None, "variacao_preco": [], "crescimento": None,
           "status": "amostra insuficiente"}
    if n:
        q1, med, q3 = np.percentile(unit, [25, 50, 75])
        out.update(preco_min=round(float(unit.min()), 2), preco_q1=round(float(q1), 2), preco_mediano=round(float(med), 2),
                   preco_q3=round(float(q3), 2), preco_max=round(float(unit.max()), 2),
                   dispersao_iqr_rel=round(float((q3 - q1) / med), 3) if med > 0 else None,
                   posicionamento={"economico_ate": round(float(q1), 2), "intermediario": [round(float(q1), 2), round(float(q3), 2)],
                                   "premium_acima_de": round(float(q3), 2),
                                   "nota": "Faixas pelos quartis dos preços unitários dos anúncios elegíveis — referência de posicionamento, não de venda."})
    if n >= MIN_ELIGIBLE_PRESSURE:
        disp = out["dispersao_iqr_rel"]
        out["pressao_competitiva"] = round(100 * (0.4 * min(1.0, math.log1p(len(sellers)) / math.log1p(200))
                                                  + 0.3 * (1 - (hhi if hhi is not None else 1.0))
                                                  + 0.3 * (1 - min(1.0, disp if disp is not None else 1.0))), 1)
        out["status"] = "indicativa (coleta única: sem tendência)" if len(days) < 2 else "indicativa"
    if len(days) >= 2 and n:
        ids = {r["item_id"] for r, _ in el}
        by = defaultdict(list)
        for r in rows:
            if r["item_id"] in ids and r["price"] and r["currency"] == cur:
                by[r["day"]].append(r["price"])
        out["variacao_preco"] = [{"dia": d, "preco_medio": round(float(np.mean(v)), 2)} for d, v in sorted(by.items())]
    out["fontes_rastreadas"] = [{"fonte": src, "mercado": out["mercado"], "coletas": len(days), "ultima": out["ultima_coleta"]}]
    return out


def competition(db, only: set | None = None, prev: dict | None = None, today=None, days: int = 90) -> dict:
    """Oferta observada por produto canônico × marketplace (mercado). `only` recalcula só os produtos afetados por uma nova
    coleta e preserva os demais itens de `prev` (sem recalcular o banco inteiro)."""
    from datetime import date, timedelta
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    q = ("SELECT product_id, source, item_id, day, title, brand, price, original_price, currency, seller FROM market_listings "
         "WHERE product_id IS NOT NULL AND day >= ?")
    args = [since]
    if only:
        q += " AND product_id IN (%s)" % ",".join("?" * len(only))
        args += sorted(only)
    by = defaultdict(list)
    for r in db.query(q, tuple(args)):
        by[(r["product_id"], r["source"])].append(r)
    out = [x for (pid, src), lst in by.items() if (x := _offer(db, pid, src, lst))]
    if only and prev:
        out += [x for x in prev.get("itens", []) if x.get("product_id") not in only]
    out.sort(key=lambda x: (x["pressao_competitiva"] is None, -(x["pressao_competitiva"] or 0), -x["anuncios_elegiveis"]))
    return {"itens": out, "aviso": ("Oferta observada em anúncios ativos de fontes autorizadas. Anúncios não são vendas, demanda "
                                    "comprovada nem participação de mercado; só produto exato/variante compatível entra nas "
                                    "estatísticas (cabos, acessórios e outros produtos ficam fora). Cada marketplace é um mercado: "
                                    "eBay = EUA, Mercado Livre = Brasil — não se misturam. Uma coleta única não indica crescimento."),
            "definicao_pressao": ("40% vendedores únicos (escala log, satura em 200) + 30% (1 − HHI das marcas declaradas) + 30% preços "
                                  f"parecidos; só com ≥ {MIN_ELIGIBLE_PRESSURE} anúncios elegíveis.")}


def competition_cached(store) -> dict:
    """Resultado 'competition' em cache; se foi invalidado por uma nova coleta, recalcula (barato: só anúncios)."""
    r = store.load_result("competition")
    if r is None:
        r = competition(store.db)
        store.save_result("competition", r)
    return r
