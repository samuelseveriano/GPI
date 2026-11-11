"""Import Intelligence — NCM candidata, estatísticas agregadas da classificação (Comex Stat), requisitos regulatórios
(reutiliza o módulo Anatel/Inmetro), riscos, qualidade e simulador PRELIMINAR de custos com cenários.

Regras: NCM é apenas candidata (correspondência HS↔NCM também); estatísticas da NCM descrevem a CLASSIFICAÇÃO inteira,
não o produto pesquisado; nenhuma conformidade é presumida por semelhança; o simulador usa SOMENTE parâmetros
informados pelo usuário — tributos, frete e taxas não são inventados e campos ausentes ficam pendentes."""
from __future__ import annotations

import json

from . import store as S

DECISION = {
    "VERDE": "Investigação recomendada — evidência comercial persistente ou crescimento confirmado, com identificação confirmada.",
    "AMARELO": "Sinal preliminar — há evidência, mas sem persistência ou crescimento confirmado.",
    "VERMELHO": "Não priorizar — evidência existente é desfavorável (ex.: declínio confirmado ou margem negativa nos SEUS parâmetros).",
    "CINZA": "Dados insuficientes — ausência de dados não é evidência negativa.",
}
NEGATIVE = {"DECLÍNIO"}


def classify_decision(p: dict | None, stage: dict | None, sim: dict | None = None) -> dict:
    """Cor da decisão. Falta de dado → CINZA (nunca VERMELHO). Score não é probabilidade."""
    why = []
    if not p or not stage:
        return {"cor": "CINZA", "significado": DECISION["CINZA"], "motivos": ["produto sem evidências coletadas no GPI"]}
    st = stage["estagio"]
    if p.get("situacao") in NEGATIVE and (p.get("confirmacao_cruzada") or {}).get("confirmado"):
        why.append("declínio confirmado por fontes independentes")
    base = (sim or {}).get("cenarios", {}).get("Base", {})
    if base.get("margem_bruta_pct") is not None and base["margem_bruta_pct"] < 0 and not base.get("incompleto"):
        why.append(f"margem bruta negativa no cenário Base com os parâmetros informados ({base['margem_bruta_pct']:.1f}%)")
    if why:
        return {"cor": "VERMELHO", "significado": DECISION["VERMELHO"], "motivos": why}
    if st >= 3:
        return {"cor": "VERDE", "significado": DECISION["VERDE"], "motivos": [stage["regra"]]}
    if st in (1, 2):
        return {"cor": "AMARELO", "significado": DECISION["AMARELO"], "motivos": [stage["regra"], *stage.get("faltando", [])[:3]]}
    return {"cor": "CINZA", "significado": DECISION["CINZA"], "motivos": ["somente identificação / atenção pública", *stage.get("faltando", [])[:3]]}


def indicators(p: dict | None, today_iso: str) -> dict:
    idx = (p or {}).get("indices") or {}
    last = None
    for e in (p or {}).get("evidencias") or []:
        per = (e.get("periodo") or "").split(" a ")[-1]
        if per and per != "—" and (last is None or per > last):
            last = per
    return {"opportunity_score": {"valor": idx.get("opportunity_score"), "nota": "prioridade relativa de investigação — não é probabilidade"},
            "evidence_coverage": {"valor": idx.get("evidence_coverage"), "nota": "quantidade, diversidade e histórico das evidências elegíveis"},
            "confidence_level": {"valor": "alta" if (idx.get("evidence_coverage") or 0) >= 60 else "média" if (idx.get("evidence_coverage") or 0) >= 30
                                 else "baixa" if idx.get("evidence_coverage") else "não avaliada"},
            "data_freshness": {"valor": last, "nota": "período mais recente entre as evidências", "referencia": today_iso}}


