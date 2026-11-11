"""URLs coladas pelo usuário (v0.9.1 MVP): identifica o tipo (imagem direta · anúncio de marketplace · página de produto ·
não suportada · inválida), consulta a API OFICIAL do marketplace (eBay Browse `get_item_by_legacy_id`; Mercado Livre
`/items` e `/products`) com as credenciais do usuário e grava o anúncio pelo mesmo fluxo dos conectores (vendedor
pseudonimizado). Nada de raspagem de páginas: uma página sem API correspondente é recusada com a orientação."""
from __future__ import annotations

import base64
import re
import urllib.parse
from datetime import date, datetime

EBAY_ITEM = re.compile(r"ebay\.[a-z.]+/itm/(?:[^/?#]+/)?(\d{9,15})", re.I)
ML_ITEM = re.compile(r"\b(MLB)-?(\d{6,12})\b", re.I)
ML_PRODUCT = re.compile(r"mercadoli[bv]re\.com\.br/(?:[^?#]*/)?p/(MLB\d{6,12})", re.I)
IMG_EXT = re.compile(r"\.(jpe?g|png|webp)(?:$|\?)", re.I)


def detect(url: str) -> dict:
    u = (url or "").strip()
    if not re.match(r"^https?://", u, re.I):
        if re.fullmatch(r"\d{9,15}", u):
            return {"tipo": "anúncio de marketplace", "provedor": "ebay", "id": u}
        m = ML_ITEM.fullmatch(u.replace(" ", ""))
        if m:
            return {"tipo": "anúncio de marketplace", "provedor": "mercadolivre", "id": (m.group(1) + m.group(2)).upper()}
        return {"tipo": "URL inválida", "motivo": "informe uma URL começando com http(s):// ou um identificador de anúncio"}
    from ..security import public_url_problem
    prob = public_url_problem(u, resolve=False)
    if prob:
        return {"tipo": "URL inválida", "motivo": prob}
    m = EBAY_ITEM.search(u)
    if m:
        return {"tipo": "anúncio de marketplace", "provedor": "ebay", "id": m.group(1)}
    m = ML_PRODUCT.search(u)
    if m:
        return {"tipo": "anúncio de marketplace", "provedor": "mercadolivre_produto", "id": m.group(1).upper()}
    if "mercadoli" in u.lower():
        m = ML_ITEM.search(u)
        if m:
            return {"tipo": "anúncio de marketplace", "provedor": "mercadolivre", "id": (m.group(1) + m.group(2)).upper()}
    if IMG_EXT.search(urllib.parse.urlsplit(u).path + ("?" if "?" in u else "")):
        return {"tipo": "URL direta de imagem", "url": u}
    host = urllib.parse.urlsplit(u).hostname or ""
    return {"tipo": "página de produto", "url": u, "host": host,
            "motivo": "Página sem API oficial integrada ao GPI: o GPI só lê metadados públicos (Schema.org/OpenGraph) quando os termos "
                      "e o robots.txt do site permitem. Se não for permitido, cole a URL DIRETA da imagem (botão direito na foto → "
                      "copiar endereço da imagem) ou o link de um anúncio do eBay/Mercado Livre."}


def _persist(db, creds, source, it: dict, pid, query):
    from ..integrations.ebay_compliance import seller_pseudonym
    day, ts = date.today().isoformat(), datetime.now().isoformat(timespec="seconds")
    db.execute("INSERT OR REPLACE INTO market_listings (source, item_id, day, product_id, query, title, brand, model, category, price, currency, "
               "original_price, country, seller, condition, url, extra, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
               (source, it["id"], day, pid, query, (it.get("titulo") or "")[:300], it.get("marca"), it.get("modelo"), it.get("categoria"),
                it.get("preco"), it.get("moeda"), None, it.get("pais"), seller_pseudonym(creds, it.get("vendedor")) if it.get("vendedor") else None,
                it.get("condicao"), it.get("url"), ts))


