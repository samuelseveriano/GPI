"""
Product Discovery Engine 2.0 — etapas adicionais ao NLP da Fase 4:

  coletar termos → idioma → filtro de relevância comercial → entidades (núcleo, qualificadores, marca,
  modelo, especificações) → normalização → CORREÇÃO DE GRAFIA → SINÔNIMOS por similaridade (aliases já
  observados) → equivalência (chave conceitual) preservando variantes técnicas → catálogo → fontes → evidência.

Similaridade textual: RapidFuzz (token_set_ratio, 0–100) quando instalado; senão, implementação própria
(difflib.SequenceMatcher, mesma escala 0–100). Limiares documentados e testados contra agrupamentos falsos:
  * correção de grafia de uma palavra: ≥ 88 e palavra com ≥ 5 letras;
  * alias por similaridade: ≥ 92, mesmo núcleo e NENHUM atributo numérico divergente (20W ≠ 140W).

Embeddings multilíngues (sentence-transformers, paraphrase-multilingual-MiniLM-L12-v2, Apache-2.0) são
OPCIONAIS: usados só se a biblioteca e o modelo estiverem na pasta local `modelos/` — servem para sugerir
produtos RELACIONADOS, nunca para declarar equivalência técnica. Sem o modelo, nada muda.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import nlp
from .lexicon import CONCEPTS

TYPO_MIN, ALIAS_MIN = 88.0, 92.0

try:                                     # opcional
    from rapidfuzz import fuzz as _rf, process as _rfp
    BACKEND = "rapidfuzz"
except ImportError:                      # pragma: no cover — depende do ambiente
    _rf = _rfp = None
    BACKEND = "difflib (biblioteca padrão)"


def _ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return 100.0 * SequenceMatcher(None, a, b).ratio()


def similarity(a: str, b: str) -> float:
    """token_set_ratio (RapidFuzz) ou equivalente com difflib: compara interseção e restos dos conjuntos de palavras."""
    if _rf is not None:
        return float(_rf.token_set_ratio(nlp._norm(a), nlp._norm(b)))
    ta, tb = set(nlp._norm(a).split()), set(nlp._norm(b).split())
    inter = " ".join(sorted(ta & tb))
    ra, rb = " ".join(sorted(ta - tb)), " ".join(sorted(tb - ta))
    c1, c2 = (inter + " " + ra).strip(), (inter + " " + rb).strip()
    return max(_ratio(inter, c1) if inter else 0, _ratio(inter, c2) if inter else 0, _ratio(c1, c2))


def word_similarity(a: str, b: str) -> float:
    if _rf is not None:
        return float(_rf.ratio(a, b))
    return _ratio(a, b)


@lru_cache(maxsize=1)
def _vocab() -> tuple[str, ...]:
    words = set()
    for _k, _c, pts, ens, _zh in CONCEPTS.values():
        for w in pts + ens:
            words.update(t for t in nlp._norm(w).split() if len(t) >= 5)
    return tuple(sorted(words))


def correct_typos(text: str) -> str:
    """Corrige palavras de produto com erro de digitação ("carregadro" → "carregador")."""
    vocab = set(_vocab())
    out = []
    for tok in nlp._norm(text).split():
        if len(tok) < 5 or tok in vocab or re.search(r"\d", tok):
            out.append(tok)
            continue
        if _rfp is not None:
            m = _rfp.extractOne(tok, _vocab(), scorer=_rf.ratio, score_cutoff=TYPO_MIN)
            out.append(m[0] if m else tok)
        else:
            best = max(_vocab(), key=lambda w: word_similarity(tok, w))
            out.append(best if word_similarity(tok, best) >= TYPO_MIN else tok)
    return " ".join(out)


def numbers(text: str) -> dict:
    a = nlp.extract_attributes(text)
    return {k: a[k] for k in nlp.VARIANT_ATTRS + ("tensao_v",) if k in a}


def compatible(a: str, b: str) -> bool:
    """Dois termos só podem ser o mesmo item se nenhum atributo numérico divergir."""
    na, nb = numbers(a), numbers(b)
    return all(na[k] == nb[k] for k in set(na) & set(nb)) and set(na) == set(nb)


def analyze(text: str, lang: str | None = None, aliases: list[tuple[str, str]] | None = None) -> dict:
    """NLP da Fase 4 + correção de grafia + alias por similaridade (quando o léxico não reconhece)."""
    a = nlp.analyze(text, lang)
    if a["produto"]:
        a["metodo"] = "léxico"
        return a
    fixed = correct_typos(text)
    if fixed != nlp._norm(text):
        b = nlp.analyze(fixed, lang)
        if b["produto"]:
            b["texto"], b["metodo"], b["corrigido"] = a["texto"], "léxico após correção de grafia", fixed
            return b
    if aliases:
        best = max(aliases, key=lambda al: similarity(text, al[0]), default=None)
        if best and similarity(text, best[0]) >= ALIAS_MIN and compatible(text, best[0]):
            b = nlp.analyze(best[0], lang)
            if b["produto"]:
                b["texto"], b["metodo"], b["alias"] = a["texto"], f"similar a '{best[0]}'", best[0]
                return b
    a["metodo"] = "não identificado"
    return a


def is_commercial(intent: str | None) -> bool:
    return intent not in ("noticia", "entretenimento")


# ------------------------------------------------------------------ embeddings (opcional)
_EMB = {"carregado": False, "modelo": None, "motivo": None}


def embedder(models_dir: Path | None = None):
    if _EMB["carregado"]:
        return _EMB["modelo"]
    _EMB["carregado"] = True
    d = (models_dir or Path("modelos")) / "paraphrase-multilingual-MiniLM-L12-v2"
    if not d.exists():
        _EMB["motivo"] = f"modelo não encontrado em {d} (opcional)"
        return None
    try:
        from sentence_transformers import SentenceTransformer
        _EMB["modelo"] = SentenceTransformer(str(d), device="cpu")
    except Exception as e:  # noqa: BLE001
        _EMB["motivo"] = f"sentence-transformers indisponível ({type(e).__name__})"
    return _EMB["modelo"]


def related_semantic(names: dict[str, str], top: int = 8, models_dir: Path | None = None) -> dict[str, list[tuple[str, float]]] | None:
    """Produtos relacionados por similaridade de embeddings (cosseno). None se o modelo não estiver disponível."""
    m = embedder(models_dir)
    if m is None:
        return None
    import numpy as np
    ids = list(names)
    v = m.encode([names[i] for i in ids], normalize_embeddings=True, show_progress_bar=False)
    sim = v @ v.T
    out = {}
    for i, pid in enumerate(ids):
        order = np.argsort(-sim[i])
        out[pid] = [(ids[j], float(sim[i, j])) for j in order if j != i][:top]
    return out


def status() -> dict:
    return {"similaridade": BACKEND, "limiar_grafia": TYPO_MIN, "limiar_alias": ALIAS_MIN,
            "embeddings": "ativo" if _EMB["modelo"] is not None else (_EMB["motivo"] or "não carregado (opcional)")}
