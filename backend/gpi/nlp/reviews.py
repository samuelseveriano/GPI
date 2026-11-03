"""
NLP local para opiniões de consumidores (português e inglês) — sem modelos pesados, sem APIs.

Sentimento por léxico com regras (estilo VADER):
  * palavras positivas/negativas com peso (1 a 3);
  * negação inverte e atenua a polaridade das 3 palavras seguintes (×−0,75);
  * intensificadores multiplicam o peso seguinte (×1,5) e atenuadores (×0,6);
  * após 'mas'/'porém'/'but', a parte final pesa 1,5× e a inicial 0,5×;
  * pontuação: '!' reforça o último termo.
  pontuação normalizada  s = S / √(S² + 15)  ∈ (−1, 1);  positivo se s ≥ 0,05, negativo se s ≤ −0,05.

Aspectos: termos de domínio para durabilidade, bateria, aquecimento, defeito elétrico, montagem,
assistência técnica, custo-benefício, qualidade, entrega, vendedor e atendimento. O sentimento de
cada aspecto é o da frase em que ele aparece.

Alvo da reclamação: produto × entrega × vendedor × atendimento (pelo aspecto dominante).

Limitações (exibidas na interface): ironia, gírias e contexto longo não são bem tratados; a
frequência de reclamações não é taxa de defeito.
"""
from __future__ import annotations

import math
import re

from ..market.taxonomy import strip_accents

POS = {
    # português
    "bom": 2, "boa": 2, "otimo": 3, "otima": 3, "excelente": 3, "perfeito": 3, "perfeita": 3, "maravilhoso": 3,
    "recomendo": 3, "adorei": 3, "amei": 3, "gostei": 2, "satisfeito": 2, "satisfeita": 2, "funciona": 1,
    "funcionando": 1, "rapido": 1, "rapida": 1, "eficiente": 2, "resistente": 2, "duravel": 2, "silencioso": 2,
    "silenciosa": 2, "bonito": 1, "bonita": 1, "pratico": 2, "pratica": 2, "barato": 1, "vale": 1, "melhor": 2,
    "superou": 2, "incrivel": 3, "top": 2, "confiavel": 2, "facil": 1, "forte": 1, "potente": 2, "economico": 2,
    "custo-beneficio": 2, "acertei": 2, "show": 2, "qualidade": 1,
    # inglês
    "good": 2, "great": 3, "excellent": 3, "perfect": 3, "amazing": 3, "awesome": 3, "love": 3, "loved": 3,
    "recommend": 3, "recommended": 3, "works": 1, "working": 1, "fast": 1, "reliable": 2, "durable": 2,
    "sturdy": 2, "quiet": 2, "worth": 2, "best": 2, "happy": 2, "solid": 2, "easy": 1, "powerful": 2, "nice": 2,
}
NEG = {
    "ruim": 2, "pessimo": 3, "pessima": 3, "horrivel": 3, "terrivel": 3, "lixo": 3, "defeito": 3, "defeituoso": 3,
    "quebrou": 3, "quebrado": 3, "quebrada": 3, "parou": 2, "estragou": 3, "queimou": 3, "esquenta": 2,
    "superaquece": 3, "aquece": 1, "fraco": 2, "fraca": 2, "frageil": 2, "barulhento": 2, "barulhenta": 2,
    "decepcionante": 3, "decepcionado": 3, "decepcao": 3, "arrependido": 3, "arrependimento": 3, "problema": 2,
    "problemas": 2, "falha": 2, "falhou": 3, "caro": 1, "demorou": 2, "atraso": 2, "atrasou": 2, "nunca": 1,
    "golpe": 3, "enganado": 3, "nao recomendo": 3, "devolvi": 2, "devolucao": 1, "reclamacao": 2, "choque": 3,
    "vazou": 2, "vazando": 2, "travando": 2, "trava": 1, "descarrega": 1, "inchou": 3, "ruido": 1, "pior": 3,
    # inglês
    "bad": 2, "terrible": 3, "awful": 3, "horrible": 3, "broke": 3, "broken": 3, "defective": 3, "faulty": 3,
    "died": 3, "dead": 2, "overheats": 3, "overheating": 3, "hot": 1, "cheap": 1, "flimsy": 2, "noisy": 2,
    "disappointed": 3, "disappointing": 3, "waste": 3, "useless": 3, "refund": 2, "returned": 2, "issue": 2,
    "issues": 2, "problem": 2, "problems": 2, "fail": 3, "failed": 3, "worst": 3, "scam": 3, "junk": 3, "leaks": 2,
}
NEGATORS = {"nao", "nem", "nunca", "jamais", "sem", "not", "no", "never", "dont", "doesnt", "didnt", "isnt", "wasnt", "cant", "wont"}
BOOST = {"muito": 1.5, "super": 1.5, "extremamente": 1.8, "bem": 1.3, "demais": 1.5, "very": 1.5, "really": 1.4,
         "extremely": 1.8, "so": 1.3, "totally": 1.5}
DAMP = {"pouco": 0.6, "meio": 0.6, "razoavelmente": 0.7, "slightly": 0.6, "somewhat": 0.7, "bit": 0.6}
CONTRAST = {"mas", "porem", "contudo", "entretanto", "but", "however"}

