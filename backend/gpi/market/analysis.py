"""Etapa de análise executada automaticamente após cada coleta."""
from __future__ import annotations

import logging
import time

from . import automl, content_intel, intel
from .content_store import ContentStore
from .store import MarketStore

log = logging.getLogger("gpi.analysis")


def make_analyzer(cfg: dict | None = None):
    cfg = cfg or {}

    def analyze(store: MarketStore, state: dict) -> dict:
        out, t0 = {}, time.time()

        def step(name, fn):
            state["atual"] = name
            try:
                out[name] = fn()
            except Exception as e:  # noqa: BLE001 — uma etapa com erro não impede as demais
                log.exception("falha na etapa %s", name)
                out[name] = {"erro": str(e)}
                state["erros"].append(f"análise/{name}: {e}")

        step("consumo_rapido", lambda: _consumer(store, cfg, state, forecasts=False))
        step("descoberta", lambda: _discovery(store, cfg))
        step("derivadas", lambda: intel.build_derived(store))
        step("conteudo", lambda: content_intel.process(store, ContentStore(store.db)))
        # oportunidades/clusters primeiro (o painel é publicado rápido); previsões depois,
        # e o ranking é recalculado ao fim para incorporar as previsões novas
        step("oportunidades", lambda: _intel(store))
        step("previsoes", lambda: _forecasts(store, cfg, state))
        step("consumo", lambda: _consumer(store, cfg, state, forecasts=True))
        if cfg.get("ml_global_enabled", False):
            step("ml_avancado", lambda: _advanced(store, cfg, state))
        out["segundos"] = round(time.time() - t0, 1)
        return out

    def quick(store: MarketStore, state: dict) -> dict:
        """Entre as etapas da coleta: atualiza o painel de consumo com o que já chegou (sem previsões)."""
        return _consumer(store, cfg, state, forecasts=False)

    analyze.quick = quick
    return analyze


def _advanced(store, cfg, state):
    from ..forecasting import advanced
    cons = store.load_result("consumer") or {}
    res = advanced.run_all(cons, cfg, store.load_result("ml_models"), state)
    store.save_result("ml_models", res)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with store.db.transaction():
        for e in res["drift"]:
            store.db.execute("INSERT OR IGNORE INTO drift_events (series_id, detector, ref_date, direction, detail, created_at)"
                             " VALUES (?, ?, ?, ?, ?, ?)", (e["serie"], e["detector"], e["data"], e["direcao"], e.get("nome"), now))
    return {"grupos": len(res["grupos"]), "mudancas": len(res["drift"]), "segundos": res["segundos"]}


def _consumer(store, cfg, state, forecasts: bool):
    from ..products import trends
    t0 = time.time()
    res = trends.analyze(store.db, cfg, forecasts=forecasts, state=state)
    prev = store.load_result("consumer") or {}
    if not forecasts and prev.get("previsoes"):
        res["previsoes"] = prev["previsoes"]          # análise rápida não descarta as previsões anteriores
    res["segundos_analise"] = round(time.time() - t0, 2)
    store.save_result("consumer", res)
    from ..products.catalog import Catalog
    from . import reviews2
    store.save_result("reviews2", reviews2.review_intelligence(store.db, Catalog(store.db, cfg)))
    store.save_result("competition", reviews2.competition(store.db))
    return {"series": len(res["series"]), "produtos": res["kpis"]["produtos_monitorados"],
            "segundos": res["segundos_analise"]}


def _discovery(store, cfg):
    d = intel.discover(store, cfg.get("discovery_min_usd", 1e6))
    store.save_result("discovery_headings", d)
    return {"posicoes": d["total_posicoes"], "prioritarias": len(d["prioritarias"]),
            "novas_categorias": len(d["novas_categorias"])}


def _priority_series(store, cfg) -> list[int]:
    """Ordem de prioridade para o AutoML (evita treinar tudo a cada abertura):
    séries principais dos produtos prioritários, câmbio e IBGE primeiro."""
    disc = store.load_result("discovery_headings") or {}
    codes = [r["codigo"] for r in disc.get("prioritarias", [])][: cfg.get("automl_max_headings", 60)]
    codes += [r["codigo"] for r in disc.get("novas_categorias", [])][:15]
    keys = [f"comex:china:{c}:fob" for c in codes]
    allser = store.series()
    sel = [s["id"] for k in keys for s in allser if s["series_key"] == k]
    sel += [s["id"] for s in allser if s["source"] == "wikimedia" and ":pt:" in s["series_key"]]
    sel += [s["id"] for s in allser if s["source"] == "wikimedia" and ":en:" in s["series_key"]]
    sel += [s["id"] for s in allser if s["source"] in ("ibge_pmc",) or s["series_key"].endswith(":M") and s["source"] == "bcb_ptax"]
    seen, out = set(), []
    for i in sel:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[: cfg.get("automl_max_series", 200)]


def _forecasts(store, cfg, state):
    ids = _priority_series(store, cfg)
    done = reused = fails = 0
    budget = cfg.get("automl_budget_s", 420)       # o restante continua na próxima sincronização
    n_ml = cfg.get("automl_ml_series", 25)          # ML (mais caro) só nas séries mais prioritárias
    t0 = time.time()
    pending = 0
    for i, sid in enumerate(ids):
        if time.time() - t0 > budget:
            pending = len(ids) - i
            break
        state["atual"] = f"previsões automáticas ({i + 1}/{len(ids)})"
        try:
            r = automl.run_series(store, sid, allow_ml=i < n_ml)
            if r and r.get("reutilizada"):
                reused += 1
            elif r:
                done += 1
        except Exception:  # noqa: BLE001
            log.exception("AutoML falhou na série %s", sid)
            fails += 1
    return {"treinadas": done, "reutilizadas": reused, "falhas": fails, "series": len(ids),
            "pendentes_proxima_execucao": pending}


def _intel(store):
    profiles = intel.product_profiles(store)
    lv = {}
    for kind in ("sh4:", "wiki:"):     # nível só é comparável dentro do mesmo tipo de sinal
        lv.update(intel.pct_rank({f["product_key"]: f.get("nivel_12m") for f in profiles
                                  if f["product_key"].startswith(kind)}))
    for f in profiles:
        f["nivel_pct"] = lv.get(f["product_key"])
        f["rotulo"], f["justificativa_rotulo"] = intel.label(f, lv.get(f["product_key"]))
    fx = None
    cny = next((s for s in store.series(source="bcb_ptax") if s["series_key"] == "bcb:ptax:CNY:M"), None)
    if cny:
        fx = intel.yoy(intel.monthly(store, cny["id"]))
    opps = intel.opportunity(profiles, fx, store.load_result("reviews"))
    clus = intel.clusterize(profiles)
    store.save_result("profiles", profiles)
    store.save_result("opportunities", {"itens": opps, "pesos": intel.WEIGHTS, "cambio_cny_12m": fx,
                                        "rankings": intel.rankings(opps, profiles)})
    store.save_result("clusters", clus)
    return {"produtos": len(profiles), "clusters": clus.get("k")}
