# Testes do GPI.exe empacotado (usados no CI e utilizáveis manualmente no Windows).
#   I relatórios XLSX/PDF · A inicialização · B servidor local · C interface · D modelos de ML dentro do pacote
#   E persistência · F encerramento e liberação da porta · G integridade · H distribuição limpa
# Cada resultado é gravado em smoke_resultados.txt (anexado ao relatório de build).
param([string]$Exe = "dist/GPI/GPI.exe", [string]$Report = "smoke_resultados.txt")
$ErrorActionPreference = "Stop"
# qualquer exceção do PowerShell vira anotação de erro com a linha exata (o log completo nem sempre é acessível)
trap {
  $msg = "exceção na linha $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message) | $($_.InvocationInfo.Line.Trim())"
  Write-Host "FALHA: $msg"
  if ($Report) { Add-Content -Encoding utf8 $Report "FALHA: $msg" -ErrorAction SilentlyContinue }
  $tail = ""
  if ($data) { $log = Join-Path $data "logs/gpi.log"; if (Test-Path $log) { $tail = (Get-Content $log -Tail 40) -join '%0A' } }
  Write-Output "::error title=smoke-excecao::$msg%0A$tail"
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
# Invoke-RestMethod devolve um array JSON como um único objeto: achatar para contar e indexar
function GetList($uri) { return @((Invoke-RestMethod -Uri $uri -NoProxy -TimeoutSec 30) | ForEach-Object { $_ }) }
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
$src = @(GetList "$base/api/market/sources")
if ($src.Count -lt 5) { Fail "lista de fontes incompleta ($($src.Count))" }
Note "   index.html + 7 arquivos CSS/JS servidos; $($src.Count) fontes listadas"

Note "E) Persistência (dados demonstrativos numa pasta isolada → encerrar → reabrir)"
$null = Invoke-RestMethod -Method Post -Uri "$base/api/demo" -Headers $hdr -NoProxy -TimeoutSec 60
$skus = @(GetList "$base/api/skus")
$before = $skus.Count
if ($before -lt 1) { Fail "importação de teste não gravou SKUs" }
if ($before -lt 2) { Fail "dados de teste com $before SKU(s); esperado ≥ 2" }
$body = @{ sku = [string]$skus[0].sku; horizon = 6 } | ConvertTo-Json
$fc = Invoke-RestMethod -Method Post -Uri "$base/api/forecast" -Headers $hdr -ContentType "application/json" -Body $body -NoProxy -TimeoutSec 300
Note "   $before SKUs gravados; previsão pela API executada (modelo escolhido: $($fc.modelo_escolhido))"
foreach ($k in $fc.modelos.PSObject.Properties.Name) {
  $e = $fc.modelos.$k.erro
  if ($e) { Note ("   modelo {0,-15} não aplicável a esta série: {1}" -f $k, $e) }
}

Note "I) Relatórios: Excel e PDF gerados pelo executável (sem Excel/Word/LibreOffice, sem internet)"
$repIds = @()
foreach ($fmt in "xlsx", "pdf") {
  $rb = @{ tipo = "executivo"; formato = $fmt; filtros = @{} } | ConvertTo-Json
  $rr = Invoke-RestMethod -Method Post -Uri "$base/api/reports/generate" -Headers $hdr -ContentType "application/json" -Body $rb -NoProxy -TimeoutSec 300
  if ($rr.status -ne "gerado") { Fail "relatório $fmt não gerado: $($rr.erro)" }
  $out = Join-Path $tmp "gpi-relatorio.$fmt"
  Invoke-WebRequest -Uri "$base/api/reports/$($rr.id)/download" -OutFile $out -UseBasicParsing -NoProxy -TimeoutSec 60
  $bytes = [IO.File]::ReadAllBytes($out)
  $magic = [Text.Encoding]::ASCII.GetString($bytes, 0, 4)
  if ($fmt -eq "pdf" -and $magic -ne "%PDF") { Fail "PDF inválido (cabeçalho '$magic')" }
  if ($fmt -eq "xlsx" -and $magic.Substring(0, 2) -ne "PK") { Fail "XLSX inválido (cabeçalho '$magic')" }
  if ($bytes.Length -lt 2000) { Fail "relatório $fmt muito pequeno ($($bytes.Length) bytes)" }
  $repIds += $rr.id
  Note ("   {0}: {1} bytes · {2}" -f $fmt.ToUpper(), $bytes.Length, $rr.arquivo)
}
if ($fmt -eq "pdf") { Copy-Item $out (Join-Path (Split-Path $Report) "exemplo_relatorio_exe.pdf") -Force }

Note "J) Painel de sincronização, integrações e YouTube (v0.6.1)"
$pn = Invoke-RestMethod -Uri "$base/api/sync/panel" -NoProxy -TimeoutSec 30
if (-not $pn.titulo) { Fail "painel de sincronização sem título" }
$ints = Invoke-RestMethod -Uri "$base/api/integrations?v=6" -NoProxy -TimeoutSec 30
$ga = @($ints.integracoes | Where-Object { $_.id -eq "google_ads" })[0]
if (@($ga.campos | Where-Object { $_.nome -eq "developer_token" }).Count -ne 0) { Fail "Google Ads ainda pede developer token" }
if (-not $ga.estados.nivel) { Fail "integração sem estado (configurado/autenticado/…)" }
$yt = Invoke-RestMethod -Uri "$base/api/youtube/status" -NoProxy -TimeoutSec 30
$diag = Invoke-WebRequest -Uri "$base/api/diagnostics/export" -UseBasicParsing -NoProxy -TimeoutSec 60
if ($diag.StatusCode -ne 200 -or $diag.Content -notmatch "versao_gpi") { Fail "exportação de diagnóstico falhou" }
Note "   painel: $($pn.titulo) · Google Ads sem developer token · YouTube: $($yt.videos_armazenados) vídeos · diagnóstico exportado"

Note "K) Conformidade de Importação, IA local sob demanda, Mercado Livre HTTPS e cabeçalhos de segurança (v0.7)"
$cs = Invoke-RestMethod -Uri "$base/api/compliance/status" -NoProxy -TimeoutSec 30
if ($cs.documentos -lt 20) { Fail "base regulatória com $($cs.documentos) documentos" }
if ($cs.ia.carregado) { Fail "IA local carregada na inicialização (deveria ser sob demanda)" }
$body = @{ formulario = @{ nome_comercial = "Fechadura inteligente"; descricao_tecnica = "Wi-Fi 2.4 GHz e Bluetooth LE"; destinacao = "comercializacao" } } | ConvertTo-Json -Depth 4
$an = Invoke-RestMethod -Uri "$base/api/compliance/analisar" -Method Post -Headers $hdr -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body)) -NoProxy -TimeoutSec 60
$anatel = @($an.achados | Where-Object { $_.orgao -eq "Anatel" })[0]
if ($anatel.estado -ne 1) { Fail "análise regulatória: Anatel estado $($anatel.estado) (esperado 1)" }
if (($an | ConvertTo-Json -Depth 8) -match "liberado para importar") { Fail "resultado contém 'liberado para importar'" }
$rb = @{ tipo = "regulatorio"; formato = "pdf"; filtros = @{ analise_id = $an.id } } | ConvertTo-Json -Depth 4
$rr = Invoke-RestMethod -Uri "$base/api/reports/generate" -Method Post -Headers $hdr -ContentType "application/json" -Body $rb -NoProxy -TimeoutSec 120
if ($rr.status -ne "gerado") { Fail "relatório regulatório não gerado: $($rr.erro)" }
$ask = @{ pergunta = "Um produto com Bluetooth precisa de homologação?" } | ConvertTo-Json
$aa = Invoke-RestMethod -Uri "$base/api/compliance/assistente" -Method Post -Headers $hdr -ContentType "application/json" -Body ([Text.Encoding]::UTF8.GetBytes($ask)) -NoProxy -TimeoutSec 60
if ($aa.modo -ne "essencial" -or -not $aa.fontes) { Fail "assistente (Modo Essencial) sem resposta com fontes" }
$ret = Invoke-WebRequest -Uri "$base/oauth/mercadolivre/retorno" -UseBasicParsing -NoProxy -TimeoutSec 30
if ($ret.Content -notmatch "oauth_retorno.js") { Fail "página local de retorno do Mercado Livre ausente" }
$h = Invoke-WebRequest -Uri "$base/" -UseBasicParsing -NoProxy -TimeoutSec 30
if ($h.Headers["Content-Security-Policy"] -notmatch "script-src 'self'") { Fail "CSP ausente" }
Note "   base: $($cs.documentos) documentos · análise nº $($an.id): Anatel estado 1 · relatório regulatório PDF · assistente essencial · CSP ativo · IA não carregada"

