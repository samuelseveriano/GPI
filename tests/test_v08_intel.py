"""v0.8 — qualidade dos dados (gates 1–4), correspondência de produtos, ranking do Mercado Livre, PIFE, Insights Engine,
consistência fim a fim e API. Dados SINTÉTICOS de teste (report_fixture + linhas montadas aqui)."""
from __future__ import annotations

from datetime import date

import pytest

import report_fixture as F

from gpi.db import Database
from gpi.intel import fusion, insights_engine as IE, matching, mlrank, quality, semantics, service
from gpi.products import trends as T
from gpi.products.catalog import Catalog


def ins(db, src, term, d, metric, v, pid=None, unit="x", country="BR", com=1, lang="pt"):
    db.execute("INSERT OR REPLACE INTO search_observations (source,country,region,term,ref_date,period,metric,value,unit,lang,"
               "product_id,intent,commercial,collected_at) VALUES (?,?,'',?,?,'dia',?,?,?,?,?,'compra',?,?)",
               (src, country, term, d, metric, v, unit, lang, pid, com, d))


# ------------------------------------------------------------------------------------------- correspondência (Gate 2)
def test_matching_states_and_false_association():
    assert matching.match("carregador usb-c 20w")["estado"] == matching.CONFIRMED
    assert matching.match("Nintendo Switch 2 tem novos jogos")["estado"] in (matching.AMBIGUOUS, matching.NONE)
    assert matching.match("monitor")["estado"] == matching.PROBABLE                         # termo polissêmico isolado
    assert matching.match("Gameplay ao vivo com drone")["estado"] == matching.AMBIGUOUS     # entretenimento
    assert matching.match("previsão do tempo")["estado"] == matching.NONE
    v = matching.match("carregador 140w gan", target="charger+gan:20w")
    assert v["relacao_alvo"] == "variante_diferente" and v["estado_alvo"] != matching.CONFIRMED   # 20 W ≠ 140 W
    o = matching.match("capacete de moto", target="air_fryer")
    assert o["relacao_alvo"] == "outro_produto" and o["estado_alvo"] == matching.NONE
    assert matching.match("freidora de aire", "es")["nucleo"] == "air_fryer"
    assert matching.match("智能门锁", "zh")["nucleo"] == "lock"


def test_matching_holdout_meets_documented_targets():
    test = matching.evaluate(quality._load("matching_holdout.tsv"))
    assert test["casos"] >= 80 and test["precision"] >= matching.TARGETS["precision"]
    assert test["taxa_incorreta"] <= matching.TARGETS["taxa_incorreta"]


def test_youtube_market_is_language_not_query_country():
    assert matching.market_of("en", "BR")["mercado"] == "idioma:en"
    assert matching.market_of("pt-BR", "BR")["nota"] is None


# ------------------------------------------------------------------------------------------- Gate 1 / Gate 3
def test_gate1_detects_problems_and_blocks_modeling(tmp_path):
    db = Database(tmp_path / "q.sqlite")
    ins(db, "google_ads_kp", "air fryer", "2026-08-01", "volume_mensal_aprox", 100, unit="buscas/mês")
    ins(db, "google_ads_kp", "air fryer", "2026-09-01", "volume_mensal_aprox", 100, unit="buscas por mês")   # unidade misturada
    ins(db, "google_ads_kp", "Air Fryer ", "2026-09-01", "volume_mensal_aprox", 90, unit="buscas/mês")      # duplicata por grafia
    ins(db, "ml_trends", "fone", "2027-03-01", "posicao_tendencia", 3, unit="posição")                     # data futura
    ins(db, "ml_trends", "cabo", "2026-09-01", "posicao_tendencia", 77, unit="posição")                     # posição impossível
    ins(db, "rss", "x", "2026-09-01", "mencoes", 1, country="XX")                                           # país desconhecido
    g = quality.gate1(db, date(2026, 10, 15))
    bad = {c["verificacao"] for c in g["verificacoes"] if not c["ok"]}
    assert {"Uma unidade por (fonte, métrica)", "Sem datas no futuro", "Posições do ranking entre 1 e 50",
            "Sem duplicatas por grafia (maiúsculas/espaços)", "Países reconhecidos (ISO 3166-1 ou GLOBAL:<idioma>)"} <= bad
    assert g["status"] == "reprovado" and "google_ads_kp/volume_mensal_aprox" in g["excluidos_da_modelagem"]
    empty = quality.gate1(Database(tmp_path / "vazio.sqlite"), date(2026, 10, 15))
    assert empty["status"] == "aprovado"                                                    # fonte sem dados não é erro


