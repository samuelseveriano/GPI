"""GPI Product Discovery Engine (v0.8.1, seção 13): classifica TODOS os termos observados nas fontes e cria candidatos.

Classes: produto identificado · família de produtos · categoria genérica · marca · serviço · entretenimento · notícia ·
termo ambíguo · não comercial. Marca e serviço nunca viram produto físico. "Carregador" é FAMÍLIA — não vira
"carregador USB-C 140W". Avaliado em conjunto rotulado independente (data/discovery_eval.tsv)."""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..products import nlp
from . import matching

CLASSES = ["produto identificado", "família de produtos", "categoria genérica", "marca", "serviço", "entretenimento", "notícia",
           "termo ambíguo", "não comercial"]
ABSTAIN = {"termo ambíguo"}
SERVICE = re.compile(r"\b(assinatura|plano|curso|seguro|frete|conserto|manutencao|instalacao|delivery|aluguel|consorcio|"
                     r"emprestimo|cartao de credito|recarga|streaming|app |aplicativo|ingresso|passagem|hotel|viagem|"
                     r"subscription|insurance|repair|shipping)\b")
NEWS = re.compile(r"\b(morre|morreu|preso|presa|policia|prefeitura|governo|eleicao|eleicoes|anuncia|aprova|operacao|"
                  r"acidente|tragedia|resultado|placar|jogo do|jogo de|campeonato|copa do|loteria|mega sena|previsao do tempo|"
                  r"news|dies|arrested|election|weather)\b")
GENERIC = {"eletronicos", "eletronico", "eletrodomesticos", "eletrodomestico", "moda", "roupas", "roupa", "calcados", "informatica",
           "games", "beleza", "casa", "decoracao", "ferramentas", "brinquedos", "esportes", "acessorios", "celulares", "promocao",
           "ofertas", "black friday", "presentes", "utilidades", "cozinha", "pet shop", "papelaria", "suplementos", "electronics",
           "clothing", "shoes", "home", "deals"}
COMMERCIAL_CUE = re.compile(r"\b(comprar|preco|barato|oferta|promocao|kit|original|masculino|feminino|infantil|unidades|pecas|"
                            r"tamanho|cor|com \d|\d+ ?(un|unid|pcs|ml|g|kg|l|w|v|mah|gb|tb))\b")


def _n(t: str) -> str:
    return " " + nlp.strip_accents(t or "").lower().strip() + " "


def classify(term: str, lang: str | None = None) -> dict:
    t = _n(term)
    core = t.strip()
    m = matching.match(term, lang)
    out = {"termo": term, "estado_correspondencia": m["estado"], "produto_id": m.get("produto_id"), "familia": m.get("familia"),
           "variante": m.get("variante"), "categoria": m.get("categoria"), "motivos": list(m["motivos"])}
    words = [w for w in re.findall(r"[a-z0-9]+", core) if w not in matching.STOP]
    brands = {nlp.strip_accents(b).lower() for b in getattr(nlp, "BRANDS", [])}
    if NEWS.search(t):
        cls = "notícia"
    elif matching.NON_COMMERCIAL.search(t) and not m["comercial"]:
        cls = "entretenimento"
    elif SERVICE.search(t + " "):
        cls = "serviço"
    elif core in GENERIC:
        cls = "categoria genérica"
    elif m["estado"] == matching.CONFIRMED:
        a = m["atributos"]
        specific = bool(m.get("variante") or a.get("marca") or a.get("modelo") or (m.get("familia") or "").count("+")
                        or a.get("tecnologia") or a.get("conector") or re.search(r"\b\d+ ?(cm|mm|pol|polegadas)\b", core))
        cls = "produto identificado" if specific else "família de produtos"
    elif m["estado"] in (matching.PROBABLE, matching.AMBIGUOUS):
        cls = "termo ambíguo"
    elif len(words) == 1 and words[0] in matching.POLY_WORDS:
        cls = "termo ambíguo"
        out["motivos"].append("palavra com mais de um sentido")
    elif words and all(w in brands for w in words):
        cls = "marca"
    elif COMMERCIAL_CUE.search(t):
        cls = "termo ambíguo"
        out["motivos"].append("possível produto ainda não catalogado (contexto comercial)")
        out["candidato_novo"] = True
    else:
        cls = "não comercial"
    out["classe"] = cls
    return out


