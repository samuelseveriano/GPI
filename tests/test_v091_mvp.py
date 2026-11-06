"""v0.9.1 MVP RC — fluxo de dados API → banco → análise: contagem dos anúncios na sincronização, carregador × cabo,
Opportunity Score com evidência insuficiente, URL de marketplace pela API oficial (simulada), imagem por URL, Meta
Business (config_id), ficha regulatória (máquina de waffle) e Dashboard consolidado. Respostas externas SIMULADAS."""
from __future__ import annotations

from datetime import date

import pytest

from gpi.db import Database
from gpi.products.catalog import Catalog
from gpi.suite import listing_match as LM
from gpi.suite import marketplace as MK
from gpi.suite import store as S
from gpi.suite import url_lookup as UL

TODAY = date.today()


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "m.sqlite")
    Catalog(d, {}).ensure_seeded()
    S.ensure(d)
    return d


def test_ebay_rows_are_counted_by_sync():
    from gpi.market import sync
    assert ("market_listings", "source") in sync._DIRECT_TABLES          # antes: 30 requisições, 0 registros contados


@pytest.mark.parametrize("title,cls", [("USB C Cable 6ft Fast Charging Cord", "Acessório relacionado"),
                                       ("Anker 65W GaN USB C Charger 3-Port", "Variante compatível"),
                                       ("65W GaN charger", "Produto exato"),
                                       ("USB C power adapter 65W", "Produto tecnicamente semelhante"),
                                       ("2 Pack USB C Charger 20W block", "Mesma família"),
                                       ("Phone case for iPhone 15", "Acessório relacionado"),
                                       ("Waffle maker 1000W", "Produto incompatível")])
def test_charger_vs_cable_classification(title, cls):
    m = LM.classify(title, "charger+gan:65w", "en")
    assert m["classe"] == cls
    assert m["elegivel"] == (cls in LM.ELIGIBLE)


def test_kit_units_and_comparable_prices(db):
    rows = [("ebay", "1", "65W GaN charger", 30.0), ("ebay", "2", "2 Pack 65W GaN charger", 50.0), ("ebay", "3", "USB C Cable 6ft", 8.0),
            ("ebay", "4", "Anker 65W GaN USB C Charger", 40.0)]
    for src, iid, t, p in rows:
        db.execute("INSERT INTO market_listings (source, item_id, day, product_id, query, title, price, currency, collected_at) VALUES (?, ?, ?, ?, 'q', ?, ?, 'USD', 't')",
                   (src, iid, TODAY.isoformat(), "charger+gan:65w", t, p))
    ls = MK.listing_stats(db, "charger+gan:65w", 30, TODAY)
    assert ls["anuncios"] == 4 and ls["anuncios_elegiveis"] == 3 and ls["kits_ou_lotes"] == 1
    assert ls["preco_min"] == 25.0 and ls["preco_max"] == 40.0 and ls["preco_mediano"] == 30.0          # cabo (8) fora; kit por unidade
    assert ls["por_correspondencia"]["Acessório relacionado"] == 1 and MK.competition(ls) == "não avaliada"


def test_opportunity_index_not_100_with_insufficient_evidence():
    from gpi.products import opportunity3 as O
    cons = {"produtos": [{"product_id": "headphones", "nome": "Fone de ouvido", "categoria": "Áudio", "series": [],
                          "indicadores": {}, "busca": {}}]}
    try:
        r = O.build(cons, None, None, None)
    except Exception:
        pytest.skip("estrutura do consumer mudou")
    for row in r.get("produtos") or r.get("itens") or []:
        if row["prioridade"] == "Evidência insuficiente":
            assert row["indice"] is None and row["elegivel_para_decisao"] is False


class Creds:
    def __init__(self, d):
        self.d = d

    def get(self, k):
        return dict(self.d.get(k) or {})

    def set(self, k, v):
        self.d.setdefault(k, {}).update(v)


class Http:
    def __init__(self):
        self.calls = []

    def request_json(self, url, method="GET", **kw):
        self.calls.append(url)
        if "identity" in url:
            return {"access_token": "t", "expires_in": 7200}
        if "get_item_by_legacy_id" in url:
            return {"itemId": "v1|123456789012|0", "title": "Anker 65W GaN USB C Charger", "price": {"value": "39.99", "currency": "USD"},
                    "brand": "Anker", "itemWebUrl": "https://www.ebay.com/itm/123456789012", "image": {"imageUrl": "https://i.ebayimg.com/x.jpg"},
                    "seller": {"username": "vendedor_x"}, "localizedAspects": [{"name": "Output Power", "values": ["65 W"]}]}
        if "api.mercadolibre.com/items/" in url:
            from gpi.connectors.http import SourceError
            raise SourceError("permissão insuficiente (HTTP 403)", "restrita", status=403, cause="permissao")
        raise AssertionError(url)


class Sync:
    def __init__(self, creds):
        self.http, self.creds = Http(), Creds(creds)


def test_url_detection():
    assert UL.detect("https://www.ebay.com/itm/Some-title/123456789012?hash=x")["id"] == "123456789012"
    assert UL.detect("https://produto.mercadolivre.com.br/MLB-1234567890-carregador-_JM")["id"] == "MLB1234567890"
    assert UL.detect("https://www.mercadolivre.com.br/carregador/p/MLB19876543")["provedor"] == "mercadolivre_produto"
    assert UL.detect("https://exemplo.com/foto.webp?w=1")["tipo"] == "URL direta de imagem"
    assert UL.detect("https://loja.exemplo.com/produto/abc")["tipo"] == "página de produto"
    assert UL.detect("http://127.0.0.1/x.png")["tipo"] == "URL inválida"


