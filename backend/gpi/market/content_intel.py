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
import re
from collections import Counter, defaultdict

from ..connectors.content import ProductMatcher
from ..nlp import reviews as nlp
from .content_store import ContentStore
from .store import MarketStore

NLP_SOURCES = ("reddit", "rss", "google_news")


def process(store: MarketStore, content: ContentStore) -> dict:
    db = store.db
    matcher = ProductMatcher(store.products())
    rows = db.query("SELECT source, item_id, title, text, product_key, sentiment FROM content_items")
    matched = analysed = 0
    with db.lock:
        for r in rows:
            sets, vals = [], []
            if not r["product_key"]:
                pk = matcher.match(f"{r['title'] or ''} {r['text'] or ''}")
                if pk:
                    sets.append("product_key = ?"); vals.append(pk); matched += 1
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


def review_summary(store: MarketStore, content: ContentStore, min_n: int = 5) -> dict:
    rows = store.db.query(
        "SELECT source, item_id, kind, title, text, url, author, published_at, product_key, sentiment, sentiment_label,"
        " aspects, target FROM content_items WHERE sentiment IS NOT NULL AND product_key IS NOT NULL")
    names = {p["product_key"]: p.get("name_pt") or p.get("name_en") for p in store.products()}
    by = defaultdict(list)
    for r in rows:
        r["aspects"] = json.loads(r["aspects"]) if r["aspects"] else {}
        by[r["product_key"]].append(r)
    prods = []
    for pk, lst in by.items():
        c = Counter(r["sentiment_label"] for r in lst)
        n = len(lst)
        asp_neg, asp_pos = Counter(), Counter()
        targets = Counter()
        for r in lst:
            for a, v in r["aspects"].items():
                if v <= -0.05:
                    asp_neg[a] += 1
                elif v >= 0.05:
                    asp_pos[a] += 1
            if r["sentiment_label"] == "negativo" and r["target"]:
                targets[r["target"]] += 1
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
            return [{"trecho": _snip(r), "fonte": r["source"], "autor": r["author"], "url": r["url"],
                     "data": r["published_at"], "aspectos": list(r["aspects"])} for r in sel]
        prods.append({
            "product_key": pk, "nome": names.get(pk, pk), "n": n, "positivos": c["positivo"], "negativos": c["negativo"],
            "neutros": c["neutro"], "saldo": (c["positivo"] - c["negativo"]) / n if n else None,
            "suficiente": n >= min_n, "problemas": [{"aspecto": nlp.ASPECT_NAMES[a], "codigo": a, "mencoes": k}
                                                    for a, k in asp_neg.most_common(6)],
            "elogios": [{"aspecto": nlp.ASPECT_NAMES[a], "codigo": a, "mencoes": k} for a, k in asp_pos.most_common(5)],
            "alvo_reclamacoes": dict(targets), "share_problemas_produto": neg_prod / n if n else None,
            "fontes": sorted({r["source"] for r in lst}), "exemplos_positivos": ex("positivo"),
            "exemplos_negativos": ex("negativo")})
    prods.sort(key=lambda p: -p["n"])
    ok = [p for p in prods if p["suficiente"]]
    agg = Counter()
    for p in ok:
        for pr in p["problemas"]:
            agg[pr["aspecto"]] += pr["mencoes"]
    return {"produtos": prods, "total_opinioes": sum(p["n"] for p in prods),
            "mais_elogiados": [p["product_key"] for p in sorted(ok, key=lambda p: -(p["saldo"] or 0))[:15]],
            "mais_criticados": [p["product_key"] for p in sorted(ok, key=lambda p: (p["saldo"] or 0))[:15]],
            "problemas_recorrentes": [{"aspecto": a, "mencoes": k} for a, k in agg.most_common(10)],
            "minimo_opinioes": min_n,
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
