"""
Pipeline de NLP para termos de busca, manchetes e opiniões (local, sem bibliotecas externas):

  1 limpeza → 2 idioma → 3 tokenização → 4 entidades (conceitos, marcas, modelos) →
  5 identificação do produto (núcleo + qualificadores) → 6 atributos técnicos →
  7 normalização → 8 chave canônica (deduplicação) → 9 agrupamento (família/variante) →
  10 categoria comercial

Exemplos:
  "Melhor carregador rápido para iPhone"  → produto {charger, fast, iphone_compat}, idioma pt
  "Best motorcycle helmet 2026"           → produto {helmet, motorcycle}, idioma en
  "65W 氮化镓充电器"                        → produto {charger, gan}, variante 65w, idioma zh

Regras de deduplicação: a chave do produto é o conjunto de conceitos (independe do idioma e da
ordem das palavras). Atributos numéricos (potência, capacidade, armazenamento) NÃO entram na
chave da família — geram variantes distintas (carregador 20W ≠ carregador 140W, mesma família).
"""
from __future__ import annotations

import re
import unicodedata

from .lexicon import BRANDS, CONCEPTS, HEADS, MODS, QUALIFIERS, STOP_ZH

CJK = re.compile(r"[一-鿿]")
PT_HINTS = {"de", "para", "com", "sem", "melhor", "qual", "comprar", "preço", "preco", "não", "nao", "que", "como",
            "é", "o", "a", "os", "as", "do", "da", "um", "uma", "barato", "onde", "vale", "pena", "mais", "em"}
