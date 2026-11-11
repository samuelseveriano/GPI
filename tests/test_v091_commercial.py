"""v0.9.1 MVP — evidência comercial (marketplaces) → indicadores → Opportunity Engine → Dashboard → comparador → exportação.

Cenário de demonstração: Carregador GaN 65W, mercado EUA (eBay Browse). Todas as respostas externas são SIMULADAS
(FakeHttp); o teste autenticado final com a API real do eBay ocorre no computador do usuário."""
from __future__ import annotations

from gpi.connectors.http import SourceError
from gpi.market import reviews2
from gpi.products import opportunity3 as O
from gpi.suite import dashboard as DB
from gpi.suite import diagnostics as DG
from gpi.suite import export as EX
from gpi.suite import marketplace as MK
from gpi.suite import research as RS
from gpi.suite import targeted as TG

from test_v091_targeted import TODAY, FakeHttp, db, fake_tokens, run, sctx  # noqa: F401  (fixtures reaproveitadas)

PID = "charger+gan:65w"
BRANDS = ["Anker", "Ugreen", "Baseus", "Anker", "Belkin", "Ugreen"]


class EbayGaN(FakeHttp):
    """eBay (EUA) com carregadores GaN 65W de várias marcas, cabos, carregador 20W, kit 2 unidades e um suporte."""

    def _resp(self, url, kw):
        if "item_summary/search" in url and not any(f in url for f in self.fail):
            items = [{"itemId": f"v1|c{i}|0", "title": f"{BRANDS[i % 6]} 65W GaN USB C Charger fast {i}", "brand": BRANDS[i % 6],
                      "price": {"value": str(30 + i), "currency": "USD"}, "seller": {"username": f"seller{i % 9}"},
                      "itemWebUrl": f"https://www.ebay.com/itm/{100 + i}", "condition": "New", "itemLocation": {"country": "US"}}
                     for i in range(14)]
            items += [{"itemId": f"v1|k{i}|0", "title": f"USB C to USB C Cable 100W 6ft {i}", "price": {"value": "8", "currency": "USD"},
                       "seller": {"username": "cables"}, "itemWebUrl": "https://www.ebay.com/itm/9", "condition": "New"} for i in range(5)]
            items += [{"itemId": "v1|w|0", "title": "20W USB C charger block", "price": {"value": "9", "currency": "USD"},
                       "seller": {"username": "x"}, "itemWebUrl": "https://www.ebay.com/itm/8", "condition": "New"},
                      {"itemId": "v1|p|0", "title": "Baseus 65W GaN Charger 2 pack", "price": {"value": "60", "currency": "USD"},
                       "seller": {"username": "y"}, "itemWebUrl": "https://www.ebay.com/itm/7", "condition": "New"},
                      {"itemId": "v1|s|0", "title": "Laptop Stand Aluminum", "price": {"value": "25", "currency": "USD"},
                       "seller": {"username": "z"}, "itemWebUrl": "https://www.ebay.com/itm/6", "condition": "New"}]
            return {"itemSummaries": items}
        return super()._resp(url, kw)


EBAY_ONLY = {"ebay": {"client_id": "a", "client_secret": "b", "sync_token": "c"}}


def _demo(db):
    fn, http = sctx(db, EbayGaN(), creds=EBAY_ONLY)        # só eBay: isola a evidência de oferta (sem volume de busca)
    rid, out, j = run(db, "Carregador GaN 65W", fn, profundidade="rapida", mercado="US")
    return rid, out, j, http


