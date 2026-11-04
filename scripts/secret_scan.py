"""Varredura de segredos do GPI (complementa o Gitleaks executado no GitHub Actions).

Uso:
  python scripts/secret_scan.py               # arquivos versionados (árvore atual)
  python scripts/secret_scan.py --historico   # todo o histórico (git log -p --all)
  python scripts/secret_scan.py --staged      # só o que está preparado para commit (pre-commit)

Nunca imprime o valor encontrado: só o tipo, o arquivo, a linha/commit e uma impressão
digital curta (SHA-256 truncado) para acompanhar a correção sem reexpor o segredo.
Também bloqueia arquivos que não devem ser versionados (bancos SQLite, relatórios gerados,
pacotes de modelo, chaves de assinatura).
"""
from __future__ import annotations

import hashlib
import math
import re
import subprocess
import sys
from collections import Counter

REGRAS = [
    ("Chave privada (PEM)", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("Chave de API Google", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Client secret OAuth Google", re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}")),
    ("Refresh token Google", re.compile(r"1//0[0-9A-Za-z_\-]{40,}")),
    ("Token GitHub", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{36,}\b|github_pat_[0-9A-Za-z_]{60,}")),
    ("Chave de acesso AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Token Slack", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("Token de acesso Meta/Facebook", re.compile(r"\bEAA[A-Za-z0-9]{60,}")),
    ("Token Mercado Livre", re.compile(r"\b(?:APP_USR|TG)-\d{6,}-[0-9]{6}-[0-9a-f]{32}-\d{5,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("Certificado de assinatura (PFX/P12 em base64)", re.compile(r"MII[A-Za-z0-9+/]{200,}")),
]
ATRIB = re.compile(
    r"(?i)\b(client_secret|secret|password|senha|api_key|apikey|access_token|refresh_token|developer_token|token)"
    r"\b\s*[\"']?\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']")
# Valores de teste claramente fictícios usados nos testes automatizados.
FICTICIO = re.compile(r"(?i)(teste|segredo|fake|dummy|exemplo|ABCDEF12|ABCDEFGH|0123456789|AUTHCODE12|VERIF12|xxxx)")
IGNORAR_VALOR = re.compile(r"(?i)^(x+|\*+|\.+|test|fake|dummy|exemplo|example|placeholder|segredo|secret|redacted|<.*>|\$\{.*\}|\{\{.*\}\})")
PROIBIDOS = re.compile(
    r"(?i)(\.sqlite3?$|\.db$|\.gguf$|\.pfx$|\.p12$|\.pem$|\.key$|(^|/)\.env$|credentials\.json$|token\.json$)")
PERMITIDOS = re.compile(r"(?i)^(exemplos/|tests/fixtures/|backend/gpi/compliance/kb/)")


def entropia(s: str) -> float:
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values())


def fp(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()[:10]


def analisar_linha(linha: str):
    for nome, rx in REGRAS:
        m = rx.search(linha)
        if m and not FICTICIO.search(m.group(0)):
            yield nome, m.group(0)
    m = ATRIB.search(linha)
    if m:
        valor = m.group(2)
        if not IGNORAR_VALOR.match(valor) and not FICTICIO.search(valor) and entropia(valor) >= 3.5 and not valor.startswith(("os.", "self.", "cfg", "env")):
            yield f"Atribuição de segredo ({m.group(1).lower()})", valor


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def varrer_texto(texto: str, origem: str, achados: list):
    commit, arquivo, n = "", "", 0
    for linha in texto.splitlines():
        if linha.startswith("commit ") and len(linha) == 47:
            commit = linha[7:15]
            continue
        if linha.startswith("+++ b/"):
            arquivo = linha[6:]
            continue
        if linha.startswith("@@"):
            m = re.search(r"\+(\d+)", linha)
            n = int(m.group(1)) - 1 if m else 0
            continue
        if origem == "patch":
            if not linha.startswith("+") or linha.startswith("+++"):
                if not linha.startswith("-"):
                    n += 1
                continue
            n += 1
            corpo = linha[1:]
        else:
            corpo = linha
        if arquivo.startswith("scripts/secret_scan.py") or arquivo.startswith("tests/test_v07_security"):
            continue
        for tipo, valor in analisar_linha(corpo):
            achados.append((tipo, commit, arquivo, n, fp(valor)))


def main(argv: list[str]) -> int:
    achados: list = []
    arquivos_proibidos: list[str] = []
    if "--historico" in argv:
        varrer_texto(git("log", "-p", "--all", "--full-history", "--no-color", "-U0"), "patch", achados)
        nomes = set(git("log", "--all", "--name-only", "--pretty=format:").split())
    elif "--staged" in argv:
        varrer_texto(git("diff", "--cached", "--no-color", "-U0"), "patch", achados)
        nomes = set(git("diff", "--cached", "--name-only").split())
    else:
        nomes = set(git("ls-files").splitlines())
        for nome in sorted(nomes):
            if nome.startswith("scripts/secret_scan.py") or nome.startswith("tests/test_v07_security"):
                continue
            try:
                with open(nome, encoding="utf-8") as f:
                    for i, linha in enumerate(f, 1):
                        for tipo, valor in analisar_linha(linha):
                            achados.append((tipo, "", nome, i, fp(valor)))
            except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
                continue
    arquivos_proibidos = sorted(n for n in nomes if PROIBIDOS.search(n) and not PERMITIDOS.match(n))
    for tipo, commit, arquivo, linha, impressao in achados:
        onde = f"{arquivo}:{linha}" + (f" (commit {commit})" if commit else "")
        print(f"[SEGREDO] {tipo} em {onde} — impressão {impressao} (valor omitido)")
    for nome in arquivos_proibidos:
        print(f"[ARQUIVO] tipo que não deve ser versionado: {nome}")
    print(f"Resultado: {len(achados)} possíveis segredos, {len(arquivos_proibidos)} arquivos proibidos.")
    return 1 if achados or arquivos_proibidos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
