"""GPI v0.9 — Opportunity Intelligence 4.0 e Product Decision Intelligence.

Estágios (cada um só é atribuído com os dados que o sustentam):
 0 Identificado · 1 Novo sinal · 2 Em observação · 3 Investigação recomendada · 4 Investigação técnica ·
 5 Viabilidade comercial · 6 Viabilidade regulatória · 7 Decisão.
0–3 vêm das EVIDÊNCIAS; 4–7 só existem quando o usuário abre e conduz uma investigação (o GPI não inventa
fornecedores, preços, margens nem certificações). Também: próximas ações, ficha de investigação pré-preenchida,
respostas fundamentadas (sem LLM obrigatório), alertas com estado (novo/conhecido/resolvido) e painel executivo."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import commercial
from . import investigations as INV
from .semantics import COMMERCIAL, DEMAND, SEARCH

STAGES = {0: "Identificado", 1: "Novo sinal", 2: "Em observação", 3: "Investigação recomendada", 4: "Investigação técnica",
          5: "Viabilidade comercial", 6: "Viabilidade regulatória", 7: "Decisão"}
STAGE_RULE = {
    0: "o GPI reconheceu o produto em alguma fonte",
    1: "existe observação comercial ou de pesquisa nas últimas 5 semanas e ainda não há histórico",
    2: "há evidência de pesquisa ou comercial, mas sem persistência ou crescimento confirmado",
    3: "evidência COMERCIAL (classe A/B) persistente (≥ 4 semanas presentes e presença em ≥ 50% das coletas) "
       "OU crescimento de pesquisa confirmado, com identificação confirmada do produto",
    4: "investigação aberta pelo usuário em estado técnico",
    5: "investigação em análise comercial (preços/custos informados pelo usuário)",
    6: "investigação em análise regulatória",
    7: "decisão registrada (concluída ou arquivada)",
}
INV_STAGE = {"Investigação técnica": 4, "Investigação comercial": 5, "Aguardando fornecedor": 4, "Investigação regulatória": 6,
             "Concluído": 7, "Arquivado": 7}
GROWING = {"EMERGENTE", "CRESCIMENTO CONSISTENTE", "ACELERAÇÃO"}
ALERT_SQL = """CREATE TABLE IF NOT EXISTS alert_state (
    fingerprint TEXT PRIMARY KEY, categoria TEXT NOT NULL, tipo TEXT, produto_id TEXT, fonte TEXT, primeira_vez TEXT NOT NULL,
    ultima_vez TEXT NOT NULL, vezes INTEGER NOT NULL DEFAULT 1, estado TEXT NOT NULL, historico TEXT, resolvido_em TEXT)"""


def _ml_ev(p: dict) -> dict | None:
    return next((e for e in p["evidencias"] if e.get("fonte") in ("ml_trends", "mercadolivre_trends") or "mercado livre" in
                 (e.get("fonte_nome") or "").lower()), None)


def evidence_stage(p: dict, today: date) -> dict:
    evs = p.get("evidencias") or []
    classes = {commercial.evidence_class(e.get("tipo"))["classe"] for e in evs}
    comm = [e for e in evs if e.get("tipo") in (COMMERCIAL, DEMAND)]
    search = [e for e in evs if e.get("tipo") == SEARCH]
    ml = _ml_ev(p)
    d = (ml or {}).get("derivado") or {}
    present = d.get("semanas_presente") or len([h for h in (d.get("historico") or []) if h[1] is not None])
    persist = d.get("persistencia") or 0
    first = d.get("primeira_semana") or (ml or {}).get("periodo", "").split(" a ")[0]
    confirmed_ident = (p.get("correspondencia") or {}).get("estado", "confirmada") == "confirmada"
    crit = {"evidencia_comercial": bool(comm), "evidencia_pesquisa": bool(search),
            "persistencia_comercial": bool(comm and present >= 4 and persist >= 0.5),
            "crescimento_pesquisa_confirmado": p.get("situacao") in GROWING and bool(search),
            "identificacao_confirmada": confirmed_ident}
    recent = False
    try:
        if first and "W" in first:
            y, w = first.split("-W")
            recent = date.fromisocalendar(int(y), int(w), 1) >= today - timedelta(days=35)
    except ValueError:
        recent = False
    if confirmed_ident and comm and (crit["persistencia_comercial"] or crit["crescimento_pesquisa_confirmado"]):
        st = 3
    elif (comm or search) and recent and present <= 3:
        st = 1
    elif comm or search:
        st = 2
    else:
        st = 0
    missing = []
    if st < 3:
        if not comm:
            missing.append("evidência comercial (ranking de buscas, volume de pesquisa autorizado ou vendas)")
        elif not crit["persistencia_comercial"]:
            missing.append(f"persistência: presente em {present} semana(s); são necessárias ≥ 4 e presença em ≥ 50% das coletas")
        if not crit["crescimento_pesquisa_confirmado"]:
            missing.append("crescimento de pesquisa confirmado estatisticamente")
        if not confirmed_ident:
            missing.append("identificação confirmada do produto (revisar associação)")
    return {"estagio": st, "nome": STAGES[st], "regra": STAGE_RULE[st], "criterios": crit, "faltando": missing,
            "classes_evidencia": sorted(c for c in classes if c), "semanas_ranking": present, "persistencia_ranking": persist}


def next_actions(p: dict, st: int) -> list[str]:
    ident = p.get("identificacao") or {}
    acts = []
    if st <= 2:
        acts.append("Acompanhar novas observações (não há crescimento confirmado)")
    if not ident.get("variante"):
        acts.append("Identificar variantes técnicas (potência, capacidade, modelo) nos termos e anúncios")
    if st >= 1:
        acts += ["Verificar concorrentes e marcas presentes (eBay/Mercado Livre, fontes autorizadas)",
                 "Levantar preços por fontes autorizadas"]
    if st >= 2:
        acts += ["Pesquisar fornecedores (cadastro próprio — o GPI não sugere fornecedores)",
                 "Verificar requisitos técnicos e regulatórios (Anatel/Inmetro, NCM provável)"]
    if st >= 3:
        acts.append("Abrir investigação e documentar a decisão")
    return acts


def stages(payload: dict, db, today: date) -> dict:
    invs = {}
    for r in db.query("SELECT id, produto_id, estado, atualizado_em FROM investigations ORDER BY id"):
        if r["produto_id"]:
            invs[r["produto_id"]] = r
    out = []
    for pid, p in payload["produtos"].items():
        ev = evidence_stage(p, today)
        inv = invs.get(pid)
        inv_st = INV_STAGE.get(inv["estado"]) if inv else None
        item = {"produto_id": pid, "produto": (p.get("identificacao") or {}).get("produto") or pid,
                "categoria": (p.get("identificacao") or {}).get("categoria"), "situacao": p.get("situacao"),
                "estagio_evidencia": ev, "estagio_investigacao": {"estagio": inv_st, "nome": STAGES[inv_st], "investigacao_id": inv["id"],
                                                                 "estado": inv["estado"]} if inv_st else
                ({"estagio": None, "nome": "investigação aberta: " + inv["estado"], "investigacao_id": inv["id"], "estado": inv["estado"]} if inv else None),
                "estagio": max(ev["estagio"], inv_st or 0), "proximas_acoes": next_actions(p, ev["estagio"]),
                "fontes": p.get("fontes") or []}
        item["nome_estagio"] = STAGES[item["estagio"]]
        out.append(item)
    out.sort(key=lambda x: (-x["estagio"], x["produto"]))
    cnt = {STAGES[k]: sum(1 for x in out if x["estagio"] == k) for k in STAGES}
    return {"itens": out, "contagem": cnt, "regras": {STAGES[k]: v for k, v in STAGE_RULE.items()}}


def prefill(p: dict, ev: dict) -> dict:
    """Ficha de investigação com SÓ o que o GPI tem: nada de fornecedor, preço, margem ou certificação inventados."""
    ident = p.get("identificacao") or {}
    evs = []
    for e in p.get("evidencias") or []:
        c = commercial.evidence_class(e.get("tipo"))
        d = e.get("derivado") or {}
        val = ", ".join(f"{k}: {v}" for k, v in d.items() if k in ("momentum", "persistencia", "melhor_posicao", "semanas_presente")
                        and v is not None)
        evs.append(f"[{c['classe']} — {c['classe_nome']}] {e.get('fonte_nome')} · {e.get('mercado') or '—'} · {e.get('metrica')} · "
                   f"período {e.get('periodo') or '—'}" + (f" · {val}" if val else ""))
    lim = [f"Limitação: {m}" for m in ev["faltando"]]
    motivo = (f"Estágio {ev['estagio']} — {ev['nome']}: {ev['regra']}. Situação estatística: {p.get('situacao')}. "
              f"Família: {ident.get('familia') or '—'} · variante: {ident.get('variante') or 'não identificada'} · "
              f"marca/modelo: {ident.get('marca') or '—'} {ident.get('modelo') or ''}".strip())
    return {"produto": ident.get("produto") or p["produto_id"], "produto_id": p["produto_id"],
            "estado": "Em observação" if ev["estagio"] < 3 else "Investigação comercial",
            "motivo": motivo[:1900], "evidencias": evs + lim, "fontes": p.get("fontes") or [],
            "proximas_acoes": next_actions(p, ev["estagio"]), "fornecedores": [], "concorrentes": [], "exigencias": [], "documentos": []}


# --------------------------------------------------------------------------------------------- respostas fundamentadas
QUESTIONS = {"por_que": "Por que este produto apareceu no radar?", "evidencias": "Quais evidências sustentam essa classificação?",
             "variante": "Qual variante está sendo pesquisada?", "crescimento": "O crescimento é confirmado ou preliminar?",
             "faltando": "Quais informações faltam para investigar a importação?"}


def answer(p: dict, ev: dict, q: str) -> dict:
    """Respostas montadas SÓ a partir dos dados do dossiê (sem LLM). Cada frase cita a fonte; sem dados → diz isso."""
    ident = p.get("identificacao") or {}
    srcs = [{"fonte": e.get("fonte_nome"), "metrica": e.get("metrica"), "periodo": e.get("periodo"), "mercado": e.get("mercado")}
            for e in p.get("evidencias") or []]
    if not srcs:
        return {"pergunta": QUESTIONS.get(q, q), "resposta": "Não há evidências registradas para este produto.", "fontes": []}
    if q == "por_que":
        main = sorted(p["evidencias"], key=lambda e: commercial.evidence_class(e.get("tipo"))["classe"])[0]
        txt = (f"Apareceu por {main.get('fonte_nome')} ({commercial.evidence_class(main.get('tipo'))['classe_nome']}, "
               f"{main.get('metrica')}, {main.get('periodo') or 'período não informado'}). Estágio atual: {ev['nome']}.")
    elif q == "evidencias":
        txt = "; ".join(f"{s['fonte']} — {s['metrica']} ({s['periodo'] or '—'}, {s['mercado'] or '—'})" for s in srcs[:8])
    elif q == "variante":
        v = ident.get("variante")
        txt = (f"Variante identificada: {v}." if v else "Nenhuma variante técnica foi identificada nos dados — os termos falam da "
               "família/produto sem especificação (potência, capacidade ou modelo).")
        if ident.get("marca") or ident.get("modelo"):
            txt += f" Marca/modelo citados: {ident.get('marca') or '—'} {ident.get('modelo') or ''}."
    elif q == "crescimento":
        c = ev["criterios"]
        txt = ("Crescimento CONFIRMADO estatisticamente na pesquisa." if c["crescimento_pesquisa_confirmado"] else
               "Crescimento NÃO confirmado: " + (f"o ranking comercial tem {ev['semanas_ranking']} semana(s) — posição em ranking não "
                                                 "é volume nem crescimento sustentado." if c["evidencia_comercial"] else
                                                 "não há série de pesquisa ou comercial com crescimento significativo."))
    elif q == "faltando":
        txt = ("Faltam: " + "; ".join(ev["faltando"]) + ". Além disso: preços e custos (informados por você), fornecedores, "
               "requisitos regulatórios (Anatel/Inmetro) e NCM confirmada.") if ev["faltando"] else \
              "As evidências mínimas existem; faltam dados que só você pode trazer: fornecedores, custos, preços de compra e documentos regulatórios."
    else:
        return {"pergunta": q, "resposta": "Pergunta não suportada. Use: " + ", ".join(QUESTIONS), "fontes": []}
    return {"pergunta": QUESTIONS[q], "resposta": txt, "fontes": srcs[:8],
            "nota": "Resposta montada pelo GPI a partir das evidências registradas; não usa dados demonstrativos."}


# --------------------------------------------------------------------------------------------- alertas com estado
def track_alerts(db, items: list[dict], today: str) -> list[dict]:
    db.execute(ALERT_SQL)
    seen = set()
    out = []
    for a in items:
        cat = {"comercial": "executivo"}.get(a.get("categoria_alerta"), a.get("categoria_alerta") or "qualidade")
        fp = hashlib.sha1("|".join(str(a.get(k) or "") for k in ("categoria_alerta", "tipo", "produto_id", "fonte")).encode()).hexdigest()[:20]
        seen.add(fp)
        row = db.query("SELECT * FROM alert_state WHERE fingerprint = ?", (fp,))
        if row:
            r = row[0]
            hist = json.loads(r["historico"] or "[]")
            if r["ultima_vez"] != today:
                hist = (hist + [today])[-30:]
                db.execute("UPDATE alert_state SET ultima_vez = ?, vezes = vezes + 1, estado = 'conhecido', historico = ?, resolvido_em = NULL "
                           "WHERE fingerprint = ?", (today, json.dumps(hist), fp))
            estado, primeira = ("novo" if r["primeira_vez"] == today else "conhecido"), r["primeira_vez"]
            vezes = r["vezes"] + (1 if r["ultima_vez"] != today else 0)
        else:
            db.execute("INSERT INTO alert_state (fingerprint, categoria, tipo, produto_id, fonte, primeira_vez, ultima_vez, vezes, estado, historico) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'novo', ?)", (fp, cat, a.get("tipo"), a.get("produto_id"), a.get("fonte"), today, today,
                                                                       json.dumps([today])))
            estado, primeira, vezes = "novo", today, 1
        out.append({**a, "categoria_v09": cat, "estado": estado, "primeira_vez": primeira, "vezes": vezes, "id": fp})
    for r in db.query("SELECT fingerprint FROM alert_state WHERE estado <> 'resolvido'"):
        if r["fingerprint"] not in seen:
            db.execute("UPDATE alert_state SET estado = 'resolvido', resolvido_em = ? WHERE fingerprint = ?", (today, r["fingerprint"]))
    return out


# --------------------------------------------------------------------------------------------- rotas
def routes(db, sync, cfg) -> list[Route]:
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    def payload():
        from .api import _payload_for_v09
        return _payload_for_v09(db, sync, cfg)

    def today():
        return sync.today_fn() if hasattr(sync, "today_fn") else date.today()

    async def stages_view(_):
        return j(await run_in_threadpool(lambda: stages(payload(), db, today())))

    async def investigate(request: Request):
        pid = request.path_params["pid"]

        def go():
            pl = payload()
            p = pl["produtos"].get(pid)
            if not p:
                return None
            ev = evidence_stage(p, today())
            r = INV.add(db, prefill(p, ev))
            return {**r, "preenchido_automaticamente": ["produto", "motivo", "evidencias", "fontes", "proximas_acoes"],
                    "nao_preenchido": "fornecedores, preços, custos, margens e certificações — só com dados informados por você"}
        r = await run_in_threadpool(go)
        return j(r) if r else j({"erro": "produto sem dossiê"}, 404)

    async def ask(request: Request):
        pid, q = request.query_params.get("produto") or "", request.query_params.get("pergunta") or "por_que"

        def go():
            p = payload()["produtos"].get(pid)
            if not p:
                return {"pergunta": QUESTIONS.get(q, q), "resposta": "Produto não encontrado no dossiê.", "fontes": []}
            return answer(p, evidence_stage(p, today()), q)
        return j({**(await run_in_threadpool(go)), "perguntas": QUESTIONS})

    async def alerts_view(request: Request):
        def go():
            pl = payload()
            items = track_alerts(db, (pl.get("alertas_v081") or {}).get("itens", []), today().isoformat())
            f = request.query_params
            if f.get("categoria"):
                items = [a for a in items if a["categoria_v09"] == f["categoria"]]
            if f.get("estado"):
                items = [a for a in items if a["estado"] == f["estado"]]
            cnt = {}
            for a in items:
                cnt.setdefault(a["categoria_v09"], {"novo": 0, "conhecido": 0})[a["estado"]] += 1
            hist = db.query("SELECT categoria, tipo, produto_id, fonte, primeira_vez, resolvido_em, vezes FROM alert_state "
                            "WHERE estado = 'resolvido' ORDER BY resolvido_em DESC LIMIT 100")
            return {"itens": items, "contagem": cnt, "resolvidos_recentes": hist,
                    "regra": "Alertas executivos = mudanças comerciais; estatísticos e de qualidade ficam separados. Um alerta já "
                             "visto aparece como 'conhecido' e não volta como novo; anomalia estatística não vira oportunidade."}
        return j(await run_in_threadpool(go))

    async def panel(_):
        def go():
            pl = payload()
            st = stages(pl, db, today())
            prev = db.query("SELECT payload FROM analysis_results WHERE name = 'v09_estagios_anterior'")
            prevmap = json.loads(prev[0]["payload"]) if prev else {}
            cur = {x["produto_id"]: x["estagio"] for x in st["itens"]}
            changes = [{"produto": x["produto"], "produto_id": x["produto_id"], "de": STAGES.get(prevmap.get(x["produto_id"])) or "—",
                        "para": x["nome_estagio"], "novo": x["produto_id"] not in prevmap}
                       for x in st["itens"] if prevmap.get(x["produto_id"]) != x["estagio"] and (x["estagio"] > 0 or x["produto_id"] in prevmap)]
            if pl.get("gerado_em") and (not prev or json.loads(prev[0]["payload"]).get("_gerado_em") != pl.get("gerado_em")):
                db.execute("INSERT INTO analysis_results (name, payload, created_at) VALUES ('v09_estagios_anterior', ?, ?) "
                           "ON CONFLICT(name) DO UPDATE SET payload = excluded.payload, created_at = excluded.created_at",
                           (json.dumps({**cur, "_gerado_em": pl.get("gerado_em")}), time.strftime("%Y-%m-%dT%H:%M:%S")))
            items = st["itens"]
            radar = [x for x in items if x["estagio_evidencia"]["criterios"]["evidencia_comercial"]]
            opp = [x for x in items if x["estagio_evidencia"]["estagio"] >= 3]
            prelim = [x for x in items if x["estagio_evidencia"]["estagio"] in (1, 2)]
            invs = INV.list_all(db, None)
            invs = invs.get("itens", invs) if isinstance(invs, dict) else invs
            from . import understanding as U
            U.ensure(db)
            pend = db.query("SELECT COUNT(*) AS n FROM association_review WHERE decisao IS NULL")[0]["n"]
            fontes = pl.get("fontes") or []
            k = pl.get("kpis") or {}
            return {"A_resumo": {"produtos": len(items), "com_evidencia_comercial": len(radar), "investigacao_recomendada": len(opp),
                                 "sinais_preliminares": len(prelim), "crescimento_confirmado": sum(1 for x in items if x["estagio_evidencia"]["criterios"]["crescimento_pesquisa_confirmado"]),
                                 "investigacoes_abertas": sum(1 for i in invs if i.get("estado") not in ("Concluído", "Arquivado")),
                                 "cobertura_comercial": (pl.get("coberturas") or {}).get("comercial"), "gerado_em": pl.get("gerado_em")},
                    "B_radar_comercial": radar[:30], "C_oportunidades": opp[:30],
                    "C_vazio": None if opp else "Nenhum produto cumpre os critérios do estágio 3 com os dados atuais — veja os sinais preliminares e o que falta.",
                    "D_sinais_preliminares": prelim[:30], "E_mudancas": changes[:40],
                    "E_nota": "Comparado com a análise anterior registrada." if prev else "Primeira análise registrada: as mudanças aparecem a partir da próxima.",
                    "F_qualidade": {"fontes_com_problema": [f for f in fontes if f.get("estado") not in ("funcional", "removida")][:20],
                                    "coberturas": pl.get("coberturas"), "associacoes_em_revisao": pend},
                    "G_investigacoes": [i for i in invs if i.get("estado") not in ("Concluído", "Arquivado")][:30],
                    "kpis_v081": k, "regras_estagios": st["regras"]}
        return j(await run_in_threadpool(go))

    return [Route("/api/v09/estagios", stages_view), Route("/api/v09/investigar/{pid:path}", investigate, methods=["POST"]),
            Route("/api/v09/perguntar", ask), Route("/api/v09/alertas", alerts_view), Route("/api/v09/painel", panel)]