# ---------------------------------------------------------------------------------------- consulta eBay → dados → produto
def test_demo_gan_65w_us_end_to_end(db):
    rid, out, j, http = _demo(db)
    assert out["abas"]["visao_geral"]["produto_id"] == PID                                   # 1. produto identificado
    col = {r["id"]: r for r in out["coleta"]["resultados"]}
    assert col["ebay"]["estado"] == "com dados" and any("item_summary" in u for u in http.calls)   # 2. eBay consultado
    assert {r["product_id"] for r in db.query("SELECT DISTINCT product_id FROM market_listings")} == {PID}
    # 3–5. classificados; cabos/suporte/20W fora; preços só dos elegíveis (kit por unidade)
    assert out["coleta"]["invalidados"] == ["competition"]       # só oferta: indicadores do produto recalculados; busca intacta
    ic = out["abas"]["marketplaces"]["indicadores_comerciais"]
    us = ic["itens"][0]
    assert us["mercado"] == "US" and us["fonte"] == "ebay" and us["tipo_evidencia"] == "Oferta observada"
    assert us["anuncios"] == 22 and us["anuncios_elegiveis"] == 15 and us["excluidos_acessorios_incompativeis"] == 7
    assert us["kits_ou_lotes"] == 1 and us["preco_min"] == 30.0 and us["preco_max"] == 43.0     # cabo (8) e 20W (9) fora; kit 60/2
    assert us["preco_q1"] <= us["preco_mediano"] <= us["preco_q3"] and us["posicionamento"]["economico_ate"] == us["preco_q1"]
    # 6. concorrentes e marcas
    assert us["concorrentes_observados"] == 10 and us["marcas_distintas"] >= 3
    assert us["pressao_competitiva"] is not None and us["status"] == "indicativa (coleta única: sem tendência)"
    assert us["crescimento"] is None and us["variacao_preco"] == []                         # coleta única ≠ crescimento
    # 7–8. Opportunity Engine: oferta EUA é contexto, índice parcial/CINZA, sem crescimento comprovado
    op = ic["oportunidade"]
    assert op["prioridade"] == "Evidência insuficiente" and op["indice"] is None and not op["elegivel_para_decisao"]
    assert op["tipos_de_evidencia"]["Oferta observada"] and not op["tipos_de_evidencia"]["Crescimento comprovado"]
    assert op["tipos_de_evidencia"]["Evidência insuficiente"]
    assert op["oferta_observada"][0]["afeta_indicadores_do_mercado"] is False
    assert any("Coleta única" in x for x in ic["limitacoes"]) and any("não são vendas" in x for x in ic["limitacoes"])
    assert out["decisao"]["cor"] in ("CINZA", "AMARELO")                                      # nunca VERDE por anúncios
    # 9. Dashboard
    d = DB.build(db, {"produtos": {}}, {"itens": []}, TODAY)
    row = next(r for r in d["concorrencia"]["faixas_preco"] if r["produto_id"] == PID)
    assert row["mercado"] == "US" and row["elegiveis"] == 15 and row["mediana"] == us["preco_mediano"]
    assert d["mercado"]["tipos_de_evidencia"]["Oferta observada"] == 1 and d["mercado"]["tipos_de_evidencia"]["Crescimento comprovado"] == 0
    assert d["mercado"]["oportunidades_com_oferta"][0]["produto_id"] == PID
    # 10. exportação
    res = RS.get(db, rid)["result"]
    tabs = {name: (rows, notes) for name, rows, notes in EX.tables_from("pesquisa", res)}
    rows, notes = tabs["Oferta e oportunidade"]
    assert rows[0]["mercado"] == "US" and rows[0]["anuncios_elegiveis"] == 15 and "anker" in rows[0]["marcas"]
    assert any("não são vendas" in n for n in notes)
    assert EX.xlsx("pesquisa", res, "GaN")[:2] == b"PK" and EX.pdf("pesquisa", res, "GaN")[:4] == b"%PDF"


