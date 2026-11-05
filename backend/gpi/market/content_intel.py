"""
Análise do conteúdo coletado: associação a produtos, NLP de opiniões, séries de menções,
resumos de reviews e de YouTube, e extração de atributos para o comparador.

Regras de uso:
  * Dados do YouTube NÃO passam por NLP nem entram em métricas combinadas com outras fontes
    (políticas de desenvolvedor do YouTube); só somas e médias de dados do próprio YouTube.
  * Frequência de reclamações não é taxa de defeito.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict

from ..connectors.content import ProductMatcher
from . import taxonomy as tx
from ..nlp import reviews as nlp
from .content_store import ContentStore
from .store import MarketStore

NLP_SOURCES = ("reddit", "rss", "google_news")


def process(store: MarketStore, content: ContentStore) -> dict:
    db = store.db
    matcher = ProductMatcher(store.products())
    rows = db.query("SELECT source, item_id, title, text, product_key, sentiment, lang FROM content_items")
    matched = analysed = 0
    from ..intel import understanding as U
    U.ensure(db)
    with db.lock:
        for r in rows:
            sets, vals = [], []
            # v0.9: vídeos do YouTube só se associam pela correspondência com o produto consultado (understanding.reassess_
            # content). Antes este casador por palavras reassociava vídeos que a v0.8 tinha rejeitado.
            if not r["product_key"] and r["source"] != "youtube":
                u = U.understand(f"{r['title'] or ''}", (r["lang"] or "")[:2] or None)
                pk = matcher.match(f"{r['title'] or ''} {r['text'] or ''}") if u["estado"] == "confirmada" else None
                if pk:
                    sets.append("product_key = ?"); vals.append(pk); matched += 1
                elif u["estado"] in ("ambigua", "provavel"):
                    U.queue_review(db, r["source"], r["item_id"], r["title"] or "", r["lang"], u)
            if r["sentiment"] is None and r["source"] in NLP_SOURCES:
                text = r["text"] if (r["text"] and len(r["text"]) > 40) else f"{r['title'] or ''}. {r['text'] or ''}"
                a = nlp.analyze(text)
                sets += ["sentiment = ?", "sentiment_label = ?", "aspects = ?", "target = ?"]
                vals += [a["score"], a["label"], json.dumps(a["aspects"]), a["target"]]
                analysed += 1
            if sets:
                db.con.execute(f"UPDATE content_items SET {', '.join(sets)} WHERE source = ? AND item_id = ?",
                               (*vals, r["source"], r["item_id"]))
        db.con.commit()
    n_series = mention_series(store)
    store.save_result("reviews", review_summary(store, content))
    store.save_result("youtube", youtube_summary(content))
    return {"associados": matched, "analisados_nlp": analysed, "series_mencoes": n_series}


def mention_series(store: MarketStore) -> int:
    rows = store.db.query(
        "SELECT product_key, substr(published_at, 1, 7) AS m, COUNT(*) AS n FROM content_items "
        "WHERE product_key IS NOT NULL AND published_at IS NOT NULL AND source IN ('rss', 'google_news', 'reddit') "
        "AND kind <> 'comentario' GROUP BY product_key, m")
    by = defaultdict(list)
    for r in rows:
        by[r["product_key"]].append((f"{r['m']}-01", float(r["n"])))
    names = {p["product_key"]: p.get("name_pt") or p.get("name_en") for p in store.products()}
    for pk, obs in by.items():
        sid = store.upsert_series(f"gpi:mentions:{pk}", dict(
            source="gpi", indicator="Menções em notícias e discussões", kind="derivado", product_key=pk,
            product_name=names.get(pk), category=None, country="Global (pt/en)", unit="menções/mês", currency=None,
            freq="M", origin_url=None, method="contagem mensal de itens de RSS, Google Notícias e Reddit associados ao produto",
            reliability="B"))
        store.upsert_obs(sid, obs)
    return len(by)


# v0.9 — Review Intelligence 2.0 -------------------------------------------------------------------------------
SOURCE_TYPES = {"avaliacao_comprador": "Avaliação de comprador", "relato_experiencia": "Relato de experiência",
                "discussao_publica": "Discussão pública", "noticia": "Notícia", "promocional": "Material promocional",
                "tecnica": "Informação técnica", "desconhecida": "Fonte desconhecida"}
OPINION_TYPES = ("avaliacao_comprador", "relato_experiencia")
_FIRST_PERSON = re.compile(r"\b(comprei|recebi|meu|minha|tenho|uso|usei|instalei|bought|my|i have|i use|i got|mine)\b")
_PROMO = re.compile(r"(#publi|\bpubli\b|patrocinad|cupom|codigo de desconto|sponsored|oferta imperdivel|link na bio|compre agora)")
_TECH = re.compile(r"\b(datasheet|especificacoes tecnicas|ficha tecnica|manual|specifications|spec sheet|norma|portaria)\b")
THEMES = {"aquecimento": "Aquecimento", "bateria": "Bateria", "durabilidade": "Durabilidade", "qualidade": "Acabamento",
          "defeito_eletrico": "Defeito elétrico", "assistencia_tecnica": "Assistência técnica", "montagem": "Compatibilidade/instalação",
          "garantia": "Garantia/troca"}
_EXTRA_THEMES = {"ruido": re.compile(r"\b(barulh\w*|ruido|noise|noisy|zumbido)\b"),
                 "seguranca": re.compile(r"\b(choque|pegou fogo|incendio|explodiu|fire|shock|smoke|fumaca)\b"),
                 "falha_funcionamento": re.compile(r"\b(parou de funcionar|nao liga|desliga sozinho|stopped working|won.?t turn on|travando)\b"),
                 "compatibilidade": re.compile(r"\b(incompativel|nao e compativel|nao reconhece|not compatible|doesn.?t work with)\b")}
_EXTRA_NAMES = {"ruido": "Ruído", "seguranca": "Segurança", "falha_funcionamento": "Falha de funcionamento", "compatibilidade": "Compatibilidade"}


def source_type(r: dict) -> str:
    """Tipo de documento. Notícias e material promocional nunca contam como opinião de consumidor."""
    t = " " + tx.strip_accents(f"{r.get('title') or ''} {r.get('text') or ''}").lower() + " "
    src = r.get("source") or ""
    if _PROMO.search(t):
        return "promocional"
    if src in ("rss", "google_news", "gdelt"):
        return "noticia"
    if _TECH.search(t):
        return "tecnica"
    if src in ("mercadolivre_reviews", "ml_reviews", "reviews"):
        return "avaliacao_comprador"
    if src == "reddit":
        return "relato_experiencia" if _FIRST_PERSON.search(t) else "discussao_publica"
    return "desconhecida"


def _wilson_lb(k: int, n: int, z: float = 1.96) -> float | None:
    if not n:
        return None
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def review_summary(store: MarketStore, content: ContentStore, min_n: int = 5) -> dict:
    rows = store.db.query(
        "SELECT source, item_id, kind, title, text, url, author, published_at, product_key, sentiment, sentiment_label,"
        " aspects, target FROM content_items WHERE sentiment IS NOT NULL AND product_key IS NOT NULL")
    names = {p["product_key"]: p.get("name_pt") or p.get("name_en") for p in store.products()}
    by = defaultdict(list)
    for r in rows:
        r["aspects"] = json.loads(r["aspects"]) if r["aspects"] else {}
        r["tipo_fonte"] = source_type(r)
        by[r["product_key"]].append(r)
    prods = []
    for pk, docs in by.items():
        tipos = Counter(r["tipo_fonte"] for r in docs)
        lst = [r for r in docs if r["tipo_fonte"] in OPINION_TYPES]      # só opiniões de consumidores
        n = len(lst)
        c = Counter(r["sentiment_label"] for r in lst)
        asp_neg, asp_pos = defaultdict(list), Counter()
        for r in lst:
            low = " " + tx.strip_accents(f"{r['title'] or ''} {r['text'] or ''}").lower() + " "
            found = {a for a, v in r["aspects"].items() if v <= -0.05 and a in THEMES}
            if r["sentiment_label"] == "negativo":
                found |= {k for k, rx in _EXTRA_THEMES.items() if rx.search(low)}
            for a in found:
                asp_neg[a].append(r)
            for a, v in r["aspects"].items():
                if v >= 0.05 and a in THEMES:
                    asp_pos[a] += 1
        problems = []
        for a, rs in sorted(asp_neg.items(), key=lambda kv: -len(kv[1])):
            fontes = {(x["source"], x["author"] or x["item_id"]) for x in rs}
            dates = sorted(x["published_at"] for x in rs if x["published_at"])
            rec = len(rs) >= 3 and len(fontes) >= 2
            problems.append({"aspecto": THEMES.get(a) or _EXTRA_NAMES[a], "codigo": a, "mencoes": len(rs),
                             "fontes_independentes": len(fontes), "periodo": [dates[0], dates[-1]] if dates else None,
                             "classificacao": "tema recorrente" if rec else "relato isolado",
                             "confianca": "moderada" if rec and len(fontes) >= 3 else "baixa",
                             "limitacao": "Frequência de reclamações publicadas — não é taxa de defeito."})
        pos, neg, neu = c["positivo"], c["negativo"], c["neutro"]
        polar = pos + neg
        suf = n >= min_n and polar >= 3
        neg_prod = sum(1 for r in lst if r["sentiment_label"] == "negativo" and r["target"] == "produto")

        def ex(lbl):
            seen, sel = set(), []
            for r in sorted([r for r in lst if r["sentiment_label"] == lbl],
                            key=lambda r: r["sentiment"] * (1 if lbl == "positivo" else -1), reverse=True):
                if _snip(r) not in seen:
                    seen.add(_snip(r))
                    sel.append(r)
                if len(sel) == 3:
                    break
            return [{"trecho": _snip(r), "fonte": r["source"], "tipo_fonte": SOURCE_TYPES[r["tipo_fonte"]], "autor": r["author"],
                     "url": r["url"], "data": r["published_at"], "aspectos": list(r["aspects"])} for r in sel]
        prods.append({
            "product_key": pk, "nome": names.get(pk, pk), "n": n, "documentos": len(docs),
            "por_tipo_fonte": {SOURCE_TYPES[k]: v for k, v in tipos.items()},
            "positivos": pos, "negativos": neg, "neutros": neu,
            "saldo": (pos - neg) / n if n else None,
            "proporcao_criticas": neg / n if n else None, "proporcao_neutras": neu / n if n else None,
            "criticas_lb95": _wilson_lb(neg, n), "elogios_lb95": _wilson_lb(pos, n),
            "suficiente": suf, "evidencia": "suficiente" if suf else "evidência insuficiente",
            "problemas": problems[:8],
            "elogios": [{"aspecto": THEMES[a], "codigo": a, "mencoes": k} for a, k in asp_pos.most_common(5)],
            "share_problemas_produto": neg_prod / n if n else None, "fontes": sorted({r["source"] for r in lst}),
            "exemplos_positivos": ex("positivo"), "exemplos_negativos": ex("negativo")})
    prods.sort(key=lambda p: -p["n"])
    ok = [p for p in prods if p["suficiente"]]
    agg = Counter()
    for p in ok:
        for pr in p["problemas"]:
            if pr["classificacao"] == "tema recorrente":
                agg[pr["aspecto"]] += pr["mencoes"]
    crit = sorted([p for p in ok if p["negativos"] >= 3 and p["negativos"] > p["positivos"] * 0.5], key=lambda p: -(p["criticas_lb95"] or 0))
    elog = sorted([p for p in ok if p["positivos"] >= 3], key=lambda p: -(p["elogios_lb95"] or 0))
    return {"produtos": prods, "total_opinioes": sum(p["n"] for p in prods),
            "mais_elogiados": [p["product_key"] for p in elog[:15]],
            "mais_criticados": [p["product_key"] for p in crit[:15]],
            "problemas_recorrentes": [{"aspecto": a, "mencoes": k} for a, k in agg.most_common(10)],
            "minimo_opinioes": min_n, "tipos_de_fonte": SOURCE_TYPES,
            "metodo": "Opiniões = avaliações de compradores e relatos de experiência (notícias, material promocional e discussões "
                      "gerais ficam fora). 'Mais criticados' ordena pelo limite inferior (95%, Wilson) da proporção de opiniões "
                      "negativas, exigindo ao menos 3 negativas — opiniões neutras não viram críticas. Tema recorrente: ≥ 3 "
                      "manifestações de ≥ 2 fontes independentes.",
            "aviso": "Contagens de opiniões publicadas — não representam taxa de defeito nem satisfação do total de compradores."}


def _snip(r, n=220):
    t = (r["text"] or r["title"] or "").strip()
    return t[:n] + ("…" if len(t) > n else "")


def youtube_summary(content: ContentStore) -> dict:
    """Somente somas e médias de dados do próprio YouTube (permitido pelas políticas)."""
    vids = content.items("youtube", limit=5000)
    by = defaultdict(list)
    for v in vids:
        by[v["product_key"] or "—"].append(v)
    out = []
    for pk, lst in by.items():
        views = [(v["metrics"] or {}).get("viewCount", 0) for v in lst]
        types = Counter(t for v in lst for t in ((v["metrics"] or {}).get("tipos") or []))
        top = sorted(lst, key=lambda v: -((v["metrics"] or {}).get("viewCount") or 0))[:5]
        out.append({"product_key": pk, "videos": len(lst), "visualizacoes_total": sum(views),
                    "visualizacoes_media": sum(views) / len(lst) if lst else 0,
                    "curtidas_total": sum((v["metrics"] or {}).get("likeCount", 0) for v in lst),
                    "comentarios_total": sum((v["metrics"] or {}).get("commentCount", 0) for v in lst),
                    "tipos": dict(types), "canais": len({v["author"] for v in lst}),
                    "top": [{"titulo": v["title"], "canal": v["author"], "url": v["url"], "data": v["published_at"],
                             "visualizacoes": (v["metrics"] or {}).get("viewCount"),
                             "curtidas": (v["metrics"] or {}).get("likeCount"),
                             "comentarios": (v["metrics"] or {}).get("commentCount"),
                             "tipos": (v["metrics"] or {}).get("tipos")} for v in top]})
    out.sort(key=lambda r: -r["visualizacoes_total"])
    return {"produtos": out, "total_videos": len(vids),
            "aviso": "Métricas públicas do YouTube (somas e médias). Exibidas separadamente, sem combinação com outras fontes."}


# --------------------------------------------------------------------------- atributos para o comparador
ATTR_PATTERNS = {
    "capacidade": r"\b(\d+(?:[.,]\d+)?)\s?(litros?|l|ml|mah|gb|tb)\b",
    "potencia": r"\b(\d{2,5})\s?(w|watts?)\b",
    "voltagem": r"\b(bivolt|(?:110|127|220|240)\s?v)\b",
    "dimensoes": r"\b(\d+(?:[.,]\d+)?\s?x\s?\d+(?:[.,]\d+)?(?:\s?x\s?\d+(?:[.,]\d+)?)?)\s?(cm|mm)\b",
    "garantia": r"\b(\d{1,2})\s?(meses|anos|months|years)\s(?:de\s)?(?:garantia|warranty)\b",
    "material": r"\b(a[cç]o inox|inox|alum[ií]nio|pl[aá]stico abs|abs|vidro temperado|silicone|stainless steel|aluminum)\b",
}


def extract_attributes(texts: list[dict]) -> dict:
    """texts: [{'texto', 'fonte', 'url'}]. Retorna, por atributo, os valores encontrados com a origem.
    Valores extraídos de texto livre têm confiabilidade C e podem se referir a modelos diferentes."""
    out = {}
    for attr, pat in ATTR_PATTERNS.items():
        cnt, src = Counter(), {}
        for t in texts:
            for m in re.finditer(pat, (t["texto"] or "").lower()):
                val = " ".join(g for g in m.groups() if g).replace("  ", " ").strip()
                val = re.sub(r"\s+", " ", val)
                cnt[val] += 1
                src.setdefault(val, {"fonte": t["fonte"], "url": t["url"]})
        if cnt:
            out[attr] = [{"valor": v, "mencoes": k, **src[v]} for v, k in cnt.most_common(3)]
    return out
