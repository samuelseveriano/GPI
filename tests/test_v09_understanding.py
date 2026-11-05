"""v0.9 — Product Understanding 2.0: regressões semânticas obrigatórias, taxonomia de 5 níveis, atributos explícitos,
contexto de vídeos, reavaliação das associações e avaliação em conjunto independente."""
from __future__ import annotations

import json

import pytest

from gpi.db import Database
from gpi.intel import understanding as U
from gpi.intel import understanding_eval as E
from gpi.market.content_store import ContentStore


# ---------------------------------------------------------------- regressões semânticas obrigatórias (seção 14.3)
def test_doorbell_is_not_smart_lock():
    u = U.understand("Campainha inteligente com câmera Wi-Fi e visão noturna", "pt", target="lock+smart")
    assert u["principal"] == "doorbell" and u["relacao_alvo"] == "outro_produto" and not u["pode_alimentar_conclusoes"]
    assert U.understand("Video doorbell vs smart lock: which one should you buy first?", "en")["estado"] == "ambigua"


def test_gan_charger_is_not_any_charger():
    g = U.understand("Carregador GaN 65W Baseus", "pt")
    plain = U.understand("carregador de celular", "pt")
    assert g["produto_id"] != plain["produto_id"]
    assert [n["id"] for n in g["taxonomia"]][-1] == "v:charger+gan:65w" and plain["nivel_rotulo"] == "família"
    other = U.understand("Carregador GaN 140W", "pt", target="charger+gan:65w")
    assert other["relacao_alvo"] == "variante_diferente" and not other["pode_alimentar_conclusoes"]


def test_entertainment_video_is_not_commercial_review():
    c = U.video_context("Desafio do slime gigante com meus amigos kkkk")
    assert c["contexto"] == "entretenimento"
    assert U.understand("Brinquedo slime caseiro DIY com a turma — vlog divertido", "pt")["estado"] != "confirmada"
    assert "não é uma categoria do YouTube" in c["nota"]


def test_news_is_not_buyer_review():
    u = U.understand("Anatel apreende carregadores falsificados em operação no porto", "pt")
    assert u["estado"] == "ambigua" and u["contexto"] == "noticia"


def test_language_is_not_country():
    from gpi.products import trends as T
    assert "LANG:en" not in T.GEO_PAGES


# ---------------------------------------------------------------- taxonomia e atributos
def test_five_levels_only_when_supported():
    u = U.understand("Projetor portátil Magcubic HY300 4K review", "pt")
    assert [n["nivel"] for n in u["taxonomia"]] == [1, 2, 3, 4, 5] and u["taxonomia"][-1]["id"] == "m:magcubic:hy300"
    fam = U.understand("projetor", "pt")
    assert [n["nivel"] for n in fam["taxonomia"]] == [1, 2] and fam["nivel_rotulo"] == "família"


def test_attributes_explicit_only_never_inferred():
    a = U.understand("Air fryer Mondial 5 litros 1500W bivolt", "pt")["atributos"]
    assert a["potencia_w"] == "1500" and a["capacidade"] == "5 L" and a["tensao"] == ["bivolt"] and a["marca"] == "mondial"
    b = U.understand("air fryer", "pt")["atributos"]
    assert b["potencia_w"] is None and b["capacidade"] is None and b["tensao"] is None and b["marca"] is None
    c = U.understand("película de vidro para Galaxy S24", "pt")
    assert c["atributos"]["modelo"] is None and c["atributos"]["modelo_compativel"] == "S24" and c["principal"] == "screen_protector"


@pytest.mark.parametrize("title,ctx", [("Ring Video Doorbell 4 review after one year", "review"), ("UNBOXING do iPhone 16", "unboxing"),
                                       ("Como instalar fechadura digital", "tutorial"), ("Robô aspirador X20 #publi", "publicidade"),
                                       ("Robot vacuum vs stick vacuum", "comparativo"), ("Vlog de viagem em Gramado", "entretenimento"),
                                       ("Minha cozinha nova", "nao_identificado")])
def test_video_contexts(title, ctx):
    assert U.video_context(title)["contexto"] == ctx


# ---------------------------------------------------------------- reavaliação das associações de vídeos
def _db(tmp_path):
    db = Database(tmp_path / "g.sqlite")
    cs = ContentStore(db)
    vids = [("v1", "Campainha inteligente com câmera Wi-Fi review", "lock+smart"),
            ("v2", "Fechadura digital biométrica review completo", "lock+smart"),
            ("v3", "Desafio do slime kkkk", "toy")]
    cs.upsert("youtube", [{"item_id": i, "url": f"https://youtu.be/{i}", "title": t, "product_key": pk,
                           "metrics": {"viewCount": 10, "produto_consultado": pk}} for i, t, pk in vids])
    return db, cs


def test_reassess_removes_wrong_associations_and_keeps_history(tmp_path):
    db, _ = _db(tmp_path)
    out = U.reassess_content(db)
    rows = {r["item_id"]: r for r in db.query("SELECT item_id, product_key, metrics FROM content_items")}
    assert rows["v1"]["product_key"] is None and json.loads(rows["v1"]["metrics"])["produto_anterior"] == "lock+smart"
    assert rows["v2"]["product_key"] == "lock+smart"
    assert rows["v3"]["product_key"] is None
    assert out["removidas"] == 2 and out["mantidas"] == 1 and out["fila_revisao"] >= 2
    q = {r["item_id"]: r for r in db.query("SELECT * FROM association_review")}
    assert "v1" in q and q["v1"]["decisao"] is None
    tax = {r["id"] for r in db.query("SELECT id FROM product_taxonomy")}
    assert "f:lock" in tax and "f:doorbell" not in tax                       # só associações confirmadas viram taxonomia


def test_human_decision_prevails(tmp_path):
    db, _ = _db(tmp_path)
    U.reassess_content(db)
    db.execute("UPDATE association_review SET decisao = 'confirmar', produto_decidido = 'doorbell+smart' WHERE item_id = 'v1'")
    U.reassess_content(db)
    assert db.query("SELECT product_key FROM content_items WHERE item_id = 'v1'")[0]["product_key"] == "doorbell+smart"


def test_upsert_no_longer_keeps_rejected_association(tmp_path):
    db, cs = _db(tmp_path)
    cs.upsert("youtube", [{"item_id": "v1", "url": "https://youtu.be/v1", "title": "Campainha", "product_key": None, "metrics": {}}])
    assert db.query("SELECT product_key FROM content_items WHERE item_id = 'v1'")[0]["product_key"] is None


# ---------------------------------------------------------------- avaliação independente
def test_independent_test_set_meets_engineering_target():
    r = E.evaluate(E.load("understanding_test_v09.tsv"), E.baseline_analyzer)
    assert r["casos"] >= 120
    assert r["precisao_alta_confianca"] >= 0.95                       # meta de engenharia, medida no conjunto de TESTE
    assert r["taxa_associacao_incorreta"] <= 0.05
    for g in ("noticia", "video_irrelevante", "semelhante"):
        assert r["por_grupo"][g]["acerto"] >= 0.9


def test_dev_and_test_sets_do_not_overlap():
    dev = {c["texto"].lower() for c in E.load("understanding_dev_v09.tsv")}
    test = {c["texto"].lower() for c in E.load("understanding_test_v09.tsv")}
    assert not dev & test
