"""
Conectores para fontes públicas, gratuitas e sem autenticação.

Cada parser valida a estrutura recebida; se a fonte mudar o formato, o conector
falha com uma mensagem clara (nunca grava dados parcialmente interpretados).
"""
from __future__ import annotations

import re
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta

from ..market import taxonomy as tx
from .base import Batch, Connector, FormatError, Job, Product, month_end, require, year_jobs
from .http import SourceError

MONTHS_PT = {m: i for i, m in enumerate(
    ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
     "setembro", "outubro", "novembro", "dezembro"], start=1)}


def _month_num(v) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})", s)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 12 else None
    s2 = tx.strip_accents(s).lower()
    for name, n in MONTHS_PT.items():
        if s2.startswith(name[:3]):
            return n
    return None


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)
    if re.fullmatch(r"-?[\d.]+,\d+", s):
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", ""))
    return None


# =========================================================================== BCB
class BcbPtax(Connector):
    id = "bcb_ptax"
    name = "Banco Central do Brasil — PTAX (câmbio)"
    reliability = "A"
    docs_url = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/documentacao"
    description = "Cotações PTAX de fechamento (venda) de USD, CNY e EUR em reais; média mensal derivada."
    limitations = "Somente dias úteis. A média mensal é calculada pelo GPI (série derivada)."
    order = 10
    CURRENCIES = {"USD": "Dólar americano", "CNY": "Yuan chinês (renminbi)", "EUR": "Euro"}
    BASE = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"

    def plan(self, ctx):
        jobs = []
        for cur in self.CURRENCIES:
            jobs += year_jobs(f"{self.id}:{cur}", ctx.cfg.get("history_start_year", 2016), ctx.today,
                              {"currency": cur}, revise_years=1)
        return jobs

    def url(self, cur, y, today):
        end = min(date(y, 12, 31), today)
        q = {"@moeda": f"'{cur}'", "@dataInicial": f"'01-01-{y}'",
             "@dataFinalCotacao": f"'{end:%m-%d-%Y}'", "$format": "json",
             "$select": "cotacaoVenda,dataHoraCotacao,tipoBoletim"}
        return (self.BASE + "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
                "dataFinalCotacao=@dataFinalCotacao)?" + urllib.parse.urlencode(q, safe="@'$,"))

    @staticmethod
    def parse(payload) -> list[tuple[str, float]]:
        require(isinstance(payload, dict) and isinstance(payload.get("value"), list),
                "PTAX: resposta sem a lista 'value'")
        by_day = {}
        for r in payload["value"]:
            require("cotacaoVenda" in r and "dataHoraCotacao" in r, "PTAX: campos cotacaoVenda/dataHoraCotacao ausentes")
            day = str(r["dataHoraCotacao"])[:10]
            tipo = str(r.get("tipoBoletim", "Fechamento"))
            if "Fechamento" in tipo or day not in by_day:
                by_day[day] = float(r["cotacaoVenda"])
        return sorted(by_day.items())

    def run(self, job, ctx):
        cur, y = job.params["currency"], job.params["year"]
        url = self.url(cur, y, ctx.today)
        daily = self.parse(ctx.http.request_json(url))
        if not daily:
            return [], []          # moeda sem cotação PTAX no período: nada a gravar (não é falha)
        meta = dict(source=self.id, indicator=f"PTAX venda — {self.CURRENCIES[cur]}", kind="observado",
                    product_key=None, product_name=None, category="Câmbio", country="Brasil",
                    unit=f"BRL por 1 {cur}", currency="BRL", freq="D", origin_url=url,
                    method="API OData oficial do BCB (Olinda)", reliability="A")
        batches = [Batch(f"bcb:ptax:{cur}:D", meta, daily)]
        months = defaultdict(list)
        for d, v in daily:
            months[d[:7]].append(v)
        today_m = ctx.today.strftime("%Y-%m")
        monthly = [(f"{m}-01", sum(v) / len(v)) for m, v in sorted(months.items()) if m < today_m]
        if monthly:
            mmeta = {**meta, "kind": "derivado", "freq": "M",
                     "indicator": f"PTAX venda média mensal — {self.CURRENCIES[cur]}",
                     "method": "Média aritmética das cotações diárias de fechamento (calculada pelo GPI)"}
            batches.append(Batch(f"bcb:ptax:{cur}:M", mmeta, monthly))
        return batches, []


