"""Correspondência anúncio × produto pesquisado (v0.9.1 MVP). Usa o Product Understanding com o alvo e separa:
produto exato · variante compatível · tecnicamente semelhante · mesma família · acessório relacionado · incompatível ·
correspondência não confirmada (pendente). Kits e lotes têm preço unitário separado. Só exato/variante compatível entram
nos preços comparáveis; nada disso é venda."""
from __future__ import annotations

import re

CLASSES = ["Produto exato", "Variante compatível", "Produto tecnicamente semelhante", "Mesma família", "Acessório relacionado",
           "Produto incompatível", "Correspondência não confirmada"]
ELIGIBLE = {"Produto exato", "Variante compatível"}
ACCESSORY_HEADS = {"cable", "phone_case", "screen_protector", "case", "strap", "stand", "mount", "cover", "bag", "holder", "dock"}
KIT = re.compile(r"\b(?:(\d{1,3})\s*(?:-|\s)?(?:pack|pcs|pc|pieces|unidades|unid|un|pçs|peças|x)\b|(?:pack|kit|lote|lot|set)\s*(?:of|de|c/|com)?\s*(\d{1,3}))",
                 re.I)


def units(title: str) -> int:
    m = KIT.search(title or "")
    if not m:
        return 1
    n = int(m.group(1) or m.group(2) or 1)
    return n if 1 < n <= 200 else 1


def _quals(pid: str | None) -> set[str]:
    if not pid:
        return set()
    fam = pid.split(":")[0]
    return set(fam.split("+")[1:])


def _variant(pid: str | None) -> str | None:
    return pid.split(":", 1)[1] if pid and ":" in pid else None


def classify(title: str, target: str | None, lang: str | None = None) -> dict:
    from ..intel import understanding as U
    if not target:
        return {"classe": CLASSES[6], "confianca": "baixa", "motivo": "sem produto-alvo identificado", "unidades": units(title), "elegivel": False}
    u = U.understand((title or "")[:300], lang, target=target)
    pid, rel, head = u.get("produto_id"), u.get("relacao_alvo"), u.get("principal")
    t_head = target.split(":")[0].split("+")[0]
    tq, cq = _quals(target), _quals(pid)
    tv, cv = _variant(target), _variant(pid)
    coinc = sorted((tq & cq) | ({tv} if tv and tv == cv else set()))
    confl = sorted((tq - cq)) + ([f"variante {cv} ≠ {tv}"] if tv and cv and cv != tv else [])
    if u.get("estado") != "confirmada" or rel in ("ambigua",):
        cls, conf, why = CLASSES[6], "baixa", "identificação ambígua — associação pendente de revisão"
    elif head != t_head:
        if head in ACCESSORY_HEADS and t_head not in ACCESSORY_HEADS:
            cls, conf, why = CLASSES[4], "alta", f"{head} é acessório, não {t_head}"
        else:
            cls, conf, why = CLASSES[5], "alta", f"outro produto ({head or 'não identificado'})"
    elif rel == "corresponde":
        if tq <= cq and (not tv or tv == cv):
            cls, conf, why = (CLASSES[0], "alta", "mesmo tipo, tecnologia e variante") if cq == tq else \
                (CLASSES[1], "média", "mesmo produto com características adicionais declaradas")
        else:
            cls, conf, why = CLASSES[2], "média", "mesmo tipo e variante, mas tecnologia do alvo não declarada (" + ", ".join(sorted(tq - cq)) + ")"
    elif rel == "variante_diferente":
        cls, conf, why = CLASSES[3], "alta", f"mesma família, variante diferente ({cv or 'não declarada'})"
    else:
        cls, conf, why = CLASSES[2], "baixa", "mesmo tipo de produto com qualificadores diferentes"
    n = units(title)
    return {"classe": cls, "confianca": conf, "motivo": why, "produto_identificado": pid, "atributos_coincidentes": coinc,
            "atributos_conflitantes": confl, "unidades": n, "kit_ou_lote": n > 1, "elegivel": cls in ELIGIBLE,
            "status": "pendente" if cls == CLASSES[6] else "automática"}
