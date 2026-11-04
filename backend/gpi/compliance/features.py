"""Camada 1a — extração rastreável de características do produto.

Precedência: (1) resposta explícita do formulário (sim/não/não sei) → (2) evidência textual na descrição técnica ou nos
anexos (só pode indicar PRESENÇA, nunca ausência) → (3) indícios no nome comercial/categoria, que NÃO viram
característica: geram apenas perguntas ("não inferir exigências somente com base no nome do produto").
Cada característica guarda a origem e o trecho que a sustenta.
"""
from __future__ import annotations

import re
import unicodedata

KW = {
    "wifi": [r"wi[\s\-‑]?fi", r"\bwlan\b", r"802\.11", r"无线局域网"],
    "bluetooth": [r"bluetooth", r"\bble\b", r"蓝牙"],
    "rf": [r"radiofrequ", r"\brf\b", r"\b(315|433|868|915)\s?mhz", r"\b2[.,]4\s?ghz", r"\b5[.,]8\s?ghz", r"zigbee", r"z-wave",
           r"\blora\b", r"\bnfc\b", r"\brfid\b", r"射频", r"无线遥控", r"transmissor", r"transmitter"],
    "celular": [r"\b[345]g\b", r"\blte\b", r"\bgsm\b", r"wcdma", r"nb-?iot", r"cat-?m1?", r"cart[aã]o sim", r"\bsim card",
                r"chip sim", r"nano[\s-]?sim", r"蜂窝", r"移动网络"],
    "alimentacao_rede": [r"\b(100|110|115|120|127|220|230|240)\s?v(ac|~)?\b", r"100\s?-\s?240\s?v", r"bivolt", r"\bac input",
                         r"entrada ca", r"tomada", r"\bmains\b", r"交流"],
    "bateria": [r"bateria", r"battery", r"电池", r"\b\d{2,6}\s?mah\b", r"\b\d+([.,]\d+)?\s?wh\b", r"pilha"],
    "bateria_litio": [r"l[ií]tio", r"lithium", r"li-?ion", r"li-?po", r"\blipo\b", r"18650", r"21700", r"锂"],
    "carregador_fonte": [r"carregador", r"charger", r"power bank", r"powerbank", r"fonte de alimenta", r"power adapter",
                         r"power supply", r"adaptador de energia", r"充电器", r"电源适配器", r"充电宝", r"移动电源"],
    "brinquedo": [r"brinquedo", r"\btoys?\b", r"玩具"],
    "infantil": [r"crian[cç]a", r"infantil", r"\bkids?\b", r"children", r"beb[eê]", r"\bbaby\b", r"儿童", r"婴儿"],
    "instrumento_medicao": [r"medi[cç][aã]o", r"medidor", r"balan[cç]a", r"\bscale\b", r"mult[ií]metro", r"multimeter",
                            r"term[oô]metro", r"thermometer", r"\bgauge\b", r"测量", r"仪表"],
    "medico": [r"m[eé]dico", r"hospitalar", r"\bmedical\b", r"clinical", r"diagn[oó]stic", r"ox[ií]metro", r"oximeter",
               r"press[aã]o arterial", r"blood pressure", r"医疗"],
    "contato_alimentos": [r"contato com alimentos", r"food[\s-]grade", r"food contact", r"食品级", r"utens[ií]lio de cozinha"],
    "cosmetico": [r"cosm[eé]tic", r"cosmetic", r"化妆品"],
    "quimico": [r"subst[aâ]ncia qu[ií]mica", r"chemical", r"solvente", r"化学品"],
    "led_iluminacao": [r"\bled\b", r"l[aâ]mpada", r"lumin[aá]ria", r"\blamp\b", r"\blight\b", r"灯"],
}
EXPLICIT = {  # campo do formulário → característica
    "wifi": "wifi", "bluetooth": "bluetooth", "radiofrequencia": "rf", "celular": "celular", "bateria": "bateria",
    "bateria_litio": "bateria_litio", "brinquedo": "brinquedo", "publico_infantil": "infantil",
    "instrumento_medicao": "instrumento_medicao", "equipamento_medico": "medico", "contato_alimentos": "contato_alimentos",
    "alimentacao_rede": "alimentacao_rede", "carregador_fonte": "carregador_fonte", "produto_controlado": "controlado",
}
LABEL = {
    "wifi": "Wi-Fi", "bluetooth": "Bluetooth", "rf": "outro transmissor de radiofrequência", "celular": "comunicação celular",
    "alimentacao_rede": "alimentação pela rede elétrica", "bateria": "bateria", "bateria_litio": "bateria de lítio",
    "carregador_fonte": "carregador/fonte de alimentação", "brinquedo": "brinquedo", "infantil": "destinado a crianças",
    "instrumento_medicao": "instrumento de medição", "medico": "equipamento médico/saúde", "contato_alimentos": "contato com alimentos",
    "cosmetico": "cosmético", "quimico": "substância química", "controlado": "produto controlado", "led_iluminacao": "iluminação/LED",
}
YES, NO, UNKNOWN = "sim", "nao", "nao_sei"


