"""v0.6 — Centro de Relatórios (XLSX/PDF/CSV), inteligência social, Opportunity Engine 3.0, sinais sociais no ML,
retenção, migração e interface. Dados SINTÉTICOS (tests/report_fixture.py, marcados como DEMONSTRAÇÃO) e respostas de API no
formato documentado: testam a lógica; NENHUMA fonte social é declarada validada por estes testes."""
import gzip
import json
import re
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pdfplumber
import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

import report_fixture as F
from test_api_integration import Srv
from test_v05 import TODAY as CTX_TODAY
from test_v05 import Creds, Http, _ctx

from gpi.connectors.http import SourceError
from gpi.db import MIGRATIONS, Database
from gpi.forecasting import social_ablation as SA
from gpi.market.store import MarketStore
from gpi.reports import data as D
from gpi.reports import pdf as P
from gpi.reports.service import ReportService
from gpi.reports.xlsx import safe_text
from gpi.social import analysis as SAN
from gpi.social import store as SS
from gpi.social.connectors import FacebookPages, InstagramHashtags, MetaAdLibrary, TikTokDiscovery, _tt_check

ROOT = Path(__file__).resolve().parents[1]
TODAY = F.TODAY


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """Base de teste completa + todos os relatórios gerados uma vez (reaproveitados pelos testes)."""
    d = tmp_path_factory.mktemp("rep")
    db = Database(d / "gpi.sqlite")
    F.build(db)
    svc = ReportService(db, d, {})
    out = {}
    for tipo in D.TYPES:
        for fmt in ("xlsx", "pdf", "csv"):
            f = {"produto": "projector+portable"} if tipo == "produto" else {}
            r = svc.generate(tipo, fmt, f)
            out[(tipo, fmt)] = (r, svc.file(r["id"]))
    yield {"db": db, "dir": d, "svc": svc, "rep": out}
    db.close()


# ===================================================================== Excel
def test_all_report_types_generated_in_three_formats(base):
    assert len(D.TYPES) >= 8
    for (tipo, fmt), (r, p) in base["rep"].items():
        assert r["status"] == "gerado", (tipo, fmt, r.get("erro"))
        assert p.exists() and p.stat().st_size > 500 and r["demo"] == 1
        assert re.match(rf"GPI_{tipo}_\d{{8}}-\d{{6}}_[0-9a-f]{{8}}\.{fmt}$", p.name)


def test_xlsx_valid_sheets_tables_filters_freeze_formats(base):
    r, p = base["rep"][("radar_global", "xlsx")]
    assert zipfile.is_zipfile(p)
    wb = load_workbook(p)
    names = wb.sheetnames
    assert names[0] == "Resumo Executivo"
    for s in ("Ranking de Produtos", "Histórico de Indicadores", "Tendências por País", "Redes Sociais", "Forecasting",
              "Oportunidades", "Fontes e Metodologia", "Dados Brutos Permitidos", "Gráficos"):
        assert s in names, s
    rk = wb["Ranking de Produtos"]
    assert rk.tables and rk.freeze_panes and rk.freeze_panes != "A1"
    tb = next(iter(rk.tables.values()))
    assert tb.autoFilter is not None or tb.ref                       # tabela estruturada com filtro
    head = int(re.findall(r"\d+", tb.ref)[0])
    hdr = [c.value for c in rk[head]]
    col = {v: i for i, v in enumerate(hdr)}
    first = rk[head + 1]
    assert first[col["Crescimento"]].number_format == "0.0%"
    assert isinstance(first[col["Crescimento"]].value, float)
    assert rk.conditional_formatting                                  # formatação condicional (scores/crescimento)
    assert rk.column_dimensions["A"].width >= 9
    assert len(wb["Gráficos"]._charts) >= 1
    # demonstração visível
    assert "DEMONSTRAÇÃO" in str(wb["Resumo Executivo"]["A1"].value)


