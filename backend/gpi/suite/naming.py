"""Identificação legível dos produtos. O ID canônico (ex.: `charger+gan:65w`) é interno; o usuário vê o nome comercial
(ex.: "Carregador GaN 65W"). A resposta separa ID, nome, família, variante, características e traduções — sem perder a
precisão técnica do ID."""
from __future__ import annotations

import json
import re

UNITS = {"w": "W", "v": "V", "hz": "Hz", "gb": "GB", "tb": "TB", "mah": "mAh", "k": "K", "l": "L", "ml": "ml", "mm": "mm", "cm": "cm",
         "pol": "\"", "in": "\"", "a": "A", "kg": "kg", "g": "g", "m": "m", "fps": "fps", "mp": "MP"}


def pretty_token(t: str) -> str:
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)([a-z]+)", t.strip().lower())
    if m and m.group(2) in UNITS:
        return m.group(1) + UNITS[m.group(2)]
    if ":" in t:
        return " ".join(pretty_token(x) for x in t.split(":"))
    return t.upper() if len(t) <= 3 and t.isalpha() else t.replace("-", " ")


def describe(db, pid: str | None, understanding: dict | None = None) -> dict:
    if not pid:
        return {"id_canonico": None, "nome_comercial": None, "familia": None, "variante": None, "caracteristicas": {}, "traducoes": {}}
    fam_id, _, var = pid.partition(":")
    rows = {r["product_id"]: r for r in db.query("SELECT product_id, name_pt, name_en, name_zh, family, category, attributes, level "
                                                 "FROM catalog_products WHERE product_id IN (?, ?)", (pid, fam_id))}
    fam = rows.get(fam_id) or {}
    me = rows.get(pid) or {}
    fam_name = fam.get("name_pt") or fam.get("name_en") or _from_id(fam_id)
    var_label = " ".join(pretty_token(v) for v in var.split(":")) if var else None
    name = me.get("name_pt") if me and me.get("level") == "variante" and me.get("name_pt") and me.get("name_pt") != fam_name else None
    name = name or (f"{fam_name} {var_label}" if var_label else fam_name)
    try:
        attrs = json.loads(me.get("attributes") or fam.get("attributes") or "{}")
    except (TypeError, ValueError):
        attrs = {}
    feats = {k: v for k, v in ((understanding or {}).get("atributos") or {}).items() if v}
    if attrs.get("qualificadores"):
        feats.setdefault("qualificadores", attrs["qualificadores"])
    tr = {}
    for lang in ("pt", "en", "zh"):
        n = (me or fam).get(f"name_{lang}") or fam.get(f"name_{lang}")
        if n:
            tr[lang] = f"{n} {var_label}" if var_label and me.get("level") != "variante" else n
    return {"id_canonico": pid, "nome_comercial": name, "familia": {"id": fam_id, "nome": fam_name, "categoria": fam.get("category")},
            "variante": {"id": pid, "rotulo": var_label} if var else None, "caracteristicas": feats, "traducoes": tr,
            "no_catalogo": bool(rows)}


def _from_id(fid: str) -> str:
    from ..products import lexicon as LX
    head, *quals = fid.split("+")
    pt = ((LX.CONCEPTS.get(head) or (None, None, []))[2] or [None])[0]
    base = pt[:1].upper() + pt[1:] if pt else head.replace("_", " ").capitalize()
    return " ".join([base, *[pretty_token(q) for q in quals]])


def name_of(db, pid: str | None) -> str | None:
    return describe(db, pid)["nome_comercial"] if pid else None
