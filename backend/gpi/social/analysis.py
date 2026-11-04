"""
Social Product Intelligence (v0.6): séries sociais por produto × plataforma × país × métrica,
Social Trend Score, Viral Product Radar e Search vs. Social Interest.

Regras metodológicas:
* Cada plataforma e cada métrica ficam em séries separadas, na própria unidade. Uma curtida do
  Instagram nunca é comparada com uma visualização do TikTok, e nada é somado entre plataformas.
* A normalização é FEITA DENTRO DE CADA PLATAFORMA E MÉTRICA: o crescimento de um produto vira o
  seu percentil entre os produtos daquela mesma plataforma/métrica. Só esses percentis (0–1) são
  combinados — com pesos documentados — no Social Trend Score.
* O Social Trend Score é uma classificação EXPLORATÓRIA de atenção social; não é probabilidade de
  compra nem demanda. Hashtags sem produto identificado ou de entretenimento não entram.
* YouTube entra nos índices combinados só se o usuário confirmar que o projeto Google aceitou o
  caso de uso "Analytics & Reporting" da política de métricas derivadas do YouTube.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from ..products.trends import COUNTRY_NAMES, METRICS, indicators
from .store import PLATFORM_NAMES, purge

SOCIAL_METRICS = {
    "tt_hashtag_posicao": {"rotulo": "Hashtags populares (TikTok)", "unidade": "pontos (201 − posição), por dia",
                           "mede": "Posição entre as hashtags populares do país — ranking, NÃO volume", "tipo": "ranking", "nivel": False},
    "tt_hashtag_views": {"rotulo": "Visualizações com a hashtag (TikTok)", "unidade": "visualizações na janela da API",
                         "mede": "Visualizações de vídeos com a hashtag — atenção, NÃO compras", "tipo": "visualizacoes", "nivel": True},
    "tt_hashtag_posts": {"rotulo": "Publicações com a hashtag (TikTok)", "unidade": "publicações na janela da API",
                         "mede": "Vídeos publicados com a hashtag — produção de conteúdo", "tipo": "publicacoes", "nivel": True},
    "tt_busca_posicao": {"rotulo": "Termos de busca em alta (TikTok)", "unidade": "pontos (21 − posição), por dia",
                         "mede": "Presença entre os 20 termos de busca em alta DENTRO do TikTok — ranking da plataforma", "tipo": "ranking", "nivel": False},
    "ig_top_curtidas": {"rotulo": "Curtidas nas publicações principais (Instagram)", "unidade": "curtidas por publicação (mediana)",
                        "mede": "Engajamento típico das publicações principais da hashtag — NÃO demanda", "tipo": "engajamento", "nivel": True},
    "ig_top_comentarios": {"rotulo": "Comentários nas publicações principais (Instagram)", "unidade": "comentários por publicação (mediana)",
                           "mede": "Engajamento típico das publicações principais da hashtag", "tipo": "engajamento", "nivel": True},
    "ig_recentes_24h": {"rotulo": "Publicações recentes com a hashtag (Instagram)", "unidade": "publicações em 24 h (máx. 50)",
                        "mede": "Ritmo de publicações recentes com a hashtag", "tipo": "publicacoes", "nivel": True},
    "fb_mencoes": {"rotulo": "Publicações de páginas que citam o produto (Facebook)", "unidade": "publicações/mês",
                   "mede": "Frequência do produto nas páginas comerciais acompanhadas", "tipo": "mencoes", "nivel": True},
    "fb_interacoes": {"rotulo": "Interações nessas publicações (Facebook)", "unidade": "reações+comentários+compartilhamentos/mês",
                      "mede": "Engajamento nas publicações que citam o produto", "tipo": "engajamento", "nivel": True},
    "meta_anuncios": {"rotulo": "Anúncios ativos (Biblioteca de Anúncios da Meta, UE)", "unidade": "anúncios ativos (máx. 500)",
                      "mede": "Atividade publicitária com o termo do produto — NÃO investimento nem alcance", "tipo": "anuncios", "nivel": True},
    "yt_videos": {"rotulo": "Vídeos publicados sobre o produto (YouTube)", "unidade": "vídeos/mês encontrados na busca",
                  "mede": "Produção de vídeos de review/unboxing sobre o produto", "tipo": "publicacoes", "nivel": True},
    "yt_views": {"rotulo": "Visualizações desses vídeos (YouTube)", "unidade": "visualizações acumuladas (instantâneo da coleta)",
                 "mede": "Visualizações dos vídeos publicados no mês — atenção, NÃO compras", "tipo": "visualizacoes", "nivel": True},
    "rd_mencoes": {"rotulo": "Discussões no Reddit", "unidade": "publicações/mês",
                   "mede": "Discussões de consumidores que citam o produto", "tipo": "mencoes", "nivel": True},
}
WEIGHTS = {"crescimento": 0.35, "persistencia": 0.20, "engajamento_relativo": 0.15, "diversidade": 0.15, "intencao_comercial": 0.15}
RADAR_CLASSES = ["Tendência emergente", "Crescimento sustentado", "Viralização recente", "Popularidade estável",
                 "Possível saturação", "Interesse em declínio"]
SOCIAL_PLATFORMS = ("tiktok", "instagram", "facebook", "meta_ads", "youtube", "reddit")


def _pct_rank(vals: dict) -> dict:
    """Percentil (0–1) de cada chave dentro do grupo; empates recebem a média."""
    if not vals:
        return {}
    keys = list(vals)
    arr = np.array([vals[k] for k in keys], dtype=float)
    if len(arr) == 1:
        return {keys[0]: 0.5}
    order = arr.argsort().argsort().astype(float)
    for v in set(arr.tolist()):                          # empates
        idx = np.where(arr == v)[0]
        order[idx] = order[idx].mean()
    return {k: float(order[i] / (len(arr) - 1)) for i, k in enumerate(keys)}


def load_points(db, cfg: dict, today: date) -> dict:
    """{(product_id, platform, country, metric): {"points": [(data, valor)], "period", "items", "url", "comercial"}}"""
    out = defaultdict(lambda: {"points": defaultdict(float), "items": set(), "url": None, "com": [0, 0], "period": "dia"})
    for r in db.query("SELECT platform, country, item, ref_date, period, metric, value, product_id, commercial, url "
                      "FROM social_observations WHERE product_id IS NOT NULL AND (retain_until IS NULL OR retain_until >= ?)",
                      (today.isoformat(),)):
        fam = r["product_id"].split(":")[0]
        k = (fam, r["platform"], r["country"], r["metric"])
        o = out[k]
        if SOCIAL_METRICS.get(r["metric"], {}).get("tipo") in ("ranking",) or r["metric"].startswith(("ig_", "meta_")):
            o["points"][r["ref_date"]] = max(o["points"][r["ref_date"]], r["value"])   # instantâneos: não somar itens repetidos
        else:
            o["points"][r["ref_date"]] += r["value"]
        o["items"].add(r["item"])
        o["url"] = o["url"] or r["url"]
        o["com"][0] += int(r["commercial"])
        o["com"][1] += 1
        o["period"] = "mes" if r["period"] == "mes" else "dia"
    # YouTube (vídeos já coletados pelo conector da Fase 3) — por mês de publicação
    if cfg.get("youtube_em_indices", False):
        from .store import identify
        cache = {}
        for r in db.query("SELECT query, published_at, metrics, url FROM content_items WHERE source = 'youtube' AND kind = 'video' "
                          "AND published_at IS NOT NULL"):
            q = r["query"] or ""
            if q not in cache:
                cache[q] = identify(db, cfg, q, "youtube", None, record=False)[0] if q else None
            pid = cache[q]
            if not pid:
                continue
            fam = pid.split(":")[0]
            m = json.loads(r["metrics"] or "{}")
            month = str(r["published_at"])[:7] + "-01"
            for metric, v in (("yt_videos", 1), ("yt_views", m.get("viewCount"))):
                if v is None:
                    continue
                o = out[(fam, "youtube", "GLOBAL", metric)]
                o["points"][month] += float(v)
                o["items"].add(q)
                o["url"] = o["url"] or r["url"]
                o["com"][0] += 1
                o["com"][1] += 1
                o["period"] = "mes"
    # Reddit: menções já registradas pela inteligência de consumo
    for r in db.query("SELECT product_id, ref_date, COUNT(*) AS n FROM search_observations WHERE source = 'reddit' "
                      "AND metric = 'mencoes' AND product_id IS NOT NULL GROUP BY product_id, ref_date"):
        o = out[(r["product_id"].split(":")[0], "reddit", "GLOBAL", "rd_mencoes")]
        o["points"][r["ref_date"]] += r["n"]
        o["com"][0] += r["n"]
        o["com"][1] += r["n"]
        o["period"] = "dia"
    return out


def _daily_to_monthly_ok(points: dict) -> bool:
    months = {d[:7] for d in points}
    return len(months) >= 6


def build_series(db, cfg: dict, today: date) -> list[dict]:
    from ..products.catalog import Catalog
    names = {p["product_id"]: p for p in Catalog(db, cfg).products()}
    out = []
    for (pid, plat, cc, metric), o in load_points(db, cfg, today).items():
        pts = sorted(o["points"].items())
        if not pts:
            continue
        period = o["period"]
        if period == "dia" and _daily_to_monthly_ok(o["points"]):
            agg = defaultdict(list)                       # histórico longo diário → média mensal (instantâneos) para tendência
            for d, v in pts:
                agg[d[:7]].append(v)
            pts = [(m + "-01", float(np.mean(v))) for m, v in sorted(agg.items())]
            period = "mes"
        s = {"id": f"{pid}|{plat}|{cc}|{metric}", "product_id": pid, "platform": plat, "country": cc, "metric": metric,
             "period": period, "points": pts}
        ind = indicators({**s, "metric": "mencoes" if metric not in METRICS else metric}, today)
        p = names.get(pid, {})
        out.append({**{k: v for k, v in s.items() if k != "points"}, "ind": ind, "nome": p.get("canonical") or pid,
                    "categoria": p.get("category"), "metrica": SOCIAL_METRICS.get(metric, {"rotulo": metric, "unidade": "", "tipo": "outro"}),
                    "plataforma_nome": PLATFORM_NAMES.get(plat, plat),
                    "pais_nome": COUNTRY_NAMES.get(cc, {"CONTA": "Região da conta (não informada pela API)", "UE": "União Europeia",
                                                        "GLOBAL": "Global"}.get(cc, cc)),
                    "item": ", ".join(sorted(o["items"]))[:200], "url": o["url"],
                    "comercial": (o["com"][0] / o["com"][1]) if o["com"][1] else 0.0})
    return out


def _growth(ind: dict):
    if ind.get("crescimento") is not None:
        return ind["crescimento"]
    return ind.get("crescimento_7d")


def _persistence(ind: dict):
    if ind.get("persistencia") is not None:
        return ind["persistencia"]
    if "dias_em_alta_30d" in ind:
        return min(1.0, ind["dias_em_alta_30d"] / 30)
    return None


def radar_class(best: list[dict]) -> tuple[str, dict]:
    """Classe do Viral Product Radar a partir das séries do produto (uma por plataforma)."""
    gs = [g for g in (_growth(s["ind"]) for s in best) if g is not None]
    ps = [p for p in (_persistence(s["ind"]) for s in best) if p is not None]
    g = float(np.median(gs)) if gs else None
    p = float(np.mean(ps)) if ps else None
    short = [s["ind"].get("crescimento_7d") for s in best if s["ind"].get("crescimento_7d") is not None]
    spike = any(x > 1.0 for x in short) or any(s["ind"].get("anomalias") and s["ind"].get("labels") and
                                                s["ind"]["anomalias"][-1] == s["ind"]["labels"][-1] for s in best)
    emerg = any(s["ind"].get("emergente") for s in best)
    sat = any(s["ind"].get("saturacao_possivel") for s in best)
    level_shift = any(s["ind"].get("pontos_mudanca") and s["ind"].get("labels") and
                      s["ind"]["pontos_mudanca"][-1] in s["ind"]["labels"][-3:] for s in best)
    info = {"crescimento_mediano": g, "persistencia_media": p, "pico_recente": spike, "mudanca_de_patamar": level_shift}
    if emerg and (g is None or g >= 0):
        return "Tendência emergente", info
    if sat:
        return "Possível saturação", info
    if spike and (p is None or p < 0.5):
        info["pico_passageiro_possivel"] = True
        return "Viralização recente", info
    if g is not None and g < -0.15:
        return "Interesse em declínio", info
    if g is not None and g > 0.15 and (p is None or p >= 0.5):
        return "Crescimento sustentado", info
    if spike:
        return "Viralização recente", info
    return "Popularidade estável", info


def scores(series: list[dict], connected: set, today: date) -> dict:
    by_pm = defaultdict(dict)                          # (plataforma, métrica) → {produto: crescimento}
    lvl_pm = defaultdict(dict)
    for s in series:
        g = _growth(s["ind"])
        if g is not None:
            by_pm[(s["platform"], s["metric"])][s["id"]] = g
        if s["metrica"].get("nivel"):
            lv = s["ind"].get("media_3m", s["ind"].get("soma_30d", s["ind"].get("ultimo_valor")))
            if lv is not None:
                lvl_pm[(s["platform"], s["metric"])][s["id"]] = lv
    pct_g = {sid: v for grp in by_pm.values() for sid, v in _pct_rank(grp).items()}
    pct_l = {sid: v for grp in lvl_pm.values() for sid, v in _pct_rank(grp).items()}
    by_prod = defaultdict(list)
    for s in series:
        by_prod[s["product_id"]].append(s)
    out = {}
    for pid, lst in by_prod.items():
        plats = sorted({s["platform"] for s in lst})
        comp = {}
        gp = [pct_g[s["id"]] for s in lst if s["id"] in pct_g]
        if gp:
            comp["crescimento"] = float(np.mean([max(pct_g[s["id"]] for s in lst if s["platform"] == pl and s["id"] in pct_g)
                                                 for pl in plats if any(s["platform"] == pl and s["id"] in pct_g for s in lst)]))
        ps = [p for p in (_persistence(s["ind"]) for s in lst) if p is not None]
        if ps:
            comp["persistencia"] = float(np.mean(ps))
        lp = [pct_l[s["id"]] for s in lst if s["id"] in pct_l]
        if lp:
            comp["engajamento_relativo"] = float(np.mean(lp))
        if connected:
            comp["diversidade"] = min(1.0, len(plats) / max(1, min(3, len(connected))))
        comp["intencao_comercial"] = float(np.mean([s["comercial"] for s in lst]))
        cov = sum(WEIGHTS[k] for k in comp)
        score = 100 * sum(WEIGHTS[k] * v for k, v in comp.items()) / cov if cov else None
        best = []
        for pl in plats:
            cand = [s for s in lst if s["platform"] == pl]
            cand.sort(key=lambda s: -(s["ind"].get("n") or 0))
            best.append(cand[0])
        cls, info = radar_class(best)
        gs = [g for g in (_growth(s["ind"]) for s in lst) if g is not None]
        lim = ["Índice exploratório de atenção social; não representa probabilidade de compra."]
        if len(plats) == 1:
            lim.append(f"Crescimento observado somente em uma plataforma ({PLATFORM_NAMES.get(plats[0], plats[0])}).")
        if max((s["ind"].get("n") or 0) for s in lst) < 6:
            lim.append("Histórico social curto (< 6 períodos): classificação instável.")
        out[pid] = {"product_id": pid, "nome": lst[0]["nome"], "categoria": lst[0]["categoria"],
                    "social_trend_score": None if score is None else round(score, 1),
                    "componentes": {k: round(v, 3) for k, v in comp.items()}, "pesos": WEIGHTS, "cobertura": round(cov, 2),
                    "plataformas": [PLATFORM_NAMES.get(p, p) for p in plats], "somente_uma_plataforma": len(plats) == 1,
                    "paises": sorted({s["country"] for s in lst}), "crescimento_social": float(np.median(gs)) if gs else None,
                    "classe_radar": cls, "radar": info, "hashtags": sorted({h for s in lst for h in s["item"].split(", ") if h})[:10],
                    "fontes": sorted({s["plataforma_nome"] for s in lst}), "data": today.isoformat(), "limitacoes": lim}
    return out


def _sign(g, band=0.05):
    if g is None:
        return None
    return 1 if g > band else -1 if g < -band else 0


def search_vs_social(consumer: dict, soc_series: list[dict], soc_scores: dict, db) -> list[dict]:
    """Indicadores separados por tipo de fonte e consistência do SINAL entre fontes (sem misturar unidades)."""
    from scipy.stats import spearmanr
    cons = consumer.get("series", [])
    by = defaultdict(lambda: {"busca": [], "social": [], "market": []})
    for s in cons:
        tipo = METRICS.get(s["metric"], {}).get("tipo")
        if tipo in ("busca", "busca_ranking"):
            (by[s["product_id"]]["market"] if s["source"] == "ml_trends" else by[s["product_id"]]["busca"]).append(s)
    for s in soc_series:
        by[s["product_id"]]["social"].append(s)
    listings = {r["product_id"]: r["n"] for r in db.query(
        "SELECT product_id, COUNT(DISTINCT item_id) AS n FROM market_listings WHERE product_id IS NOT NULL GROUP BY product_id")}
    out = []
    for pid, g in by.items():
        if not g["social"] and not g["market"] and not listings.get(pid):
            continue
        sg = [x for x in (_growth(s["ind"]) for s in g["busca"]) if x is not None]
        so = [x for x in (_growth(s["ind"]) for s in g["social"]) if x is not None]
        mk = [x for x in (_growth(s["ind"]) for s in g["market"]) if x is not None]
        search_growth = max(sg) if sg else None
        social_growth = float(np.median(so)) if so else None
        days_ml = max([s["ind"].get("dias_em_alta_30d", 0) for s in g["market"]] or [0])
        market_sig = None
        if g["market"] or listings.get(pid):
            market_sig = round(min(100.0, 100 * days_ml / 30 * 0.7 + 30 * min(1.0, math.log1p(listings.get(pid, 0)) / math.log(200))), 1)
        types = sum(1 for k in ("busca", "social") if g[k]) + (1 if market_sig is not None else 0)
        signs = [x for x in (_sign(search_growth), _sign(social_growth), _sign(max(mk) if mk else None)) if x is not None]
        cons_v = None
        if len(signs) >= 2:
            pairs = [(a, b) for i, a in enumerate(signs) for b in signs[i + 1:]]
            cons_v = round(float(np.mean([a * b for a, b in pairs])), 2)
        corr = None
        a = next((s for s in g["busca"] if s["period"] == "mes" and len(s["ind"].get("valores") or []) >= 8), None)
        b = next((s for s in g["social"] if s["period"] == "mes" and len(s["ind"].get("valores") or []) >= 8), None)
        if a and b:
            da, dbb = dict(zip(a["ind"]["labels"], a["ind"]["valores"])), dict(zip(b["ind"]["labels"], b["ind"]["valores"]))
            common = sorted(set(da) & set(dbb))
            if len(common) >= 8 and len({da[k] for k in common}) > 1 and len({dbb[k] for k in common}) > 1:
                rho, p = spearmanr([da[k] for k in common], [dbb[k] for k in common])
                corr = {"spearman": round(float(rho), 3), "p_valor": round(float(p), 4), "meses": len(common)}
        if types < 2:
            leitura = "apenas um tipo de fonte — sem verificação cruzada"
        elif cons_v is None:
            leitura = "crescimento indisponível em uma das fontes"
        elif cons_v >= 0.5:
            leitura = "fontes apontam na mesma direção"
        elif cons_v <= -0.5:
            leitura = "fontes divergem"
        else:
            leitura = "sinais mistos ou estáveis"
        nome = (g["busca"] or g["social"] or g["market"] or [{"nome": pid}])[0].get("nome", pid)
        cat = (g["busca"] or g["social"] or g["market"] or [{}])[0].get("categoria")
        out.append({"product_id": pid, "nome": nome, "categoria": cat, "search_growth": search_growth, "social_growth": social_growth,
                    "marketplace_signals": market_sig, "evidence_coverage": round(100 * types / 3, 1),
                    "cross_source_consistency": cons_v, "correlacao_mensal": corr, "leitura": leitura,
                    "fontes": sorted({s.get("fonte_nome") or s.get("plataforma_nome") for k in ("busca", "social", "market") for s in g[k]}
                                     | ({"Anúncios de marketplaces"} if listings.get(pid) else set()))})
    out.sort(key=lambda r: -(r["evidence_coverage"] or 0))
    return out


def analyze(db, cfg: dict | None = None, today: date | None = None, consumer: dict | None = None, creds=None) -> dict:
    cfg = cfg or {}
    today = today or date.today()
    pr = purge(db, today)
    series = build_series(db, cfg, today)
    connected = {s["platform"] for s in series}
    sc = scores(series, connected, today)
    status = {}
    for p in SOCIAL_PLATFORMS:
        r = db.query("SELECT COUNT(*) AS n, MAX(collected_at) AS m FROM social_observations WHERE platform = ?", (p,))[0]
        n = r["n"]
        if p == "youtube":
            n = db.query("SELECT COUNT(*) AS n FROM content_items WHERE source = 'youtube'")[0]["n"]
        elif p == "reddit":
            n = db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'reddit'")[0]["n"]
        status[p] = {"nome": PLATFORM_NAMES[p], "observacoes": n, "ultima_coleta": (r["m"] or "")[:10] or None,
                     "situacao": "com dados" if n else "sem dados (não conectada ou sem coleta)",
                     "retencao": f"{cfg.get('retencao_dias_' + p) or {'youtube': 1095, 'reddit': 365}.get(p, 90)} dias"}
    if not cfg.get("youtube_em_indices", False):
        status["youtube"]["situacao"] += " · fora dos índices combinados (confirmação da política do YouTube pendente)"
    hashtags = []
    for r in db.query("SELECT platform, country, item, MAX(ref_date) AS d, MAX(value) AS v, product_id, MAX(commercial) AS c "
                      "FROM social_observations WHERE metric IN ('tt_hashtag_posicao', 'tt_busca_posicao') AND ref_date >= ? "
                      "GROUP BY platform, country, item ORDER BY v DESC LIMIT 300", ((today - timedelta(days=14)).isoformat(),)):
        top = 201 if r["platform"] == "tiktok" else 21
        hashtags.append({"item": r["item"], "platform": r["platform"], "plataforma_nome": PLATFORM_NAMES.get(r["platform"]),
                         "country": r["country"], "pais_nome": COUNTRY_NAMES.get(r["country"], r["country"]),
                         "posicao": int(top - r["v"]), "product_id": r["product_id"],
                         "produto": (sc.get((r["product_id"] or "").split(":")[0]) or {}).get("nome") if r["product_id"] else None,
                         "comercial": bool(r["c"]), "data": r["d"]})
    svs = search_vs_social(consumer or {}, series, sc, db)
    radar = defaultdict(list)
    for pid, v in sc.items():
        radar[v["classe_radar"]].append({"product_id": pid, "nome": v["nome"], "score": v["social_trend_score"],
                                         "plataformas": v["plataformas"], "somente_uma_plataforma": v["somente_uma_plataforma"],
                                         **v["radar"]})
    for k in radar:
        radar[k].sort(key=lambda x: -(x["score"] or 0))
    return {"gerado_em": today.isoformat(), "plataformas": status, "series": series, "scores": sc,
            "radar": {k: radar.get(k, []) for k in RADAR_CLASSES}, "search_vs_social": svs, "hashtags": hashtags,
            "metricas": SOCIAL_METRICS, "pesos": WEIGHTS, "retencao": pr,
            "avisos": ["Métricas sociais medem atenção nas plataformas; não são compras, vendas nem volume de pesquisas.",
                       "Cada plataforma é normalizada separadamente; nenhuma métrica é somada entre plataformas."]}
