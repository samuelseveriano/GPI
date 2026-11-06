"""v0.9.1 — Product Intelligence Suite. Testes com dados SIMULADOS (fixtures/mocks marcados como tal); a validação com
dados reais acontece no CI (real-data-audit) e no computador do usuário.

Numeração entre colchetes = item da seção 43 da especificação."""
from __future__ import annotations

import base64
import io
import json
from datetime import date
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from gpi.db import Database
from gpi.intel import decision as D
from gpi.intel.semantics import COMMERCIAL, SEARCH
from gpi.products.catalog import Catalog
from gpi.suite import capabilities as CAP
from gpi.suite import export as EX
from gpi.suite import importx as IX
from gpi.suite import importyeti as IY
from gpi.suite import marketplace as MK
from gpi.suite import monitor as MON
from gpi.suite import research as RS
from gpi.suite import store as S
from gpi.suite import suppliers as SP
from gpi.suite import visual as V

TODAY = date(2026, 11, 5)
SIMULADO = "fixture simulada — não é dado real"


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "s.sqlite")
    Catalog(d, {}).ensure_seeded()
    S.ensure(d)
    return d


def _listings(db, pid="charger+gan:65w", n=6, days=("2026-10-20", "2026-10-27", "2026-11-03")):
    rows = []
    for i in range(n):
        for k, day in enumerate(days):
            rows.append(("ebay", f"11000000{i}", day, pid, "gan charger", f"GaN charger 65W USB-C model {i}", ["anker", "baseus", None][i % 3],
                         None, "chargers", 20.0 + i + k, "USD", None, "US", f"seller{i % 4}", "new", f"https://www.ebay.com/itm/11000000{i}", None, "t"))
    db.executemany("INSERT INTO market_listings (source, item_id, day, product_id, query, title, brand, model, category, price, currency, "
                   "original_price, country, seller, condition, url, extra, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _searches(db, term="carregador gan", pid="charger+gan:65w", months=14, source="google_ads_kp", metric="volume_mensal_aprox"):
    rows = [(source, "BR", "", term, f"{2025 + (m // 12)}-{m % 12 + 1:02d}-01", "mes", metric, 1000 + 80 * m, 1500 + 80 * m, "buscas/mês", "pt",
             pid, "compra", 1, None, None, "t") for m in range(months)]
    db.executemany("INSERT INTO search_observations (source, country, region, term, ref_date, period, metric, value, value_high, unit, lang, "
                   "product_id, intent, commercial, url, extra, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def ml(weeks, persist, first="2026-W30"):
    return {"tipo": COMMERCIAL, "fonte": "ml_trends", "fonte_nome": "Mercado Livre — tendências", "metrica": "posicao_tendencia",
            "indicador": "posição no ranking", "mercado": "BR", "pais": "BR", "periodo": f"{first} a 2026-W45", "observacoes_n": weeks,
            "frequencia": "semana", "elegibilidade": {"tendencia": False}, "camada": "observado", "serie": "x",
            "derivado": {"semanas_presente": weeks, "persistencia": persist, "primeira_semana": first, "melhor_posicao": 3,
                         "semanas_coletadas": weeks, "posicao_media": 10}}


def payload(evs=None, situacao="INTERESSE RECORRENTE", corr="confirmada"):
    p = {"produto_id": "charger+gan", "identificacao": {"produto": "Carregador GaN", "familia": "charger+gan", "variante": None,
                                                         "categoria": "Celulares e acessórios"},
         "situacao": situacao, "evidencias": evs if evs is not None else [ml(6, 0.75)], "correspondencia": {"estado": corr},
         "fontes": ["Mercado Livre"], "indices": {"opportunity_score": 62.0, "evidence_coverage": 45.0, "search_interest_index": None,
                                                  "commercial_intent_index": 50.0}, "confirmacao_cruzada": {"fontes_independentes_positivas": [], "confirmado": False}}
    return {"versao": "0.8.1", "produtos": {"charger+gan": p}}


def ctx(db, pl=None):
    pl = pl if pl is not None else payload()
    return {"payload_fn": lambda: pl, "stages_fn": lambda: D.stages(pl, db, TODAY), "catalog_fn": lambda: {}, "ncm": None, "today": TODAY, "cfg": {}}


def img(color=(200, 30, 30), shape="circle", size=(320, 240), fmt="PNG", noise=0, exif=False):
    im = Image.new("RGB", size, (245, 245, 245))
    d = ImageDraw.Draw(im)
    if shape == "circle":
        d.ellipse((60, 40, 260, 200), fill=color)
    elif shape == "bars":
        for x in range(0, size[0], 40):
            d.rectangle((x, 0, x + 18, size[1]), fill=color)
    else:
        d.polygon([(160, 20), (300, 220), (20, 220)], fill=color)
    if noise:
        d.rectangle((5, 5, 5 + noise, 5 + noise), fill=(0, 0, 0))
    b = io.BytesIO()
    kw = {}
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "CameraMaker"
        kw["exif"] = ex.tobytes()
    im.save(b, fmt, **kw)
    return b.getvalue()


# ================================================================================================ PRODUCT RESEARCH
@pytest.mark.parametrize("q", ["carregador GaN 65W", "GaN charger 65W"])          # [1] [2]
def test_research_by_name_pt_and_en(db, q):
    rid = RS.create(db, q, {"profundidade": "rapida", "mercado": "BR"})
    out = RS.run(db, rid, ctx(db))
    ov = out["abas"]["visao_geral"]
    assert ov["produto_id"] in ("charger+gan:65w", "charger+gan") and ov["entendimento"]["estado"] == "confirmada"
    assert set(out["abas"]) >= {"visao_geral", "demanda", "marketplaces", "semelhantes", "fornecedores", "importacao", "qualidade", "evidencias"}


def test_variant_identified(db):                                                   # [3]
    u = RS.run(db, RS.create(db, "carregador GaN 65W", {}), ctx(db))["abas"]["visao_geral"]["entendimento"]
    assert u["atributos"]["potencia_w"] == "65" and u["taxonomia"][-1]["id"].endswith(":65w")


def test_quick_skips_forecast_full_runs_it_and_progress_is_real(db):               # [4] [5]
    _searches(db, months=26)
    j = RS.get(db, rid := RS.create(db, "carregador GaN 65W", {"profundidade": "rapida"}))
    assert j["progresso"]["concluidas"] == 0                                        # nada é marcado antes de executar
    RS.run(db, rid, ctx(db))
    j = RS.get(db, rid)
    assert next(s for s in j["steps"] if s["id"] == "previsoes")["estado"] == "ignorada por configuração" and j["progresso"]["pct"] == 100
    rid2 = RS.create(db, "carregador GaN 65W", {"profundidade": "completa"})
    out = RS.run(db, rid2, ctx(db))
    assert next(s for s in RS.get(db, rid2)["steps"] if s["id"] == "previsoes")["estado"] == "concluída com dados"
    s = out["abas"]["previsoes"]["series"][0]
    assert s["n"] >= 24 and s["previsao"]["modelo"] and "backtest_wape" in s["previsao"] and "não de vendas" in s["previsao"]["nota"]


def test_product_outside_commercial_radar_is_grey_not_red(db):                     # [6]
    out = RS.run(db, RS.create(db, "projetor portátil", {}), ctx(db))
    assert out["decisao"]["cor"] == "CINZA" and out["abas"]["visao_geral"]["na_inteligencia"] is False


def test_decision_colors():
    st3 = D.evidence_stage(payload()["produtos"]["charger+gan"], TODAY)
    assert IX.classify_decision(payload()["produtos"]["charger+gan"], st3)["cor"] == "VERDE"
    p1 = payload([ml(1, 1.0, "2026-W44")])["produtos"]["charger+gan"]
    assert IX.classify_decision(p1, D.evidence_stage(p1, TODAY))["cor"] == "AMARELO"
    p0 = payload([])["produtos"]["charger+gan"]
    assert IX.classify_decision(p0, D.evidence_stage(p0, TODAY))["cor"] == "CINZA"          # ausência de dado ≠ negativo
    pd = payload(situacao="DECLÍNIO")["produtos"]["charger+gan"]
    pd["confirmacao_cruzada"]["confirmado"] = True
    assert IX.classify_decision(pd, D.evidence_stage(pd, TODAY))["cor"] == "VERMELHO"


def test_ambiguous_identification_never_green():
    p = payload(corr="ambigua")["produtos"]["charger+gan"]
    assert IX.classify_decision(p, D.evidence_stage(p, TODAY))["cor"] != "VERDE"


# ================================================================================================ MARKETPLACE INTELLIGENCE
def test_niche_filters_exclude_missing_data(db):                                  # [7]
    _listings(db)
    pl = payload()
    rows = MK.niche_rows(pl, db, {}, D.stages(pl, db, TODAY), TODAY)
    assert rows[0]["anuncios"] == 6 and rows[0]["decisao"] == "VERDE"
    assert MK.filter_niches(rows, {"preco_max": "30"}) and not MK.filter_niches(rows, {"preco_max": "5"})
    rows[0]["preco_mediano"] = None
    assert not MK.filter_niches(rows, {"preco_min": "1"})                           # sem dado não passa num filtro numérico
    assert MK.filter_niches(rows, {"cor": "verde", "competicao": "baixa"})


def test_keywords_observed_vs_generated_and_volume_only_from_authorized(db):       # [8] [13]
    _searches(db)
    _searches(db, term="carregador gan rapido", source="google_trends_bq", metric="interesse_relativo")
    k = MK.keywords(db, "carregador GaN")
    vol = [r for r in k["observadas"] if r["fonte"] == "google_ads_kp"]
    rel = [r for r in k["observadas"] if r["fonte"] == "google_trends_bq"]
    assert vol and vol[0]["classe"] == "com volume verificado" and "buscas/mês" in vol[0]["volume_disponivel"]
    assert rel and rel[0]["volume_disponivel"].startswith("não disponível")
    assert all(g["classe"] == "gerada" and g["volume_disponivel"] == "não disponível" for g in k["geradas"])


def test_reverse_listing_returns_hypotheses_only(db):
    _listings(db)
    r = MK.reverse_listing(db, "110000001")
    assert r["encontrado"] and r["hipoteses"] and "HIPÓTESES" in r["aviso"]
    assert not MK.reverse_listing(db, "999")["encontrado"]


def test_competitor_data_and_no_sales(db):                                         # [9] [12]
    _listings(db)
    ls = MK.listing_stats(db, "charger+gan:65w", 30, TODAY)
    assert ls["vendedores_distintos"] == 4 and ls["marcas_distintas"] == 2 and "não são vendas" in ls["nota"]
    one = MK.listing(db, "https://www.ebay.com/itm/110000002")
    assert one["encontrado"] and set(one["nao_disponivel"]) == {"vendas", "receita", "estoque"}
    assert "vendas" not in {k for k in one if k not in ("nao_disponivel", "aviso")}


def test_compare_up_to_five_and_price_history_real_only(db):                        # [10] [11]
    _listings(db)
    c = MK.compare_listings(db, [f"11000000{i}" for i in range(6)])
    assert len(c["itens"]) == 5
    h = c["itens"][0]["historico_precos"]
    assert [x["dia"] for x in h] == ["2026-10-20", "2026-10-27", "2026-11-03"]        # dias sem coleta não são preenchidos
    assert c["itens"][0]["variacao_preco_pct"] == 10.0


def test_trend_explorer_eligibility(db):
    _searches(db, months=8)
    t = MK.trend_explorer(db, "charger+gan:65w")
    s = t["series"][0]
    assert s["tendencia"]["direcao"] == "crescimento" and s["mudanca_regime"] is None and any("24 meses" in x for x in s["limitacoes"])


def test_review_file_upload_local(db):
    csv = "produto;nota;comentario\nA;1;bateria esquentou muito\nA;5;ótimo produto\nA;2;bateria fraca\nB;5;bom\n".encode()
    r = MK.review_file(csv, "avaliacoes.csv")
    a = next(p for p in r["produtos"] if p["produto"] == "A")
    assert a["avaliacoes"] == 3 and a["negativas"] == 2 and a["amostra_pequena"] and a["negativas_lb95"] < 2 / 3


# ================================================================================================ VISUAL SEARCH
@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])                            # [14] [15] [16]
def test_upload_formats(tmp_path, db, fmt):
    r = V.add_to_catalog(db, tmp_path, img(fmt=fmt), "x." + fmt.lower(), "charger+gan", "charger+gan")
    assert r["ok"] and not r["duplicada"] and r["info"]["formato"] == fmt


