"""
AutoML de séries temporais — sem configuração manual.

1. Perfil da série (tamanho, zeros, tendência, sazonalidade, padrão SBC).
2. Elegibilidade: < 12 períodos → somente análise exploratória (sem previsão quantitativa).
3. Candidatos conforme o perfil (intermitente → Croston/TSB; sazonal → Holt-Winters/ETS;
   ≥ 48 períodos → Random Forest e HistGradientBoosting).
4. Backtesting temporal (módulo da Fase 1, sem vazamento).
5. Escolha do menor WAPE entre os elegíveis; se nenhum superar o Naive, fica o Naive.
6. Previsão, intervalos e registro do desempenho e das limitações.
Retreina somente quando os dados da série mudam (hash). Previsões antigas são
mantidas para avaliação posterior contra os valores realizados.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from ..analytics import classification as cl
from ..forecasting.backtest import backtest, interval
from ..forecasting.models import MODELS, ModelNotApplicable, run_model
from .store import now_iso

FORECAST_TYPES = {
    "vendas": "Previsão de vendas (unidades)",
    "importacao": "Projeção de indicador de importação (US$ ou kg importados — não são vendas da empresa)",
    "interesse": "Previsão de interesse de pesquisa/atenção (visualizações — não são vendas)",
    "popularidade": "Previsão de popularidade (menções em notícias e discussões — não são vendas)",
    "indicador": "Projeção de indicador de mercado (câmbio, varejo — não são vendas da empresa)",
}


def forecast_type(meta: dict) -> str:
    if meta.get("source") == "wikimedia":
        return "interesse"
    if meta.get("source") in ("comexstat", "comtrade"):
        return "importacao"
    if (meta.get("indicator") or "").startswith("Menções"):
        return "popularidade"
    return "indicador"


def profile(y: np.ndarray, m: int) -> dict:
    n = len(y)
    p = {"n": n, "zeros": float(np.mean(y == 0)) if n else None, "padrao": cl.sbc(y)["padrao"] if n else None}
    p["tendencia"] = cl.trend_test(y[-36:]) if n >= 6 else None
    s = cl.seasonality_strength(y, m) if m > 1 else None
    p["sazonal"] = bool(s and s["significativa"])
    p["forca_sazonal"] = s["fs"] if s else None
    return p


def candidates(prof: dict, m: int, allow_ml: bool = True) -> list[str]:
    n = prof["n"]
    if prof["padrao"] in ("intermitente", "irregular (lumpy)"):
        return ["naive", "moving_average", "croston_sba", "tsb"]
    c = ["naive", "ses", "holt_damped"]
    if m > 1 and n >= m + 1:
        c.append("seasonal_naive")
    if m > 1 and n >= 2 * m + 2 and prof["sazonal"]:
        c.append("holt_winters")
    if "sarima" in MODELS and n >= 36:
        c.append("sarima")
    if allow_ml and n >= 60:
        c += ["random_forest", "hist_gb"] + [k for k in ("lightgbm", "xgboost") if k in MODELS]
    return c


def quality(wape: float | None) -> str:
    if wape is None:
        return "não validada"
    return "boa" if wape < 0.2 else ("moderada" if wape < 0.4 else "baixa")


def data_hash(y: pd.Series) -> str:
    return hashlib.sha256(json.dumps([[str(i), round(float(v), 6)] for i, v in y.items()]).encode()).hexdigest()[:16]


def regular_monthly(s: pd.Series) -> pd.Series:
    """Série mensal regular (sem lacunas internas). Lacunas não são preenchidas com
    zero nem interpoladas: usa-se o trecho contínuo mais recente."""
    if s.empty:
        return s
    idx = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
    s = pd.Series(s.values, index=idx).groupby(level=0).last().sort_index()
    full = pd.period_range(s.index.min(), s.index.max(), freq="M")
    s = s.reindex(full)
    if s.isna().any():
        last_gap = np.flatnonzero(s.isna().values)[-1]
        s = s.iloc[last_gap + 1:]
    return s


def auto_forecast(y: pd.Series, meta: dict, horizon: int = 12, m: int = 12, allow_ml: bool = True) -> dict:
    s = regular_monthly(y)
    vals = s.values.astype(float)
    prof = profile(vals, m)
    ftype = forecast_type(meta)
    out = {"tipo": ftype, "tipo_descricao": FORECAST_TYPES[ftype], "perfil": prof,
           "labels": [str(p) for p in s.index], "valores": vals.tolist()}
    if prof["n"] < 12:
        out.update(status="exploratoria", limitacao=f"apenas {prof['n']} meses contínuos: sem previsão quantitativa; "
                                                   "use a tendência como indicação exploratória")
        return out
    cands = candidates(prof, m, allow_ml)
    h = horizon
    bt = backtest(vals, h, m, cands, n_origins=4) if prof["n"] >= 20 else {"resultados": {}, "aviso": "histórico curto"}
    res = bt.get("resultados", {})
    eligible = {k: v for k, v in res.items() if v.get("wape") is not None}
    best = min(eligible, key=lambda k: eligible[k]["wape"]) if eligible else "naive"
    if best != "naive" and eligible.get(best, {}).get("fva_vs_naive", 1) <= 0:
        best = "naive"
    try:
        r = run_model(best, vals, h, m)
    except ModelNotApplicable:
        best = "naive"
        r = run_model("naive", vals, h, m)
    lo80, hi80 = interval(r.forecast, r.var_h, 0.80)
    lo95, hi95 = interval(r.forecast, r.var_h, 0.95)
    last = s.index[-1]
    met = res.get(best, {})
    lim = []
    if not bt.get("origens"):
        lim.append("backtesting indisponível (histórico curto): previsão não validada fora da amostra")
    if met.get("cobertura_80") is not None and met["cobertura_80"] < 0.65:
        lim.append("intervalos estreitos demais no backtesting: a incerteza real é maior")
    if r.interval_method == "aproximado":
        lim.append("intervalo de previsão aproximado")
    out.update(
        status="prevista", modelo=best, modelo_nome=MODELS[best][0], candidatos=cands,
        backtest={k: {kk: vv for kk, vv in v.items() if kk in ("wape", "mae", "rmsse", "bias_pct",
                                                                "cobertura_80", "fva_vs_naive", "erro")}
                  for k, v in res.items()},
        qualidade=quality(met.get("wape")), metricas=met,
        labels_futuro=[str(p) for p in pd.period_range(last + 1, periods=h, freq="M")],
        previsao=np.maximum(r.forecast, 0).tolist(), lo80=lo80.tolist(), hi80=hi80.tolist(),
        lo95=lo95.tolist(), hi95=hi95.tolist(), parametros={k: v for k, v in r.params.items()
                                                            if isinstance(v, (int, float, str))},
        limitacoes=lim)
    return out


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def evaluate_previous(store, sid: int, current: pd.Series) -> list[dict]:
    """Compara previsões anteriores com os valores que se realizaram depois."""
    rows = store.db.query("SELECT id, created_at, payload FROM auto_forecasts WHERE series_id = ? "
                          "AND status = 'prevista' ORDER BY id", (sid,))
    actual = {str(p): v for p, v in regular_monthly(current).items()}
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        pairs = [(a, actual[l]) for l, a in zip(p.get("labels_futuro", []), p.get("previsao", [])) if l in actual]
        if pairs:
            fa = np.array(pairs)
            wape = float(np.abs(fa[:, 0] - fa[:, 1]).sum() / max(np.abs(fa[:, 1]).sum(), 1e-9))
            out.append({"criada_em": r["created_at"], "modelo": p.get("modelo"), "periodos_avaliados": len(pairs),
                        "wape_realizado": wape})
    return out


def run_series(store, sid: int, force: bool = False, allow_ml: bool = True) -> dict | None:
    meta = store.get_series(sid)
    y = store.values(sid)
    if meta is None or y.empty or meta["freq"] != "M":
        return None
    h = data_hash(y)
    prev = store.db.query("SELECT id, data_hash FROM auto_forecasts WHERE series_id = ? ORDER BY id DESC LIMIT 1", (sid,))
    if prev and prev[0]["data_hash"] == h and not force:
        return {"reutilizada": True}
    res = _clean(auto_forecast(y, meta, allow_ml=allow_ml))
    res["avaliacao_anteriores"] = evaluate_previous(store, sid, y)
    fid = store.db.next_id("auto_forecasts")
    store.db.execute("INSERT INTO auto_forecasts (id, series_id, created_at, data_hash, forecast_type, model, status,"
                     " payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (fid, sid, now_iso(), h, res["tipo"], res.get("modelo"), res["status"],
                      json.dumps(res, ensure_ascii=False)))
    return {"reutilizada": False, "status": res["status"], "modelo": res.get("modelo")}


def latest(store, sid: int) -> dict | None:
    r = store.db.query("SELECT created_at, payload FROM auto_forecasts WHERE series_id = ? ORDER BY id DESC LIMIT 1",
                       (sid,))
    if not r:
        return None
    p = json.loads(r[0]["payload"])
    p["criada_em"] = r[0]["created_at"]
    return p
