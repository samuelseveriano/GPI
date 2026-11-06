"""v0.9 — estágios de decisão, próximas ações, ficha pré-preenchida, respostas fundamentadas e alertas com estado."""
from __future__ import annotations

from datetime import date

from gpi.db import Database
from gpi.intel import decision as D
from gpi.intel.semantics import COMMERCIAL, PUBLIC, SEARCH

TODAY = date(2026, 11, 5)


def prod(evs, situacao="SINAL INSUFICIENTE", corr="confirmada"):
    return {"produto_id": "chair+gamer", "identificacao": {"produto": "Cadeira gamer", "familia": "chair", "variante": None},
            "situacao": situacao, "evidencias": evs, "correspondencia": {"estado": corr}, "fontes": ["Mercado Livre"]}


def ml(weeks_present, persist, first="2026-W44"):
    return {"tipo": COMMERCIAL, "fonte": "ml_trends", "fonte_nome": "Mercado Livre — tendências", "metrica": "posicao", "mercado": "BR",
            "periodo": f"{first} a 2026-W45", "derivado": {"semanas_presente": weeks_present, "persistencia": persist,
                                                          "primeira_semana": first, "melhor_posicao": 3}}


def test_one_week_in_ranking_is_new_signal_not_recommendation():
    p = prod([ml(1, 1.0)])
    ev = D.evidence_stage(p, TODAY)
    assert ev["estagio"] == 1 and ev["nome"] == "Novo sinal"
    assert any("persistência" in m for m in ev["faltando"])
    acts = D.next_actions(p, ev["estagio"])
    assert acts[0].startswith("Acompanhar") and any("variantes" in a for a in acts) and any("preços" in a for a in acts)
    a = D.answer(p, ev, "crescimento")
    assert "NÃO confirmado" in a["resposta"] and "1 semana" in a["resposta"]


def test_persistent_commercial_evidence_reaches_stage_3():
    ev = D.evidence_stage(prod([ml(6, 0.75, "2026-W30")]), TODAY)
    assert ev["estagio"] == 3 and ev["criterios"]["persistencia_comercial"]


def test_ambiguous_identification_never_reaches_stage_3():
    ev = D.evidence_stage(prod([ml(6, 0.75, "2026-W30")], corr="ambigua"), TODAY)
    assert ev["estagio"] < 3 and any("identificação" in m for m in ev["faltando"])


def test_wikipedia_only_stays_identified():
    ev = D.evidence_stage(prod([{"tipo": PUBLIC, "fonte": "wikimedia", "fonte_nome": "Wikipédia", "metrica": "visualizacoes"}]), TODAY)
    assert ev["estagio"] == 0


def test_search_growth_confirmed_alone_is_not_enough_without_commercial():
    ev = D.evidence_stage(prod([{"tipo": SEARCH, "fonte": "trends", "fonte_nome": "Google Trends", "metrica": "busca"}],
                               situacao="CRESCIMENTO CONSISTENTE"), TODAY)
    assert ev["estagio"] == 2


def test_prefill_uses_only_existing_data(tmp_path):
    p = prod([ml(1, 1.0)])
    f = D.prefill(p, D.evidence_stage(p, TODAY))
    assert f["fornecedores"] == [] and f["concorrentes"] == [] and f["exigencias"] == []
    assert any("Mercado Livre" in e for e in f["evidencias"]) and any(e.startswith("Limitação") for e in f["evidencias"])
    assert "variante: não identificada" in f["motivo"]
    db = Database(tmp_path / "d.sqlite")
    r = D.INV.add(db, f)
    assert r["produto_id"] == "chair+gamer" and D.INV.add(db, f)["ja_existia"]


def test_grounded_answers_say_when_data_is_missing():
    assert "Não há evidências" in D.answer(prod([]), D.evidence_stage(prod([]), TODAY), "por_que")["resposta"]
    a = D.answer(prod([ml(1, 1.0)]), D.evidence_stage(prod([ml(1, 1.0)]), TODAY), "variante")
    assert "Nenhuma variante" in a["resposta"] and a["fontes"]


def test_alerts_new_then_known_then_resolved(tmp_path):
    db = Database(tmp_path / "a.sqlite")
    a = [{"categoria_alerta": "comercial", "tipo": "novo sinal", "produto_id": "p1", "fonte": "ml"},
         {"categoria_alerta": "estatístico", "tipo": "anomalia", "produto_id": "p2", "fonte": "trends"}]
    r1 = D.track_alerts(db, a, "2026-11-01")
    assert {x["estado"] for x in r1} == {"novo"} and r1[0]["categoria_v09"] == "executivo"
    r2 = D.track_alerts(db, a, "2026-11-02")
    assert {x["estado"] for x in r2} == {"conhecido"} and r2[0]["vezes"] == 2
    D.track_alerts(db, a[:1], "2026-11-03")
    assert db.query("SELECT estado FROM alert_state WHERE produto_id = 'p2'")[0]["estado"] == "resolvido"
    assert r2[1]["categoria_v09"] == "estatístico"               # anomalia estatística não vira alerta executivo


def test_origin_labels_and_demo_never_in_production():
    from gpi.intel.semantics import origin_of
    assert origin_of("DADOS DEMONSTRATIVOS (sintéticos)") == "DEMONSTRATIVO"
    assert origin_of("painel sintético de teste") == "SIMULADO"
    assert origin_of("ml_trends") == "REAL" and origin_of("gpi", "derivado") == "DERIVADO" and origin_of("x", "previsto") == "PREVISTO"


def test_demo_sales_do_not_change_opportunity_payload(tmp_path):
    """Importar Vendas Próprias de demonstração não altera produtos, evidências nem estágios do motor de oportunidades."""
    from gpi.demo import make_demo_csv
    from gpi.importer import import_file
    from gpi.intel import fusion
    db = Database(tmp_path / "x.sqlite")
    before = fusion.build(db, {"series": [], "scores": {}}, {}, TODAY, with_lineage=False)
    import_file(db, "dados_demonstrativos.csv", make_demo_csv(), source="DADOS DEMONSTRATIVOS (sintéticos)", is_demo=True)
    after = fusion.build(db, {"series": [], "scores": {}}, {}, TODAY, with_lineage=False)
    assert before["produtos"] == after["produtos"] == {}