ASPECTS = {
    "durabilidade": ["durou", "durabilidade", "quebrou", "quebrado", "estragou", "parou de funcionar", "pouco tempo",
                     "meses de uso", "durable", "broke", "stopped working", "lasted", "after a month", "resistente", "frageil"],
    "bateria": ["bateria", "carga", "carregar", "carregamento", "descarrega", "autonomia", "battery", "charge",
                "charging", "mah", "inchou"],
    "aquecimento": ["esquenta", "aquece", "superaquece", "quente", "temperatura", "overheat", "overheats",
                    "overheating", "hot", "heats up"],
    "defeito_eletrico": ["curto", "choque", "queimou", "fumaca", "faisca", "disjuntor", "fiacao", "tomada",
                         "short circuit", "shock", "burned", "smoke", "sparks", "fuse"],
    "montagem": ["montagem", "montar", "encaixe", "parafuso", "instalacao", "instalar", "manual", "assembly",
                 "install", "installation", "screws"],
    "assistencia_tecnica": ["assistencia", "suporte", "conserto", "reparo", "autorizada", "repair", "support"],
    "garantia": ["garantia", "warranty", "troca", "devolucao", "devolver", "return policy", "rma", "acionar a garantia"],
    "custo_beneficio": ["custo-beneficio", "custo beneficio", "preco", "barato", "caro", "vale a pena", "vale cada",
                        "price", "worth", "value for money", "expensive", "cheap"],
    "qualidade": ["qualidade", "acabamento", "material", "plastico", "quality", "build quality", "finish"],
    "entrega": ["entrega", "frete", "chegou", "correios", "transportadora", "prazo", "atraso", "embalagem",
                "delivery", "shipping", "arrived", "package"],
    "vendedor": ["vendedor", "loja", "anuncio", "seller", "store", "listing"],
    "atendimento": ["atendimento", "sac", "atendente", "resposta", "contato", "customer service", "reembolso", "refund"],
}
TARGET = {"entrega": "entrega", "vendedor": "vendedor", "atendimento": "atendimento", "garantia": "garantia"}
TARGET_NAMES = {"produto": "Produto", "entrega": "Transporte/entrega", "vendedor": "Vendedor", "atendimento": "Atendimento",
                "garantia": "Garantia/troca"}
ASPECT_NAMES = {"durabilidade": "Durabilidade", "bateria": "Bateria", "aquecimento": "Aquecimento",
                "defeito_eletrico": "Defeito elétrico", "montagem": "Montagem/instalação",
                "assistencia_tecnica": "Assistência técnica", "garantia": "Garantia/troca", "custo_beneficio": "Custo-benefício",
                "qualidade": "Qualidade/acabamento", "entrega": "Entrega", "vendedor": "Vendedor",
                "atendimento": "Atendimento"}


def _norm(text: str) -> str:
    return strip_accents(text or "").lower()


def tokens(text: str) -> list[str]:
    t = _norm(text).replace("n't", "nt").replace("custo-beneficio", "custo-beneficio")
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?|!", t)


def sentence_score(toks: list[str]) -> float:
    total, i = 0.0, 0
    neg_left, mult = 0, 1.0
    contrast_at = None
    contribs = []
    while i < len(toks):
        w = toks[i]
        if w in CONTRAST:
            contrast_at = len(contribs)
            i += 1
            continue
        if w == "!" and contribs:
            contribs[-1] *= 1.2
            i += 1
            continue
        two = f"{w} {toks[i + 1]}" if i + 1 < len(toks) else None
        if two and two in NEG:
            contribs.append(-NEG[two] * mult)
            mult, neg_left = 1.0, 0
            i += 2
            continue
        if w in NEGATORS:
            neg_left = 3
            i += 1
            continue
        if w in BOOST:
            mult *= BOOST[w]
            i += 1
            continue
        if w in DAMP:
            mult *= DAMP[w]
            i += 1
            continue
        v = POS.get(w, 0) - NEG.get(w, 0)
        if v:
            v *= mult
            if neg_left > 0:
                v *= -0.75
            contribs.append(v)
            mult = 1.0
        if neg_left > 0:
            neg_left -= 1
        i += 1
    if contrast_at is not None:
        contribs = [c * 0.5 for c in contribs[:contrast_at]] + [c * 1.5 for c in contribs[contrast_at:]]
    total = sum(contribs)
    return total / math.sqrt(total * total + 15) if total else 0.0


def label(score: float) -> str:
    return "positivo" if score >= 0.05 else ("negativo" if score <= -0.05 else "neutro")


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if s.strip()]


def analyze(text: str) -> dict:
    sents = split_sentences(text) or [text or ""]
    scores, aspects = [], {}
    for s in sents:
        tk = tokens(s)
        sc = sentence_score(tk)
        scores.append(sc)
        ns = " " + " ".join(tk) + " "
        for asp, terms in ASPECTS.items():
            if any(f" {_norm(t)} " in ns or (" " in t and _norm(t) in ns) for t in terms):
                prev = aspects.get(asp)
                aspects[asp] = sc if prev is None else (prev + sc) / 2
    overall = float(sum(scores) / len(scores)) if scores else 0.0
    # se alguma frase é claramente negativa, ela não é diluída por frases neutras
    strong = [s for s in scores if abs(s) >= 0.3]
    if strong:
        overall = float(sum(strong) / len(strong))
    lab = label(overall)
    target = "produto"
    neg_aspects = {a: v for a, v in aspects.items() if v <= -0.05}
    pool = neg_aspects or aspects
    if pool:
        non_product = [a for a in pool if a in TARGET]
        product = [a for a in pool if a not in TARGET]
        if non_product and not product:
            target = TARGET[non_product[0]]
    return {"score": round(overall, 4), "label": lab, "aspects": {a: round(v, 3) for a, v in aspects.items()},
            "target": target if aspects or lab != "neutro" else None}