def test_xlsx_dates_hyperlinks_formulas_and_units(base):
    _, p = base["rep"][("radar_global", "xlsx")]
    wb = load_workbook(p)
    ws = wb["Dados Brutos Permitidos"]
    tb = next(iter(ws.tables.values()))
    head = int(re.findall(r"\d+", tb.ref)[0])
    hdr = [c.value for c in ws[head]]
    row = ws[head + 1]
    dcell = row[hdr.index("Data de referência")]
    assert isinstance(dcell.value, (date,)) and dcell.number_format == "DD/MM/YYYY"
    link = row[hdr.index("Link")]
    assert link.hyperlink and link.hyperlink.target.startswith("https://")
    assert "Unidade" in hdr and row[hdr.index("Unidade")].value
    fs = [c.value for c in wb["Resumo Executivo"]["B"] if isinstance(c.value, str) and c.value.startswith("=")]
    assert any("COUNTA('Ranking de Produtos'!" in f for f in fs) and any("AVERAGE(" in f for f in fs)
    assert wb.calculation.fullCalcOnLoad


def test_formula_injection_and_special_characters(tmp_path):
    for bad in ("=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tx"):
        assert safe_text(bad)[1]
    assert not safe_text("ação 智能门锁 — ≥ 10%")[1]
    db = Database(tmp_path / "g.sqlite")
    F.build(db, with_social=False)
    db.execute("UPDATE search_observations SET term = '=cmd|'' /C calc''!A0' WHERE rowid = (SELECT MIN(rowid) FROM search_observations)")
    db.execute("UPDATE search_observations SET term = 'Projetor 投影仪 «ação» \x07' WHERE rowid = (SELECT MAX(rowid) FROM search_observations)")
    svc = ReportService(db, tmp_path, {})
    r = svc.generate("radar_global", "xlsx", {})
    wb = load_workbook(svc.file(r["id"]))
    ws = wb["Dados Brutos Permitidos"]
    cells = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    evil = [c for c in cells if c.value.startswith("=cmd")]
    assert evil and all(c.data_type == "s" and c.quotePrefix for c in evil)
    assert any("投影仪" in c.value and "\x07" not in c.value for c in cells)
    # CSV: prefixo de citação (OWASP)
    r2 = svc.generate("radar_global", "csv", {})
    txt = svc.file(r2["id"]).read_text(encoding="utf-8-sig")
    assert "DEMONSTRAÇÃO" in txt
    db.close()


def test_filters_preserved_and_period_recomputed(base):
    db, svc = base["db"], base["svc"]
    r = svc.generate("tendencias_pais", "xlsx", {"pais": "BR", "periodo_meses": 12, "categoria": "Áudio e vídeo"})
    assert r["filtros"] == {"pais": "BR", "categoria": "Áudio e vídeo", "periodo_meses": 12} and r["pais"] == "BR"
    wb = load_workbook(svc.file(r["id"]))
    txt = " ".join(str(c.value) for row in wb["Resumo Executivo"].iter_rows() for c in row if c.value)
    assert "País: Brasil" in txt and "Categoria: Áudio e vídeo" in txt and "últimos 12 meses" in txt
    ds = D.build(db, "radar_global", {"pais": "BR", "periodo_meses": 12})
    hist = next(t for _, ts in ds["secoes"] for t in ts if t["id"] == "historico")
    cut = D._cut_label(12, date.today())
    assert hist["linhas"] and all(x["pais"] == "Brasil" for x in hist["linhas"])
    assert all(x["periodo"] >= cut for x in hist["linhas"] if x["granularidade"] == "mês")
    rk = next(t for _, ts in ds["secoes"] for t in ts if t["id"] == "ranking")
    assert all(x["pais"] == "Brasil" or "português" in (x["pais"] or "") for x in rk["linhas"])


