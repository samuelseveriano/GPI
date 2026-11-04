"""v0.8 — Regulatory Competitor Intelligence.

As linhas da Anatel abaixo são REGISTROS REAIS e públicos, copiados do arquivo oficial de dados abertos
(produtos_certificados.zip, lido pela sonda do CI em 04/11/2026), com o cabeçalho oficial exato. A linha 'TESTE…'
é sintética e marcada como tal (usada só para o caso 'homologação emitida/vigente').
"""
from __future__ import annotations

import io
import zipfile

import pytest

from gpi.db import Database
from gpi.regulatory import registry as R
from gpi.regulatory.api import record_lookup, search_all

HEADER = ("Data da Homologação;Número de Homologação;Nome do Solicitante;CNPJ do Solicitante;Certificado de Conformidade Técnica;"
          "Data do Certificado de Conformidade Técnica;Data de Validade do Certificado;Código de Situação do Certificado;"
          "Situação do Certificado;Código de Situação do Requerimento;Situação do Requerimento;Nome do Fabricante;Modelo;"
          "Nome Comercial;Categoria do Produto;Tipo do Produto;IC_ANTENA;IC_ATIVO;País do Fabricante;CodUIT;CodISO")
REAL = [
    "19/03/2003;003310301861;Canon do Brasil IndUstria e ComErcio LTDA.;46266771000126;1163.TEL.1638.01.A.0/9;13/12/2002;"
    "2007-12-13 00:00:00.000000;6;Suspenso;10;Homologação Suspensa;Copyer Industries Development Co., Ltd.;imageRunner 2200;"
    "imageRunner 2200;1;Equipamento de Fac-Símile;N;S;China;CHN;CHN",
    "07/04/2009;005190904712;BRH REPRESENTAÇÃO COMERCIAL LTDA.;07479382000127;03178/09;12/03/2009;2011-03-12 00:00:00.000000;6;"
    "Suspenso;10;Homologação Suspensa;KYE Systems Corp.;GK-070010/T;GK-070010/T;2;Equipamento de Radiocomunicação de Radiação "
    "Restrita;N;S;Taiwan;TWN;TWN",
    "12/01/2018;004901402678;Nikon do Brasil Ltda;12484782000160;00081683;07/02/2014;2020-02-07 00:00:00.000000;6;Suspenso;10;"
    "Homologação Suspensa;Nikon Corporation;DW092;DW092;2;Transceptor de Radiação Restrita;N;S;Japão;J;JPN",
]
SYNTH = ("05/10/2026;TESTE00000001;EMPRESA TESTE IMPORTADORA LTDA;00000000000000;TESTE-CERT-1;01/09/2026;"
         "2028-09-01 00:00:00.000000;2;Preenchimento Concluído;6;Homologação Emitida;Shenzhen Teste Electronics Co., Ltd.;"
         "QC-20W-PD;Carregador Teste 20W;1;Carregador para Telefone Celular;N;S;China;CHN;CHN")


def zip_bytes(lines):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Produtos_Homologados_Anatel.csv", ("﻿" + "\n".join([HEADER] + lines)).encode("utf-8"))
    return b.getvalue()


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "r.sqlite")
    R.load_anatel_zip_v2(d, zip_bytes(REAL + [SYNTH]), "teste")
    yield d
    d.close()


def test_real_header_and_fields_loaded(db):
    st = R.anatel_status(db)
    assert st["carregada"] and st["registros"] == 4
    r = db.query("SELECT * FROM anatel_registros WHERE numero_homologacao = '004901402678'")[0]
    assert r["solicitante"] == "Nikon do Brasil Ltda" and r["fabricante"] == "Nikon Corporation" and r["cnpj_solicitante"] == "12484782000160"
    assert r["data_homologacao"] == "2018-01-12" and r["validade_certificado"] == "2020-02-07" and r["pais_fabricante"] == "Japão"
    assert r["situacao_requerimento"] == "Homologação Suspensa" and r["situacao_certificado"] == "Suspenso"


def test_real_reference_exact_match_and_roles(db):
    res = search_all(db, {"modelo": "DW092", "fabricante": "Nikon", "orgao": "Anatel"})
    r = res["resultados"][0]
    assert r["correspondencia"] == R.EXACT and r["registro"] == "004901402678" and r["id_registro"].startswith("anatel:")
    assert r["papel"] == "titular" and r["empresa"] == "Nikon do Brasil Ltda" and r["fabricante"] == "Nikon Corporation"
    assert r["fonte_url"].startswith("https://sistemas.anatel.gov.br")
    papeis = {(x["empresa"], x["papel"]) for x in res["empresas"]["tabela"]}
    assert ("Nikon do Brasil Ltda", R.ROLES["titular"]) in papeis and ("Nikon Corporation", R.ROLES["fabricante"]) in papeis


