"""
Machine learning avançado (v0.5) — tudo em CPU, com limites de tempo e memória.

1. Modelo GLOBAL multi-série (mesma ideia do MLForecast): um único modelo aprende padrões comuns a
   várias séries da MESMA métrica. Alvo em razão ao nível recente (y_t / média dos 3 meses anteriores)
   para que séries de escalas diferentes sejam comparáveis. Variáveis: defasagens 1,2,3,6,12 (em
   razão ao nível), médias móveis 3 e 6, crescimento histórico, mês (seno/cosseno e categoria),
   família, categoria, país e fonte (categóricas). Modelos: HistGradientBoosting (sempre), LightGBM,
   XGBoost e CatBoost (se instalados). Previsão recursiva até o horizonte.
2. Comparação justa com modelos LOCAIS (melhor modelo da série no AutoML) por backtesting de origem
   móvel nas mesmas origens; o vencedor é escolhido POR SÉRIE — o global não é presumido melhor.
3. Intervalos CONFORMAIS 80/90/95%: quantis (com correção de amostra finita) dos erros relativos por
   passo do horizonte, calibrados nas origens antigas; a cobertura observada é medida nas origens
   recentes. Dependência temporal e mudanças de regime podem reduzir a cobertura — ela é exibida.
4. Explicabilidade: contribuições SHAP exatas de árvores (TreeSHAP do próprio LightGBM/XGBoost,
   pred_contrib); sem LightGBM/XGBoost, importância por permutação (rotulada como tal). Contribuição
   preditiva não é causalidade.
5. Otimização de hiperparâmetros com Optuna (se instalado) com limite de tentativas e de tempo.
6. Detecção de mudanças: ADWIN (Bifet & Gavaldà, 2007) e Page-Hinkley (River, se instalado; senão,
   implementação própria) sobre log(1+y) — gera eventos e marca a série para reavaliação.
7. Reconciliação hierárquica (Bottom-Up, Top-Down por proporções históricas, MinTrace OLS e WLS
   estrutural) apenas para séries ADITIVAS de volume; índices relativos nunca são somados.
"""
from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

LAGS = (1, 2, 3, 6, 12)
CATS = ("family", "category", "country", "source")


