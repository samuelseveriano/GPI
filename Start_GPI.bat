@echo off
rem ==== GPI - Global Product Intelligence: inicializador portatil ====
rem Nao requer administrador. Escuta somente em 127.0.0.1.
setlocal
cd /d "%~dp0"

set "PY="
if exist "portable\python\python.exe" set "PY=portable\python\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [GPI] Python nao encontrado.
  echo [GPI] Use a versao portatil ^(pasta portable\python^) gerada por scripts\build_portable.ps1
  echo [GPI] ou solicite a equipe de TI. Veja docs\TI.md.
  pause
  exit /b 1
)

set "PYTHONPATH=%~dp0backend"
set "PYTHONDONTWRITEBYTECODE=1"
echo [GPI] Iniciando... o navegador abrira em http://127.0.0.1:8765
echo [GPI] Para encerrar, feche esta janela ou execute Stop_GPI.bat
%PY% -m gpi.main %*
if errorlevel 1 (
  echo.
  echo [GPI] O programa terminou com erro. Detalhes em data\logs\gpi.log
  echo [GPI] Diagnostico: Start_GPI.bat --check
  pause
)
endlocal
