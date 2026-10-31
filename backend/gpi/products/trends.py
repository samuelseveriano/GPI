"""
Inteligência de consumo: séries de interesse por produto × país × fonte × métrica, indicadores,
classificação de tendência, pontos de mudança, anomalias, rankings, comparação internacional
(lead-lag exploratório), previsões e scores (oportunidade, cobertura, confiança, prontidão).

Regras fixas:
* Métricas de natureza diferente NUNCA são somadas ou comparadas diretamente. Cada série tem
  fonte, país, período, métrica e unidade; cada ranking declara o que mede.
* "Mais pesquisados" usa SOMENTE volume de buscas (Google Ads). Sem essa fonte, o ranking fica vazio
  com a limitação explicada — não é preenchido com visualizações, menções ou importações.
* Wikipédia em chinês não é apresentada como busca na China; idiomas não são países.
* Correlação entre países é sinal antecedente exploratório, não causalidade nem promessa.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..analytics.classification import seasonality_strength, trend_test
from ..market.taxonomy import concept_key
from . import nlp
from .catalog import Catalog, label

METRICS = {
    "volume_mensal_aprox": {"rotulo": "Volume de buscas (aproximado)", "unidade": "buscas/mês (arredondado pelo Google)",
                            "mede": "Pesquisas no Google por mês (Planejador do Google Ads)", "tipo": "busca", "peso_conf": 1.0},
    "trafego_faixa": {"rotulo": "Buscas em alta (Trending Now)", "unidade": "buscas/dia — limite inferior da faixa",
                      "mede": "Tráfego mínimo das buscas que entraram na lista de alta do Google", "tipo": "busca", "peso_conf": 0.8},
    "visualizacoes": {"rotulo": "Leitura de artigos (Wikipédia)", "unidade": "visualizações/mês",
                      "mede": "Visualizações de artigos da Wikipédia no idioma — atenção, NÃO são pesquisas", "tipo": "atencao", "peso_conf": 0.6},
    "mencoes": {"rotulo": "Menções em notícias e discussões", "unidade": "itens/mês",
                "mede": "Manchetes e discussões que citam o produto — popularidade, NÃO são pesquisas", "tipo": "popularidade", "peso_conf": 0.4},
}
COUNTRY_NAMES = {"BR": "Brasil", "US": "Estados Unidos", "CN": "China", "GLOBAL:pt": "Leitores em português (global)",
                 "GLOBAL:en": "Leitores em inglês (global)", "GLOBAL:zh": "Leitores em chinês (global — não é a China continental)"}
PAGE_OF = {"BR": "BR", "US": "US", "CN": "CN", "GLOBAL:pt": "BR", "GLOBAL:en": "US", "GLOBAL:zh": "CN"}
SOURCE_NAMES = {"google_ads_kp": "Google Ads (Planejador)", "google_trends_rss": "Google Trends — Trending Now",
                "wikimedia": "Wikimedia", "rss": "Feeds RSS", "google_news": "Google Notícias", "reddit": "Reddit"}
WIKI_LANG = {"Wikipédia em português": "GLOBAL:pt", "Wikipédia em inglês": "GLOBAL:en", "Wikipédia em chinês": "GLOBAL:zh"}


# ============================================================================ coleta de menções
def ingest_content(db, catalog: Catalog, today: date) -> int:
    """Associa manchetes/discussões (RSS, Google Notícias, Reddit) a produtos do catálogo e registra
    menções. Também alimenta a descoberta. YouTube não passa por NLP (políticas do YouTube)."""
    rows = db.query("SELECT source, item_id, title, url, published_at, lang FROM content_items "
                    "WHERE source IN ('rss', 'google_news', 'reddit') AND kind <> 'comentario' AND published_at IS NOT NULL")
    done = {(r["source"], r["term"]) for r in db.query(
        "SELECT source, term FROM search_observations WHERE metric = 'mencoes'")}
    from .intent import classify
    n = 0
    with db.transaction():
        n = _ingest_rows(db, catalog, rows, done, classify, today)
    return n


def _ingest_rows(db, catalog, rows, done, classify, today) -> int:
    n = 0
    for r in rows:
        title = (r["title"] or "").strip()
        if not title or (r["source"], title[:200]) in done:
            continue
        intent = classify(title)
        pid = catalog.observe(title, r["source"], None, intent["intencao"])
        if not pid:
            continue
        lang = intent["idioma"] if intent["idioma"] in ("pt", "en", "zh") else (r["lang"] or "en")[:2]
        db.execute("INSERT OR IGNORE INTO search_observations (source, country, region, term, ref_date, period, metric,"
                   " value, value_high, unit, lang, product_id, intent, commercial, url, extra, collected_at)"
                   " VALUES (?, ?, '', ?, ?, 'dia', 'mencoes', 1, NULL, 'itens', ?, ?, ?, ?, ?, NULL, ?)",
                   (r["source"], f"GLOBAL:{lang}", title[:200], str(r["published_at"])[:10], lang, pid,
                    intent["intencao"], int(intent["comercial"]), r["url"], today.isoformat()))
        n += 1
    return n


# ============================================================================ séries
def family(pid: str | None) -> str | None:
    return pid.split(":")[0] if pid else None


def build_series(db, catalog: Catalog) -> list[dict]:
    series: dict[tuple, dict] = {}

    def add(pid, country, source, metric, period, d, v, msid=None):
        k = (pid, country, source, metric, period)
        s = series.setdefault(k, {"product_id": pid, "country": country, "page": PAGE_OF.get(country, country),
                                  "source": source, "metric": metric, "period": period, "pts": defaultdict(float)})
        s["pts"][d] += v
        if msid:
            s["market_series_id"] = msid

    for r in db.query("SELECT product_id, country, source, metric, ref_date, value, commercial FROM search_observations "
                      "WHERE product_id IS NOT NULL"):
        fam = family(r["product_id"])
        if r["metric"] == "volume_mensal_aprox":
            add(fam, r["country"], r["source"], r["metric"], "mes", r["ref_date"][:7] + "-01", r["value"])
        elif r["metric"] == "trafego_faixa" and r["commercial"]:
            add(fam, r["country"], r["source"], r["metric"], "dia", r["ref_date"], r["value"])
        elif r["metric"] == "mencoes":
            add(fam, r["country"], r["source"], r["metric"], "mes", r["ref_date"][:7] + "-01", r["value"])
    # Wikipédia: séries mensais já coletadas (Fase 2), ligadas ao catálogo pelo título do artigo
    wmap = {concept_key(p["wiki_en"]): p["product_id"] for p in catalog.products("produto") if p.get("wiki_en")}
    for s in db.query("SELECT id, product_key, country FROM market_series WHERE source = 'wikimedia'"):
        pid = wmap.get(s["product_key"])
        cc = WIKI_LANG.get(s["country"])
        if not pid or not cc:
            continue
        for o in db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ?", (s["id"],)):
            add(pid, cc, "wikimedia", "visualizacoes", "mes", o["ref_date"], o["value"], s["id"])
    out = []
    for s in series.values():
        pts = sorted(s.pop("pts").items())
        s["points"] = pts
        s["id"] = f"{s['product_id']}|{s['country']}|{s['source']}|{s['metric']}"
        out.append(s)
    return out


# ============================================================================ indicadores
def _monthly(points: list[tuple[str, float]], today: date) -> pd.Series:
    if not points:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Period(d[:7], "M"): v for d, v in points}).sort_index()
    cur = pd.Period(today, "M")
    s = s[s.index < cur]                                          # mês corrente incompleto fica de fora
    if s.empty:
        return s
    return s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"), fill_value=0.0)


def change_points(y: np.ndarray, min_size: int = 3, max_cp: int = 3) -> list[int]:
    """Segmentação binária da média com penalidade β = 2·ln(n)·σ̂² (σ̂ robusto, pelas diferenças).
    Devolve índices onde um novo regime começa."""
    y = np.asarray(y, float)
    n = len(y)
    if n < 2 * min_size + 1:
        return []
    d = np.diff(y)
    sigma = 1.4826 * np.median(np.abs(d - np.median(d))) / math.sqrt(2) if len(d) else 0
    sigma2 = max(sigma ** 2, 1e-9 * (np.var(y) + 1e-12))
    beta = 2 * math.log(n) * sigma2
    out = []

    def cost(a, b):
        seg = y[a:b]
        return float(((seg - seg.mean()) ** 2).sum())

    def split(a, b):
        if len(out) >= max_cp or b - a < 2 * min_size:
            return
        base, best, arg = cost(a, b), 0.0, None
        for k in range(a + min_size, b - min_size + 1):
            gain = base - cost(a, k) - cost(k, b)
            if gain > best:
                best, arg = gain, k
        if arg is not None and best > beta:
            out.append(arg)
            split(a, arg)
            split(arg, b)
    split(0, n)
    return sorted(out)


def anomalies(y: np.ndarray, window: int = 5, z: float = 3.5) -> list[int]:
    """Pontos com |z robusto| > 3,5 em relação à mediana móvel (MAD × 1,4826)."""
    y = np.asarray(y, float)
    if len(y) < window + 3:
        return []
    med = pd.Series(y).rolling(window, center=True, min_periods=2).median().values
    r = y - med
    mad = 1.4826 * np.nanmedian(np.abs(r - np.nanmedian(r)))
    if not mad or not np.isfinite(mad):
        return []
    return [int(i) for i in np.flatnonzero(np.abs(r / mad) > z)]


def indicators(s: dict, today: date) -> dict:
    ind = {"n": len(s["points"]), "primeiro": s["points"][0][0] if s["points"] else None,
           "ultimo": s["points"][-1][0] if s["points"] else None}
    if s["period"] == "dia":
        days = {date.fromisoformat(d): v for d, v in s["points"]}
        def win(a, b):
            return sum(v for d, v in days.items() if today - timedelta(days=b) < d <= today - timedelta(days=a))
        for w in (7, 30, 90):
            ind[f"soma_{w}d"] = win(0, w)
            ind[f"dias_em_alta_{w}d"] = sum(1 for d in days if today - timedelta(days=w) < d <= today)
            prev = win(w, 2 * w)
            ind[f"crescimento_{w}d"] = (ind[f"soma_{w}d"] / prev - 1) if prev > 0 else None
        first = min(days) if days else None
        ind["dias_historico"] = (today - first).days + 1 if first else 0
        ind["emergente"] = bool(first and (today - first).days <= 30)
        ind["crescimento"] = ind.get("crescimento_30d")
        ind["classe"] = "emergente" if ind["emergente"] else ("crescimento" if (ind["crescimento"] or 0) > 0.15
                                                               else "declínio" if (ind["crescimento"] or 0) < -0.15 else "estável")
        ind["valores_semanais"] = _weekly(days, today)
        return ind
    m = _monthly(s["points"], today)
    y = m.values.astype(float)
    ind.update(n=len(y), labels=[str(p) for p in m.index], valores=y.tolist())
    if len(y) == 0:
        ind["classe"] = "sem dados"
        return ind
    ind["ultimo_valor"] = float(y[-1])
    ind["media_3m"] = float(y[-3:].mean())
    if len(y) >= 6 and y[-6:-3].mean() > 0:
        ind["crescimento_3m"] = float(y[-3:].mean() / y[-6:-3].mean() - 1)
    if len(y) >= 15 and y[-15:-12].mean() > 0:
        ind["crescimento_12m"] = float(y[-3:].mean() / y[-15:-12].mean() - 1)
    if len(y) >= 9 and y[-9:-6].mean() > 0 and "crescimento_3m" in ind:
        ind["aceleracao"] = ind["crescimento_3m"] - float(y[-6:-3].mean() / y[-9:-6].mean() - 1)
    tail = y[-24:]
    tt = trend_test(tail) if len(tail) >= 6 else {}
    ind["tendencia"] = {k: tt.get(k) for k in ("direcao", "significativa", "p_valor", "inclinacao_relativa")} if tt else None
    seas = seasonality_strength(y[-60:], 12) if len(y) >= 24 else None
    ind["sazonalidade"] = seas
    if seas:
        prof = pd.Series(y[-60:]).groupby(np.arange(len(y[-60:])) % 12).mean()
        idx = [m.index[-60:][i].month for i in range(min(12, len(y[-60:])))]
        ind["perfil_mensal"] = {int(idx[i]): float(prof.iloc[i]) for i in range(len(idx))}
    nz = y[y > 0]
    ind["volatilidade"] = float(np.std(np.diff(nz)) / np.mean(nz)) if len(nz) >= 4 and np.mean(nz) > 0 else None
    ind["pontos_mudanca"] = [str(m.index[i]) for i in change_points(np.log1p(y))]
    ind["anomalias"] = [str(m.index[i]) for i in anomalies(np.log1p(y))]
    first_nonzero = next((i for i, v in enumerate(y) if v > 0), None)
    ind["emergente"] = bool(first_nonzero is not None and len(y) - first_nonzero <= 3 and s["metric"] != "visualizacoes")
    # crescimento: ano contra ano quando há ≥ 15 meses (não confunde sazonalidade com tendência);
    # senão, últimos 3 meses contra os 3 anteriores
    g = ind.get("crescimento_12m", ind.get("crescimento_3m"))
    ind["base_crescimento"] = "12 meses (mesmo trimestre do ano anterior)" if "crescimento_12m" in ind else "3 meses"
    sig_up = bool(tt.get("significativa") and tt.get("direcao") == "crescimento")
    sig_dn = bool(tt.get("significativa") and tt.get("direcao") == "queda")
    if len(y) >= 24:
        yoy = [y[t] / y[t - 12] - 1 for t in range(len(y) - 12, len(y)) if y[t - 12] > 0]
        if len(yoy) >= 9:
            pos = sum(v > 0 for v in yoy) / len(yoy)
            ind["variacao_anual_mediana"] = float(np.median(yoy))
            if seas and seas.get("significativa"):        # em série sazonal, a tendência é julgada ano contra ano
                sig_up = pos >= 0.75 and np.median(yoy) > 0.05
                sig_dn = pos <= 0.25 and np.median(yoy) < -0.05
    if ind["emergente"]:
        cls = "emergente"
    elif sig_up and (g or 0) > 0:
        cls = "crescimento consistente"
    elif (g or 0) > 0.15:
        cls = "crescimento"
    elif sig_dn or (g or 0) < -0.15:
        cls = "declínio"
    elif seas and seas.get("significativa"):
        cls = "sazonal"
    else:
        cls = "estável"
    ind["classe"] = cls
    ind["crescimento"] = g
    return ind


def _weekly(days: dict, today: date) -> dict:
    start = today - timedelta(days=7 * 26)
    wk = defaultdict(float)
    for d, v in days.items():
        if d > start:
            wk[(d - timedelta(days=d.weekday())).isoformat()] += v
    return dict(sorted(wk.items()))


# ============================================================================ lead-lag
def lead_lag(a: list[float], b: list[float], max_lag: int = 6) -> dict | None:
    """Correlação cruzada das variações (Δ, padronizadas) de A e B. lag > 0: A antecede B.
    Inclui significância aproximada (±1,96/√n), estabilidade entre as duas metades e um backtest
    simples: prever Δb(t) com Δa(t−lag) reduz o erro em relação a 'sem variação'?"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    if n < 18:
        return None
    a, b = np.log1p(a[-n:]), np.log1p(b[-n:])
    da, db = np.diff(a), np.diff(b)
    if da.std() == 0 or db.std() == 0:
        return None
    za, zb = (da - da.mean()) / da.std(), (db - db.mean()) / db.std()

    def ccf(x, y, k):
        if k >= 0:
            xs, ys = x[:len(x) - k], y[k:]
        else:
            xs, ys = x[-k:], y[:len(y) + k]
        return float(np.corrcoef(xs, ys)[0, 1]) if len(xs) > 4 and xs.std() > 0 and ys.std() > 0 else 0.0
    lags = list(range(-max_lag, max_lag + 1))
    cc = {k: ccf(za, zb, k) for k in lags}
    best = max(lags, key=lambda k: abs(cc[k]))
    bound = 1.96 / math.sqrt(len(za))
    h = len(za) // 2
    halves = []
    for xs, ys in ((za[:h], zb[:h]), (za[h:], zb[h:])):
        if len(xs) >= 8:
            c = {k: ccf(xs, ys, k) for k in lags}
            halves.append(max(lags, key=lambda k: abs(c[k])))
    stable = len(halves) == 2 and abs(halves[0] - halves[1]) <= 1 and halves[0] * best >= 0
    fva = None
    if best > 0:
        errs_m, errs_n = [], []
        for t in range(max(best + 6, len(db) // 2), len(db)):
            x, y = da[:t - best], db[best:t]
            if len(x) < 6 or np.std(x) == 0:
                continue
            beta = float(np.dot(x - x.mean(), y - y.mean()) / np.dot(x - x.mean(), x - x.mean()))
            alpha = float(y.mean() - beta * x.mean())
            errs_m.append(abs(db[t] - (alpha + beta * da[t - best])))
            errs_n.append(abs(db[t]))
        if errs_m and sum(errs_n) > 0:
            fva = 1 - sum(errs_m) / sum(errs_n)
    return {"lag": best, "correlacao": round(cc[best], 3), "limite_significancia": round(bound, 3),
            "significativa": abs(cc[best]) > bound, "estavel": stable, "lags_metades": halves,
            "ganho_backtest": None if fva is None else round(fva, 3), "n": int(len(za)),
            "ccf": {k: round(v, 3) for k, v in cc.items()},
            "interpretacao": ("A antecede B" if best > 0 else "B antecede A" if best < 0 else "movimento simultâneo"),
            "aviso": "Sinal exploratório: correlação temporal não implica causalidade nem garante que a tendência se repetirá."}


# ============================================================================ análise completa
def analyze(db, cfg: dict | None = None, today: date | None = None, forecasts: bool = True, state: dict | None = None) -> dict:
    cfg = cfg or {}
    today = today or date.today()
    cat = Catalog(db, cfg)
    cat.ensure_seeded()
    ing = ingest_content(db, cat, today)
    series = build_series(db, cat)
    prods = {p["product_id"]: p for p in cat.products()}
    for s in series:
        s["ind"] = indicators(s, today)
        p = prods.get(s["product_id"], {})
        s["nome"] = p.get("canonical") or label(s["product_id"])
        s["categoria"] = p.get("category")
        s["metrica"] = METRICS[s["metric"]]
        s["pais_nome"] = COUNTRY_NAMES.get(s["country"], s["country"])
        s["fonte_nome"] = SOURCE_NAMES.get(s["source"], s["source"])

    # previsões (somente séries mensais elegíveis; unidades preservadas)
    fc = {}
    if forecasts:
        from ..market import automl
        from ..market.automl import auto_forecast
        from ..market.store import MarketStore
        ms = MarketStore(db)
        # Wikipédia: reaproveita a previsão já feita pelo AutoML da Fase 2 (sem recalcular)
        for s in series:
            if s.get("market_series_id"):
                prev = automl.latest(ms, s["market_series_id"])
                if prev and prev.get("status") == "prevista":
                    fc[s["id"]] = {**prev, "serie": s["id"], "fonte": s["fonte_nome"], "unidade": s["metrica"]["unidade"],
                                   "origem": "AutoML da série coletada (Wikimedia)"}
        # volume de buscas: previsão própria (séries mensais com ≥ 24 meses; o Google Ads fornece 12 meses por consulta,
        # então o histórico elegível se forma com as coletas mensais)
        elig = [s for s in series if s["period"] == "mes" and s["metric"] == "volume_mensal_aprox" and s["ind"]["n"] >= 24]
        elig.sort(key=lambda s: -(s["ind"].get("media_3m") or 0))
        ml_left = int(cfg.get("trend_forecast_ml_max", 5))
        for s in elig[:int(cfg.get("trend_forecast_max", 20))]:
            if state is not None:
                state["atual"] = f"previsão de tendência: {s['nome']} ({s['pais_nome']})"
            m = _monthly(s["points"], today)
            try:
                f = auto_forecast(pd.Series(m.values, index=m.index.to_timestamp()), {"source": "google_ads_kp"},
                                  horizon=6, m=12, allow_ml=ml_left > 0)
                ml_left -= 1
                f["serie"] = s["id"]
                f["fonte"] = s["fonte_nome"]
                f["unidade"] = s["metrica"]["unidade"]
                fc[s["id"]] = f
            except Exception as e:  # noqa: BLE001
                fc[s["id"]] = {"status": "erro", "erro": str(e)}

    by_prod = defaultdict(list)
    for s in series:
        by_prod[s["product_id"]].append(s)

    # comparação internacional (mesma métrica e fonte, países diferentes)
    comps = {}
    for pid, lst in by_prod.items():
        groups = defaultdict(list)
        for s in lst:
            if s["period"] == "mes":
                groups[(s["metric"], s["source"])].append(s)
        res = []
        for (metric, source), g in groups.items():
            if len(g) < 2:
                continue
            g.sort(key=lambda s: s["country"])
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    A, B = g[i], g[j]
                    la, lb = dict(zip(A["ind"].get("labels", []), A["ind"].get("valores", []))), \
                        dict(zip(B["ind"].get("labels", []), B["ind"].get("valores", [])))
                    common = sorted(set(la) & set(lb))
                    ll = lead_lag([la[k] for k in common], [lb[k] for k in common])
                    if ll:
                        res.append({"metrica": METRICS[metric]["rotulo"], "metrica_id": metric,
                                    "fonte": SOURCE_NAMES.get(source, source), "a": A["country"],
                                    "b": B["country"], "a_nome": A["pais_nome"], "b_nome": B["pais_nome"], **ll})
        if res:
            comps[pid] = res

    # scores por produto (foco: Brasil)
    scores = {pid: product_scores(pid, lst, prods.get(pid, {}), fc, comps.get(pid, []), db) for pid, lst in by_prod.items()}

    pages = {cc: country_page(cc, series, scores, today) for cc in ("BR", "US", "CN")}
    alerts = build_alerts(series, today)
    sources = db.query("SELECT source, metric, country, COUNT(*) AS n, MIN(ref_date) AS de, MAX(ref_date) AS ate "
                       "FROM search_observations GROUP BY source, metric, country")
    out = {
        "gerado_em": today.isoformat(), "menções_novas": ing,
        "series": [{k: v for k, v in s.items() if k not in ("points",)} for s in series],
        "previsoes": fc, "comparacoes": comps, "scores": scores, "paises": pages, "alertas": alerts,
        "fontes_observacoes": sources,
        "kpis": {"produtos_monitorados": sum(1 for p in prods.values() if p["level"] == "produto"),
                 "variantes": sum(1 for p in prods.values() if p["level"] == "variante"),
                 "descobertos": sum(1 for p in prods.values() if p["origin"] == "descoberto"),
                 "emergentes": len({s["product_id"] for s in series if s["ind"].get("classe") == "emergente"}),
                 "tendencias": len({s["product_id"] for s in series if s["ind"].get("classe") not in ("estável", "sem dados")}),
                 "paises_com_buscas": sorted({PAGE_OF.get(s["country"]) for s in series if METRICS[s["metric"]]["tipo"] == "busca"}),
                 "fontes_com_dados": sorted({s["source"] for s in series})},
        "intencao_modelo": __import__("gpi.products.intent", fromlist=["x"]).default_model().info,
    }
    return _clean(out)


def product_scores(pid, lst, prod, fc, comps, db) -> dict:
    br = [s for s in lst if s["page"] == "BR"]
    intl = [s for s in lst if s["page"] in ("US", "CN")]

    def best_growth(group, kinds=("busca", "atencao", "popularidade")):
        for kind in kinds:
            vals = [s["ind"].get("crescimento") for s in group if METRICS[s["metric"]]["tipo"] == kind
                    and s["ind"].get("crescimento") is not None]
            if vals:
                return max(vals), kind
        return None, None
    comp, have = {}, {}
    g_br, k_br = best_growth(br)
    g_in, k_in = best_growth(intl)
    sq = lambda g: max(0.0, min(1.0, 0.5 + 0.5 * math.tanh(2 * g)))          # crescimento → 0..1
    if g_br is not None:
        comp["crescimento_brasil"] = sq(g_br)
    if g_in is not None:
        comp["crescimento_internacional"] = sq(g_in)
    cons = [s for s in lst if s["ind"].get("classe") == "crescimento consistente"]
    trendy = [s for s in lst if s["period"] == "dia"]
    if any(s["period"] == "mes" for s in lst) or trendy:
        comp["persistencia"] = min(1.0, len(cons) / 2 + sum(s["ind"].get("dias_em_alta_90d", 0) for s in trendy) / 20)
    ints = db.query("SELECT intent, COUNT(*) AS n FROM search_observations WHERE product_id LIKE ? GROUP BY intent",
                    (pid + "%",))
    tot = sum(r["n"] for r in ints)
    if tot >= 3:
        comp["intencao_compra"] = sum(r["n"] for r in ints if r["intent"] in ("compra", "comparacao", "review")) / tot
    compet = [json.loads(r["extra"]).get("indice_concorrencia") for r in db.query(
        "SELECT extra FROM search_observations WHERE product_id LIKE ? AND source = 'google_ads_kp' AND extra IS NOT NULL LIMIT 200",
        (pid + "%",))]
    compet = [c for c in compet if c is not None]
    if compet:
        comp["concorrencia_baixa"] = 1 - float(np.mean(compet)) / 100
    seas = [s["ind"]["sazonalidade"]["fs"] for s in lst if s["ind"].get("sazonalidade") and s["ind"]["sazonalidade"].get("significativa")]
    if seas:
        comp["estabilidade_sazonal"] = 1 - max(seas)
    vol = [s["ind"].get("volatilidade") for s in lst if s["ind"].get("volatilidade") is not None]
    if vol:
        comp["baixa_volatilidade"] = max(0.0, 1 - min(vol))
    comp["qualidade_dados"] = max(METRICS[s["metric"]]["peso_conf"] for s in lst) * min(1.0, max(s["ind"]["n"] for s in lst) / 24)
    W = {"crescimento_brasil": .22, "crescimento_internacional": .14, "persistencia": .14, "intencao_compra": .16,
         "concorrencia_baixa": .10, "estabilidade_sazonal": .06, "baixa_volatilidade": .08, "qualidade_dados": .10}
    cov = sum(W[k] for k in comp)
    score = 100 * sum(W[k] * v for k, v in comp.items()) / cov if cov else None
    fcs = [fc[s["id"]] for s in lst if s["id"] in fc and fc[s["id"]].get("status") == "prevista"]
    qmap = {"boa": 0.9, "razoável": 0.65, "fraca": 0.35, "muito fraca": 0.15}
    fconf = 100 * max((qmap.get(f.get("qualidade"), 0.3) * (0.6 + 0.4 * min(1, f["perfil"]["n"] / 60)) for f in fcs), default=0)
    sources = {s["source"] for s in lst}
    evid = 100 * (0.5 * cov + 0.5 * min(1.0, len(sources) / 4))
    ncm = prod.get("ncm_hint")
    has_comex = bool(ncm and db.query("SELECT 1 FROM market_series WHERE source = 'comexstat' AND series_key LIKE ? LIMIT 1",
                                      (f"%{ncm}%",)))
    checklist = {"NCM/SH fundamentado": bool(ncm), "Importações monitoradas (Comex Stat)": has_comex,
                 "Volume de buscas no Brasil": any(s["metric"] == "volume_mensal_aprox" and s["page"] == "BR" for s in lst),
                 "Previsão validada": bool(fcs), "Evidência de intenção de compra": "intencao_compra" in comp,
                 "Preços observados": False}
    readiness = 100 * sum(checklist.values()) / len(checklist)
    risks = []
    if not any(s["metric"] == "volume_mensal_aprox" for s in lst):
        risks.append("sem volume absoluto de buscas (conecte o Google Ads para medir)")
    if max(s["ind"]["n"] for s in lst) < 12:
        risks.append("histórico curto (< 12 períodos)")
    if seas and max(seas) > 0.6:
        risks.append("sazonalidade forte: demanda concentrada em alguns meses")
    if vol and min(vol) > 0.5:
        risks.append("alta volatilidade do interesse")
    if comp.get("concorrencia_baixa") is not None and comp["concorrencia_baixa"] < 0.34:
        risks.append("concorrência publicitária alta no Google")
    risks.append("sem preços observados: margem e rentabilidade não são estimadas")
    if not ncm:
        risks.append("sem NCM/SH tecnicamente fundamentado no catálogo")
    if any(c.get("significativa") and c.get("estavel") for c in comps):
        lead = next(c for c in comps if c.get("significativa") and c.get("estavel"))
    else:
        lead = None
    return {"opportunity_score": None if score is None else round(score, 1), "componentes": comp,
            "evidence_coverage": round(evid, 1), "forecast_confidence": round(fconf, 1),
            "import_readiness": round(readiness, 1), "checklist_importacao": checklist, "riscos": risks,
            "fontes": sorted(sources), "sinal_antecedente": lead,
            "aviso": "Score para priorizar investigação, não recomendação de compra nem estimativa de margem."}


def country_page(cc: str, series: list[dict], scores: dict, today: date) -> dict:
    mine = [s for s in series if s["page"] == cc]
    search = [s for s in mine if METRICS[s["metric"]]["tipo"] == "busca"]

    def item(s, val, extra=None):
        return {"product_id": s["product_id"], "nome": s["nome"], "categoria": s["categoria"], "pais": s["pais_nome"],
                "fonte": s["fonte_nome"], "metrica": s["metric"], "metrica_rotulo": s["metrica"]["rotulo"],
                "unidade": s["metrica"]["unidade"], "valor": val, "classe": s["ind"].get("classe"),
                "periodo": f"{s['ind'].get('primeiro')} a {s['ind'].get('ultimo')}",
                "score": (scores.get(s["product_id"]) or {}).get("opportunity_score"), **(extra or {})}

    vol = [s for s in search if s["metric"] == "volume_mensal_aprox"]
    trn = [s for s in search if s["metric"] == "trafego_faixa"]
    rk = {}
    rk["mais_pesquisados"] = {
        "mede": "Média dos últimos 3 meses de buscas por mês (Google Ads, aproximado). Ranking de volume absoluto.",
        "itens": sorted([item(s, s["ind"].get("media_3m")) for s in vol if s["ind"].get("media_3m")], key=lambda x: -x["valor"])[:50],
        "limitacao": None if vol else ("Sem fonte de volume de buscas conectada para este país: o ranking por volume não é "
                                       "exibido. Conecte o Planejador do Google Ads na Central de Integrações.")}
    rk["em_alta"] = {
        "mede": "Soma do tráfego mínimo (faixas) nas buscas em alta do Google nos últimos 30 dias, só termos de produto com intenção comercial.",
        "itens": sorted([item(s, s["ind"].get("soma_30d"), {"dias_em_alta": s["ind"].get("dias_em_alta_30d")})
                         for s in trn if s["ind"].get("soma_30d")], key=lambda x: -x["valor"])[:50],
        "limitacao": None if trn else "Nenhum termo de produto apareceu nas buscas em alta deste país no período coletado."}
    grow = [s for s in mine if s["ind"].get("crescimento") is not None and (s["ind"].get("n", 0) >= 6 or s["period"] == "dia")]
    rk["maior_crescimento"] = {"mede": "Variação do último trimestre sobre o mesmo trimestre do ano anterior (ou sobre o trimestre anterior quando "
                                       "há menos de 15 meses; 30 dias sobre os 30 anteriores nas buscas em alta), por métrica.",
                               "itens": sorted([item(s, s["ind"]["crescimento"]) for s in grow], key=lambda x: -x["valor"])[:50]}
    rk["emergentes"] = {"mede": "Produtos que passaram a aparecer recentemente (≤ 30 dias nas buscas em alta ou ≤ 3 meses nas séries mensais).",
                        "itens": [item(s, s["ind"].get("primeiro")) for s in mine if s["ind"].get("classe") == "emergente"][:50]}
    rk["crescimento_consistente"] = {"mede": "Tendência de alta estatisticamente significativa (Mann–Kendall, p < 0,05) e crescimento recente.",
                                     "itens": sorted([item(s, s["ind"].get("crescimento")) for s in mine if s["ind"].get("classe") == "crescimento consistente"],
                                                     key=lambda x: -(x["valor"] or 0))[:50]}
    rk["maior_aceleracao"] = {"mede": "Diferença entre o crescimento do último trimestre e o do trimestre anterior.",
                              "itens": sorted([item(s, s["ind"]["aceleracao"]) for s in mine if s["ind"].get("aceleracao") is not None],
                                              key=lambda x: -x["valor"])[:50]}
    rk["sazonais"] = {"mede": "Sazonalidade anual significativa (Kruskal–Wallis, p < 0,05) — força de 0 a 1.",
                      "itens": sorted([item(s, s["ind"]["sazonalidade"].get("fs")) for s in mine
                                       if s["ind"].get("sazonalidade") and s["ind"]["sazonalidade"].get("significativa")], key=lambda x: -x["valor"])[:50]}
    rk["declinio"] = {"mede": "Tendência de queda significativa ou queda > 15% no último trimestre.",
                      "itens": sorted([item(s, s["ind"].get("crescimento")) for s in mine if s["ind"].get("classe") == "declínio"],
                                      key=lambda x: (x["valor"] or 0))[:50]}
    cats = defaultdict(lambda: {"produtos": set(), "busca": 0.0})
    for s in search:
        c = cats[s["categoria"] or "Outros"]
        c["produtos"].add(s["product_id"])
        c["busca"] += s["ind"].get("media_3m") or s["ind"].get("soma_30d") or 0
    rk["categorias"] = {"mede": "Categorias com produtos nas fontes de busca deste país (soma por métrica de busca disponível).",
                        "itens": sorted([{"categoria": k, "produtos": len(v["produtos"]), "valor": v["busca"]} for k, v in cats.items()],
                                        key=lambda x: -x["valor"])}
    limit = []
    if cc == "CN":
        limit.append("Não há fonte autorizada de buscas de consumidores na China continental (Baidu Index, 巨量算数 e "
                     "dados do Alibaba exigem login chinês ou contrato). Os rankings de busca ficam vazios; a página "
                     "mostra apenas sinais auxiliares claramente identificados.")
    if not search:
        limit.append("Sem dados de busca coletados para este país.")
    regional = any(s.get("region") for s in mine)
    if not regional:
        limit.append("As fontes conectadas não informam a dimensão regional (UF); comparações por estado não são exibidas.")
    return {"pais": cc, "nome": COUNTRY_NAMES[cc], "rankings": rk, "limitacoes": limit,
            "series_busca": len(search), "series_auxiliares": len(mine) - len(search)}


def build_alerts(series: list[dict], today: date) -> list[dict]:
    out = []
    for s in series:
        ind = s["ind"]
        base = {"produto": s["nome"], "product_id": s["product_id"], "pais": s["pais_nome"], "fonte": s["fonte_nome"],
                "metrica": s["metrica"]["rotulo"]}
        if ind.get("classe") == "emergente":
            out.append({**base, "tipo": "novo produto em evidência", "detalhe": f"primeira observação em {ind.get('primeiro')}"})
        if s["period"] == "dia" and ind.get("dias_em_alta_7d"):
            out.append({**base, "tipo": "nas buscas em alta", "detalhe": f"{ind['dias_em_alta_7d']} dia(s) nos últimos 7 dias"})
        if ind.get("pontos_mudanca") and ind.get("labels") and ind["pontos_mudanca"][-1] in ind["labels"][-3:]:
            out.append({**base, "tipo": "mudança de patamar", "detalhe": f"novo regime a partir de {ind['pontos_mudanca'][-1]}"})
        if ind.get("anomalias") and ind.get("labels") and ind["anomalias"][-1] == ind["labels"][-1]:
            out.append({**base, "tipo": "anomalia no último período", "detalhe": "valor fora do padrão recente (|z robusto| > 3,5)"})
        if (ind.get("crescimento") or 0) > 0.5 and ind.get("n", 0) >= 6:
            out.append({**base, "tipo": "alta forte", "detalhe": f"+{ind['crescimento'] * 100:.0f}% no período recente"})
    return out[:300]


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, set):
        return sorted(_clean(v) for v in o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o