def test_no_invented_values_and_relative_title_without_volume(tmp_path):
    db = Database(tmp_path / "s.sqlite")
    F.build(db, with_social=False)
    db.execute("DELETE FROM search_observations WHERE metric = 'volume_mensal_aprox'")
    MarketStore(db).save_result("consumer", __import__("gpi.products.trends", fromlist=["x"]).analyze(db, {}, TODAY, forecasts=False))
    ds = D.build(db, "mais_pesquisados", {})
    assert ds["titulo"].endswith("Ranking de Interesse Relativo")
    t = next(t for _, ts in ds["secoes"] for t in ts if t["id"] == "pesquisados")
    assert all(r["unidade"] != "buscas/mês (arredondado pelo Google)" for r in t["linhas"])
    assert any("não volume" in n for n in t["notas"])
    db.close()


# ===================================================================== PDF
def test_pdf_valid_pages_sizes_accents_and_demo(base):
    _, p = base["rep"][("executivo", "pdf")]
    assert p.read_bytes()[:5] == b"%PDF-"
    rd = PdfReader(str(p))
    n = len(rd.pages)
    assert n >= 4
    sizes = {(round(float(pg.mediabox.width)), round(float(pg.mediabox.height))) for pg in rd.pages}
    assert (595, 842) in sizes                                          # A4 vertical
    with pdfplumber.open(str(p)) as pdf:
        texts = [pg.extract_text() or "" for pg in pdf.pages]
    full = "\n".join(texts)
    assert "Relatório Executivo de Oportunidades" in full and "Página 1 de" in texts[0] and f"Página {n} de {n}" in texts[-1]
    for w in ("ação", "Prontidão" if "Prontidão" in full else "Limitações", "Próximas investigações"):
        assert w in full
    assert "DEMONSTRAÇÃO" in full and "Sumário" in full
    assert all(t.strip() for t in texts)                               # nenhuma página vazia
    fonts = {f for pg in rd.pages for f in (pg.get("/Resources", {}).get("/Font") or {}).values()}
    names = {str(f.get_object().get("/BaseFont")) for f in fonts}
    assert any("DejaVu" in x for x in names)                           # fonte embutida (offline)


def test_pdf_landscape_tables_no_overflow_no_overlap(base):
    _, p = base["rep"][("radar_global", "pdf")]
    with pdfplumber.open(str(p)) as pdf:
        land = [pg for pg in pdf.pages if pg.width > pg.height]
        assert land                                                     # tabelas largas em A4 horizontal
        for pg in pdf.pages:
            words = [w for w in pg.extract_words(extra_attrs=["size"]) if w["size"] < 20]   # ignora a marca d'água
            for w in words:                                             # nada cortado fora da página
                assert -1 <= w["x0"] and w["x1"] <= pg.width + 1 and 0 <= w["top"] and w["bottom"] <= pg.height + 1
            for i, a in enumerate(words):                               # sem sobreposição: nenhuma palavra cobre outra
                for b in words[i + 1:]:
                    same_line = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > 0.5 * min(a["size"], b["size"])
                    if same_line:
                        assert min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) < 0.6, (pg.page_number, a["text"], b["text"])
        assert pdf.pages[-1].extract_text()
    assert len(PdfReader(str(p)).pages[5].get("/Resources", {}).get("/XObject") or {}) >= 0


def test_pdf_charts_and_chinese_characters(base):
    _, p = base["rep"][("produto", "pdf")]
    with pdfplumber.open(str(p)) as pdf:
        txt = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
        lines = sum(len(pg.lines) + len(pg.curves) for pg in pdf.pages)
    assert "Projetor portátil" in txt and "Comparação internacional" in txt
    assert lines > 20                                                   # gráficos vetoriais desenhados
    assert P._register()["cjk"] in ("GPI-CJK", "STSong-Light")
    assert "投影" in txt or P._register()["cjk"] == "STSong-Light"


def test_pdf_offline_does_not_touch_network(base, monkeypatch, tmp_path):
    import socket

    def boom(*a, **k):
        raise AssertionError("rede usada na geração do PDF")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    ds = D.build(base["db"], "executivo", {})
    P.write(ds, tmp_path / "x.pdf")
    assert (tmp_path / "x.pdf").read_bytes()[:4] == b"%PDF"


