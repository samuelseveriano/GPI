"""GPI v0.9 — Product Understanding 2.0.

* Taxonomia de 5 níveis com identificadores persistentes:
  categoria (c:) → família (f:) → produto (p:) → variante técnica (v:) → modelo comercial (m:).
  Um nível só existe quando o texto o sustenta: modelo comercial exige modelo explícito (com marca ou linha de modelo).
* Atributos explícitos (marca, modelo, tecnologia, potência, tensão, frequência, capacidade, dimensões, materiais,
  conectividade, recursos, aplicação, compatibilidade). O que não está no texto fica DESCONHECIDO — nunca inferido pela
  categoria.
* Produto principal × mencionados, contexto (comparativo, notícia, entretenimento) e justificativa.
* Contexto de vídeos: classificação TEXTUAL do GPI (não é categoria do YouTube; Derived Metrics Policy: tags próprias
  distinguidas dos dados da API).
* Reavaliação das associações de conteúdo e fila de revisão humana para associações duvidosas."""
from __future__ import annotations

import json
import re
import time
from collections import Counter

from ..products import nlp
from . import matching as M

TAXONOMY_SQL = """CREATE TABLE IF NOT EXISTS product_taxonomy (
    id TEXT PRIMARY KEY, nivel INTEGER NOT NULL, tipo TEXT NOT NULL, pai TEXT, rotulo TEXT NOT NULL,
    primeira_vez TEXT NOT NULL, ultima_vez TEXT NOT NULL, observacoes INTEGER NOT NULL DEFAULT 0, exemplo TEXT)"""
REVIEW_SQL = """CREATE TABLE IF NOT EXISTS association_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fonte TEXT NOT NULL, item_id TEXT NOT NULL, texto TEXT NOT NULL, idioma TEXT,
    sugestao TEXT, estado TEXT NOT NULL, motivos TEXT, contexto TEXT, criado_em TEXT NOT NULL,
    decisao TEXT, produto_decidido TEXT, decidido_em TEXT, justificativa TEXT, UNIQUE (fonte, item_id))"""
LEVELS = {1: "categoria", 2: "família", 3: "produto", 4: "variante técnica", 5: "modelo comercial"}

ATTR = {
    "frequencia": re.compile(r"\b(\d{2,3})\s?hz\b"),
    "tensao": re.compile(r"\b(bivolt|(?:5|9|12|24|110|127|220|240)\s?v)\b"),
    "dimensoes": re.compile(r"\b(\d+(?:[.,]\d+)?\s?x\s?\d+(?:[.,]\d+)?(?:\s?x\s?\d+(?:[.,]\d+)?)?\s?(?:cm|mm|m))\b|\b(\d{2,3}\s?(?:cm|mm))\b"),
    "materiais": re.compile(r"\b(aco inox|inox|aluminio|plastico abs|abs|vidro temperado|silicone|couro|madeira|stainless steel|"
                            r"aluminum|leather|lifepo4|monocristalino|policristalino)\b"),
    "conectividade": re.compile(r"\b(wi-?fi ?6?|bluetooth(?: \d\.\d)?|usb-?c|usb 3\.0|lightning|nfc|zigbee|5g|4g|ethernet|hdmi)\b"),
    "recursos": re.compile(r"\b(anc|cancelamento de ruido|noise cancell\w*|a prova d.?agua|waterproof|ip6\d|ipx\d|sem fio|wireless|"
                           r"recarregavel|rechargeable|dobravel|foldable|magnetico|magnetic|reclinavel|visao noturna|night vision|"
                           r"carregamento rapido|fast charg\w*|biometric\w*|biometrica|gan)\b"),
    "aplicacao": re.compile(r"\b(?:para|for|pra)\s(carro|gatos?|caes|cachorros?|podcast|notebook|macbook|cozinha|banheiro|escritorio|"
                            r"academia|gym|iniciantes|criancas|pets?|casa|jogos|games)\b"),
}
CONTEXTS = [  # ordem importa: o primeiro sinal forte decide
    ("publicidade", re.compile(r"(#publi|\bpubli\b|patrocinad|parceria paga|sponsored|#ad\b|paid promotion|cupom|codigo de desconto)")),
    ("comparativo", re.compile(r"\b(vs\.?|versus|comparativo|comparacao|comparison|qual (?:o )?melhor|which is better|x)\b")),
    ("unboxing", re.compile(r"\b(unboxing|desempacotando|abrindo a caixa|chegou)\b")),
    ("review", re.compile(r"\b(review|analise|resenha|vale a pena|e bom|worth it|honest|opiniao|depois de \d+ (?:meses|anos)|after \d+ (?:months|years))\b")),
    ("tutorial", re.compile(r"\b(como (?:usar|instalar|configurar)|tutorial|how to|passo a passo|instalacao|setup)\b")),
    ("demonstracao_tecnica", re.compile(r"\b(teste|test|benchmark|medicao|medindo|desmontando|teardown|bateria dura|autonomia)\b")),
    ("lancamento", re.compile(r"\b(lancamento|lancou|launch|anuncia|announced|novo|new) \b")),
    ("entretenimento", re.compile(r"\b(vlog|k{3,}|reagindo|reacting|desafio|challenge|prank|pegadinha|meme|trailer|gameplay|cursed|divertid\w*)\b")),
]
CONTEXT_LABEL = {"review": "Review", "unboxing": "Unboxing", "comparativo": "Comparativo", "tutorial": "Tutorial",
                 "demonstracao_tecnica": "Demonstração técnica", "lancamento": "Lançamento", "publicidade": "Publicidade",
                 "entretenimento": "Entretenimento", "nao_identificado": "Conteúdo não identificado"}
