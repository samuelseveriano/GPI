"""Global Trade Intelligence — evolução histórica das importações por classificação (NCM/SH/HTS) e país de origem.

Fontes OFICIAIS e gratuitas (nenhuma é obrigatória; sem acesso → modo degradado com os dados locais):
* Brasil — Comex Stat (MDIC), API pública POST /general: NCM 8 dígitos ou SH4, mês, país de origem, US$ FOB, kg líquido e
  quantidade estatística.
* EUA — U.S. Census Bureau, International Trade API (timeseries/intltrade/imports/hs): HS 2–10 dígitos, mês, país,
  valor das importações gerais (US$) e quantidade; chave gratuita opcional.
* Internacional — UN Comtrade (conector existente, comparação China → outros países).

Regras: a estatística descreve a CLASSIFICAÇÃO inteira (todos os produtos do código), nunca o produto pesquisado nem uma
empresa; código candidato ≠ classificação fiscal; HS (6) ≠ NCM (8) ≠ HTS (10) — sem correspondência exata presumida;
Brasil e EUA nunca são somados; crescimento de importação ≠ crescimento de procura."""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from collections import defaultdict
from datetime import date, datetime

from ..connectors.http import SourceError

COMEX_URL = "https://api-comexstat.mdic.gov.br/general"
CENSUS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
USITC_URL = "https://dataweb.usitc.gov/"
CACHE_DAYS = 7
EXTRA_SH4 = {"waffle_maker": "8516", "sandwich_maker": "8516", "toaster": "8516", "oven": "8516", "mixer": "8509"}
SCOPE_WARN = ("Estatística oficial da CLASSIFICAÇÃO inteira: inclui todos os produtos desse código, não apenas o produto "
              "pesquisado. Não representa o volume do produto, de uma marca nem de uma empresa.")
REL = {"BR": "Comex Stat (MDIC)", "US": "U.S. Census Bureau — International Trade API"}


def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS trade_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
        reporter TEXT NOT NULL, flow TEXT NOT NULL, code TEXT NOT NULL, code_type TEXT NOT NULL, partner TEXT NOT NULL,
        partner_code TEXT, period TEXT NOT NULL, value_usd REAL, value_kind TEXT, kg REAL, qty REAL, qty_unit TEXT,
        description TEXT, fetched_at TEXT NOT NULL, UNIQUE(source, reporter, flow, code, partner, period))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_trade_code ON trade_stats(reporter, code, period)")
    db.execute("""CREATE TABLE IF NOT EXISTS trade_queries (key TEXT PRIMARY KEY, source TEXT, reporter TEXT, code TEXT,
        period_from TEXT, period_to TEXT, state TEXT, message TEXT, rows INTEGER, http INTEGER, queried_at TEXT)""")


def digits(code) -> str:
    return re.sub(r"\D", "", str(code or ""))


def code_type(code: str, reporter: str) -> str:
    n = len(digits(code))
    if reporter == "BR":
        return {4: "SH4", 6: "SH6", 8: "NCM"}.get(n, f"{n} dígitos")
    return {2: "HS2", 4: "HS4", 6: "HS6", 8: "HTS8", 10: "HTS10"}.get(n, f"{n} dígitos")


def months_back(today: date, n: int) -> tuple[str, str]:
    """Últimos n meses COMPLETOS (o mês corrente nunca entra)."""
    y, m = today.year, today.month - 1
    if m == 0:
        y, m = y - 1, 12
    end = f"{y:04d}-{m:02d}"
    t = y * 12 + (m - 1) - (n - 1)
    return f"{t // 12:04d}-{t % 12 + 1:02d}", end


