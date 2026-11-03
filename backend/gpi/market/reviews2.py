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


def competition(db) -> dict:
    rows = db.query("SELECT * FROM market_listings WHERE day = (SELECT MAX(day) FROM market_listings m2 WHERE m2.product_id = "
                    "market_listings.product_id AND m2.source = market_listings.source)")
    by = defaultdict(list)
    for r in rows:
        by[(r["product_id"], r["source"], r["currency"] or "?")].append(r)
    out = []
    for (pid, src, cur), lst in by.items():
        prices = np.asarray([r["price"] for r in lst if r["price"]], float)
        if len(prices) < 3:
            continue
        sellers = {(r["seller"] or "").strip().lower() for r in lst if r["seller"]}
        brand_ct = Counter((r["brand"] or "sem marca identificada") for r in lst)
        shares = np.asarray(list(brand_ct.values()), float) / len(lst)
        hhi = float(np.sum(shares ** 2))
        promo = sum(1 for r in lst if r["original_price"] and r["price"] and r["original_price"] > r["price"])
        q1, med, q3 = np.percentile(prices, [25, 50, 75])
        disp = float((q3 - q1) / med) if med > 0 else None
        pressure = 100 * (0.4 * min(1.0, math.log1p(len(sellers)) / math.log1p(200)) + 0.3 * (1 - hhi)
                          + 0.3 * (1 - min(1.0, disp or 1.0)))
        hist = db.query("SELECT day, AVG(price) AS p FROM market_listings WHERE product_id = ? AND source = ? AND currency = ? "
                        "GROUP BY day ORDER BY day", (pid, src, cur))
        out.append({"product_id": pid, "fonte": src, "moeda": cur, "anuncios": len(lst), "vendedores_unicos": len(sellers),
                    "preco_mediano": float(med), "preco_q1": float(q1), "preco_q3": float(q3), "dispersao_iqr_rel": disp,
                    "anuncios_em_promocao": promo, "marcas": [{"marca": b, "anuncios": k} for b, k in brand_ct.most_common(8)],
                    "hhi_marcas_anuncios": round(hhi, 3), "pressao_competitiva": round(pressure, 1),
                    "variacao_preco": [{"dia": h["day"], "preco_medio": h["p"]} for h in hist]})
    out.sort(key=lambda x: -x["pressao_competitiva"])
    return {"itens": out, "aviso": ("Baseado em anúncios ativos de fontes autorizadas. Anúncios não são vendas; vendedores são "
                                    "deduplicados pelo nome; a participação de marcas é nos anúncios, não no mercado."),
            "definicao_pressao": "40% vendedores únicos (escala log, satura em 200) + 30% (1 − HHI das marcas) + 30% preços parecidos."}
