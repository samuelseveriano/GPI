"""Rotas HTTP da inteligência de consumo (Fase 4)."""
from __future__ import annotations

import json
import threading

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from .catalog import Catalog
from .trends import COUNTRY_NAMES, METRICS


# Configurações editáveis pela interface (sem editar arquivos): chave → (tipo, mín, máx, descrição)
SETTINGS = {
    "auto_sync": (bool, None, None, "Sincronizar automaticamente ao abrir e semanalmente"),
    "sync_workers": (int, 1, 8, "Fontes coletadas em paralelo (cada fonte continua respeitando seus limites)"),
    "trends_geos": (list, None, None, "Países do Google Trends — Trending Now (códigos ISO, ex.: BR, US)"),
    "catalog_max_products": (int, 500, 50000, "Limite de produtos no catálogo (controle de memória)"),
    "catalog_max_candidates": (int, 1000, 200000, "Limite de termos candidatos guardados"),
    "kp_max_products": (int, 10, 2000, "Produtos consultados por mês no Planejador do Google Ads"),
    "trend_forecast_max": (int, 0, 200, "Séries de busca previstas por sincronização"),
    "gdelt_max_products": (int, 0, 200, "Produtos consultados no GDELT por sincronização"),
    "ebay_max_products": (int, 0, 200, "Produtos pesquisados no eBay por sincronização"),
    "bq_max_gb": (float, 0.1, 100.0, "Limite de dados processados por consulta no BigQuery (GB) — consultas acima disso não são executadas"),
    "ml_global_enabled": (bool, None, None, "Treinar o modelo global multi-série (LightGBM/XGBoost/CatBoost) após a sincronização"),
    "ml_tuning_trials": (int, 0, 100, "Tentativas de otimização de hiperparâmetros (Optuna); 0 desliga"),
    "ml_tuning_seconds": (int, 10, 1800, "Tempo máximo da otimização de hiperparâmetros (segundos)"),
    # v0.6 — relatórios e redes sociais
    "auto_report_weekly": (bool, None, None, "Gerar relatório semanal automaticamente (executivo em PDF e Excel, após a sincronização; "
                                             "se o GPI estiver fechado, gera na próxima abertura). Salvo só neste computador."),
    "tiktok_countries": (list, None, None, "Países das hashtags populares do TikTok (códigos ISO, ex.: BR, US)"),
    "tiktok_account_country": (str, None, None, "País da conta TikTok for Business (ex.: BR) — os termos de busca em alta são da região da conta; vazio = não informado"),
    "tiktok_max_products": (int, 0, 100, "Produtos consultados nos termos recomendados do TikTok por semana"),
    "instagram_max_hashtags": (int, 0, 30, "Hashtags do Instagram consultadas por 7 dias (a Meta permite no máximo 30 por conta)"),
    "facebook_pages": (tuple, None, None, "Páginas do Facebook a acompanhar (IDs ou nomes de usuário, separados por vírgula) — páginas que você administra ou, com aprovação da Meta, páginas públicas"),
    "meta_ads_enabled": (bool, None, None, "Consultar a Biblioteca de Anúncios da Meta (exige identidade verificada; só anúncios comerciais da UE)"),
    "meta_ads_countries": (list, None, None, "Países da UE consultados na Biblioteca de Anúncios (ex.: DE, FR, ES, IT, PT)"),
    "youtube_em_indices": (bool, None, None, "Usar estatísticas do YouTube nos índices sociais combinados — marque só se o projeto Google aceitou o caso de uso 'Analytics & Reporting' da política de métricas derivadas"),
    "retencao_dias_tiktok": (int, 1, 1095, "Retenção dos dados do TikTok (dias)"),
    "retencao_dias_instagram": (int, 1, 1095, "Retenção dos dados do Instagram (dias)"),
    "retencao_dias_facebook": (int, 1, 1095, "Retenção dos dados do Facebook (dias)"),
    "retencao_dias_meta_ads": (int, 1, 1095, "Retenção dos dados da Biblioteca de Anúncios (dias)"),
    "retencao_dias_youtube": (int, 1, 1095, "Retenção das estatísticas do YouTube (dias; a política permite até 36 meses)"),
}


