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
    # v0.9.1: busca visual local (formatos verificados pelo conteúdo)
    "PIL.Image", "PIL.ImageOps", "PIL.ImageDraw", "PIL.JpegImagePlugin", "PIL.PngImagePlugin", "PIL.WebPImagePlugin",
    "gpi.suite.api", "gpi.suite.research", "gpi.suite.marketplace", "gpi.suite.visual", "gpi.suite.suppliers",
    "gpi.suite.importx", "gpi.suite.importyeti", "gpi.suite.export", "gpi.suite.monitor", "gpi.suite.capabilities",
]
binaries, datas = [], [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "config"), "config"),
    (os.path.join(ROOT, "docs"), "docs"),
    (os.path.join(ROOT, "backend", "gpi", "reports", "fonts"), os.path.join("gpi", "reports", "fonts")),   # DejaVu (PDF)
    (os.path.join(ROOT, "backend", "gpi", "compliance", "kb"), os.path.join("gpi", "compliance", "kb")),  # v0.7: base regulatória
    (os.path.join(ROOT, "backend", "gpi", "intel", "data"), os.path.join("gpi", "intel", "data")),   # v0.8: conjuntos rotulados (Gate 2)
]
# v0.6: ReportLab (PDF dos relatórios) — módulos carregados dinamicamente e dados (fontes padrão, mapas CID)
hidden += collect_submodules("reportlab", filter=lambda n: ".test" not in n)
datas += collect_data_files("reportlab")
binaries += collect_dynamic_libs("reportlab")
# Bibliotecas opcionais: incluídas somente se instaladas no ambiente de build (sem módulos de teste)
for opt in ("lightgbm", "xgboost", "catboost"):
    try:
        __import__(opt)
        binaries += collect_dynamic_libs(opt)
        datas += collect_data_files(opt)
        hidden += collect_submodules(opt, filter=lambda n: ".testing" not in n and ".tests" not in n)
    except ImportError:
        pass
for opt in ("river", "rapidfuzz", "optuna"):
    try:
        __import__(opt)
        hidden += collect_submodules(opt, filter=lambda n: ".test" not in n and ".benchmarks" not in n and ".datasets" not in n)
        datas += collect_data_files(opt, excludes=["**/tests/**"])
        binaries += collect_dynamic_libs(opt)
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
    # não empacotados: ferramentas de desenvolvimento e bibliotecas pesadas não usadas (embeddings são opcionais e externos)
    excludes=["matplotlib", "IPython", "notebook", "pytest", "torch", "tensorflow", "sentence_transformers", "transformers",
              "plotly", "graphviz", "jupyter", "ipykernel", "black", "pylint"],
    noarchive=False,
)
# Remove pacotes de TESTE das bibliotecas (pastas "tests"); módulos "testing" são mantidos (usados em tempo de execução)
import re as _re
_is_test = lambda name: bool(_re.search(r"(^|[./\\])tests([./\\]|$)", name))
a.pure = [x for x in a.pure if not _is_test(x[0])]
a.datas = [x for x in a.datas if not _is_test(x[0])]
a.binaries = [x for x in a.binaries if not _is_test(x[0])]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="GPI",
    console=False,          # aplicativo de janela: mostra a janela de controle "GPI em execução"
    upx=False,              # UPX costuma gerar falsos positivos em antivírus corporativos
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
    icon=os.path.join(ROOT, "packaging", "gpi.ico"),
    uac_admin=False,        # executa como o usuário (asInvoker): nunca pede privilégio administrativo
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GPI")