def _num(v):
    if v in (None, "", "-", "(D)", "(X)"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------------- Comex Stat
def comex_body(code: str, start: str, end: str) -> dict:
    d = digits(code)
    filt = "ncm" if len(d) == 8 else "heading" if len(d) == 4 else "subHeading"
    return {"flow": "import", "monthDetail": True, "period": {"from": start, "to": end},
            "filters": [{"filter": filt, "values": [d]}], "details": ["country"],
            "metrics": ["metricFOB", "metricKG", "metricStatistic"]}


def parse_comex(payload, code: str) -> list[dict]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    rows = data.get("list") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise SourceError("Comex Stat: lista de dados não encontrada na resposta", "formato", cause="formato")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            raise SourceError("Comex Stat: linha em formato inesperado", "formato", cause="formato")
        y, m = r.get("year") or r.get("coAno"), r.get("monthNumber") or r.get("coMes") or r.get("month")
        name = r.get("country") or r.get("noPaispt") or r.get("countryName")
        pcode = r.get("countryCode") or r.get("coPais")
        fob = _num(r.get("metricFOB"))
        try:
            mm = int(str(m).split(".")[0][:2]) if str(m)[:2].isdigit() else None
        except ValueError:
            mm = None
        if not (y and mm and name and fob is not None):
            raise SourceError(f"Comex Stat: campos esperados ausentes (chaves recebidas: {sorted(r.keys())[:12]})", "formato",
                              cause="formato")
        out.append({"period": f"{int(y):04d}-{mm:02d}", "partner": str(name).strip(), "partner_code": str(pcode) if pcode else None,
                    "value_usd": fob, "value_kind": "FOB", "kg": _num(r.get("metricKG")), "qty": _num(r.get("metricStatistic")),
                    "qty_unit": r.get("statisticUnit") or r.get("unidadeEstatistica") or "unidade estatística da NCM"})
    return out


# ----------------------------------------------------------------------------------------------------- U.S. Census
def census_url(code: str, start: str, end: str, key: str | None = None) -> str:
    d = digits(code)
    q = {"get": "CTY_CODE,CTY_NAME,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1,I_COMMODITY_SDESC", "I_COMMODITY": d,
         "COMM_LVL": f"HS{len(d)}", "time": f"from {start} to {end}"}
    if key:
        q["key"] = key
    return CENSUS_URL + "?" + urllib.parse.urlencode(q)


def parse_census(payload) -> list[dict]:
    if payload in (None, "", []):
        return []                                     # a API responde 204/vazio quando não há linhas
    if not (isinstance(payload, list) and payload and isinstance(payload[0], list)):
        raise SourceError("Census: resposta não é uma tabela JSON", "formato", cause="formato")
    head = [str(h) for h in payload[0]]
    need = {"CTY_CODE", "CTY_NAME", "GEN_VAL_MO", "time"}
    if not need <= set(head):
        raise SourceError(f"Census: colunas ausentes ({sorted(need - set(head))})", "formato", cause="formato")
    out = []
    for row in payload[1:]:
        r = dict(zip(head, row))
        cc = str(r["CTY_CODE"] or "")
        if not (cc.isdigit() and int(cc) >= 1000):       # totais e agrupamentos (UE, OCDE...) ficam fora da partição
            continue
        out.append({"period": str(r["time"])[:7], "partner": str(r["CTY_NAME"]).title(), "partner_code": cc,
                    "value_usd": _num(r["GEN_VAL_MO"]), "value_kind": "valor das importações gerais (US$)", "kg": None,
                    "qty": _num(r.get("GEN_QY1_MO")), "qty_unit": r.get("UNIT_QY1") or None,
                    "description": r.get("I_COMMODITY_SDESC")})
    return out


# ----------------------------------------------------------------------------------------------------- coleta
def collect(db, http, creds, reporter: str, code: str, months: int, today: date, force: bool = False) -> dict:
    """Consulta a fonte oficial do mercado (cache de 7 dias por código/período) e grava em trade_stats."""
    ensure(db)
    start, end = months_back(today, months)
    src = "comexstat" if reporter == "BR" else "census"
    key = f"{src}:{reporter}:{digits(code)}:{start}:{end}"
    prev = db.query("SELECT * FROM trade_queries WHERE key = ?", (key,))
    if prev and not force and prev[0]["state"] == "com dados":
        age = (datetime.now() - datetime.fromisoformat(prev[0]["queried_at"])).days
        if age < CACHE_DAYS:
            return {**dict(prev[0]), "cache": True}
    st = {"key": key, "source": src, "reporter": reporter, "code": digits(code), "period_from": start, "period_to": end,
          "rows": 0, "http": None, "message": None}
    try:
        if reporter == "BR":
            rows = parse_comex(http.request_json(COMEX_URL, "POST", comex_body(code, start, end), min_interval=12.0, ttl=86400), code)
        else:
            k = ((creds or {}).get("census") or {}).get("api_key") if creds else None
            rows = parse_census(http.request_json(census_url(code, start, end, k), min_interval=1.0, ttl=86400))
        now = datetime.now().isoformat(timespec="seconds")
        with db.transaction():
            for r in rows:
                db.execute("INSERT INTO trade_stats (source, reporter, flow, code, code_type, partner, partner_code, period, value_usd, "
                           "value_kind, kg, qty, qty_unit, description, fetched_at) VALUES (?, ?, 'import', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                           "ON CONFLICT(source, reporter, flow, code, partner, period) DO UPDATE SET value_usd = excluded.value_usd, "
                           "kg = excluded.kg, qty = excluded.qty, qty_unit = excluded.qty_unit, fetched_at = excluded.fetched_at",
                           (src, reporter, digits(code), code_type(code, reporter), r["partner"], r.get("partner_code"), r["period"],
                            r["value_usd"], r["value_kind"], r.get("kg"), r.get("qty"), r.get("qty_unit"), r.get("description"), now))
        st.update(state="com dados" if rows else "sem resultados", rows=len(rows),
                  message=None if rows else "a fonte respondeu sem linhas para este código e período")
    except SourceError as e:
        from . import diagnostics as DG
        d = DG.classify(e)
        st.update(state=d["estado"], message=d["mensagem"], http=d.get("http"))
    except Exception as e:  # noqa: BLE001 — falha de rede não derruba a análise; o diagnóstico registra
        st.update(state="falha", message=f"{type(e).__name__}: {str(e)[:200]}")
    st["queried_at"] = datetime.now().isoformat(timespec="seconds")
    db.execute("INSERT INTO trade_queries (key, source, reporter, code, period_from, period_to, state, message, rows, http, queried_at) "
               "VALUES (:key, :source, :reporter, :code, :period_from, :period_to, :state, :message, :rows, :http, :queried_at) "
               "ON CONFLICT(key) DO UPDATE SET state = excluded.state, message = excluded.message, rows = excluded.rows, "
               "http = excluded.http, queried_at = excluded.queried_at", st)
    return st


# ----------------------------------------------------------------------------------------------------- análise
def _pct(a, b):
    return round(100 * (a / b - 1), 1) if a is not None and b not in (None, 0) else None


def analyze(rows: list[dict], start: str | None = None, end: str | None = None) -> dict:
    """Métricas determinísticas sobre linhas mensais (período × país) de UM mercado e UM código."""
    if not rows:
        return {"meses": 0, "mensal": [], "anual": [], "paises": [], "variacoes": {}, "anomalias": [], "previsao": {"elegivel": False,
                "motivo": "sem dados"}}
    by_m = defaultdict(lambda: {"valor": 0.0, "kg": 0.0, "qtd": 0.0, "kg_n": 0, "qtd_n": 0})
    by_c = defaultdict(lambda: defaultdict(float))
    for r in rows:
        b = by_m[r["period"]]
        b["valor"] += r["value_usd"] or 0
        if r.get("kg") is not None:
            b["kg"] += r["kg"]; b["kg_n"] += 1
        if r.get("qty") is not None:
            b["qtd"] += r["qty"]; b["qtd_n"] += 1
        by_c[r["partner"]][r["period"]] += r["value_usd"] or 0
    months = sorted(by_m)
    if start and end:                                   # meses sem registro dentro do período = zero (série completa)
        y, m = map(int, start.split("-"))
        full = []
        while f"{y:04d}-{m:02d}" <= end:
            full.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        months = full
    mensal = [{"mes": p, "valor_usd": round(by_m[p]["valor"], 2) if p in by_m else 0.0,
               "kg": round(by_m[p]["kg"], 1) if by_m.get(p, {}).get("kg_n") else None,
               "quantidade": round(by_m[p]["qtd"], 1) if by_m.get(p, {}).get("qtd_n") else None} for p in months]
    for x in mensal:
        x["usd_por_kg"] = round(x["valor_usd"] / x["kg"], 2) if x["kg"] else None
    acc = 0.0
    for x in mensal:
        acc += x["valor_usd"]
        x["acumulado_usd"] = round(acc, 2)
    years = defaultdict(lambda: {"valor": 0.0, "meses": 0, "kg": 0.0})
    for x in mensal:
        yb = years[x["mes"][:4]]
        yb["valor"] += x["valor_usd"]; yb["meses"] += 1; yb["kg"] += x["kg"] or 0
    anual, prev = [], None
    for y in sorted(years):
        v = years[y]
        row = {"ano": y, "valor_usd": round(v["valor"], 2), "kg": round(v["kg"], 1) or None, "meses": v["meses"],
               "completo": v["meses"] == 12, "variacao_pct": _pct(v["valor"], prev["valor"]) if prev and prev["completo"] and v["meses"] == 12 else None}
        anual.append(row)
        prev = {"valor": v["valor"], "completo": v["meses"] == 12}
    vals = [x["valor_usd"] for x in mensal]
    var = {}
    if len(vals) >= 24:
        l12, p12 = sum(vals[-12:]), sum(vals[-24:-12])
        var["ultimos_12m_usd"], var["12m_anteriores_usd"] = round(l12, 2), round(p12, 2)
        var["variacao_12m_pct"] = _pct(l12, p12)
        kg = [x["kg"] for x in mensal]
        if all(k is not None for k in kg[-24:]):
            var["variacao_12m_kg_pct"] = _pct(sum(kg[-12:]), sum(kg[-24:-12]))
    elif len(vals) >= 12:
        var["ultimos_12m_usd"] = round(sum(vals[-12:]), 2)
        var["nota"] = "menos de 24 meses: sem comparação 12m × 12m anteriores"
    comp = [a for a in anual if a["completo"]]
    if len(comp) >= 3 and comp[0]["valor_usd"] > 0 and comp[-1]["valor_usd"] > 0:
        n = int(comp[-1]["ano"]) - int(comp[0]["ano"])
        var["cagr_pct"] = round(100 * ((comp[-1]["valor_usd"] / comp[0]["valor_usd"]) ** (1 / n) - 1), 1)
        var["cagr_periodo"] = f"{comp[0]['ano']}–{comp[-1]['ano']} (anos completos)"
    else:
        var["cagr_pct"] = None
        var["cagr_nota"] = "CAGR só com ≥ 3 anos completos"
    last12 = set(months[-12:])
    prev12 = set(months[-24:-12]) if len(months) >= 24 else set()
    tot_l = sum(v for c in by_c.values() for p, v in c.items() if p in last12) or 0
    tot_p = sum(v for c in by_c.values() for p, v in c.items() if p in prev12) or 0
    paises = []
    for c, ser in by_c.items():
        l = sum(v for p, v in ser.items() if p in last12)
        pr = sum(v for p, v in ser.items() if p in prev12)
        paises.append({"pais": c, "valor_12m_usd": round(l, 2), "participacao_12m_pct": round(100 * l / tot_l, 1) if tot_l else None,
                       "participacao_anterior_pct": round(100 * pr / tot_p, 1) if tot_p else None,
                       "variacao_12m_pct": _pct(l, pr) if prev12 else None})
    paises.sort(key=lambda x: -x["valor_12m_usd"])
    for p in paises:
        if p["participacao_12m_pct"] is not None and p["participacao_anterior_pct"] is not None:
            p["mudanca_participacao_pp"] = round(p["participacao_12m_pct"] - p["participacao_anterior_pct"], 1)
    mudancas = [f"{p['pais']}: participação {p['participacao_anterior_pct']}% → {p['participacao_12m_pct']}%"
                for p in paises[:15] if abs(p.get("mudanca_participacao_pp") or 0) >= 5]
    anomalias = []
    logs = [math.log1p(v) for v in vals]
    if len(logs) >= 12:
        med = sorted(logs)[len(logs) // 2]
        mad = sorted(abs(x - med) for x in logs)[len(logs) // 2] or 1e-9
        for x, lv in zip(mensal, logs):
            z = 0.6745 * (lv - med) / mad
            if abs(z) > 3.5:
                anomalias.append({"mes": x["mes"], "valor_usd": x["valor_usd"], "z_robusto": round(z, 1),
                                  "tipo": "pico" if z > 0 else "queda"})
    nz = sum(1 for v in vals if v > 0)
    prev_ok = len(vals) >= 24 and nz >= 18
    return {"meses": len(mensal), "mensal": mensal, "anual": anual, "variacoes": var, "paises": paises[:25],
            "mudancas_relevantes": mudancas, "anomalias": anomalias,
            "previsao": {"elegivel": prev_ok, "motivo": "≥ 24 meses com ≥ 18 meses positivos — use o módulo Forecasting (backtesting)"
                         if prev_ok else "histórico insuficiente para previsão (precisa ≥ 24 meses, ≥ 18 com valor)"}}


def stored(db, reporter: str, code: str, start: str | None = None, end: str | None = None) -> list[dict]:
    ensure(db)
    q, a = "SELECT * FROM trade_stats WHERE reporter = ? AND code = ?", [reporter, digits(code)]
    if start:
        q += " AND period >= ?"; a.append(start)
    if end:
        q += " AND period <= ?"; a.append(end)
    return db.query(q, tuple(a))


def local_sh4(db, code: str) -> list[dict]:
    """Modo degradado: séries SH4 do Comex Stat já sincronizadas (todas as origens e China), sem detalhe por país."""
    out = []
    for scope, partner in (("total", "Todas as origens"), ("china", "China")):
        s = db.query("SELECT id FROM market_series WHERE series_key = ?", (f"comex:{scope}:{digits(code)[:4]}:fob",))
        if s:
            for o in db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date", (s[0]["id"],)):
                out.append({"period": o["ref_date"][:7], "partner": partner, "value_usd": o["value"], "kg": None, "qty": None})
    return out


# ----------------------------------------------------------------------------------------------------- produto → códigos
def candidate_codes(db, text: str, ncm_table=None) -> dict:
    from ..intel import understanding as U
    from ..products.catalog import NCM_HINT
    u = U.understand(text, "pt")
    pid = u.get("produto_id") or ""
    head = pid.split("+")[0].split(":")[0]
    cands = []
    h = NCM_HINT.get(head) or EXTRA_SH4.get(head)
    if h:
        cands.append({"codigo": h, "tipo": "SH4", "origem": "posição do Sistema Harmonizado do núcleo do produto (tabela do GPI)",
                      "abrangencia": "posição inteira (4 dígitos) — muito ampla", "confianca": "média"})
    try:
        for c in (ncm_table.candidates(text, limit=4) if ncm_table is not None else []):
            cod = digits(c.get("codigo"))
            if len(cod) == 8 and (not h or cod.startswith(h)):
                cands.append({"codigo": cod, "tipo": "NCM", "descricao": c.get("descricao"),
                              "origem": "tabela NCM oficial (sobreposição de palavras)", "abrangencia": "subitem NCM (8 dígitos)",
                              "confianca": "baixa — confirmar com despachante/Receita"})
    except Exception:  # noqa: BLE001
        pass
    from ..products import lexicon as LX
    from . import naming as NM
    return {"entendimento": {"produto_id": pid or None, "nome": NM._from_id(pid.split(":")[0]) if pid else text,
                             "categoria": (LX.CONCEPTS.get(head) or (None, None))[1] if head else None,
                             "estado": u.get("estado_rotulo") or u.get("estado"), "atributos": u.get("atributos")},
            "candidatos": cands,
            "aviso": "Códigos CANDIDATOS para investigação — não são classificação fiscal confirmada. HS (6) ≠ NCM (8) ≠ HTS (10)."}


def report(db, http, creds, text: str, market: str = "BR", months: int = 36, today: date | None = None, ncm_table=None,
           code: str | None = None) -> dict:
    """Cenário A: 'Comportamento das importações da categoria associada ao produto pesquisado'."""
    today = today or date.today()
    market = "US" if str(market).upper() in ("US", "EUA", "USA") else "BR"
    months = max(12, min(int(months or 36), 120))
    cc = candidate_codes(db, text, ncm_table) if text else {"entendimento": None, "candidatos": [], "aviso": None}
    codes = [code] if code else [c["codigo"] for c in cc["candidatos"]][:3]
    start, end = months_back(today, months)
    blocks = []
    for c in codes:
        q = collect(db, http, creds, market, c, months, today) if http is not None else {"state": "sem conexão", "message": "modo offline"}
        rows = stored(db, market, c, start, end)
        degraded = False
        if not rows and market == "BR" and len(digits(c)) >= 4:
            rows = local_sh4(db, c)
            rows = [r for r in rows if start <= r["period"] <= end]
            degraded = bool(rows)
        total_rows = [r for r in rows if r["partner"] != "China"] if degraded else rows
        an = analyze(total_rows, start, end)
        china = analyze([r for r in rows if r["partner"] in ("China", "China, People's Republic", "China (Mainland)")]
                        if not degraded else [r for r in rows if r["partner"] == "China"], start, end)
        blocks.append({"codigo": digits(c), "tipo_codigo": code_type(c, market), "mercado": market, "fonte": REL[market],
                       "consulta": {k: q.get(k) for k in ("state", "message", "rows", "http", "cache", "queried_at", "period_from", "period_to")},
                       "modo": "degradado: série SH4 local, sem detalhe por país" if degraded else "fonte oficial por país",
                       "periodo": {"de": start, "ate": end, "meses": months}, "analise": an,
                       "china": {"valor_12m_usd": china["variacoes"].get("ultimos_12m_usd"), "variacao_12m_pct": china["variacoes"].get("variacao_12m_pct")},
                       "abrangencia": SCOPE_WARN})
    with_data = [b for b in blocks if b["analise"]["meses"] and any(x["valor_usd"] for x in b["analise"]["mensal"])]
    concl = []
    for b in with_data:
        v = b["analise"]["variacoes"]
        if v.get("variacao_12m_pct") is not None:
            concl.append(f"{b['tipo_codigo']} {b['codigo']} ({b['mercado']}): importações da classificação "
                         f"{'+' if v['variacao_12m_pct'] >= 0 else ''}{v['variacao_12m_pct']}% nos últimos 12 meses vs. 12 anteriores "
                         f"(US$ {v['ultimos_12m_usd']:,.0f}).")
        if b["analise"]["paises"]:
            p = b["analise"]["paises"][0]
            concl.append(f"Principal origem em 12 meses: {p['pais']} ({p['participacao_12m_pct']}%).")
    lim = [SCOPE_WARN, "Aumento de importações da classificação não comprova aumento de procura pelo produto.",
           "Estatísticas agregadas não identificam importadores, fornecedores nem embarques individuais."]
    if not with_data:
        lim.insert(0, "Nenhuma estatística oficial disponível para os códigos candidatos (fonte indisponível, sem chave ou sem linhas).")
    if not codes:
        lim.insert(0, "Nenhum código candidato identificado: informe a NCM/HS manualmente.")
    return {"titulo": "Comportamento das importações da categoria associada ao produto pesquisado",
            "consulta": {"texto": text, "mercado": market, "meses": months, "codigo_informado": code},
            "produto": cc["entendimento"], "codigos_candidatos": cc["candidatos"], "aviso_codigos": cc["aviso"],
            "classificacoes": blocks, "conclusoes": concl or ["Sem dados suficientes para conclusões."], "limitacoes": lim,
            "tipo_evidencia": "Comércio exterior (estatística oficial agregada)"}


def category_growth(db, limit: int = 20, min_usd: float = 1e6) -> dict:
    """Posições SH4 com maior variação 12m × 12m anteriores (importações brasileiras, todas as origens) a partir das séries
    Comex Stat já sincronizadas. Ranking de CLASSIFICAÇÕES, não de produtos."""
    out = []
    for s in db.query("SELECT id, series_key, product_name, category FROM market_series WHERE source = 'comexstat' "
                      "AND series_key LIKE 'comex:total:%:fob'"):
        obs = db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date DESC LIMIT 24", (s["id"],))
        if len(obs) < 24:
            continue
        l12, p12 = sum(o["value"] for o in obs[:12]), sum(o["value"] for o in obs[12:])
        if l12 < min_usd or p12 <= 0:
            continue
        out.append({"codigo": s["series_key"].split(":")[2], "descricao": s["product_name"], "categoria": s["category"],
                    "ultimos_12m_usd": round(l12, 2), "variacao_12m_pct": _pct(l12, p12), "ate": obs[0]["ref_date"][:7]})
    out.sort(key=lambda x: -(x["variacao_12m_pct"] or -1e9))
    return {"itens": out[:limit], "fonte": "Comex Stat (MDIC) — séries SH4 sincronizadas, todas as origens, US$ FOB",
            "aviso": "Ranking de POSIÇÕES SH4 (classificações amplas) com ≥ US$ 1 mi em 12 meses. " + SCOPE_WARN,
            "vazio": None if out else "Sem séries Comex Stat sincronizadas com 24 meses (rode a sincronização)."}


def dashboard(db) -> dict:
    ensure(db)
    q = db.query("SELECT source, reporter, code, period_from, period_to, state, message, rows, queried_at FROM trade_queries "
                 "ORDER BY queried_at DESC LIMIT 20")
    return {"crescimento_categorias": category_growth(db, 12), "consultas_recentes": q,
            "fontes": [{"mercado": "BR", "fonte": REL["BR"], "url": COMEX_URL, "granularidade": "NCM 8 / SH4 × país × mês"},
                       {"mercado": "US", "fonte": REL["US"], "url": CENSUS_URL, "granularidade": "HS 2–10 × país × mês"},
                       {"mercado": "US", "fonte": "USITC DataWeb", "url": USITC_URL, "granularidade": "HTS × país",
                        "estado": "Consulta manual (conta gratuita; API com token não integrada nesta versão)"}]}