CONTEXT_NOTE = "Classificação textual do GPI a partir do título e da descrição — não é uma categoria do YouTube."


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nlp.strip_accents(str(s)).lower()).strip("-")


def attributes(text: str, base: dict | None = None) -> dict:
    """Atributos EXPLÍCITOS. Ausentes → None (desconhecido)."""
    t = " " + nlp.strip_accents(text or "").lower() + " "
    b = base or {}
    out = {"marca": b.get("marca"), "modelo": b.get("modelo"), "modelo_compativel": b.get("modelo_compativel"),
           "fabricante": None, "tecnologia": b.get("tecnologia"), "potencia_w": b.get("potencia_w"),
           "capacidade": b.get("capacidade_mah") and f"{b['capacidade_mah']} mAh" or b.get("volume_l") and f"{b['volume_l']} L"
           or b.get("armazenamento_gb") and f"{b['armazenamento_gb']} GB" or None,
           "tela_pol": b.get("tela_pol"), "resolucao": b.get("resolucao"), "compatibilidade": b.get("compatibilidade")}
    m = re.search(r"\b(?:fabricante|fabricado por|manufacturer|made by)\s*:?\s*([a-z0-9][\w\- ]{1,30})", t)
    if m:
        out["fabricante"] = m.group(1).strip()
    for k, rx in ATTR.items():
        vals = sorted({(g or "").strip() for mm in rx.finditer(t) for g in mm.groups() if g} if rx.groups else
                      {mm.group(0).strip() for mm in rx.finditer(t)})
        out[k] = vals or None
    if out["tensao"]:
        out["tensao"] = [v.replace(" ", "").upper() if v != "bivolt" else "bivolt" for v in out["tensao"]]
    return out


def taxonomy_nodes(m: dict) -> list[dict]:
    """Nós da taxonomia sustentados pelo texto (do mais geral ao mais específico)."""
    if m.get("estado") != M.CONFIRMED or not m.get("familia"):
        return []
    fam = m["familia"]
    head = fam.split("+")[0]
    cat = m.get("categoria") or (nlp.CONCEPTS.get(head) or (None, "Sem categoria"))[1]
    nodes = [{"id": "c:" + _slug(cat), "nivel": 1, "rotulo": cat, "pai": None},
             {"id": "f:" + head, "nivel": 2, "rotulo": nlp.CONCEPTS.get(head, (None, None, [head]))[2][0] if head in nlp.CONCEPTS else head,
              "pai": "c:" + _slug(cat)}]
    if "+" in fam:
        nodes.append({"id": "p:" + fam, "nivel": 3, "rotulo": fam.replace("+", " · "), "pai": "f:" + head})
    parent = nodes[-1]["id"]
    if m.get("variante"):
        nodes.append({"id": f"v:{fam}:{m['variante']}", "nivel": 4, "rotulo": f"{fam.replace('+', ' · ')} {m['variante'].upper()}", "pai": parent})
        parent = nodes[-1]["id"]
    at = m.get("atributos") or {}
    if at.get("modelo") and (at.get("marca") or m.get("linha_de_modelo")):
        mk = at.get("marca") or "?"
        nodes.append({"id": f"m:{_slug(mk)}:{_slug(at['modelo'])}", "nivel": 5, "rotulo": f"{mk} {at['modelo']}".strip(), "pai": parent})
    return nodes


