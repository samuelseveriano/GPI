"""Revisão do PR #18 — pesquisa DIRECIONADA nas APIs, rápida × completa, estados das etapas, cobertura, nome comercial,
produtos semelhantes classificados, fornecedores candidatos com evidência, diagnóstico de fontes, Dashboard e
monitoramento a partir da pesquisa.

Todas as respostas externas aqui são SIMULADAS (FakeHttp) — nenhuma credencial real ou fictícia com formato realista é
usada. A validação com APIs reais está em scripts/real_targeted_research_v091.py (CI) e no computador do usuário."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from gpi.connectors.http import SourceError
from gpi.db import Database
from gpi.intel import decision as D
from gpi.market.content_store import ContentStore
from gpi.market.store import MarketStore
from gpi.market.sync import SyncContext
from gpi.products.catalog import Catalog
from gpi.suite import monitor as MON
from gpi.suite import naming as NM
from gpi.suite import research as RS
from gpi.suite import store as S
from gpi.suite import suppliers as SP
from gpi.suite import targeted as TG

TODAY = date(2026, 11, 5)


class Creds:
    def __init__(self, d=None):
        self.d = {k: dict(v) for k, v in (d or {}).items()}

    def get(self, k):
        return dict(self.d.get(k) or {})

    def set(self, k, v):
        self.d.setdefault(k, {}).update(v)

    def delete(self, k):
        self.d.pop(k, None)


def months(n=14, base=1000, step=90):
    out = []
    for i in range(n):
        y, m = 2025 + (9 + i) // 12, (9 + i) % 12 + 1
        out.append({"year": str(y), "month": ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
                                               "OCTOBER", "NOVEMBER", "DECEMBER"][m - 1], "monthlySearches": str(base + step * i)})
    return out


class FakeHttp:
    """Respostas SIMULADAS por endereço. `fail` = {trecho_da_url: SourceError} para simular falhas isoladas."""

    def __init__(self, fail=None, empty=()):
        self.calls, self.fail, self.empty = [], fail or {}, set(empty)

    def _resp(self, url, kw):
        for frag, err in self.fail.items():
            if frag in url:
                raise err
        if "mercadolibre.com/sites/MLB/search" in url:
            return {"results": [] if "ml" in self.empty else [
                {"id": f"MLB{i}", "title": f"Carregador GaN 65W USB-C turbo {i}", "price": 120 + i, "currency_id": "BRL",
                 "seller": {"id": 1000 + i % 3}, "permalink": f"https://produto.mercadolivre.com.br/MLB-{i}", "condition": "new",
                 "attributes": [{"id": "BRAND", "value_name": ["Baseus", "Ugreen"][i % 2]}]} for i in range(8)]}
        if "identity/v1/oauth2/token" in url:
            return {"access_token": "tok-ebay", "expires_in": 7200}
        if "item_summary/search" in url:
            return {"itemSummaries": [] if "ebay" in self.empty else [
                {"itemId": f"v1|{i}|0", "title": f"GaN charger 65W fast {i}", "price": {"value": str(20 + i), "currency": "USD"},
                 "condition": "New", "seller": {"username": f"seller{i}"}, "itemWebUrl": f"https://www.ebay.com/itm/{i}",
                 "categories": [{"categoryName": "Chargers"}], "itemLocation": {"country": "CN"}} for i in range(5)]}
        if "api.gdeltproject.org" in url:
            return {"timeline": [{"data": [{"date": f"2026{m:02d}15T000000Z", "value": 3 + m} for m in range(1, 11)]}]}
        if "youtube/v3/search" in url:
            return {"items": [{"id": {"videoId": f"vid{i}"}} for i in range(3)]}
        if "youtube/v3/videos" in url:
            return {"items": [{"id": f"vid{i}", "snippet": {"title": f"Carregador GaN 65W review {i}", "publishedAt": "2026-10-01T00:00:00Z"},
                               "statistics": {"viewCount": "100"}} for i in range(3)]}
        raise SourceError(f"endereço não simulado: {url}", "http")

    def request_json(self, url, method="GET", **kw):
        self.calls.append(url)
        return self._resp(url, kw)

    def request_text(self, url, **kw):
        self.calls.append(url)
        raise SourceError("SOAP não simulado", "http")


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.sqlite")
    Catalog(d, {}).ensure_seeded()
    S.ensure(d)
    return d


@pytest.fixture(autouse=True)
def fake_tokens(monkeypatch):
    import gpi.integrations.registry as reg
    monkeypatch.setattr(reg, "ml_token", lambda http, creds: "tok-ml")

    def gads(http, creds, path, body):
        http.calls.append("googleads:" + ",".join(body["keywordSeed"]["keywords"]))
        if getattr(http, "gads_error", None):
            raise http.gads_error
        return {"results": [{"text": body["keywordSeed"]["keywords"][0], "keywordIdeaMetrics": {"avgMonthlySearches": "1500",
                                                                                               "monthlySearchVolumes": months()}}]}
    import gpi.connectors.search as cs
    monkeypatch.setattr(cs, "gads_call", gads)


ALL = {"mercadolivre": {"access_token": "x"}, "ebay": {"client_id": "a", "client_secret": "b", "sync_token": "c"},
       "google_ads": {"refresh_token": "r", "customer_id": "1"}, "youtube": {"api_key": "k"}}


def sctx(db, http=None, creds=None):
    http = http or FakeHttp()
    c = Creds(ALL if creds is None else creds)
    ms = MarketStore(db)
    return (lambda: SyncContext(http, ms, {}, TODAY, ContentStore(db), c)), http


def rctx(db, sync_fn=None, payload=None):
    pl = payload or {"versao": "0.8.1", "produtos": {}}
    return {"payload_fn": lambda: pl, "stages_fn": lambda: D.stages(pl, db, TODAY), "ncm": None, "today": TODAY, "cfg": {},
            "sync_ctx_fn": sync_fn}


def run(db, q, sync_fn, **params):
    rid = RS.create(db, q, params)
    out = RS.run(db, rid, rctx(db, sync_fn))
    return rid, out, RS.get(db, rid)


# ================================================================================================ 1. pesquisa direcionada
def test_product_absent_from_sqlite_triggers_targeted_queries(db):
    assert not db.query("SELECT 1 FROM market_listings") and not db.query("SELECT 1 FROM search_observations")
    fn, http = sctx(db)
    rid, out, j = run(db, "carregador GaN 65W", fn, profundidade="rapida", mercado="BR")
    col = {r["id"]: r for r in out["coleta"]["resultados"]}
    assert col["mercadolivre_busca"]["estado"] == "com dados" and col["mercadolivre_busca"]["registros"] == 8
    assert col["google_ads_kp"]["estado"] == "com dados"
    assert col["ebay"]["estado"] == "não cobre o mercado" and not any("item_summary" in u for u in http.calls)   # EUA não substitui BR
    assert any("mercadolibre.com/sites/MLB/search" in u for u in http.calls)
    assert out["abas"]["marketplaces"]["ultimos_30_dias"]["anuncios"] == 8
    sellers = {r["seller"] for r in db.query("SELECT seller FROM market_listings")}
    assert all(s.startswith("h:") for s in sellers)                                     # vendedor pseudonimizado
    assert out["cobertura"]["fontes_com_evidencia"] >= 2 and out["conclusiva"]
    assert out["abas"]["demanda"]["volume_autorizado"][0]["meses"] >= 12      # dentro do período de 12 meses


def test_no_source_available_reports_concrete_impediments(db):
    fn, http = sctx(db, creds={})
    rid, out, j = run(db, "carregador GaN 65W", fn)
    st = next(s for s in j["steps"] if s["id"] == "coleta")
    assert st["estado"] == "não autorizada" and not [u for u in http.calls]
    motivos = {r["fonte"]: r["motivo"] for r in out["coleta"]["resultados"]}
    assert "Mercado Livre não conectado" in motivos["Mercado Livre — busca de anúncios"] and "Keyword Planner" in motivos["Google Ads Keyword Planner"]
    assert out["mensagem_final"] == RS.INSUFFICIENT and not out["conclusiva"] and j["status"] == "concluída — dados insuficientes"


def test_isolated_api_failure_does_not_stop_others(db):
    http = FakeHttp(fail={"mercadolibre.com": SourceError("permissão insuficiente (HTTP 403)", "restrita", status=403, cause="permissao"),
                          "item_summary": SourceError("tempo de conexão esgotado", "rede", cause="timeout")})
    fn, _ = sctx(db, http)
    rid, out, j = run(db, "carregador GaN 65W", fn, mercado="BR", comparacao=["US"], profundidade="completa")
    col = {(r["id"], r["mercado"]): r for r in out["coleta"]["resultados"]}
    assert col[("mercadolivre_busca", "BR")]["estado"] == "não autorizada" and "403" in col[("mercadolivre_busca", "BR")]["motivo"]
    assert col[("ebay", "US")]["estado"] == "indisponível" and "Tempo de conexão esgotado" in col[("ebay", "US")]["motivo"]
    assert col[("google_ads_kp", "BR")]["estado"] == "com dados"
    assert next(s for s in j["steps"] if s["id"] == "coleta")["estado"] == "concluída com dados"


def test_cache_valid_and_expired(db):
    fn, http = sctx(db)
    run(db, "carregador GaN 65W", fn)
    n1 = len(http.calls)
    _, out, _ = run(db, "carregador GaN 65W", fn)                                     # 2ª rápida: cache válido, sem chamadas
    assert len(http.calls) == n1 and all(r["estado"] in ("cache válido", "ignorada (modo rápido)", "não cobre o mercado") for r in out["coleta"]["resultados"])
    old = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
    db.execute("UPDATE research_source_runs SET at = ?", (old,))
    _, out, _ = run(db, "carregador GaN 65W", fn)
    assert len(http.calls) > n1 and any((r.get("cache") or "").startswith("expirado") for r in out["coleta"]["resultados"])
    n2 = len(http.calls)
    _, out, _ = run(db, "carregador GaN 65W", fn, atualizar=True)        # forçada logo após: < 10 min → não repete (limites da API)
    assert len(http.calls) == n2 and any("não repetida" in (r.get("motivo") or "") for r in out["coleta"]["resultados"])
    db.execute("UPDATE research_source_runs SET at = ?", ((datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds"),))
    _, out, _ = run(db, "carregador GaN 65W", fn, atualizar=True)        # 'Atualizar' ignora o cache válido (7 dias)
    assert len(http.calls) > n2 and all(r["estado"] != "cache válido" for r in out["coleta"]["resultados"])


def test_quick_vs_full_are_functionally_different(db):
    fn, http = sctx(db)
    _, quick, jq = run(db, "carregador GaN 65W", fn, profundidade="rapida", mercado="BR", comparacao=["US"])
    q_ids = {(r["id"], r["mercado"]) for r in quick["coleta"]["resultados"] if r["estado"] != "ignorada (modo rápido)"}
    assert ("youtube", "BR") not in q_ids and ("gdelt", "GLOBAL") not in q_ids and ("google_ads_kp", "US") not in q_ids
    assert {r["id"] for r in quick["coleta"]["resultados"] if r["estado"] == "ignorada (modo rápido)"} >= {"youtube", "gdelt", "msads_kp"}
    n_quick = len(http.calls)
    _, full, jf = run(db, "carregador GaN 65W", fn, profundidade="completa", mercado="BR", comparacao=["US"])
    f = {(r["id"], r["mercado"]): r for r in full["coleta"]["resultados"]}
    assert f[("google_ads_kp", "BR")]["estado"] == "cache válido"                    # reaproveita a rápida (mesmo dia)
    assert f[("google_ads_kp", "US")]["estado"] == "com dados" and f[("youtube", "BR")]["estado"] == "com dados"
    assert f[("gdelt", "GLOBAL")]["estado"] == "com dados" and f[("msads_kp", "BR")]["estado"] == "não autorizada"
    assert len(http.calls) > n_quick
    assert full["abas"]["demanda"]["comparacao_mercados"] and {s["mercado"] for s in full["abas"]["demanda"]["volume_autorizado"]} == {"BR", "US"}
    assert full["abas"]["demanda"]["noticias_gdelt"]["nota"].startswith("Atenção pública")
    assert next(s for s in jf["steps"] if s["id"] == "previsoes")["estado"] in ("concluída com dados", "concluída sem dados")
    assert next(s for s in jq["steps"] if s["id"] == "previsoes")["estado"] == "ignorada por configuração"


def test_targeted_volume_growth_gives_green_only_with_confirmed_identity(db):
    fn, _ = sctx(db)
    _, out, _ = run(db, "carregador GaN 65W", fn)
    assert out["decisao"]["cor"] == "VERDE" and out["abas"]["visao_geral"]["estagio_direto"]["estagio"] == 3
    _, out2, _ = run(db, "007 first light", fn)                                       # jogo: identificação não confirmada
    assert out2["decisao"]["cor"] != "VERDE"


def test_news_and_videos_do_not_raise_stage(db):
    fn, _ = sctx(db, creds={"youtube": {"api_key": "k"}})
    _, out, _ = run(db, "carregador GaN 65W", fn, profundidade="completa")
    c = out["coberturas"]
    assert c["contextual"]["n"] >= 2 and c["comercial"]["n"] == 0                      # GDELT/YouTube = contexto, não demanda
    assert out["cobertura"]["fontes_com_evidencia"] == 0 and out["cobertura"]["fontes_contextuais"] >= 2
    assert out["decisao"]["cor"] == "CINZA" and out["mensagem_final"] == RS.INSUFFICIENT


# ================================================================================================ 3. progresso × cobertura
def test_progress_with_skipped_and_failed_steps(db, monkeypatch):
    fn, _ = sctx(db, creds={})
    monkeypatch.setattr(RS, "_s_similar", lambda *a: (_ for _ in ()).throw(RuntimeError("falha simulada")))
    _, out, j = run(db, "carregador GaN 65W", fn)
    p = j["progresso"]
    assert p["pct"] == 100 and p["por_estado"]["falhou"] == 1 and p["por_estado"]["ignorada por configuração"] == 1
    assert p["por_estado"]["não autorizada"] == 1 and "Não indica sucesso" in p["nota"]
    assert j["status"] == "concluída com falhas" and out["mensagem_final"] == RS.INSUFFICIENT


def test_cancel_marks_remaining_steps(db):
    rid = RS.create(db, "carregador GaN 65W", {})
    RS.cancel(db, rid)
    RS.run(db, rid, rctx(db, sctx(db)[0]))
    j = RS.get(db, rid)
    assert j["status"] == "cancelada" and all(s["estado"] == "cancelada" for s in j["steps"])


# ================================================================================================ 4. nome comercial
def test_commercial_name_vs_canonical_id(db):
    d = NM.describe(db, "charger+gan:65w")
    assert d["id_canonico"] == "charger+gan:65w" and d["nome_comercial"] == "Carregador GaN 65W"
    assert d["familia"] == {"id": "charger+gan", "nome": "Carregador GaN", "categoria": "Celulares e acessórios"}
    assert d["variante"]["rotulo"] == "65W" and d["traducoes"]["en"] == "GaN charger 65W"
    _, out, _ = run(db, "carregador GaN 65W", None)
    ov = out["abas"]["visao_geral"]
    assert ov["produto"] == "Carregador GaN 65W" and ov["produto_id"] == "charger+gan:65w" and "+" not in ov["produto"]
    assert NM.pretty_token("5000mah") == "5000mAh"


# ================================================================================================ 5. semelhantes
def test_similar_products_are_classified(db):
    res = RS.similar_products(db, "charger+gan:65w", None, {}, TODAY)
    g = res["grupos"]
    assert any(i["produto_id"] == "charger+gan" for i in g["Variante da mesma família"])
    assert any(i["produto_id"] == "charger" for i in g["Produto tecnicamente semelhante"])
    cat = g["Produto da mesma categoria"]
    assert cat and all("NÃO é equivalente" in i["motivo"] for i in cat)
    assert "Similaridade visual" in res["grupos"] and "não comprova o mesmo fabricante" in " ".join(res["avisos"])


def test_visual_similarity_group(tmp_path, db):
    from test_v091_suite import img
    from gpi.suite import visual as V
    V.add_to_catalog(db, tmp_path, img(), "a", "charger+gan:65w", "charger+gan")
    V.add_to_catalog(db, tmp_path, img(fmt="JPEG", noise=4), "b", "powerbank", "powerbank")
    res = RS.similar_products(db, "charger+gan:65w", None, {}, TODAY, deep=True)
    vis = res["grupos"]["Similaridade visual"]
    assert vis and vis[0]["produto_id"] == "powerbank" and "não comprova o mesmo fabricante" in vis[0]["motivo"]


# ================================================================================================ 6. fornecedores
def test_supplier_candidates_have_traceable_evidence_and_types(db):
    from test_v091_suite import SHIP_CSV
    SP.import_shipments(db, SHIP_CSV.encode(), "embarques.csv")
    SP.upsert_company(db, {"legal_name": "Cadastro Carregadores Ltda", "country": "CN", "product_families": "carregador gan"}, "informado pelo usuário")
    db.execute("INSERT INTO anatel_registros (numero_homologacao, data_homologacao, solicitante, cnpj_solicitante, fabricante, pais_fabricante, modelo, "
               "tipo_produto, nome_comercial) VALUES ('0999', '2025-02-01', 'Importadora X', '1', 'Dongguan Gan Power Co Ltd', 'China', 'G65', "
               "'Carregador', 'Carregador GaN 65W')")
    db.execute("INSERT OR REPLACE INTO ncm_meta (k, v) VALUES ('anatel_v2_registros', '1')")      # base Anatel "carregada" (fixture)
    d = SP.discover(db, "carregador GaN 65W", family="charger+gan", product_id="charger+gan:65w", extra_terms=["GaN charger 65W"])
    by = {c["empresa"]: c for c in d["candidatos"]}
    alpha = by["Shenzhen Alpha Electronics Co Ltd"]
    assert alpha["tipo_correspondencia"] == "exportador (embarques)" and "BOL1" in alpha["correspondencias"][0]["evidencia"]
    assert alpha["comprovacao"] == "registro de embarque" and any("não comprovam que a empresa fabrica" in x for x in alpha["limitacoes"])
    assert by["Cadastro Carregadores Ltda"]["tipo_correspondencia"] == "fornecedor cadastrado" and by["Cadastro Carregadores Ltda"]["confianca"] == "baixa"
    fab = next(c for c in d["candidatos"] if c["empresa"].startswith("Dongguan"))
    assert fab["tipo_correspondencia"] == "fabricante documentado em registro regulatório" and "0999" in fab["correspondencias"][0]["evidencia"]
    assert all(c["tipo_correspondencia"] != "fabricante confirmado" for c in d["candidatos"])   # nada inferido vira confirmado
    for c in d["candidatos"]:
        assert {"empresa", "produto_relacionado", "tipo_correspondencia", "fontes", "correspondencias", "confianca", "limitacoes"} <= set(c)


# ================================================================================================ 7. diagnóstico
def test_source_diagnostics_panel(db):
    fn, _ = sctx(db, creds={"google_ads": {"refresh_token": "r", "customer_id": "1"}})
    _, out, _ = run(db, "carregador GaN 65W", fn)
    f = {r["id"]: r for r in out["fontes"]}
    assert f["mercadolivre_busca"]["estado"] == "não autorizada" and f["mercadolivre_busca"]["acao"]
    assert f["comexstat"]["motivo"].startswith("NCM ainda não validada")
    assert f["google_trends_rss"]["estado"] == "não suporta consulta direcionada"
    assert f["visual"]["motivo"] == "catálogo visual vazio" and f["visual"]["estado"] == "sem dados"
    for r in out["fontes"]:
        assert {"fonte", "capacidade", "estado", "consulta_realizada", "registros", "motivo", "acao"} <= set(r)


# ================================================================================================ 8. dashboard / 9. monitoramento
def test_monitor_from_research_and_weekly_refresh(db):
    fn, http = sctx(db)
    rid, out, _ = run(db, "carregador GaN 65W", fn)
    m = MON.from_research(db, out, rid)
    assert m["semanal"] and m["parametros"]["termos"]["en"] == "GaN charger 65W" and "mercadolivre_busca" in m["parametros"]["fontes"]
    pl = {"produtos": {}}
    r1 = MON.refresh(db, lambda: pl, lambda: D.stages(pl, db, TODAY), TODAY, fn)
    assert r1["consultas"] == 0                                                       # cache de 7 dias respeitado
    db.execute("UPDATE research_source_runs SET at = ?", ((datetime.now() - timedelta(days=8)).isoformat(timespec="seconds"),))
    n = len(http.calls)
    r2 = MON.refresh(db, lambda: pl, lambda: D.stages(pl, db, TODAY), TODAY, fn)
    assert r2["consultas"] >= 2 and len(http.calls) > n
    item = MON.listing(db)[0]
    assert item["semanal"] and item["label"] == "Carregador GaN 65W" and item["last_snapshot"]["anuncios_30d"] == 8


def test_unidentified_term_can_be_monitored(db):
    fn, _ = sctx(db)
    rid, out, _ = run(db, "kit xyzzy sem nome", fn)
    m = MON.from_research(db, out, rid)
    assert m["ref"].startswith("termo:") and MON.listing(db)[0]["semanal"]


def test_evidence_history_across_researches(db):
    fn, _ = sctx(db)
    run(db, "carregador GaN 65W", fn)
    _, out, _ = run(db, "carregador GaN 65W", fn, atualizar=True)
    assert out["abas"]["evidencias"]["pesquisas_com_evidencias_desta_entidade"] >= 1
    assert db.query("SELECT COUNT(DISTINCT evidence_id) AS n FROM research_evidence")[0]["n"] == db.query("SELECT COUNT(*) AS n FROM research_evidence")[0]["n"]


def test_monitored_schema_migration_adds_column(tmp_path):
    d = Database(tmp_path / "old.sqlite")
    d.execute("CREATE TABLE monitored (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT NOT NULL, label TEXT, "
              "created_at TEXT NOT NULL, last_checked TEXT, last_snapshot TEXT, notes TEXT, UNIQUE (kind, ref))")
    d.execute("INSERT INTO monitored (kind, ref, label, created_at) VALUES ('produto', 'lamp', 'Luminária', 't')")
    S.ensure(d)
    assert d.query("SELECT params, label FROM monitored")[0] == {"params": None, "label": "Luminária"}


def test_export_of_targeted_research(db):
    import io
    from openpyxl import load_workbook
    from gpi.suite import export as EX
    fn, _ = sctx(db)
    _, out, _ = run(db, "carregador GaN 65W", fn, profundidade="completa")
    wb = load_workbook(io.BytesIO(EX.xlsx("pesquisa", out, "x")))
    assert "Fontes e cobertura" in wb.sheetnames and "Marketplaces" in wb.sheetnames
    assert EX.pdf("pesquisa", out, "x")[:5] == b"%PDF-"


def test_plan_never_targets_trends_or_comex():
    for mode in ("rapida", "completa"):
        ids = {s for s, _m, _r in TG.plan(mode, ["BR", "US"])}
        assert not ids & {"google_trends_rss", "google_trends_bq", "comexstat", "ml_trends"}


def test_dashboard_counts_separate_demo(tmp_path):
    import json as _j
    from test_v091_suite import SHIP_CSV
    from gpi.suite.api import routes
    d = Database(tmp_path / "d.sqlite")
    Catalog(d, {}).ensure_seeded()
    SP.import_shipments(d, SHIP_CSV.encode(), "e.csv", "[DEMONSTRATIVO] exemplo")

    class Store:
        db = d

        def load_result(self, n):
            return None

        def save_result(self, n, p):
            pass

    class Sync:
        store = Store()
        creds = Creds()
        http = FakeHttp()

        def today_fn(self):
            return TODAY

        def context(self):
            raise RuntimeError("sem conectores")

    import asyncio
    import gpi.intel.api as IA
    orig = IA._payload_for_v09
    IA._payload_for_v09 = lambda db, sync, cfg: {"produtos": {}}
    try:
        r = next(x for x in routes(d, Sync(), {}, None, tmp_path) if x.path == "/api/suite/visao")
        resp = asyncio.run(r.endpoint(None))
    finally:
        IA._payload_for_v09 = orig
    v = _j.loads(resp.body)
    assert v["contagens"]["embarques"] == 0 and v["demonstrativos"]["embarques"] == 3 and v["tem_demonstrativos"]
    assert v["produtos"]["cadastrados"] >= 100 and v["produtos"]["com_evidencias_comerciais"] == 0
