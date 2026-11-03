"""
Viabilidade de importação (v0.5) — só com dados informados pelo usuário (preços de fornecedor, impostos,
frete, preço de venda e demanda NUNCA são inventados). O câmbio pode vir da PTAX coletada.

Custo nacionalizado por unidade (simplificação — confirme alíquotas e regime com o despachante):
  CIF = (FOB + frete + seguro) × câmbio            (FOB = EXW + frete interno na China, se informado EXW)
  II = CIF·ii;  IPI = (CIF + II)·ipi;  PIS = CIF·pis;  COFINS = CIF·cofins
  ICMS "por dentro": base = (CIF + II + IPI + PIS + COFINS + despesas) / (1 − icms);  ICMS = base·icms
  custo = CIF + II + IPI + PIS + COFINS + ICMS + despesas
Monte Carlo: cada variável incerta com distribuição triangular (mín, base, máx) informada; 10.000 cenários.
Estoque: SS = z·σ_d·√L; ponto de reposição = d·L + SS (L em meses).
Quantidade do pedido: maximiza o lucro esperado (média dos cenários, vendas = mín(Q, demanda no horizonte))
sujeito a Q ≥ MOQ, múltiplo do lote e Q·custo ≤ orçamento — busca exata em uma dimensão.
"""
from __future__ import annotations

import math

import numpy as np

REQUIRED = {"fob_usd": "Preço FOB por unidade (US$) — ou EXW + frete interno na China",
            "frete_usd": "Frete internacional por unidade (US$)", "preco_venda_brl": "Preço de venda por unidade (R$)",
            "demanda_mensal": "Demanda mensal estimada (unidades) — a sua estimativa; interesse de busca não é demanda",
            "ii": "Alíquota do Imposto de Importação (%)", "ipi": "Alíquota do IPI (%)", "pis": "PIS-Importação (%)",
            "cofins": "COFINS-Importação (%)", "icms": "ICMS (%)", "cambio": "Câmbio R$/US$ (pode usar a PTAX coletada)"}
UNCERTAIN = ("fob_usd", "frete_usd", "cambio", "preco_venda_brl", "demanda_mensal")


def _tri(v):
    """Aceita número ou {min, base, max}."""
    if isinstance(v, dict):
        b = float(v["base"])
        lo, hi = float(v.get("min", b)), float(v.get("max", b))
        if not lo <= b <= hi:
            raise ValueError("cada intervalo precisa de mín ≤ base ≤ máx")
        return lo, b, hi
    b = float(v)
    return b, b, b


def missing(p: dict) -> list[str]:
    have = dict(p)
    if have.get("fob_usd") in (None, "") and have.get("exw_usd") not in (None, ""):
        have["fob_usd"] = "via EXW"
    return [f"{k}: {d}" for k, d in REQUIRED.items() if have.get(k) in (None, "")]


def unit_cost(fob, frete, cambio, p) -> dict:
    seguro = (fob + frete) * float(p.get("seguro_pct", 0)) / 100
    cif = (fob + frete + seguro) * cambio
    ii = cif * p["ii"] / 100
    ipi = (cif + ii) * p["ipi"] / 100
    pis, cofins = cif * p["pis"] / 100, cif * p["cofins"] / 100
    desp = float(p.get("despesas_brl_unidade", 0))
    base_icms = (cif + ii + ipi + pis + cofins + desp) / (1 - p["icms"] / 100)
    icms = base_icms * p["icms"] / 100
    total = cif + ii + ipi + pis + cofins + icms + desp
    return {"cif": cif, "ii": ii, "ipi": ipi, "pis": pis, "cofins": cofins, "icms": icms, "despesas": desp, "custo_unitario": total}