def libs() -> dict:
    out = {}
    for name in ("lightgbm", "xgboost", "catboost", "optuna", "river", "rapidfuzz"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", "?")
        except ImportError:
            out[name] = None
    return out


# ============================================================================ dados em painel
def _level(y, t):
    v = y[max(0, t - 3):t]
    return float(np.mean(v)) if len(v) and np.mean(v) > 0 else None


def features(y: np.ndarray, t: int, month: int, meta: dict) -> dict | None:
    """Variáveis para prever y[t] usando só y[:t]."""
    if t < 13:
        return None
    lev = _level(y, t)
    if not lev:
        return None
    f = {f"lag{k}": y[t - k] / lev for k in LAGS}
    f["mm3"] = float(np.mean(y[t - 3:t])) / lev
    f["mm6"] = float(np.mean(y[t - 6:t])) / lev
    base = y[t - 15:t - 12] if t >= 15 else y[0:1]
    f["cresc_hist"] = (float(np.mean(y[t - 3:t])) / float(np.mean(base)) - 1) if np.mean(base) > 0 else 0.0
    f["mes_sin"], f["mes_cos"] = math.sin(2 * math.pi * month / 12), math.cos(2 * math.pi * month / 12)
    f["mes"] = str(month)
    for c in CATS:
        f[c] = str(meta.get(c) or "—")
    return {"f": f, "nivel": lev}


def panel(series: list[dict], cut: int | None = None) -> tuple[pd.DataFrame, np.ndarray]:
    """series: [{id, y (np.array), months (lista de 1..12 do 1º ponto em diante), meta}]. cut = nº de pontos finais excluídos."""
    rows, target = [], []
    for s in series:
        y = s["y"] if cut is None else s["y"][:len(s["y"]) - cut]
        for t in range(13, len(y)):
            r = features(y, t, s["months"][t], s["meta"])
            if r:
                rows.append(r["f"])
                target.append(y[t] / r["nivel"])
    return pd.DataFrame(rows), np.asarray(target, float)


# ============================================================================ modelos
def _encode(X: pd.DataFrame, cats: dict | None = None):
    X = X.copy()
    cats = cats or {c: sorted(X[c].unique().tolist()) for c in (*CATS, "mes") if c in X}
    for c, vals in cats.items():
        m = {v: i for i, v in enumerate(vals)}
        X[c] = X[c].map(lambda v: m.get(v, -1)).astype(int)
    return X, cats


@dataclass
class Fitted:
    name: str
    model: object
    cats: dict
    columns: list


def make_models(params: dict | None = None) -> dict:
    params = params or {}
    from sklearn.ensemble import HistGradientBoostingRegressor
    av = libs()
    out = {"hist_gb_global": lambda: HistGradientBoostingRegressor(max_iter=200, learning_rate=0.06, min_samples_leaf=8,
                                                                   random_state=0)}
    if av["lightgbm"]:
        import lightgbm as lgb
        p = {"n_estimators": 250, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 8, "subsample": 0.9,
             "colsample_bytree": 0.9, **params.get("lightgbm_global", {})}
        out["lightgbm_global"] = lambda: lgb.LGBMRegressor(**p, n_jobs=1, verbose=-1, random_state=0)
    if av["xgboost"]:
        import xgboost as xgb
        out["xgboost_global"] = lambda: xgb.XGBRegressor(n_estimators=250, learning_rate=0.05, max_depth=4, n_jobs=1,
                                                         random_state=0, verbosity=0)
    if av["catboost"]:
        from catboost import CatBoostRegressor
        out["catboost_global"] = lambda: CatBoostRegressor(iterations=300, learning_rate=0.06, depth=5, loss_function="RMSE",
                                                           verbose=False, random_seed=0, thread_count=1)
    return out


def fit(name: str, factory, X: pd.DataFrame, y: np.ndarray) -> Fitted:
    if name == "catboost_global":
        Xc = X.copy()
        m = factory()
        m.fit(Xc, y, cat_features=[c for c in (*CATS, "mes") if c in Xc])
        return Fitted(name, m, {}, list(Xc.columns))
    Xe, cats = _encode(X)
    m = factory()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.fit(Xe, y)
    return Fitted(name, m, cats, list(Xe.columns))


def predict_rows(fm: Fitted, X: pd.DataFrame) -> np.ndarray:
    if fm.name == "catboost_global":
        return np.asarray(fm.model.predict(X[fm.columns]), float)
    Xe, _ = _encode(X, fm.cats)
    return np.asarray(fm.model.predict(Xe[fm.columns]), float)


def forecast_series(fm: Fitted, s: dict, h: int, cut: int = 0) -> np.ndarray:
    """Previsão recursiva de h passos a partir de y[:len−cut]."""
    y = list(s["y"][:len(s["y"]) - cut] if cut else s["y"])
    m0 = s["months"][len(y) - 1]
    out = []
    for k in range(h):
        month = (m0 + k) % 12 + 1
        r = features(np.asarray(y, float), len(y), month, s["meta"])
        if r is None:
            return np.full(h, np.nan)
        ratio = float(predict_rows(fm, pd.DataFrame([r["f"]]))[0])
        v = max(0.0, ratio * r["nivel"])
        out.append(v)
        y.append(v)
    return np.asarray(out)


# ============================================================================ backtesting global × local
def _wape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    ok = ~np.isnan(p)
    return float(np.sum(np.abs(a[ok] - p[ok])) / np.sum(np.abs(a[ok]))) if ok.any() and np.sum(np.abs(a[ok])) > 0 else None


def local_forecast(y: np.ndarray, h: int) -> tuple[str, np.ndarray]:
    """Melhor modelo local simples por AICc/heurística (mesma família do AutoML): ETS automático, com
    Naive sazonal como alternativa quando o ETS não se aplica."""
    from .models import ModelNotApplicable, run_model
    for key in ("ets_auto", "seasonal_naive", "naive"):
        try:
            return key, np.maximum(run_model(key, y, h, 12).forecast, 0)
        except ModelNotApplicable:
            continue
    return "naive", np.full(h, y[-1])


def evaluate(series: list[dict], h: int = 6, origins: int = 3, cfg: dict | None = None, deadline: float | None = None) -> dict:
    """Backtesting de origem móvel: global (cada modelo) × local, mesmas origens e horizonte."""
    cfg = cfg or {}
    models = make_models(cfg.get("_tuned_params"))
    res = {m: [] for m in models} | {"local": []}
    errs = {m: {} for m in models} | {"local": {}}              # erros relativos por passo, por origem
    per_series = {s["id"]: {} for s in series}
    for o in range(origins, 0, -1):
        cut = o * h if o * h < 30 else h * o
        train = [s for s in series if len(s["y"]) - cut >= 24]
        if len(train) < 3:
            continue
        X, yv = panel(train, cut)
        if len(yv) < 50:
            continue
        fitted = {}
        for name, fac in models.items():
            if deadline and time.time() > deadline:
                break
            try:
                fitted[name] = fit(name, fac, X, yv)
            except Exception:  # noqa: BLE001 — um modelo com erro não impede os demais
                continue
        for s in train:
            actual = s["y"][len(s["y"]) - cut:len(s["y"]) - cut + h]
            if len(actual) < h:
                continue
            preds = {n: forecast_series(f, s, h, cut) for n, f in fitted.items()}
            preds["local"] = local_forecast(s["y"][:len(s["y"]) - cut], h)[1]
            for n, p in preds.items():
                w = _wape(actual, p)
                if w is not None:
                    res[n].append(w)
                    per_series[s["id"]].setdefault(n, []).append(w)
                    errs[n].setdefault(o, []).append((np.asarray(actual) - p) / np.maximum(p, 1e-9))
    summary = {n: {"wape_medio": float(np.mean(v)), "wape_mediano": float(np.median(v)), "n": len(v)}
               for n, v in res.items() if v}
    wins = {}
    for sid, d in per_series.items():
        if d:
            best = min(d, key=lambda n: np.mean(d[n]))
            wins[best] = wins.get(best, 0) + 1
    return {"resumo": summary, "vitorias_por_serie": wins, "por_serie": {k: {n: float(np.mean(v)) for n, v in d.items()}
                                                                          for k, d in per_series.items() if d},
            "erros": errs, "horizonte": h, "origens": origins}


def conformal(errs_by_origin: dict, levels=(0.8, 0.9, 0.95)) -> dict:
    """Quantis dos erros relativos absolutos por passo, calibrados nas origens mais antigas; cobertura
    observada nas mais recentes (avaliação honesta, fora da calibração)."""
    if not errs_by_origin:
        return {}
    origins = sorted(errs_by_origin, reverse=True)               # maior o = mais antiga
    calib = [e for o in origins[:max(1, len(origins) - 1)] for e in errs_by_origin[o]]
    test = [e for e in errs_by_origin[origins[-1]]] if len(origins) > 1 else []
    if not calib:
        return {}
    C = np.abs(np.vstack(calib))                                  # (n, h)
    n = C.shape[0]
    out = {"n_calibracao": int(n), "n_teste": len(test), "quantis": {}, "cobertura_observada": {}, "niveis_indisponiveis": []}
    for lv in levels:
        if math.ceil((n + 1) * lv) > n:
            # v0.7.1: calibração pequena demais para este nível (o quantil conformal seria infinito);
            # antes, todos os níveis viravam o erro máximo e 80/90/95% saíam idênticos — intervalo indefensável
            out["niveis_indisponiveis"].append(str(lv))
            continue
        k = math.ceil((n + 1) * lv) / n
        q = np.quantile(C, k, axis=0, method="higher")
        out["quantis"][str(lv)] = q.tolist()
        if test:
            T = np.abs(np.vstack(test))
            out["cobertura_observada"][str(lv)] = float(np.mean(T <= q))
    return out


def interval(pred: np.ndarray, q: list[float]) -> tuple[np.ndarray, np.ndarray]:
    q = np.asarray(q[:len(pred)], float)
    return np.maximum(0, pred / (1 + q)), pred * (1 + q)        # erro relativo e = (a − p)/p → a = p(1 + e)


# ============================================================================ explicabilidade
GROUPS = {"lag1": "tendência recente", "lag2": "tendência recente", "lag3": "tendência recente", "mm3": "tendência recente",
          "lag6": "patamar do semestre", "mm6": "patamar do semestre", "lag12": "sazonalidade (mesmo mês do ano anterior)",
          "mes": "sazonalidade (mês)", "mes_sin": "sazonalidade (mês)", "mes_cos": "sazonalidade (mês)",
          "cresc_hist": "crescimento histórico", "family": "família do produto", "category": "categoria",
          "country": "país", "source": "fonte"}


def explain(fm: Fitted, X: pd.DataFrame) -> dict:
    method = None
    try:
        if fm.name == "lightgbm_global":
            Xe, _ = _encode(X, fm.cats)
            contrib = fm.model.predict(Xe[fm.columns], pred_contrib=True)
            method = "SHAP (TreeSHAP do LightGBM)"
        elif fm.name == "xgboost_global":
            import xgboost as xgb
            Xe, _ = _encode(X, fm.cats)
            contrib = fm.model.get_booster().predict(xgb.DMatrix(Xe[fm.columns]), pred_contribs=True)
            method = "SHAP (TreeSHAP do XGBoost)"
        elif fm.name == "catboost_global":
            from catboost import Pool
            contrib = fm.model.get_feature_importance(Pool(X[fm.columns], cat_features=[c for c in (*CATS, "mes") if c in X]),
                                                      type="ShapValues")
            method = "SHAP (CatBoost)"
        else:
            return {"metodo": "indisponível para este modelo (instale LightGBM/XGBoost para SHAP)", "fatores": []}
    except Exception as e:  # noqa: BLE001
        return {"metodo": f"falhou ({type(e).__name__})", "fatores": []}
    c = np.asarray(contrib)[:, :-1]                               # última coluna = valor base
    agg = {}
    for j, col in enumerate(fm.columns):
        g = GROUPS.get(col, col)
        agg[g] = agg.get(g, 0.0) + float(np.mean(np.abs(c[:, j])))
    tot = sum(agg.values()) or 1
    return {"metodo": method, "fatores": sorted([{"fator": k, "peso": v / tot} for k, v in agg.items()], key=lambda x: -x["peso"]),
            "aviso": "Contribuição para a previsão do modelo — não indica causalidade."}


def explain_row(fm: Fitted, frow: dict) -> list[dict]:
    e = explain(fm, pd.DataFrame([frow]))
    return e["fatores"][:5]


# ============================================================================ otimização (Optuna)
def tune_lightgbm(series: list[dict], trials: int, seconds: int) -> dict | None:
    av = libs()
    if not (av["optuna"] and av["lightgbm"]) or trials <= 0:
        return None
    import lightgbm as lgb
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    h = 6
    train = [s for s in series if len(s["y"]) >= 30]
    X, y = panel(train, h)
    if len(y) < 80:
        return None
    Xe, cats = _encode(X)
    val = [s for s in train]

    def objective(trial):
        p = {"n_estimators": trial.suggest_int("n_estimators", 80, 400), "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
             "num_leaves": trial.suggest_int("num_leaves", 7, 31), "min_child_samples": trial.suggest_int("min_child_samples", 5, 30)}
        m = lgb.LGBMRegressor(**p, n_jobs=1, verbose=-1, random_state=0).fit(Xe, y)
        fm = Fitted("lightgbm_global", m, cats, list(Xe.columns))
        ws = [_wape(s["y"][len(s["y"]) - h:], forecast_series(fm, s, h, h)) for s in val]
        ws = [w for w in ws if w is not None]
        return float(np.mean(ws)) if ws else 1e9
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
    study.optimize(objective, n_trials=trials, timeout=seconds, n_jobs=1, gc_after_trial=True)
    return {"melhores_parametros": study.best_params, "wape_validacao": study.best_value, "tentativas": len(study.trials)}


# ============================================================================ mudanças de comportamento (drift)
class PageHinkley:
    """Page-Hinkley para aumento OU queda da média: m_t = Σ (x_i − x̄_i − δ); alarme se m_t − min m > λ."""

    def __init__(self, delta=0.05, threshold=1.5, min_n=6):
        self.delta, self.threshold, self.min_n = delta, threshold, min_n
        self.n = 0
        self.mean = 0.0
        self.up = self.up_min = 0.0
        self.dn = self.dn_max = 0.0

    def update(self, x: float) -> str | None:
        self.n += 1
        self.mean += (x - self.mean) / self.n
        self.up += x - self.mean - self.delta
        self.up_min = min(self.up_min, self.up)
        self.dn += x - self.mean + self.delta
        self.dn_max = max(self.dn_max, self.dn)
        if self.n < self.min_n:
            return None
        if self.up - self.up_min > self.threshold:
            self.__init__(self.delta, self.threshold, self.min_n)
            return "alta"
        if self.dn_max - self.dn > self.threshold:
            self.__init__(self.delta, self.threshold, self.min_n)
            return "queda"
        return None


class Adwin:
    """ADWIN exato (janela ≤ max_w): corta a janela quando duas subjanelas têm médias diferentes além de
    ε_cut = sqrt( (1/(2m)) · ln(4n/δ) ), m = média harmônica dos tamanhos (Bifet & Gavaldà, 2007).
    Os valores devem estar em [0, 1] (normalizados pelo chamador)."""

    def __init__(self, delta=0.002, max_w=240, min_side=5):
        self.delta, self.max_w, self.min_side, self.w = delta, max_w, min_side, []

    def update(self, x: float) -> str | None:
        self.w.append(float(x))
        if len(self.w) > self.max_w:
            self.w.pop(0)
        n = len(self.w)
        if n < 2 * self.min_side:
            return None
        arr = np.asarray(self.w)
        cs = np.cumsum(arr)
        for k in range(self.min_side, n - self.min_side + 1):
            n0, n1 = k, n - k
            mu0, mu1 = cs[k - 1] / n0, (cs[-1] - cs[k - 1]) / n1
            m = 1 / (1 / n0 + 1 / n1)
            eps = math.sqrt((1 / (2 * m)) * math.log(4 * n / self.delta))
            if abs(mu0 - mu1) > eps:
                self.w = self.w[k:]
                return "alta" if mu1 > mu0 else "queda"
        return None


def detect_drift(y: np.ndarray, labels: list[str]) -> list[dict]:
    """Eventos de mudança persistente na série (log(1+y), normalizada para [0,1] no ADWIN)."""
    z = np.log1p(np.asarray(y, float))
    if len(z) < 12 or np.ptp(z) == 0:
        return []
    zn = (z - z.min()) / np.ptp(z)
    av = libs()
    events = []
    if av["river"]:
        from river import drift
        dets = {"ADWIN (River)": drift.ADWIN(delta=0.002), "Page-Hinkley (River)": drift.PageHinkley(min_instances=6, delta=0.05, threshold=1.5)}
        for name, d in dets.items():
            for i, v in enumerate(zn if "ADWIN" in name else z - z[:6].mean()):
                d.update(float(v))
                if d.drift_detected:
                    before, after = z[max(0, i - 6):i].mean() if i else z[0], z[i:i + 3].mean()
                    events.append({"detector": name, "indice": i, "data": labels[i], "direcao": "alta" if after > before else "queda"})
    else:
        ad, ph = Adwin(), PageHinkley()
        for i, v in enumerate(zn):
            r = ad.update(v)
            if r:
                events.append({"detector": "ADWIN", "indice": i, "data": labels[i], "direcao": r})
        for i, v in enumerate(z - z[:6].mean()):
            r = ph.update(float(v))
            if r:
                events.append({"detector": "Page-Hinkley", "indice": i, "data": labels[i], "direcao": r})
    return events


# ============================================================================ reconciliação hierárquica
def summing_matrix(groups: dict[str, list[int]], n_bottom: int) -> tuple[np.ndarray, list[str]]:
    """S: linhas = [total, grupos…, base…]; colunas = séries de base."""
    rows, names = [np.ones(n_bottom)], ["total"]
    for g, idx in groups.items():
        r = np.zeros(n_bottom)
        r[idx] = 1
        rows.append(r)
        names.append(g)
    rows += list(np.eye(n_bottom))
    names += [f"base{i}" for i in range(n_bottom)]
    return np.vstack(rows), names


def reconcile(S: np.ndarray, yhat: np.ndarray, method: str, hist: np.ndarray | None = None) -> np.ndarray:
    """yhat: (n_total_nós, h) previsões base de todos os nós. Devolve previsões coerentes de todos os nós.
    bu — soma das bases; td — total × proporções históricas médias; mint_ols — P=(SᵀS)⁻¹Sᵀ;
    mint_wls — P=(SᵀW⁻¹S)⁻¹SᵀW⁻¹ com W = diag(S·1) (escala estrutural)."""
    m, n = S.shape
    if method == "bu":
        b = yhat[m - n:]
    elif method == "td":
        if hist is None:
            raise ValueError("top-down exige histórico das séries de base")
        p = hist.sum(axis=1) / hist.sum()
        b = np.outer(p, yhat[0])
    elif method == "mint_ols":
        b = np.linalg.solve(S.T @ S, S.T @ yhat)
    elif method == "mint_wls":
        Wi = np.diag(1 / S.sum(axis=1))
        b = np.linalg.solve(S.T @ Wi @ S, S.T @ Wi @ yhat)
    else:
        raise ValueError(method)
    return S @ np.maximum(b, 0)


# ============================================================================ execução completa (etapa do analisador)
def run_all(consumer: dict, cfg: dict, previous: dict | None = None, state: dict | None = None) -> dict:
    """Executa o ML avançado por grupo de métrica (unidades nunca misturadas). Reaproveita o resultado
    anterior de um grupo quando os dados não mudaram e não houve mudança de comportamento."""
    import hashlib
    import json
    t0 = time.time()
    budget = float(cfg.get("ml_budget_s", 300))
    deadline = t0 + budget
    groups = {}
    for s in consumer.get("series", []):
        ind = s.get("ind", {})
        if s.get("period") != "mes" or ind.get("n", 0) < 24 or s["metric"] not in ("volume_mensal_aprox", "volume_bing", "visualizacoes"):
            continue
        labels = ind["labels"]
        months = [int(lbl[5:7]) for lbl in labels]
        groups.setdefault(s["metric"], []).append({
            "id": s["id"], "y": np.asarray(ind["valores"], float), "months": months, "labels": labels, "nome": s.get("nome"),
            "meta": {"family": s["product_id"].split("+")[0], "category": s.get("categoria"), "country": s["country"],
                     "source": s["source"]}})
    out = {"bibliotecas": libs(), "grupos": {}, "drift": [], "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S")}
    prev_groups = (previous or {}).get("grupos", {})
    for metric, series in groups.items():
        series = sorted(series, key=lambda s: -float(np.mean(s["y"][-3:])))[:int(cfg.get("ml_global_max_series", 120))]
        h = hashlib.sha256(json.dumps([[s["id"], s["y"].round(4).tolist()] for s in series]).encode()).hexdigest()[:16]
        drift = []
        for s in series:
            for e in detect_drift(s["y"], s["labels"]):
                if e["indice"] >= len(s["y"]) - 6:                 # mudança recente e persistente o bastante para agir
                    drift.append({**e, "serie": s["id"], "nome": s["nome"]})
        out["drift"] += drift
        if prev_groups.get(metric, {}).get("hash") == h and not drift:
            out["grupos"][metric] = {**prev_groups[metric], "reutilizado": True}
            continue
        if state is not None:
            state["atual"] = f"ML avançado: {metric} ({len(series)} séries)"
        g = {"hash": h, "series": len(series), "reutilizado": False}
        if len(series) < 3:
            g["aviso"] = "menos de 3 séries elegíveis: o modelo global não é treinado"
            out["grupos"][metric] = g
            continue
        tuned = None
        if cfg.get("ml_tuning_trials", 0) and time.time() < deadline:
            tuned = tune_lightgbm(series, int(cfg.get("ml_tuning_trials", 15)), int(cfg.get("ml_tuning_seconds", 120)))
        g["otimizacao"] = tuned or {"aviso": "Optuna/LightGBM indisponíveis ou desligado em Configurações"}
        ev = evaluate(series, 6, 3, {"_tuned_params": {"lightgbm_global": tuned["melhores_parametros"]} if tuned else {}}, deadline)
        g["backtest"] = {k: ev[k] for k in ("resumo", "vitorias_por_serie", "horizonte", "origens")}
        models = make_models({"lightgbm_global": tuned["melhores_parametros"]} if tuned else {})
        ranked = sorted((k for k in ev["resumo"] if k != "local"), key=lambda k: ev["resumo"][k]["wape_medio"])
        if not ranked:
            out["grupos"][metric] = {**g, "aviso": "backtesting sem origens suficientes"}
            continue
        best = ranked[0]
        g["melhor_global"] = best
        g["conformal"] = conformal(ev["erros"].get(best, {}))
        X, yv = panel(series)
        fm = fit(best, models[best], X, yv)
        g["explicacao_global"] = explain(fm, X)
        per = {}
        for s in series:
            choice = min(("local", best), key=lambda k: ev["por_serie"].get(s["id"], {}).get(k, 9e9))
            if choice == "local":
                name, pred = local_forecast(s["y"], 6)
            else:
                name, pred = best, forecast_series(fm, s, 6)
            lv = {}
            for level, q in (g["conformal"].get("quantis") or {}).items():
                lo, hi = interval(pred, q)
                lv[level] = {"lo": lo.tolist(), "hi": hi.tolist()}
            r = features(s["y"], len(s["y"]), s["months"][-1] % 12 + 1, s["meta"])
            per[s["id"]] = {"modelo": name, "escolha": "global" if choice != "local" else "local",
                            "wape_backtest": ev["por_serie"].get(s["id"], {}), "previsao": pred.tolist(), "intervalos": lv,
                            "fatores": explain_row(fm, r["f"]) if (r and choice != "local") else []}
        g["por_serie"] = per
        g["hierarquia"] = hierarchy(series, per) if metric in ("volume_mensal_aprox", "volume_bing") else \
            {"aviso": "índices de atenção (visualizações) não são agregados hierarquicamente"}
        out["grupos"][metric] = g
    out["segundos"] = round(time.time() - t0, 1)
    return out