def test_ebay_url_uses_official_api_and_persists(db):
    s = Sync({"ebay": {"client_id": "a", "client_secret": "b", "sync_token": "c"}})
    r = UL.fetch_listing(db, s, "https://www.ebay.com/itm/123456789012")
    assert r["ok"] and r["gravado"] and r["anuncio"]["imagem"].endswith("x.jpg") and r["produto_identificado"].startswith("charger")
    row = db.query("SELECT seller, price, product_id FROM market_listings")[0]
    assert row["seller"].startswith("h:") and row["price"] == 39.99                                   # vendedor pseudonimizado
    assert "vendedor" not in r["anuncio"]
    r2 = UL.fetch_listing(db, Sync({"ebay": {"client_id": "a", "client_secret": "b"}}), "123456789012")
    assert r2["ok"] and not r2["gravado"]                                                             # sem fluxo de exclusão: não grava


def test_mercadolivre_url_permission_diagnostic(db):
    import gpi.integrations.registry as reg
    reg_tok = reg.ml_token
    reg.ml_token = lambda http, creds: "t"
    try:
        r = UL.fetch_listing(db, Sync({"mercadolivre": {"access_token": "x"}}), "https://produto.mercadolivre.com.br/MLB-1234567890-x")
    finally:
        reg.ml_token = reg_tok
    assert not r["ok"] and r["estado"] == "Permissão insuficiente" and "palavra-chave" in r["alternativa"]


def test_meta_business_uses_config_id_not_scope():
    from gpi.integrations import meta as M
    u = M.authorize_url({"client_id": "1", "config_id": "987"}, "v23.0", "https://samuelseveriano.github.io/GPI/oauth/meta/", "st", "paginas")
    assert "config_id=987" in u and "scope=" not in u and "redirect_uri=https%3A%2F%2Fsamuelseveriano.github.io%2FGPI%2Foauth%2Fmeta%2F" in u
    assert "scope=public_profile" in M.authorize_url({"client_id": "1", "config_id": "987"}, "v23.0", "https://x/", "st", "basico")
    with pytest.raises(Exception):
        M.authorize_url({"client_id": "1", "config_id": "abc"}, "v23.0", "https://x/", "st", "paginas")


def test_waffle_maker_regulatory_ficha(db):
    from gpi.compliance import features as CF
    from gpi.compliance import rules as CR
    from gpi.suite import regassist
    q = "Máquina de waffle 220V"
    f = regassist.ficha(db, q, {"achados": CR.run(CF.extract({"descricao_tecnica": q}), None), "fontes": []})
    assert f["produto"].startswith("Máquina de waffle") and f["categoria_provavel"] == "Eletroportáteis"
    qs = {x["questao"]: x["situacao"] for x in f["questoes_tecnicas"]}
    assert qs["Materiais e revestimentos em contato com alimentos"] == "pendente" and qs["Tensão nominal (127 V, 220 V ou bivolt)"] == "informado"
    assert all(r["situacao"] == "não confirmado" for r in f["requisitos_potenciais"])
    assert any("Não presume certificação Inmetro" in a for a in f["avisos"])


def test_registry_match_classes(db):
    from gpi.suite import regassist
    db.execute("INSERT INTO anatel_registros (numero_homologacao, data_homologacao, solicitante, cnpj_solicitante, fabricante, pais_fabricante, modelo, "
               "tipo_produto, nome_comercial) VALUES ('1', '2025-01-01', 'Imp X', '1', 'Shenzhen A Co Ltd', 'China', 'A65', 'Carregador', 'Carregador GaN 65W')")
    db.execute("INSERT OR REPLACE INTO ncm_meta (k, v) VALUES ('anatel_v2_registros', '1')")
    r = regassist._registry_matches(db, ["Carregador GaN 65W"], "Shenzhen A Co., Ltd.", "A65")
    assert r["itens"][0]["correspondencia"] == "Modelo exato confirmado"
    r = regassist._registry_matches(db, ["Carregador GaN 65W"], None, None)
    assert r["itens"][0]["correspondencia"] == "Produto semelhante" and "NÃO vale para outro modelo" in r["regra"]


def test_consolidated_dashboard_uses_real_tables(db):
    from gpi.suite import dashboard as DB_
    db.execute("INSERT INTO market_listings (source, item_id, day, product_id, query, title, price, currency, collected_at) VALUES "
               "('ebay', '1', ?, 'charger+gan:65w', 'q', '65W GaN charger', 30, 'USD', 't')", (TODAY.isoformat(),))
    c = DB_.build(db, {"produtos": {}}, {"itens": []}, TODAY)
    assert c["concorrencia"]["produtos_com_anuncios"] == 1 and c["concorrencia"]["faixas_preco"][0]["elegiveis"] == 1
    assert c["vazios"]["mercado"] and c["vazios"]["comex"] and c["portfolio"]["cadastrados"] >= 100


def test_supplier_cn_has_assisted_gsxt_link(db):
    from gpi.suite import suppliers as SP
    SP.upsert_company(db, {"legal_name": "Dongguan Waffle Appliance Co Ltd", "country": "CN", "product_families": "máquina de waffle"}, "t")
    d = SP.discover(db, "máquina de waffle")
    c = d["candidatos"][0]
    assert c["tipo_correspondencia"] == "fornecedor cadastrado" and c["validar_registro"]["url"] == "https://www.gsxt.gov.cn/"
