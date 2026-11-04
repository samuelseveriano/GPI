"""v0.7 — Conformidade de Importação: base regulatória, regras, NCM, homologações, anexos, atualização e relatórios."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from test_api_integration import Srv

from gpi.compliance import attachments as AT
from gpi.compliance import certs as C
from gpi.compliance import engine as E
from gpi.compliance import features as F
from gpi.compliance import rules as R
from gpi.compliance import updater as U
from gpi.compliance.knowledge import BUNDLED, KnowledgeBase
from gpi.compliance.ncm import NcmTable, parse_official
from gpi.db import Database

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("orgao", "titulo", "numero", "data_publicacao", "vigencia_inicio", "ultima_verificacao", "url_oficial", "versao",
            "id", "hash_sha256", "status_atualizacao", "texto")


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    kb = KnowledgeBase(db, tmp_path)
    ncm = NcmTable(db)
    yield db, kb, ncm
    db.close()


def ncm_fixture() -> bytes:
    rows = [("85", "Máquinas, aparelhos e materiais elétricos, e suas partes"),
            ("8517", "Aparelhos telefônicos, incluindo os telefones inteligentes"),
            ("8517.62", "-- Aparelhos para recepção, conversão e transmissão de voz, imagens ou outros dados"),
            ("8517.62.77", "Outros aparelhos de transmissão com recepção incorporada, sem fio"),
            ("8504.40.10", "Carregadores de acumuladores"), ("8504", "Transformadores elétricos, conversores estáticos"),
            ("8301", "Cadeados, fechaduras e ferrolhos"), ("8301.40.00", "- Outras fechaduras; ferrolhos"),
            ("9503.00.10", "Brinquedos de rodas concebidos para serem montados por crianças"), ("9503", "Triciclos e outros brinquedos"),
            ("8471.30.12", "Computadores portáteis (antigo)"), ("95", "Brinquedos, jogos, artigos para divertimento")]
    noms = [{"Codigo": c, "Descricao": d, "Data_Inicio": "01/04/2022", "Data_Fim": "31/12/9999", "Tipo_Ato_Ini": "Res Camex",
             "Numero_Ato_Ini": "272", "Ano_Ato_Ini": "2021"} for c, d in rows]
    noms[10]["Data_Fim"] = "31/03/2022"
    return json.dumps({"Data_Ultima_Atualizacao_NCM": "Vigente a partir de 01/04/2025", "Ato": "Resolução Gecex nº 272/2021",
                       "Nomenclaturas": noms}, ensure_ascii=False).encode("utf-8")


def anatel_zip() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Número de Homologação", "Nome do Fabricante", "Modelo", "Nome Comercial", "Tipo do Produto",
                "Data da Homologação", "Situação do Certificado", "Solicitante"])
    w.writerow(["01234-23-05678", "SHENZHEN LOCKTECH CO., LTD.", "LT-X200", "Fechadura LT", "Transceptor de Radiação Restrita",
                "10/05/2023", "Emitido", "Importadora X"])
    w.writerow(["09876-22-01111", "SHENZHEN LOCKTECH CO., LTD.", "LT-X200 PRO", "Fechadura LT Pro", "Transceptor de Radiação Restrita",
                "02/02/2022", "Emitido", "Importadora X"])
    w.writerow(["05555-21-02222", "OUTRA FÁBRICA", "LTX200", "Outro", "Transceptor", "01/01/2021", "Cancelado", "Y"])
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr("produtos_certificados.csv", buf.getvalue().encode("latin-1"))
    return raw.getvalue()


# ------------------------------------------------------------------------- base regulatória
def test_bundled_documents_have_required_metadata(env):
    _, kb, _ = env
    docs = kb.all()
    assert len(docs) >= 20
    for d in docs:
        for k in REQUIRED:
            assert k in d, (d["id"], k)
        assert d["orgao"] and d["titulo"] and d["texto"] and d["url_oficial"].startswith(("https://", "http://"))
        assert d["status_atualizacao"] in json.loads(BUNDLED.read_text(encoding="utf-8"))["legenda_status"]
        assert d["texto_tipo"] == "resumo_gpi"
    orgs = {d["orgao"] for d in docs}
    assert {"Anatel", "Inmetro", "Receita Federal", "Siscomex", "Anvisa", "MAPA", "Ibama", "Exército"} <= orgs | {"Receita Federal / Siscomex"}


def test_every_doc_cited_by_rules_exists_and_is_current(env):
    _, kb, _ = env
    src = (ROOT / "backend/gpi/compliance/rules.py").read_text(encoding="utf-8")
    cited = set(re.findall(r'"((?:anatel|inmetro|rfb|siscomex|secex|anvisa|mapa|ibama|exercito)-[a-z0-9\-]+)"', src))
    assert len(cited) >= 15
    for did in cited:
        d = kb.doc(did)
        assert d, did
        assert not d["revogado"], did


def test_no_invented_norm_numbers_outside_kb():
    """Toda norma numerada citada nas regras/resumos tem documento próprio na base."""
    kbtxt = BUNDLED.read_text(encoding="utf-8")
    src = (ROOT / "backend/gpi/compliance/rules.py").read_text(encoding="utf-8")
    for n in re.findall(r"(?:Resolução|Portaria|Lei|Ato)\s+(?:n[ºo]\s*)?(\d[\d.]*/\d{4})", src):
        assert n in kbtxt, n


def test_revoked_doc_never_current_and_history_kept(env):
    db, kb, _ = env
    d = kb.doc("inmetro-port-302-2021")
    d2 = {k: v for k, v in d.items() if k not in ("revogado", "vigente", "origem")}
    d2["situacao"] = "revogado"
    res = kb.apply_pack({"formato": "gpi-base-regulatoria", "versao_base": "t", "documentos": [d2]}, "teste")
    assert res["revogados"] == 1
    assert kb.doc("inmetro-port-302-2021")["revogado"]
    assert not any(x["id"] == "inmetro-port-302-2021" for x in kb.search("brinquedos", tags=["brinquedo"]))
    assert kb.history("inmetro-port-302-2021")[0]["situacao"] == "vigente"
    r = E.analyze(db, kb, NcmTable(db), {"nome_comercial": "Carrinho", "brinquedo": "sim", "destinacao": "comercializacao"})
    inm = [a for a in r["achados"] if a["orgao"] == "Inmetro"][0]
    assert "inmetro-port-302-2021" not in inm["documentos"] and any("revogado" in x for x in r["riscos"])


def test_stale_base_warns_and_blocks(env):
    db, kb, ncm = env
    later = date.today() + timedelta(days=400)
    fr = kb.freshness(later)
    assert fr["desatualizada"] and fr["bloquear_exigencias"] and "desatualizada" in fr["aviso"]
    r = E.analyze(db, kb, ncm, {"nome_comercial": "Câmera", "wifi": "sim", "destinacao": "comercializacao"}, today=later)
    an = [a for a in r["achados"] if a["orgao"] == "Anatel"][0]
    assert an["estado"] == 2 and "Rebaixado" in an["motivo"] and any("desatualizada" in x for x in r["riscos"])


def test_search_filters(env):
    _, kb, _ = env
    assert kb.search("homologação produtos de telecomunicações", orgao="Anatel")[0]["orgao"] == "Anatel"
    top = kb.search("classificação fiscal NCM", tags=["ncm"])
    assert top[0]["orgao"].startswith("Receita Federal") and all("ncm" in d["aplica_a"] or "NCM" in d["texto"] for d in top[:3])


# ------------------------------------------------------------------------- características e regras
def test_explicit_answer_wins_over_text():
    f = F.extract({"descricao_tecnica": "possui Bluetooth 5.0", "bluetooth": "nao"})
    assert f["caracteristicas"]["bluetooth"]["valor"] is False


def test_name_only_does_not_create_requirement():
    f = F.extract({"nome_comercial": "Fone Bluetooth Pro"})
    assert "bluetooth" not in f["caracteristicas"]
    assert f["indicios_nome"][0]["caracteristica"] == "bluetooth"
    an = R.anatel(f)[0]
    assert an["estado"] == 4


def test_text_evidence_multilingual():
    f = F.extract({"descricao_tecnica": "智能门锁，支持蓝牙和无线局域网，锂电池 5000mAh"})
    c = f["caracteristicas"]
    assert c["bluetooth"]["valor"] and c["wifi"]["valor"] and c["bateria_litio"]["valor"] and c["bateria"]["valor"]


@pytest.mark.parametrize("form,orgao,estado", [
    ({"nome_comercial": "Fechadura eletrônica", "descricao_tecnica": "com Wi-Fi e app", "destinacao": "comercializacao"}, "Anatel", 1),
    ({"nome_comercial": "Produto", "bluetooth": "sim"}, "Anatel", 2),
    ({"nome_comercial": "Módulo", "bluetooth": "sim", "produto_completo": "componente", "destinacao": "comercializacao"}, "Anatel", 2),
    ({"nome_comercial": "Rádio", "radiofrequencia": "sim", "destinacao": "amostra"}, "Anatel", 5),
    ({"nome_comercial": "Caneca", "wifi": "nao", "bluetooth": "nao", "radiofrequencia": "nao", "celular": "nao"}, "Anatel", 3),
    ({"nome_comercial": "Luminária LED", "descricao_tecnica": "luminária LED 220V 18W"}, "Inmetro", 5),
    ({"nome_comercial": "Carregador USB-C", "carregador_fonte": "sim", "destinacao": "comercializacao"}, "Inmetro", 5),
    ({"nome_comercial": "Boneca", "brinquedo": "sim", "destinacao": "comercializacao"}, "Inmetro", 1),
    ({"nome_comercial": "Air fryer", "alimentacao_rede": "sim"}, "Inmetro", 2),
    ({"nome_comercial": "Caneca"}, "Inmetro", 4),
    ({"nome_comercial": "Oxímetro", "equipamento_medico": "sim"}, "Anvisa", 5),
])
def test_state_matrix(env, form, orgao, estado):
    db, kb, ncm = env
    r = E.analyze(db, kb, ncm, form, save=False)
    found = [a for a in r["achados"] if a["orgao"] == orgao]
    assert found and found[0]["estado"] == estado, [(a["orgao"], a["estado"], a["titulo"]) for a in r["achados"]]
    if estado == 3:
        assert "NÃO representa dispensa" in found[0]["observacao"]


def test_never_says_released(env):
    db, kb, ncm = env
    for form in ({"nome_comercial": "Caneca", "wifi": "nao", "bluetooth": "nao", "radiofrequencia": "nao", "celular": "nao"},
                 {"nome_comercial": "Fone", "bluetooth": "sim", "destinacao": "comercializacao"}):
        txt = json.dumps(E.analyze(db, kb, ncm, form, save=False), ensure_ascii=False).lower()
        assert "liberado para importar" not in txt and "dispensado" not in txt
    assert "liberad" not in (ROOT / "backend/gpi/compliance/rules.py").read_text(encoding="utf-8").lower()


def test_result_structure_and_persistence(env):
    db, kb, ncm = env
    r = E.analyze(db, kb, ncm, {"nome_comercial": "Fechadura inteligente", "modelo": "LT-X200", "fabricante": "Shenzhen LockTech",
                                "descricao_tecnica": "Wi-Fi 2.4 GHz, Bluetooth LE, 4x pilhas AA", "destinacao": "comercializacao",
                                "product_id": "fechadura-inteligente", "variante": "wifi"})
    for k in ("por_orgao", "documentos_necessarios", "proximas_acoes", "fontes", "informacoes_faltantes", "riscos", "limitacoes",
              "checklist", "consulta_manual", "frescor_base"):
        assert k in r
    assert [o["orgao"] for o in r["por_orgao"]][:2] == ["Anatel", "Inmetro"]
    assert all(f.get("ultima_verificacao") and f.get("url_oficial") for f in r["fontes"])
    assert E.load(db, r["id"])["produto"]["product_id"] == "fechadura-inteligente"
    h = E.history(db, "fechadura-inteligente")
    assert h and h[0]["resumo"][0]["orgao"] == "Anatel"


def test_variants_are_analyzed_independently(env):
    db, kb, ncm = env
    base = {"nome_comercial": "Fechadura", "product_id": "fechadura", "destinacao": "comercializacao", "celular": "nao", "radiofrequencia": "nao"}
    a = E.analyze(db, kb, ncm, {**base, "variante": "wifi", "wifi": "sim", "bluetooth": "nao"})
    b = E.analyze(db, kb, ncm, {**base, "variante": "mecanica", "wifi": "nao", "bluetooth": "nao"})
    sa = [x for x in a["achados"] if x["orgao"] == "Anatel"][0]["estado"]
    sb = [x for x in b["achados"] if x["orgao"] == "Anatel"][0]["estado"]
    assert (sa, sb) == (1, 3)


# ------------------------------------------------------------------------- NCM
def test_ncm_validation_hierarchy_and_candidates(env):
    db, kb, ncm = env
    assert ncm.validate("8517.62")["estado"] == "formato_invalido"
    assert ncm.validate("85176277")["estado"] == "tabela_nao_carregada"
    r = ncm.load_bytes(ncm_fixture(), "teste")
    assert r["codigos"] == 12 and ncm.meta()["ato"] == "Resolução Gecex nº 272/2021"
    v = ncm.validate("8517.62.77")
    assert v["estado"] == "valida" and [h["nivel"] for h in v["hierarquia"]][:2] == ["capítulo", "posição"]
    assert ncm.validate("8471.30.12")["estado"] == "expirada"
    assert ncm.validate("1234.56.78")["estado"] == "inexistente"
    cands = ncm.candidates("carregador de acumuladores USB")
    assert cands and cands[0]["codigo"] == "8504.40.10" and "não é classificação" in cands[0]["aviso"]
    f = F.extract({"brinquedo": "sim"})
    assert ncm.validate("8301.40.00", f)["alertas"]


def test_ncm_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_official(b'{"x": 1}')


# ------------------------------------------------------------------------- homologações
def test_anatel_open_data_exact_vs_similar(env):
    db, *_ = env
    r = C.load_anatel_zip(db, anatel_zip(), "teste")
    assert r["registros"] == 3
    res = C.anatel_lookup(db, modelo="LT-X200", fabricante="Shenzhen LockTech")
    corr = {x["modelo"]: x["correspondencia"] for x in res["resultados"]}
    assert corr["LT-X200"] == "modelo_exato"
    assert corr["LT-X200 PRO"] == "semelhante" and corr.get("LTX200") == "semelhante"     # outro fabricante
    assert "NÃO vale" in res["aviso"]
    assert C.anatel_lookup(db, numero="01234-23-05678")["resultados"][0]["correspondencia"] == "numero_informado"


def test_anatel_not_loaded_points_to_manual(env):
    db, *_ = env
    res = C.anatel_lookup(db, modelo="X")
    assert not res["resultados"] and res["consulta_manual"].startswith("https://sistemas.anatel.gov.br")


def test_record_manual_check_validation(env):
    db, *_ = env
    assert C.record_check(db, None, "Inmetro", {"marca": "X"}, "nao_encontrado", "consulta 03/11", "usuário") > 0
    with pytest.raises(ValueError):
        C.record_check(db, None, "Inmetro", {}, "liberado", "", "u")


# ------------------------------------------------------------------------- anexos
def _office(extra: dict | None = None) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   "<w:body><w:p><w:r><w:t>Módulo Bluetooth BLE 5.0, 2.4 GHz</w:t></w:r></w:p></w:body></w:document>")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return b.getvalue()


def test_attachments_safe_handling(env, tmp_path):
    db, *_ = env
    a = AT.store(db, tmp_path, None, "../../etc/ficha técnica.txt", "Produto com Wi-Fi 802.11n e bateria Li-ion".encode())
    assert a["nome"] == "ficha técnica.txt" and (tmp_path / "compliance" / "anexos").exists()
    assert "Wi-Fi" in AT.texts(db, [a["id"]])[0]
    d = AT.store(db, tmp_path, None, "spec.docx", _office())
    assert "Bluetooth" in AT.texts(db, [d["id"]])[0]
    for name, data, msg in [("virus.exe", b"MZ...", "formato"), ("fake.pdf", b"MZ\x90\x00", "não corresponde"),
                            ("macro.docx", _office({"word/vbaProject.bin": "x"}), "macros"), ("x.docm", _office(), "formato"),
                            ("p.html", b"<html><script>", "formato"), ("s.txt", b"#!/bin/sh\nrm -rf /", "ativo"),
                            ("big.txt", b"a" * (AT.MAX_FILE + 1), "10 MB"), ("e.txt", b"", "vazio")]:
        with pytest.raises(AT.AttachmentError, match=msg):
            AT.inspect(name, data)


def test_attachment_text_feeds_features(env, tmp_path):
    db, kb, ncm = env
    a = AT.store(db, tmp_path, None, "manual.txt", "Este produto possui comunicação 4G LTE com cartão SIM".encode())
    r = E.analyze(db, kb, ncm, {"nome_comercial": "Rastreador", "destinacao": "comercializacao"}, AT.texts(db, [a["id"]]), [a])
    assert r["caracteristicas"]["celular"]["origem"] == "anexo"
    assert [x for x in r["achados"] if x["orgao"] == "Anatel"][0]["estado"] == 1


# ------------------------------------------------------------------------- atualização
class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def request_json(self, url, **kw):
        self.calls.append(url)
        if url not in self.pages:
            from gpi.connectors.http import SourceError
            raise SourceError("HTTP 404", "http", status=404)
        return {"_bytes": self.pages[url]}


def test_online_update_detects_change_keeps_history_and_never_touches_rules(env):
    db, kb, _ = env
    url = kb.doc("secex-port-249-2023")["url_oficial"]
    h1 = FakeHttp({url: b"%PDF-1.7 versao 1"})
    r = U.check_online(db, kb, h1, only=["secex-port-249-2023", "anatel-res-715-2019"])
    assert r["registrados"] == 1 and any(d["resultado"] == "ignorado" for d in r["detalhes"])     # 715 aponta índice
    d = kb.doc("secex-port-249-2023")
    assert d["status_atualizacao"] == "verificado_automatico" and d["hash_sha256"] and d["versao"] == 1
    r = U.check_online(db, kb, FakeHttp({url: b"%PDF-1.7 versao 1"}), only=["secex-port-249-2023"])
    assert r["inalterados"] == 1 and kb.doc("secex-port-249-2023")["versao"] == 1
    r = U.check_online(db, kb, FakeHttp({url: b"%PDF-1.7 versao 2 alterada"}), only=["secex-port-249-2023"])
    d = kb.doc("secex-port-249-2023")
    assert r["alterados"] == 1 and d["status_atualizacao"] == "alterado_revisao" and d["versao"] == 2
    assert kb.history("secex-port-249-2023") and kb.conflicts()[0]["id"] == "secex-port-249-2023"
    assert U.history(db)[0]["alterados"] == 1


def test_non_official_url_is_not_fetched(env):
    db, kb, _ = env
    h = FakeHttp({})
    r = U.check_online(db, kb, h)
    assert not any("apify" in c or "lefosse" in c for c in h.calls)
    assert all(U.is_official(c) for c in h.calls)
    assert r["falhas"] >= 1


def test_offline_pack_requires_matching_hash(env):
    db, kb, _ = env
    raw = U.export_pack(kb, "2026.12.01")
    import hashlib
    sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="não confere"):
        U.import_pack(db, kb, raw, "0" * 64)
    assert U.import_pack(db, kb, raw, sha)["inalterados"] >= 20
    b = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zin, zipfile.ZipFile(b, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, zin.read(n))
        zout.writestr("script.py", "print(1)")
    bad = b.getvalue()
    with pytest.raises(ValueError, match="inesperados"):
        U.import_pack(db, kb, bad, hashlib.sha256(bad).hexdigest())


# ------------------------------------------------------------------------- API, relatórios e catálogo
def test_api_end_to_end_reports_and_checklist(tmp_path):
    s = Srv(tmp_path / "data")
    try:
        code, st = s.req("/api/compliance/status")
        assert code == 200 and st["documentos"] >= 20 and st["ia"]["modo_efetivo"] == "essencial"
        assert st["estados"]["3"] == "NÃO IDENTIFICADA NAS FONTES CONSULTADAS"
        code, up = s.req("/api/compliance/anexos", "Ficha: Bluetooth 5.3, bateria de lítio 300 mAh".encode(),
                         headers={"X-Filename": "ficha.txt", "Content-Type": "application/octet-stream"})
        assert code == 200
        code, r = s.req("/api/compliance/analisar", {"formulario": {"nome_comercial": "Fone sem fio", "modelo": "TWS-9",
                                                                    "destinacao": "comercializacao", "product_id": "fone-tws"},
                                                     "anexos": [up["id"]]})
        assert code == 200 and r["id"]
        assert [a for a in r["achados"] if a["orgao"] == "Anatel"][0]["estado"] == 1
        code, h = s.req("/api/compliance/analises?product_id=fone-tws")
        assert h["analises"][0]["id"] == r["id"]
        for tipo in ("regulatorio", "checklist_fornecedor"):
            for fmt in ("pdf", "xlsx"):
                code, rep = s.req("/api/reports/generate", {"tipo": tipo, "formato": fmt, "filtros": {"analise_id": r["id"]}})
                assert code == 200 and rep["status"] == "gerado", rep
        code, rep = s.req("/api/reports/generate", {"tipo": "regulatorio", "formato": "xlsx", "filtros": {}})
        assert code == 400 or rep.get("status") == "erro"
        code, ck = s.req(f"/api/compliance/checklist/{r['id']}")
        assert any(i["zh"] for i in ck["itens"]) and "NÃO" in ck["aviso_internacional"]
        code, _ = s.req("/api/compliance/analisar", {"formulario": {}})
        assert code == 400
        code, sup = s.req("/api/compliance/fornecedores", {"nome": "Shenzhen LockTech", "nome_local": "深圳锁科技", "cidade": "Shenzhen"})
        assert code == 200
        code, lst = s.req("/api/compliance/fornecedores")
        assert lst["fornecedores"][0]["fonte"] == "informado pelo usuário"
        code, ans = s.req("/api/compliance/assistente", {"pergunta": "Qual a diferença entre certificação, homologação e anuência?"})
        assert code == 200 and ans["modo"] == "essencial" and "Anuência" in ans["resposta"]
        code, ans = s.req("/api/compliance/assistente", {"pergunta": "Um produto com Bluetooth precisa de homologação?"})
        assert "Anatel" in ans["resposta"] and ans["fontes"]
    finally:
        s.stop()


def test_regulatory_report_has_17_sections(env, tmp_path):
    db, kb, ncm = env
    from gpi.reports import regulatory as RG
    a = E.analyze(db, kb, ncm, {"nome_comercial": "Fechadura", "wifi": "sim", "destinacao": "comercializacao"})
    ds = RG.build(E.load(db, a["id"]))
    assert [n for n, _ in ds["secoes"]] == RG.SECTIONS and len(RG.SECTIONS) == 17
    from gpi.reports.xlsx import write as wx
    from gpi.reports.pdf import write as wp
    wx(ds, tmp_path / "r.xlsx")
    wp(ds, tmp_path / "r.pdf")
    from openpyxl import load_workbook
    wb = load_workbook(tmp_path / "r.xlsx")
    assert len(wb.sheetnames) >= 10
    from pypdf import PdfReader
    txt = " ".join(p.extract_text() or "" for p in PdfReader(tmp_path / "r.pdf").pages)
    assert "Análise Anatel" in txt and "Limitações" in txt and "EXIGÊNCIA IDENTIFICADA" in txt
    ck = RG.build_checklist(E.load(db, a["id"]))
    wp(ck, tmp_path / "c.pdf")                                  # chinês simplificado com fonte CJK
    assert (tmp_path / "c.pdf").stat().st_size > 3000


def test_catalog_button_and_frontend_wiring():
    js = (ROOT / "frontend/v07.js").read_text(encoding="utf-8")
    assert "Analisar requisitos de importação" in js
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert "#conformidade" in html and "/static/v07.js" in html
