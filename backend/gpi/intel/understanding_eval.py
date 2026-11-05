"""Avaliação do Product Understanding (v0.9) em conjuntos rotulados SEPARADOS:
* understanding_dev_v09.tsv  — usado para desenvolver e ajustar regras;
* understanding_test_v09.tsv — escrito ANTES das alterações e usado só para medir (nunca para ajustar).

Métricas: precisão, recall e F1 da associação produto↔família; taxa de associação incorreta; taxa de abstenção;
precisão das associações de ALTA CONFIANÇA (estado "confirmada"); por idioma, por grupo e por nível
(família, variante, marca, modelo)."""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data"


def load(name: str) -> list[dict]:
    out = []
    for ln in (DATA / name).read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        p = ln.split("\t")
        if len(p) < 8:
            continue
        dash = lambda v: None if v.strip() in ("-", "") else v.strip()  # noqa: E731
        out.append({"idioma": p[0], "estado": p[1], "familia": dash(p[2]), "variante": dash(p[3]), "marca": dash(p[4]),
                    "modelo": dash(p[5]), "grupo": p[6], "texto": p[7]})
    return out


def _supported(var: str, text: str) -> bool:
    t = re.sub(r"\s+", "", text.lower().replace(",", "."))
    for a, b in (("litros", "l"), ("litro", "l"), ("polegadas", "pol"), ("watts", "w"), ("fullhd", "full hd")):
        t = t.replace(a, b)
    return var.lower().replace(" ", "") in t.replace(" ", "")


def _nm(v):
    return re.sub(r"[\s\-_.]", "", str(v or "")).upper() or None


def evaluate(cases: list[dict], analyzer) -> dict:
    """analyzer(texto, idioma) → {'estado', 'familia' (cabeça), 'variante', 'marca', 'modelo'}."""
    tp = fp = fn = abst = wrong = hc = hc_ok = 0
    by_lang, by_group = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    lvl = {k: [0, 0] for k in ("familia", "variante", "marca", "modelo")}
    errs = []
    for c in cases:
        r = analyzer(c["texto"], c["idioma"])
        head = (r.get("familia") or "").split("+")[0] or None
        exp_pos = c["estado"] == "confirmada"
        pred_pos = r.get("estado") == "confirmada"
        correct_assoc = exp_pos and pred_pos and head == c["familia"]
        if pred_pos:
            hc += 1
            hc_ok += correct_assoc
            if correct_assoc:
                tp += 1
            else:
                fp += 1
                wrong += 1
        if exp_pos and not correct_assoc:
            fn += 1
            if not pred_pos:
                abst += 1
        ok_case = correct_assoc if exp_pos else (r.get("estado") == c["estado"] or (c["estado"] == "ambigua" and not pred_pos))
        for d, k in ((by_lang, c["idioma"]), (by_group, c["grupo"])):
            d[k][0] += ok_case
            d[k][1] += 1
        if correct_assoc:
            for k in ("variante", "marca", "modelo"):
                got = r.get(k)
                if got:                                      # precisão por nível: só quando o sistema afirma um valor
                    lvl[k][1] += 1
                    if k == "variante":                      # variante: precisa estar EXPLÍCITA no texto (nunca inferida)
                        lvl[k][0] += _supported(str(got), c["texto"])
                    elif k == "modelo":
                        a, b = _nm(got), _nm(c[k])
                        lvl[k][0] += bool(a and b and (a in b or b in a))
                    else:
                        lvl[k][0] += _nm(got) == _nm(c[k])
            lvl["familia"][0] += 1
        if pred_pos:
            lvl["familia"][1] += 0 if correct_assoc else 1
        if not ok_case:
            errs.append({"texto": c["texto"], "esperado": f"{c['estado']}:{c['familia']}", "obtido": f"{r.get('estado')}:{head}"})
    lvl["familia"][1] += lvl["familia"][0]
    P = tp / (tp + fp) if tp + fp else None
    R = tp / (tp + fn) if tp + fn else None
    n_pos = sum(c["estado"] == "confirmada" for c in cases)
    return {"casos": len(cases), "precisao": P, "recall": R, "f1": 2 * P * R / (P + R) if P and R else None,
            "taxa_associacao_incorreta": wrong / len(cases), "taxa_abstencao": abst / n_pos if n_pos else None,
            "precisao_alta_confianca": hc_ok / hc if hc else None, "alta_confianca_n": hc,
            "por_idioma": {k: {"acerto": v[0] / v[1], "n": v[1]} for k, v in sorted(by_lang.items())},
            "por_grupo": {k: {"acerto": v[0] / v[1], "n": v[1]} for k, v in sorted(by_group.items())},
            "por_nivel": {k: {"precisao": v[0] / v[1] if v[1] else None, "afirmados": v[1]} for k, v in lvl.items()},
            "erros": errs}


def baseline_analyzer(text, lang):
    from .matching import match
    m = match(text, lang)
    return {"estado": m["estado"], "familia": m.get("familia"), "variante": m.get("variante"),
            "marca": (m.get("atributos") or {}).get("marca"), "modelo": (m.get("atributos") or {}).get("modelo")}
