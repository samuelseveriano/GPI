@echo off
setlocal
cd /d "%~dp0"
set "PY="
if exist "portable\python\python.exe" set "PY=portable\python\python.exe"
if not defined PY ( where py >nul 2>nul && set "PY=py -3" )
if not defined PY set "PY=python"
set "PYTHONPATH=%~dp0backend"
%PY% -m gpi.main --stop
timeout /t 2 >nul
endlocal