def understand(text: str, lang: str | None = None, target: str | None = None) -> dict:
    m = M.match(text, lang, target=target)
    nodes = taxonomy_nodes(m)
    lvl = max((n["nivel"] for n in nodes), default=0)
    ment = m.get("mencionados") or ([m["familia"].split("+")[0]] if m.get("familia") else [])
    principal = m["familia"].split("+")[0] if m.get("estado") == M.CONFIRMED and m.get("familia") else None
    return {"texto": text, "estado": m["estado"], "estado_rotulo": M.LABEL[m["estado"]], "contexto": m.get("contexto"),
            "produto_id": m.get("produto_id") if m["estado"] == M.CONFIRMED else None,
            "principal": principal, "secundarios": [h for h in ment if h != principal],
            "nivel": lvl, "nivel_rotulo": LEVELS.get(lvl, "não identificado"), "taxonomia": nodes,
            "atributos": attributes(text, m.get("atributos")), "motivos": m["motivos"],
            "relacao_alvo": m.get("relacao_alvo"), "estado_alvo": m.get("estado_alvo"),
            "pode_alimentar_conclusoes": m["estado"] == M.CONFIRMED and (target is None or m.get("estado_alvo") == M.CONFIRMED)}


def video_context(title: str, description: str = "") -> dict:
    t = " " + nlp.strip_accents(f"{title or ''} {description or ''}").lower() + " "
    tt = " " + nlp.strip_accents(title or "").lower() + " "
    for k, rx in CONTEXTS:
        if rx.search(tt if k in ("comparativo", "lancamento") else t):
            if k == "comparativo" and not re.search(r"\b(vs\.?|versus|comparativo|comparacao|comparison|qual (?:o )?melhor|which is better)\b|[a-z] x [a-z]", tt):
                continue
            return {"contexto": k, "rotulo": CONTEXT_LABEL[k], "nota": CONTEXT_NOTE}
    return {"contexto": "nao_identificado", "rotulo": CONTEXT_LABEL["nao_identificado"], "nota": CONTEXT_NOTE}


# ------------------------------------------------------------------------------------------------ persistência
def ensure(db):
    db.execute(TAXONOMY_SQL)
    db.execute(REVIEW_SQL)


def record_taxonomy(db, nodes: list[dict], example: str):
    if not nodes:
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for n in nodes:
        db.execute("INSERT INTO product_taxonomy (id, nivel, tipo, pai, rotulo, primeira_vez, ultima_vez, observacoes, exemplo) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?) ON CONFLICT(id) DO UPDATE SET ultima_vez = excluded.ultima_vez, "
                   "observacoes = observacoes + 1", (n["id"], n["nivel"], LEVELS[n["nivel"]], n["pai"], n["rotulo"], now, now, example[:200]))


def queue_review(db, fonte: str, item_id: str, text: str, lang: str | None, u: dict):
    db.execute("INSERT INTO association_review (fonte, item_id, texto, idioma, sugestao, estado, motivos, contexto, criado_em) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(fonte, item_id) DO UPDATE SET sugestao = excluded.sugestao, "
               "estado = excluded.estado, motivos = excluded.motivos WHERE decisao IS NULL",
               (fonte, item_id, text[:300], lang, (u.get("secundarios") or [None])[0] if not u.get("principal") else u["principal"],
                u["estado"], json.dumps(u["motivos"][:3], ensure_ascii=False), u.get("contexto"), time.strftime("%Y-%m-%dT%H:%M:%S")))


