"""
Descoberta de produtos, séries derivadas, perfis, clusterização e ranking de oportunidades.
Todas as regras e pesos estão documentados na página Metodologia (seções 13–17).
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

from ..analytics import classification as cl
from . import automl, taxonomy as tx
from .store import MarketStore

# --------------------------------------------------------------------------- utilidades


def monthly(store: MarketStore, sid: int) -> pd.Series:
    return automl.regular_monthly(store.values(sid))


def yoy(s: pd.Series, k: int = 12) -> float | None:
    """Crescimento dos últimos k meses sobre os k meses equivalentes do ano anterior."""
    if len(s) < k + 12:
        return None
    a, b = s.iloc[-k:].sum(), s.iloc[-k - 12:-12].sum()
    return float(a / b - 1) if b > 0 else None


def persistence(s: pd.Series) -> float | None:
    """Fração dos últimos 12 meses com valor acima do mesmo mês do ano anterior."""
    if len(s) < 24:
        return None
    a, b = s.iloc[-12:].values, s.iloc[-24:-12].values
    return float(np.mean(a > b))


def volatility(s: pd.Series) -> float | None:
    """Desvio-padrão das variações mensais do log (log-retornos)."""
    if len(s) < 13:
        return None
    lr = np.diff(np.log1p(s.values.astype(float)))
    return float(np.std(lr, ddof=1))


def pct_rank(values: dict) -> dict:
    """Posição percentil (0..1) de cada valor; None permanece None."""
    ks = [k for k, v in values.items() if v is not None and np.isfinite(v)]
    if not ks:
        return {k: None for k in values}
    arr = np.array([values[k] for k in ks])
    ranks = stats.rankdata(arr, method="average")
    out = {k: None for k in values}
    for k, r in zip(ks, ranks):
        out[k] = float((r - 1) / (len(ks) - 1)) if len(ks) > 1 else 0.5
    return out


# --------------------------------------------------------------------------- descoberta


def discover(store: MarketStore, min_value_usd: float = 1e6) -> dict:
    """Ranqueia TODAS as posições SH4 importadas da China (não apenas a taxonomia)."""
    china = {r["product_key"]: r for r in store.series(source="comexstat")
             if r["series_key"].startswith("comex:china:") and r["series_key"].endswith(":fob")}
    total = {r["product_key"]: r for r in store.series(source="comexstat")
             if r["series_key"].startswith("comex:total:") and r["series_key"].endswith(":fob")}
    rows = []
    for pk, meta in china.items():
        s = monthly(store, meta["id"])
        if len(s) < 13:
            continue
        l12 = float(s.iloc[-12:].sum())
        if l12 < min_value_usd:
            continue
        share = None
        if pk in total:
            t = monthly(store, total[pk]["id"])
            common = s.index.intersection(t.index)[-12:]
            if len(common) and t[common].sum() > 0:
                share = float(s[common].sum() / t[common].sum())
        code = pk.split(":")[1]
        rows.append({"product_key": pk, "codigo": code, "nome": meta["product_name"], "categoria": meta["category"],
                     "prioritaria": meta["category"] in tx.PRIORITY_CATEGORIES, "importado_12m_usd": l12,
                     "crescimento_12m": yoy(s), "crescimento_6m": yoy(s, 6), "participacao_china": share,
                     "ultimo_mes": str(s.index[-1])})
    rows.sort(key=lambda r: -r["importado_12m_usd"])
    pri = [r for r in rows if r["prioritaria"]]
    others = [r for r in rows if not r["prioritaria"] and (r["crescimento_12m"] or 0) > 0.3
              and r["importado_12m_usd"] >= 5 * min_value_usd]
    others.sort(key=lambda r: -(r["crescimento_12m"] or 0))
    return {"total_posicoes": len(rows), "prioritarias": pri, "novas_categorias": others[:30],
            "criterio": f"importações da China ≥ US$ {min_value_usd:,.0f} nos últimos 12 meses".replace(",", ".")}


# --------------------------------------------------------------------------- séries derivadas


def build_derived(store: MarketStore) -> int:
    """Participação da China e preço médio indicativo (US$/kg) por posição SH4."""
    n = 0
    series = {r["series_key"]: r for r in store.series(source="comexstat")}
    for key, meta in series.items():
        if not (key.startswith("comex:china:") and key.endswith(":fob")):
            continue
        code = key.split(":")[2]
        fob = monthly(store, meta["id"])
        kgm = series.get(f"comex:china:{code}:kg")
        if kgm:
            kg = monthly(store, kgm["id"])
            idx = fob.index.intersection(kg.index)
            obs = [(f"{p}-01", float(fob[p] / kg[p])) for p in idx if kg[p] > 0]
            if obs:
                sid = store.upsert_series(f"gpi:unitvalue:china:{code}", dict(
                    source="gpi", indicator="Preço médio indicativo de importação da China (FOB/kg)",
                    kind="derivado", product_key=meta["product_key"], product_name=meta["product_name"],
                    category=meta["category"], country="China → Brasil", unit="US$/kg", currency="USD", freq="M",
                    origin_url=meta["origin_url"], method="valor FOB ÷ peso líquido (Comex Stat), calculado pelo GPI",
                    reliability="A"))
                store.upsert_obs(sid, obs)
                n += 1
        tm = series.get(f"comex:total:{code}:fob")
        if tm:
            tot = monthly(store, tm["id"])
            idx = fob.index.intersection(tot.index)
            obs = [(f"{p}-01", float(fob[p] / tot[p])) for p in idx if tot[p] > 0]
            if obs:
                sid = store.upsert_series(f"gpi:share:china:{code}", dict(
                    source="gpi", indicator="Participação da China nas importações brasileiras (valor FOB)",
                    kind="derivado", product_key=meta["product_key"], product_name=meta["product_name"],
                    category=meta["category"], country="Brasil", unit="fração (0–1)", currency=None, freq="M",
                    origin_url=meta["origin_url"], method="FOB China ÷ FOB todas as origens, calculado pelo GPI",
                    reliability="A"))
                store.upsert_obs(sid, obs)
                n += 1
    return n


# --------------------------------------------------------------------------- perfis de produto


def product_profiles(store: MarketStore) -> list[dict]:
    """Junta, por produto, as séries de todas as fontes. Conceitos (Wikipédia) ligam-se
    às posições SH4 relacionadas pela taxonomia; a deduplicação por similaridade de nomes
    une conceitos equivalentes."""
    by_prod = defaultdict(list)
    for s in store.series():
        if s["product_key"] and s["freq"] == "M":
            by_prod[s["product_key"]].append(s)
    prods = {p["product_key"]: p for p in store.products()}
    profiles = []
    for pk, lst in by_prod.items():
        p = prods.get(pk, {})
        feats = {"product_key": pk, "nome": p.get("name_pt") or p.get("name_en") or lst[0]["product_name"] or pk,
                 "nome_en": p.get("name_en"), "nome_zh": p.get("name_zh"),
                 "categoria": p.get("category") or lst[0]["category"], "origem": p.get("origin"),
                 "fontes": sorted({s["source"] for s in lst if s["source"] != "gpi"}), "series": {}}
        for s in lst:
            feats["series"][s["series_key"]] = s["id"]
        primary = None
        if pk.startswith("sh4:"):
            code = pk.split(":")[1]
            primary = next((s for s in lst if s["series_key"] == f"comex:china:{code}:fob"), None)
            feats["tipo_sinal"] = "importação (US$ FOB, China → Brasil)"
        else:
            pv = [s for s in lst if s["source"] == "wikimedia"]
            primary = next((s for s in pv if ":pt:" in s["series_key"]), None) or \
                next((s for s in pv if ":en:" in s["series_key"]), None)
            feats["tipo_sinal"] = "interesse (visualizações da Wikipédia)"
        if not primary:
            continue
        y = monthly(store, primary["id"])
        if len(y) < 13:
            continue
        feats["serie_principal"] = primary["id"]
        feats["meses"] = len(y)
        win = y.iloc[-36:]
        tr = cl.trend_test(win.values)
        se = cl.seasonality_strength(y.values[-48:], 12)
        feats.update({
            "nivel_12m": float(y.iloc[-12:].sum()),
            "crescimento_12m": yoy(y), "crescimento_6m": yoy(y, 6),
            "persistencia": persistence(y), "volatilidade": volatility(y),
            "tendencia_rel": tr.get("inclinacao_relativa"), "tendencia_sig": bool(tr.get("significativa")),
            "tendencia_dir": tr.get("direcao"),
            "sazonalidade": (se["fs"] if se and se["significativa"] else 0.0) if se else None,
        })
        if len(y) >= 27:
            base = y.iloc[-27:-3].values
            feats["surto"] = bool(y.iloc[-3:].mean() > base.mean() + 2 * base.std(ddof=1))
        ment = next((x for x in lst if x["series_key"] == f"gpi:mentions:{pk}"), None)
        feats["mencoes_12m"] = float(monthly(store, ment["id"]).iloc[-12:].sum()) if ment else None
        g12, g6 = feats["crescimento_12m"], feats["crescimento_6m"]
        feats["aceleracao"] = (g6 - g12) if (g6 is not None and g12 is not None) else None
        # sinais complementares
        if pk.startswith("wiki:"):
            for lang in ("pt", "en", "zh"):
                s = next((x for x in lst if x["series_key"] == f"wiki:pv:{lang}:{pk}"), None)
                if s:
                    feats[f"interesse_{lang}_12m"] = yoy(monthly(store, s["id"]))
            hs = (p.get("hs_codes") or "").split(",")
            feats["sh4_relacionadas"] = [h for h in hs if h]
        else:
            code = pk.split(":")[1]
            u = next((x for x in lst if x["series_key"] == f"gpi:unitvalue:china:{code}"), None)
            feats["preco_kg_12m"] = yoy(monthly(store, u["id"])) if u else None
            sh = next((x for x in lst if x["series_key"] == f"gpi:share:china:{code}"), None)
            feats["participacao_china"] = float(monthly(store, sh["id"]).iloc[-12:].mean()) if sh else None
            others = [x for x in lst if x["source"] == "comtrade"]
            feats["outros_paises_12m"] = {x["country"]: yoy(monthly(store, x["id"])) for x in others}
        profiles.append(feats)
    # liga conceitos às posições SH4 (evidência de importação para os conceitos de interesse)
    imp = {f["product_key"]: f for f in profiles if f["product_key"].startswith("sh4:")}
    for f in profiles:
        if f["product_key"].startswith("wiki:"):
            linked = [imp[f"sh4:{h}"] for h in f.get("sh4_relacionadas", []) if f"sh4:{h}" in imp]
            f["importacao_relacionada"] = [{"codigo": x["product_key"][4:], "nome": x["nome"],
                                            "crescimento_12m": x["crescimento_12m"], "nivel_12m": x["nivel_12m"]}
                                           for x in linked]
            if linked:
                f["fontes"] = sorted(set(f["fontes"]) | {"comexstat"})
    # deduplicação de conceitos equivalentes (mesmo nome normalizado)
    names = [f["nome"] for f in profiles]
    for grp in tx.dedupe(names):
        if len(grp) > 1:
            keep = grp[0]
            for i in grp[1:]:
                profiles[i]["duplicado_de"] = profiles[keep]["product_key"]
    return [f for f in profiles if "duplicado_de" not in f]


# --------------------------------------------------------------------------- rótulos interpretáveis

LABELS = ["Tendência emergente", "Crescimento acelerado", "Crescimento estável", "Alta sazonalidade",
          "Mercado maduro", "Possível declínio", "Alta volatilidade", "Oportunidade de nicho"]


def label(f: dict, level_pct: float | None) -> tuple[str, str]:
    g, a = f.get("crescimento_12m"), f.get("aceleracao")
    vol, sea = f.get("volatilidade") or 0, f.get("sazonalidade") or 0
    if g is not None and g > 0.5 and (level_pct is not None and level_pct < 0.5):
        return LABELS[0], f"cresceu {g:.0%} em 12 meses a partir de base pequena"
    if g is not None and g > 0.25 and a is not None and a > 0.05:
        return LABELS[1], f"crescimento de {g:.0%} em 12 meses e acelerando ({a:+.0%} no semestre)"
    if f.get("tendencia_sig") and f.get("tendencia_dir") == "queda" or (g is not None and g < -0.15):
        return LABELS[5], "tendência de queda significativa" if f.get("tendencia_sig") else f"queda de {g:.0%} em 12 meses"
    if f.get("tendencia_sig") and f.get("tendencia_dir") == "crescimento":
        return LABELS[2], "tendência de alta estatisticamente significativa (Mann–Kendall)"
    if sea >= 0.6:
        return LABELS[3], f"sazonalidade significativa (F_S = {sea:.2f})"
    if vol > 0.35:
        return LABELS[6], f"variação mensal típica de {vol:.0%}"
    if g is not None and g > 0.1 and level_pct is not None and level_pct < 0.3:
        return LABELS[7], "crescimento moderado em mercado pequeno"
    return LABELS[4], "sem tendência significativa e baixa volatilidade"


# --------------------------------------------------------------------------- clusterização

FEATURES = ["crescimento_12m", "aceleracao", "tendencia_rel", "sazonalidade", "volatilidade", "persistencia",
            "nivel_pct"]


def clusterize(profiles: list[dict]) -> dict:
    from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
    from sklearn.decomposition import PCA
    from sklearn.ensemble import IsolationForest
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    from sklearn.preprocessing import RobustScaler

    rows = [dict(f) for f in profiles]   # nivel_pct: percentil do nível dentro do mesmo tipo de sinal
    df = pd.DataFrame([{k: r.get(k) for k in FEATURES} for r in rows], dtype=float)
    keep = df.notna().sum(axis=1) >= len(FEATURES) - 2
    df = df[keep]
    idx = list(df.index)
    if len(df) < 6:
        return {"aviso": f"produtos com dados suficientes: {len(df)} (mínimo 6)", "itens": []}
    df = df.fillna(df.median())
    X = RobustScaler().fit_transform(df.values.clip(np.percentile(df.values, 1, axis=0),
                                                    np.percentile(df.values, 99, axis=0)))
    best = None
    for k in range(3, min(8, len(df) - 1) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
        sil = silhouette_score(X, km.labels_)
        if best is None or sil > best[0]:
            best = (sil, k, km.labels_)
    sil, k, lab = best
    agg = AgglomerativeClustering(n_clusters=k, linkage="ward").fit(X).labels_
    hdb = HDBSCAN(min_cluster_size=max(3, len(df) // 15), copy=True).fit(X).labels_
    pca = PCA(n_components=2, random_state=0).fit(X)
    xy = pca.transform(X)
    iso = IsolationForest(random_state=0, contamination=0.05).fit(X)
    anomaly = iso.predict(X) == -1
    items = []
    for j, i in enumerate(idx):
        f = rows[i]
        items.append({"product_key": f["product_key"], "nome": f["nome"], "categoria": f["categoria"],
                      "cluster": int(lab[j]), "hdbscan": int(hdb[j]), "x": float(xy[j, 0]), "y": float(xy[j, 1]),
                      "anomalia": bool(anomaly[j]), "rotulo": f.get("rotulo"), "tipo_sinal": f.get("tipo_sinal")})
    clusters = []
    for c in range(k):
        mem = [it for it in items if it["cluster"] == c]
        cent = df.loc[[idx[j] for j in range(len(idx)) if lab[j] == c]].median()
        counts = pd.Series([m["rotulo"] for m in mem]).value_counts()
        clusters.append({"id": c, "n": len(mem), "nome": counts.index[0] if len(counts) else f"Grupo {c + 1}",
                         "composicao_rotulos": counts.to_dict(),
                         "centroide_mediano": {k2: (None if pd.isna(v) else float(v)) for k2, v in cent.items()}})
    names = [c["nome"] for c in clusters]
    for c in clusters:
        if names.count(c["nome"]) > 1:
            kinds = pd.Series([it["tipo_sinal"] or "" for it in items if it["cluster"] == c["id"]]).value_counts()
            c["nome"] += " — " + (kinds.index[0].split(" (")[0] if len(kinds) else f"grupo {c['id'] + 1}")
    return {"k": k, "silhueta": float(sil), "ari_aglomerativo_vs_kmeans": float(adjusted_rand_score(lab, agg)),
            "hdbscan_grupos": int(len(set(hdb)) - (1 if -1 in hdb else 0)), "hdbscan_ruido": int(np.sum(hdb == -1)),
            "pca_variancia_explicada": [float(v) for v in pca.explained_variance_ratio_],
            "pca_cargas": {FEATURES[i]: [float(pca.components_[0, i]), float(pca.components_[1, i])]
                           for i in range(len(FEATURES))},
            "variaveis": FEATURES, "clusters": clusters, "itens": items,
            "anomalias": int(np.sum(anomaly))}


# --------------------------------------------------------------------------- oportunidade

# Fase 3: diversidade de fontes saiu do score (vai para a confiança) para não penalizar um produto
# só porque uma fonte não tem dados dele; entraram menções, sentimento e problemas recorrentes.
WEIGHTS = {
    "crescimento_interesse": 0.17, "persistencia": 0.13, "evidencia_demanda": 0.20, "mencoes": 0.06,
    "sentimento": 0.08, "problemas_recorrentes": 0.06, "concorrencia": 0.08, "sazonalidade": 0.04,
    "volatilidade": 0.08, "risco_comercial": 0.05, "qualidade_dados": 0.05,
}
RELIABILITY_FACTOR = {"A": 1.0, "B": 0.8, "C": 0.6}
SOURCE_RELIABILITY = {"comexstat": "A", "comtrade": "A", "bcb_ptax": "A", "ibge_pmc": "A", "wikimedia": "B",
                      "rss": "B", "google_news": "B", "reddit": "B", "mercadolivre": "B", "gpi": "A"}


def _clip01(v):
    return None if v is None else float(min(1.0, max(0.0, v)))


def opportunity(profiles: list[dict], fx_cny_12m: float | None = None, reviews: dict | None = None) -> list[dict]:
    """Score heurístico 0–100 (NÃO é probabilidade de sucesso). Componentes sem dados são
    excluídos e os pesos restantes renormalizados — a falta de uma fonte não reduz o score.
    Cobertura = soma dos pesos com dados; confiança = confiabilidade das fontes × corroboração
    × tamanho do histórico. Dados do YouTube não entram (políticas do YouTube)."""
    rv = {p["product_key"]: p for p in (reviews or {}).get("produtos", []) if p.get("suficiente")}
    pm = pct_rank({f["product_key"]: f.get("mencoes_12m") for f in profiles})
    interest = {f["product_key"]: (f.get("interesse_pt_12m") if f.get("interesse_pt_12m") is not None
                                   else f.get("crescimento_12m") if f["product_key"].startswith("wiki:") else None)
                for f in profiles}
    imp_growth, imp_level = {}, {}
    for f in profiles:
        if f["product_key"].startswith("sh4:"):
            imp_growth[f["product_key"]], imp_level[f["product_key"]] = f.get("crescimento_12m"), f.get("nivel_12m")
        else:
            rel = f.get("importacao_relacionada") or []
            gs = [r["crescimento_12m"] for r in rel if r["crescimento_12m"] is not None]
            imp_growth[f["product_key"]] = float(np.mean(gs)) if gs else None
            imp_level[f["product_key"]] = float(np.sum([r["nivel_12m"] for r in rel])) if rel else None
    pi, pg, pl = pct_rank(interest), pct_rank(imp_growth), pct_rank(imp_level)
    pv = pct_rank({f["product_key"]: f.get("volatilidade") for f in profiles})
    out = []
    for f in profiles:
        k = f["product_key"]
        comp = {}
        comp["crescimento_interesse"] = pi.get(k)
        p, sig = f.get("persistencia"), f.get("tendencia_sig") and f.get("tendencia_dir") == "crescimento"
        comp["persistencia"] = None if p is None else _clip01(0.7 * p + 0.3 * (1.0 if sig else 0.0))
        ev = [v for v in (pg.get(k), pl.get(k)) if v is not None]
        comp["evidencia_demanda"] = float(np.mean(ev)) if ev else None
        comp["mencoes"] = pm.get(k)
        rvw = rv.get(k)
        comp["sentimento"] = None if not rvw else _clip01((rvw["saldo"] + 1) / 2)
        comp["problemas_recorrentes"] = None if not rvw or rvw["share_problemas_produto"] is None else \
            _clip01(1 - 2 * rvw["share_problemas_produto"])
        share = f.get("participacao_china")
        comp["concorrencia"] = None if (pl.get(k) is None) else _clip01(1 - pl[k] * (share if share is not None else 0.5))
        comp["sazonalidade"] = None if f.get("sazonalidade") is None else _clip01(1 - 0.5 * f["sazonalidade"])
        comp["volatilidade"] = None if pv.get(k) is None else 1 - pv[k]
        risk_parts = []
        if f.get("preco_kg_12m") is not None:
            risk_parts.append(_clip01(1 - max(0.0, f["preco_kg_12m"]) * 2))
        if fx_cny_12m is not None:
            risk_parts.append(_clip01(1 - max(0.0, fx_cny_12m) * 3))
        comp["risco_comercial"] = float(np.mean(risk_parts)) if risk_parts else None
        months = f.get("meses") or 0
        comp["qualidade_dados"] = _clip01(min(1.0, months / 60))
        wsum = sum(WEIGHTS[c] for c, v in comp.items() if v is not None)
        score = 100 * sum(WEIGHTS[c] * v for c, v in comp.items() if v is not None) / wsum if wsum else None
        srcs = [s_ for s_ in f["fontes"] if s_ != "gpi"]
        relf = float(np.mean([RELIABILITY_FACTOR[SOURCE_RELIABILITY.get(s_, "B")] for s_ in srcs])) if srcs else 0.6
        confidence = relf * (0.5 + 0.5 * min(1.0, len(srcs) / 3)) * (0.5 + 0.5 * min(1.0, months / 36))
        top_p = ""
        if rvw and rvw["problemas"]:
            top_p = ", ".join(x["aspecto"].lower() for x in rvw["problemas"][:2])
        evid, risks = [], []
        if f.get("crescimento_12m") is not None:
            evid.append(f"{f['tipo_sinal']}: {f['crescimento_12m']:+.0%} nos últimos 12 meses vs. ano anterior")
        if f.get("interesse_pt_12m") is not None:
            evid.append(f"interesse na Wikipédia em português: {f['interesse_pt_12m']:+.0%} em 12 meses")
        for r in (f.get("importacao_relacionada") or [])[:3]:
            if r["crescimento_12m"] is not None:
                evid.append(f"importações da China, SH4 {r['codigo']}: {r['crescimento_12m']:+.0%} em 12 meses")
        if f.get("tendencia_sig"):
            evid.append(f"tendência de {f['tendencia_dir']} estatisticamente significativa (p < 0,05)")
        if (f.get("volatilidade") or 0) > 0.35:
            risks.append("alta volatilidade mensal")
        if (f.get("sazonalidade") or 0) >= 0.6:
            risks.append("demanda concentrada em parte do ano")
        if share is not None and share > 0.8:
            risks.append(f"China já responde por {share:.0%} das importações (mercado disputado)")
        if f.get("preco_kg_12m") is not None and f["preco_kg_12m"] > 0.1:
            risks.append(f"preço médio de importação subiu {f['preco_kg_12m']:.0%} em 12 meses")
        if len(f["fontes"]) < 2:
            risks.append("evidência de uma única fonte")
        if months < 36:
            risks.append(f"histórico curto ({months} meses)")
        if rvw:
            evid.append(f"{rvw['n']} opiniões analisadas: {rvw['positivos']} positivas, {rvw['negativos']} negativas")
            if rvw["problemas"]:
                risks.append(f"reclamações recorrentes sobre {top_p} (contagem de opiniões, não taxa de defeito)")
        if f.get("surto"):
            evid.append("aumento recente atípico (últimos 3 meses > média + 2 desvios dos 24 anteriores)")
        out.append({**{x: f.get(x) for x in ("product_key", "nome", "nome_en", "nome_zh", "categoria", "fontes",
                                             "tipo_sinal", "crescimento_12m", "aceleracao", "rotulo",
                                             "justificativa_rotulo", "serie_principal", "meses", "nivel_12m",
                                             "importacao_relacionada", "participacao_china")},
                    "score": None if score is None else round(score, 1), "componentes": comp,
                    "cobertura": round(wsum, 3), "confianca": round(confidence, 3),
                    "confianca_rotulo": "alta" if confidence >= 0.7 else ("média" if confidence >= 0.45 else "baixa"),
                    "surto": f.get("surto", False), "interesse_nivel_pct": f.get("nivel_pct") if k.startswith("wiki:") else None,
                    "evidencias": evid, "riscos": risks})
    out.sort(key=lambda r: -(r["score"] or -1))
    return out


def rankings(opps: list[dict], profiles: list[dict]) -> dict:
    byk = {f["product_key"]: f for f in profiles}

    def top(cond, key=lambda r: -(r["score"] or 0), n=20):
        return [r["product_key"] for r in sorted([r for r in opps if cond(r)], key=key)][:n]

    cat = defaultdict(list)
    for f in profiles:
        if f.get("aceleracao") is not None and f.get("crescimento_12m") is not None:
            cat[f["categoria"]].append((f["aceleracao"], f["crescimento_12m"]))
    cats = sorted([{"categoria": c, "aceleracao_media": float(np.median([a for a, _ in v])),
                    "crescimento_medio": float(np.median([g for _, g in v])), "produtos": len(v)}
                   for c, v in cat.items() if len(v) >= 2], key=lambda r: -r["aceleracao_media"])
    return {
        "emergentes": top(lambda r: r["rotulo"] in ("Tendência emergente", "Crescimento acelerado")),
        "crescimento_consistente": top(lambda r: r["rotulo"] == "Crescimento estável" or
                                       ((byk[r["product_key"]].get("persistencia") or 0) >= 0.75 and
                                        (r["crescimento_12m"] or 0) > 0)),
        "investigacao_importacao": top(lambda r: len(r["fontes"]) >= 2 and (r["componentes"].get("evidencia_demanda") or 0) >= 0.5),
        "possivel_declinio": top(lambda r: r["rotulo"] == "Possível declínio", key=lambda r: r["crescimento_12m"] or 0),
        "categorias_aceleracao": cats,
        # Fase 3
        "produtos_emergentes": top(lambda r: r["rotulo"] in ("Tendência emergente", "Crescimento acelerado") or r.get("surto")),
        "mais_pesquisados": top(lambda r: r.get("interesse_nivel_pct") is not None,
                                key=lambda r: -(r.get("interesse_nivel_pct") or 0)),
        "em_crescimento": top(lambda r: (r["crescimento_12m"] or 0) > 0.1 and
                              (byk[r["product_key"]].get("persistencia") or 0) >= 0.5),
        "avaliacoes_favoraveis": top(lambda r: r["componentes"].get("sentimento") is not None and
                                     r["componentes"]["sentimento"] >= 0.6,
                                     key=lambda r: -(r["componentes"].get("sentimento") or 0)),
        "problemas_recorrentes": top(lambda r: r["componentes"].get("problemas_recorrentes") is not None and
                                     r["componentes"]["problemas_recorrentes"] < 0.7,
                                     key=lambda r: r["componentes"].get("problemas_recorrentes") or 0),
        "promissores_importacao": top(lambda r: (r["componentes"].get("evidencia_demanda") or 0) >= 0.5 and
                                      r["confianca"] >= 0.45),
        "alto_risco": top(lambda r: (r["componentes"].get("risco_comercial") is not None and r["componentes"]["risco_comercial"] < 0.5)
                          or (r["componentes"].get("volatilidade") is not None and r["componentes"]["volatilidade"] < 0.2)
                          or r["rotulo"] == "Possível declínio", key=lambda r: (r["score"] or 0)),
        "sinais_brasil": top(lambda r: (byk[r["product_key"]].get("interesse_pt_12m") or -1) > 0 and
                             any((x["crescimento_12m"] or -1) > 0 for x in (r.get("importacao_relacionada") or []))
                             or (r["product_key"].startswith("sh4:") and (r["crescimento_12m"] or -1) > 0.1)),
    }
