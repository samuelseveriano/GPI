"""Monta o GPI-Local-AI-Model-Pack (executado no GitHub Actions, nunca pelo GPI em uso).

Componentes oficiais, redistribuíveis e com procedência conferida:
* llama.cpp (MIT) — release oficial do repositório ggml-org/llama.cpp; o SHA-256 do ZIP baixado é comparado com o
  "digest" que o próprio GitHub registra para o asset da release.
* Modelo GGUF (padrão: Qwen/Qwen3-0.6B-GGUF, Apache-2.0) — o SHA-256 do arquivo é comparado com o oid LFS publicado
  pelo Hugging Face para a revisão (commit) fixada no manifesto; a licença é lida dos metadados do repositório.
Gera a pasta do pacote com gpi-model-pack.json (licença, origem, revisão e SHA-256 de cada arquivo) e as licenças.

Uso: python scripts/build_model_pack.py --saida pack/ia --llama-tag v0.8.0 --modelo Qwen/Qwen3-0.6B-GGUF --arquivo Qwen3-0.6B-Q8_0.gguf
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "GPI-build (GitHub Actions)"}
ALLOWED_LICENSES = {"mit", "apache-2.0", "apache 2.0", "bsd-3-clause"}


def get(url, headers=None, binary=False):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=600) as r:      # noqa: S310 — URLs fixas de origem oficial
        data = r.read()
    return data if binary else json.loads(data)


def download(url, dest: Path, expect_sha: str | None):
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=1800) as r, open(dest, "wb") as f:   # noqa: S310
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            h.update(b)
            f.write(b)
    got = h.hexdigest()
    if expect_sha and got != expect_sha.lower():
        dest.unlink(missing_ok=True)
        sys.exit(f"SHA-256 divergente para {url}: esperado {expect_sha}, obtido {got}")
    return got


def llama(tag: str, out: Path) -> tuple[list[dict], dict]:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    hdr = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})}
    rel = get(f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{tag}", hdr)
    pats = [r"bin-win-cpu-x64\.zip$", r"win.*cpu.*x64.*\.zip$", r"win.*avx2.*x64.*\.zip$"]
    asset = None
    for p in pats:
        asset = next((a for a in rel["assets"] if re.search(p, a["name"])), None)
        if asset:
            break
    if not asset:
        sys.exit("asset Windows CPU x64 não encontrado na release " + tag + ": " + ", ".join(a["name"] for a in rel["assets"]))
    digest = (asset.get("digest") or "").removeprefix("sha256:")
    tmp = out / "_llama.zip"
    got = download(asset["browser_download_url"], tmp, digest or None)
    files = []
    with zipfile.ZipFile(tmp) as z:
        names = z.namelist()
        keep = [n for n in names if Path(n).name == "llama-server.exe" or n.lower().endswith(".dll")]
        if not any(Path(n).name == "llama-server.exe" for n in keep):
            sys.exit("llama-server.exe ausente do asset")
        for n in keep:
            base = Path(n).name
            data = z.read(n)
            (out / base).write_bytes(data)
            files.append({"nome": base, "papel": "servidor" if base == "llama-server.exe" else "biblioteca", "licenca": "MIT",
                          "origem": f"https://github.com/ggml-org/llama.cpp/releases/tag/{tag} ({asset['name']})",
                          "sha256": hashlib.sha256(data).hexdigest(), "tamanho": len(data)})
    tmp.unlink()
    lic = get(f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{tag}/LICENSE", binary=True)
    (out / "LICENSE-llama.cpp.txt").write_bytes(lic)
    files.append({"nome": "LICENSE-llama.cpp.txt", "papel": "licenca", "licenca": "MIT", "origem": "llama.cpp " + tag,
                  "sha256": hashlib.sha256(lic).hexdigest(), "tamanho": len(lic)})
    return files, {"llama_cpp_tag": tag, "llama_cpp_asset": asset["name"], "llama_cpp_asset_sha256": got,
                   "llama_cpp_digest_github": digest or "não informado pelo GitHub"}


def model(repo: str, filename: str, out: Path) -> tuple[list[dict], dict]:
    meta = get(f"https://huggingface.co/api/models/{repo}?blobs=true")
    rev = meta["sha"]
    lic = str((meta.get("cardData") or {}).get("license") or "").lower()
    if lic not in ALLOWED_LICENSES:
        sys.exit(f"licença do modelo não permitida ou ausente: {lic!r}")
    sib = next((s for s in meta.get("siblings", []) if s["rfilename"] == filename), None)
    if not sib or not (sib.get("lfs") or {}).get("sha256"):
        sys.exit("arquivo GGUF sem SHA-256 publicado pelo Hugging Face")
    sha = sib["lfs"]["sha256"]
    got = download(f"https://huggingface.co/{repo}/resolve/{rev}/{filename}", out / filename, sha)
    files = [{"nome": filename, "papel": "modelo", "licenca": lic, "origem": f"https://huggingface.co/{repo} (revisão {rev})",
              "sha256": got, "tamanho": (out / filename).stat().st_size}]
    try:
        readme = get(f"https://huggingface.co/{repo}/resolve/{rev}/LICENSE", binary=True)
        name = f"LICENSE-{repo.split('/')[-1]}.txt"
        (out / name).write_bytes(readme)
        files.append({"nome": name, "papel": "licenca", "licenca": lic, "origem": repo, "sha256": hashlib.sha256(readme).hexdigest(),
                      "tamanho": len(readme)})
    except Exception:  # noqa: BLE001 — alguns repositórios não têm LICENSE separado; a licença está nos metadados
        pass
    return files, {"modelo_repo": repo, "modelo_revisao": rev, "modelo_licenca": lic, "modelo_arquivo": filename}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True)
    ap.add_argument("--llama-tag", required=True)
    ap.add_argument("--modelo", default="Qwen/Qwen3-0.6B-GGUF")
    ap.add_argument("--arquivo", default="Qwen3-0.6B-Q8_0.gguf")
    ap.add_argument("--versao", default="0.7")
    a = ap.parse_args(argv)
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    f1, m1 = llama(a.llama_tag, out)
    f2, m2 = model(a.modelo, a.arquivo, out)
    man = {"formato": "gpi-model-pack", "versao": a.versao, **m1, **m2,
           "argumentos_extras": ["--jinja"],
           "observacao": "Pacote opcional da IA local do GPI. Copie esta pasta para 'ia' ao lado do GPI.exe ou para "
                         "%LOCALAPPDATA%\\GPI\\ia. O GPI confere o SHA-256 de cada arquivo antes de executar.",
           "arquivos": f1 + f2}
    (out / "gpi-model-pack.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in man.items() if k != "arquivos"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
