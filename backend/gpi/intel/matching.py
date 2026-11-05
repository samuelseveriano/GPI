"""Identificação canônica de produtos com estados de correspondência (v0.8, seção 6 e Gate 2).

Estados:
* CONFIRMADA — núcleo do produto reconhecido, produto existente no catálogo, sem sinais de outro sentido; variante
  (potência, capacidade…) coerente quando informada.
* PROVÁVEL   — núcleo reconhecido, mas termo genérico/polissêmico sem qualificadores, ou produto ainda não catalogado.
* AMBÍGUA    — sinais de entretenimento/notícia/outro sentido, ou vários produtos de categorias diferentes no mesmo texto.
* NÃO IDENTIFICADO — nenhum produto reconhecido.

Regras: quando há ambiguidade o termo original é preservado e NÃO é associado. Associações PROVÁVEIS podem aparecer em
análises exploratórias, mas não em rankings de oportunidades confirmadas (Gate 2). Variantes técnicas diferentes
(20 W × 140 W) nunca são tratadas como o mesmo modelo.
"""
from __future__ import annotations

import re

from ..products import nlp

CONFIRMED, PROBABLE, AMBIGUOUS, NONE = "confirmada", "provavel", "ambigua", "nao_identificado"
LABEL = {CONFIRMED: "Correspondência confirmada", PROBABLE: "Correspondência provável", AMBIGUOUS: "Correspondência ambígua",
         NONE: "Não identificado"}

# sinais de que o texto fala de outra coisa (entretenimento, esportes, notícia policial/política…) — pt/en/es
NON_COMMERCIAL = re.compile(
    r"\b(trailer|filme|film|movie|serie|series|estreno|episodio|episode|temporada|season|novela|musica|music|cancion|"
    r"clipe|videoclipe|official video|lyrics|letra|gameplay|walkthrough|campeonato|championship|ao vivo|en vivo|podcast|"
    r"meme|react|reacao|reaction|prank|pegadinha|morre|morreu|muere|dies|died|preso|presa|arrested|eleicao|election|"
    r"eleccion|gol|gols|goles|goals|highlights|melhores momentos|resumen|escalacao|lineup|show|turne|tour|album|"
    r"cosplay|anime|fanfic|fan art|novidades da semana)\b")
COMMERCIAL = re.compile(
    r"\b(comprar|compra|preco|precos|barato|barata|oferta|promocao|desconto|melhor|melhores|review|analise|unboxing|teste|"
    r"vale a pena|qual comprar|custo beneficio|buy|price|cheap|deal|best|vs|versus|comparativo|mejor|precio|barato|"
    r"comparacion|resena)\b")
# termos que, sozinhos, têm outros sentidos (sem qualificador/atributo/marca não são confirmados)
POLYSEMOUS = {"switch", "plug", "alarm", "sensor", "monitor", "mirror", "toy", "safe", "fan", "mixer", "lock", "camera",
              "scale", "speaker", "helmet", "gloves", "bike", "tent", "backpack", "organizer", "heater", "inverter"}
# expressões em que o núcleo reconhecido é falso cognato de outra coisa
FALSE_FRIENDS = re.compile(
    r"\b(nintendo switch|black mirror|toy story|safe mode|fan club|fa clube|lockdown|camara dos deputados|camara municipal|"
    r"monitor de aula|monitoria|alarme falso|plug and play|sensor de estacionamento do jogo|dj mixer|mixer de audio|"
    r"mixer de som|scale up|power ranger|power rangers)\b")


def _norm(t: str) -> str:
    return " " + nlp.strip_accents(t).lower() + " "


# termos de produto em espanhol → equivalente em português (o léxico conceitual é pt/en/zh; a chave do produto é a mesma)
ES_TO_PT = [("freidora de aire", "air fryer"), ("freidora sin aceite", "fritadeira sem óleo"),
            ("audifonos inalambricos", "fone sem fio"), ("audifonos", "fone de ouvido"), ("auriculares", "fone de ouvido"),
            ("cerradura inteligente", "fechadura inteligente"), ("cerradura", "fechadura"), ("aspiradora robot", "aspirador robô"),
            ("aspiradora", "aspirador"), ("cargador", "carregador"), ("reloj inteligente", "relógio inteligente"),
            ("altavoz", "caixa de som"), ("bocina bluetooth", "caixa de som bluetooth"), ("camara de accion", "câmera de ação"),
            ("camara", "câmera"), ("patinete electrico", "patinete elétrico"), ("bateria externa", "bateria externa"),
            ("bombilla", "lâmpada"), ("lampara", "lâmpada"), ("taladro inalambrico", "furadeira sem fio"), ("taladro", "furadeira"),
            ("casco de moto", "capacete de moto"), ("purificador de aire", "purificador de ar"), ("humidificador", "umidificador"),
            ("proyector", "projetor"), ("enchufe inteligente", "tomada inteligente"), ("cafetera", "cafeteira"),
            ("licuadora", "liquidificador"), ("bascula", "balança digital"), ("raton", "mouse"), ("inalambrico", "sem fio"),
            ("inalambricos", "sem fio"), ("portatil", "portátil")]
