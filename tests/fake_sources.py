"""
Respostas SINTÉTICAS no formato das APIs reais — usadas somente nos testes.
Nenhum destes números representa o mercado real.
"""
from __future__ import annotations

import math
import re
import urllib.parse
from datetime import date, timedelta

import numpy as np

from gpi.connectors.http import SourceError

HEADINGS = {  # código: (descrição, nível US$/mês, crescimento anual, sazonalidade)
    "8539": ("Lâmpadas e tubos elétricos de incandescência ou de descarga, incluindo LED", 3e7, 0.25, 0.1),
    "9405": ("Aparelhos de iluminação e suas partes", 4e7, 0.10, 0.2),
    "8536": ("Aparelhos para interrupção, seccionamento, proteção de circuitos elétricos", 5e7, 0.05, 0.0),
    "8544": ("Fios, cabos e outros condutores isolados para usos elétricos", 2e7, -0.20, 0.0),
    "8516": ("Aquecedores elétricos, fornos de micro-ondas, fritadeiras", 6e7, 0.40, 0.3),
    "8509": ("Aparelhos eletromecânicos de motor elétrico incorporado, de uso doméstico", 1.5e7, 0.02, 0.1),
    "8467": ("Ferramentas pneumáticas, hidráulicas ou com motor incorporado, de uso manual", 1e7, 0.15, 0.0),
    "8518": ("Microfones, alto-falantes, fones de ouvido", 2.5e7, 0.08, 0.4),
    "8507": ("Acumuladores elétricos", 8e7, 0.60, 0.0),
    "8504": ("Transformadores elétricos, conversores estáticos", 4.5e7, 0.12, 0.0),
    "9617": ("Garrafas térmicas e outros recipientes isotérmicos", 2e6, 0.05, 0.5),
    "3924": ("Serviços de mesa e outros artigos de uso doméstico, de plástico", 6e6, 0.0, 0.0),
    "8541": ("Dispositivos semicondutores; diodos emissores de luz (LED)", 9e7, 0.9, 0.0),
    "9503": ("Brinquedos", 3e7, 0.45, 0.6),
}


def _rng(key):
    return np.random.default_rng(abs(hash(key)) % (2 ** 32))


