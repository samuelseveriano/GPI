"""Regras de aplicação: ligam banco, séries, modelos e análises."""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from .analytics import classification as cl
from .forecasting.backtest import backtest, interval, select_best
from .forecasting.models import MODELS, ModelNotApplicable, run_model
from .series import FREQS, build_series, future_labels, period_labels
from .supply_chain import inventory


def _clean(o):
    """Converte numpy/NaN para JSON."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return [_clean(v) for v in o.tolist()]
    if isinstance(o, (np.floating, float)):
        return None if (np.isnan(o) or np.isinf(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def data_bounds(db):
    r = db.query("SELECT MIN(date) AS a, MAX(date) AS b FROM sales")[0]
    return r["a"], r["b"]


def status(db, engine: str):
    imports = db.query("SELECT * FROM imports ORDER BY id")
    counts = db.query("SELECT COUNT(*) AS n, COUNT(DISTINCT sku) AS skus FROM sales")[0]
    a, b = data_bounds(db)
    return {"motor_banco": engine, "versao_schema": db.schema_version(),
            "importacoes": imports, "linhas": counts["n"], "skus": counts["skus"],
            "periodo": [a, b], "tem_demo": any(i["is_demo"] for i in imports),
            "somente_demo": bool(imports) and all(i["is_demo"] for i in imports)}


def sales_df(db, sku: str | None = None, category: str | None = None) -> pd.DataFrame:
    sql = ("SELECT s.date, s.sku, s.product, s.category, s.quantity, s.unit_price, i.is_demo "
           "FROM sales s JOIN imports i ON i.id = s.import_id WHERE 1=1")
    p = []
    if sku:
        sql += " AND s.sku = ?"; p.append(sku)
    if category:
        sql += " AND s.category = ?"; p.append(category)
    return db.query_df(sql, tuple(p))


def skus(db, q: str = "", category: str = ""):
    sql = ("SELECT s.sku, MAX(s.product) AS produto, MAX(s.category) AS categoria, "
           "SUM(s.quantity) AS quantidade, SUM(s.quantity * COALESCE(s.unit_price, 0)) AS receita, "
           "MIN(s.date) AS primeira, MAX(s.date) AS ultima, COUNT(*) AS registros, "
           "MAX(i.is_demo) AS demo FROM sales s JOIN imports i ON i.id = s.import_id WHERE 1=1")
    p = []
    if q:
        sql += " AND (LOWER(s.sku) LIKE ? OR LOWER(s.product) LIKE ?)"
        p += [f"%{q.lower()}%"] * 2
    if category:
        sql += " AND s.category = ?"; p.append(category)
    sql += " GROUP BY s.sku ORDER BY quantidade DESC"
    return db.query(sql, tuple(p))


def series_for(db, sku, freq, zero_fill=True, category=None):
    df = sales_df(db, sku=sku, category=category)
    a, b = data_bounds(db)
    s, info = build_series(df, freq, zero_fill=zero_fill, data_start=a, data_end=b)
    info["demo"] = bool(df["is_demo"].max()) if not df.empty else False
    return s, info


def history(db, sku, freq, zero_fill=True):
    s, info = series_for(db, sku, freq, zero_fill)
    y = s.values
    m = FREQS[freq]["m"]
    meta = db.query("SELECT MAX(product) AS p, MAX(category) AS c FROM sales WHERE sku = ?", (sku,))[0]
    return _clean({
        "sku": sku, "produto": meta["p"], "categoria": meta["c"],
        "labels": period_labels(s.index, freq), "valores": y, "info": info,
        "tendencia": cl.trend_test(y),
        "forca_sazonal": cl.seasonality_strength(y, m),
        "padrao_demanda": cl.sbc(y),
        "estatisticas": {"media": float(np.mean(y)) if len(y) else None,
                         "desvio": float(np.std(y, ddof=1)) if len(y) > 1 else None,
                         "cv": cl.xyz_cv(y), "total": float(np.sum(y)),
                         "zeros": int(np.sum(y == 0))},
    })


def overview(db, freq="M"):
    df = sales_df(db)
    if df.empty:
        return {"vazio": True}
    a, b = data_bounds(db)
    s, info = build_series(df, freq, True, a, b)
    df["receita"] = df["quantity"] * df["unit_price"].fillna(0)
    by_cat = (df.groupby("category").agg(quantidade=("quantity", "sum"),
                                         receita=("receita", "sum")).reset_index()
              .sort_values("quantidade", ascending=False))
    return _clean({
        "vazio": False, "labels": period_labels(s.index, freq), "valores": s.values,
        "info": info, "tendencia_total": cl.trend_test(s.values),
        "categorias": by_cat.to_dict("records"),
        "kpis": {"skus": int(df["sku"].nunique()), "quantidade": float(df["quantity"].sum()),
                 "receita": float(df["receita"].sum()), "inicio": a, "fim": b},
    })


def trends_table(db, freq="M"):
    out = []
    a, b = data_bounds(db)
    df_all = sales_df(db)
    for sku, g in df_all.groupby("sku"):
        try:
            s, _ = build_series(g, freq, True, a, b)
        except ValueError:
            continue
        t = cl.trend_test(s.values)
        out.append({"sku": sku, "produto": g["product"].iloc[0], "n": len(s),
                    "direcao": t.get("direcao", "—"), "p_valor": t.get("p_valor"),
                    "inclinacao_relativa": t.get("inclinacao_relativa")})
    return _clean(out)


def abcxyz(db, freq="M", last_n: int = 12):
    df = sales_df(db)
    if df.empty:
        return {"linhas": []}
    a, b = data_bounds(db)
    has_price = df["unit_price"].notna().any()
    df["valor"] = df["quantity"] * df["unit_price"].fillna(0) if has_price else df["quantity"]
    rows = []
    for sku, g in df.groupby("sku"):
        try:
            s, _ = build_series(g, freq, True, a, b)
        except ValueError:
            continue
        y = s.values[-last_n:]
        cv = cl.xyz_cv(y)
        rows.append({"sku": sku, "produto": g["product"].iloc[0],
                     "categoria": g["category"].iloc[0], "periodos": len(y), "cv": cv,
                     "xyz": cl.xyz_class(cv), **cl.sbc(y)})
    # janela do ABC = mesmo intervalo de datas dos últimos N períodos completos
    s_all, _ = build_series(df, freq, True, a, b)
    w0 = s_all.index[-last_n:][0].start_time
    w1 = s_all.index[-1].end_time
    d = pd.to_datetime(df["date"])
    win = df[(d >= w0) & (d <= w1)]
    abc = cl.abc(win.groupby("sku")["valor"].sum())
    t = pd.DataFrame(rows).set_index("sku").join(abc)
    t["valor"] = t["valor"].fillna(0.0)
    t["abc"] = t["abc"].fillna("C")          # sem vendas na janela
    t["classe"] = t["abc"] + t["xyz"]
    t = t.sort_values("valor", ascending=False).reset_index()
    matrix = t.groupby(["abc", "xyz"]).size().unstack(fill_value=0)
    return _clean({"base_abc": "receita" if has_price else "quantidade",
                   "janela": [w0.strftime("%d/%m/%Y"), w1.strftime("%d/%m/%Y")],
                   "periodos": last_n,
                   "linhas": t.to_dict("records"),
                   "matriz": {f"{i}{j}": int(matrix.loc[i, j]) if (i in matrix.index and j in matrix.columns) else 0
                              for i in "ABC" for j in "XYZ"},
                   "limites": {"abc": cl.ABC_LIMITS, "xyz": cl.XYZ_LIMITS,
                               "adi": cl.ADI_CUT, "cv2": cl.CV2_CUT}})


def forecast(db, sku, freq="M", horizon=6, models=None, criterion="wape",
             n_origins=6, zero_fill=True, chosen=None):
    s, info = series_for(db, sku, freq, zero_fill)
    y = s.values
    m = FREQS[freq]["m"]
    models = [k for k in (models or list(MODELS)) if k in MODELS]
    if "naive" not in models:
        models = ["naive"] + models  # referência obrigatória para o FVA
    bt = backtest(y, horizon, m, models, n_origins=n_origins)
    best = chosen or select_best(bt, criterion) or "naive"
    fits = {}
    for k in models:
        try:
            r = run_model(k, y, horizon, m)
        except ModelNotApplicable as e:
            fits[k] = {"erro": str(e)}
            continue
        lo80, hi80 = interval(r.forecast, r.var_h, 0.80)
        lo95, hi95 = interval(r.forecast, r.var_h, 0.95)
        fits[k] = {"nome": MODELS[k][0], "previsao": np.maximum(r.forecast, 0),
                   "previsao_bruta": r.forecast,
                   "lo80": lo80, "hi80": hi80, "lo95": lo95, "hi95": hi95,
                   "ajustado": r.fitted, "parametros": r.params, "sigma": np.sqrt(r.sigma2),
                   "aicc": r.aicc, "intervalo": r.interval_method}
    if best not in fits or "erro" in fits[best]:
        best = "naive"
    payload = _clean({
        "sku": sku, "frequencia": freq, "horizonte": horizon, "criterio": criterion,
        "labels": period_labels(s.index, freq),
        "labels_futuro": future_labels(s.index[-1], horizon, freq),
        "valores": y, "info": info, "backtest": bt, "modelo_escolhido": best,
        "modelos": fits, "nomes": {k: v[0] for k, v in MODELS.items()},
        "aviso_cold_start": len(y) < 2 * m and freq == "M",
    })
    rid = db.next_id("forecast_runs")
    db.execute("INSERT INTO forecast_runs (id, created_at, sku, freq, horizon, model, payload)"
               " VALUES (?, ?, ?, ?, ?, ?, ?)",
               (rid, datetime.now().isoformat(timespec="seconds"), sku, freq, horizon, best,
                json.dumps(payload, ensure_ascii=False)))
    payload["run_id"] = rid
    return payload


def get_run(db, rid: int):
    r = db.query("SELECT payload FROM forecast_runs WHERE id = ?", (rid,))
    if not r:
        raise KeyError(rid)
    p = json.loads(r[0]["payload"]); p["run_id"] = rid
    return p


def inventory_plan(db, rid: int, model: str | None, params: dict):
    run = get_run(db, rid)
    model = model or run["modelo_escolhido"]
    fit = run["modelos"][model]
    bt = run["backtest"]["resultados"].get(model, {})
    sigma = bt.get("rmse")
    sigma_src = "RMSE do backtesting (fora da amostra)"
    if sigma is None:
        sigma = fit["sigma"]; sigma_src = "σ dos resíduos dentro da amostra (backtesting indisponível)"
    res = inventory.plan(fit["previsao"], sigma, run["frequencia"], **params)
    res["fonte_sigma"] = sigma_src
    res["modelo"] = model
    return _clean(res)