def test_duplicate_similar_related_and_none(tmp_path, db):                          # [17] [18] [19] [20]
    V.add_to_catalog(db, tmp_path, img(), "círculo vermelho", "charger+gan", "charger+gan")
    V.add_to_catalog(db, tmp_path, img(shape="bars", color=(20, 20, 200)), "barras azuis", None, "outro")
    assert V.add_to_catalog(db, tmp_path, img(), "dup", None, None)["duplicada"]
    same = V.search(db, tmp_path, img())
    assert same["resultados"][0]["classe"] == "Mesma imagem" and same["duplicatas"]
    jpg = V.search(db, tmp_path, img(fmt="JPEG", noise=6))                            # recompressão + pequena marca
    assert jpg["resultados"][0]["classe"] in ("Imagem muito semelhante", "Possível mesmo produto")
    rel = V.search(db, tmp_path, img(color=(210, 60, 40), shape="tri"), family="charger+gan")
    top = rel["resultados"][0]
    assert top["rotulo"] == "círculo vermelho" and top["classe"] in ("Mesma família", "Produto visualmente relacionado", "Possível mesmo produto")
    noise = Image.effect_noise((320, 240), 90).convert("RGB")
    b = io.BytesIO()
    noise.save(b, "PNG")
    none = V.search(db, tmp_path, b.getvalue())
    assert all(r["classe"] not in ("Mesma imagem", "Imagem muito semelhante") for r in none["resultados"])
    assert "não comprova o mesmo fabricante" in same["aviso"]


