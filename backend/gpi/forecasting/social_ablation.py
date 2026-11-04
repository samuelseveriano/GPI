"""
Sinais sociais como variáveis explicativas — comparação COM × SEM (v0.6).

Os sinais sociais só são usados na previsão quando há evidência de ganho fora da amostra:
* Pares (série de busca/atenção mensal, série social mensal do mesmo produto) com pelo menos
  `min_overlap` meses alinhados (padrão 18) e métrica social estável (sem lacunas no período).
* Modelo global (HistGradientBoosting; LightGBM quando instalado) treinado em razões ao nível
  recente — mesmas variáveis nos dois cenários, mais as defasagens sociais no cenário "com".
* Variáveis só usam informação até t−1 (defasagens 1 e 2 do sinal social e 1–3 do alvo): não há
  vazamento temporal. A validação é por origem móvel: treina até a origem e prevê o mês seguinte.
* Regra de adoção: WAPE com sinais sociais menor que sem, com redução relativa ≥ 2% no total E em
  pelo menos 75% das origens. Caso contrário os sinais NÃO são usados automaticamente.
* Isso prevê interesse de busca/atenção, não unidades vendidas.
"""
from __future__ import annotations

import numpy as np

MIN_OVERLAP = 18


def _model():
    try:
        import lightgbm as lgb
        return lgb.LGBMRegressor(n_estimators=150, learning_rate=0.05, num_leaves=15, min_child_samples=5, verbose=-1, random_state=0)
    except Exception:  # noqa: BLE001
        from sklearn.ensemble import HistGradientBoostingRegressor
        return HistGradientBoostingRegressor(max_iter=150, learning_rate=0.06, max_leaf_nodes=15, random_state=0)


def features(y: np.ndarray, x: np.ndarray, t: int, with_social: bool) -> list[float] | None:
    """Variáveis para prever y[t] usando somente índices < t (sem vazamento)."""
    if t < 6:
        return None
    lvl = float(np.mean(y[t - 6:t]))
    if lvl <= 0:
        return None
    f = [y[t - 1] / lvl, y[t - 2] / lvl, y[t - 3] / lvl, (y[t - 1] - y[t - 4]) / lvl]
    if with_social:
        sl = float(np.mean(x[t - 6:t]))
        sl = sl if sl > 0 else 1.0
        f += [x[t - 1] / sl, x[t - 2] / sl, (x[t - 1] - x[t - 3]) / sl]
    return f


def _xy(pairs, upto: int | None, with_social: bool):
    X, Y = [], []
    for y, x in pairs:
        end = len(y) if upto is None else min(len(y), upto)
        for t in range(6, end):
            f = features(y, x, t, with_social)
            if f is None:
                continue
            X.append(f)
            Y.append(y[t] / float(np.mean(y[t - 6:t])))
    return np.array(X), np.array(Y)


def evaluate(pairs: list[tuple[np.ndarray, np.ndarray]], n_origins: int = 6) -> dict:
    """Backtesting por origem móvel (1 passo à frente). pairs: [(alvo, social)] alinhados e do mesmo tamanho."""
    pairs = [(np.asarray(y, float), np.asarray(x, float)) for y, x in pairs if len(y) == len(x) and len(y) >= MIN_OVERLAP]
    if len(pairs) < 2:
        return {"status": "insuficiente", "aviso": f"são necessários ≥ 2 produtos com ≥ {MIN_OVERLAP} meses alinhados de busca e redes sociais"}
    n = min(len(y) for y, _ in pairs)
    origins = list(range(n - n_origins, n))
    res = {"sem": [], "com": []}
    per_origin = []
    for o in origins:
        err = {}
        for key, ws in (("sem", False), ("com", True)):
            X, Y = _xy([(y[:o], x[:o]) for y, x in pairs], None, ws)
            if len(Y) < 20:
                err = None
                break
            m = _model()
            m.fit(X, Y)
            num = den = 0.0
            for y, x in pairs:
                f = features(y, x, o, ws)
                if f is None:
                    continue
                pred = float(m.predict(np.array([f]))[0]) * float(np.mean(y[o - 6:o]))
                num += abs(y[o] - max(pred, 0))
                den += abs(y[o])
            err[key] = num / den if den else None
        if not err or None in err.values():
            continue
        res["sem"].append(err["sem"])
        res["com"].append(err["com"])
        per_origin.append({"origem": int(o), "wape_sem_social": err["sem"], "wape_com_social": err["com"]})
    if len(per_origin) < 3:
        return {"status": "insuficiente", "aviso": "origens de validação insuficientes"}
    sem, com = float(np.mean(res["sem"])), float(np.mean(res["com"]))
    gain = (sem - com) / sem if sem else 0.0
    wins = sum(1 for p in per_origin if p["wape_com_social"] < p["wape_sem_social"]) / len(per_origin)
    adopt = gain >= 0.02 and wins >= 0.75
    return {"status": "avaliado", "wape_sem_social": sem, "wape_com_social": com, "ganho_relativo": gain,
            "origens_com_ganho": wins, "origens": per_origin, "series": len(pairs), "adotar": adopt,
            "decisao": ("usar sinais sociais (ganho fora da amostra confirmado)" if adopt else
                        "não usar sinais sociais (sem ganho consistente fora da amostra)")}


def run(consumer: dict, social: dict) -> dict:
    """Monta os pares por métrica de busca/atenção e avalia. Uma métrica social por par (a de maior histórico)."""
    soc_by = {}
    for s in social.get("series", []):
        if s.get("period") != "mes" or len(s["ind"].get("valores") or []) < MIN_OVERLAP:
            continue
        cur = soc_by.get(s["product_id"])
        if cur is None or len(s["ind"]["valores"]) > len(cur["ind"]["valores"]):
            soc_by[s["product_id"]] = s
    groups = {}
    for s in consumer.get("series", []):
        if s.get("period") != "mes" or s["product_id"] not in soc_by:
            continue
        a = dict(zip(s["ind"].get("labels") or [], s["ind"].get("valores") or []))
        b = dict(zip(soc_by[s["product_id"]]["ind"]["labels"], soc_by[s["product_id"]]["ind"]["valores"]))
        common = sorted(set(a) & set(b))
        if len(common) < MIN_OVERLAP:
            continue
        # estabilidade: meses consecutivos e sem zeros no sinal social
        if any(b[k] <= 0 for k in common[-MIN_OVERLAP:]):
            continue
        common = common[-36:]
        groups.setdefault(s["metric"], []).append((np.array([a[k] for k in common]), np.array([b[k] for k in common])))
    out = {}
    for metric, pairs in groups.items():
        n = min(len(y) for y, _ in pairs)
        pairs = [(y[-n:], x[-n:]) for y, x in pairs]
        out[metric] = evaluate(pairs)
    return {"grupos": {k: v for k, v in out.items()},
            "aviso": None if out else (f"Sem pares com ≥ {MIN_OVERLAP} meses alinhados de busca/atenção e redes sociais: "
                                       "os sinais sociais não são usados nas previsões."),
            "regra": "Adotar somente com redução de WAPE ≥ 2% no total e em ≥ 75% das origens (backtesting 1 passo, origem móvel)."}