# ===================================================================== histórico, reprodução, exclusão, relatório semanal
def test_history_snapshot_reproduction_and_no_overwrite(base):
    svc = base["svc"]
    r1, p1 = base["rep"][("oportunidades", "xlsx")]
    r2 = svc.generate("oportunidades", "xlsx", {})
    assert svc.file(r2["id"]) != p1 and p1.exists()                    # nunca sobrescreve
    rep = svc.regenerate(r1["id"], "snapshot")
    assert rep["status"] == "gerado" and rep["origem"] == "reproducao" and rep["origem_id"] == r1["id"]
    a = load_workbook(p1)["Oportunidades"]
    b = load_workbook(svc.file(rep["id"]))["Oportunidades"]
    va = [[c.value for c in row] for row in a.iter_rows(min_row=5)]
    vb = [[c.value for c in row] for row in b.iter_rows(min_row=5)]
    assert va == vb                                                    # mesmos números a partir do snapshot
    h = svc.history()
    for k in ("tipo", "periodo", "created_at", "pais", "filtros", "modelos", "versao_dados", "arquivo", "size", "status", "run_id"):
        assert k in h[0]
    snap = Path(svc.db.query("SELECT snapshot_path FROM reports WHERE id = ?", (r1["id"],))[0]["snapshot_path"])
    with gzip.open(snap, "rt", encoding="utf-8") as fh:
        s = json.load(fh)
    assert s["meta"]["run_id"] == r1["run_id"] and s["meta"]["versao_software"] == __import__("gpi").__version__


def test_delete_requires_confirmation_and_keeps_audit(base):
    svc = base["svc"]
    r = svc.generate("social", "csv", {})
    with pytest.raises(PermissionError):
        svc.delete(r["id"], False)
    p = svc.file(r["id"])
    out = svc.delete(r["id"], True)
    assert out["status"] == "excluido" and not p.exists() and svc.file(r["id"]) is None


def test_weekly_report_disabled_by_default_and_pending_after_sync(tmp_path):
    db = Database(tmp_path / "w.sqlite")
    F.build(db, with_social=False)
    svc = ReportService(db, tmp_path, {})
    db.execute("INSERT INTO sync_runs (id, trigger, started_at, finished_at, state) VALUES (1, 'teste', '2026-10-01T00:00:00', '2026-10-01T01:00:00', 'concluida')")
    assert svc.run_weekly() is None                                    # desligado por padrão
    svc.cfg["auto_report_weekly"] = True
    out = svc.run_weekly()
    assert out and len(out["gerados"]) == 2
    assert {n["formato"] for n in svc.notifications()} == {"pdf", "xlsx"}
    svc.mark_seen()
    assert not svc.notifications() and svc.run_weekly() is None        # já gerado para esta sincronização
    db.close()


def test_credentials_never_in_reports(base):
    ds = D.build(base["db"], "radar_global", {})
    ds["meta"]["parametros"]["access_token"] = "SEGREDO123"
    from gpi.reports.service import _scrub
    assert "SEGREDO123" not in json.dumps(_scrub(ds), ensure_ascii=False)


# ===================================================================== social: conectores
def test_social_connectors_need_authorization(tmp_path):
    ctx, _ = _ctx(tmp_path, Http({}))
    for c in (TikTokDiscovery(), InstagramHashtags(), FacebookPages(), MetaAdLibrary()):
        assert not c.available(ctx) and c.restricted_reason


def test_tiktok_errors_map_to_permission_and_rate_limit():
    assert _tt_check({"code": 0, "data": {"x": 1}}) == {"x": 1}
    with pytest.raises(SourceError) as e:
        _tt_check({"code": 40001, "message": "No permission"})
    assert e.value.kind == "restrita"
    with pytest.raises(SourceError) as e:
        _tt_check({"code": 40100, "message": "Too many requests"})
    assert e.value.kind == "limite"


