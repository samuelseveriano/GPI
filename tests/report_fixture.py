"""
Base de TESTE para relatórios e inteligência social (v0.6).

Dados sintéticos com fontes e unidades realistas, usados só em testes automatizados e nos
relatórios de exemplo. A base é marcada como demonstrativa ('base_demonstrativa'), então todo
relatório gerado a partir dela sai com a faixa e a marca d'água DEMONSTRAÇÃO.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np

TODAY = date(2026, 10, 15)


def months(n, end=date(2026, 9, 1)):
    out, d = [], end
    for _ in range(n):
        out.append(d)
        d = date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)
    return [x.isoformat() for x in reversed(out)]


def _obs(db, src, cc, pid, metric, pts, period="mes", term=None, unit="x", intent="compra", com=1):
    for d, v in pts:
        db.execute("INSERT OR REPLACE INTO search_observations (source,country,region,term,ref_date,period,metric,value,unit,"
                   "lang,product_id,intent,commercial,url,collected_at) VALUES (?,?,'',?,?,?,?,?,?,'pt',?,?,?,?,?)",
                   (src, cc, term or pid, d, period, metric, float(v), unit, pid, intent, com,
                    f"https://example.org/{src}/{pid}", TODAY.isoformat()))


def _soc(db, plat, cc, item, pid, metric, pts, period="dia", unit="x", com=1):
    from gpi.social.store import store
    for d, v in pts:
        store(db, {}, plat, cc, "hashtag", item, d, period, metric, v, unit, f"https://www.tiktok.com/tag/{item}", None,
              pid, "compra", com, TODAY)


def build(db, *, with_social=True, demo=True, seed=0) -> dict:
    from gpi.market.store import MarketStore
    from gpi.products import opportunity3, trends
    from gpi.products.catalog import Catalog
    from gpi.forecasting import social_ablation
    from gpi.social import analysis as social
    rng = np.random.default_rng(seed)
    Catalog(db, {}).ensure_seeded()
    ms = months(36)
    # volume de buscas (Google Ads, aproximado) — Brasil e EUA
    prods = {"air_fryer": (12000, 0.015, 0.25), "projector+portable": (3000, 0.04, 0.05), "charger+wireless": (8000, 0.02, 0.1),
             "camera": (9000, -0.012, 0.05), "lamp+led": (5000, 0.0, 0.35), "drill+wireless": (4000, 0.025, 0.15)}
    for pid, (base, g, seas) in prods.items():
        for cc, mult, lag in (("BR", 1.0, 0), ("US", 4.0, 6)):
            pts = []
            for k, d in enumerate(ms):
                kk = k + lag
                v = base * mult * (1 + g) ** kk * (1 + seas * math.sin(2 * math.pi * int(d[5:7]) / 12)) * (1 + rng.normal(0, 0.04))
                pts.append((d, round(max(v, 10), -1)))
            _obs(db, "google_ads_kp", cc, pid, "volume_mensal_aprox", pts, unit="buscas/mês (arredondado pelo Google)",
                 term={"projector+portable": "mini projetor portátil", "charger+wireless": "carregador sem fio"}.get(pid, pid))
    # buscas em alta (diário) e lista do Mercado Livre
    days = [(TODAY - timedelta(days=i)).isoformat() for i in range(40)]
    _obs(db, "google_trends_rss", "BR", "projector+portable", "trafego_faixa", [(d, 2000) for d in days[:20]], period="dia")
    _obs(db, "ml_trends", "BR", "projector+portable", "posicao_tendencia", [(d, 40 - i % 5) for i, d in enumerate(days[:25])], period="dia")
    _obs(db, "ml_trends", "BR", "charger+wireless", "posicao_tendencia", [(d, 20) for d in days[:10]], period="dia")
    _obs(db, "gdelt", "GLOBAL:news", "camera", "noticias_gdelt", [(d, 50 + 3 * k) for k, d in enumerate(ms[-12:])])
    # anúncios (eBay) — concorrência
    for i in range(30):
        db.execute("INSERT OR REPLACE INTO market_listings (source,item_id,day,product_id,query,title,brand,price,currency,country,seller,"
                   "condition,url,collected_at) VALUES ('ebay',?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"i{i}", TODAY.isoformat(), "projector+portable", "mini projector", f"Mini projector {i}", ["A", "B", "C"][i % 3],
                    60 + i, "USD", "US", f"s{i % 12}", "NEW", f"https://www.ebay.com/itm/{i}", TODAY.isoformat()))
    if with_social:
        sd = [(TODAY - timedelta(days=i)) for i in range(0, 240, 3)]
        _soc(db, "tiktok", "BR", "miniprojetor", "projector+portable", "tt_hashtag_posicao",
             [(d.isoformat(), min(200, 60 + (240 - (TODAY - d).days) * 0.5)) for d in sd], unit="pontos (201 − posição)")
        _soc(db, "tiktok", "BR", "miniprojetor", "projector+portable", "tt_hashtag_views",
             [(d.isoformat(), 1e5 * (1.01 ** (240 - (TODAY - d).days))) for d in sd], unit="visualizações")
        _soc(db, "tiktok", "BR", "carregadorsemfio", "charger+wireless", "tt_hashtag_posicao",
             [(d.isoformat(), 120) for d in sd], unit="pontos (201 − posição)")
        _soc(db, "tiktok", "BR", "câmerawifi", "camera", "tt_hashtag_posicao",
             [(d.isoformat(), max(5, 150 - (240 - (TODAY - d).days) * 0.5)) for d in sd], unit="pontos (201 − posição)")
        _soc(db, "instagram", "CONTA", "airfryer", "air_fryer", "ig_top_curtidas", [(d.isoformat(), 300 + 2 * (240 - (TODAY - d).days)) for d in sd],
             unit="curtidas por publicação (mediana)")
        _soc(db, "tiktok", "BR", "dancinha", None, "tt_hashtag_posicao", [(TODAY.isoformat(), 200)], com=0)
        # Facebook mensal com 30 meses: série social que ANTECEDE a busca (para a avaliação com × sem)
        y = {pid: [r["value"] for r in db.query("SELECT value FROM search_observations WHERE product_id = ? AND country = 'BR' "
                                                  "AND metric = 'volume_mensal_aprox' ORDER BY ref_date", (pid,))] for pid in prods}
        for pid in prods:
            vals = y[pid]
            for k, d in enumerate(ms):
                lead = vals[k + 1] if k + 1 < len(vals) else vals[-1]
                _soc(db, "facebook", "CONTA", f"pagina_loja · {pid}", pid, "fb_mencoes", [(d, max(1.0, lead / 100 * (1 + rng.normal(0, 0.02))))],
                     period="mes", unit="publicações/mês")
    store = MarketStore(db)
    cons = trends.analyze(db, {}, TODAY, forecasts=True)
    store.save_result("consumer", cons)
    from gpi.market import reviews2
    store.save_result("reviews2", reviews2.review_intelligence(db, Catalog(db, {})))
    store.save_result("competition", reviews2.competition(db))
    soc = social.analyze(db, {}, TODAY, consumer=cons)
    store.save_result("social", soc)
    store.save_result("opportunity3", opportunity3.build(cons, soc, store.load_result("reviews2"), store.load_result("competition"), db))
    store.save_result("ml_social", social_ablation.run(cons, soc))
    if demo:
        store.save_result("base_demonstrativa", {"motivo": "base sintética de teste do GPI (tests/report_fixture.py)"})
    return {"consumer": cons, "social": soc}
