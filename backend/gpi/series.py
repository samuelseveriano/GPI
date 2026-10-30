"""
Construção de séries temporais regulares a partir das vendas registradas.

Regras (todas exibidas ao usuário junto com o resultado):
  * Frequência semanal (semana ISO, segunda a domingo) ou mensal.
  * Períodos sem nenhum registro entre a primeira e a última venda do SKU são
    tratados como 0 vendas SOMENTE se o usuário confirmar essa premissa
    (padrão: sim, pois em dados de vendas a ausência de linha normalmente
    significa ausência de venda). Caso contrário, a série é recusada se tiver
    lacunas — nunca se interpola histórico.
  * O último período é descartado quando está incompleto (a data máxima do
    arquivo é anterior ao fim do período), pois subestimaria a demanda.
    O primeiro período também é descartado se incompleto.
"""
from __future__ import annotations

import pandas as pd

FREQS = {"W": {"rule": "W-SUN", "m": 52, "label": "semanal"},
         "M": {"rule": "M", "m": 12, "label": "mensal"}}


def to_periods(dates: pd.Series, freq: str) -> pd.PeriodIndex:
    return pd.to_datetime(dates).dt.to_period(FREQS[freq]["rule"])


def build_series(df: pd.DataFrame, freq: str = "M", zero_fill: bool = True,
                 data_start: str | None = None, data_end: str | None = None,
                 drop_incomplete: bool = True):
    """df com colunas date (str ISO) e quantity. Retorna (Series, info)."""
    if df.empty:
        raise ValueError("sem dados para o filtro selecionado")
    d = pd.to_datetime(df["date"])
    per = d.dt.to_period(FREQS[freq]["rule"])
    agg = df.assign(p=per).groupby("p")["quantity"].sum().sort_index()
    full = pd.period_range(agg.index.min(), agg.index.max(), freq=agg.index.freq)
    missing = full.difference(agg.index)
    info = {"frequencia": FREQS[freq]["label"], "m": FREQS[freq]["m"],
            "periodos_sem_registro": len(missing), "tratamento_lacunas": None,
            "descartados": []}
    if len(missing):
        if not zero_fill:
            raise ValueError(
                f"a série tem {len(missing)} período(s) sem registro e a premissa "
                "'período sem registro = 0 vendas' está desativada")
        info["tratamento_lacunas"] = "períodos sem registro considerados como 0 vendas"
    s = agg.reindex(full, fill_value=0.0)

    # Limites do arquivo (globais) determinam se primeiro/último período estão completos
    gmin = pd.Timestamp(data_start) if data_start else d.min()
    gmax = pd.Timestamp(data_end) if data_end else d.max()
    if drop_incomplete and len(s) > 2:
        last = s.index[-1]
        if gmax.normalize() < last.end_time.normalize():
            info["descartados"].append(f"{last} (incompleto: dados até {gmax:%d/%m/%Y})")
            s = s.iloc[:-1]
        first = s.index[0]
        if gmin.normalize() > first.start_time.normalize():
            info["descartados"].append(f"{first} (incompleto: dados desde {gmin:%d/%m/%Y})")
            s = s.iloc[1:]
    info["n"] = len(s)
    return s.astype(float), info


def period_labels(idx: pd.PeriodIndex, freq: str) -> list[str]:
    if freq == "M":
        return [p.strftime("%Y-%m") for p in idx]
    return [p.start_time.strftime("%Y-%m-%d") for p in idx]


def future_labels(last: pd.Period, h: int, freq: str) -> list[str]:
    idx = pd.period_range(last + 1, periods=h, freq=last.freq)
    return period_labels(idx, freq)
