"""Ficha de investigação regulatória (v0.9.1 MVP) — complementa o Assistente Regulatório existente (regras + base de
documentos oficiais + IA local opcional) com: identificação técnica do produto, questões técnicas a responder, registros
Anatel/Inmetro locais classificados por correspondência e um checklist. NENHUMA obrigação é afirmada aqui: requisitos
vêm só das regras/documentos já fundamentados do assistente e ficam "a confirmar"; normas não são inventadas."""
from __future__ import annotations

from ..products import lexicon as LX

QUESTIONS = {
    "Eletroportáteis": ["Tipo de alimentação (tomada, bateria, USB)", "Tensão nominal (127 V, 220 V ou bivolt)", "Potência nominal (W)",
                        "Possui elemento de aquecimento? Temperatura máxima", "Materiais e revestimentos em contato com alimentos",
                        "Classe de isolação elétrica / aterramento", "Tipo de plugue e cabo de alimentação", "Fabricante e modelo técnico exatos",
                        "Possui comunicação sem fio (Wi-Fi/Bluetooth)?"],
    "Celulares e acessórios": ["Tecnologias de radiofrequência (Wi-Fi, Bluetooth, NFC, celular)", "Potência de saída / carga (W)",
                               "Bateria interna (tipo e capacidade em Wh/mAh)", "Tensão de entrada e saída", "Fabricante e modelo técnico exatos"],
}
DEFAULT_Q = ["Função e uso do produto", "Alimentação elétrica (se houver)", "Comunicação sem fio (se houver)", "Público (adulto/infantil)",
             "Materiais", "Fabricante e modelo técnico exatos"]
MATCH = ["Modelo exato confirmado", "Fabricante e modelo correspondentes", "Produto semelhante", "Apenas mesma categoria", "Correspondência não confirmada"]


def _registry_matches(db, terms: list[str], fabricante: str | None, modelo: str | None) -> dict:
    from ..regulatory import registry as R
    from .store import norm_company
    out, seen = [], set()
    for t in terms:
        try:
            res = R.search_anatel(db, {"produto": t}, limit=100)["resultados"]
        except Exception:  # noqa: BLE001
            res = []
        for r in res:
            k = (r.get("orgao"), r.get("registro"), r.get("modelo"))
            if k in seen:
                continue
            seen.add(k)
            mm = modelo and r.get("modelo") and modelo.strip().lower() == str(r["modelo"]).strip().lower()
            fm = fabricante and r.get("fabricante") and norm_company(fabricante) == norm_company(r["fabricante"])
            cls = MATCH[0] if mm and fm else MATCH[1] if (mm or fm) and (modelo or fabricante) else MATCH[2]
            out.append({**{k2: r.get(k2) for k2 in ("orgao", "registro", "data", "fabricante", "pais_fabricante", "modelo", "empresa", "situacao")},
                        "correspondencia": cls})
    order = {c: i for i, c in enumerate(MATCH)}
    out.sort(key=lambda x: order[x["correspondencia"]])
    try:
        st = R.anatel_status(db)
    except Exception:  # noqa: BLE001
        st = {}
    return {"itens": out[:30], "total": len(out), "base_anatel": st,
            "regra": "Homologação de produto semelhante NÃO vale para outro modelo. Só 'Modelo exato confirmado' (fabricante + modelo) "
                     "indica que o mesmo produto já foi homologado — e ainda assim o titular é outra empresa."}


def ficha(db, question: str, answer: dict | None = None, fabricante: str | None = None, modelo: str | None = None) -> dict:
    from ..intel import understanding as U
    from . import naming as NM
    u = U.understand(question[:300], None)
    pid = u.get("produto_id") if u.get("estado") in ("confirmada", "provavel") else None
    head = (pid or "").split(":")[0].split("+")[0]
    cat = (LX.CONCEPTS.get(head) or (None, None))[1]
    attrs = {k: v for k, v in (u.get("atributos") or {}).items() if v}
    qs = QUESTIONS.get(cat, DEFAULT_Q)
    known = {"Potência nominal (W)": attrs.get("potencia_w"), "Tensão nominal (127 V, 220 V ou bivolt)": attrs.get("tensao"),
             "Fabricante e modelo técnico exatos": modelo or attrs.get("modelo")}
    questoes = [{"questao": q, "resposta": known.get(q), "situacao": "informado" if known.get(q) else "pendente"} for q in qs]
    names = [x for x in {NM.name_of(db, pid) if pid else None, (NM.describe(db, pid)["traducoes"].get("pt") if pid else None),
                         question.strip()[:80]} if x]
    reqs = []
    for a in (answer or {}).get("achados") or []:
        reqs.append({"requisito_potencial": a.get("titulo"), "orgao": a.get("orgao"), "regra": a.get("regra"),
                     "fundamento": ", ".join(a.get("documentos") or []), "aplicabilidade": a.get("estado_rotulo") or "a confirmar",
                     "evidencia": "; ".join(a.get("evidencias") or []) or a.get("motivo"), "situacao": "não confirmado",
                     "pendencia": "; ".join(a.get("documentos_solicitar") or []) or "confirmar características técnicas",
                     "proxima_acao": a.get("proxima_acao")})
    regs = _registry_matches(db, names, fabricante, modelo)
    checklist = ["Confirmar as respostas técnicas pendentes com o fabricante (ficha técnica e manual)",
                 "Pedir ao fabricante relatórios de ensaio e certificados existentes (com modelo idêntico)",
                 "Verificar no portal oficial do órgão se o MODELO exato já possui registro/certificado",
                 "Confirmar a NCM com despachante e consultar o tratamento administrativo (LPCO) no Portal Único",
                 "Registrar a decisão e anexos na análise de conformidade do GPI"]
    return {"produto": NM.name_of(db, pid) if pid else question.strip()[:80], "identificacao": u.get("estado"), "produto_id": pid,
            "categoria_provavel": cat or "não identificada", "familia_tecnica": head or None, "caracteristicas_informadas": attrs,
            "questoes_tecnicas": questoes, "requisitos_potenciais": reqs, "registros_locais": regs, "checklist": checklist,
            "documentos": [{"id": f.get("id"), "orgao": f.get("orgao"), "titulo": f.get("titulo"), "url": f.get("url_oficial"),
                            "situacao": f.get("situacao")} for f in (answer or {}).get("fontes") or []],
            "avisos": ["Triagem preliminar: nenhuma exigência é afirmada sem documento oficial; requisitos ficam 'a confirmar'.",
                       "Não presume certificação Inmetro obrigatória nem dispensada: depende das características e da regulamentação vigente.",
                       "Registros de produtos semelhantes não comprovam conformidade de outro modelo."]}