# =========================================================================== Wikimedia
class WikimediaPageviews(Connector):
    id = "wikimedia"
    name = "Wikimedia — visualizações de páginas da Wikipédia"
    reliability = "B"
    docs_url = "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/"
    description = ("Interesse público por conceitos de produto: visualizações mensais (somente usuários, "
                   "sem robôs) nas Wikipédias em português, inglês e chinês. Alternativa aberta ao Google Trends.")
    limitations = ("Mede atenção/interesse, não vendas. Idioma ≠ país (pt inclui Portugal e outros). "
                   "Disponível a partir de 07/2015.")
    order = 20
    LANGS = {"pt": "Wikipédia em português", "en": "Wikipédia em inglês", "zh": "Wikipédia em chinês"}

    def plan(self, ctx):
        jobs = [Job(f"{self.id}:langlinks:{t}", {"title": t}, refresh_days=90, priority=0)
                for t in tx.CONCEPTS]
        resolved = {p["product_key"]: p for p in ctx.store.products() if p["origin"] == "wikipedia"}
        for t in tx.CONCEPTS:
            p = resolved.get(tx.concept_key(t))
            if not p:
                continue
            for lang, title in (("en", p["name_en"]), ("pt", p["name_pt"]), ("zh", p["name_zh"])):
                if title:
                    jobs.append(Job(f"{self.id}:pv:{lang}:{t}", {"concept": t, "lang": lang, "title": title},
                                    refresh_days=7, priority=2))
        return jobs

    @staticmethod
    def parse_langlinks(payload, concept):
        require(isinstance(payload, dict) and "query" in payload, "Wikipédia: resposta sem 'query'")
        pages = payload["query"].get("pages", [])
        if isinstance(pages, dict):          # formatversion=1
            pages = list(pages.values())
        require(pages, "Wikipédia: nenhuma página na resposta")
        pg = pages[0]
        if pg.get("missing") is not None and pg.get("missing") is not False:
            return None
        names = {"en": pg.get("title", concept)}
        for ll in pg.get("langlinks", []):
            lang = ll.get("lang")
            title = ll.get("title") or ll.get("*")
            if lang in ("pt", "zh") and title:
                names[lang] = title
        return names

    @staticmethod
    def parse_pageviews(payload):
        require(isinstance(payload, dict) and isinstance(payload.get("items"), list),
                "Wikimedia: resposta sem 'items'")
        out = []
        for it in payload["items"]:
            require("timestamp" in it and "views" in it, "Wikimedia: item sem timestamp/views")
            ts = str(it["timestamp"])
            out.append((f"{ts[:4]}-{ts[4:6]}-01", float(it["views"])))
        return out

    def run(self, job, ctx):
        if job.key.startswith(f"{self.id}:langlinks:"):
            t = job.params["title"]
            q = {"action": "query", "titles": t, "redirects": 1, "prop": "langlinks", "lllimit": 500,
                 "format": "json", "formatversion": 2}
            payload = ctx.http.request_json("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q),
                                            ttl=30 * 86400, min_interval=0.5)
            names = self.parse_langlinks(payload, t)
            if names is None:
                raise SourceError(f"artigo '{t}' não existe na Wikipédia em inglês", "http", status=404)
            cat, hs = tx.CONCEPTS[t]
            toks = " ".join(sorted(set(tx.normalize_tokens(names.get("pt", "")) + tx.normalize_tokens(names["en"]))))
            return [], [Product(tx.concept_key(t), dict(name_en=names["en"], name_pt=names.get("pt"),
                                                         name_zh=names.get("zh"), category=cat,
                                                         origin="wikipedia", hs_codes=",".join(hs),
                                                         norm_tokens=toks))]
        lang, title, concept = job.params["lang"], job.params["title"], job.params["concept"]
        last = (ctx.today.replace(day=1) - timedelta(days=1))
        art = urllib.parse.quote(title.replace(" ", "_"), safe="")
        url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/"
               f"all-access/user/{art}/monthly/2015070100/{last:%Y%m%d}00")
        obs = self.parse_pageviews(ctx.http.request_json(url, ttl=24 * 3600, min_interval=0.2))
        cat, _ = tx.CONCEPTS[concept]
        meta = dict(source=self.id, indicator="Visualizações de página (usuários)", kind="observado",
                    product_key=tx.concept_key(concept), product_name=title, category=cat,
                    country=self.LANGS[lang], unit="visualizações/mês", currency=None, freq="M",
                    origin_url=url, method="API REST pública de métricas da Wikimedia (agent=user)",
                    reliability="B")
        return [Batch(f"wiki:pv:{lang}:{tx.concept_key(concept)}", meta, obs)], []


