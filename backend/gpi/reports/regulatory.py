"""Relatório de Análise Regulatória de Produto (17 seções) e Checklist Técnico para Importação — no Centro de Relatórios."""
from __future__ import annotations

import uuid
from datetime import datetime

from .. import __version__
from ..compliance import engine as E
from ..compliance import rules as R
from .data import table

SECTIONS = ["Identificação do produto", "Informações técnicas utilizadas", "Finalidade da importação", "NCM informada ou candidata",
            "Análise Anatel", "Análise Inmetro", "Tratamento administrativo", "Outros órgãos potencialmente envolvidos",
            "Evidências", "Normas consultadas", "Informações faltantes", "Riscos", "Checklist documental",
            "Próximas verificações", "Data da análise", "Data da última atualização das fontes",
            "Limitações e necessidade de validação especializada"]


def _kv(tid, titulo, pairs, natureza="obs"):
    return table(tid, titulo, [("campo", "Campo"), ("valor", "Valor")],
                 [{"campo": k, "valor": "" if v is None else str(v)} for k, v in pairs], natureza)


def _findings(tid, titulo, items):
    return table(tid, titulo, [("estado", "Situação"), ("titulo", "Exigência"), ("motivo", "Motivo"), ("regra", "Regra"),
                               ("documentos", "Documentos"), ("perguntas", "Informações necessárias"), ("acao", "Próxima ação")],
                 [{"estado": f"{a['estado']} — {a['estado_rotulo']}", "titulo": a["titulo"], "motivo": a["motivo"] +
                   (" " + a["observacao"] if a.get("observacao") else ""), "regra": a["regra"],
                   "documentos": ", ".join(a["documentos"]), "perguntas": "; ".join(a["perguntas"]),
                   "acao": a.get("proxima_acao") or ""} for a in items], "der",
                 vazio="Nenhum resultado para este órgão nesta análise.", largura="larga")


def _meta(analysis: dict, run_id: str, tipo_nome: str) -> dict:
    fr = analysis.get("frescor_base") or {}
    return {"run_id": run_id, "gerado_em": datetime.now().isoformat(timespec="seconds"), "versao_software": __version__,
            "versao_dados": f"base regulatória {fr.get('versao') or '?'} (verificação mais antiga: {fr.get('ultima_verificacao') or '?'})",
            "filtros": {"analise_id": analysis.get("id")}, "filtros_texto": f"Análise nº {analysis.get('id')}",
            "fontes": sorted({f"{f['orgao']} — {f['titulo']}" for f in analysis.get("fontes", [])}), "modelos": [],
            "parametros": {"modo": analysis.get("modo")}, "criterios_ranking": "—", "tipo_nome": tipo_nome}