def reassess_content(db) -> dict:
    """Reavalia as associações de vídeos (e itens de conteúdo) com as regras v0.9. Não apaga nada: guarda a associação
    anterior em metrics.produto_anterior; decisões humanas da fila de revisão prevalecem."""
    ensure(db)
    decided = {(r["fonte"], r["item_id"]): r for r in db.query(
        "SELECT fonte, item_id, decisao, produto_decidido FROM association_review WHERE decisao IS NOT NULL")}
    rows = db.query("SELECT source, item_id, title, text, lang, product_key, query, metrics FROM content_items WHERE source = 'youtube'")
    stats = Counter()
    with db.lock:
        for r in rows:
            mt = json.loads(r["metrics"] or "{}")
            target = mt.get("produto_consultado") or mt.get("produto_anterior") or r["product_key"]
            u = understand(r["title"] or "", (r["lang"] or "")[:2] or None, target=target if target and not str(target).startswith(("wiki:", "ml:")) else None)
            ctx = video_context(r["title"] or "", r["text"] or "")
            new_pk = target if (u["pode_alimentar_conclusoes"] and target) else None
            d = decided.get(("youtube", r["item_id"]))
            if d:
                new_pk = d["produto_decidido"] if d["decisao"] == "confirmar" else None
                stats["decisao_humana"] += 1
            elif u["estado"] in (M.AMBIGUOUS, M.PROBABLE) or (target and u.get("relacao_alvo") not in (None, "corresponde")):
                queue_review(db, "youtube", r["item_id"], r["title"] or "", r["lang"], u)
                stats["fila_revisao"] += 1
            if r["product_key"] and r["product_key"] != new_pk:
                stats["removidas" if new_pk is None else "alteradas"] += 1
                mt.setdefault("produto_anterior", r["product_key"])
            elif new_pk:
                stats["mantidas"] += 1
            else:
                stats["sem_associacao"] += 1
            mt["correspondencia_v09"] = {"estado": u["estado"], "relacao": u.get("relacao_alvo"), "motivos": u["motivos"][:2],
                                         "nivel": u["nivel_rotulo"], "principal": u["principal"], "secundarios": u["secundarios"]}
            mt["contexto_gpi"] = ctx
            mt["atributos_explicitos"] = {k: v for k, v in u["atributos"].items() if v}
            db.con.execute("UPDATE content_items SET product_key = ?, metrics = ? WHERE source = 'youtube' AND item_id = ?",
                           (new_pk, json.dumps(mt, ensure_ascii=False), r["item_id"]))
            if new_pk:
                record_taxonomy(db, u["taxonomia"], r["title"] or "")
        db.con.commit()
    out = {"videos": len(rows), **stats, "em": time.strftime("%Y-%m-%dT%H:%M:%S")}
    db.execute("INSERT INTO analysis_results (name, payload, created_at) VALUES ('v09_reavaliacao_conteudo', ?, ?) "
               "ON CONFLICT(name) DO UPDATE SET payload = excluded.payload, created_at = excluded.created_at",
               (json.dumps(out), out["em"]))
    return out


def build_taxonomy(db, limit: int = 5000) -> dict:
    """Registra a taxonomia a partir dos termos observados (buscas, rankings) com associação confirmada."""
    ensure(db)
    try:
        rows = db.query("SELECT term, MIN(lang) AS lang, COUNT(*) AS n FROM search_observations GROUP BY term ORDER BY n DESC LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001
        rows = []
    c = Counter()
    for r in rows:
        u = understand(r["term"], r["lang"])
        if u["taxonomia"]:
            record_taxonomy(db, u["taxonomia"], r["term"])
            c[u["nivel_rotulo"]] += 1
        elif u["estado"] in (M.AMBIGUOUS, M.PROBABLE):
            queue_review(db, "busca", r["term"], r["term"], r["lang"], u)
            c["fila_revisao"] += 1
    return {"termos": len(rows), "por_nivel": dict(c)}