Note "L) v0.7.1: auditoria das fontes, integridade do banco, Inteligência de Oportunidades e atualização manual"
$au = Invoke-RestMethod -Uri "$base/api/sources/audit" -NoProxy -TimeoutSec 60
if (@($au.fontes).Count -lt 20) { Fail "auditoria das fontes com $(@($au.fontes).Count) fontes" }
$ig = Invoke-RestMethod -Uri "$base/api/db/integrity" -NoProxy -TimeoutSec 60
if (-not $ig.ok) { Fail "integridade do banco: $($ig.integridade)" }
$ins = Invoke-RestMethod -Uri "$base/api/consumer/insights" -NoProxy -TimeoutSec 120
if (-not $ins.aviso) { Fail "Inteligência de Oportunidades sem resposta" }
$mb = @{ fontes = @("bcb_ptax"); manual = $true } | ConvertTo-Json
$ms = Invoke-RestMethod -Uri "$base/api/sync/start" -Method Post -Headers $hdr -ContentType "application/json" -Body $mb -NoProxy -TimeoutSec 30
Note "   auditoria: $(@($au.fontes).Count) fontes · banco íntegro (esquema v$($ig.versao_esquema)) · insights: $(@($ins.itens).Count) produtos · atualização manual iniciada: $($ms.iniciada)"