# ------------------------------------------------------------------------------------------------- NCM e comércio exterior
def ncm_block(db, ncm_table, text: str, hint: str | None = None) -> dict:
    cands = []
    try:
        cands = ncm_table.candidates(text, limit=6) if ncm_table is not None else []
    except Exception:  # noqa: BLE001
        cands = []
    stats = []
    codes = [c["codigo"].replace(".", "") for c in cands[:3]] + ([hint] if hint else [])
    seen = set()
    for code in codes:
        for pref in (code[:8], code[:6], code[:4]):
            if not pref or pref in seen:
                continue
            seen.add(pref)
            rows = db.query("SELECT s.id, s.series_key, s.indicator, s.country, s.unit, s.currency, s.freq, "
                            "(SELECT COUNT(*) FROM market_obs o WHERE o.series_id = s.id) AS n, "
                            "(SELECT MAX(ref_date) FROM market_obs o WHERE o.series_id = s.id) AS fim "
                            "FROM market_series s WHERE s.source = 'comexstat' AND (s.product_key = ? OR s.series_key LIKE ?) LIMIT 6",
                            (pref, f"%:{pref}:%"))
            for r in rows:
                obs = db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date DESC LIMIT 12", (r["id"],))
                r["ultimos_12"] = sum(o["value"] for o in obs) if obs else None
                r["nivel"] = len(pref)
                stats.append(r)
            if rows:
                break
    return {"candidatas": cands, "ncm_do_catalogo": hint, "estatisticas_agregadas": stats,
            "avisos": ["NCM candidata para investigação — não é classificação fiscal (confirme com despachante/Receita).",
                       "Estatísticas do Comex Stat descrevem TODA a classificação (todos os produtos da NCM), não o produto pesquisado.",
                       "Correspondência HS (internacional) ↔ NCM (Mercosul) é apenas candidata nos 6 primeiros dígitos.",
                       "Comex Stat é agregado: não identifica importadores nem fornecedores."],
            "sem_tabela": ncm_table is None or not getattr(ncm_table, "loaded", lambda: False)()}


def regulatory_block(db, text: str) -> dict:
    try:
        from ..regulatory.api import search_all
        r = search_all(db, {"produto": text[:120]})
        res = r["resultados"]
        return {"registros_encontrados": len(res), "por_orgao": {p.get("orgao") or str(i): len(p["resultados"]) for i, p in enumerate(r["por_orgao"])},
                "exemplos": [{k: x.get(k) for k in ("orgao", "registro", "empresa", "fabricante", "pais_fabricante", "modelo", "situacao", "data")}
                             for x in res[:10]],
                "empresas": r["empresas"]["fabricantes"][:10], "limitacoes": r.get("limitacoes"),
                "regra": "Registros de produtos semelhantes NÃO tornam o seu produto conforme: cada modelo precisa da própria "
                         "homologação/certificação quando exigida. Use 'Conformidade › Analisar Produto' para a análise completa."}
    except Exception as e:  # noqa: BLE001
        return {"registros_encontrados": 0, "erro": type(e).__name__, "regra": "Bases Anatel/Inmetro não carregadas."}


def risks(u: dict, reg: dict, ncm: dict, listings: dict | None) -> list[dict]:
    """Riscos IDENTIFICADOS a partir de dados — cada um com a origem. Não é uma lista exaustiva."""
    out = []
    a = (u or {}).get("atributos") or {}
    t = " ".join(str(v) for v in a.values() if v).lower() + " " + ((u or {}).get("principal") or "")
    if any(k in t for k in ("bluetooth", "wifi", "wi-fi", "rf", "wireless", "zigbee", "nfc")) or (reg.get("por_orgao") or {}).get("Anatel"):
        out.append({"risco": "Homologação Anatel provável (radiofrequência/telecom)", "origem": "atributos do produto / registros Anatel",
                    "acao": "Verificar requisitos e custos de certificação antes de importar"})
    if a.get("tensao") or a.get("potencia_w") or any(k in t for k in ("charger", "carregador", "bateria", "battery")):
        out.append({"risco": "Produto elétrico/bateria — possível certificação Inmetro e restrições de transporte (baterias de lítio)",
                    "origem": "atributos explícitos do produto", "acao": "Confirmar portaria Inmetro aplicável e regras do frete"})
    if (u or {}).get("estado") != "confirmada":
        out.append({"risco": "Identificação do produto não confirmada", "origem": "Product Understanding", "acao": "Revisar a associação"})
    if not ncm.get("candidatas"):
        out.append({"risco": "Sem NCM candidata", "origem": "tabela NCM", "acao": "Carregar a tabela NCM oficial ou classificar com despachante"})
    if listings and listings.get("vendedores_distintos", 0) >= 20:
        out.append({"risco": f"Muitos vendedores nos anúncios observados ({listings['vendedores_distintos']})", "origem": "anúncios coletados",
                    "acao": "Avaliar diferenciação — quantidade de anúncios não é volume de vendas"})
    return out


# ------------------------------------------------------------------------------------------------- simulador
FIELDS = {"preco_fob_unit_usd": "Preço FOB unitário (USD)", "quantidade": "Quantidade (unidades)", "cambio_brl_usd": "Câmbio (BRL por USD)",
          "frete_total_brl": "Frete internacional total (BRL)", "seguro_total_brl": "Seguro (BRL)", "tributos_total_brl": "Tributos de importação totais (BRL)",
          "despesas_aduaneiras_brl": "Despesas aduaneiras/despachante (BRL)", "frete_interno_brl": "Frete interno (BRL)",
          "certificacao_brl": "Certificação/homologação (BRL)", "outros_custos_brl": "Outros custos (BRL)", "preco_venda_unit_brl": "Preço de venda unitário (BRL)",
          "taxa_venda_pct": "Comissão/taxa de venda (%)", "variacao_cenarios_pct": "Variação dos cenários (%)"}
