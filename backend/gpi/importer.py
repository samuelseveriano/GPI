"""
Importação de planilhas de vendas (CSV, XLSX) com validação linha a linha.

Colunas reconhecidas (cabeçalho sem acentos/maiúsculas, várias variações):
  data        → obrigatória
  quantidade  → obrigatória (numérica, ≥ 0)
  sku/código ou produto → ao menos uma das duas
  categoria, preço unitário → opcionais
Nada é inventado: linhas inválidas são rejeitadas e listadas com o motivo.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

MAX_BYTES = 50 * 1024 * 1024

ALIASES = {
    "date": ["data", "date", "dia", "data_venda", "data_da_venda", "dt", "periodo", "data_pedido"],
    "sku": ["sku", "codigo", "cod", "cod_produto", "codigo_produto", "id_produto",
            "product_id", "item", "referencia", "ref"],
    "product": ["produto", "descricao", "product", "nome", "nome_produto", "descricao_produto"],
    "category": ["categoria", "category", "grupo", "familia", "departamento", "linha"],
    "quantity": ["quantidade", "qtd", "qtde", "qty", "quantity", "unidades", "vendas",
                 "volume", "qtd_vendida", "quantidade_vendida"],
    "unit_price": ["preco", "preco_unitario", "valor_unitario", "price", "unit_price",
                   "preco_venda", "vl_unitario"],
}


class ImportErrorGPI(Exception):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def map_columns(columns) -> dict:
    normalized = {_norm(c): c for c in columns}
    mapping = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in normalized:
                mapping[field] = normalized[n]
                break
    return mapping


def parse_number(v):
    """Aceita 1234.5, 1.234,5, 1,234.5, 'R$ 10,00'. Retorna NaN se inválido."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).strip())
    if not s or s in "-.,":
        return np.nan
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    if len(content) > MAX_BYTES:
        raise ImportErrorGPI("arquivo maior que 50 MB")
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in ("xlsx", "xlsm"):
        if not content.startswith(b"PK"):
            raise ImportErrorGPI("o conteúdo não é um arquivo XLSX válido")
        return pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=object)
    if ext in ("csv", "txt"):
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str)
    raise ImportErrorGPI("formato não suportado (use .csv ou .xlsx)")


def _parse_dates(col: pd.Series) -> pd.Series:
    """ISO (aaaa-mm-dd) primeiro; depois padrão brasileiro dd/mm/aaaa."""
    s = col.map(lambda v: v.strftime("%Y-%m-%d") if isinstance(v, (datetime, pd.Timestamp))
                else str(v).strip())
    d = pd.to_datetime(s.str[:10], format="%Y-%m-%d", errors="coerce")
    m = d.isna()
    if m.any():
        d[m] = pd.to_datetime(s[m], format="%d/%m/%Y", errors="coerce")
    m = d.isna()
    if m.any():
        d[m] = pd.to_datetime(s[m], dayfirst=True, errors="coerce", format="mixed")
    return d


def validate(raw: pd.DataFrame):
    mapping = map_columns(raw.columns)
    missing = [f for f in ("date", "quantity") if f not in mapping]
    if "sku" not in mapping and "product" not in mapping:
        missing.append("sku ou produto")
    if missing:
        raise ImportErrorGPI(
            "colunas obrigatórias não encontradas: " + ", ".join(missing) +
            f". Colunas lidas: {', '.join(map(str, raw.columns))}")

    df = pd.DataFrame(index=raw.index)
    df["date"] = _parse_dates(raw[mapping["date"]])
    df["quantity"] = raw[mapping["quantity"]].map(parse_number)
    def text(col):  # pandas 3: células vazias chegam como NaN, não como ""
        return raw[col].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v))
                            else str(v).strip())
    prod = text(mapping["product"]) if "product" in mapping else None
    sku = text(mapping["sku"]) if "sku" in mapping else prod
    df["sku"] = sku
    df["product"] = prod if prod is not None else sku
    df["category"] = (text(mapping["category"])
                      if "category" in mapping else "Sem categoria")
    df["unit_price"] = (raw[mapping["unit_price"]].map(parse_number)
                        if "unit_price" in mapping else np.nan)

    reasons = pd.Series("", index=df.index)
    reasons[df["date"].isna()] += "data inválida; "
    reasons[df["quantity"].isna()] += "quantidade não numérica; "
    reasons[df["quantity"] < 0] += "quantidade negativa (devoluções não são aceitas nesta versão); "
    reasons[df["sku"].isin(["", "nan", "None"])] += "SKU/produto vazio; "
    df["product"] = df["product"].where(df["product"] != "", df["sku"])
    reasons[df["unit_price"] < 0] += "preço negativo; "
    bad = reasons != ""
    rejected = [{"linha": int(i) + 2, "motivo": reasons[i].strip("; ")}
                for i in df.index[bad][:200]]
    ok = df[~bad].copy()
    ok["date"] = ok["date"].dt.strftime("%Y-%m-%d")
    ok["category"] = ok["category"].replace({"nan": "Sem categoria", "": "Sem categoria"})
    return ok, int(bad.sum()), rejected, mapping


def import_file(db, filename: str, content: bytes, source: str = "Importação manual",
                is_demo: bool = False) -> dict:
    sha = hashlib.sha256(content).hexdigest()
    if db.query("SELECT id FROM imports WHERE sha256 = ?", (sha,)):
        raise ImportErrorGPI("este arquivo já foi importado (mesmo conteúdo)")
    raw = read_table(filename, content)
    if raw.empty:
        raise ImportErrorGPI("planilha vazia")
    ok, n_bad, rejected, mapping = validate(raw)
    if ok.empty:
        raise ImportErrorGPI("nenhuma linha válida; verifique o relatório de rejeições")
    iid = db.next_id("imports")
    db.execute(
        "INSERT INTO imports (id, filename, sha256, source, is_demo, imported_at, rows_ok,"
        " rows_rejected, columns_map) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (iid, filename, sha, source, int(is_demo), datetime.now().isoformat(timespec="seconds"),
         len(ok), n_bad, json.dumps(mapping, ensure_ascii=False)))
    db.insert_sales(iid, ok)
    return {"import_id": iid, "linhas_validas": len(ok), "linhas_rejeitadas": n_bad,
            "rejeicoes": rejected, "colunas": mapping,
            "periodo": [ok["date"].min(), ok["date"].max()],
            "skus": int(ok["sku"].nunique())}