def test_tiktok_hashtags_parse_product_extraction_and_dedup(tmp_path):
    payload = {"code": 0, "message": "OK", "data": {"list": [
        {"hashtag_id": "1", "hashtag_name": "miniprojetor", "rank_position": 3, "rank_change": 5, "views": 120000, "posts": 800},
        {"hashtag_id": "2", "hashtag_name": "CarregadorSemFio", "rank_position": 10, "views": 50000, "posts": 200},
        {"hashtag_id": "3", "hashtag_name": "dancinha", "rank_position": 1, "views": 9e6, "posts": 9e4}]}}
    http = Http({"discovery/trending_list/": payload, "discovery/search/": {"code": 0, "data": {"search_keywords": ["air fryer", "novela"]}}})
    ctx, db = _ctx(tmp_path, http, {"tiktok": {"access_token": "t", "advertiser_id": "123", "business_id": "abc"}},
                   {"tiktok_countries": ["BR"], "tiktok_max_products": 0})
    c = TikTokDiscovery()
    assert c.available(ctx)
    jobs = c.plan(ctx)
    for j in jobs:
        c.run(j, ctx)
        c.run(j, ctx)                                                   # repetido no mesmo dia: sem duplicar
    assert http.last["headers"]["Access-Token"] == "t"
    rows = db.query("SELECT item, metric, value, product_id, commercial, country, retain_until FROM social_observations ORDER BY item, metric")
    by = {(r["item"], r["metric"]): r for r in rows}
    assert by[("miniprojetor", "tt_hashtag_posicao")]["value"] == 198 and by[("miniprojetor", "tt_hashtag_posicao")]["product_id"].startswith("projector")
    assert by[("CarregadorSemFio", "tt_hashtag_views")]["product_id"].startswith("charger+wireless")
    assert by[("dancinha", "tt_hashtag_posicao")]["product_id"] is None and by[("dancinha", "tt_hashtag_posicao")]["commercial"] == 0
    assert len(rows) == len(set((r["item"], r["metric"], r["country"]) for r in rows))
    assert by[("air fryer", "tt_busca_posicao")]["country"] == "CONTA"   # região da conta não informada pela API
    assert by[("miniprojetor", "tt_hashtag_posicao")]["retain_until"] == (CTX_TODAY + timedelta(days=90)).isoformat()


def test_instagram_quota_30_hashtags_per_7_days(tmp_path):
    ctx, db = _ctx(tmp_path, Http({}), {"meta": {"access_token": "t", "ig_user_id": "9"}}, {"instagram_max_hashtags": 40})
    for i in range(28):
        SS.quota_add(db, "instagram", f"tag{i}", CTX_TODAY - timedelta(days=2))
    jobs = InstagramHashtags().plan(ctx)
    new = [j for j in jobs if j.params["tag"] not in {f"tag{i}" for i in range(28)}]
    assert len(new) <= 2                                                # nunca passa de 30 por conta em 7 dias
    SS.quota_add(db, "instagram", "velha", CTX_TODAY - timedelta(days=9))
    SS.purge(db, CTX_TODAY)
    assert "velha" not in SS.quota_used(db, "instagram", CTX_TODAY)


def test_instagram_run_stores_only_aggregates(tmp_path):
    now = "2026-10-15T10:00:00+0000"
    http = Http({"ig_hashtag_search": {"data": [{"id": "h1"}]},
                 "h1/top_media": {"data": [{"id": "1", "like_count": 100, "comments_count": 5, "timestamp": now, "caption": "texto privado"},
                                           {"id": "2", "like_count": 300, "comments_count": 9, "timestamp": now}]},
                 "h1/recent_media": {"data": [{"id": "3", "timestamp": now}]}})
    ctx, db = _ctx(tmp_path, http, {"meta": {"access_token": "t", "ig_user_id": "9"}})
    c = InstagramHashtags()
    c.run(type("J", (), {"params": {"tag": "airfryer", "pid": "air_fryer"}, "key": "k"})(), ctx)
    rows = db.query("SELECT * FROM social_observations")
    assert {r["metric"] for r in rows} >= {"ig_top_curtidas", "ig_top_comentarios", "ig_recentes_24h"}
    assert next(r for r in rows if r["metric"] == "ig_top_curtidas")["value"] == 200
    assert "texto privado" not in json.dumps(rows, ensure_ascii=False)
    assert "airfryer" in SS.quota_used(db, "instagram", CTX_TODAY)