# =========================================================================== Comex Stat
class ComexStat(Connector):
    id = "comexstat"
    name = "Comex Stat (MDIC) — importações brasileiras"
    reliability = "A"
    docs_url = "https://api-comexstat.mdic.gov.br/docs"
    description = ("Importações mensais do Brasil por posição SH4 (NCM): valor FOB (US$) e peso (kg), "
                   "da China e de todas as origens. Base da descoberta automática de produtos.")
    limitations = ("Estatística oficial com defasagem de ~1 mês; revisões ocorrem. A API pode responder "
                   "HTTP 429 (limite de requisições) — o GPI aguarda e tenta de novo.")
    order = 30
    URL = "https://api-comexstat.mdic.gov.br/general"
    CHINA = 160

    def plan(self, ctx):
        start = max(ctx.cfg.get("history_start_year", 2016), 1997)
        return (year_jobs(f"{self.id}:china", start, ctx.today, {"scope": "china"}) +
                year_jobs(f"{self.id}:total", start, ctx.today, {"scope": "total"}))

    def body(self, scope, y):
        b = {"flow": "import", "monthDetail": True, "period": {"from": f"{y}-01", "to": f"{y}-12"},
             "details": ["heading"], "metrics": ["metricFOB", "metricKG"]}
        if scope == "china":
            b["filters"] = [{"filter": "country", "values": [self.CHINA]}]
        return b

    @staticmethod
    def parse(payload, year):
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        rows = data.get("list") if isinstance(data, dict) else data
        require(isinstance(rows, list), "Comex Stat: lista de dados não encontrada na resposta")
        out = []
        for r in rows:
            require(isinstance(r, dict), "Comex Stat: linha em formato inesperado")
            y = r.get("year") or r.get("coAno") or year
            mth = _month_num(r.get("monthNumber") or r.get("month") or r.get("coMes"))
            code = r.get("headingCode") or r.get("coSh4") or r.get("sh4Code")
            desc = r.get("heading") or r.get("noSh4pt") or r.get("headingDescription")
            if code is None and desc:
                m = re.match(r"^\s*(\d{4})", str(desc))
                code = m.group(1) if m else None
            fob, kg = _num(r.get("metricFOB")), _num(r.get("metricKG"))
            require(mth and code and fob is not None,
                    f"Comex Stat: campos esperados ausentes (chaves recebidas: {sorted(r.keys())[:12]})")
            out.append({"date": f"{int(y):04d}-{mth:02d}-01", "code": str(code).zfill(4)[:4],
                        "desc": str(desc or code), "fob": fob, "kg": kg})
        return out

    def run(self, job, ctx):
        scope, y = job.params["scope"], job.params["year"]
        rows = self.parse(ctx.http.request_json(self.URL, "POST", self.body(scope, y), min_interval=12.0), y)
        by = defaultdict(lambda: {"desc": "", "fob": [], "kg": []})
        for r in rows:
            b = by[r["code"]]
            b["desc"] = r["desc"]
            b["fob"].append((r["date"], r["fob"]))
            if r["kg"] is not None:
                b["kg"].append((r["date"], r["kg"]))
        country = "China → Brasil" if scope == "china" else "Todas as origens → Brasil"
        batches, products = [], []
        for code, b in by.items():
            name = re.sub(r"^\s*\d{4}\s*[-–]\s*", "", b["desc"]).strip() or code
            base = dict(source=self.id, kind="observado", product_key=tx.heading_key(code), product_name=name,
                        category=tx.category_for_heading(code), country=country, freq="M",
                        origin_url=self.URL, reliability="A",
                        method="API oficial Comex Stat, POST /general (importação, detalhamento por SH4, mensal)")
            batches.append(Batch(f"comex:{scope}:{code}:fob", {**base, "indicator": "Importação — valor FOB",
                                                               "unit": "US$ FOB", "currency": "USD"}, b["fob"]))
            if b["kg"]:
                batches.append(Batch(f"comex:{scope}:{code}:kg", {**base, "indicator": "Importação — peso líquido",
                                                                  "unit": "kg", "currency": None}, b["kg"]))
            products.append(Product(tx.heading_key(code), dict(
                name_pt=name, category=tx.category_for_heading(code), origin="ncm", hs_codes=code,
                norm_tokens=" ".join(sorted(set(tx.normalize_tokens(name)))))))
        return batches, products