def load_eval() -> list[dict]:
    out = []
    for line in (Path(__file__).parent / "data" / "discovery_eval.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cls, lang, text = (line.split("\t") + ["", "", ""])[:3]
        if text.strip():
            out.append({"classe": cls, "idioma": lang or None, "texto": text})
    return out


def evaluate(cases: list[dict] | None = None) -> dict:
    cases = cases or load_eval()
    per = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    abst = wrong = 0
    errs = []
    for c in cases:
        r = classify(c["texto"], c["idioma"])
        pred, exp = r["classe"], c["classe"]
        if pred in ABSTAIN and exp not in ABSTAIN:
            abst += 1
            per[exp]["fn"] += 1
            continue
        if pred == exp:
            per[exp]["tp"] += 1
        else:
            wrong += 1
            per[pred]["fp"] += 1
            per[exp]["fn"] += 1
            errs.append({"texto": c["texto"], "esperado": exp, "obtido": pred})
    rep = {}
    for k, v in per.items():
        p = v["tp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else None
        r = v["tp"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else None
        rep[k] = {**v, "precision": p, "recall": r, "f1": (2 * p * r / (p + r)) if p and r else None}
    n = len(cases)
    tp = sum(v["tp"] for v in per.values())
    phys = [k for k in ("produto identificado", "família de produtos")]
    ptp = sum(per[k]["tp"] for k in phys)
    pfp = sum(per[k]["fp"] for k in phys)
    return {"casos": n, "acuracia": tp / n if n else None, "taxa_incorreta": wrong / n if n else None,
            "taxa_abstencao": abst / n if n else None, "por_classe": rep,
            "precision_produto_fisico": ptp / (ptp + pfp) if ptp + pfp else None, "erros": errs}


def run(db, limit: int = 2000) -> dict:
    """Classifica os termos observados e cria candidatos para investigação (com evidência e histórico)."""
    try:
        rows = db.query("SELECT term, MIN(lang) AS lang, COUNT(*) AS n, COUNT(DISTINCT source) AS fontes, "
                        "GROUP_CONCAT(DISTINCT source) AS srcs, MIN(ref_date) AS primeiro, MAX(ref_date) AS ultimo, "
                        "MAX(commercial) AS com FROM search_observations GROUP BY term ORDER BY n DESC LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001
        rows = []
    counts = defaultdict(int)
    cands = []
    for r in rows:
        c = classify(r["term"], r["lang"])
        counts[c["classe"]] += 1
        commercial_src = any(s in (r["srcs"] or "") for s in ("ml_trends", "mercadolivre", "google_ads_kp", "msads_kp"))
        if c["classe"] in ("produto identificado", "família de produtos") or c.get("candidato_novo"):
            rel = 2 * commercial_src + min(3, r["fontes"]) + min(2, r["n"] / 10)
            cands.append({"termo": r["term"], "classe": c["classe"], "produto_id": c.get("produto_id"), "familia": c.get("familia"),
                          "variante": c.get("variante"), "categoria": c.get("categoria"), "observacoes": r["n"],
                          "fontes": (r["srcs"] or "").split(","), "fonte_comercial": commercial_src, "primeiro": r["primeiro"],
                          "ultimo": r["ultimo"], "relevancia": round(rel, 2), "novo_produto": bool(c.get("candidato_novo")),
                          "motivos": c["motivos"][:2]})
    cands.sort(key=lambda x: -x["relevancia"])
    return {"termos_classificados": len(rows), "por_classe": dict(counts), "candidatos": cands[:150],
            "regra": "Marca e serviço não viram produto físico; família ≠ modelo técnico (carregador ≠ carregador USB-C 140 W)."}
