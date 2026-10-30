# Build local no Windows (alternativa ao GitHub Actions). Não requer administrador.
# Requer Python 3.12 instalado no computador de BUILD (não no computador do usuário final).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m venv .venv-build
.\.venv-build\Scripts\python -m pip install --upgrade pip
.\.venv-build\Scripts\pip install -r requirements.txt -r requirements-optional.txt pytest "pyinstaller>=6.6,<7"
.\.venv-build\Scripts\python -m pytest -q tests
.\.venv-build\Scripts\pyinstaller --noconfirm --clean packaging/gpi.spec
.\.venv-build\Scripts\python packaging/make_manifest.py dist/GPI
./packaging/smoke_test.ps1 -Exe dist/GPI/GPI.exe
Compress-Archive -Force -Path dist/GPI -DestinationPath GPI-Windows-Portable.zip
Write-Host "Pronto: GPI-Windows-Portable.zip"
