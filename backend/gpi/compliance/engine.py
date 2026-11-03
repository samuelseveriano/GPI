"""Motor de Conformidade de Importação: características → regras → documentos → (IA) → verificação → resultado.

O resultado é uma TRIAGEM: separa as conclusões por órgão em cinco estados, cita documentos com data de verificação e
lista informações faltantes, documentos a solicitar e próximas ações. Nunca indica "liberado para importar".
"""
from __future__ import annotations

import json
from datetime import datetime

from . import certs as C
from . import checklist as CK
from . import features as F
from . import rules as R

FORM_FIELDS = ["nome_comercial", "categoria", "marca", "modelo", "fabricante", "pais_origem", "descricao_tecnica", "finalidade",
               "tipo_importacao", "destinacao", "ncm", "tensao", "potencia", "frequencia", "bateria", "bateria_litio", "wifi",
               "bluetooth", "radiofrequencia", "celular", "componentes", "material", "documentacao_disponivel",
               "produto_completo", "publico_infantil", "brinquedo", "instrumento_medicao", "equipamento_medico",
               "contato_alimentos", "alimentacao_rede", "carregador_fonte", "produto_controlado", "product_id", "variante",
               "familia"]
SEVERITY = {5: 5, 1: 4, 2: 3, 4: 2, 3: 1}     # para resumir um órgão: revisão > exigência > potencial > faltam dados > não identificada
ORDER = ["Anatel", "Inmetro", "Receita Federal", "Siscomex", "Anvisa", "MAPA", "Ibama", "Exército"]
LIMITACOES = [
    "Ferramenta de triagem e apoio à investigação regulatória; não é autoridade certificadora nem decisão oficial.",
    "Não substitui Receita Federal, Siscomex, Anatel, Inmetro, órgãos anuentes, despachante aduaneiro ou profissionais "
    "de conformidade regulatória.",
    "“Não identificada nas fontes consultadas” não representa dispensa: a ausência de regra na base não equivale à "
    "inexistência de obrigação legal.",
    "A base regulatória local cobre um conjunto limitado de normas e orientações oficiais, com as datas de verificação "
    "indicadas; normas podem ter sido alteradas depois dessas datas.",
    "A classificação fiscal (NCM) e o tratamento administrativo precisam ser confirmados no Sistema Classif e no "
    "Simulador de Tratamento Administrativo do Portal Único.",
]


def clean_form(form: dict) -> dict:
    out = {}
    for k in FORM_FIELDS:
        v = form.get(k)
        if v is None:
            continue
        out[k] = str(v).strip()[:4000 if k == "descricao_tecnica" else 300]
    return out


