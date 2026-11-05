"""Inteligência do ranking de mais buscados do Mercado Livre (v0.8, seção 9).

A fonte informa POSIÇÃO (1–50), não volume. Por isso nada aqui calcula crescimento percentual de volume.
Cada termo é reduzido a UMA observação por semana ISO (melhor posição da semana) — coletas repetidas na mesma semana
não duplicam o histórico.

Indicadores (por termo e por produto):
* semanas_coletadas  — semanas em que a fonte foi coletada (denominador comum a todos os termos)
* semanas_presente   — semanas em que o termo apareceu no Top 50
* persistencia       — semanas_presente / semanas_coletadas (= frequência no Top 50)
* melhor_posicao, posicao_media, ultima_posicao
* variacao_posicao   — posição anterior − última (positivo = subiu), só entre semanas consecutivas presentes
* entradas, saidas, reaparecimentos — transições presente/ausente; reaparecimento = volta após ≥ 1 semana fora
* estabilidade       — desvio-padrão das posições (≤ 5 alta; ≤ 12 média; > 12 baixa), com ≥ 3 semanas presentes

Classes:
* NOVO SINAL COMERCIAL — uma única semana com presença (nunca é "crescimento sustentado")
* SINAL EM OBSERVAÇÃO  — 2 ou 3 semanas presentes
* INTERESSE RECORRENTE — ≥ 4 semanas presentes e persistência ≥ 50%
* SINAL INTERMITENTE   — ≥ 4 semanas presentes e persistência < 50%
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np

SOURCES = ("ml_trends", "mercadolivre")


def _week(d: str) -> str:
    y, w, _ = date.fromisoformat(d[:10]).isocalendar()
    return f"{y}-W{w:02d}"


def load(db) -> list[dict]:
    try:
        return db.query("SELECT source, term, ref_date, value, product_id, commercial, intent FROM search_observations "
                        "WHERE metric = 'posicao_tendencia' AND source IN (?, ?) ORDER BY ref_date", SOURCES)
    except Exception:  # noqa: BLE001
        return []


def term_stats(positions: dict[str, float], weeks: list[str]) -> dict:
    present = [w for w in weeks if w in positions]
    pos = [positions[w] for w in present]
    out = {"historico": [[w, positions.get(w)] for w in weeks][-26:],
           "semanas_coletadas": len(weeks), "semanas_presente": len(present),
           "persistencia": round(len(present) / len(weeks), 3) if weeks else None,
           "melhor_posicao": int(min(pos)) if pos else None, "posicao_media": round(float(np.mean(pos)), 1) if pos else None,
           "ultima_posicao": int(positions[present[-1]]) if present else None, "primeira_semana": present[0] if present else None,
           "ultima_semana": present[-1] if present else None, "presente_na_ultima_coleta": bool(weeks and weeks[-1] in positions)}
    ent = sai = rea = 0
    prev = False
    seen = False
    for w in weeks:
        cur = w in positions
        if cur and not prev:
            ent += 1
            if seen:
                rea += 1
        if prev and not cur:
            sai += 1
        seen = seen or cur
        prev = cur
    out.update(entradas=ent, saidas=sai, reaparecimentos=rea)
    var = None
    for i in range(len(weeks) - 1, 0, -1):
        if weeks[i] in positions and weeks[i - 1] in positions:
            var = int(positions[weeks[i - 1]] - positions[weeks[i]])
            break
    out["variacao_posicao"] = var
    if len(pos) >= 3:
        sd = float(np.std(pos))
        out["estabilidade"] = "alta" if sd <= 5 else "média" if sd <= 12 else "baixa"
        out["desvio_posicao"] = round(sd, 1)
    else:
        out["estabilidade"] = None
    run = best = 0
    for w in weeks:                                   # v0.9: maior permanência contínua no ranking
        run = run + 1 if w in positions else 0
        best = max(best, run)
    out["permanencia_max_semanas"] = best
    out["crescimento"] = ("não comprovado — o ranking mede posição relativa, não volume de buscas"
                          if len(present) < 8 else "ver tendência da posição (posição não é volume)")
    n = len(present)
    out["classe"] = ("NOVO SINAL COMERCIAL" if n == 1 else "SINAL EM OBSERVAÇÃO" if n <= 3 else
                     "INTERESSE RECORRENTE" if (out["persistencia"] or 0) >= 0.5 else "SINAL INTERMITENTE") if n else None
    return out


def analyze(db) -> dict:
    rows = load(db)
    weeks = sorted({_week(r["ref_date"]) for r in rows})
    by_term: dict[str, dict] = defaultdict(lambda: {"pos": {}, "product_id": None, "commercial": 0, "ids": []})
    for r in rows:
        t = by_term[r["term"]]
        w = _week(r["ref_date"])
        if w not in t["pos"] or r["value"] < t["pos"][w]:
            t["pos"][w] = float(r["value"])
        t["product_id"] = t["product_id"] or r["product_id"]
        t["commercial"] = max(t["commercial"], int(r["commercial"] or 0))
        t["ids"].append(f"so:{r['source']}|BR|{r['ref_date']}|posicao_tendencia|{r['term']}")
    terms = []
    for term, t in by_term.items():
        st = term_stats(t["pos"], weeks)
        terms.append({"termo": term, "produto_id": t["product_id"], "comercial": bool(t["commercial"]), **st,
                      "observacoes": t["ids"][-12:], "n_observacoes": len(t["ids"])})
    prods: dict[str, list] = defaultdict(list)
    for x in terms:
        if x["produto_id"]:
            prods[x["produto_id"].split(":")[0]].append(x)
    by_product = {}
    for pid, lst in prods.items():
        merged: dict[str, float] = {}
        for x in lst:
            for w, p in by_term[x["termo"]]["pos"].items():
                merged[w] = min(p, merged.get(w, 99))
        st = term_stats(merged, weeks)
        by_product[pid] = {**st, "termos": sorted(x["termo"] for x in lst),
                           "observacoes": [i for x in lst for i in x["observacoes"]][-20:],
                           "n_observacoes": sum(x["n_observacoes"] for x in lst)}
    return {"semanas_coletadas": weeks, "termos": sorted(terms, key=lambda x: (x["ultima_posicao"] or 99)),
            "por_produto": by_product, "termos_sem_produto": sum(1 for x in terms if not x["produto_id"]),
            "aviso": "Posição em ranking não é volume de buscas; nenhuma variação percentual de volume é calculada. "
                     "Uma semana de dados é um novo sinal, não uma tendência histórica."}