ES_HINT = re.compile(r"\b(inalambric\w*|freidora|cerradura|aspiradora|cargador|reloj|altavoz|bocina|camara|bombilla|lampara|"
                     r"taladro|enchufe|cafetera|licuadora|bascula|raton|audifonos|auriculares|proyector)\b")
# palavras que, sozinhas, têm mais de um sentido (avaliadas pela PALAVRA usada, não pelo conceito)
POLY_WORDS = {"switch", "plug", "alarm", "alarme", "sensor", "monitor", "mirror", "espelho", "toy", "safe", "fan", "mixer",
              "lock", "camera", "scale", "speaker", "helmet", "bike", "tent", "heater", "inverter", "inversor", "fone"}


def _es_to_pt(text: str) -> str:
    t = nlp.strip_accents(text).lower()
    for a, b in ES_TO_PT:
        t = re.sub(rf"\b{a}\b", b, t)
    return t


def _singular(text: str) -> str:
    out = []
    for w in text.split():
        lw = w.lower()
        if len(lw) > 4 and lw.endswith("oes"):
            w = w[:-3] + "ao"
        elif len(lw) > 4 and lw.endswith(("is",)) and not lw.endswith("ais"):
            w = w
        elif len(lw) > 3 and lw.endswith("s") and not lw.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def match(text: str, lang: str | None = None, catalog_ids: set | None = None, target: str | None = None) -> dict:
    """Classifica a correspondência de um texto com o catálogo.

    catalog_ids: chaves de família existentes (None = não verificar existência).
    target: product_id esperado (ex.: consulta do YouTube). Se informado, o resultado diz se o texto realmente fala
            desse produto (mesma família e variante compatível).
    """
    original = text or ""
    src = original
    if lang == "es" or (lang in (None, "pt", "und") and ES_HINT.search(nlp.strip_accents(original).lower())):
        src, lang = _es_to_pt(original), "pt"
    a = nlp.analyze(src, lang)
    if not a["produto"]:
        b = nlp.analyze(_singular(src), lang)          # plural ("patinetes elétricos", "drones")
        if b["produto"]:
            a = b
    a["texto"] = a["texto"] if src == original else original
    t = _norm(original + " " + src)
    out = {"texto": a["texto"], "idioma": a["idioma"], "estado": NONE, "produto_id": None, "familia": None, "variante": None,
           "atributos": a["atributos"], "motivos": [], "comercial": bool(COMMERCIAL.search(t))}
    p = a["produto"]
    if FALSE_FRIENDS.search(t):
        out.update(estado=AMBIGUOUS if p else NONE)
        out["motivos"].append("expressão com outro sentido (falso cognato)")
        return _vs_target(out, target)
    if not p:
        out["motivos"].append("nenhum produto reconhecido")
        return _vs_target(out, target)
    fam, var = p["chave"], p["variante"]
    out.update(familia=fam, variante=var, produto_id=f"{fam}:{var}" if var else fam, nucleo=p["nucleo"], categoria=p["categoria"])
    heads = [c for c, _ in nlp.find_concepts(a["texto"], a["idioma"] if a["idioma"] != "und" else "en") if c in nlp.HEADS]
    cats = {nlp.CONCEPTS[h][1] for h in heads}
    reasons = out["motivos"]
    if NON_COMMERCIAL.search(t) and not out["comercial"]:
        out["estado"] = AMBIGUOUS
        reasons.append("contexto de entretenimento/notícia: o produto pode ser apenas citado")
    elif len(cats) > 1 and not _is_accessory_phrase(t):
        out["estado"] = AMBIGUOUS
        reasons.append(f"produtos de categorias diferentes no mesmo texto ({', '.join(sorted(set(heads)))})")
    elif _bare(t) in POLY_WORDS and not var and not a["atributos"] and not out["comercial"]:
        out["estado"] = PROBABLE
        reasons.append(f"termo genérico com mais de um sentido ('{p['nome_pt']}') sem qualificador")
    elif catalog_ids is not None and fam not in catalog_ids:
        out["estado"] = PROBABLE
        reasons.append("produto reconhecido, mas ainda não catalogado (candidato)")
    else:
        out["estado"] = CONFIRMED
        reasons.append("núcleo do produto reconhecido" + (f"; variante {var.upper()}" if var else ""))
    return _vs_target(out, target)


def _is_accessory_phrase(t: str) -> bool:
    """'capinha para iPhone', 'drone com câmera': o segundo conceito é compatibilidade/característica, não outro produto."""
    return bool(re.search(r"\b(para|pra|for|com|with|con|compativel|compatible)\b", t))


