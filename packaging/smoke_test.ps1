# Testes de inicialização do GPI.exe empacotado (usado no CI e utilizável manualmente).
param([string]$Exe = "dist/GPI/GPI.exe")
$ErrorActionPreference = "Stop"
$data = Join-Path $env:RUNNER_TEMP "gpi-smoke-data"
if (-not $env:RUNNER_TEMP) { $data = Join-Path $env:TEMP "gpi-smoke-data" }
Remove-Item -Recurse -Force $data -ErrorAction SilentlyContinue
$env:GPI_DATA_DIR = $data
$env:GPI_NO_DIALOG = "1"
New-Item -ItemType Directory -Force $data | Out-Null
# sem sincronização automática no teste de inicialização (a coleta real é validada em outra etapa)
'{"auto_sync": false}' | Set-Content -Encoding utf8 (Join-Path $data "config.json")

function Fail($msg) {
  Write-Host "FALHA: $msg"
  $log = Join-Path $data "logs/gpi.log"
  $tail = ""
  if (Test-Path $log) { $tail = (Get-Content $log -Tail 30) -join '%0A' }
  Write-Output "::error title=smoke::$msg%0A$tail"
  Get-Process GPI -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  exit 1
}

function RunExe([string[]]$ArgList, [int]$TimeoutSec = 120) {
  $p = Start-Process -FilePath $Exe -ArgumentList $ArgList -PassThru
  if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    try { $p.Kill() } catch {}
    Fail "GPI.exe $($ArgList -join ' ') não terminou em $TimeoutSec s"
  }
  return $p.ExitCode
}

Write-Host "1) Verificação de integridade + inicialização rápida (--smoke)"
$code = RunExe @("--smoke") 180
if ($code -ne 0) { Fail "--smoke terminou com código $code" }

Write-Host "2) Execução normal em segundo plano e acesso a http://127.0.0.1:8765"
$app = Start-Process -FilePath $Exe -ArgumentList "--no-browser" -PassThru
$ok = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2 -NoProxy
    if ($r.ok) { $ok = $true; break }
  } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { Fail "servidor não respondeu em 90 s" }
$html = Invoke-WebRequest -Uri "http://127.0.0.1:8765/" -UseBasicParsing -NoProxy -TimeoutSec 15
if ($html.Content -notmatch "Global Product Intelligence") { Fail "interface não carregou" }
$src = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/market/sources" -NoProxy -TimeoutSec 30
Write-Host ("   fontes listadas: " + $src.Count)
try { Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -Headers @{Host = "evil.example"} -UseBasicParsing -NoProxy -TimeoutSec 15 | Out-Null; Fail "proteção de Host não funcionou" } catch { Write-Host "   proteção de Host OK (403)" }

Write-Host "3) Encerramento seguro (--stop)"
$null = RunExe @("--stop") 60
if (-not $app.WaitForExit(30000)) { $app.Kill(); Fail "GPI não encerrou em 30 s após --stop" }

Write-Host "4) Persistência: banco criado na pasta de dados do usuário e reabertura"
if (-not (Test-Path (Join-Path $data "gpi.sqlite"))) { Fail "banco não encontrado em $data" }
$code = RunExe @("--smoke") 180
if ($code -ne 0) { Fail "reabertura falhou (código $code)" }

Write-Host "5) Integridade: arquivo alterado deve impedir a abertura"
$victim = Join-Path (Split-Path $Exe) "_internal/frontend/app.js"
Copy-Item $victim "$victim.bak"
Add-Content $victim "// alterado"
$code = RunExe @("--smoke") 180
Move-Item -Force "$victim.bak" $victim
if ($code -ne 4) { Fail "arquivo alterado não foi detectado (código $code)" }

Write-Host "TODOS OS TESTES DE INICIALIZAÇÃO PASSARAM"