class FakeHttp:
    def __init__(self, today: date, fail_hosts=(), broken_format=()):
        self.today = today
        self.fail_hosts = set(fail_hosts)
        self.broken_format = set(broken_format)
        self.calls = []
        import threading
        self.cancel_event = threading.Event()
        self.stats = {}

    def request_text(self, url, headers=None, ttl=None, min_interval=None, max_bytes=5_000_000):
        self.calls.append(("GET", url, None))
        host = urllib.parse.urlsplit(url).netloc
        if host in self.fail_hosts:
            raise SourceError("falha de rede: simulada", "rede", True)
        if "news.google.com" in url:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
            return _rss([(f"{q}: vendas disparam e consumidores elogiam", "Ótimo produto, recomendo"),
                         (f"Recall de {q} por superaquecimento", "Produto esquenta e queimou a tomada")], self.today)
        name = host.split(".")[-3] if host.count(".") >= 2 else host
        return _rss([(f"Review: Air fryer da marca X com 4 litros e 1500W é excelente", "Fritadeira bivolt, 12 meses de garantia"),
                     (f"Power bank de 20000 mAh decepciona: bateria descarrega rápido", "Problema de bateria e esquenta"),
                     (f"{name}: novidades da semana", "Resumo")], self.today)

    def request_json(self, url, method="GET", body=None, headers=None, ttl=None, min_interval=None, form=None, **kw):
        self.calls.append((method, url, body or form))
        host = urllib.parse.urlsplit(url).netloc
        if host in self.fail_hosts:
            raise SourceError("falha de rede: simulada", "rede", True)
        if host in self.broken_format:
            return {"inesperado": True}
        if "googleapis.com/youtube" in url:
            return self._youtube(url)
        if "reddit.com" in url:
            return self._reddit(url, form)
        if "olinda.bcb" in url:
            return self._ptax(url)
        if "en.wikipedia.org" in url:
            return self._langlinks(url)
        if "wikimedia.org" in url:
            return self._pageviews(url)
        if "comexstat" in url:
            return self._comex(body)
        if "servicodados.ibge" in url:
            return self._ibge(url)
        if "comtradeapi" in url:
            return self._comtrade(url)
        raise SourceError("host desconhecido no teste", "rede")

    # ------------------------------------------------------------------
    def _ptax(self, url):
        cur = re.search(r"moeda=(?:%27|')(\w+)(?:%27|')", url).group(1)
        y = int(re.search(r"dataInicial=(?:%27|')01-01-(\d{4})", url).group(1))
        base = {"USD": 5.0, "CNY": 0.70, "EUR": 5.5}[cur]
        d, out = date(y, 1, 1), []
        while d <= min(date(y, 12, 31), self.today):
            if d.weekday() < 5:
                v = base * (1 + 0.03 * (d.year - 2016) + 0.01 * math.sin(d.toordinal() / 30))
                out.append({"cotacaoVenda": round(v, 4), "dataHoraCotacao": f"{d} 13:05:00.000",
                            "tipoBoletim": "Fechamento PTAX"})
            d += timedelta(days=1)
        return {"@odata.context": "x", "value": out}

    def _langlinks(self, url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        t = q["titles"][0]
        if t == "Laser level":
            return {"query": {"pages": [{"ns": 0, "title": t, "missing": True}]}}
        return {"query": {"pages": [{"pageid": 1, "ns": 0, "title": t, "langlinks": [
            {"lang": "pt", "title": f"{t} (pt)"}, {"lang": "zh", "title": f"{t}中文"},
            {"lang": "de", "title": f"{t} (de)"}]}]}}

    def _pageviews(self, url):
        parts = url.split("/")
        lang, art = parts[-6].split(".")[0], urllib.parse.unquote(parts[-3])
        end = parts[-1][:6]
        r = _rng(art + lang)
        g = {"Air fryer": 0.5, "Power bank": 0.3, "Flashlight": -0.2}.get(art.split(" (")[0].replace("_", " ").replace("中文", ""), r.normal(0.05, 0.1))
        items, d = [], date(2016, 1, 1)
        i = 0
        while d.strftime("%Y%m") <= end:
            v = 1000 * (1 + g) ** (i / 12) * (1 + 0.2 * math.sin(2 * math.pi * d.month / 12)) * r.lognormal(0, 0.08)
            items.append({"project": f"{lang}.wikipedia", "article": art, "granularity": "monthly",
                          "timestamp": d.strftime("%Y%m%d00"), "access": "all-access", "agent": "user",
                          "views": int(v)})
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            i += 1
        return {"items": items}

    def _comex(self, body):
        y = int(body["period"]["from"][:4])
        china = any(f["filter"] == "country" for f in body.get("filters", []))
        rows = []
        last_m = 12 if y < self.today.year else self.today.month - 1
        for code, (desc, lvl, g, s) in HEADINGS.items():
            r = _rng(code + str(china))
            for mth in range(1, last_m + 1):
                t = (y - 2016) + mth / 12
                v = lvl * (1 + g) ** t * (1 + s * math.sin(2 * math.pi * mth / 12)) * r.lognormal(0, 0.1)
                if not china:
                    v *= 1.6
                rows.append({"year": str(y), "monthNumber": f"{mth:02d}", "headingCode": code,
                             "heading": desc, "metricFOB": f"{v:.0f}", "metricKG": f"{v / 8:.0f}"})
        return {"data": {"list": rows}, "success": True, "message": None}

    def _ibge(self, url):
        if url.endswith("/agregados"):
            return [{"id": "XX", "nome": "Pesquisa Mensal de Comércio", "agregados": [
                {"id": "9999", "nome": "Índice de volume de vendas no comércio varejista, por atividades"}]}]
        if url.endswith("/metadados"):
            return {"id": 9999, "variaveis": [{"id": 1, "nome": "Índice de volume de vendas", "unidade": "Número-índice"}],
                    "classificacoes": [
                        {"id": 11046, "nome": "Tipos de índice", "categorias": [
                            {"id": 1, "nome": "Índice de base fixa (2022=100)"}]},
                        {"id": 85, "nome": "Atividades", "categorias": [
                            {"id": 2, "nome": "Móveis e eletrodomésticos"}, {"id": 3, "nome": "Material de construção"}]}]}
        res = []
        for cid, name in ((2, "Móveis e eletrodomésticos"), (3, "Material de construção")):
            serie, d = {}, date(2016, 1, 1)
            while d < self.today.replace(day=1):
                serie[d.strftime("%Y%m")] = f"{100 + (d.year - 2016) * 2 + cid:.1f}"
                d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            res.append({"classificacoes": [{"id": "11046", "categoria": {"1": "Índice de base fixa (2022=100)"}},
                                           {"id": "85", "categoria": {str(cid): name}}],
                        "series": [{"localidade": {"id": "1", "nome": "Brasil"}, "serie": serie}]})
        return [{"id": "1", "variavel": "Índice de volume de vendas", "unidade": "Número-índice", "resultados": res}]

    def _comtrade(self, url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        rows = []
        for per in q["period"][0].split(","):
            for code in q["cmdCode"][0].split(","):
                rows.append({"period": per, "cmdCode": code, "primaryValue": 1e6 * (1 + int(per[:4]) - 2019),
                             "netWgt": 1e5, "reporterCode": int(q["reporterCode"][0])})
        return {"elapsedTime": "0.1 secs", "count": len(rows), "data": rows, "error": ""}


def _rss(items, today):
    body = "".join(f"<item><title>{t}</title><link>https://exemplo.test/{abs(hash(t))}</link>"
                   f"<pubDate>{today.strftime('%a, %d %b %Y')} 10:00:00 GMT</pubDate><description>{d}</description></item>"
                   for t, d in items)
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>teste</title>{body}</channel></rss>"


def _yt_videos(ids):
    titles = ["Air fryer review: vale a pena?", "Unboxing air fryer 4L", "Air fryer vs forno: comparativo",
              "Power bank teste de bateria", "Melhores power banks 2026"]
    return {"items": [{"id": v, "snippet": {"title": titles[i % len(titles)], "channelTitle": f"Canal {i % 3}",
                                             "publishedAt": "2026-09-01T10:00:00Z", "description": "descrição curta",
                                             "categoryId": "28", "defaultAudioLanguage": "pt"},
                       "statistics": {"viewCount": str(1000 * (i + 1)), "likeCount": str(50 * (i + 1)),
                                      "commentCount": str(5 * (i + 1))}} for i, v in enumerate(ids)]}


def _yt(self, url):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    if "/search" in url:
        return {"items": [{"id": {"kind": "youtube#video", "videoId": f"v{abs(hash(q['q'][0])) % 1000}_{i}"}} for i in range(5)]}
    if "/videos" in url:
        return _yt_videos(q["id"][0].split(","))
    if "i18nRegions" in url:
        return {"items": [{"id": "BR"}]}
    return {"items": []}


def _rd(self, url, form):
    if "access_token" in url:
        return {"access_token": "tok", "expires_in": 3600}
    if "/search" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
        texts = ["Bought this last month, works great, highly recommend", "Stopped working after a month, battery died",
                 "It overheats a lot, terrible", "Great value for money", "Delivery was late but product is good",
                 "Excellent build quality, love it"]
        return {"data": {"children": [{"kind": "t3", "data": {"name": f"t3_{abs(hash(q + str(i))) % 99999}",
                "title": f"{q.strip(chr(34))} experience {i}", "selftext": t, "permalink": f"/r/test/{i}",
                "created_utc": 1788000000 + i, "subreddit": "BuyItForLife", "score": 10 + i, "num_comments": i}}
                for i, t in enumerate(texts)]}}
    if "/comments/" in url:
        return [{}, {"data": {"children": [{"kind": "t1", "data": {"name": f"t1_{abs(hash(url)) % 9999}",
                "body": "Mine broke after two weeks, defective", "permalink": "/r/test/c", "created_utc": 1788000000,
                "subreddit": "BuyItForLife", "score": 3}}]}}]
    return {}


FakeHttp._youtube = _yt
FakeHttp._reddit = _rd