def analyze(db, kb, ncm_table, form: dict, attachment_texts: list[str] | None = None, attachments: list[dict] | None = None,
            llm=None, cfg: dict | None = None, mode: str = "essencial", save: bool = True, today=None) -> dict:
    form = clean_form(form)
    feats = F.extract(form, attachment_texts)
    ncm_info = None
    candidatos = []
    if form.get("ncm"):
        ncm_info = ncm_table.validate(form["ncm"], feats, today=today)
    else:
        candidatos = ncm_table.candidates(" ".join(filter(None, [form.get("descricao_tecnica"), form.get("material"),
                                                                 form.get("componentes")])))
    achados = R.run(feats, ncm_info)
    fresh = kb.freshness(today)
    riscos = []
    if fresh["bloquear_exigencias"]:
        for a in achados:
            if a["estado"] == 1:
                a["estado"], a["estado_rotulo"] = 2, R.STATE_LABEL[2]
                a["motivo"] += " (Rebaixado: base regulatória desatualizada.)"
    if fresh.get("aviso"):
        riscos.append(fresh["aviso"])
    # documentos citados: só os existentes e não revogados; inexistentes ou revogados viram alerta
    fontes = {}
    for a in achados:
        ok = []
        for did in a["documentos"]:
            d = kb.doc(did)
            if not d:
                riscos.append(f"Regra {a['regra']} cita documento ausente da base ({did}) — revisão necessária.")
                continue
            if d["revogado"]:
                riscos.append(f"Documento {did} está revogado e não foi usado como vigente.")
                continue
            ok.append(did)
            fontes[did] = {k: d.get(k) for k in ("id", "orgao", "tipo", "numero", "titulo", "data_publicacao", "vigencia_inicio",
                                                  "situacao", "ultima_verificacao", "url_oficial", "localizar_no_portal",
                                                  "status_atualizacao", "versao", "hash_sha256", "fontes_da_verificacao")}
        a["documentos"] = ok
        a["fontes"] = [fontes[x] for x in ok]
    conflitos = [c for c in kb.conflicts() if c["id"] in fontes]
    for c in conflitos:
        riscos.append(f"Conflito/alteração em {c['id']}: {c['motivo']}")
    for a in achados:
        if a["estado"] == 5:
            riscos.append(f"{a['orgao']}: {a['titulo']} — revisão especializada necessária.")
        elif a["estado"] == 1:
            riscos.append(f"{a['orgao']}: {a['titulo']} — exigência identificada; importar/comercializar sem atendê-la "
                          "pode resultar em retenção, apreensão ou impedimento de venda.")
    if feats["indicios_nome"]:
        riscos.append("Há características sugeridas apenas pelo nome/categoria; o GPI não as considerou sem confirmação técnica.")
    for at in attachments or []:
        if at.get("pdf_com_conteudo_ativo"):
            riscos.append(f"O anexo {at['nome']} contém elementos ativos de PDF; foi apenas lido como texto, sem executar nada.")
    cert = None
    if form.get("modelo") and any(a["orgao"] == "Anatel" and a["estado"] in (1, 2, 5) for a in achados):
        cert = C.anatel_lookup(db, modelo=form.get("modelo", ""), fabricante=form.get("fabricante", ""))
    por_orgao = []
    for org in ORDER + sorted({a["orgao"] for a in achados} - set(ORDER)):
        items = [a for a in achados if a["orgao"] == org]
        if items:
            por_orgao.append({"orgao": org, "pior_estado": max((i["estado"] for i in items), key=SEVERITY.get),
                              "achados": items})
    docs_needed, faltantes, acoes = [], [], []
    for a in achados:
        for d in a["documentos_solicitar"]:
            if d not in docs_needed:
                docs_needed.append(d)
        for q in a["perguntas"]:
            if q not in faltantes:
                faltantes.append(q)
        if a.get("proxima_acao") and a["proxima_acao"] not in acoes:
            acoes.append(a["proxima_acao"])
    res = {
        "criado_em": datetime.now().isoformat(timespec="seconds"),
        "produto": {k: form.get(k) for k in ("nome_comercial", "categoria", "marca", "modelo", "fabricante", "pais_origem",
                                             "product_id", "variante", "familia")},
        "operacao": {"finalidade": form.get("finalidade"), "tipo_importacao": form.get("tipo_importacao"),
                     "destinacao": form.get("destinacao"), "produto_completo": form.get("produto_completo"), **feats["operacao"]},
        "informacoes_tecnicas": F.describe(feats), "formulario": form,
        "caracteristicas": feats["caracteristicas"], "indicios_nome": feats["indicios_nome"],
        "ncm": ncm_info, "ncm_candidatos": candidatos, "achados": achados, "por_orgao": por_orgao,
        "documentos_necessarios": docs_needed, "informacoes_faltantes": faltantes, "proximas_acoes": acoes,
        "riscos": riscos, "fontes": list(fontes.values()), "frescor_base": fresh, "conflitos": conflitos,
        "certificados": cert, "consulta_manual": C.manual_links(form.get("marca", ""), form.get("modelo", "")),
        "limitacoes": LIMITACOES, "anexos": [{k: at.get(k) for k in ("id", "nome", "tipo", "tamanho", "sha256")} for at in attachments or []],
        "aviso": "Triagem regulatória — não é decisão oficial nem autorização de importação.",
        "modo": "essencial",
    }
    res["checklist"] = CK.build(res)
    if mode == "ia_local" and llm is not None:
        from ..ai.assistant import answer
        q = (f"Explique, para o produto {form.get('nome_comercial') or 'analisado'}, as exigências identificadas, as "
             "informações faltantes e as próximas verificações.")
        ai = answer(q, kb, llm, {**(cfg or {}), "ia_modo": "ia_local"}, {"formulario": form, "ncm": ncm_info})
        res["explicacao"] = {"modo": ai["modo"], "texto": ai["resposta"], "verificacao": ai.get("verificacao"),
                             "aviso": ai.get("aviso_ia"), "geracao": ai.get("geracao")}
        res["modo"] = ai["modo"]
    if save:
        cur = db.execute("INSERT INTO compliance_analyses (criado_em, produto, product_id, entrada, resultado, base_versao, modo) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (res["criado_em"], form.get("nome_comercial") or form.get("modelo") or "produto", form.get("product_id"),
                          json.dumps(form, ensure_ascii=False), json.dumps(res, ensure_ascii=False, default=str),
                          fresh.get("versao"), res["modo"]))
        res["id"] = int(cur.lastrowid)
        if attachments:
            for at in attachments:
                db.execute("UPDATE compliance_attachments SET analysis_id = ? WHERE id = ? AND analysis_id IS NULL",
                           (res["id"], at["id"]))
    return res


def load(db, aid: int) -> dict | None:
    r = db.query("SELECT id, resultado FROM compliance_analyses WHERE id = ?", (aid,))
    if not r:
        return None
    out = json.loads(r[0]["resultado"])
    out["id"] = r[0]["id"]
    return out


def history(db, product_id: str | None = None, limit: int = 100) -> list[dict]:
    q = "SELECT id, criado_em, produto, product_id, modo, base_versao, resultado FROM compliance_analyses"
    p: tuple = ()
    if product_id:
        q += " WHERE product_id = ?"
        p = (product_id,)
    out = []
    for r in db.query(q + " ORDER BY id DESC LIMIT ?", p + (limit,)):
        res = json.loads(r["resultado"])
        out.append({"id": r["id"], "criado_em": r["criado_em"], "produto": r["produto"], "product_id": r["product_id"],
                    "modo": r["modo"], "base_versao": r["base_versao"],
                    "resumo": [{"orgao": o["orgao"], "estado": o["pior_estado"], "rotulo": R.STATE_LABEL[o["pior_estado"]]}
                               for o in res.get("por_orgao", [])]})
    return out