def simulate(p: dict, n: int = 10000, seed: int = 0) -> dict:
    miss = missing(p)
    if miss:
        return {"status": "dados insuficientes", "faltando": miss,
                "aviso": "A simulação só usa valores informados por você. Nenhum preço, custo ou margem é estimado pelo GPI."}
    p = dict(p)
    for k in ("ii", "ipi", "pis", "cofins", "icms", "seguro_pct"):
        p[k] = float(p.get(k, 0) or 0)
    if p["icms"] >= 100:
        raise ValueError("ICMS deve ser menor que 100%")
    tri = {k: _tri(p[k]) for k in UNCERTAIN if k in p}
    if p.get("fob_usd") in (None, ""):
        exw, frete_cn = _tri(p["exw_usd"]), _tri(p.get("frete_china_usd", 0))
        tri["fob_usd"] = tuple(a + b for a, b in zip(exw, frete_cn))
    rng = np.random.default_rng(seed)
    draw = {k: (rng.triangular(lo, b, hi, n) if hi > lo else np.full(n, b)) for k, (lo, b, hi) in tri.items()}
    horizon = int(p.get("horizonte_meses", 6))
    lead = float(p.get("lead_time_dias", 60)) / 30.4
    moq, lote = int(p.get("moq", 1) or 1), int(p.get("lote", 1) or 1)
    budget = float(p["orcamento_brl"]) if p.get("orcamento_brl") not in (None, "") else math.inf
    cost = unit_cost(draw["fob_usd"], draw["frete_usd"], draw["cambio"], p)["custo_unitario"]
    demand = draw["demanda_mensal"] * horizon
    price = draw["preco_venda_brl"]
    base = {k: v[1] for k, v in tri.items()}
    base_cost = unit_cost(base["fob_usd"], base["frete_usd"], base["cambio"], p)

    def profit(q, c=cost, d=demand, pr=price):
        return np.minimum(q, d) * pr - q * c

    # quantidade ótima (busca exata em uma dimensão)
    q_max = int(min(np.percentile(demand, 95) * 1.2, budget / max(base_cost["custo_unitario"], 1e-9)))
    cands = [q for q in range(moq, max(moq, q_max) + 1, lote)] or [moq]
    if len(cands) > 400:
        cands = sorted(set(int(x) // lote * lote for x in np.linspace(moq, max(moq, q_max), 400)) | {moq})
    feas = [q for q in cands if q * base_cost["custo_unitario"] <= budget]
    best_q = max(feas, key=lambda q: float(np.mean(profit(q)))) if feas else None
    q = best_q or moq
    pr = profit(q)
    margin = (price - cost) / price
    # cenários e sensibilidade
    def det(vals):
        c = unit_cost(vals["fob_usd"], vals["frete_usd"], vals["cambio"], p)["custo_unitario"]
        return float(min(q, vals["demanda_mensal"] * horizon) * vals["preco_venda_brl"] - q * c)
    worst = {k: (v[2] if k in ("fob_usd", "frete_usd", "cambio") else v[0]) for k, v in tri.items()}
    bestc = {k: (v[0] if k in ("fob_usd", "frete_usd", "cambio") else v[2]) for k, v in tri.items()}
    sens = []
    for k, (lo, b, hi) in tri.items():
        if hi > lo:
            a, z = det({**base, k: lo}), det({**base, k: hi})
            sens.append({"variavel": k, "lucro_no_minimo": a, "lucro_no_maximo": z, "amplitude": abs(z - a)})
    d_month = draw["demanda_mensal"]
    z = {0.9: 1.2816, 0.95: 1.6449, 0.98: 2.0537}.get(float(p.get("nivel_servico", 0.95)), 1.6449)
    ss = z * float(np.std(d_month)) * math.sqrt(lead)
    return {
        "status": "ok", "quantidade_sugerida": best_q, "restricoes": {"moq": moq, "lote": lote, "orcamento_brl": None if budget == math.inf else budget},
        "custo_base": base_cost, "lucro": {"media": float(np.mean(pr)), "p10": float(np.percentile(pr, 10)), "p50": float(np.percentile(pr, 50)),
                                           "p90": float(np.percentile(pr, 90)), "prob_prejuizo": float(np.mean(pr < 0))},
        "margem_unitaria": {"p10": float(np.percentile(margin, 10)), "p50": float(np.percentile(margin, 50)), "p90": float(np.percentile(margin, 90))},
        "investimento_base": q * base_cost["custo_unitario"],
        "cenarios": {"pessimista": det(worst), "base": det(base), "otimista": det(bestc)},
        "sensibilidade": sorted(sens, key=lambda x: -x["amplitude"]),
        "estoque": {"estoque_seguranca": ss, "ponto_reposicao": float(np.mean(d_month)) * lead + ss, "lead_time_meses": lead},
        "cenarios_simulados": n,
        "aviso": ("Simulação com os valores informados. Impostos simplificados (sem regimes especiais, ST ou benefícios); confirme com o "
                  "despachante. Não é recomendação de compra.")}