REQUIRED = ["preco_fob_unit_usd", "quantidade", "cambio_brl_usd", "preco_venda_unit_brl"]
COST_ITEMS = ["frete_total_brl", "seguro_total_brl", "tributos_total_brl", "despesas_aduaneiras_brl", "frete_interno_brl", "certificacao_brl",
              "outros_custos_brl"]


def _f(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def simulate(params: dict) -> dict:
    p = {k: _f(params.get(k)) for k in FIELDS}
    missing_req = [FIELDS[k] for k in REQUIRED if p[k] is None]
    pending = [FIELDS[k] for k in COST_ITEMS if p[k] is None]
    if missing_req:
        return {"calculado": False, "pendentes_obrigatorios": missing_req, "pendentes": pending,
                "mensagem": "Informe os campos obrigatórios. O GPI não preenche preços, câmbio, tributos ou frete."}
    if p["quantidade"] <= 0 or p["cambio_brl_usd"] <= 0:
        return {"calculado": False, "pendentes_obrigatorios": ["quantidade e câmbio devem ser maiores que zero"], "pendentes": pending}
    var = (p["variacao_cenarios_pct"] if p["variacao_cenarios_pct"] is not None else 10.0) / 100
    fee = (p["taxa_venda_pct"] or 0) / 100

    def run(cost_mult, price_mult):
        q = p["quantidade"]
        fob_usd = p["preco_fob_unit_usd"] * q
        fob = fob_usd * p["cambio_brl_usd"] * cost_mult
        extras = {FIELDS[k]: round((p[k] or 0) * cost_mult, 2) for k in COST_ITEMS if p[k] is not None}
        landed = fob + sum(extras.values())
        unit_cost = landed / q
        price = p["preco_venda_unit_brl"] * price_mult
        net = price * (1 - fee)
        margin = net - unit_cost
        return {"fob_total_usd": round(fob_usd * cost_mult, 2), "fob_total_brl": round(fob, 2),
                "frete_por_unidade_brl": round((p["frete_total_brl"] or 0) * cost_mult / q, 4) if p["frete_total_brl"] is not None else None,
                "custos_adicionais": extras, "custo_total_brl": round(landed, 2), "custo_unitario_brl": round(unit_cost, 4),
                "preco_venda_unit_brl": round(price, 2), "receita_liquida_unit_brl": round(net, 4), "margem_bruta_unit_brl": round(margin, 4),
                "margem_bruta_pct": round(100 * margin / net, 2) if net else None, "markup": round(price / unit_cost, 3) if unit_cost else None,
                "incompleto": bool(pending)}
    sc = {"Conservador": run(1 + var, 1 - var), "Base": run(1, 1), "Otimista": run(1 - var, 1 + var)}
    return {"calculado": True, "cenarios": sc, "parametros": {FIELDS[k]: v for k, v in p.items() if v is not None},
            "pendentes": pending, "variacao_cenarios_pct": round(var * 100, 2),
            "avisos": ["Simulação PRELIMINAR com os parâmetros que você informou — não é cotação nem cálculo tributário.",
                       "Cenários aplicam ±variação sobre os SEUS valores (custos para cima e preço para baixo no Conservador).",
                       *(["Campos não informados ficam fora do custo: " + ", ".join(pending) + ". O resultado está INCOMPLETO."] if pending else [])]}


def save_scenario(db, name: str | None, product_id: str | None, company_id: int | None, params: dict, result: dict) -> dict:
    S.ensure(db)
    cur = db.execute("INSERT INTO import_scenarios (name, product_id, company_id, params, result, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     ((name or "")[:120] or None, product_id, company_id, json.dumps(params, ensure_ascii=False),
                      json.dumps(result, ensure_ascii=False), S.now()))
    return {"id": cur.lastrowid}


def list_scenarios(db, product_id: str | None = None) -> list[dict]:
    S.ensure(db)
    rows = db.query("SELECT * FROM import_scenarios" + (" WHERE product_id = ?" if product_id else "") + " ORDER BY id DESC LIMIT 100",
                    (product_id,) if product_id else ())
    for r in rows:
        r["params"], r["result"] = json.loads(r["params"]), json.loads(r["result"] or "null")
    return rows