EN_HINTS = {"the", "for", "with", "best", "buy", "how", "what", "cheap", "and", "to", "is", "of", "near", "me",
            "review", "which", "vs", "top", "price", "under"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# 1 ---------------------------------------------------------------------------------------- limpeza
def clean(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[#@]\w+", " ", t)
    t = re.sub(r"[\"“”‘’'`´|•·…!?¿¡()\[\]{}<>*_~^=;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# 2 ---------------------------------------------------------------------------------------- idioma
def detect_lang(text: str) -> str:
    t = clean(text).lower()
    if CJK.search(t):
        return "zh"
    toks = re.findall(r"[a-zà-ÿ]+", t)
    pt = sum(1 for w in toks if w in PT_HINTS) + 2 * len(re.findall(r"[ãõçáéíóúâêô]", t))
    en = sum(1 for w in toks if w in EN_HINTS)
    if pt == en:
        # desempate pelo léxico de produtos: palavras que só existem em um idioma
        pt += sum(1 for c in CONCEPTS.values() for w in c[2] if " " not in w and w in toks and w not in c[3])
        en += sum(1 for c in CONCEPTS.values() for w in c[3] if " " not in w and w in toks and w not in c[2])
    return "pt" if pt > en else "en" if en > pt else "und"


# 3 ---------------------------------------------------------------------------------------- tokenização
TOKEN = re.compile(r"usb[\s-]?c|type[\s-]?c|tipo[\s-]?c|wi[\s-]?fi|\d+(?:[.,]\d+)?\s?(?:w|mah|v|gb|tb|l|ml|pol|polegadas|\"|in|cm|mm|k|hz|db)\b|[a-z0-9à-ÿ+]+(?:-[a-z0-9à-ÿ]+)*")


def tokenize(text: str, lang: str | None = None) -> list[str]:
    t = clean(text).lower()
    if (lang or detect_lang(t)) == "zh":
        return _zh_segment(t)
    return [re.sub(r"\s+", "", m) if re.match(r"\d", m) else m.replace(" ", "-") if re.match(r"(usb|type|tipo|wi)", m) else m
            for m in TOKEN.findall(t)]


# índice de expressões por idioma: expressão normalizada → conceito
def _norm(s: str) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"usb[\s-]?c|type[\s-]?c|tipo[\s-]?c", "usb-c", s)
    s = re.sub(r"wi[\s-]?fi", "wi-fi", s)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s+-]", " ", s)).strip()


_INDEX: dict[str, list[tuple[str, str]]] = {"pt": [], "en": [], "zh": []}
for cid, (_k, _cat, pts, ens, zhs) in CONCEPTS.items():
    for lang, words in (("pt", pts), ("en", ens), ("zh", zhs)):
        for w in words:
            _INDEX[lang].append((_norm(w) if lang != "zh" else w.lower(), cid))
for lang in _INDEX:
    _INDEX[lang].sort(key=lambda x: -len(x[0]))                     # mais longas primeiro
_ZH_WORDS = sorted({w for w, _ in _INDEX["zh"]} | STOP_ZH, key=len, reverse=True)


def _zh_segment(t: str) -> list[str]:
    """Máxima correspondência para frente com o léxico; o resto vira caracteres/sequências latinas."""
    out, i = [], 0
    while i < len(t):
        if t[i].isspace():
            i += 1
            continue
        m = re.match(r"\d+(?:\.\d+)?\s?(?:w|mah|v|gb|l|ml)\b|[a-z0-9-]+", t[i:])
        if m:
            out.append(m.group(0).replace(" ", ""))
            i += m.end()
            continue
        for w in _ZH_WORDS:
            if t.startswith(w, i):
                out.append(w)
                i += len(w)
                break
        else:
            out.append(t[i])
            i += 1
    return out


# 4/5 ------------------------------------------------------------------------------------- entidades
def find_concepts(text: str, lang: str) -> list[tuple[str, int]]:
    """Conceitos encontrados com a posição (para escolher o núcleo). Correspondência mais longa
    primeiro; cada trecho do texto é consumido uma única vez."""
    if lang == "zh":
        s = clean(text).lower()
        found, used = [], [False] * len(s)
        for w, cid in _INDEX["zh"]:
            start = s.find(w)
            while start >= 0:
                if not any(used[start:start + len(w)]):
                    found.append((cid, start))
                    for k in range(start, start + len(w)):
                        used[k] = True
                start = s.find(w, start + 1)
        # termos latinos dentro do texto chinês (ex.: "led", "usb-c")
        for cid, pos in find_concepts(re.sub(r"[一-鿿]", " ", s), "en"):
            if (cid, pos) not in found:
                found.append((cid, pos))
        return sorted(set(found), key=lambda x: x[1])
    s = " " + _norm(text) + " "
    found = []
    for w, cid in _INDEX[lang if lang in ("pt", "en") else "en"] + (_INDEX["en"] if lang == "pt" else _INDEX["pt"] if lang == "en" else []):
        pat = " " + w + " "
        start = s.find(pat)
        while start >= 0:
            found.append((cid, start))
            s = s[:start + 1] + "#" * len(w) + s[start + 1 + len(w):]       # consome o trecho
            start = s.find(pat)
    return sorted(found, key=lambda x: x[1])


# 6 ---------------------------------------------------------------------------------------- atributos
ATTR_RX = [
    ("potencia_w", re.compile(r"(\d{1,4}(?:[.,]\d)?)\s?(?:w|watts?)\b")),
    ("capacidade_mah", re.compile(r"(\d{3,6})\s?mah\b")),
    ("tensao_v", re.compile(r"\b(110|127|220|240|12|24)\s?v\b")),
    ("armazenamento_gb", re.compile(r"(\d{1,4})\s?(?:gb|tb)\b")),
    ("volume_l", re.compile(r"(\d{1,2}(?:[.,]\d)?)\s?(?:litros?|l)\b")),
    ("tela_pol", re.compile(r"(\d{1,3}(?:[.,]\d)?)\s?(?:pol|polegadas|\"|inch|inches|in)\b")),
    ("resolucao", re.compile(r"\b(4k|8k|1080p|2k|720p|full hd|fhd)\b")),
]
VARIANT_ATTRS = ("potencia_w", "capacidade_mah", "armazenamento_gb", "volume_l", "tela_pol", "resolucao")
TECH = {"gan": "GaN", "bluetooth": "Bluetooth", "wi-fi": "Wi-Fi", "wifi": "Wi-Fi", "zigbee": "Zigbee",
        "magsafe": "MagSafe", "pd": "Power Delivery", "qi": "Qi", "anc": "ANC", "bivolt": "bivolt",
        "氮化镓": "GaN", "蓝牙": "Bluetooth", "solar": "solar", "太阳能": "solar"}
COMPAT = {"iphone": "iPhone", "ipad": "iPad", "macbook": "MacBook", "samsung": "Samsung", "galaxy": "Samsung Galaxy",
          "xiaomi": "Xiaomi", "android": "Android", "苹果": "iPhone", "alexa": "Alexa", "google home": "Google Home"}


def extract_attributes(text: str) -> dict:
    t = strip_accents(clean(text).lower())
    t = re.sub(r"(\d)\s*([.,])\s*(\d)", r"\1\2\3", t)
    out: dict = {}
    for name, rx in ATTR_RX:
        m = rx.search(t)
        if m:
            v = m.group(1).replace(",", ".")
            if name == "armazenamento_gb" and re.search(rf"{re.escape(m.group(1))}\s?tb", t):
                v = str(int(float(v) * 1024))
            out[name] = v
    if re.search(r"usb[\s-]?c|type[\s-]?c|tipo[\s-]?c", t):
        out["conector"] = "USB-C"
    elif "lightning" in t:
        out["conector"] = "Lightning"
    tech = sorted({v for k, v in TECH.items() if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", t) or (CJK.search(k) and k in text)})
    if tech:
        out["tecnologia"] = tech
    comp = sorted({v for k, v in COMPAT.items() if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", t) or (CJK.search(k) and k in text)})
    if comp:
        out["compatibilidade"] = comp
    brands = sorted({b for b in BRANDS if re.search(rf"(?<![\w]){re.escape(strip_accents(b))}(?![\w])", t)})
    if brands:
        out["marca"] = brands[0]
    for m in re.finditer(r"\b([a-z]{1,4}-?\d{2,5}[a-z]{0,3})\b", t):
        mdl = m.group(1)
        if re.fullmatch(r"(usb|wi|type|tipo|ip)-?\w*", mdl) or re.search(r"\d(w|v|mah|gb|tb|l|ml|k|hz|p|db|mm|cm)$", mdl):
            continue
        out["modelo"] = mdl.upper()
        break
    return out


# 7–10 ------------------------------------------------------------------------------------ análise
def analyze(text: str, lang: str | None = None) -> dict:
    """Analisa um termo/manchete e devolve o produto identificado (ou None)."""
    raw = clean(text)
    lang = lang or detect_lang(raw)
    found = find_concepts(raw, lang if lang != "und" else "en")
    heads = [(c, p) for c, p in found if c in HEADS]
    mods = sorted({c for c, _ in found if c in MODS})
    attrs = extract_attributes(raw)
    res = {"texto": raw, "idioma": lang, "tokens": tokenize(raw, lang), "atributos": attrs, "produto": None}
    if not heads:
        return res
    # núcleo: pt/zh → o primeiro (o núcleo vem antes ou o chinês junta tudo); en → o último antes de "for/with"
    if lang == "en":
        cut = re.search(r"\b(for|with|to)\b", _norm(raw))
        pos_cut = cut.start() + 1 if cut else 10 ** 6
        cand = [h for h in heads if h[1] < pos_cut] or heads
        head = cand[-1][0]
    else:
        head = heads[0][0]
    others = {c for c, _ in heads if c != head}
    if "smartphone" in others and head != "smartphone" and re.search(r"iphone|苹果", raw.lower()):
        mods = sorted(set(mods) | {"iphone_compat"})
    if head == "smartphone":
        mods = [m for m in mods if m != "iphone_compat"]
    # qualificadores redundantes com o núcleo (ex.: 'robô' em 'aspirador robô' é parte do produto e fica)
    key = "+".join([head] + mods)
    variant = None
    for a in VARIANT_ATTRS:
        if a in attrs:
            unit = {"potencia_w": "w", "capacidade_mah": "mah", "armazenamento_gb": "gb", "volume_l": "l",
                    "tela_pol": "pol", "resolucao": ""}[a]
            variant = f"{attrs[a]}{unit}".replace(".0", "")
            break
    res["produto"] = {"chave": key, "nucleo": head, "qualificadores": mods, "variante": variant,
                      "categoria": CONCEPTS[head][1], **names_for(head, mods)}
    return res


def names_for(head: str, mods: list[str]) -> dict:
    """Nomes legíveis gerados a partir dos conceitos (pt: núcleo + qualificadores; en/zh: o contrário)."""
    pt = CONCEPTS[head][2][0]
    pt_mods = [CONCEPTS[m][2][0] for m in mods if m not in ("iphone_compat",)]
    en = CONCEPTS[head][3][0]
    en_mods = [CONCEPTS[m][3][0] for m in mods if m not in ("iphone_compat",)]
    zh = CONCEPTS[head][4][0]
    zh_mods = [CONCEPTS[m][4][0] for m in mods if m not in ("iphone_compat",)]
    if "iphone_compat" in mods:
        pt_mods.append("para iPhone")
        en_mods.insert(0, "iPhone")
        zh_mods.insert(0, "苹果")
    name_pt = " ".join([pt] + pt_mods)
    return {"nome_pt": _cap(name_pt), "nome_en": _cap(" ".join(en_mods + [en])),
            "nome_zh": "".join(zh_mods + [zh])}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def similar(a: str, b: str) -> float:
    """Similaridade entre dois termos (Jaccard de trigramas de caracteres normalizados) — usada
    para agrupar grafias diferentes que não estão no léxico."""
    def grams(s):
        s = f"  {_norm(s)}  "
        return {s[i:i + 3] for i in range(len(s) - 2)}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0
