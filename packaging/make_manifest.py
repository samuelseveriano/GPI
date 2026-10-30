"""Copia documentação para a pasta do build e gera manifest.json (SHA-256 de cada arquivo),
usado pelo GPI.exe para verificar a integridade ao abrir."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from gpi.main import build_manifest  # noqa: E402


def main(dist: str):
    d = Path(dist)
    for f in ("README.md", "MANUAL.md", "LEIA-ME.txt"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, d / f)
    m = build_manifest(d)
    (d / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    total = sum(v["size"] for v in m["files"].values())
    print(f"manifest.json: {len(m['files'])} arquivos, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "dist" / "GPI"))