def test_gate3_semantics():
    g = quality.gate3(_mem())
    assert g["status"] == "aprovado"
    assert not semantics.eligible("visualizacoes", "search_interest_index")               # Wikipédia não é demanda
    assert not semantics.eligible("posicao_tendencia", "search_interest_index")           # ranking não é volume
    assert semantics.eligible("posicao_tendencia", "commercial_intent_index")
    assert not semantics.eligible("videos_youtube", "opportunity_score", "youtube")       # política do YouTube


def _mem():
    import tempfile
    from pathlib import Path
    return Database(Path(tempfile.mkdtemp()) / "m.sqlite")


# ------------------------------------------------------------------------------------------- Mercado Livre
def test_ml_rank_is_weekly_positional_and_first_observation_is_new_signal(tmp_path):
    db = Database(tmp_path / "ml.sqlite")
    ins(db, "ml_trends", "cadeira gamer", "2026-10-12", "posicao_tendencia", 7, "chair+gamer", "posição")
    ins(db, "ml_trends", "cadeira gamer", "2026-10-13", "posicao_tendencia", 4, "chair+gamer", "posição")   # mesma semana
    ins(db, "ml_trends", "air fryer", "2026-10-13", "posicao_tendencia", 2, "air_fryer", "posição")
    r = mlrank.analyze(db)
    t = {x["termo"]: x for x in r["termos"]}
    assert t["cadeira gamer"]["semanas_presente"] == 1 and t["cadeira gamer"]["melhor_posicao"] == 4      # sem duplicar a semana
    assert t["cadeira gamer"]["classe"] == "NOVO SINAL COMERCIAL" and "crescimento" not in t["cadeira gamer"]
    for d, p in (("2026-10-19", 3), ("2026-10-26", 5), ("2026-11-02", 2)):
        ins(db, "ml_trends", "air fryer", d, "posicao_tendencia", p, "air_fryer", "posição")
    ins(db, "ml_trends", "cadeira gamer", "2026-11-02", "posicao_tendencia", 9, "chair+gamer", "posição")
    r = mlrank.analyze(db)
    a = r["por_produto"]["air_fryer"]
    assert a["semanas_presente"] == 4 and a["persistencia"] == 1.0 and a["classe"] == "INTERESSE RECORRENTE"
    c = {x["termo"]: x for x in r["termos"]}["cadeira gamer"]
    assert c["reaparecimentos"] == 1 and c["saidas"] == 1 and c["classe"] == "SINAL EM OBSERVAÇÃO"


def test_rank_metrics_never_produce_percent_growth():
    s = {"id": "x", "product_id": "p", "source": "ml_trends", "metric": "posicao_tendencia", "period": "dia",
         "points": [("2026-10-01", 40.0), ("2026-10-10", 45.0), ("2026-10-14", 49.0)]}
    ind = T.indicators(s, date(2026, 10, 15))
    assert ind["crescimento"] is None and "crescimento_30d" not in ind and ind["sem_crescimento_pct"]


