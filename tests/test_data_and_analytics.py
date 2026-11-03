"""Importação, séries, classificações e estoque."""
import io
import math

import numpy as np
import pandas as pd
import pytest
from openpyxl import Workbook

from gpi.analytics import classification as cl
from gpi.db import Database
from gpi.importer import ImportErrorGPI, import_file, parse_number
from gpi.series import build_series
from gpi.supply_chain.inventory import plan


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.sqlite")
    yield d
    d.close()


@pytest.mark.parametrize("raw,exp", [("1.234,56", 1234.56), ("1,234.56", 1234.56), ("R$ 10,00", 10.0),
                                     ("7", 7.0), (3, 3.0), ("abc", float("nan"))])
def test_parse_number(raw, exp):
    v = parse_number(raw)
    assert (math.isnan(v) and math.isnan(exp)) or v == pytest.approx(exp)


def test_import_csv_validates_and_rejects(db):
    csv = ("Data;Código;Descrição;Qtd;Preço\n"
           "05/02/2025;A1;Item A;3;10,50\n"
           "2025-02-06;A1;Item A;2;10,50\n"
           "32/13/2025;A1;Item A;1;10\n"
           "07/02/2025;A1;Item A;-4;10\n"
           "08/02/2025;;;5;1\n").encode("utf-8")
    r = import_file(db, "v.csv", csv)
    assert r["linhas_validas"] == 2 and r["linhas_rejeitadas"] == 3
    motivos = " ".join(x["motivo"] for x in r["rejeicoes"])
    assert "data inválida" in motivos and "negativa" in motivos and "vazio" in motivos
    rows = db.query("SELECT date, quantity, unit_price FROM sales ORDER BY date")
    assert rows[0] == {"date": "2025-02-05", "quantity": 3.0, "unit_price": 10.5}
    with pytest.raises(ImportErrorGPI):
        import_file(db, "v.csv", csv)       # duplicado


def test_import_xlsx(db):
    wb = Workbook(); ws = wb.active
    ws.append(["data", "sku", "quantidade"])
    ws.append([pd.Timestamp("2025-03-01").to_pydatetime(), "X", 4])
    ws.append(["02/03/2025", "X", 6])
    buf = io.BytesIO(); wb.save(buf)
    r = import_file(db, "p.xlsx", buf.getvalue())
    assert r["linhas_validas"] == 2
    assert db.query("SELECT SUM(quantity) AS s FROM sales")[0]["s"] == 10


def test_missing_columns_message(db):
    with pytest.raises(ImportErrorGPI, match="quantity"):
        import_file(db, "x.csv", b"data;sku\n01/01/2025;A\n")


def test_persistence_after_reopen(tmp_path):
    d = Database(tmp_path / "p.sqlite")
    import_file(d, "a.csv", b"data;sku;quantidade\n01/01/2025;A;1\n")
    d.close()
    d2 = Database(tmp_path / "p.sqlite")
    assert d2.query("SELECT COUNT(*) AS n FROM sales")[0]["n"] == 1
    assert d2.schema_version() == 5
    d2.close()


# ----------------------------------------------------------------- séries
def _df(rows):
    return pd.DataFrame(rows, columns=["date", "quantity"])


def test_series_zero_fill_and_incomplete_periods():
    df = _df([("2025-01-15", 5), ("2025-02-10", 3), ("2025-04-01", 2), ("2025-05-10", 9)])
    s, info = build_series(df, "M", True, "2025-01-15", "2025-05-10")
    # jan (dados desde 15/01) e mai (até 10/05) descartados; mar = 0
    assert list(s.values) == [3.0, 0.0, 2.0]
    assert len(info["descartados"]) == 2 and info["periodos_sem_registro"] == 1


def test_series_refuses_gaps_without_premise():
    df = _df([("2025-01-01", 5), ("2025-03-01", 3), ("2025-04-30", 1)])
    with pytest.raises(ValueError):
        build_series(df, "M", zero_fill=False)