# =========================================================================== UN Comtrade
class UnComtrade(Connector):
    id = "comtrade"
    name = "UN Comtrade — importações de outros países vindas da China"
    reliability = "A"
    docs_url = "https://comtradedeveloper.un.org/"
    description = ("Comparação internacional: importações mensais de EUA, Alemanha e México provenientes "
                   "da China, nas posições SH4 com maior relevância para o Brasil (API pública 'preview').")
    limitations = ("A API pública sem chave limita o número de registros por chamada; dados mensais de "
                   "alguns países chegam com meses de atraso.")
    order = 60
    REPORTERS = {842: "Estados Unidos", 276: "Alemanha", 484: "México"}
    URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"

    def plan(self, ctx):
        heads = ctx.store.load_result("discovery_headings")
        if not heads:
            from ..market.intel import discover
            heads = discover(ctx.store)
        codes = [h["codigo"] for h in heads.get("prioritarias", [])][:20]
        if not codes:
            return []
        # A API pública 'preview' aceita só 1 período por chamada: um job por país e mês.
        jobs = []
        first = date(ctx.today.year - 2, ctx.today.month, 1)
        d = first
        while d < ctx.today.replace(day=1):
            recent = (ctx.today.year - d.year) * 12 + ctx.today.month - d.month <= 6
            for rep in self.REPORTERS:
                jobs.append(Job(f"{self.id}:{rep}:{d:%Y%m}:{len(codes)}", {"reporter": rep, "period": f"{d:%Y%m}",
                                                                          "codes": codes}, 7 if recent else None, priority=4))
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return jobs

    @staticmethod
    def parse(payload):
        require(isinstance(payload, dict), "Comtrade: resposta inesperada")
        if payload.get("error"):
            raise SourceError(f"Comtrade: {payload['error']}", "http")
        rows = payload.get("data")
        require(isinstance(rows, list), "Comtrade: campo 'data' ausente")
        out = []
        for r in rows:
            per, code, val = str(r.get("period", "")), r.get("cmdCode"), _num(r.get("primaryValue"))
            require(len(per) == 6 and code and val is not None, "Comtrade: período/cmdCode/primaryValue ausentes")
            out.append({"date": f"{per[:4]}-{per[4:]}-01", "code": str(code), "value": val,
                        "kg": _num(r.get("netWgt"))})
        return out

    def run(self, job, ctx):
        rep, per, codes = job.params["reporter"], job.params["period"], job.params["codes"]
        q = {"reporterCode": rep, "period": per, "partnerCode": 156, "cmdCode": ",".join(codes), "flowCode": "M"}
        url = self.URL + "?" + urllib.parse.urlencode(q)
        rows = self.parse(ctx.http.request_json(url, min_interval=3.0))
        by = defaultdict(list)
        for r in rows:
            by[r["code"]].append((r["date"], r["value"]))
        batches = []
        for code, obs in by.items():
            meta = dict(source=self.id, indicator="Importação da China — valor", kind="observado",
                        product_key=tx.heading_key(code), product_name=None, category=tx.category_for_heading(code),
                        country=f"China → {self.REPORTERS[rep]}", unit="US$", currency="USD", freq="M",
                        origin_url=self.URL, method="API pública UN Comtrade (preview, sem chave, 1 período por chamada)",
                        reliability="A")
            batches.append(Batch(f"comtrade:{rep}:{code}:value", meta, obs))
        return batches, []