DEFAULTS = {"auto_sync": True, "sync_workers": 4, "trends_geos": ["BR", "US"], "catalog_max_products": 5000,
            "catalog_max_candidates": 20000, "kp_max_products": 200, "trend_forecast_max": 20, "gdelt_max_products": 30,
            "ebay_max_products": 30, "bq_max_gb": 2.0, "ml_global_enabled": True, "ml_tuning_trials": 15, "ml_tuning_seconds": 120,
            "auto_report_weekly": False, "tiktok_countries": ["BR", "US"], "tiktok_account_country": "", "tiktok_max_products": 20,
            "instagram_max_hashtags": 25, "facebook_pages": [], "meta_ads_enabled": False,
            "meta_ads_countries": ["DE", "FR", "ES", "IT", "PT"], "youtube_em_indices": False,
            "retencao_dias_tiktok": 90, "retencao_dias_instagram": 90, "retencao_dias_facebook": 90, "retencao_dias_meta_ads": 90,
            "retencao_dias_youtube": 1095}


def routes(db, sync, cfg, save_settings=None) -> list[Route]:
    lock = threading.Lock()

    def result() -> dict:
        r = sync.store.load_result("consumer")
        if r:
            return r
        # primeira abertura: mostra imediatamente o que existe localmente (sem previsões)
        with lock:
            r = sync.store.load_result("consumer")
            if not r:
                from . import trends
                r = trends.analyze(db, cfg, forecasts=False, today=sync.today_fn())
                sync.store.save_result("consumer", r)
        return r

    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def dashboard(_):
        r = await run_in_threadpool(result)
        series = r["series"]
        best = {}
        for s in series:                         # por produto: o sinal mais forte (busca > atenção > menções)
            rank = {"busca": 0, "busca_ranking": 1, "atencao": 2, "popularidade": 3}[METRICS[s["metric"]]["tipo"]]
            cur = best.get(s["product_id"])
            if cur is None or (rank, -(s["ind"].get("n") or 0)) < cur[0]:
                best[s["product_id"]] = ((rank, -(s["ind"].get("n") or 0)), s)
        rows = []
        for pid, (_, s) in best.items():
            sc = r["scores"].get(pid, {})
            ind = s["ind"]
            rows.append({"product_id": pid, "nome": s["nome"], "categoria": s["categoria"], "pais": s["pais_nome"],
                         "indicador": s["metrica"]["rotulo"], "unidade": s["metrica"]["unidade"],
                         "valor": ind.get("media_3m", ind.get("soma_30d")), "crescimento": ind.get("crescimento"),
                         "tendencia": ind.get("classe"), "confianca": sc.get("evidence_coverage"),
                         "score": sc.get("opportunity_score"), "fonte": s["fonte_nome"]})
        rows.sort(key=lambda x: -(x["score"] or 0))
        growth = {}
        for s in series:
            if s["ind"].get("crescimento") is not None:
                g = growth.setdefault(s["pais_nome"], [])
                g.append(s["ind"]["crescimento"])
        syncs = db.query("SELECT finished_at FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
        return j({"kpis": {**r["kpis"], "ultima_atualizacao": syncs[0]["finished_at"] if syncs else None,
                           "paises_analisados": [COUNTRY_NAMES[c] for c in r["kpis"]["paises_com_buscas"] if c in COUNTRY_NAMES],
                           "fontes_disponiveis": len(r["kpis"]["fontes_com_dados"])},
                  "tabela": rows[:100], "alertas": r["alertas"][:20],
                  "crescimento_por_pais": {k: sorted(v)[len(v) // 2] for k, v in growth.items()},
                  "emergentes": [s for s in series if s["ind"].get("classe") == "emergente"][:20],
                  "evolucao": [s for s in sorted(series, key=lambda s: -((r["scores"].get(s["product_id"]) or {}).get("opportunity_score") or 0))
                               if s["period"] == "mes" and s["ind"].get("n", 0) >= 6][:6],
                  "gerado_em": r["gerado_em"], "metricas": METRICS,
                  "intencao_modelo": r.get("intencao_modelo")})

    async def country(request):
        cc = request.path_params["cc"].upper()
        r = await run_in_threadpool(result)
        if cc not in r["paises"]:
            return j({"erro": "país não suportado"}, 404)
        page = r["paises"][cc]
        aux = [s for s in r["series"] if s["page"] == cc and METRICS[s["metric"]]["tipo"] not in ("busca", "busca_ranking")]
        return j({**page, "auxiliares": aux[:60], "metricas": METRICS})

    def _insights():
        from .insights import build
        r = result()
        prods = {p["product_id"]: p for p in Catalog(db, cfg).products()}
        return build(r, db, prods)

    async def insights(_):
        return j(await run_in_threadpool(_insights))

    async def insight_one(request):
        pid = request.path_params["pid"]
        d = await run_in_threadpool(_insights)
        it = next((i for i in d["itens"] if i["produto_id"] == pid), None)
        if it is None:
            fam = pid.split(":")[0]
            it = next((i for i in d["itens"] if i["produto_id"] == fam), None)
        return j(it or {"produto_id": pid, "situacao": "EVIDÊNCIA INSUFICIENTE",
                        "analise": "Nenhuma série coletada para este produto ainda.", "proxima_acao":
                        "Coletar dados (sincronizar fontes de busca, atenção ou marketplaces) antes de qualquer conclusão."})

    async def product(request):
        pid = request.path_params["pid"]
        cat = Catalog(db, cfg)
        p = await run_in_threadpool(cat.get, pid)
        if not p:
            return j({"erro": "produto não encontrado"}, 404)
        fam = p["parent_id"] or p["product_id"]
        r = await run_in_threadpool(result)
        series = [s for s in r["series"] if s["product_id"] == fam]
        obs = db.query("SELECT source, country, term, ref_date, metric, value, intent, url, extra FROM search_observations "
                       "WHERE product_id = ? OR product_id LIKE ? ORDER BY ref_date DESC LIMIT 60", (fam, fam + ":%"))
        for o in obs:
            o["extra"] = json.loads(o["extra"]) if o["extra"] else None
        ml = sync.store.load_result("ml_models") or {}
        ml_series = {sid: v for g in ml.get("grupos", {}).values() for sid, v in (g.get("por_serie") or {}).items()
                     if sid.split("|")[0] == fam}
        comp = [c for c in (sync.store.load_result("competition") or {}).get("itens", []) if c["product_id"] == fam]
        rev = next((x for x in (sync.store.load_result("reviews2") or {}).get("produtos", []) if x["product_id"] == fam), None)
        return j({"produto": p, "series": series, "ml": ml_series, "concorrencia": comp, "reviews": rev,
                  "previsoes": {k: v for k, v in r["previsoes"].items() if k.split("|")[0] == fam},
                  "comparacoes": r["comparacoes"].get(fam, []), "score": r["scores"].get(fam),
                  "evidencias": obs, "metricas": METRICS})

    async def compare(request):
        r = await run_in_threadpool(result)
        pid = request.query_params.get("produto")
        prods = sorted({(s["product_id"], s["nome"]) for s in r["series"]
                        if len({x["page"] for x in r["series"] if x["product_id"] == s["product_id"]}) >= 2})
        if not pid and prods:
            pid = prods[0][0]
        series = [s for s in r["series"] if s["product_id"] == pid]
        return j({"produtos": [{"product_id": a, "nome": b} for a, b in prods], "produto": pid, "series": series,
                  "comparacoes": r["comparacoes"].get(pid, []), "metricas": METRICS,
                  "normalizacao": "Cada série é dividida pela própria média (índice 100 = média do período) apenas para "
                                  "comparar formas; níveis absolutos de métricas diferentes não são comparados."})

    async def opportunities(_):
        r = await run_in_threadpool(result)
        names = {s["product_id"]: (s["nome"], s["categoria"]) for s in r["series"]}
        items = [{"product_id": k, "nome": names.get(k, (k, None))[0], "categoria": names.get(k, (k, None))[1], **v}
                 for k, v in r["scores"].items()]
        items.sort(key=lambda x: -(x.get("opportunity_score") or 0))
        return j({"itens": items, "definicoes": {
            "opportunity_score": "Potencial comercial estimado (0–100) a partir dos sinais disponíveis; ausência de uma fonte não penaliza.",
            "evidence_coverage": "Quantidade e diversidade de evidências (peso dos componentes disponíveis e número de fontes).",
            "forecast_confidence": "Confiabilidade da previsão (qualidade no backtesting e tamanho do histórico); 0 = sem previsão validada.",
            "import_readiness": "Itens já verificados para uma eventual decisão de importação (NCM, importações, buscas, previsão, intenção, preços)."}})

    async def alerts(_):
        r = await run_in_threadpool(result)
        return j({"itens": r["alertas"]})

    async def anomalies(_):
        r = await run_in_threadpool(result)
        return j({"itens": [s for s in r["series"] if s["ind"].get("anomalias") or s["ind"].get("pontos_mudanca")]})

    async def trend_forecasts(_):
        r = await run_in_threadpool(result)
        names = {s["id"]: s for s in r["series"]}
        out = []
        for sid, f in r["previsoes"].items():
            s = names.get(sid, {})
            out.append({"serie": sid, "nome": s.get("nome"), "pais": s.get("pais_nome"), "fonte": s.get("fonte_nome"),
                        "metrica": (s.get("metrica") or {}).get("rotulo"), **f})
        return j({"itens": out, "aviso": "Previsões de INTERESSE (buscas aproximadas ou visualizações). Não equivalem a unidades vendidas."})

    async def discovery(_):
        cat = Catalog(db, cfg)
        cands = await run_in_threadpool(cat.candidates, None, 300)
        disc = [p for p in await run_in_threadpool(cat.products) if p["origin"] == "descoberto"]
        disc.sort(key=lambda p: p["first_seen"], reverse=True)
        from .intent import default_model
        return j({"candidatos": cands, "descobertos": disc[:200], "intencao_modelo": default_model().info})

    async def catalog(request):
        q = (request.query_params.get("q") or "").lower()
        rows = await run_in_threadpool(Catalog(db, cfg).products)
        if q:
            rows = [p for p in rows if q in (p["canonical"] or "").lower() or q in (p["name_en"] or "").lower()
                    or q in (p["name_zh"] or "")]
        return j({"itens": rows[:500], "total": len(rows)})

    async def analyze_term(request):
        from . import nlp
        from .intent import classify
        t = request.query_params.get("texto", "")[:300]
        a = nlp.analyze(t)
        return j({**a, "intencao": classify(t), "catalogo": Catalog(db, cfg).match(t) is not None})

    async def performance(_):
        runs = db.query("SELECT id, started_at, finished_at, state, summary FROM sync_runs ORDER BY id DESC LIMIT 10")
        out = []
        for r in runs:
            summ = json.loads(r["summary"] or "{}")
            out.append({"id": r["id"], "inicio": r["started_at"], "fim": r["finished_at"], "estado": r["state"],
                        "desempenho": summ.get("desempenho"),
                        "fontes": db.query("SELECT * FROM source_metrics WHERE run_id = ? ORDER BY seconds DESC", (r["id"],))})
        return j({"execucoes": out})

    async def search(request):
        q = (request.query_params.get("q") or "").strip().lower()[:80]
        if len(q) < 2:
            return j({"itens": []})
        from . import nlp
        qn = nlp._norm(q)
        out = []
        for cc, name in (("BR", "Brasil"), ("US", "Estados Unidos"), ("CN", "China")):
            if qn in nlp._norm(name) or q == cc.lower():
                out.append({"titulo": name, "tipo": "País", "href": f"#consumo/{cc}", "detalhe": "inteligência de consumo"})
        rows = db.query("SELECT product_id, canonical, name_en, name_zh, category, family, level FROM catalog_products "
                        "WHERE lower(canonical) LIKE ? OR lower(name_en) LIKE ? OR name_zh LIKE ? OR lower(category) LIKE ? "
                        "OR family LIKE ? OR product_id IN (SELECT product_id FROM product_aliases WHERE alias_norm LIKE ?) "
                        "ORDER BY level, evidence DESC LIMIT 25", (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", f"%{qn}%", f"%{qn}%"))
        cats = sorted({r["category"] for r in rows if q in (r["category"] or "").lower()})
        out += [{"titulo": c, "tipo": "Categoria", "href": "#mais-pesquisados/BR/categorias", "detalhe": "rankings por categoria"} for c in cats[:3]]
        out += [{"titulo": r["canonical"], "tipo": "Variante" if r["level"] == "variante" else "Produto",
                 "detalhe": f"{r['category']} · família {r['family']}", "href": "#produto-consumo/" + r["product_id"]} for r in rows]
        kws = db.query("SELECT term, country, source, product_id FROM search_observations WHERE lower(term) LIKE ? "
                       "AND product_id IS NOT NULL GROUP BY term LIMIT 10", (f"%{q}%",))
        out += [{"titulo": k["term"], "tipo": "Palavra-chave", "detalhe": f"{k['country']} · {k['source']}",
                 "href": "#produto-consumo/" + k["product_id"]} for k in kws]
        return j({"itens": out[:30]})

    async def settings(request):
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                body = {}
            vals, errs = {}, []
            for k, v in body.items():
                if v is None or (isinstance(v, str) and not v.strip()) or v == [""]:
                    continue                                    # campo em branco: mantém o valor atual
                if k not in SETTINGS:
                    errs.append(f"{k}: configuração desconhecida")
                    continue
                typ, lo, hi, _ = SETTINGS[k]
                try:
                    if typ is bool:
                        v = bool(v)
                    elif typ is list:
                        v = [str(x).strip().upper()[:2] for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
                    elif typ is tuple:
                        v = [str(x).strip()[:120] for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()][:20]
                    elif typ is str:
                        v = str(v).strip().upper()[:2]
                    else:
                        v = typ(v)
                        if (lo is not None and v < lo) or (hi is not None and v > hi):
                            raise ValueError(f"fora do intervalo {lo}–{hi}")
                    vals[k] = v
                except (TypeError, ValueError) as e:
                    errs.append(f"{k}: {e}")
            if errs:
                return j({"erro": "; ".join(errs)}, 400)
            if save_settings:
                save_settings(vals)
            else:
                cfg.update(vals)
        return j({"valores": {k: cfg.get(k, DEFAULTS.get(k)) for k in SETTINGS},
                  "campos": [{"chave": k, "tipo": t.__name__, "min": lo, "max": hi, "descricao": d} for k, (t, lo, hi, d) in SETTINGS.items()]})

    async def models(_):
        from ..forecasting.advanced import libs
        from . import discovery
        ml = sync.store.load_result("ml_models") or {}
        drift = db.query("SELECT * FROM drift_events ORDER BY created_at DESC, ref_date DESC LIMIT 100")
        return j({"ml": ml, "bibliotecas": libs(), "descoberta": discovery.status(), "mudancas": drift,
                  "aviso": "Comparações por backtesting de origem móvel nas mesmas origens; o melhor modelo é escolhido por série."})

    async def reviews2(_):
        return j(sync.store.load_result("reviews2") or {"produtos": [], "clusters": {"grupos": []},
                                                          "aviso": "Ainda não calculado: aguarde a primeira sincronização."})

    async def competition(_):
        return j(sync.store.load_result("competition") or {"itens": [], "aviso": "Sem anúncios coletados: conecte o eBay na Central de Integrações."})

    async def import_defaults(_):
        r = db.query("SELECT o.value, o.ref_date FROM market_obs o JOIN market_series s ON s.id = o.series_id "
                     "WHERE s.series_key = 'bcb:ptax:USD:D' ORDER BY o.ref_date DESC LIMIT 1")
        from ..market.viability import REQUIRED
        return j({"cambio_ptax": r[0] if r else None, "campos": REQUIRED})

    async def import_simulate(request):
        from ..market.viability import simulate
        try:
            body = await request.json()
            res = await run_in_threadpool(simulate, body.get("parametros", body), int(body.get("cenarios", 10000)))
        except (ValueError, KeyError, TypeError) as e:
            return j({"erro": str(e)}, 400)
        return j(res)

    return [
        Route("/api/consumer/models", models),
        Route("/api/consumer/reviews2", reviews2),
        Route("/api/consumer/competition", competition),
        Route("/api/import/defaults", import_defaults),
        Route("/api/import/simulate", import_simulate, methods=["POST"]),
        Route("/api/search", search),
        Route("/api/settings", settings, methods=["GET", "POST"]),
        Route("/api/consumer/dashboard", dashboard),
        Route("/api/consumer/country/{cc}", country),
        Route("/api/consumer/insights", insights),
        Route("/api/consumer/insights/{pid:path}", insight_one),
        Route("/api/consumer/product/{pid:path}", product),
        Route("/api/consumer/compare", compare),
        Route("/api/consumer/opportunities", opportunities),
        Route("/api/consumer/alerts", alerts),
        Route("/api/consumer/anomalies", anomalies),
        Route("/api/consumer/forecasts", trend_forecasts),
        Route("/api/consumer/discovery", discovery),
        Route("/api/consumer/catalog", catalog),
        Route("/api/consumer/analyze", analyze_term),
        Route("/api/consumer/performance", performance),
    ]