def build(analysis: dict, run_id: str | None = None) -> dict:
    run_id = run_id or uuid.uuid4().hex
    p = analysis["produto"]
    nome = p.get("nome_comercial") or p.get("modelo") or "produto"
    by = {o["orgao"]: o["achados"] for o in analysis["por_orgao"]}
    ncm = analysis.get("ncm") or {}
    ncm_rows = []
    if ncm:
        ncm_rows.append({"codigo": ncm.get("codigo_formatado"), "descricao": ncm.get("descricao") or "",
                         "situacao": ncm.get("estado"), "observacao": "; ".join(ncm.get("alertas") or []) or ncm.get("observacao") or ""})
    for c in analysis.get("ncm_candidatos") or []:
        ncm_rows.append({"codigo": c["codigo"], "descricao": c["descricao"], "situacao": "candidato", "observacao": c["aviso"]})
    outros = [a for o, items in by.items() if o not in ("Anatel", "Inmetro", "Receita Federal", "Siscomex") for a in items]
    ev = [{"orgao": a["orgao"], "regra": a["regra"], "evidencia": e} for a in analysis["achados"] for e in a["evidencias"]]
    ev += [{"orgao": "—", "regra": "nome/categoria", "evidencia": f"indício não considerado sem confirmação: {i['rotulo']} (“{i['trecho']}”)"}
           for i in analysis.get("indicios_nome", [])]
    fr = analysis.get("frescor_base") or {}
    cert = analysis.get("certificados") or {}
    cert_rows = [{"orgao": "Anatel", "numero": r.get("numero"), "fabricante": r.get("fabricante"), "modelo": r.get("modelo"),
                  "situacao": r.get("situacao"), "correspondencia": r.get("nota")} for r in (cert.get("resultados") or [])[:15]]
    secoes = [
        (SECTIONS[0], [_kv("identificacao", "Identificação do produto",
                           [("Nome comercial", nome), ("Categoria", p.get("categoria")), ("Marca", p.get("marca")),
                            ("Modelo", p.get("modelo")), ("Fabricante", p.get("fabricante")), ("País de origem", p.get("pais_origem")),
                            ("Produto do catálogo", p.get("product_id")), ("Família", p.get("familia")), ("Variante", p.get("variante"))])]),
        (SECTIONS[1], [table("tecnicas", "Características consideradas (com origem)", [("item", "Característica")],
                             [{"item": x} for x in analysis["informacoes_tecnicas"]], "obs",
                             vazio="Nenhuma característica técnica informada.")]),
        (SECTIONS[2], [_kv("finalidade", "Operação", [("Finalidade", analysis["operacao"].get("finalidade")),
                                                       ("Tipo de importação", analysis["operacao"].get("tipo_importacao")),
                                                       ("Destinação", analysis["operacao"].get("destinacao")),
                                                       ("Produto completo ou componente", analysis["operacao"].get("produto_completo"))])]),
        (SECTIONS[3], [table("ncm", "NCM", [("codigo", "Código"), ("descricao", "Descrição oficial"), ("situacao", "Situação"),
                                            ("observacao", "Observação")], ncm_rows, "der",
                             vazio="NCM não informada e tabela oficial sem candidatos para a descrição.")]),
        (SECTIONS[4], [_findings("anatel", "Anatel", by.get("Anatel", [])),
                       table("cert_anatel", "Homologações encontradas nos dados abertos da Anatel", [("numero", "Nº"),
                             ("fabricante", "Fabricante"), ("modelo", "Modelo"), ("situacao", "Situação"),
                             ("correspondencia", "Correspondência")], cert_rows, "obs",
                             vazio="Consulta não realizada ou sem resultados (dados abertos não carregados ou modelo não informado).")]),
        (SECTIONS[5], [_findings("inmetro", "Inmetro", by.get("Inmetro", []))]),
        (SECTIONS[6], [_findings("receita", "Receita Federal — classificação fiscal", by.get("Receita Federal", [])),
                       _findings("siscomex", "Siscomex — tratamento administrativo", by.get("Siscomex", []))]),
        (SECTIONS[7], [_findings("outros", "Outros órgãos", outros)]),
        (SECTIONS[8], [table("evidencias", "Evidências", [("orgao", "Órgão"), ("regra", "Regra"), ("evidencia", "Evidência")], ev,
                             "obs", vazio="Sem evidências textuais (apenas respostas do formulário).", largura="larga")]),
        (SECTIONS[9], [table("normas", "Normas e fontes oficiais consultadas", [("orgao", "Órgão"), ("numero", "Número"),
                             ("titulo", "Título"), ("situacao", "Situação"), ("verificacao", "Última verificação"),
                             ("status", "Status"), ("url", "URL oficial", "link")],
                             [{"orgao": f["orgao"], "numero": f.get("numero") or "—", "titulo": f["titulo"], "situacao": f["situacao"],
                               "verificacao": f.get("ultima_verificacao"), "status": f.get("status_atualizacao"),
                               "url": f.get("url_oficial")} for f in analysis["fontes"]], "obs", largura="larga")]),
        (SECTIONS[10], [table("faltantes", "Informações faltantes", [("item", "Pergunta")],
                              [{"item": x} for x in analysis["informacoes_faltantes"]], "der", vazio="Nenhuma.")]),
        (SECTIONS[11], [table("riscos", "Riscos", [("item", "Risco")], [{"item": x} for x in analysis["riscos"]], "der",
                              vazio="Nenhum risco adicional identificado pelas regras (não significa ausência de risco).")]),
        (SECTIONS[12], [table("checklist", "Documentos a solicitar ao fabricante", [("item", "Item"), ("pt", "Português"),
                              ("en", "English")], analysis["checklist"]["itens"], "der", largura="larga",
                              notas=[analysis["checklist"]["aviso_internacional"]])]),
        (SECTIONS[13], [table("proximas", "Próximas verificações", [("item", "Ação")],
                              [{"item": x} for x in analysis["proximas_acoes"]] +
                              [{"item": f"{m['orgao']}: {m['nome']} — {m['url']} ({m['como']})"} for m in analysis["consulta_manual"]],
                              "der")]),
        (SECTIONS[14], [_kv("data_analise", "Data da análise", [("Análise realizada em", analysis["criado_em"]),
                                                                ("Modo", analysis.get("modo")), ("Identificador", analysis.get("id"))])]),
        (SECTIONS[15], [_kv("data_fontes", "Atualização das fontes", [("Versão da base", fr.get("versao")),
                                                                      ("Verificação mais antiga", fr.get("ultima_verificacao")),
                                                                      ("Dias desde a verificação", fr.get("dias")),
                                                                      ("Aviso", fr.get("aviso") or "—")])]),
        (SECTIONS[16], [table("limitacoes", "Limitações", [("item", "Limitação")], [{"item": x} for x in analysis["limitacoes"]], "der")]),
    ]
    resumo_rows = [{"orgao": o["orgao"], "situacao": f"{o['pior_estado']} — {R.STATE_LABEL[o['pior_estado']]}",
                    "itens": len(o["achados"])} for o in analysis["por_orgao"]]
    ds = {"tipo": "regulatorio", "titulo": f"Global Product Intelligence — Relatório de Análise Regulatória: {nome}",
          "subtitulo": "Triagem regulatória de importação (Anatel, Inmetro, Receita Federal, Siscomex e outros órgãos). "
                       "Não é decisão oficial nem autorização de importação.",
          "secoes": secoes, "graficos": [], "texto": {}, "demo": False, "demo_motivo": None,
          "resumo": table("resumo", "Resumo por órgão", [("orgao", "Órgão"), ("situacao", "Situação mais relevante"),
                                                        ("itens", "Itens", "inteiro")], resumo_rows, "der"),
          "meta": _meta(analysis, run_id, "Relatório de Análise Regulatória de Produto")}
    return ds


