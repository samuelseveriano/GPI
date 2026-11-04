"""Serviço da v0.8: executa a sequência completa e grava o resultado ("intel08") para dashboard, dossiê e relatórios.

Uma única fonte de números (Gate 8): dashboard, dossiê e relatórios leem o MESMO resultado gravado.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta

from . import fusion, insights_engine as IE, investigations, quality, semantics

RESULT = "intel08"


def fontes_por_indicador(db, products: dict) -> list[dict]:
    """Quais fontes com dados alimentam cada indicador — e por que as demais não (inconsistência A da v0.7.1)."""
    have = defaultdict(int)
    for r in db.query("SELECT source, metric, COUNT(*) AS n FROM search_observations GROUP BY source, metric"):
        have[(r["source"], r["metric"])] += r["n"]
    for r in db.query("SELECT source, COUNT(*) AS n FROM market_series GROUP BY source"):
        m = quality.STORED_METRIC.get((r["source"], None))
        if m:
            have[(r["source"], m)] += r["n"]
    for r in db.query("SELECT source, COUNT(*) AS n FROM content_items GROUP BY source"):
        have[(r["source"], "videos_youtube" if r["source"] == "youtube" else "mencoes")] += r["n"]
    used = defaultdict(set)
    for p in products.values():
        for e in p["evidencias"]:
            used[e["metrica"]].add(e["fonte"])
    out = []
    for ind_id, ind in semantics.INDICATORS.items():
        el, nel = [], []
        for (src, met), n in sorted(have.items()):
            nm = semantics.SOURCES.get(src, {}).get("nome", src)
            if semantics.eligible(met, ind_id, src):
                el.append({"fonte": src, "nome": nm, "metrica": met, "registros": n,
                           "ligada_a_produtos": src in used.get(met, set()) or (met == "posicao_tendencia")})
            else:
                t = semantics.metric_type(met)
                motivo = ("política da plataforma: exibida separadamente" if semantics.SOURCES.get(src, {}).get("combinavel") is False
                          else f"{semantics.TYPE_LABEL.get(t, 'métrica')}: {semantics.TYPE_NOT.get(t, '')}" if t
                          else "métrica fora do catálogo semântico")
                nel.append({"fonte": src, "nome": nm, "metrica": met, "registros": n, "motivo": motivo})
        out.append({"indicador": ind_id, "nome": ind["nome"], "rotulo": ind["rotulo"], "descricao": ind["descricao"],
                    "fontes_elegiveis": el, "fontes_nao_elegiveis": nel})
    return out


def international(products: dict) -> list[dict]:
    """Só quando há a MESMA métrica e fonte com série elegível em dois mercados."""
    out = []
    for p in products.values():
        by = defaultdict(dict)
        for e in p["evidencias"]:
            if e["elegibilidade"].get("tendencia") and e["derivado"].get("momentum") is not None and e["pais"] in ("BR", "US", "GLOBAL:pt", "GLOBAL:en"):
                by[(e["fonte"], e["metrica"])][e["pais"]] = e
        for (src, met), m in by.items():
            pair = [k for k in ("BR", "US") if k in m] if met != "visualizacoes" else [k for k in ("GLOBAL:pt", "GLOBAL:en") if k in m]
            if len(pair) == 2:
                a, b = m[pair[0]], m[pair[1]]
                out.append({"produto_id": p["produto_id"], "produto": p["identificacao"]["produto"], "fonte": a["fonte_nome"],
                            "indicador": a["indicador"], "mercado_a": a["mercado"], "variacao_a": a["derivado"]["momentum"],
                            "mercado_b": b["mercado"], "variacao_b": b["derivado"]["momentum"],
                            "nota": "mesma fonte e métrica nos dois mercados" + ("; idioma ≠ país" if met == "visualizacoes" else "")})
    return sorted(out, key=lambda x: -abs((x["variacao_a"] or 0) - (x["variacao_b"] or 0)))


def gate8(db, payload: dict) -> dict:
    """Consistência fim a fim: banco → fusão → insights → dashboard/relatórios."""
    P = payload["produtos"]
    checks = []
    fams = {pid.split(":")[0] for pid in P}
    db_n = 0
    for f in fams:
        db_n += db.query("SELECT COUNT(*) AS n FROM search_observations WHERE product_id = ? OR product_id LIKE ?", (f, f + ":%"))[0]["n"]
    lin = sum((p.get("linhagem") or {}).get("total") or 0 for pid, p in P.items() if ":" not in pid)
    lin_var = sum((p.get("linhagem") or {}).get("total") or 0 for pid, p in P.items() if ":" in pid and pid.split(":")[0] not in P)
    checks.append({"verificacao": "Observações ligadas a produtos (banco = linhagem)", "ok": db_n == lin + lin_var,
                   "banco": db_n, "linhagem": lin + lin_var})
    rk = {r["produto_id"] for r in payload["ranking"]}
    checks.append({"verificacao": "Ranking contém só produtos analisados", "ok": rk <= set(P)})
    ins = {i["produto_id"] for i in payload["insights"]}
    checks.append({"verificacao": "Um insight por produto analisado", "ok": ins == set(P)})
    k = payload["kpis"]
    checks.append({"verificacao": "KPIs = contagens da fusão", "ok": k["produtos_analisados"] == len(P)
                   and k["emergentes"] == sum(1 for p in P.values() if p["situacao"] in ("EMERGENTE", "NOVO SINAL COMERCIAL"))
                   and k["crescimento_consistente"] == sum(1 for p in P.values() if p["situacao"] in ("CRESCIMENTO CONSISTENTE", "ACELERAÇÃO"))})
    st = db.query("SELECT COUNT(*) AS n FROM source_status WHERE state = 'funcional'")[0]["n"]
    checks.append({"verificacao": "Fontes funcionais = situação gravada das fontes", "ok": k["fontes_funcionais"] == st})
    return {"gate": 8, "nome": "Consistência fim a fim", "status": "aprovado" if all(c["ok"] for c in checks) else "reprovado",
            "verificacoes": checks}


def compute(db, consumer: dict, catalog_products: dict, today: date | None = None) -> dict:
    t0 = time.time()
    today = today or date.today()
    fu = fusion.build(db, consumer, catalog_products, today)
    P = fu["produtos"]
    insights = [IE.insight(p) for p in P.values()]
    insights.sort(key=lambda i: (-(P[i["produto_id"]]["indices"].get("opportunity_score") or -1), i["produto"]))
    ranking = IE.investigate_rank(P)
    groups = IE.groups(P)
    recent = (today - timedelta(days=45)).isoformat()

    def recent_ev(p):
        for e in p["evidencias"]:
            per = (e.get("periodo") or "").split(" a ")[-1]
            if per and per != "—" and per >= recent[:len(per)]:
                return True
        return False
    monitored = sum(1 for p in catalog_products.values() if p.get("level") == "produto")
    st_rows = db.query("SELECT source, state, last_success FROM source_status")
    last = db.query("SELECT finished_at FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    demand_cov = sum(1 for p in P.values() if p["indices"]["search_interest_index"] is not None
                     or p["indices"]["commercial_intent_index"] is not None)
    kpis = {"produtos_monitorados": monitored, "produtos_analisados": len(P),
            "produtos_com_dados_recentes": sum(1 for p in P.values() if recent_ev(p)),
            "com_interesse_comercial": sum(1 for p in P.values() if p["indices"]["commercial_intent_index"] is not None),
            "emergentes": sum(1 for p in P.values() if p["situacao"] in ("EMERGENTE", "NOVO SINAL COMERCIAL")),
            "crescimento_consistente": sum(1 for p in P.values() if p["situacao"] in ("CRESCIMENTO CONSISTENTE", "ACELERAÇÃO")),
            "em_investigacao": investigations.active_count(db),
            "fontes_funcionais": sum(1 for r in st_rows if r["state"] == "funcional"),
            "fontes_com_dados": len({e["fonte"] for p in P.values() for e in p["evidencias"]}),
            "cobertura_real": round(100 * demand_cov / monitored, 1) if monitored else 0.0,
            "cobertura_real_nota": "produtos com evidência elegível de pesquisa ou sinal comercial ÷ produtos monitorados",
            "ultima_atualizacao": last[0]["finished_at"] if last else None}
    radar = defaultdict(list)
    for p in P.values():
        if p["radar"]:
            radar[p["radar"]].append({"produto_id": p["produto_id"], "produto": p["identificacao"]["produto"], "situacao": p["situacao"],
                                      "fontes": p["confirmacao_cruzada"]["fontes_independentes_positivas"]})
    alerts = []
    for p in P.values():
        for a in p["alertas"]:
            alerts.append({**a, "produto_id": p["produto_id"], "produto": p["identificacao"]["produto"]})
    for c in fu["gate1"]["verificacoes"]:
        if not c["ok"]:
            alerts.append({"tipo": "qualidade dos dados", "detalhe": f"{c['verificacao']}: {c['detalhe']}", "produto": "—"})
    payload = {"versao": "0.8", "gerado_em": today.isoformat(), "kpis": kpis, "produtos": P, "insights": insights,
               "ranking": ranking, "grupos": groups, "contagens": {k: len(v) for k, v in groups.items()},
               "clusters": IE.clusters(P), "radar": dict(radar), "alertas": alerts[:300],
               "comparacao_internacional": international(P), "mercado_livre": fu["mercado_livre"],
               "fontes_por_indicador": fontes_por_indicador(db, P), "classes": fu["classes"],
               "gates": {"1": fu["gate1"], "4": fu["gate4"], "6": IE.gate6(insights)},
               "fontes": [{"id": r["source"], "estado": r["state"], "ultima_coleta_ok": r["last_success"]} for r in st_rows],
               "aviso": "Scores priorizam investigação; não são probabilidade de sucesso. Ausência de dados não é baixa demanda."}
    payload["gates"]["8"] = gate8(db, payload)
    payload["segundos"] = round(time.time() - t0, 2)
    return payload


def gates_full(db, payload: dict) -> dict:
    """Gates 2 e 3 (mais caros) sob demanda, junto com os já calculados."""
    g = dict(payload.get("gates") or {})
    g["2"] = quality.gate2(db)
    g["3"] = quality.gate3(db)
    return dict(sorted(g.items()))
