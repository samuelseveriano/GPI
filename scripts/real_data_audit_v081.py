"""Auditoria v0.8.1 com DADOS REAIS públicos (CI, sem credenciais).

Coleta, pelo mesmo código do aplicativo, Wikimedia (todo o catálogo), Comex Stat, BCB PTAX e Google Trends RSS e mede:
  G — declínio: regra antiga (v0.8: queda significativa OU queda > 15%) × v0.8.1 (significância + BH + coorte + persistência)
  H — sazonalidade: regra antiga (Kruskal–Wallis com ≥ 24 meses) × v0.8.1 (3 ciclos, ACF12, pico estável)
  C — Wikipédia nunca classificada como demanda comercial nem com score de oportunidade
  F — comparações entre idiomas nunca viram "sinal internacional consistente"
  I — backtesting de previsão em séries REAIS elegíveis (atenção pública e comércio exterior), com o fenômeno declarado
  B — coberturas recalculadas com fórmula
Uso: python scripts/real_data_audit_v081.py saida.json
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from gpi.db import Database  # noqa: E402
from gpi.market.sync import SyncManager  # noqa: E402


def main(out: str):
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp())
    db = Database(tmp / "real.sqlite")
    cfg = {"history_start_year": date.today().year - 5, "contact": "ci-auditoria-v081", "max_jobs_per_source": 400, "sync_workers": 4}
    from gpi.products.catalog import Catalog
    Catalog(db, cfg).ensure_seeded()
    sm = SyncManager(db, tmp, cfg)
    summ = sm.run("auditoria-v081", ["wikimedia", "comexstat", "bcb_ptax", "google_trends_rss"])
    # Wikimedia coleta em duas etapas: 1ª passada resolve os títulos (langlinks); as visualizações são planejadas na 2ª
    summ2 = sm.run("auditoria-v081-pv", ["wikimedia"])
    summ["fontes"]["wikimedia_visualizacoes"] = summ2["fontes"].get("wikimedia", {})
    rep = {"coleta": {k: {x: v.get(x) for x in ("estado", "segundos", "jobs_ok", "jobs_falhos", "novas", "ultimo_erro")}
                      for k, v in summ["fontes"].items()},
           "produtos_wikipedia_resolvidos": sum(1 for p in sm.store.products() if p.get("origin") == "wikipedia"),
           "registros": {r["source"]: r["n"] for r in db.query("SELECT s.source, COUNT(*) AS n FROM market_obs o JOIN market_series s "
                                                                "ON s.id = o.series_id GROUP BY s.source")}}
    from gpi.products import trends as T
    r = T.analyze(db, cfg, date.today(), forecasts=False)
    series = r["series"]
    wiki = [s for s in series if s["metric"] == "visualizacoes"]
    # ---- G / H: antes × depois
    old_dec = new_dec = old_seas = new_seas = 0
    new_classes = Counter()
    seas_detail = Counter()
    for s in wiki:
        ind = s["ind"]
        tt = ind.get("tendencia") or {}
        if (tt.get("significativa") and tt.get("direcao") == "queda") or (ind.get("crescimento") or 0) < -0.15:
            old_dec += 1
        if ind.get("classe") == "declínio":
            new_dec += 1
        new_classes[ind.get("classe")] += 1
        sz = ind.get("sazonalidade") or {}
        if sz.get("significativa_teste"):
            old_seas += 1
        if sz.get("significativa"):
            new_seas += 1
        if sz:
            seas_detail[sz.get("classificacao")] += 1
    rep["G_declinio"] = {"series_wikipedia": len(wiki), "regra_v08": old_dec, "declinio_confirmado_v081": new_dec,
                         "classes_v081": dict(new_classes), "medianas_coorte": r["testes_multiplos"]["medianas_coorte"],
                         "reclassificacoes": r["testes_multiplos"]["reclassificacoes"],
                         "nota": "Declínio aqui é da ATENÇÃO na Wikipédia, nunca de vendas."}
    rep["H_sazonalidade"] = {"regra_v08_kruskal": old_seas, "confirmada_v081": new_seas, "classificacoes_v081": dict(seas_detail),
                             "nota": "Sazonalidade de atenção — não é sazonalidade comercial."}
    # ---- C / F / B: fusão
    from gpi.intel import commercial, fusion
    prods = {p["product_id"]: p for p in Catalog(db, cfg).products()}
    fu = fusion.build(db, r, prods, date.today())
    P = fu["produtos"]
    wiki_only = [p for p in P.values() if p["evidencias"] and all(e["metrica"] == "visualizacoes" for e in p["evidencias"])]
    bad = [p["produto_id"] for p in wiki_only if p["situacao"] in fusion.GROWING | {"DECLÍNIO", "INTERESSE RECORRENTE"}
           or p["indices"]["opportunity_score"] is not None or p["pontuacao"]["investigation_priority"]["valor"] is not None]
    legacy_scored = [pid for pid, sc in r["scores"].items() if sc.get("opportunity_score") is not None
                     and all(s["metric"] == "visualizacoes" for s in series if s["product_id"] == pid)]
    rep["C_wikipedia"] = {"produtos_so_wikipedia": len(wiki_only), "classificados_como_demanda": bad,
                          "score_legado_so_wikipedia": legacy_scored, "aprovado": not bad and not legacy_scored,
                          "situacoes": dict(Counter(p["situacao"] for p in wiki_only))}
    ll = [c for lst in r["comparacoes"].values() for c in lst]
    rep["F_internacional"] = {"comparacoes": len(ll), "por_dimensao": dict(Counter(c["dimensao"] for c in ll)),
                              "por_classe": dict(Counter(c["classe_antecedencia"] for c in ll)),
                              "idioma_como_consistente": sum(1 for c in ll if c["dimensao"] != "geografica"
                                                             and c["classe_antecedencia"] == "sinal internacional consistente"),
                              "exemplos": [{k: c.get(k) for k in ("a", "b", "correlacao", "r2", "estavel", "classe_antecedencia")} for c in ll[:5]],
                              "paginas_de_pais_com_wikipedia": sum(1 for s in series if s["metric"] == "visualizacoes" and s["page"] in T.GEO_PAGES)}
    rep["B_cobertura"] = commercial.coverage(P, sum(1 for p in prods.values() if p.get("level") == "produto"))
    # ---- I: backtesting em séries reais elegíveis
    from gpi.forecasting.backtest import backtest
    from gpi.intel.quality import series_eligibility
    from gpi.market.store import MarketStore
    ms = MarketStore(db)
    res = []
    elig = [s for s in wiki if series_eligibility(s)["metodos"]["previsao"]]
    for s in sorted(elig, key=lambda s: -(s["ind"].get("media_3m") or 0))[:25]:
        y = np.asarray(s["ind"]["valores"], float)
        bt = backtest(y, 6, 12, ["naive", "seasonal_naive", "ses", "holt_damped", "ets_auto", "holt_winters"], n_origins=6)
        R = {k: v for k, v in bt["resultados"].items() if not v.get("falhou") and v.get("wape") is not None}
        if not R or "naive" not in R:
            continue
        b = min(R, key=lambda k: R[k]["wape"])
        res.append({"serie": s["id"], "fenomeno": "atenção pública (Wikipédia)", "n": len(y), "melhor": b, "wape": R[b]["wape"],
                    "wape_naive": R["naive"]["wape"], "fva": 1 - R[b]["wape"] / R["naive"]["wape"] if R["naive"]["wape"] else None,
                    "cobertura_80": R[b].get("cobertura_80")})
    cx = [m for m in ms.series(source="comexstat") if m["series_key"].endswith(":fob")]
    rep["I_comex_diagnostico"] = {"series_fob": len(cx), "obs_por_serie": sorted(int(m["n_obs"] or 0) for m in cx)[-10:],
                                  "exemplo": cx[0]["series_key"] if cx else None}
    for meta in sorted(cx, key=lambda m: -(m["n_obs"] or 0))[:25]:
        obs = db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date", (meta["id"],))
        y = np.asarray([o["value"] for o in obs], float)
        if len(y) < 30 or np.mean(y > 0) < 0.8:
            continue
        bt = backtest(y, 6, 12, ["naive", "seasonal_naive", "ses", "holt_damped", "ets_auto", "holt_winters"], n_origins=6)
        R = {k: v for k, v in bt["resultados"].items() if not v.get("falhou") and v.get("wape") is not None}
        if not R or "naive" not in R:
            continue
        b = min(R, key=lambda k: R[k]["wape"])
        res.append({"serie": meta["series_key"], "fenomeno": "comércio exterior (importação US$ FOB por NCM)", "n": len(y), "melhor": b,
                    "wape": R[b]["wape"], "wape_naive": R["naive"]["wape"],
                    "fva": 1 - R[b]["wape"] / R["naive"]["wape"] if R["naive"]["wape"] else None, "cobertura_80": R[b].get("cobertura_80")})
    by = {}
    for x in res:
        g = by.setdefault(x["fenomeno"], {"series": 0, "wape_mediano": [], "fva_mediano": [], "baseline_venceu": 0, "cobertura80": [], "modelos": Counter()})
        g["series"] += 1
        g["wape_mediano"].append(x["wape"])
        g["fva_mediano"].append(x["fva"] or 0)
        g["baseline_venceu"] += x["melhor"] == "naive"
        if x.get("cobertura_80") is not None:
            g["cobertura80"].append(x["cobertura_80"])
        g["modelos"][x["melhor"]] += 1
    rep["I_backtesting_real"] = {k: {"series": v["series"], "wape_mediano": float(np.median(v["wape_mediano"])),
                                     "fva_mediano": float(np.median(v["fva_mediano"])), "naive_foi_o_melhor": v["baseline_venceu"],
                                     "cobertura_ic80_media": float(np.mean(v["cobertura80"])) if v["cobertura80"] else None,
                                     "modelos_vencedores": dict(v["modelos"])} for k, v in by.items()}
    rep["I_series"] = res
    rep["I_nota"] = ("Previsões de ATENÇÃO PÚBLICA e de COMÉRCIO EXTERIOR — não são previsões de demanda comercial. "
                     "Demanda efetiva só com vendas do usuário.")
    rep["segundos"] = round(time.time() - t0, 1)
    Path(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k in ("registros", "G_declinio", "H_sazonalidade", "C_wikipedia", "F_internacional", "I_backtesting_real"):
        v = rep[k]
        if isinstance(v, dict):
            v = {a: b for a, b in v.items() if a not in ("exemplos", "medianas_coorte")}
        print(k, json.dumps(v, ensure_ascii=False, default=str)[:900])
    print("coleta", json.dumps(rep["coleta"], ensure_ascii=False))
    print("diagnostico", json.dumps({"produtos_wikipedia_resolvidos": rep["produtos_wikipedia_resolvidos"],
                                     **rep["I_comex_diagnostico"]}, ensure_ascii=False))
    print("B_cobertura", json.dumps({k: (v.get("valor"), v.get("numerador"), v.get("denominador")) for k, v in rep["B_cobertura"].items()
                                     if isinstance(v, dict) and "valor" in v}, ensure_ascii=False))
    vazio = [k for k, v in (("Wikimedia", rep["G_declinio"]["series_wikipedia"]), ("Comex Stat", rep["registros"].get("comexstat", 0)),
                            ("backtesting", len(res))) if not v]
    if vazio:                     # sem dados, as verificações passariam sem provar nada: falha explícita
        print("AUDITORIA SEM DADOS REAIS SUFICIENTES:", ", ".join(vazio))
        sys.exit(2)
    if not rep["C_wikipedia"]["aprovado"] or rep["F_internacional"]["idioma_como_consistente"] or rep["F_internacional"]["paginas_de_pais_com_wikipedia"]:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "auditoria_real_v081.json")
