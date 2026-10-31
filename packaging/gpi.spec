# -*- mode: python ; coding: utf-8 -*-
# Build one-folder do GPI para Windows x64:  pyinstaller --noconfirm --clean packaging/gpi.spec
import os
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
import sys
sys.path.insert(0, os.path.join(ROOT, "backend"))      # para collect_submodules("gpi") enxergar o pacote

hidden = collect_submodules("gpi") + collect_submodules("uvicorn") + [
    "gpi.products.api", "gpi.products.trends", "gpi.products.catalog", "gpi.products.intent",
    "gpi.products.nlp", "gpi.products.lexicon", "gpi.products.labels", "gpi.connectors.search",
    "sklearn.ensemble._hist_gradient_boosting.gradient_boosting",
    "sklearn.cluster._hdbscan.hdbscan",
    "scipy.special.cython_special",
    "openpyxl",
]
binaries, datas = [], [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "config"), "config"),
    (os.path.join(ROOT, "docs"), "docs"),
]
# Modelos opcionais: incluídos somente se instalados no ambiente de build
for opt in ("lightgbm", "xgboost"):
    try:
        __import__(opt)
        binaries += collect_dynamic_libs(opt)
        datas += collect_data_files(opt)
        hidden += collect_submodules(opt, filter=lambda n: ".testing" not in n and ".tests" not in n)
    except ImportError:
        pass
try:
    import statsmodels  # noqa: F401
    hidden += ["statsmodels.tsa.statespace.sarimax"]
except ImportError:
    pass

assert "gpi.products.api" in collect_submodules("gpi"), "pacote gpi não encontrado pelo PyInstaller"

a = Analysis(
    [os.path.join(ROOT, "packaging", "gpi_entry.py")],
    pathex=[os.path.join(ROOT, "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "IPython", "notebook", "pytest", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="GPI",
    console=False,          # aplicativo de janela: mostra a janela de controle "GPI em execução"
    upx=False,              # UPX costuma gerar falsos positivos em antivírus corporativos
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GPI")
