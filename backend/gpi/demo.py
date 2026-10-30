"""
Gerador de DADOS DEMONSTRATIVOS SINTÉTICOS.

Servem apenas para conhecer o sistema. São gravados com is_demo = 1 e a origem
"DADOS DEMONSTRATIVOS (sintéticos)", aparecem com selo na interface e podem
ser removidos com um clique. Não representam nenhum mercado real.
"""
from __future__ import annotations

import io
import numpy as np
import pandas as pd

DEMO_SOURCE = "DADOS DEMONSTRATIVOS (sintéticos)"

# (sku, produto, categoria, preço, base diária, tendência anual, amplitude sazonal, pico (mês), prob. venda/dia)
PRODUCTS = [
    ("DEMO-001", "Fone Bluetooth (demo)", "Eletrônicos", 89.9, 14, 0.35, 0.25, 11, 1.0),
    ("DEMO-002", "Carregador USB-C (demo)", "Eletrônicos", 49.9, 22, 0.10, 0.10, 12, 1.0),
    ("DEMO-003", "Ventilador portátil (demo)", "Casa", 119.0, 6, 0.05, 0.85, 1, 1.0),
    ("DEMO-004", "Organizador de gaveta (demo)", "Casa", 29.9, 9, -0.30, 0.05, 6, 1.0),
    ("DEMO-005", "Luminária LED (demo)", "Casa", 75.0, 4, 0.00, 0.15, 12, 0.6),
    ("DEMO-006", "Garrafa térmica (demo)", "Esporte", 64.9, 7, 0.20, 0.40, 1, 1.0),
    ("DEMO-007", "Faixa elástica (demo)", "Esporte", 39.9, 3, 0.15, 0.30, 1, 0.5),
    ("DEMO-008", "Peça de reposição X (demo)", "Ferramentas", 210.0, 2, 0.00, 0.00, 1, 0.08),
    ("DEMO-009", "Kit chaves precisão (demo)", "Ferramentas", 59.9, 3, 0.05, 0.10, 12, 0.35),
    ("DEMO-010", "Capa de celular (demo)", "Eletrônicos", 24.9, 30, -0.15, 0.20, 12, 1.0),
]


def make_demo_csv(start="2023-01-01", end="2025-12-31", seed=42) -> bytes:
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    t_years = (days - days[0]).days / 365.25
    rows = []
    for sku, name, cat, price, base, tr, amp, peak, p_sale in PRODUCTS:
        seas = 1 + amp * np.cos(2 * np.pi * (days.month - peak) / 12)
        lam = base * (1 + tr) ** t_years * seas
        if p_sale < 1:  # demanda intermitente: ocorre com prob. p e tamanho maior
            occ = rng.random(len(days)) < p_sale
            qty = np.where(occ, rng.poisson(lam / max(p_sale, 1e-9) * 0.2) + 1, 0)
        else:
            qty = rng.poisson(lam)
        for d, q in zip(days, qty):
            if q > 0:
                rows.append((d.strftime("%d/%m/%Y"), sku, name, cat, int(q),
                             f"{price:.2f}".replace(".", ",")))
    df = pd.DataFrame(rows, columns=["Data", "SKU", "Produto", "Categoria",
                                     "Quantidade", "Preço unitário"])
    buf = io.StringIO()
    df.to_csv(buf, sep=";", index=False)
    return buf.getvalue().encode("utf-8")