# =========================================================================== IBGE
class IbgePmc(Connector):
    id = "ibge_pmc"
    name = "IBGE — Pesquisa Mensal de Comércio (volume de vendas do varejo)"
    reliability = "A"
    docs_url = "https://servicodados.ibge.gov.br/api/docs/agregados?versao=3"
    description = ("Índice de volume de vendas do varejo por atividade (ex.: móveis e eletrodomésticos, "
                   "material de construção). A tabela é localizada automaticamente pelos metadados do IBGE.")
    limitations = "Índice (base fixa), não unidades; nível Brasil. Atividades agregadas, não produtos."
    order = 40
    API = "https://servicodados.ibge.gov.br/api/v3/agregados"

    def plan(self, ctx):
        return [Job(f"{self.id}:pmc", {}, refresh_days=7, priority=2)]

    @staticmethod
    def pick_table(catalog):
        require(isinstance(catalog, list), "IBGE: catálogo de agregados inesperado")
        cands = []
        for pesq in catalog:
            if "comercio" not in tx.strip_accents(str(pesq.get("nome", ""))).lower() or \
               "mensal" not in tx.strip_accents(str(pesq.get("nome", ""))).lower():
                continue
            for ag in pesq.get("agregados", []):
                n = tx.strip_accents(str(ag.get("nome", ""))).lower()
                if "volume" in n and "atividade" in n and "varejista" in n:
                    cands.append((0 if "ampliado" not in n else 1, -int(ag["id"]), str(ag["id"]), ag.get("nome")))
        require(cands, "IBGE: tabela da PMC por atividades não localizada no catálogo")
        cands.sort()
        return cands[0][2], cands[0][3]

    @staticmethod
    def pick_query(meta):
        require(isinstance(meta, dict) and meta.get("variaveis"), "IBGE: metadados sem variáveis")
        var = None
        for v in meta["variaveis"]:
            n = tx.strip_accents(v.get("nome", "")).lower()
            if "indice" in n and "volume" in n and "variacao" not in n:
                var = v
                break
        var = var or meta["variaveis"][0]
        cls = []
        activity = None
        for c in meta.get("classificacoes", []):
            cats = c.get("categorias", [])
            names = " ".join(tx.strip_accents(x.get("nome", "")).lower() for x in cats)
            if "eletrodomestico" in names or "construcao" in names:
                activity = c
                cls.append(f"{c['id']}[all]")
            else:
                pick = next((x for x in cats if "base fixa" in tx.strip_accents(x.get("nome", "")).lower()
                             and "ajuste" not in tx.strip_accents(x.get("nome", "")).lower()), cats[0] if cats else None)
                if pick:
                    cls.append(f"{c['id']}[{pick['id']}]")
        require(activity is not None, "IBGE: classificação de atividades não encontrada")
        return var, cls

    @staticmethod
    def parse_values(payload):
        require(isinstance(payload, list) and payload, "IBGE: resposta de valores vazia")
        out = []
        for res in payload[0].get("resultados", []):
            label = None
            for c in res.get("classificacoes", []):
                cat = c.get("categoria", {})
                name = next(iter(cat.values()), "")
                if name and name.lower() not in ("total", "índice de base fixa (2022=100)"):
                    label = name if label is None else label
            for s in res.get("series", []):
                obs = []
                for per, v in (s.get("serie") or {}).items():
                    val = _num(v)
                    if val is not None and len(per) == 6:
                        obs.append((f"{per[:4]}-{per[4:]}-01", val))
                if obs:
                    out.append((label or "Total", sorted(obs)))
        require(out, "IBGE: nenhuma série numérica na resposta")
        return out

    def run(self, job, ctx):
        table, tname = self.pick_table(ctx.http.request_json(self.API, ttl=30 * 86400))
        meta = ctx.http.request_json(f"{self.API}/{table}/metadados", ttl=30 * 86400)
        var, cls = self.pick_query(meta)
        url = (f"{self.API}/{table}/periodos/-180/variaveis/{var['id']}?localidades=N1[all]"
               f"&classificacao={'|'.join(cls)}")
        series = self.parse_values(ctx.http.request_json(url))
        batches = []
        for label, obs in series:
            key = tx.normalize_name(label).replace(" ", "-")[:60]
            m = dict(source=self.id, indicator=f"{var.get('nome', 'Índice de volume')} — {label}", kind="observado",
                     product_key=None, product_name=label, category="Varejo (atividade)", country="Brasil",
                     unit=var.get("unidade", "índice"), currency=None, freq="M", origin_url=url,
                     method=f"API de agregados do IBGE v3, tabela {table} ({tname})", reliability="A")
            batches.append(Batch(f"ibge:pmc:{key}", m, obs))
        return batches, []