def test_suspended_record_is_not_presented_as_valid(db):
    r = search_all(db, {"modelo": "GK-070010/T"})["resultados"][0]
    assert r["situacao"] == "Homologação Suspensa" and r["vigente"] is False
    ok = search_all(db, {"modelo": "QC-20W-PD"})["resultados"][0]
    assert ok["vigente"] is True


def test_different_manufacturer_is_only_probable(db):
    r = search_all(db, {"modelo": "DW092", "fabricante": "Canon"})["resultados"][0]
    assert r["correspondencia"] == R.PROBABLE


def test_similar_model_never_exact(db):
    res = search_all(db, {"tipo": "carregador", "modelo": "QC-65W-PD"})
    assert all(x["correspondencia"] != R.EXACT for x in res["resultados"])
    res2 = search_all(db, {"produto": "carregador"})
    assert res2["resultados"] and all(x["correspondencia"] == R.SIMILAR for x in res2["resultados"])


def test_not_found_and_source_unavailable(tmp_path, db):
    res = search_all(db, {"modelo": "ZZZ-NAO-EXISTE-999", "orgao": "Anatel"})
    assert not res["resultados"] and "SEM CORRESPONDÊNCIA CONFIRMADA" in res["por_orgao"][0]["mensagem"]
    empty = Database(tmp_path / "vazio.sqlite")
    res = search_all(empty, {"modelo": "DW092"})
    assert all(p.get("estado_fonte") == "indisponivel" for p in res["por_orgao"]) and not res["resultados"]


def test_compare_lists_matching_different_and_missing(db):
    rec = search_all(db, {"modelo": "DW092"})["resultados"][0]
    c = R.compare({"modelo": "DW092", "fabricante": "Nikon", "potencia": "5 W", "comunicacao_sem_fio": "Bluetooth"}, rec)
    assert c["tipo_correspondencia"] == R.EXACT and "NÃO é declaração de equivalência técnica" in c["conclusao"]
    assert any(x["caracteristica"] == "Potência" for x in c["faltantes"])
    c2 = R.compare({"modelo": "DW092", "fabricante": "Outra Marca"}, rec)
    assert c2["tipo_correspondencia"] == R.PROBABLE and c2["diferentes"]


def test_inmetro_file_import_and_search(tmp_path):
    d = Database(tmp_path / "i.sqlite")
    csv = ("Número do Registro;Razão Social;CNPJ;Marca;Modelo;Objeto;OCP;Situação;Data do Registro\n"
           "000123/2025;FORNECEDOR TESTE LTDA;00.000.000/0001-00;MarcaX;AF-5000;Fritadeira elétrica;OCP TESTE;Ativo;10/05/2025\n")
    info = R.load_inmetro_file(d, csv.encode("utf-8"), "teste.csv")
    assert info["registros"] == 1 and "modelo" in info["colunas_reconhecidas"]
    res = search_all(d, {"modelo": "AF5000", "marca": "marcax", "orgao": "Inmetro"})
    r = res["resultados"][0]
    assert r["correspondencia"] == R.EXACT and r["cnpj"] == "00000000000100" and r["organismo"] == "OCP TESTE"
    papeis = {x["papel"] for x in res["empresas"]["tabela"]}
    assert R.ROLES["organismo"] in papeis                   # organismo certificador não vira fabricante
    with pytest.raises(ValueError):
        R.load_inmetro_file(d, b"col1;col2\n1;2\n", "x.csv")


def test_manual_lookup_requires_official_source(db):
    with pytest.raises(ValueError):
        record_lookup(db, {"orgao": "Inmetro", "resultado": "nao_encontrado", "fonte_url": "https://example.com"})
    r = record_lookup(db, {"orgao": "Inmetro", "resultado": "encontrado_exato", "fonte_url": R.INMETRO_CONSULTA,
                           "numero_registro": "000123/2025", "responsavel": "Analista", "produto_id": "air_fryer"})
    assert r["id"] > 0
    assert search_all(db, {"modelo": "x", "produto_id": "air_fryer"})["manuais"][0]["numero_registro"] == "000123/2025"
