"""Classifica as licenças das dependências (saída do pip-licenses em markdown).

Sinaliza licenças copyleft fortes (GPL/AGPL/SSPL) e desconhecidas para revisão; não falha o build,
porque a decisão de licenciamento cabe ao responsável pelo projeto.
"""
import re
import sys

ATENCAO = re.compile(r"(?i)\b(AGPL|SSPL|GPL(?!.*LGPL)|GNU General Public)")
DESCONHECIDA = re.compile(r"(?i)\bUNKNOWN\b")


def main(path: str) -> int:
    linhas = [l for l in open(path, encoding="utf-8") if l.startswith("|") and not l.startswith("|--")][1:]
    alertas = []
    for l in linhas:
        cols = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cols) < 3:
            continue
        nome, versao, lic = cols[0], cols[1], cols[2]
        if ATENCAO.search(lic) or DESCONHECIDA.search(lic):
            alertas.append(f"| {nome} | {versao} | {lic} |")
    print(f"### Licenças: {len(linhas)} pacotes; {len(alertas)} para revisão")
    if alertas:
        print("| Pacote | Versão | Licença |\n|---|---|---|")
        print("\n".join(alertas))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
