# Build local no Windows — substitui o GitHub Actions (mesmos passos do job "build" de windows-build.yml).
# Não requer administrador. Requer Python 3.12 (64 bits) instalado NO COMPUTADOR DE BUILD — o GPI.exe gerado
# não precisa de Python no computador do usuário final.
#
# Uso (PowerShell, na pasta do código-fonte):
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_windows.ps1            # completo
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -SkipTests # sem a suíte pytest
param(
  [switch]$SkipTests,
  [string]$ZipName = "GPI-Windows-Portable-Trade-Intelligence.zip",
  [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"
Set-Location (Split-Path -Parent $PSScriptRoot)
$root = Get-Location
$log = Join-Path $root "build_local.log"
"GPI - build local $(Get-Date -Format s)" | Set-Content -Encoding utf8 $log
function Step($t) { Write-Host ""; Write-Host "==== $t ====" -ForegroundColor Cyan; Add-Content -Encoding utf8 $log "== $t" }

Step "1/8 Python de build"
if (-not $Python) {
  if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py"; $pyArgs = @("-3.12") } else { $Python = "python"; $pyArgs = @() }
} else { $pyArgs = @() }
$ver = & $Python @pyArgs -c "import sys,struct;print(sys.version.split()[0], struct.calcsize('P')*8)"
if ($LASTEXITCODE -ne 0 -or -not $ver) { throw "Python 3.12 (64 bits) não encontrado. Instale em python.org (opção 'Install for me only', sem administrador) e rode de novo." }
Write-Host "Python $ver"; Add-Content -Encoding utf8 $log "Python $ver"
if ($ver -notmatch "^3\.1[2-3]\.\d+ 64$") { Write-Warning "Recomendado: Python 3.12 64 bits (o CI usava 3.12). Encontrado: $ver" }

Step "2/8 Ambiente virtual e dependências (pip)"
if (-not (Test-Path .venv-build\Scripts\python.exe)) { & $Python @pyArgs -m venv .venv-build }
$vpy = Join-Path $root ".venv-build\Scripts\python.exe"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements.txt -r requirements-optional.txt -r requirements-dev.txt "pyinstaller>=6.6,<7"
if ($LASTEXITCODE -ne 0) { throw "falha ao instalar dependências (verifique a internet/proxy)" }
& $vpy -m pip freeze | Out-File -Encoding utf8 dependencias.txt

if (-not $SkipTests) {
  Step "3/8 Testes automatizados (pytest — pode levar ~30 min)"
  & $vpy -m pytest -q -rfEs --tb=short tests *> pytest.log
  $c = $LASTEXITCODE
  Get-Content pytest.log -Tail 5
  if ($c -ne 0) { throw "testes falharam — veja pytest.log (o pacote NÃO foi gerado)" }
  $tests = (Get-Content pytest.log -Tail 1)
} else {
  Step "3/8 Testes automatizados: PULADOS (-SkipTests)"
  $tests = "não executados neste build (-SkipTests)"
}

Step "4/8 PyInstaller (one-folder: dist\GPI)"
Remove-Item -Recurse -Force dist\GPI -ErrorAction SilentlyContinue
& $vpy -m PyInstaller --noconfirm --clean packaging/gpi.spec *> pyi.log
if ($LASTEXITCODE -ne 0) { Get-Content pyi.log -Tail 40; throw "PyInstaller falhou — veja pyi.log" }
if (-not (Test-Path dist\GPI\GPI.exe)) { throw "dist\GPI\GPI.exe não foi gerado" }

Step "5/8 Documentação, manifesto de integridade e SBOM"
New-Item -ItemType Directory -Force dist\GPI\relatorios | Out-Null
"0.9.1" | Out-File -Encoding ascii -NoNewline dist\GPI\VERSION.txt
& $vpy -m pip install "cyclonedx-bom>=4,<8" | Out-Null
& (Join-Path $root ".venv-build\Scripts\cyclonedx-py.exe") environment --of JSON -o dist\GPI\relatorios\sbom.cdx.json 2>$null
& $vpy packaging/make_manifest.py dist/GPI
if ($LASTEXITCODE -ne 0) { throw "falha no manifesto de integridade" }

Step "6/8 Microsoft Defender (varredura do pacote, se disponível)"
$mp = Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
if (Test-Path $mp) {
  $out = & $mp -Scan -ScanType 3 -File (Resolve-Path dist\GPI) -DisableRemediation 2>&1
  $dcode = $LASTEXITCODE
  @("MpCmdRun -Scan -ScanType 3 -File dist\GPI -DisableRemediation", "código de saída: $dcode (0 = nenhuma ameaça; 2 = ameaça encontrada)", "", $out) | Out-File -Encoding utf8 defender.txt
  if ($dcode -eq 2) { throw "o Defender acusou ameaça no pacote — veja defender.txt" }
} else { "Microsoft Defender (MpCmdRun) indisponível neste computador" | Out-File -Encoding utf8 defender.txt }

Step "7/8 Testes do executável (cópia limpa, sem Python no PATH)"
# processo separado: o smoke test altera o PATH da própria sessão
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\smoke_test.ps1 -Exe dist/GPI/GPI.exe -Report smoke_resultados.txt
$smoke = $LASTEXITCODE
if ($smoke -ne 0) { throw "testes do executável falharam — veja smoke_resultados.txt" }

Step "8/8 Relatório, segurança, ZIP e SHA-256"
$commit = if (Test-Path BUILD_COMMIT.txt) { (Get-Content BUILD_COMMIT.txt -Raw).Trim() } else { (git rev-parse --short HEAD 2>$null) }
$exe = Get-Item dist\GPI\GPI.exe
$files = (Get-ChildItem -Recurse -File dist\GPI | Measure-Object -Property Length -Sum)
$pkgs = Get-Content dependencias.txt | Where-Object { $_ -match '^(numpy|scipy|pandas|scikit-learn|statsmodels|lightgbm|xgboost|catboost|river|rapidfuzz|optuna|starlette|uvicorn|pyinstaller|openpyxl|reportlab)==' }
$sig = Get-AuthenticodeSignature dist\GPI\GPI.exe
$report = @(
  "GPI - relatório de build (local, sem GitHub Actions)",
  "Versão: 0.9.1 MVP",
  "Commit de origem: $commit",
  "Plataforma: $([Environment]::OSVersion.VersionString) $env:PROCESSOR_ARCHITECTURE | Python $ver | PyInstaller $(& $vpy -m PyInstaller --version)",
  "GPI.exe: $([math]::Round($exe.Length/1KB)) KB; pacote: $($files.Count) arquivos, $([math]::Round($files.Sum/1MB,1)) MB",
  "Assinatura digital: $(if ($sig.Status -eq 'Valid') { 'assinado por ' + $sig.SignerCertificate.Subject } else { 'NÃO ASSINADO (' + $sig.Status + ')' })",
  "", "Bibliotecas principais:", $pkgs, "",
  "Testes automatizados: $tests",
  "Testes do executável:", (Get-Content smoke_resultados.txt)
)
$report | Out-File -Encoding utf8 dist\GPI\relatorios\relatorio_build.txt
Copy-Item dependencias.txt, defender.txt dist\GPI\relatorios\ -ErrorAction SilentlyContinue
$sec = & $vpy packaging/security_report.py dist/GPI $ZipName defender.txt dist/GPI/relatorios/seguranca.md ""
if ($LASTEXITCODE -ne 0) { throw "relatório de segurança encontrou problema (credencial embutida ou nível de execução elevado): $sec" }
Remove-Item -Force $ZipName -ErrorAction SilentlyContinue
Compress-Archive -Path dist\GPI -DestinationPath $ZipName
$h = @(Get-FileHash dist\GPI\GPI.exe -Algorithm SHA256; Get-FileHash $ZipName -Algorithm SHA256)
$h | ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } | Out-File -Encoding ascii SHA256SUMS.txt
$report + @("", "Segurança: $sec", "", "SHA-256:", (Get-Content SHA256SUMS.txt)) | Out-File -Encoding utf8 GPI-Build-Report.txt
Get-Content GPI-Build-Report.txt
Write-Host ""
Write-Host "Pronto: $ZipName  (relatório: GPI-Build-Report.txt)" -ForegroundColor Green
