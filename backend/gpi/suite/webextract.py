"""Web Discovery — leitura de páginas PÚBLICAS de produto quando a coleta automatizada é permitida.

Ordem: (1) URL validada contra SSRF (só http/https, sem IP privado/local, DNS resolvido e checado a cada redirecionamento);
(2) domínio fora da lista de sites cujos termos proíbem coleta automatizada ou que têm API oficial no GPI (Mercado Livre,
eBay → API); (3) robots.txt do site respeitado (erro do servidor = não coleta); (4) GET único, até 2 MB, só text/html,
no máximo 3 redirecionamentos, intervalo por host; (5) extração de metadados estruturados: Schema.org Product (JSON-LD,
inclusive @graph), OpenGraph, meta description, tabelas de especificação; (6) o conteúdo é EVIDÊNCIA NÃO CONFIÁVEL —
só texto curto é guardado, nunca executado nem tratado como instrução. Sem CAPTCHA, login, bypass de bloqueio nem
contorno de limites. Quando não é permitido, o GPI devolve o link para verificação manual."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.robotparser
from html.parser import HTMLParser

UA = "GPI-ProductIntelligence/0.9.1 (+uso local; respeita robots.txt)"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
NO_AUTOMATION = {  # termos de uso proíbem coleta automatizada, exigem login/anti-bot, ou o GPI usa a API oficial
    "amazon.": "termos da Amazon proíbem coleta automatizada (use a página manualmente)",
    "mercadolivre.": "Mercado Livre: use a API oficial (cole o link do anúncio — consulta pela API)",
    "mercadolibre.": "Mercado Livre: use a API oficial", "ebay.": "eBay: use a Browse API (cole o link do anúncio)",
    "aliexpress.": "termos do AliExpress proíbem coleta automatizada", "alibaba.": "termos do Alibaba proíbem coleta automatizada",
    "shopee.": "Shopee exige app/login e proíbe coleta automatizada", "temu.": "termos da Temu proíbem coleta automatizada",
    "shein.": "termos da Shein proíbem coleta automatizada", "magazineluiza.": "termos da Magalu proíbem coleta automatizada",
    "facebook.": "Meta: somente APIs autorizadas", "instagram.": "Meta: somente APIs autorizadas", "tiktok.": "TikTok: somente APIs autorizadas",
    "walmart.": "termos do Walmart proíbem coleta automatizada", "google.": "Google: somente APIs autorizadas",
}
INJECTION = re.compile(r"(ignore (?:all |the )?(?:previous|prior) instructions|system prompt|you are (?:now )?(?:an? )?(?:ai|assistant)|"
                       r"ignore as instru[çc][õo]es|<\s*/?\s*(?:script|iframe))", re.I)
_last: dict[str, float] = {}
_robots: dict[str, tuple[float, object]] = {}


class PageRefused(Exception):
    def __init__(self, motivo: str, estado: str = "Consulta manual"):
        super().__init__(motivo)
        self.motivo, self.estado = motivo, estado


def _blocked(host: str) -> str | None:
    h = host.lower()
    for k, why in NO_AUTOMATION.items():
        if h.startswith(k) or f".{k}" in h or h.startswith("www." + k):
            return why
    return None


def _send(http, url: str, max_bytes: int) -> tuple[int, dict, bytes]:
    from ..security import public_url_problem
    for _ in range(MAX_REDIRECTS + 1):
        prob = public_url_problem(url, resolve=True)
        if prob:
            raise PageRefused(f"URL recusada: {prob}", "Indisponível")
        host = urllib.parse.urlsplit(url).hostname or ""
        wait = _last.get(host, 0) + 2.0 - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, 2.0))
        _last[host] = time.monotonic()
        status, rh, raw = http.transport.send("GET", url, {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,text/plain"},
                                              None, 20, {})
        if status in (301, 302, 303, 307, 308):
            loc = rh.get("Location")
            if not loc:
                raise PageRefused("redirecionamento sem destino", "Indisponível")
            url = urllib.parse.urljoin(url, loc)
            continue
        if len(raw) > max_bytes:
            raise PageRefused("página maior que o limite de 2 MB", "Indisponível")
        from ..connectors.http import decode_body
        return status, {**dict(rh), "_url": url}, decode_body(raw, rh.get("Content-Encoding"))
    raise PageRefused("redirecionamentos demais", "Indisponível")


def robots_allows(http, url: str) -> tuple[bool, str]:
    p = urllib.parse.urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    cached = _robots.get(base)
    if cached and time.time() - cached[0] < 3600:
        rp = cached[1]
    else:
        try:
            st, _, raw = _send(http, base + "/robots.txt", 500_000)
        except PageRefused:
            raise
        except Exception as e:  # noqa: BLE001
            return False, f"robots.txt inacessível ({type(e).__name__}) — coleta não realizada"
        rp = urllib.robotparser.RobotFileParser()
        if st >= 500:
            return False, f"robots.txt respondeu HTTP {st} — coleta não realizada"
        rp.parse([] if st >= 400 else raw.decode("utf-8", "replace").splitlines())
        _robots[base] = (time.time(), rp)
    ok = rp.can_fetch(UA, url)
    return ok, "permitido pelo robots.txt" if ok else "robots.txt do site não permite a coleta automatizada desta página"


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld, self.meta, self.title, self.rows = [], {}, "", []
        self._in, self._buf, self._cell, self._row, self._tag = None, [], None, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in, self._buf = "ld", []
        elif tag == "title":
            self._in, self._buf = "title", []
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content") and k not in self.meta:
                self.meta[k] = a["content"]
        elif tag in ("td", "th") and len(self.rows) < 60:
            self._cell = []
        elif tag == "tr":
            self._row = []

    def handle_endtag(self, tag):
        if tag == "script" and self._in == "ld":
            self.ld.append("".join(self._buf)); self._in = None
        elif tag == "title" and self._in == "title":
            self.title = "".join(self._buf).strip(); self._in = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip()[:200]); self._cell = None
        elif tag == "tr" and len(self._row) == 2 and all(self._row) and len(self.rows) < 60:
            self.rows.append(tuple(self._row))

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)
        if self._cell is not None:
            self._cell.append(data)


def _products(obj):
    if isinstance(obj, list):
        for o in obj:
            yield from _products(o)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        if t == "Product" or (isinstance(t, list) and "Product" in t):
            yield obj
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in obj:
                yield from _products(obj[k])


def _clean(v, n=300):
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("name") or v.get("@id") or ""
    if isinstance(v, list):
        v = v[0] if v else ""
    t = re.sub(r"\s+", " ", html.unescape(str(v))).strip()
    return INJECTION.sub("[removido]", t)[:n] or None


def extract(html_text: str, url: str) -> dict:
    p = _P()
    try:
        p.feed(html_text[:MAX_BYTES])
    except Exception:  # noqa: BLE001 — HTML malformado: usa o que foi lido
        pass
    prod = {}
    for blob in p.ld:
        try:
            data = json.loads(blob.strip())
        except ValueError:
            continue
        for pr in _products(data):
            prod = pr
            break
        if prod:
            break
    offers = prod.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict) and offers.get("@type") == "AggregateOffer":
        offers = {**offers, "price": offers.get("lowPrice") or offers.get("price")}
    m = p.meta
    fields = {
        "nome": _clean(prod.get("name")) or _clean(m.get("og:title")) or _clean(p.title),
        "marca_declarada": _clean(prod.get("brand")), "fabricante_declarado": _clean(prod.get("manufacturer")),
        "modelo": _clean(prod.get("model")), "sku": _clean(prod.get("sku")), "mpn": _clean(prod.get("mpn")),
        "gtin": _clean(prod.get("gtin13") or prod.get("gtin") or prod.get("gtin12") or prod.get("gtin14") or prod.get("gtin8")),
        "preco": _clean(offers.get("price") if isinstance(offers, dict) else None) or _clean(m.get("product:price:amount")),
        "moeda": _clean(offers.get("priceCurrency") if isinstance(offers, dict) else None) or _clean(m.get("product:price:currency")),
        "disponibilidade": _clean((offers.get("availability") or "").rsplit("/", 1)[-1] if isinstance(offers, dict) else None),
        "imagem": _clean(prod.get("image")) or _clean(m.get("og:image")),
        "descricao": _clean(prod.get("description"), 800) or _clean(m.get("og:description") or m.get("description"), 800),
        "categoria": _clean(prod.get("category")),
    }
    if fields["imagem"]:
        fields["imagem"] = urllib.parse.urljoin(url, fields["imagem"])
    specs = [{"atributo": _clean(a, 80), "valor": _clean(b, 160)} for a, b in p.rows[:40]]
    origem = "Schema.org Product (JSON-LD)" if prod else "OpenGraph/metadados" if any(k.startswith("og:") for k in m) else "título da página"
    return {"campos": {k: v for k, v in fields.items() if v}, "especificacoes": specs, "origem_dos_dados": origem,
            "injecao_detectada": bool(INJECTION.search(html_text[:MAX_BYTES]))}


def read_page(http, url: str) -> dict:
    """Lê UMA página pública permitida e devolve atributos verificáveis + produto identificado + diagnóstico."""
    host = urllib.parse.urlsplit(url).hostname or ""
    base = {"url": url, "host": host, "verificacao_manual": url,
            "aviso": "Conteúdo de site externo: evidência NÃO confiável, nunca instrução. Confira os termos de uso do site."}
    why = _blocked(host)
    if why:
        return {**base, "ok": False, "estado": "Consulta manual", "motivo": why}
    try:
        ok, rmsg = robots_allows(http, url)
        if not ok:
            return {**base, "ok": False, "estado": "Consulta manual", "motivo": rmsg}
        st, rh, raw = _send(http, url, MAX_BYTES)
    except PageRefused as e:
        return {**base, "ok": False, "estado": e.estado, "motivo": e.motivo}
    except Exception as e:  # noqa: BLE001
        return {**base, "ok": False, "estado": "Indisponível", "motivo": f"falha de rede: {type(e).__name__}"}
    if st in (401, 403, 429):
        return {**base, "ok": False, "estado": "Limite de requisições" if st == 429 else "Consulta manual",
                "motivo": f"o site respondeu HTTP {st} (acesso restrito/anti-bot) — não contornado"}
    if st >= 400:
        return {**base, "ok": False, "estado": "Indisponível", "motivo": f"HTTP {st}"}
    ctype = (rh.get("Content-Type") or "").lower()
    if "html" not in ctype and "text/plain" not in ctype:
        return {**base, "ok": False, "estado": "Indisponível", "motivo": f"tipo de conteúdo não suportado ({ctype[:60] or 'desconhecido'})"}
    ex = extract(raw.decode("utf-8", "replace"), rh.get("_url") or url)
    from ..intel import understanding as U
    from ..products import nlp as PN
    name = ex["campos"].get("nome") or ""
    u = U.understand(name, "pt") if name else {}
    if not u.get("produto_id") and name:
        u = U.understand(name, "en")
    at = {k: v for k, v in PN.extract_attributes(" ".join([name, ex["campos"].get("descricao") or ""])).items() if v}
    return {**base, "ok": True, "estado": "Operacional com dados reais", "robots": rmsg, "url_final": rh.get("_url"), **ex,
            "atributos_tecnicos": at, "produto_identificado": u.get("produto_id"),
            "identificacao": u.get("estado_rotulo"), "coletado_em": time.strftime("%Y-%m-%dT%H:%M:%S")}