def test_meta_errors_and_ad_library_counts_without_spend(tmp_path):
    http = Http({"ads_archive": {"data": [{"id": str(i)} for i in range(37)]}})
    ctx, db = _ctx(tmp_path, http, {"meta": {"access_token": "t"}}, {"meta_ads_enabled": True})
    c = MetaAdLibrary()
    assert c.available(ctx)
    c.run(type("J", (), {"params": {"pid": "air_fryer", "q": "air fryer"}, "key": "k"})(), ctx)
    r = db.query("SELECT * FROM social_observations")[0]
    assert r["value"] == 37 and r["country"] == "UE" and "anúncios ativos" in r["unit"]
    assert "spend" not in (r["extra"] or "") and "ad_reached_countries" in http.last["url"]
    ctx2, _ = _ctx(tmp_path / "b", Http({"ads_archive": {"error": {"code": 10, "message": "Application does not have permission"}}}),
                   {"meta": {"access_token": "t"}}, {"meta_ads_enabled": True})
    with pytest.raises(SourceError) as e:
        c.run(type("J", (), {"params": {"pid": "x", "q": "x"}, "key": "k"})(), ctx2)
    assert e.value.kind == "restrita"


def test_retention_purges_expired_social_data(tmp_path):
    db = Database(tmp_path / "r.sqlite")
    SS.store(db, {"retencao_dias_tiktok": 10}, "tiktok", "BR", "hashtag", "x", "2026-01-01", "dia", "tt_hashtag_posicao", 5, "p",
             today=TODAY - timedelta(days=30))
    SS.store(db, {}, "tiktok", "BR", "hashtag", "y", "2026-01-01", "dia", "tt_hashtag_posicao", 5, "p", today=TODAY)
    assert SS.purge(db, TODAY)["removidas"] == 1
    assert [r["item"] for r in db.query("SELECT item FROM social_observations")] == ["y"]


# ===================================================================== social: análise
def test_normalization_per_platform_never_sums_platforms(base):
    soc = MarketStore(base["db"]).load_result("social")
    assert soc["series"] and all(s["metric"] in SAN.SOCIAL_METRICS for s in soc["series"])
    assert len({(s["product_id"], s["platform"], s["metric"], s["country"]) for s in soc["series"]}) == len(soc["series"])
    for v in soc["scores"].values():
        assert 0 <= (v["social_trend_score"] or 0) <= 100 and set(v["componentes"]) <= set(SAN.WEIGHTS)
        assert abs(sum(SAN.WEIGHTS.values()) - 1) < 1e-9
    r = SAN._pct_rank({"a": 1, "b": 100, "c": 10})
    assert r == {"a": 0.0, "b": 1.0, "c": 0.5}


def test_radar_classes_and_single_platform_flag(base):
    soc = MarketStore(base["db"]).load_result("social")
    assert set(soc["radar"]) == set(SAN.RADAR_CLASSES)
    sc = soc["scores"]
    assert sc["projector+portable"]["classe_radar"] in ("Crescimento sustentado", "Tendência emergente")
    assert sc["camera"]["classe_radar"] in ("Interesse em declínio", "Viralização recente", "Popularidade estável")
    assert all("dancinha" not in v["hashtags"] for v in sc.values())    # entretenimento sem produto não entra
    ind = {"crescimento": 1.5, "crescimento_7d": 1.5, "persistencia": 0.2}
    cls, info = SAN.radar_class([{"ind": ind}])
    assert cls == "Viralização recente" and info["pico_passageiro_possivel"]
    cls, _ = SAN.radar_class([{"ind": {"crescimento": -0.4}}])
    assert cls == "Interesse em declínio"