def build_checklist(analysis: dict, run_id: str | None = None) -> dict:
    run_id = run_id or uuid.uuid4().hex
    ck = analysis["checklist"]
    nome = (analysis["produto"].get("nome_comercial") or analysis["produto"].get("modelo") or "produto")
    rows = [{"n": i, "pt": r["pt"], "en": r["en"] or "", "zh": r["zh"] or ""} for i, r in enumerate(ck["itens"], 1)]
    ds = {"tipo": "checklist_fornecedor", "titulo": f"Global Product Intelligence — Checklist Técnico para Importação: {nome}",
          "subtitulo": "Perguntas e documentos a solicitar ao fabricante (português, inglês e chinês simplificado).",
          "secoes": [("Checklist", [table("checklist", "Itens a solicitar", [("n", "#", "inteiro"), ("pt", "Português"),
                                          ("en", "English"), ("zh", "简体中文")], rows, "der", largura="larga",
                                          notas=[ck["aviso_internacional"], ck["aviso_traducao"]])])],
          "graficos": [], "texto": {}, "demo": False, "demo_motivo": None,
          "resumo": table("resumo", "Resumo", [("campo", "Campo"), ("valor", "Valor")],
                          [{"campo": "Produto", "valor": nome}, {"campo": "Itens", "valor": len(rows)},
                           {"campo": "Grupos", "valor": ", ".join(ck["grupos"])}], "der"),
          "meta": _meta(analysis, run_id, "Checklist Técnico para Importação")}
    return ds


def load_analysis(db, filtros: dict) -> dict:
    aid = (filtros or {}).get("analise_id")
    if not aid:
        raise ValueError("selecione uma análise regulatória")
    a = E.load(db, int(aid))
    if not a:
        raise ValueError("análise regulatória não encontrada")
    return a