# ---------------------------------------------------------------------------------------- persistência e atualização
def test_indicators_persist_and_update_after_new_collection(db):
    _demo(db)
    first = TG._load(db, "competition")
    assert first and first["itens"][0]["dias_observados"] == 1
    # nova coleta em outro dia → só o produto afetado é recalculado; outro produto em cache é preservado
    other = {"product_id": "air_fryer", "fonte": "mercadolivre", "mercado": "BR", "anuncios_elegiveis": 3, "pressao_competitiva": None}
    TG._save(db, "competition", {**first, "itens": first["itens"] + [other]})
    db.execute("INSERT INTO market_listings (source, item_id, day, product_id, query, title, brand, price, currency, seller, collected_at) "
               "SELECT source, item_id, '2026-11-04', product_id, query, title, brand, price + 1, currency, seller, collected_at "
               "FROM market_listings WHERE source = 'ebay'")
    TG.invalidate(db, [{"consulta_realizada": True, "estado": "com dados", "capacidade": "listings"}], PID)
    c = TG._load(db, "competition")
    us = next(x for x in c["itens"] if x["product_id"] == PID)
    assert us["dias_observados"] == 2 and us["status"] == "indicativa" and len(us["variacao_preco"]) == 2
    assert any(x["product_id"] == "air_fryer" for x in c["itens"])                       # não recalcula o banco inteiro
    assert RS.commercial_indicators(db, PID)["oportunidade"]["oferta_observada"][0]["dias_observados"] == 2


# ---------------------------------------------------------------------------------------- Brasil × EUA
def test_us_listings_do_not_affect_brazil_indicators(db):
    def ins(src, iid, title, price, cur, seller, brand):
        db.execute("INSERT INTO market_listings (source, item_id, day, product_id, query, title, brand, price, currency, seller, collected_at) "
                   "VALUES (?, ?, ?, ?, 'q', ?, ?, ?, ?, ?, 't')", (src, iid, TODAY.isoformat(), PID, title, brand, price, cur, seller))
    for i in range(12):
        ins("ebay", f"e{i}", f"Anker 65W GaN charger {i}", 30 + i, "USD", f"s{i}", ["Anker", "Ugreen", "Belkin"][i % 3])
    comp = reviews2.competition(db, today=TODAY)
    row = next(r for r in O.build({}, None, None, comp, db)["produtos"] if r["product_id"] == PID)
    assert "competition_pressure" not in row["dimensoes"] and "import_readiness" not in row["dimensoes"]   # EUA não vira indicador BR
    assert row["indice"] is None and row["prioridade"] == "Evidência insuficiente"
    for i in range(12):
        ins("mercadolivre", f"m{i}", f"Carregador GaN 65W turbo {i}", 150 + i, "BRL", f"v{i % 6}", ["Baseus", "Ugreen"][i % 2])
    comp = reviews2.competition(db, today=TODAY)
    br = next(c for c in comp["itens"] if c["mercado"] == "BR")
    us = next(c for c in comp["itens"] if c["mercado"] == "US")
    assert br["moeda"] == "BRL" and us["moeda"] == "USD" and br["preco_min"] == 150.0 and us["preco_max"] == 41.0   # nunca misturados
    row = next(r for r in O.build({}, None, None, comp, db)["produtos"] if r["product_id"] == PID)
    assert row["dimensoes"]["competition_pressure"] == br["pressao_competitiva"]          # só o Brasil entra no índice
    assert {o["mercado"]: o["afeta_indicadores_do_mercado"] for o in row["oferta_observada"]} == {"BR": True, "US": False}


# ---------------------------------------------------------------------------------------- indicadores → Opportunity Engine
def test_offer_feeds_existing_dimensions_without_counting_as_demand():
    comp = {"itens": [{"product_id": "headphones", "mercado": "BR", "fonte": "mercadolivre", "anuncios_elegiveis": 40, "pressao_competitiva": 70.0}]}
    cons = {"series": [{"id": "s1", "product_id": "headphones", "metric": "volume_busca", "source": "google_ads_kp", "nome": "Fone",
                        "ind": {"media_3m": 100, "crescimento": 0.2}}], "scores": {}}
    row = O.build(cons, None, None, comp)["produtos"][0]
    assert row["dimensoes"]["competition_pressure"] == 70.0 and row["dimensoes"]["import_readiness"] == 100.0
    assert "marketplace_evidence" not in row["dimensoes"]                                  # anúncio ≠ demanda
    assert row["tipos_de_evidencia"]["Oferta observada"] and not row["tipos_de_evidencia"]["Crescimento comprovado"]
    assert row["indice"] is None and row["indice_parcial"] is not None                    # só 1 dimensão de demanda → parcial