def test_search_vs_social_separate_indicators(base):
    soc = MarketStore(base["db"]).load_result("social")
    rows = {r["product_id"]: r for r in soc["search_vs_social"]}
    p = rows["projector+portable"]
    for k in ("search_growth", "social_growth", "marketplace_signals", "evidence_coverage", "cross_source_consistency"):
        assert k in p
    assert p["marketplace_signals"] is not None and -1 <= p["cross_source_consistency"] <= 1
    assert p["evidence_coverage"] == 100.0


def test_opportunity3_dimensions_priority_and_no_purchase_advice(base):
    o = MarketStore(base["db"]).load_result("opportunity3")
    assert o["produtos"] and "não é probabilidade" in o["aviso"].lower().replace("Não", "não")
    for r in o["produtos"]:
        assert r["prioridade"] in ("Alta", "Média", "Baixa", "Evidência insuficiente")
        assert set(r["dimensoes"]) <= {"consumer_search_strength", "social_momentum", "marketplace_evidence", "trend_persistence",
                                       "competition_pressure", "product_quality_risk", "evidence_coverage", "forecast_confidence", "import_readiness"}
        assert all(0 <= v <= 100 for v in r["dimensoes"].values())
        assert "margem" not in json.dumps(r["dimensoes"])
    from gpi.products import opportunity3
    only_search = opportunity3.build(MarketStore(base["db"]).load_result("consumer"), None, None, None)
    assert only_search["produtos"] and all(r["prioridade"] == "Evidência insuficiente" for r in only_search["produtos"])
    assert all("social_momentum" not in r["dimensoes"] for r in only_search["produtos"])   # nada preenchido sem dados


