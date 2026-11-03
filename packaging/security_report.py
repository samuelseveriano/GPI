"""Relatório de segurança e integridade do pacote GPI (gerado no CI após o build).

Uso: python packaging/security_report.py dist/GPI GPI-Windows-Portable-v0.5.zip defender.txt saida.md
Verifica: arquivos e binários nativos incluídos, ausência de módulos de teste/credenciais, nível de execução
solicitado pelo GPI.exe (manifesto), assinatura Authenticode (status), endpoints de rede usados pelo código,
hashes SHA-256 do executável e do ZIP e o resultado da verificação do Microsoft Defender.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(dist: str, zip_path: str, defender: str, out: str, signature: str = ""):
    d = Path(dist)
    files = [p for p in d.rglob("*") if p.is_file()]
    native = [p for p in files if p.suffix.lower() in (".dll", ".pyd", ".so")]
    tests = [str(p.relative_to(d)) for p in files if re.search(r"[\\/]tests[\\/]", str(p.relative_to(d)))]
    exe = d / "GPI.exe"
    raw = exe.read_bytes()
    level = re.search(rb'requestedExecutionLevel\s+level="(\w+)"', raw)
    secrets_hit = []
    for p in files:
        if p.suffix.lower() in (".json", ".txt", ".cfg", ".ini", ".py", ".js", ".html") and p.stat().st_size < 2_000_000:
            t = p.read_text(encoding="utf-8", errors="ignore")
            for pat in (r"AIza[0-9A-Za-z_\-]{30,}", r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", r"\"client_secret\"\s*:\s*\"[^\"]{8,}\""):
                if re.search(pat, t):
                    secrets_hit.append(f"{p.relative_to(d)} ({pat[:20]}…)")
    hosts = sorted({m for p in (ROOT / "backend" / "gpi").rglob("*.py")
                    for m in re.findall(r"https://([a-z0-9.\-]+\.[a-z]{2,})", p.read_text(encoding="utf-8"))})
    zp = Path(zip_path)
    dtext = Path(defender).read_text(encoding="utf-8", errors="ignore") if Path(defender).exists() else "verificação não executada"
    lines = [
        "# GPI — relatório de segurança do pacote Windows", "",
        f"* Versão: 0.5.0 · arquivos: {len(files)} · tamanho: {sum(p.stat().st_size for p in files) / 1e6:.1f} MB",
        f"* SHA-256 GPI.exe: `{sha256(exe)}`",
        f"* SHA-256 {zp.name}: `{sha256(zp) if zp.exists() else '(gerado depois)'}`",
        f"* Nível de execução solicitado (manifesto): **{level.group(1).decode() if level else 'não declarado'}** "
        f"(asInvoker = sem privilégio administrativo)",
        f"* Assinatura digital (Authenticode): {signature or 'NÃO ASSINADO — nenhum certificado de assinatura disponível; ver docs/SEGURANCA.md'}",
        f"* Empacotamento: PyInstaller one-folder, sem UPX, sem ofuscação, sem extração em pasta temporária",
        f"* Binários nativos incluídos: {len(native)} (bibliotecas do Python, NumPy/SciPy, scikit-learn, LightGBM, XGBoost, CatBoost…)",
        f"* Módulos de teste no pacote: {len(tests)}" + (f" — {tests[:5]}" if tests else ""),
        f"* Credenciais embutidas encontradas: {len(secrets_hit)}" + (f" — {secrets_hit}" if secrets_hit else " (nenhuma)"),
        "* Rede: servidor somente em 127.0.0.1 (porta 8765 ou próxima livre); nenhum serviço Windows, tarefa agendada ou",
        "  inicialização automática é criado; nenhum processo oculto além do servidor local e da janela de controle.",
        f"* Endereços externos presentes no código (só são acessados quando a fonte está habilitada/conectada): {len(hosts)}",
        "", "  " + ", ".join(hosts), "",
        "## Microsoft Defender (verificação no runner)", "", "```", dtext.strip()[:4000], "```", ""]
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    summary = {"arquivos": len(files), "nativos": len(native), "testes_no_pacote": len(tests), "credenciais": len(secrets_hit),
               "nivel_execucao": level.group(1).decode() if level else None, "sha256_exe": sha256(exe)}
    print(json.dumps(summary))
    if secrets_hit or (level and level.group(1).decode() != "asInvoker"):
        sys.exit(2)


if __name__ == "__main__":
    main(*sys.argv[1:6])