def fetch_listing(db, sync, url_or_id: str, persist: bool = True) -> dict:
    """Consulta o anúncio pela API oficial. Devolve {'ok', 'anuncio', 'imagem', ...} ou o motivo concreto."""
    from ..connectors.http import SourceError
    from ..intel import understanding as U
    from . import diagnostics as DG
    d = detect(url_or_id)
    if d["tipo"] != "anúncio de marketplace":
        return {"ok": False, **d}
    prov = d["provedor"]
    try:
        if prov == "ebay":
            c = sync.creds.get("ebay") or {}
            if not (c.get("client_id") and c.get("client_secret")):
                return {"ok": False, **d, "estado": "Não configurada", "motivo": "eBay sem Client ID/Secret", "central": "#integracoes/ebay"}
            from ..connectors.sources5 import ebay_token
            tok = ebay_token(sync.http, sync.creds)
            r = sync.http.request_json("https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?" + urllib.parse.urlencode({"legacy_item_id": d["id"]}),
                                       headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}, ttl=0)
            it = {"id": r.get("itemId") or d["id"], "titulo": r.get("title"), "preco": float((r.get("price") or {}).get("value") or 0) or None,
                  "moeda": (r.get("price") or {}).get("currency"), "marca": r.get("brand"), "modelo": r.get("mpn"), "condicao": r.get("condition"),
                  "categoria": (r.get("categoryPath") or "").split("|")[-1] or None, "url": r.get("itemWebUrl"),
                  "pais": (r.get("itemLocation") or {}).get("country"), "vendedor": (r.get("seller") or {}).get("username"),
                  "imagem": (r.get("image") or {}).get("imageUrl"), "marketplace": "eBay EUA",
                  "caracteristicas": {a.get("name"): ", ".join(a.get("values") or []) for a in r.get("localizedAspects") or [] if a.get("name")}}
            source = "ebay"
            can_store = bool(c.get("sync_token"))      # guarda só com o fluxo de exclusão de contas configurado (conformidade eBay)
        else:
            from ..integrations.registry import ml_token
            tok = ml_token(sync.http, sync.creds)
            h = {"Authorization": f"Bearer {tok}"}
            if prov == "mercadolivre_produto":
                r = sync.http.request_json(f"https://api.mercadolibre.com/products/{d['id']}", headers=h, ttl=0)
                bw = r.get("buy_box_winner") or {}
                it = {"id": bw.get("item_id") or d["id"], "titulo": r.get("name"), "preco": bw.get("price"), "moeda": bw.get("currency_id"),
                      "marca": next((a.get("value_name") for a in r.get("attributes") or [] if a.get("id") == "BRAND"), None),
                      "modelo": next((a.get("value_name") for a in r.get("attributes") or [] if a.get("id") == "MODEL"), None),
                      "url": r.get("permalink"), "pais": "BR", "imagem": ((r.get("pictures") or [{}])[0]).get("url"), "marketplace": "Mercado Livre (catálogo)",
                      "caracteristicas": {a.get("name"): a.get("value_name") for a in r.get("attributes") or [] if a.get("value_name")}}
            else:
                r = sync.http.request_json(f"https://api.mercadolibre.com/items/{d['id']}", headers=h, ttl=0)
                it = {"id": r.get("id") or d["id"], "titulo": r.get("title"), "preco": r.get("price"), "moeda": r.get("currency_id"),
                      "marca": next((a.get("value_name") for a in r.get("attributes") or [] if a.get("id") == "BRAND"), None),
                      "modelo": next((a.get("value_name") for a in r.get("attributes") or [] if a.get("id") == "MODEL"), None),
                      "condicao": r.get("condition"), "categoria": r.get("category_id"), "url": r.get("permalink"), "pais": "BR",
                      "vendedor": str(r.get("seller_id")) if r.get("seller_id") else None, "imagem": ((r.get("pictures") or [{}])[0]).get("secure_url"),
                      "marketplace": "Mercado Livre Brasil",
                      "caracteristicas": {a.get("name"): a.get("value_name") for a in r.get("attributes") or [] if a.get("value_name")}}
            source, can_store = "mercadolivre", True
    except SourceError as e:
        c = DG.classify(e)
        return {"ok": False, **d, "estado": c["estado"], "motivo": c["mensagem"], "acao": c["acao"],
                "alternativa": "Use a pesquisa por palavra-chave (Pesquisa de Produtos) ou importe dados autorizados.",
                "central": "#integracoes/" + ("ebay" if prov == "ebay" else "mercadolivre")}
    if not it.get("titulo"):
        return {"ok": False, **d, "estado": "Indisponível", "motivo": "a API não devolveu o anúncio"}
    u = U.understand(it["titulo"], None)
    pid = u.get("produto_id") if u.get("estado") == "confirmada" else None
    stored = False
    if persist and can_store:
        _persist(db, sync.creds, source, it, pid, f"url:{d['id']}")
        stored = True
    return {"ok": True, **d, "anuncio": {k: v for k, v in it.items() if k != "vendedor"}, "produto_identificado": pid,
            "identificacao": {"estado": u.get("estado"), "principal": u.get("principal"), "atributos": {k: v for k, v in (u.get("atributos") or {}).items() if v}},
            "gravado": stored, "nota_gravacao": None if stored else "não gravado (eBay exige o fluxo de exclusão de contas configurado para guardar anúncios)",
            "avisos": ["Dados da API oficial do marketplace. Preço anunciado ≠ preço de venda; vendas não são informadas."]}


def ebay_search_by_image(sync, raw: bytes, limit: int = 20) -> dict:
    """Browse API `search_by_image` (operação oficial do eBay). Só é chamada quando o usuário marca explicitamente o envio
    da imagem ao eBay."""
    from ..connectors.http import SourceError
    from ..connectors.sources5 import ebay_token
    from . import diagnostics as DG
    c = sync.creds.get("ebay") or {}
    if not (c.get("client_id") and c.get("client_secret")):
        return {"ok": False, "estado": "Não configurada", "motivo": "eBay sem Client ID/Secret", "central": "#integracoes/ebay"}
    try:
        tok = ebay_token(sync.http, sync.creds)
        r = sync.http.request_json(f"https://api.ebay.com/buy/browse/v1/item_summary/search_by_image?limit={max(1, min(50, limit))}", "POST",
                                   body={"image": base64.b64encode(raw).decode()},
                                   headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}, ttl=0)
    except SourceError as e:
        c = DG.classify(e)
        return {"ok": False, "estado": c["estado"], "motivo": c["mensagem"], "acao": c["acao"]}
    items = [{"titulo": it.get("title"), "preco": (it.get("price") or {}).get("value"), "moeda": (it.get("price") or {}).get("currency"),
              "url": it.get("itemWebUrl"), "imagem": (it.get("image") or {}).get("imageUrl"), "id": it.get("itemId"), "fonte": "eBay search_by_image"}
             for it in (r or {}).get("itemSummaries") or []]
    return {"ok": True, "itens": items, "aviso": "Resultados visuais do eBay: semelhança de imagem não comprova o mesmo fabricante."}
