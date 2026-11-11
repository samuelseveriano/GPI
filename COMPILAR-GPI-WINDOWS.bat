@echo off
rem ==== GPI v0.9.1 - compilar o GPI.exe neste computador (sem GitHub) ====
rem Requer Python 3.12 64 bits instalado (python.org, "Install for me only"). Nao requer administrador.
rem Gera GPI-Windows-Portable-v0.9.1-MVP.zip e GPI-Build-Report.txt nesta pasta.
setlocal
cd /d "%~dp0"
echo.
echo  GPI - compilacao local do executavel Windows
echo  1) Completo (testes automatizados + executavel, ~45 min)
echo  2) Rapido   (somente executavel + testes do executavel, ~15 min)
echo.
choice /c 12 /n /m "Escolha 1 ou 2: "
if errorlevel 2 (set "OPT=-SkipTests") else (set "OPT=")
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build_windows.ps1" %OPT%
if errorlevel 1 (
  echo.
  echo [GPI] A compilacao falhou. Veja build_local.log, pyi.log, pytest.log ou smoke_resultados.txt nesta pasta.
) else (
  echo.
  echo [GPI] Pronto. Extraia GPI-Windows-Portable-v0.9.1-MVP.zip e abra GPI\GPI.exe
)
pause