# ------------------------------------------------------------------------------------------- PIFE + insights + Gate 8
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    db = Database(tmp_path_factory.mktemp("w") / "g.sqlite")
    F.build(db)
    cat = Catalog(db, {})
    for d, pos in (("2026-09-28", 3), ("2026-10-05", 2), ("2026-10-12", 1)):
        ins(db, "ml_trends", "air fryer", d, "posicao_tendencia", pos, cat.observe("air fryer", "ml_trends", "BR", "compra", strong=True), "x")
    ins(db, "ml_trends", "cadeira gamer", "2026-10-12", "posicao_tendencia", 5,
        cat.observe("cadeira gamer", "ml_trends", "BR", "compra", strong=True), "x")
    r = T.analyze(db, {}, F.TODAY, forecasts=True)
    prods = {p["product_id"]: p for p in Catalog(db, {}).products()}
    pay = service.compute(db, r, prods, F.TODAY)
    yield db, r, prods, pay
    db.close()


def test_fusion_layers_lineage_and_separate_indices(world):
    db, r, prods, pay = world
    P = pay["produtos"]
    af = P["air_fryer"]
    assert set(af["indices"]) == {"search_interest_index", "commercial_intent_index", "public_attention_index", "evidence_coverage",
                                  "forecast_confidence", "opportunity_score", "import_readiness"}
    assert af["indices"]["commercial_intent_index"] is not None and af["linhagem"]["total"] > 0
    assert all(i.startswith(("so:", "ms:")) for i in af["linhagem"]["ids"])
    camadas = {e["camada"] for e in af["evidencias"]} | {e["previsto"]["camada"] for e in af["evidencias"] if e.get("previsto")}
    assert "observado" in camadas
    for p in P.values():                                                # previsão só com série elegível
        for e in p["evidencias"]:
            if e.get("previsto"):
                assert e["elegibilidade"]["previsao"]


def test_new_commercial_signal_and_missing_data_is_not_low_demand(world):
    _, _, _, pay = world
    P = pay["produtos"]
    g = P.get("chair+gamer")
    assert g and g["situacao"] == "NOVO SINAL COMERCIAL" and g["indices"]["commercial_intent_index"] <= 40
    assert g["indices"]["search_interest_index"] is None and g["indices_motivos"]["search_interest_index"]
    i = next(x for x in pay["insights"] if x["produto_id"] == "chair+gamer")
    assert "não possui histórico suficiente" in i["interpretacao"] and i["confianca"] == "baixa"


def test_cross_source_confirmation_and_attention_only(world):
    _, _, _, pay = world
    af = pay["produtos"]["air_fryer"]
    assert af["confirmacao_cruzada"]["confirmado"]                                  # Google Ads + Mercado Livre
    for p in pay["produtos"].values():
        only_pub = p["indices"]["search_interest_index"] is None and p["indices"]["commercial_intent_index"] is None
        if only_pub:
            assert p["indices"]["opportunity_score"] is None                        # atenção pública não vira oportunidade


def test_insights_have_all_fields_and_observation_ids(world):
    _, _, _, pay = world
    assert pay["gates"]["6"]["status"] == "aprovado"
    for i in pay["insights"]:
        for f in IE.FIELDS:
            assert i[f] not in (None, "")
        assert set(i["perguntas"]) == {"o_que_aconteceu", "qual_a_evidencia", "o_que_significa", "qual_a_incerteza", "o_que_investigar"}
        if i["situacao"] != "EVIDÊNCIA INSUFICIENTE":
            assert i["observacoes_ids"]
        assert i["gerado_por"].endswith("(sem IA)")


def test_ranking_requires_confirmed_matching_and_classes_documented(world):
    _, _, _, pay = world
    for r in pay["ranking"]:
        if r["nivel"] == "investigar":
            assert r["opportunity_score"] >= 55 and r["evidence_coverage"] >= 40
        else:
            assert r["motivo_nivel"]
    assert {c["classe"] for c in pay["classes"]} >= set(fusion.INTERMEDIATE)


def test_end_to_end_consistency_gate8(world):
    _, _, _, pay = world
    g8 = pay["gates"]["8"]
    assert g8["status"] == "aprovado", g8