STOP = {"o", "a", "os", "as", "de", "do", "da", "the", "el", "la", "um", "uma"}


def _bare(t: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in STOP]
    return words[0] if len(set(words)) == 1 else ""


def _vs_target(out: dict, target: str | None) -> dict:
    if not target:
        return out
    tfam, _, tvar = target.partition(":")
    if out["familia"] is None:
        rel = "nao_corresponde"
    elif out["familia"].split("+")[0] != tfam.split("+")[0]:
        rel = "outro_produto"
    elif tvar and out["variante"] and out["variante"] != tvar:
        rel = "variante_diferente"
    elif out["estado"] == AMBIGUOUS:
        rel = "ambigua"
    else:
        rel = "corresponde"
    out["relacao_alvo"] = rel
    if rel != "corresponde" and out["estado"] == CONFIRMED:
        out["estado_alvo"] = AMBIGUOUS if rel == "ambigua" else NONE
    else:
        out["estado_alvo"] = out["estado"] if rel == "corresponde" else NONE if rel in ("nao_corresponde", "outro_produto") else AMBIGUOUS
    if rel == "variante_diferente":
        out["motivos"].append(f"variante diferente da consultada ({out['variante'].upper()} × {tvar.upper()})")
    elif rel == "outro_produto":
        out["motivos"].append("o texto fala de outro produto")
    return out


def market_of(lang: str | None, region_query: str | None) -> dict:
    """Mercado de um conteúdo: idioma do conteúdo ≠ país da consulta. Vídeo em inglês achado com regionCode=BR não
    é 'consulta brasileira'."""
    lg = (lang or "").lower()[:2]
    if lg == "pt":
        m = "BR"
    elif not lg:
        m = None
    else:
        m = f"idioma:{lg}"
    return {"mercado": m, "pais_da_consulta": region_query, "idioma": lg or None,
            "nota": None if m == region_query else
            ("idioma não informado pela fonte" if m is None else f"conteúdo em '{lg}' encontrado em consulta {region_query}")}


# ------------------------------------------------------------------------------------------------- avaliação (Gate 2)
def evaluate(cases: list[dict], catalog_ids: set | None = None) -> dict:
    """Mede a identificação num conjunto ROTULADO MANUALMENTE (independente das regras).

    Cada caso: texto, idioma (opcional), grupo, esperado (núcleo do produto ou '' quando NÃO deve associar),
    variante (opcional). Associação = estado CONFIRMADA (o que entra em rankings). Provável/ambígua/não identificado =
    abstenção.
    """
    tp = fp = fn = abst = 0
    per = {}
    errors = []
    for c in cases:
        r = match(c["texto"], c.get("idioma") or None, catalog_ids)
        assoc = r["estado"] == CONFIRMED
        exp = c.get("esperado") or ""
        ok_head = assoc and (r.get("nucleo") == exp) and (not c.get("variante") or r["variante"] == c["variante"])
        g = per.setdefault(c["grupo"], {"casos": 0, "corretos": 0, "incorretos": 0, "abstencoes": 0})
        g["casos"] += 1
        if assoc and ok_head:
            tp += 1
            g["corretos"] += 1
        elif assoc:
            fp += 1
            g["incorretos"] += 1
            errors.append({"texto": c["texto"], "grupo": c["grupo"], "esperado": exp or "(não associar)",
                           "obtido": f"{r.get('nucleo')}" + (f":{r['variante']}" if r.get("variante") else ""), "motivo": r["motivos"]})
            if exp:
                fn += 1
        else:
            abst += 1
            g["abstencoes"] += 1
            if exp:
                fn += 1
            else:
                g["corretos"] += 1           # abster-se num caso que não deve ser associado é o comportamento correto
    n = len(cases)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"casos": n, "verdadeiros_positivos": tp, "falsos_positivos": fp, "falsos_negativos": fn,
            "precision": prec, "recall": rec, "f1": f1, "taxa_incorreta": fp / n if n else None,
            "taxa_abstencao": abst / n if n else None, "por_grupo": per, "erros": errors, "metas": TARGETS,
            "metas_atingidas": {"precision": prec is not None and prec >= TARGETS["precision"],
                                "taxa_incorreta": n and fp / n <= TARGETS["taxa_incorreta"],
                                "recall": rec is not None and rec >= TARGETS["recall"]}}


# metas documentadas (docs/DATA_QUALITY.md): precisão alta é prioritária — preferimos abster a associar errado
TARGETS = {"precision": 0.95, "taxa_incorreta": 0.03, "recall": 0.70}


def load_eval() -> list[dict]:
    from pathlib import Path
    out = []
    for line in (Path(__file__).parent / "data" / "matching_eval.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        g, lg, exp, var, text = (line.split("\t") + [""] * 5)[:5]
        if text.strip():
            out.append({"grupo": g, "idioma": lg or None, "esperado": exp, "variante": var or None, "texto": text})
    return out