def _n(t: str) -> str:
    return unicodedata.normalize("NFC", str(t or "")).lower()


def _find(text: str, pats: list[str]) -> str | None:
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            a, b = max(0, m.start() - 40), min(len(text), m.end() + 40)
            return text[a:b].replace("\n", " ").strip()
    return None


def tri(v) -> str:
    v = _n(v).strip()
    if v in ("sim", "s", "yes", "true", "1", "on"):
        return YES
    if v in ("nao", "não", "n", "no", "false", "0", "off"):
        return NO
    return UNKNOWN


def extract(form: dict, attachment_texts: list[str] | None = None) -> dict:
    """Devolve {'caracteristicas': {k: {valor, origem, evidencia}}, 'indicios_nome': [...], 'operacao': {...}}."""
    feats: dict[str, dict] = {}
    for field, k in EXPLICIT.items():
        if field in form and form[field] not in (None, ""):
            t = tri(form[field])
            if t != UNKNOWN:
                feats[k] = {"valor": t == YES, "origem": "formulário", "evidencia": f"{field} = {form[field]}"}
            else:
                feats[k] = {"valor": None, "origem": "formulário", "evidencia": f"{field} = não sei"}
    tech = " ".join(_n(form.get(f)) for f in ("descricao_tecnica", "componentes", "frequencia", "tensao", "potencia",
                                              "material", "documentacao_disponivel"))
    att = " ".join(_n(t) for t in (attachment_texts or []))
    for k, pats in KW.items():
        if feats.get(k, {}).get("valor") is not None:
            continue                       # resposta explícita prevalece
        ev = _find(tech, pats)
        src = "descrição técnica"
        if not ev and att:
            ev, src = _find(att, pats), "anexo"
        if ev:
            feats[k] = {"valor": True, "origem": src, "evidencia": ev}
    # tensão informada no campo próprio
    tens = _n(form.get("tensao"))
    if "alimentacao_rede" not in feats and re.search(r"(100|110|115|120|127|220|230|240)\s?v|bivolt", tens):
        feats["alimentacao_rede"] = {"valor": True, "origem": "formulário", "evidencia": f"tensão = {form.get('tensao')}"}
    if feats.get("bateria_litio", {}).get("valor") and "bateria" not in feats:
        feats["bateria"] = {"valor": True, "origem": feats["bateria_litio"]["origem"], "evidencia": feats["bateria_litio"]["evidencia"]}
    name = _n(f"{form.get('nome_comercial', '')} {form.get('categoria', '')}")
    indicios = []
    for k, pats in KW.items():
        if k in feats:
            continue
        ev = _find(name, pats)
        if ev:
            indicios.append({"caracteristica": k, "rotulo": LABEL[k], "trecho": ev})
    destino = _n(form.get("destinacao") or form.get("uso"))
    op = {
        "comercializacao": destino in ("comercializacao", "comercialização", "revenda", "comercial"),
        "uso_proprio": destino in ("uso_proprio", "uso próprio", "proprio"),
        "amostra_ensaio": destino in ("amostra", "amostra_ensaio", "amostra para ensaio", "ensaio"),
        "componente": _n(form.get("produto_completo")) in ("componente", "component", "modulo", "módulo", "peça", "peca"),
        "completo": _n(form.get("produto_completo")) in ("completo", "produto completo", "acabado"),
        "destinacao_informada": bool(destino),
    }
    any_radio = [k for k in ("wifi", "bluetooth", "rf", "celular") if feats.get(k, {}).get("valor")]
    return {"caracteristicas": feats, "indicios_nome": indicios, "operacao": op, "radio": any_radio}


def describe(feats: dict) -> list[str]:
    out = []
    for k, f in feats["caracteristicas"].items():
        v = "sim" if f["valor"] else ("não" if f["valor"] is False else "não sei")
        out.append(f"{LABEL.get(k, k)}: {v} ({f['origem']}: {f['evidencia'][:90]})")
    return out
