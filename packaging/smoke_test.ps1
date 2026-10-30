# Testes do GPI.exe empacotado (usados no CI e utilizáveis manualmente no Windows).
#   A inicialização · B servidor local · C interface · D modelos de ML dentro do pacote
#   E persistência · F encerramento e liberação da porta · G integridade · H distribuição limpa
# Cada resultado é gravado em smoke_resultados.txt (anexado ao relatório de build).
param([string]$Exe = "dist/GPI/GPI.exe", [string]$Report = "smoke_resultados.txt")
$ErrorActionPreference = "Stop"
# qualquer exceção do PowerShell vira anotação de erro com a linha exata (o log completo nem sempre é acessível)
trap {
  $msg = "exceção na linha $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message) | $($_.InvocationInfo.Line.Trim())"
  Write-Host "FALHA: $msg"
  if ($Report) { Add-Content -Encoding utf8 $Report "FALHA: $msg" -ErrorAction SilentlyContinue }
  Write-Output "::error title=smoke-excecao::$msg"
  Get-Process GPI -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  exit 1
}
$tmp = $env:RUNNER_TEMP
if (-not $tmp) { $tmp = $env:TEMP }
$Report = [IO.Path]::GetFullPath((Join-Path (Get-Location) $Report))
"" | Set-Content -Encoding utf8 $Report

# H) Distribuição limpa: cópia do pacote em outra pasta, sem Python no PATH e sem variáveis do Python
$clean = Join-Path $tmp "gpi-limpo"
Remove-Item -Recurse -Force $clean -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $clean | Out-Null
Copy-Item -Recurse (Split-Path (Resolve-Path $Exe)) $clean
$Exe = Join-Path $clean "GPI/GPI.exe"
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0;$PSHOME"
foreach ($v in "PYTHONHOME", "PYTHONPATH", "pythonLocation", "Python_ROOT_DIR", "Python2_ROOT_DIR", "Python3_ROOT_DIR", "VIRTUAL_ENV") {
  Remove-Item "Env:$v" -ErrorAction SilentlyContinue
}
$py = Get-Command python -ErrorAction SilentlyContinue
$pyInfo = if ($py) { "python ainda acessível: $($py.Source)" } else { "python fora do PATH" }

$data = Join-Path $tmp "gpi-smoke-data"
Remove-Item -Recurse -Force $data -ErrorAction SilentlyContinue
$env:GPI_DATA_DIR = $data
$env:GPI_NO_DIALOG = "1"
New-Item -ItemType Directory -Force $data | Out-Null
# sem sincronização automática aqui (a coleta real é validada no job de conectores)
'{"auto_sync": false}' | Set-Content -Encoding utf8 (Join-Path $data "config.json")
$base = "http://127.0.0.1:8765"
$hdr = @{ "X-GPI" = "1" }

function Note($msg) { Write-Host $msg; Add-Content -Encoding utf8 $Report $msg }
function Fail($msg) {
  Note "FALHA: $msg"
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
function StartApp {
  $p = Start-Process -FilePath $Exe -ArgumentList "--no-browser" -PassThru
  for ($i = 0; $i -lt 90; $i++) {
    try { $r = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 2 -NoProxy; if ($r.ok) { return $p } }
    catch { Start-Sleep -Seconds 1 }
  }
  Fail "servidor não respondeu em 90 s"
}
function StopApp($p) {
  $null = RunExe @("--stop") 60
  if (-not $p.WaitForExit(30000)) { $p.Kill(); Fail "GPI não encerrou em 30 s após --stop" }
}
function PortFree([int]$port) {
  try { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port); $l.Start(); $l.Stop(); return $true }
  catch { return $false }
}

Note "H) Distribuição limpa: pacote copiado para $clean; $pyInfo"

Note "A) Inicialização + verificação de integridade (--smoke)"
$code = RunExe @("--smoke") 180
if ($code -ne 0) { Fail "--smoke terminou com código $code" }
Note "   OK"