def test_small_sample_has_no_competition_pressure(db):
    for i in range(4):
        db.execute("INSERT INTO market_listings (source, item_id, day, product_id, query, title, price, currency, seller, collected_at) "
                   "VALUES ('ebay', ?, ?, ?, 'q', ?, ?, 'USD', ?, 't')", (f"i{i}", TODAY.isoformat(), PID, f"65W GaN charger {i}", 30 + i, f"s{i}"))
    it = reviews2.competition(db, today=TODAY)["itens"][0]
    assert it["anuncios_elegiveis"] == 4 and it["pressao_competitiva"] is None and it["status"] == "amostra insuficiente"


# ---------------------------------------------------------------------------------------- falta de evidências
def test_no_listings_no_commercial_evidence(db):
    assert reviews2.competition(db, today=TODAY)["itens"] == []
    ic = RS.commercial_indicators(db, PID)
    assert ic["itens"] == [] and ic["vazio"] and ic["oportunidade"] is None
    assert O.build({}, None, None, {"itens": []})["produtos"] == []
    assert DB.build(db, {"produtos": {}}, {"itens": []}, TODAY)["vazios"]["concorrencia"]


# ---------------------------------------------------------------------------------------- comparador
def test_commercial_comparator_up_to_five(db):
    _demo(db)
    refs = ["v1|c0|0", "v1|c1|0", "v1|k0|0", "v1|p|0", "v1|c2|0", "v1|c3|0"]
    r = MK.compare_listings(db, refs)
    assert len(r["itens"]) == 5 and r["alvo"] == PID and r["compativeis"] == 4
    by = {i["id"]: i for i in r["itens"]}
    cable = by["v1|k0|0"]
    assert not cable["compativel"] and "fora da síntese" in cable["limitacoes"][0]
    assert by["v1|c0|0"]["marca_declarada"].lower() == "anker" and by["v1|c0|0"]["especificacoes"]["Potência (W)"] == "65"
    assert by["v1|p|0"]["preco_unitario"] == 30.0 and any("kit/lote" in x for x in by["v1|p|0"]["limitacoes"])
    assert "Capacidade (mAh)" not in by["v1|c0|0"]["especificacoes"]                     # não declarada em nenhum → não inventada
    assert any("Preço unitário observado" in s for s in r["sintese"]) and any("incompatibilidade" in s for s in r["sintese"])
    assert all(i["fonte"] == "ebay" and i["mercado"] == "US" for i in r["itens"])
    p = MK.compare_listings(db, ["produto:" + PID, "v1|c4|0"])
    assert p["itens"][0]["tipo"] == "produto" and p["itens"][0]["preco_atual"] is not None


# ---------------------------------------------------------------------------------------- 429 transitório × falha de implementação
def test_http_429_is_transient_diagnostic_not_implementation_failure(db):
    e = SourceError("Limite de requisições atingido.", "limite", retryable=True, status=429, cause="limite")
    st = DG.classify(e)
    assert "limite" in (st.get("estado") or "").lower() or "limite" in str(st).lower()
    http = EbayGaN(fail={"item_summary": e})
    fn, _ = sctx(db, http)
    rid, out, j = run(db, "Carregador GaN 65W", fn, profundidade="rapida", mercado="US")
    ebay = next(r for r in out["coleta"]["resultados"] if r["id"] == "ebay")
    assert ebay["http"] == 429 and ebay["causa"] == "limite" and "Limite" in ebay["motivo"]
    assert j["status"] != "falhou" and ebay["registros"] == 0 and not db.query("SELECT 1 FROM market_listings")