def hierarchy(series: list[dict], per: dict) -> dict:
    """Categoria → produtos, por país, para volumes aditivos. Compara BU, TD e MinT no último ano."""
    out = {}
    by = {}
    for s in series:
        by.setdefault((s["meta"]["country"], s["meta"]["category"] or "—"), []).append(s)
    for (cc, cat), lst in by.items():
        if len(lst) < 2:
            continue
        n, h = len(lst), 6
        base = np.vstack([per[s["id"]]["previsao"] for s in lst])
        total_hist = np.sum([s["y"][-12:] for s in lst], axis=0)
        from .models import ModelNotApplicable, run_model
        try:
            top = np.maximum(run_model("ets_auto", total_hist if len(total_hist) >= 24 else
                                       np.sum([s["y"] for s in lst], axis=0), h, 12).forecast, 0)
        except ModelNotApplicable:
            top = base.sum(axis=0)
        S, names = summing_matrix({}, n)
        S = S[[0] + list(range(1, 1 + n))]                        # total + bases (dois níveis)
        yhat = np.vstack([top, base])
        hist = np.vstack([s["y"][-12:] for s in lst])
        rec = {m: reconcile(S, yhat, m, hist)[0].tolist() for m in ("bu", "td", "mint_ols", "mint_wls")}
        out[f"{cc} · {cat}"] = {"produtos": [s["nome"] for s in lst], "total_base": top.tolist(), "reconciliado": rec,
                               "aviso": "Soma de volumes de palavras-chave distintas por produto; termos sobrepostos podem inflar o total."}
    return out