Note "D) Modelos dentro do pacote (--selftest: importação e inferência mínima)"
$code = RunExe @("--selftest") 600
$stFile = Join-Path $data "selftest.json"
if (-not (Test-Path $stFile)) { Fail "selftest.json não foi gerado (código $code)" }
Copy-Item $stFile (Join-Path (Split-Path $Report) "selftest.json") -Force
$st = Get-Content -Raw -Encoding utf8 $stFile | ConvertFrom-Json
foreach ($k in $st.bibliotecas.PSObject.Properties.Name) { Note ("   biblioteca {0,-11} {1}" -f $k, $st.bibliotecas.$k) }
foreach ($k in $st.modelos.PSObject.Properties.Name) {
  $m = $st.modelos.$k
  if ($m.ok) { Note ("   modelo {0,-15} OK   {1} s" -f $k, $m.segundos) } else { Note ("   modelo {0,-15} ERRO {1}" -f $k, $m.erro) }
}
if ($code -ne 0) { Fail "autoteste dos modelos falhou: $($st.exigidos_com_falha -join ', ')" }

Note "B) Servidor local em $base"
$app = StartApp
Note "   /api/health OK"
try { Invoke-WebRequest -Uri "$base/api/health" -Headers @{Host = "evil.example"} -UseBasicParsing -NoProxy -TimeoutSec 15 | Out-Null; Fail "proteção de Host não funcionou" }
catch { Note "   proteção de Host OK (403)" }
$csrf = $false
try { Invoke-RestMethod -Method Post -Uri "$base/api/demo" -NoProxy -TimeoutSec 15 | Out-Null } catch { $csrf = $true }
if (-not $csrf) { Fail "POST sem cabeçalho X-GPI foi aceito" }
Note "   proteção CSRF OK"

Note "C) Interface"
$html = Invoke-WebRequest -Uri "$base/" -UseBasicParsing -NoProxy -TimeoutSec 15
if ($html.Content -notmatch "Global Product Intelligence") { Fail "index.html não carregou" }
foreach ($f in "styles.css", "math.js", "charts.js", "methodology.js", "market.js", "market3.js", "app.js") {
  $r = Invoke-WebRequest -Uri "$base/static/$f" -UseBasicParsing -NoProxy -TimeoutSec 15
  if ($r.StatusCode -ne 200 -or $r.RawContentLength -lt 100) { Fail "/static/$f não servido" }
}
$src = Invoke-RestMethod -Uri "$base/api/market/sources" -NoProxy -TimeoutSec 30
Note "   index.html + 7 arquivos CSS/JS servidos; $(@($src).Count) fontes listadas"

Note "E) Persistência (dados demonstrativos numa pasta isolada → encerrar → reabrir)"
$null = Invoke-RestMethod -Method Post -Uri "$base/api/demo" -Headers $hdr -NoProxy -TimeoutSec 60
$skus = @(Invoke-RestMethod -Uri "$base/api/skus" -NoProxy -TimeoutSec 30)
$before = $skus.Count
if ($before -lt 1) { Fail "importação de teste não gravou SKUs" }
$body = @{ sku = $skus[0].sku; horizon = 6 } | ConvertTo-Json
$fc = Invoke-RestMethod -Method Post -Uri "$base/api/forecast" -Headers $hdr -ContentType "application/json" -Body $body -NoProxy -TimeoutSec 300
Note "   $before SKUs gravados; previsão pela API executada (modelo escolhido: $($fc.modelo_escolhido))"

Note "F) Encerramento seguro e liberação da porta"
StopApp $app
Start-Sleep -Seconds 2
if (-not (PortFree 8765)) { Fail "porta 8765 continua ocupada após o encerramento" }
if (Test-Path (Join-Path $data "gpi.run.json")) { Fail "gpi.run.json não foi removido" }
Note "   processo encerrado; porta 8765 liberada"

$app = StartApp
$after = @(Invoke-RestMethod -Uri "$base/api/skus" -NoProxy -TimeoutSec 30).Count
StopApp $app
if ($after -ne $before) { Fail "persistência: $before SKUs antes, $after depois da reabertura" }
Note "   reabertura: $after SKUs preservados"

Note "G) Integridade: arquivo alterado deve impedir a abertura (código 4)"
$victim = Join-Path (Split-Path $Exe) "_internal/frontend/app.js"
Copy-Item $victim "$victim.bak"
Add-Content $victim "// alterado"
$code = RunExe @("--smoke") 180
Move-Item -Force "$victim.bak" $victim
if ($code -ne 4) { Fail "arquivo alterado não foi detectado (código $code)" }
Note "   alteração detectada"

Note "TODOS OS TESTES DO EXECUTÁVEL PASSARAM (A–H)"