# ----------------------------------------------------------------- classificações
def test_abc_boundaries():
    t = cl.abc(pd.Series({"a": 70.0, "b": 15.0, "c": 10.0, "d": 5.0}))
    assert list(t["abc"]) == ["A", "A", "B", "C"]   # b começa em 70% (<80%) → A


def test_xyz_and_sbc():
    assert cl.xyz_class(cl.xyz_cv(np.array([10, 11, 9, 10.0]))) == "X"
    assert cl.xyz_class(cl.xyz_cv(np.array([0, 30, 0, 1.0]))) == "Z"
    assert cl.sbc(np.array([5, 6, 5, 6, 5.0]))["padrao"] == "suave"
    assert cl.sbc(np.array([0, 0, 5, 0, 0, 5, 0, 0, 6.0]))["padrao"] == "intermitente"
    assert cl.sbc(np.array([0, 0, 1, 0, 0, 40, 0, 0, 2.0]))["padrao"] == "irregular (lumpy)"


def test_trend_test_detects_and_does_not_hallucinate():
    rng = np.random.default_rng(5)
    up = cl.trend_test(np.arange(30) * 2 + rng.normal(0, 3, 30))
    assert up["significativa"] and up["direcao"] == "crescimento"
    assert up["ic95"][0] <= up["inclinacao"] <= up["ic95"][1]
    false_pos = sum(cl.trend_test(np.random.default_rng(s).normal(50, 5, 30))["significativa"]
                    for s in range(200))
    assert false_pos / 200 < 0.10      # nível nominal 5%


def test_seasonality_strength():
    t = np.arange(48)
    strong = 100 + 20 * np.sin(2 * np.pi * t / 12) + np.random.default_rng(1).normal(0, 1, 48)
    noise = np.random.default_rng(2).normal(100, 5, 48)
    st = cl.seasonality_strength(strong, 12)
    assert st["fs"] > 0.9 and st["significativa"]
    false_pos = sum(cl.seasonality_strength(np.random.default_rng(s).normal(100, 5, 36), 12)["significativa"]
                    for s in range(200))
    assert false_pos / 200 < 0.10      # ruído puro raramente é declarado sazonal


# ----------------------------------------------------------------- estoque
def test_inventory_formulas():
    f = np.full(12, 100.0)
    r = plan(f, sigma_d=20, freq="M", lead_time_days=30.4375 * 2, review_days=30.4375,
             service_level=0.95, on_hand=150, in_transit=50, moq=0, order_multiple=10)
    z = 1.6448536269514722
    assert r["estoque_seguranca"] == pytest.approx(z * 20 * math.sqrt(2))
    assert r["ponto_reposicao"] == pytest.approx(200 + z * 20 * math.sqrt(2))
    S = 300 + z * 20 * math.sqrt(3)
    assert r["nivel_alvo_S"] == pytest.approx(S)
    assert r["qtd_sugerida"] == math.ceil((S - 200) / 10) * 10
    assert r["deve_pedir_agora"] is True


def test_inventory_moq_and_lead_time_variability():
    f = np.full(12, 10.0)
    r = plan(f, 2, "M", 30.4375, 0, 0.9, on_hand=0, in_transit=0, moq=100,
             lead_time_sd_days=30.4375)
    assert r["efeito_moq"] and r["qtd_sugerida"] == 100
    assert r["sigma_lead_time"] == pytest.approx(math.sqrt(1 * 4 + 100 * 1))


def test_eoq():
    r = plan(np.full(12, 100.0), 10, "M", 30, 30, 0.95, 0, 0, unit_cost=50,
             order_cost=200, holding_rate_year=0.2)
    D = 100 * 365.25 / 30.4375
    assert r["eoq"] == pytest.approx(math.sqrt(2 * D * 200 / (0.2 * 50)))
