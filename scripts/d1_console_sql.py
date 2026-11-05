"""Gera a versão da migração D1 para colar no Console do painel da Cloudflare (v0.9).

Motivo: o Console remove linhas que começam com "--" (regex /^\\s*--.*/gm, igual ao D1 remoto) e responde
"No SQL statements detected." quando não sobra nada. Se as quebras de linha se perdem ao copiar/colar, a migração
inteira vira UMA linha começando com "--" e é descartada. A versão de console não tem NENHUM comentário (nem no fim
das linhas) e cada instrução termina em ";" — funciona com ou sem quebras de linha.
Uso: python scripts/d1_console_sql.py  (regera cloudflare/ebay-notifications/console/*.sql)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "cloudflare" / "ebay-notifications"


def statements(sql: str) -> list[str]:
    """Instruções sem comentários (respeita aspas simples; o arquivo não usa comentários /* */)."""
    out, cur, i, q = [], [], 0, False
    while i < len(sql):
        ch = sql[i]
        if not q and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = len(sql) if j < 0 else j
            continue
        if ch == "'":
            q = not q
        if ch == ";" and not q:
            s = re.sub(r"\s+", " ", "".join(cur)).strip()
            if s:
                out.append(s + ";")
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = re.sub(r"\s+", " ", "".join(cur)).strip()
    if tail:
        out.append(tail + ";")
    return out


def build() -> dict[str, str]:
    files = {}
    for mig in sorted((ROOT / "migrations").glob("*.sql")):
        files[f"{mig.stem}_console.sql"] = "\n".join(statements(mig.read_text(encoding="utf-8"))) + "\n"
    return files


if __name__ == "__main__":
    for name, txt in build().items():
        (ROOT / "console" / name).write_text(txt, encoding="utf-8", newline="\n")
        print(name, len(txt.splitlines()), "instruções")