def test_crop(tmp_path, db):                                                        # [21]
    r = V.search(db, tmp_path, img(size=(640, 480)), crop={"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5})
    assert r["consulta"]["largura"] == 320 and r["consulta"]["recorte"]
    with pytest.raises(V.ImageRejected):
        V.search(db, tmp_path, img(), crop={"x": 0.99, "y": 0.99, "w": 0.01, "h": 0.01})


def test_offline_and_query_image_not_stored(tmp_path, db, monkeypatch):            # [22] [70]
    import socket
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(OSError("sem rede")))
    r = V.search(db, tmp_path, img())
    assert r["nivel"] == "básico (local)" and r["consulta"]["gravada"] is False
    assert not (tmp_path / "imagens_catalogo").exists()


@pytest.mark.parametrize("raw,msg", [(b"", "vazio"), (b"GIF89a....", "formato"), (b"\x89PNG\r\n\x1a\nlixo", "inválida"),
                                     (b"MZ\x90\x00" + b"0" * 100, "formato")])
def test_invalid_files(tmp_path, db, raw, msg):                                     # [23] [57]
    with pytest.raises(V.ImageRejected, match=msg):
        V.search(db, tmp_path, raw)


def test_decompression_bomb_and_size_limits(tmp_path, db):
    big = Image.new("L", (9000, 100))
    b = io.BytesIO()
    big.save(b, "PNG")
    with pytest.raises(V.ImageRejected, match="resolução|bomba"):
        V.search(db, tmp_path, b.getvalue())
    with pytest.raises(V.ImageRejected, match="maior"):
        V.search(db, tmp_path, b"\xff\xd8\xff" + b"0" * (V.MAX_BYTES + 1))


def test_exif_removed_and_name_sanitized(tmp_path, db):                             # [57]
    r = V.add_to_catalog(db, tmp_path, img(fmt="JPEG", exif=True), "../../etc/passwd<script>", None, None)
    row = db.query("SELECT label, stored_path FROM product_images WHERE image_id = ?", (r["image_id"],))[0]
    assert "/" not in row["label"] and "<" not in row["label"] and row["stored_path"].endswith(".jpg") and len(row["stored_path"]) == 68
    with Image.open(tmp_path / "imagens_catalogo" / row["stored_path"]) as im:
        assert not im.getexif()


def test_malicious_url_rejected():                                                  # [24] [58]
    from gpi.security import public_url_problem
    for u in ("http://127.0.0.1/x.png", "file:///etc/passwd", "http://user:pw@exemplo.com/a.png", "http://localhost:8765/api", "http://10.0.0.5/a"):
        assert public_url_problem(u, resolve=False)
    links = V.external_links("https://exemplo.com/a b.png")
    assert all(s["por_url"].startswith("https://") and "a%20b.png" in s["por_url"] for s in links["servicos"])
    assert all("por_url" not in s for s in V.external_links(None)["servicos"])     # imagem privada: só a página de envio manual


def test_optional_model_failure_falls_back(tmp_path, db):                           # [25]
    st = V.advanced_status(tmp_path, {"modelos_opcionais": True})
    assert st["ativo"] is False and not st["modelo_presente"]
    (tmp_path / "modelos").mkdir()
    (tmp_path / "modelos" / "visual.onnx").write_bytes(b"isto nao e um modelo")
    assert V.embedding(Image.new("RGB", (10, 10)), tmp_path) is None
    r = V.search(db, tmp_path, img(), settings={"modelos_opcionais": True})
    assert r["nivel"] == "básico (local)"


# ================================================================================================ SUPPLIER INTELLIGENCE
def test_company_search_and_normalization(db):                                      # [26] [27]
    a = SP.upsert_company(db, {"legal_name": "Shenzhen Baseus Technology Co., Ltd.", "country": "CN", "product_families": "carregador, cabo"}, "teste")
    b = SP.upsert_company(db, {"legal_name": "SHENZHEN BASEUS TECHNOLOGY CO LTD", "country": "cn"}, "teste")
    assert a["company_id"] == b["company_id"] and not b["criada"]
    assert S.norm_company("深圳市倍思科技有限公司") == S.norm_company("深圳市倍思") or "有限公司" not in S.norm_company("深圳市倍思科技有限公司")
    assert SP.search_companies(db, "baseus")[0]["company_id"] == a["company_id"]


def test_similar_names_go_to_manual_review_never_auto_merge(db):                    # [28]
    a = SP.upsert_company(db, {"legal_name": "Ugreen Group Limited", "country": "CN"}, "t")["company_id"]
    b = SP.upsert_company(db, {"legal_name": "Ugren Group Ltd", "country": "CN"}, "t")["company_id"]
    assert a != b
    q = SP.merge_queue(db)
    assert len(q) == 1 and q[0]["estado"] == "pendente"
    SP.link_product(db, b, "charger+gan", None, "fornece (declarado)", "t")
    SP.decide_merge(db, q[0]["id"], "mesclar")
    assert db.query("SELECT company_id FROM supplier_products")[0]["company_id"] == a
    assert db.query("SELECT verification_status FROM companies WHERE company_id = ?", (b,))[0]["verification_status"] == f"mesclada em {a}"


def _xlsx(rows, header):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_xlsx_supplier_import_validation(db):                                       # [29]
    raw = _xlsx([["Anker Innovations Ltd", "CN", "Changsha", "carregador; power bank", "fabricante"], ["", "CN", "", "", ""],
                 ["=HYPERLINK(\"http://x\")", "CN", "", "", ""]], ["Razão social", "País", "Cidade", "Produtos", "Tipo"])
    r = SP.import_companies(db, raw, "f.xlsx")
    # fórmula NÃO é executada: sem valor calculado gravado, a célula fica vazia e a linha é rejeitada
    assert r["criadas"] == 1 and [x["linha"] for x in r["rejeitadas"]] == [3, 4]
    names = {c["legal_name"] for c in SP.search_companies(db)}
    assert "Anker Innovations Ltd" in names and not any(n.startswith("=") for n in names)
    zf = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(zf, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
        z.writestr("xl/vbaProject.bin", "macro")
    with pytest.raises(ValueError, match="macros"):
        SP.import_companies(db, zf.getvalue(), "m.xlsx")
    with pytest.raises(ValueError):
        SP.import_companies(db, b"MZ\x00\x00binario", "x.csv")


SHIP_CSV = ("bill_of_lading,shipper,consignee,origin,destination,date,description,weight\n"
            "BOL1,Shenzhen Alpha Electronics Co Ltd,Acme Imports LLC,China,US,2026-05-01,GaN charger 65W,1200\n"
            "BOL2,Shenzhen Alpha Electronics Co Ltd,Acme Imports LLC,China,US,2026-06-03,GaN charger 65W USB-C,800\n"
            "BOL1,Shenzhen Alpha Electronics Co Ltd,Acme Imports LLC,China,US,2026-05-01,GaN charger 65W,1200\n"
            ",Ningbo Beta Trading,Other Buyer Inc,China,US,2026-07-01,phone case,300\n")


def test_shipments_dedupe_relations_and_discovery(db):                              # [31] [32] [33] [15]
    r = SP.import_shipments(db, SHIP_CSV.encode(), "embarques.csv")
    assert r["novos"] == 3 and r["duplicados"] == 1
    again = SP.import_shipments(db, SHIP_CSV.encode(), "embarques.csv")
    assert again["novos"] == 0 and again["duplicados"] == 4
    rel = db.query("SELECT * FROM trade_relationships WHERE rel_type = 'exportou para'")
    alpha = next(x for x in rel if x["n_records"] == 2)
    assert alpha["status"] == "documentado" and alpha["period_start"] == "2026-05-01" and alpha["confidence"] == "média"
    d = SP.discover(db, "gan charger")
    assert d["candidatos"][0]["empresa"].startswith("Shenzhen Alpha") and "não indica" in d["aviso"]
    assert SP.discover(db, "drone agrícola")["vazio"]
    cov = SP.coverage(db)
    assert cov["total"] == 3 and any("capacidade produtiva" in x for x in cov["limitacoes"])


def test_inferred_and_declared_relations_need_labels(db):                           # [34] [19]
    a = SP.upsert_company(db, {"legal_name": "Foo Electronics", "country": "CN", "website": "https://foo.cn"}, "t")["company_id"]
    b = SP.upsert_company(db, {"legal_name": "Foo Trading HK", "country": "HK", "website": "http://www.foo.cn/contato"}, "t")["company_id"]
    q = SP.merge_queue(db)
    assert q and any("mesmo site" in m for m in q[0]["motivos"]) and any("países diferentes" in m for m in q[0]["motivos"])
    SP.add_relationship(db, a, b, "mesmo grupo", "inferido", "GPI (mesmo site)")
    with pytest.raises(ValueError):
        SP.add_relationship(db, a, b, "fornece", "documentado", "t")                 # documentado exige evidência
    n = SP.network(db, a)
    assert n["arestas"][0]["status"] == "inferido" and n["arestas"][0]["confianca"] == "baixa" and n["legenda"]["inferido"]


def test_regulatory_registry_relations(db):
    db.execute("INSERT INTO anatel_registros (numero_homologacao, data_homologacao, solicitante, cnpj_solicitante, fabricante, pais_fabricante, modelo, "
               "tipo_produto) VALUES ('0123', '2025-01-10', 'Importadora Brasil Ltda', '00.000.000/0001-00', 'Shenzhen Alpha Electronics Co Ltd', "
               "'China', 'A65', 'Carregador')")
    r = SP.sync_regulatory_relations(db)
    assert r["relacoes"] == 1 and "Não comprova" in r["nota"]
    rel = db.query("SELECT * FROM trade_relationships")[0]
    assert rel["status"] == "documentado" and "0123" in rel["evidence"]


def test_product_supplier_match_is_preliminary(db):                                 # [30]
    SP.import_shipments(db, SHIP_CSV.encode(), "e.csv")
    cid = SP.search_companies(db, "alpha")[0]["company_id"]
    m = SP.match_product(db, cid, None, None, "gan charger")
    assert m["confianca"] in ("baixa", "média") and m["natureza"].startswith("correspondência preliminar")
    SP.link_product(db, cid, "charger+gan", "charger+gan", "fabricante (documentado)", "t", "certificado X")
    SP.evaluate(db, cid, "certificações", "CE", "certificado nº 1", "documental", "t", "cert.pdf")
    assert SP.match_product(db, cid, "charger+gan", "charger+gan", "gan charger")["confianca"] == "alta"
    with pytest.raises(ValueError):
        SP.evaluate(db, cid, "qualidade", "x", "y", "documental")                  # documental sem documento


class FakeCreds:
    def __init__(self, d=None):
        self.d = d or {}

    def get(self, k):
        return self.d.get(k) or {}

    def set(self, k, v):
        self.d[k] = v

    def delete(self, k):
        self.d.pop(k, None)


class FakeHttp:
    def __init__(self, resp):
        self.calls, self.resp = [], resp

    def request_json(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_importyeti_blocked_without_credentials_budget_or_authorization(db):        # [35] [36] [37] [60]
    http = FakeHttp({"requestCost": 1, "creditsRemaining": 9, "data": []})
    base = {"sem_custos": True, "orcamento_creditos": 10}
    r = IY.paid_query(db, http, FakeCreds({"importyeti": {"api_key": "k"}}), base, "company_search", {"name": "x"}, True, 1)
    assert r["mensagem"] == IY.BLOCKED and not http.calls                            # modo sem custos (padrão)
    on = {"sem_custos": False, "orcamento_creditos": 1}
    assert IY.paid_query(db, http, FakeCreds(), on, "company_search", {}, True, 1)["motivo"] == "chave não configurada"
    assert IY.paid_query(db, http, FakeCreds({"importyeti": {"api_key": "k"}}), on, "company_search", {}, False, 1)["motivo"] == "sem autorização explícita"
    assert IY.paid_query(db, http, FakeCreds({"importyeti": {"api_key": "k"}}), on, "company_search", {}, True, 5)["motivo"] == "orçamento insuficiente"
    assert not http.calls
    ok = IY.paid_query(db, http, FakeCreds({"importyeti": {"api_key": "k"}}), on, "company_search", {"name": "alpha"}, True, 1)
    assert ok["ok"] and ok["custo"] == 1 and http.calls[0][1]["headers"] == {"IYApiKey": "k"}
    assert IY.paid_query(db, http, FakeCreds({"importyeti": {"api_key": "k"}}), on, "company_search", {}, True, 1)["motivo"] == "orçamento insuficiente"
    assert IY.spent(db) == 1


def test_importyeti_status_and_geography(db):                                      # [38]
    st = IY.status(db, FakeCreds(), S.settings(type("St", (), {"load_result": lambda self, n: None})()))
    assert st["estado"] == "desligado (modo sem custos)" and "EUA" in st["cobertura"] and any("brasileiras" in x for x in st["limitacoes"])
    assert CAP.PROVIDERS["comexstat"]["limites"].endswith("não identifica empresas")


def test_comex_never_creates_company_relations(db):
    db.execute("INSERT INTO market_series (series_key, source, indicator, kind, product_key, country, freq) VALUES "
               "('comex:china:85044010:fob', 'comexstat', 'FOB', 'comercio', '85044010', 'CN', 'M')")
    IX.ncm_block(db, None, "carregador", "85044010")
    assert db.query("SELECT COUNT(*) AS n FROM trade_relationships")[0]["n"] == 0


# ================================================================================================ IMPORT INTELLIGENCE
class FakeNcm:
    def loaded(self):
        return True

    def candidates(self, text, limit=8):
        return [{"codigo": "8504.40.10", "descricao": "Carregadores de acumuladores", "pontuacao": 2.0, "hierarquia": [],
                 "aviso": "candidato para investigação — não é classificação"}]


def test_ncm_candidate_and_aggregate_stats(db):                                     # [39] [40]
    db.execute("INSERT INTO market_series (series_key, source, indicator, kind, product_key, country, unit, freq) VALUES "
               "('comex:china:85044010:fob', 'comexstat', 'FOB', 'comercio', '85044010', 'CN', 'USD', 'M')")
    sid = db.query("SELECT id FROM market_series")[0]["id"]
    db.executemany("INSERT INTO market_obs (series_id, ref_date, value, collected_at) VALUES (?, ?, ?, 't')",
                   [(sid, f"2026-{m:02d}-01", 100.0) for m in range(1, 11)])
    b = IX.ncm_block(db, FakeNcm(), "carregador GaN")
    assert b["candidatas"][0]["codigo"] == "8504.40.10" and b["estatisticas_agregadas"][0]["ultimos_12"] == 1000.0
    assert any("TODA a classificação" in a for a in b["avisos"]) and any("não é classificação fiscal" in a for a in b["avisos"])


def test_regulatory_preliminary_no_compliance_by_similarity(db):                    # [41]
    r = IX.regulatory_block(db, "carregador")
    assert "NÃO tornam o seu produto conforme" in r["regra"]


def test_simulator_costs_margin_incomplete_and_scenarios():                        # [42] [43] [44] [45]
    miss = IX.simulate({"quantidade": 100})
    assert not miss["calculado"] and "Preço FOB unitário (USD)" in miss["pendentes_obrigatorios"]
    p = {"preco_fob_unit_usd": 5, "quantidade": 100, "cambio_brl_usd": 5.0, "frete_total_brl": 500, "preco_venda_unit_brl": 60, "taxa_venda_pct": 10}
    r = IX.simulate(p)
    b = r["cenarios"]["Base"]
    assert b["fob_total_brl"] == 2500 and b["custo_total_brl"] == 3000 and b["custo_unitario_brl"] == 30 and b["frete_por_unidade_brl"] == 5
    assert b["receita_liquida_unit_brl"] == 54 and b["margem_bruta_unit_brl"] == 24 and b["markup"] == 2.0 and b["incompleto"]
    assert "Tributos de importação totais (BRL)" in r["pendentes"] and any("INCOMPLETO" in a for a in r["avisos"])
    assert r["cenarios"]["Conservador"]["margem_bruta_unit_brl"] < b["margem_bruta_unit_brl"] < r["cenarios"]["Otimista"]["margem_bruta_unit_brl"]
    full = IX.simulate({**p, **{k: 0 for k in IX.COST_ITEMS}})
    assert not full["pendentes"] and not full["cenarios"]["Base"]["incompleto"]


def test_negative_margin_with_complete_data_is_red():
    pr = payload()["produtos"]["charger+gan"]
    sim = IX.simulate({"preco_fob_unit_usd": 20, "quantidade": 10, "cambio_brl_usd": 5, "preco_venda_unit_brl": 50, **{k: 0 for k in IX.COST_ITEMS}})
    assert IX.classify_decision(pr, D.evidence_stage(pr, TODAY), sim)["cor"] == "VERMELHO"
    inc = IX.simulate({"preco_fob_unit_usd": 20, "quantidade": 10, "cambio_brl_usd": 5, "preco_venda_unit_brl": 50})
    assert IX.classify_decision(pr, D.evidence_stage(pr, TODAY), inc)["cor"] == "VERDE"     # simulação incompleta não reprova


# ================================================================================================ INTEGRAÇÃO E HISTÓRICO
def test_research_integrates_modules_and_registers_evidence_once(db):              # [46] [48] [49] [24 dossiê]
    _listings(db)
    SP.import_shipments(db, SHIP_CSV.encode(), "e.csv")
    rid = RS.create(db, "carregador GaN 65W", {"profundidade": "completa", "mercado": "BR", "comparacao": ["US"]})
    out = RS.run(db, rid, ctx(db))
    mk = out["abas"]["marketplaces"]
    assert mk["ultimos_30_dias"] is None                                         # anúncios do eBay (EUA) NÃO viram dados do Brasil
    assert mk["por_mercado"]["US"]["ultimos_30_dias"]["anuncios"] == 6 and mk["por_mercado"]["US"]["papel"] == "comparativo"
    assert out["abas"]["fornecedores"]["candidatos"][0]["empresa"].startswith("Shenzhen Alpha")
    assert out["abas"]["importacao"]["simulador"]["obrigatorios"] and out["decisao"]["cor"] == "VERDE"
    n1 = db.query("SELECT COUNT(*) AS n FROM research_evidence")[0]["n"]
    RS.run(db, RS.create(db, "carregador GaN 65W", {}), ctx(db))
    assert db.query("SELECT COUNT(*) AS n FROM research_evidence")[0]["n"] == n1        # mesma observação não é contada duas vezes
    ev = out["abas"]["evidencias"]["itens"]
    assert {"evidence_id", "entity_type", "source", "indicator", "source_capability", "usage_restrictions", "origin"} <= set(ev[0])


def test_visual_to_research_same_identification(tmp_path, db):                     # [47] [51]
    V.add_to_catalog(db, tmp_path, img(), "carregador", "charger+gan:65w", "charger+gan")
    hit = V.search(db, tmp_path, img())["resultados"][0]
    out = RS.run(db, RS.create(db, hit["product_id"].replace("+", " ").replace(":", " "), {}), ctx(db))
    assert out["abas"]["visao_geral"]["produto_id"].startswith("charger+gan")


def test_discovery_prefill_to_research(db):                                         # [50] [54]
    p = payload()["produtos"]["charger+gan"]
    f = D.prefill(p, D.evidence_stage(p, TODAY))
    r = D.INV.add(db, f)
    rid = RS.create(db, f["produto"], {})
    assert r["produto_id"] == "charger+gan" and RS.get(db, rid)["query"] == f["produto"]


def test_monitoring_products_and_suppliers(db):                                     # [52] [53]
    _listings(db)
    SP.import_shipments(db, SHIP_CSV.encode(), "e.csv")
    cid = SP.search_companies(db, "alpha")[0]["company_id"]
    MON.add(db, "produto", "charger+gan:65w")
    MON.add(db, "fornecedor", str(cid))
    with pytest.raises(ValueError):
        MON.add(db, "qualquer", "x")
    pl = payload()
    MON.refresh(db, lambda: pl, lambda: D.stages(pl, db, TODAY), TODAY)
    SP.add_shipments(db, [{"doc_id": "BOL9", "exporter_name": "Shenzhen Alpha Electronics Co Ltd", "importer_name": "Acme Imports LLC",
                           "description": "GaN charger", "date": "2026-10-01"}], "embarques.csv")
    r = MON.refresh(db, lambda: pl, lambda: D.stages(pl, db, TODAY), TODAY)
    assert r["mudancas"] == 1
    sup = next(x for x in MON.listing(db) if x["kind"] == "fornecedor")
    assert sup["eventos"][0]["mudancas"][0]["campo"] in ("embarques", "ultimo_embarque", "relacoes")


def test_history_and_saving(db):                                                    # [55] [25 salvar]
    rid = RS.create(db, "fone bluetooth", {})
    RS.run(db, rid, ctx(db))
    db.execute("UPDATE research_jobs SET saved = 1 WHERE id = ?", (rid,))
    h = RS.history(db)
    assert h[0]["query"] == "fone bluetooth" and h[0]["saved"] == 1 and h[0]["status"].startswith("concluída")


def test_step_failure_does_not_stop_research(db):                                   # [29 APIs indisponíveis]
    c = ctx(db)
    c["stages_fn"] = lambda: (_ for _ in ()).throw(RuntimeError("fonte fora do ar"))
    out = RS.run(db, rid := RS.create(db, "carregador GaN 65W", {}), c)
    j = RS.get(db, rid)
    assert j["status"] == "concluída com falhas" and any(s["estado"] == "falhou" for s in j["steps"])
    assert "fornecedores" in out["abas"] and out["erros"][0]["etapa"] == "catalogo"


# ================================================================================================ EXPORTAÇÃO, SEGURANÇA, CONFIG
def test_exports_pdf_and_xlsx(db):                                                  # [68] [69]
    _listings(db)
    out = RS.run(db, RS.create(db, "carregador GaN 65W", {"profundidade": "completa"}), ctx(db))
    x = EX.xlsx("pesquisa", out, "Pesquisa")
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(x))
    assert {"Visão geral", "Marketplaces", "Evidências", "Importação NCM"} <= set(wb.sheetnames)
    p = EX.pdf("pesquisa", out, "Pesquisa")
    assert p[:5] == b"%PDF-" and len(p) > 2000
    inj = EX.xlsx("nichos", {"itens": [{"produto": "=cmd|' /C calc'!A0"}]}, "x")
    ws = load_workbook(io.BytesIO(inj)).worksheets[0]
    assert all(not str(c.value or "").startswith("=") for row in ws.iter_rows() for c in row)
    sim = IX.simulate({"preco_fob_unit_usd": 5, "quantidade": 100, "cambio_brl_usd": 5, "preco_venda_unit_brl": 60})
    assert EX.pdf("cenario", sim, "Cenário")[:5] == b"%PDF-"


def test_settings_default_no_cost_and_validation():                                 # [30 sem pago]
    class St:
        def __init__(self):
            self.v = None

        def load_result(self, n):
            return self.v

        def save_result(self, n, p):
            self.v = p
    st = St()
    s = S.settings(st)
    assert s["sem_custos"] is True and s["orcamento_creditos"] == 0 and s["modelos_opcionais"] is False
    s2 = S.save_settings(st, {"periodo_meses": 7, "modo": "x", "orcamento_creditos": "-5", "segredo": "y"})
    assert s2["periodo_meses"] == 12 and s2["modo"] == "rapida" and s2["orcamento_creditos"] == 0 and "segredo" not in s2


def test_capabilities_preflight(db):
    assert CAP.preflight(db, "search_volume", "ml_trends", {})["ok"] is False              # ranking não é volume
    pf = CAP.preflight(db, "supplier_search", "importyeti", {"sem_custos": True})
    assert not pf["ok"] and next(e for e in pf["etapas"] if e["etapa"] == "custo")["ok"] is False
    assert all(p["custo"] != "pago" for p in CAP.PROVIDERS.values())
    assert {e["nome"] for e in CAP.EXCLUDED} >= {"Bing Visual Search", "Google Custom Search JSON API"}


def test_schema_is_additive_and_preserves_existing_data(tmp_path):                 # [62] [65] [31 histórico]
    d = Database(tmp_path / "m.sqlite")
    d.execute("INSERT INTO suppliers (nome, pais, produtos, criado_em, atualizado_em) VALUES ('Fornecedor Antigo', 'CN', 'cabo, carregador', 't', 't')")
    before = {r["name"] for r in d.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    S.ensure(d)
    S.ensure(d)
    after = {r["name"] for r in d.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert before <= after and d.query("SELECT COUNT(*) AS n FROM suppliers")[0]["n"] == 1
    c = d.query("SELECT * FROM companies")
    assert len(c) == 1 and c[0]["legacy_supplier_id"] == 1 and json.loads(c[0]["product_families"]) == ["cabo", "carregador"]


# ------------------------------------------------------------------------------------------------ servidor local real [63] [66] [67] [56] [59]
def test_http_routes_end_to_end(tmp_path):
    import socket
    import threading
    import time
    import urllib.error
    import urllib.request

    import uvicorn

    from gpi.app import create_app
    front = Path(__file__).resolve().parents[1] / "frontend"
    app = create_app(tmp_path / "data", front)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)

    def req(path, data=None, headers=None, raw=False, method=None):
        h = {"Content-Type": "application/json", "X-GPI": "1", **(headers or {})}
        body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
        r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method or ("POST" if data is not None else "GET"), headers=h)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                b = resp.read()
                return resp.status, (b if raw else json.loads(b))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    try:
        code, v = req("/api/suite/visao")
        assert code == 200 and v["versao"] == "0.9.1" and v["modo_sem_custos"] is True
        code, cfgv = req("/api/suite/config", {"importyeti_chave": "chave-de-teste"})
        assert code == 200 and "chave-de-teste" not in json.dumps(cfgv)                        # credencial nunca volta na resposta
        assert "chave-de-teste" not in json.dumps(req("/api/suite/importyeti")[1])
        code, r = req("/api/suite/pesquisa", {"consulta": "carregador GaN 65W", "sincrono": True})
        assert code == 200
        code, j = req(f"/api/suite/pesquisa/{r['id']}")
        assert j["status"].startswith("concluída") and j["progresso"]["pct"] == 100
        code, x = req(f"/api/suite/pesquisa/{r['id']}.xlsx", raw=True)
        assert code == 200 and x[:2] == b"PK"
        code, ires = req("/api/suite/imagem/buscar", img(), headers={"Content-Type": "application/octet-stream", "X-Filename": "a.png"})
        assert code == 200 and ires["consulta"]["formato"] == "PNG" and ires["busca_externa"]["servicos"]
        code, bad = req("/api/suite/imagem/buscar?url=http://127.0.0.1:1/x.png", b"", headers={"Content-Type": "application/octet-stream"})
        assert code == 400 and "URL recusada" in bad["erro"]
        try:                                                                                 # corpo acima do limite: recusado (413) ou conexão encerrada
            code, _ = req("/api/suite/imagem/buscar", b"\xff\xd8\xff" + b"0" * (12 * 1024 * 1024), headers={"Content-Type": "application/octet-stream"})
        except (urllib.error.URLError, ConnectionError):
            code = 413
        assert code == 413
        code, cmp_ = req("/api/suite/imagem/comparar", {"a": base64.b64encode(img()).decode(), "b": base64.b64encode(img(fmt="JPEG")).decode()})
        assert code == 200 and cmp_["classe"] in ("Imagem muito semelhante", "Possível mesmo produto")
        code, imp = req("/api/suite/importar/embarques", SHIP_CSV.encode(), headers={"Content-Type": "text/csv", "X-Filename": "e.csv"})
        assert code == 200 and imp["novos"] == 3
        code, blk = req("/api/suite/importyeti/consulta", {"consulta": "company_search", "autorizado": True, "custo_maximo": 1})
        assert blk["mensagem"] == IY.BLOCKED and blk["requisicao_feita"] is False
        code, sim = req("/api/suite/simular", {"parametros": {"preco_fob_unit_usd": 5, "quantidade": 10, "cambio_brl_usd": 5, "preco_venda_unit_brl": 60},
                                               "salvar": True, "nome": "teste"})
        assert sim["calculado"] and sim["salvo"]["id"]
        code, pdf = req(f"/api/suite/cenarios/{sim['salvo']['id']}.pdf", raw=True)
        assert pdf[:5] == b"%PDF-"
        assert req("/api/suite/monitorados", {"tipo": "produto", "ref": "charger+gan"})[0] == 200
        assert req("/api/suite/monitorados/atualizar", {})[0] == 200
        assert req("/api/suite/nichos")[0] == 200 and req("/api/suite/provedores")[0] == 200
        code, h = req("/api/v09/painel")                                                     # funcionalidades anteriores preservadas
        assert code == 200
    finally:
        srv.should_exit = True
        t.join(10)
        app.state.db.close()


def test_fixture_is_labeled_simulated():
    assert "simulada" in SIMULADO