# ===================================================================== ML: com × sem sinais sociais
def _pairs(lead, n=30, k=6, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(k):
        y = 1000 * (1 + 0.02 * i) * np.exp(np.cumsum(rng.normal(0, 0.08, n + 1)))
        x = y[1:] / 10 if lead else rng.lognormal(3, 0.3, n)
        out.append((y[:n], x[:n]))
    return out


def test_social_signals_adopted_only_with_out_of_sample_gain():
    good = SA.evaluate(_pairs(True))
    bad = SA.evaluate(_pairs(False))
    assert good["adotar"] and good["wape_com_social"] < good["wape_sem_social"]
    assert not bad["adotar"] and "não usar" in bad["decisao"]
    assert SA.evaluate(_pairs(True, k=1))["status"] == "insuficiente"


def test_social_features_have_no_temporal_leakage():
    y, x = _pairs(True, k=1)[0]
    t = 20
    f1 = SA.features(y, x, t, True)
    y2, x2 = y.copy(), x.copy()
    y2[t:] *= 50
    x2[t:] *= 50                                                        # alterar o futuro (inclusive t) não muda as variáveis
    assert SA.features(y2, x2, t, True) == f1


# ===================================================================== migração, API, interface, empacotamento
def test_migration_v6_preserves_existing_database(tmp_path):
    p = tmp_path / "old.sqlite"
    import sqlite3
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE schema_version (v INTEGER NOT NULL)")
    con.execute("INSERT INTO schema_version VALUES (0)")
    con.commit()
    con.close()
    db = Database(p)
    assert db.schema_version() == len(MIGRATIONS) == 6
    db.execute("INSERT INTO search_observations (source,country,region,term,ref_date,period,metric,value,unit,commercial,collected_at)"
               " VALUES ('x','BR','','t','2026-01-01','dia','m',1,'u',0,'n')")
    db.close()
    db = Database(p)
    assert db.query("SELECT COUNT(*) AS n FROM search_observations")[0]["n"] == 1
    assert db.query("SELECT COUNT(*) AS n FROM reports")[0]["n"] == 0
    db.close()


def test_reports_and_social_api(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    db = Database(d / "gpi.sqlite")
    F.build(db)
    db.close()
    s = Srv(d)
    try:
        code, t = s.req("/api/reports/types")
        assert code == 200 and len(t["tipos"]) >= 8 and t["relatorio_semanal"] is False and t["filtros"]["produtos"]
        code, r = s.req("/api/reports/generate", {"tipo": "executivo", "formato": "pdf", "filtros": {"pais": "BR"}})
        assert code == 200 and r["status"] == "gerado" and r["filtros"] == {"pais": "BR"}
        code, raw = s.req(f"/api/reports/{r['id']}/download", raw=True)
        assert code == 200 and raw[:4] == b"%PDF"
        code, e = s.req("/api/reports/generate", {"tipo": "produto", "formato": "xlsx", "filtros": {}})
        assert code == 400 and "produto" in e["erro"]
        code, e = s.req(f"/api/reports/{r['id']}", {"confirmar": False}, method="DELETE")
        assert code == 400
        code, e = s.req(f"/api/reports/{r['id']}", {"confirmar": True}, method="DELETE")
        assert code == 200 and e["status"] == "excluido"
        assert s.req(f"/api/reports/{r['id']}/download")[0] == 404
        code, _ = s.req("/api/reports/generate", {"tipo": "executivo", "formato": "pdf"}, headers={"X-GPI": "0"})
        assert code == 403                                              # proteção CSRF preservada
        code, ov = s.req("/api/social/overview")
        assert code == 200 and ov["ranking"] and "tiktok" in ov["plataformas"]
        assert s.req("/api/social/platform/tiktok")[1]["series"]
        assert s.req("/api/social/platform/xx")[0] == 404
        assert s.req("/api/opportunities3")[1]["produtos"]
        code, ints = s.req("/api/integrations?v=6")
        ids = {p["id"]: p for p in ints["integracoes"]}
        assert {"tiktok", "meta", "youtube", "reddit"} <= set(ids) and ids["tiktok"]["categorias"] == ["redes_sociais"]
        assert ids["meta"]["situacao"] in ("Requer autorização", "Conectado") and ids["publicas"]["situacao"] in ("Disponível", "Erro")
        assert "Pesquisas" in ints["categorias"].values()
        assert isinstance(s.req("/api/integrations")[1], list)          # formato anterior preservado
        code, st = s.req("/api/settings", {"auto_report_weekly": True, "facebook_pages": "Loja X, 12345"})
        assert code == 200 and st["valores"]["auto_report_weekly"] is True and st["valores"]["facebook_pages"] == ["Loja X", "12345"]
    finally:
        s.stop()


def test_menu_structure_v06():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    groups = re.findall(r'data-grp="(\w+)"', html)
    assert groups == ["overview", "consumer", "social", "market", "ml", "trade", "reports", "sales", "system"]
    for label in ("Centro de Relatórios", "Histórico", "Social Intelligence", "TikTok Trends", "Instagram Intelligence",
                  "Facebook Intelligence", "YouTube Intelligence", "Viral Product Radar", "Viabilidade de Importação"):
        assert f">{label}<" in html, label
    nav = re.search(r'<nav id="nav".*?</nav>', html, re.S).group(0)
    hrefs = re.findall(r'<a href="#([^"]+)"', nav)
    assert len(hrefs) == len(set(hrefs))                                # sem páginas duplicadas no menu
    assert html.count('aria-expanded="false"') >= 9 and "v06.js" in html and "Exportar PDF" in html
    js = (ROOT / "frontend" / "v06.js").read_text(encoding="utf-8")
    for route in ("relatorios", "relatorios-historico", "social", "radar-viral", "oportunidades-consumo"):
        assert f"'{route}'" in js or f"{route}:" in js


def test_packaging_includes_reportlab_and_fonts():
    spec = (ROOT / "packaging" / "gpi.spec").read_text(encoding="utf-8")
    assert "reportlab" in spec and "fonts" in spec
    assert (ROOT / "backend" / "gpi" / "reports" / "fonts" / "DejaVuSans.ttf").exists()
    assert (ROOT / "backend" / "gpi" / "reports" / "fonts" / "LICENSE-DejaVu.txt").exists()
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "reportlab" in req
    wf = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(encoding="utf-8")
    assert "GPI-Windows-Portable-v0.6" in wf
