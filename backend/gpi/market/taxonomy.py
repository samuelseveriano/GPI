"""
Taxonomia inicial, normalização multilíngue e deduplicação (sem LLMs, sem serviços pagos).

A taxonomia é apenas o PONTO DE PARTIDA da descoberta:
  * Categorias prioritárias ↔ posições SH4 (NCM) do comércio exterior.
  * Conceitos de produto (títulos da Wikipédia em inglês); os nomes em português
    e chinês são obtidos automaticamente pelos links interlínguas da própria
    Wikipédia na primeira sincronização (não são traduções feitas pelo GPI).
A descoberta automática (discovery.py) expande esse conjunto com qualquer posição
SH4 cujas importações da China cresçam de forma relevante, inclusive fora das
categorias prioritárias.
"""
from __future__ import annotations

import re
import unicodedata

PRIORITY_CATEGORIES = [
    "Iluminação", "Materiais elétricos", "Casa inteligente", "Ferramentas",
    "Eletrodomésticos", "Utilidades domésticas", "Eletrônicos", "Acessórios tecnológicos",
]

# Posição SH4 (4 primeiros dígitos da NCM) → categoria prioritária
HS_CATEGORY = {
    "8539": "Iluminação", "9405": "Iluminação", "8513": "Iluminação", "8541": "Iluminação",
    "8536": "Materiais elétricos", "8544": "Materiais elétricos", "8537": "Materiais elétricos",
    "8538": "Materiais elétricos", "8535": "Materiais elétricos", "8546": "Materiais elétricos",
    "8531": "Casa inteligente", "9032": "Casa inteligente", "8543": "Casa inteligente",
    "8526": "Casa inteligente",
    "8467": "Ferramentas", "8205": "Ferramentas", "8204": "Ferramentas", "8203": "Ferramentas",
    "8207": "Ferramentas", "9030": "Ferramentas", "8515": "Ferramentas", "8202": "Ferramentas",
    "8516": "Eletrodomésticos", "8509": "Eletrodomésticos", "8508": "Eletrodomésticos",
    "8414": "Eletrodomésticos", "8415": "Eletrodomésticos", "8418": "Eletrodomésticos",
    "8450": "Eletrodomésticos", "8421": "Eletrodomésticos", "8510": "Eletrodomésticos",
    "3924": "Utilidades domésticas", "7323": "Utilidades domésticas", "9617": "Utilidades domésticas",
    "7615": "Utilidades domésticas", "6912": "Utilidades domésticas", "8211": "Utilidades domésticas",
    "8215": "Utilidades domésticas", "7013": "Utilidades domésticas",
    "8518": "Eletrônicos", "8528": "Eletrônicos", "8471": "Eletrônicos", "8517": "Eletrônicos",
    "8525": "Eletrônicos", "8519": "Eletrônicos", "8521": "Eletrônicos",
    "8507": "Acessórios tecnológicos", "8504": "Acessórios tecnológicos", "8523": "Acessórios tecnológicos",
    "8473": "Acessórios tecnológicos",
}