Note "M) v0.8: qualidade dos dados (gates), fusão de evidências, dashboard, dossiê, regulatório e lista de investigação"
$v8 = Invoke-RestMethod -Uri "$base/api/v08/visao" -NoProxy -TimeoutSec 180
if ($null -eq $v8.kpis.produtos_monitorados) { Fail "dashboard v0.8 sem KPIs" }
$q8 = Invoke-RestMethod -Uri "$base/api/v08/qualidade" -NoProxy -TimeoutSec 180
foreach ($g in @("1", "2", "3", "4", "6", "8")) { if (-not $q8.gates.$g) { Fail "gate $g ausente" } }
if ($q8.gates."2".status -ne "aprovado") { Fail "Gate 2 (identificação de produtos) reprovado no executável" }
if ($q8.gates."8".status -ne "aprovado") { Fail "Gate 8 (consistência fim a fim) reprovado no executável" }
$m8 = Invoke-RestMethod -Uri "$base/api/v08/metricas" -NoProxy -TimeoutSec 30
if (@($m8.metricas).Count -lt 10) { Fail "catálogo semântico incompleto" }
$rs = Invoke-RestMethod -Uri "$base/api/regulatorio/status" -NoProxy -TimeoutSec 30
if (-not $rs.papeis.titular) { Fail "módulo regulatório sem papéis" }
$ib = @{ produto = "Teste do executável"; motivo = "smoke" } | ConvertTo-Json
$iv = Invoke-RestMethod -Uri "$base/api/v08/investigacoes" -Method Post -Headers $hdr -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($ib)) -NoProxy -TimeoutSec 30
if ($iv.estado -ne "Novo sinal") { Fail "lista de investigação não gravou" }
$invId = $iv.id
$rp8 = @{ tipo = "executivo"; formato = "pdf"; filtros = @{} } | ConvertTo-Json
$re8 = Invoke-RestMethod -Uri "$base/api/reports/generate" -Method Post -Headers $hdr -ContentType "application/json" -Body $rp8 -NoProxy -TimeoutSec 300
if ($re8.status -ne "gerado") { Fail "relatório executivo v0.8: $($re8.erro)" }
Note "   gates: $(($q8.gates.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value.status)" }) -join ' ') · produtos analisados: $($v8.kpis.produtos_analisados) · métricas: $(@($m8.metricas).Count) · investigação nº $invId · executivo PDF gerado"

Note "F) Encerramento seguro e liberação da porta"
StopApp $app
Start-Sleep -Seconds 2
if (-not (PortFree 8765)) { Fail "porta 8765 continua ocupada após o encerramento" }
if (Test-Path (Join-Path $data "gpi.run.json")) { Fail "gpi.run.json não foi removido" }
Note "   processo encerrado; porta 8765 liberada"

$app = StartApp
$after = @(GetList "$base/api/skus").Count
$hist = Invoke-RestMethod -Uri "$base/api/reports" -NoProxy -TimeoutSec 30
$kept = @($hist.relatorios | Where-Object { $repIds -contains $_.id -and $_.disponivel }).Count
$inv2 = Invoke-RestMethod -Uri "$base/api/v08/investigacoes/$invId" -NoProxy -TimeoutSec 30
StopApp $app
if ($kept -ne 2) { Fail "histórico de relatórios não persistiu após reabrir ($kept de 2)" }
if ($inv2.produto -ne "Teste do executável") { Fail "lista de investigação não persistiu após reabrir" }
Note "   reabertura: investigação nº $invId preservada"
Note "   reabertura: 2 relatórios preservados no histórico"
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

Note "TODOS OS TESTES DO EXECUTÁVEL PASSARAM (A–M)"