def test_decline_requires_significance():
    ev = {"frequencia": "mes", "elegibilidade": {"tendencia": True, "aceleracao": True}, "classe_serie": "declínio",
          "derivado": {"momentum": -0.2, "persistencia": 0.6, "tendencia": {"significativa": False, "direcao": "queda"}}}
    assert fusion._demand_status(ev) == "VARIAÇÃO NÃO CONFIRMADA"
    ev["derivado"]["tendencia"] = {"significativa": True, "direcao": "queda"}
    assert fusion._demand_status(ev) == "DECLÍNIO"


def test_wikipedia_attention_is_relative_to_cohort():
    series = [{"metric": "visualizacoes", "country": "GLOBAL:en", "ind": {"crescimento": g, "base_suficiente": True}}
              for g in (-0.2, -0.15, -0.1, -0.12, -0.18)]
    med = fusion.cohort_medians(series)["GLOBAL:en"]
    assert med == pytest.approx(-0.15)
    rel = (1 + 0.0) / (1 + med) - 1
    assert rel > 0.15                    # artigo estável enquanto a Wikipédia cai = atenção relativa em alta, não "declínio"


def test_api_v08_and_investigation_list(tmp_path):
    from test_api_integration import Srv
    s = Srv(tmp_path / "data")
    try:
        code, v = s.req("/api/v08/visao")
        assert code == 200 and "kpis" in v and "fontes_funcionais" in v["kpis"]
        code, q = s.req("/api/v08/qualidade")
        assert code == 200 and set(q["gates"]) >= {"1", "2", "3", "4", "6", "8"} and q["fontes_por_indicador"]
        code, m = s.req("/api/v08/metricas")
        assert code == 200 and any(x["metrica"] == "posicao_tendencia" and "não é volume" in x["nao_e"] for x in m["metricas"])
        code, d = s.req("/api/v08/dossie/produto-inexistente")
        assert code == 200 and d["situacao"] == "EVIDÊNCIA INSUFICIENTE"
        code, a = s.req("/api/v08/investigacoes", {"produto": "Cadeira gamer", "produto_id": "chair+gamer", "motivo": "novo sinal",
                                                   "documentos": "Ficha técnica\nManual"})
        assert code == 200 and a["estado"] == "Novo sinal" and a["documentos"] == ["Ficha técnica", "Manual"]
        code, b = s.req(f"/api/v08/investigacoes/{a['id']}", {"estado": "Investigação regulatória", "nota": "verificar Anatel"})
        assert b["estado"] == "Investigação regulatória" and len(b["historico"]) == 2
        code, e = s.req(f"/api/v08/investigacoes/{a['id']}", {"estado": "inventado"})
        assert code == 400
        code, st = s.req("/api/regulatorio/status")
        assert code == 200 and "titular" in st["papeis"]
    finally:
        s.stop()


def test_youtube_video_association_is_verified_by_title():
    from gpi.connectors.content import YouTube
    payload = {"items": [
        {"id": "a1", "snippet": {"title": "Air fryer Mondial vale a pena? Review completo", "defaultAudioLanguage": "pt-BR"}, "statistics": {}},
        {"id": "a2", "snippet": {"title": "MC Fulano - Clipe Oficial (ao vivo)", "defaultAudioLanguage": "pt"}, "statistics": {}},
        {"id": "a3", "snippet": {"title": "Best robot vacuum 2026 tested", "defaultAudioLanguage": "en"}, "statistics": {}},
    ]}
    rows = {r["item_id"]: r for r in YouTube.parse_videos(payload, "air_fryer", "air fryer")}
    assert rows["a1"]["product_key"] == "air_fryer" and rows["a1"]["metrics"]["mercado"] == "BR"
    assert rows["a2"]["product_key"] is None                                   # entretenimento não é associado
    assert rows["a3"]["product_key"] is None and rows["a3"]["metrics"]["mercado"] == "idioma:en"   # outro produto, outro idioma
    assert rows["a3"]["metrics"]["correspondencia"]["relacao"] == "outro_produto"