# Conceitos de produto: título em inglês na Wikipédia → (categoria, posições SH4 relacionadas)
CONCEPTS = {
    "LED lamp": ("Iluminação", ["8539"]),
    "LED strip light": ("Iluminação", ["9405", "8541"]),
    "Solar lamp": ("Iluminação", ["9405"]),
    "Flashlight": ("Iluminação", ["8513"]),
    "Christmas lights": ("Iluminação", ["9405"]),
    "Light fixture": ("Iluminação", ["9405"]),
    "Power strip": ("Materiais elétricos", ["8536"]),
    "Circuit breaker": ("Materiais elétricos", ["8536"]),
    "Extension cord": ("Materiais elétricos", ["8544"]),
    "Residual-current device": ("Materiais elétricos", ["8536"]),
    "Light switch": ("Materiais elétricos", ["8536"]),
    "Surge protector": ("Materiais elétricos", ["8536"]),
    "Home automation": ("Casa inteligente", ["8517", "8543"]),
    "Smart speaker": ("Casa inteligente", ["8518"]),
    "Smart lock": ("Casa inteligente", ["8301"]),
    "Smart thermostat": ("Casa inteligente", ["9032"]),
    "Smart plug": ("Casa inteligente", ["8536"]),
    "Robotic vacuum cleaner": ("Casa inteligente", ["8508"]),
    "Impact driver": ("Ferramentas", ["8467"]),
    "Angle grinder": ("Ferramentas", ["8467"]),
    "Multimeter": ("Ferramentas", ["9030"]),
    "Soldering iron": ("Ferramentas", ["8515"]),
    "Power tool": ("Ferramentas", ["8467"]),
    "Laser level": ("Ferramentas", ["9015"]),
    "Air fryer": ("Eletrodomésticos", ["8516"]),
    "Microwave oven": ("Eletrodomésticos", ["8516"]),
    "Electric kettle": ("Eletrodomésticos", ["8516"]),
    "Blender": ("Eletrodomésticos", ["8509"]),
    "Air purifier": ("Eletrodomésticos", ["8421"]),
    "Dehumidifier": ("Eletrodomésticos", ["8479"]),
    "Vacuum flask": ("Utilidades domésticas", ["9617"]),
    "Pressure cooker": ("Utilidades domésticas", ["7323", "7615"]),
    "Water filter": ("Utilidades domésticas", ["8421"]),
    "Food storage container": ("Utilidades domésticas", ["3924"]),
    "Kitchen scale": ("Utilidades domésticas", ["8423"]),
    "Headphones": ("Eletrônicos", ["8518"]),
    "Smartwatch": ("Eletrônicos", ["8517"]),
    "Action camera": ("Eletrônicos", ["8525"]),
    "Wireless speaker": ("Eletrônicos", ["8518"]),
    "Projector": ("Eletrônicos", ["8528"]),
    "Power bank": ("Acessórios tecnológicos", ["8507"]),
    "USB-C": ("Acessórios tecnológicos", ["8544"]),
    "Inductive charging": ("Acessórios tecnológicos", ["8504"]),
    "Screen protector": ("Acessórios tecnológicos", ["3919"]),
    "Selfie stick": ("Acessórios tecnológicos", ["9620"]),
    "Ring light": ("Acessórios tecnológicos", ["9405"]),
}

STOP = {"de", "da", "do", "das", "dos", "e", "para", "com", "em", "a", "o", "as", "os", "uso",
        "of", "for", "and", "the", "with", "an", "or", "outros", "outras", "suas", "seus", "partes"}


def strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _has_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def singular(tok: str) -> str:
    """Redução simples de plural (pt/en). Regras determinísticas, documentadas."""
    for suf, rep in (("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("ies", "y"),
                     ("ns", "m"), ("res", "r"), ("zes", "z"), ("ses", "s")):
        if tok.endswith(suf) and len(tok) > len(suf) + 2:
            return tok[: -len(suf)] + rep
    if tok.endswith("s") and len(tok) > 3 and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def normalize_tokens(text: str) -> list[str]:
    """Tokens normalizados: sem acentos, minúsculos, sem stopwords, singular.
    Texto chinês é representado por bigramas de caracteres."""
    if not text:
        return []
    if _has_cjk(text):
        chars = [c for c in text if "一" <= c <= "鿿"]
        return [a + b for a, b in zip(chars, chars[1:])] or chars
    s = strip_accents(text).lower()
    toks = re.findall(r"[a-z0-9]+", s)
    return [singular(t) for t in toks if t not in STOP and len(t) > 1]


def normalize_name(text: str) -> str:
    return " ".join(normalize_tokens(text))


def _trigrams(s: str) -> set[str]:
    s = f"  {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def similarity(a: str, b: str) -> float:
    """0..1: média da similaridade de Jaccard dos tokens e do coeficiente de Dice
    dos trigramas de caracteres sobre os nomes normalizados."""
    ta, tb = set(normalize_tokens(a)), set(normalize_tokens(b))
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    ga, gb = _trigrams(" ".join(sorted(ta))), _trigrams(" ".join(sorted(tb)))
    dice = 2 * len(ga & gb) / (len(ga) + len(gb))
    return (jac + dice) / 2


def dedupe(names: list[str], threshold: float = 0.72) -> list[list[int]]:
    """Agrupa índices de nomes equivalentes (ligação simples sobre a similaridade)."""
    parent = list(range(len(names)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    norm = [normalize_name(n) for n in names]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if norm[i] and (norm[i] == norm[j] or similarity(names[i], names[j]) >= threshold):
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(names)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def category_for_heading(code: str) -> str:
    return HS_CATEGORY.get(str(code)[:4], "Outras categorias")


def concept_key(en_title: str) -> str:
    return "wiki:" + re.sub(r"[^a-z0-9]+", "-", en_title.lower()).strip("-")


def heading_key(code: str) -> str:
    return f"sh4:{str(code)[:4]}"
