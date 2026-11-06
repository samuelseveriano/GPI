# Build do GPI para Windows — GPI v0.6.1

O executável é gerado e testado automaticamente pelo GitHub Actions
(`.github/workflows/windows-build.yml`) a cada push na branch `main`, ou manualmente em
*Actions → windows-build → Run workflow*.

## Como baixar o aplicativo
1. Abra o repositório no GitHub → aba **Actions** → workflow **windows-build**.
2. Clique na execução mais recente com o ícone verde (✓).
3. No fim da página, em **Artifacts**, clique em **GPI-Windows-Portable** (é preciso estar logado no GitHub).
4. O download é um ZIP que contém `GPI-Windows-Portable.zip` e `relatorio_build.txt`. Extraia o
   `GPI-Windows-Portable.zip` numa pasta (ex.: Documentos\GPI) e dê dois cliques em `GPI\GPI.exe`.
5. O navegador abre em `http://127.0.0.1:8765`. Os dados ficam em `%LOCALAPPDATA%\GPI`.

Não é preciso instalar Python, Node.js, banco de dados, Docker, nem ter privilégio de administrador.
A execução continua sujeita às políticas de segurança da empresa (antivírus/EDR, proxy) — ver `docs/TI.md`.
Artefatos ficam disponíveis por 30 dias; um novo push gera um novo pacote.

## O que o workflow faz
| Job | Runner | O que executa | Bloqueia o pacote? |
|---|---|---|---|
| 1. Testes automatizados | Windows | `pytest` com statsmodels, LightGBM e XGBoost instalados; publica `relatorio-testes` (log + JUnit XML) | Sim |
| 2. Validação real dos conectores | Ubuntu | Coleta uma amostra real de cada API pública (até 6 requisições por fonte); publica `validacao-conectores` | Não — fonte fora do ar não impede o build, mas só aparece como validada com registros gravados |
| 3. Compilar e testar GPI.exe | Windows | PyInstaller one-folder → manifesto SHA-256 → testes A–H → relatório → ZIP | Sim |

Testes do executável (`packaging/smoke_test.ps1`), executados numa **cópia do pacote em outra pasta,
com o Python removido do PATH e sem variáveis PYTHON\***:

| Teste | Verificação |
|---|---|
| A — Inicialização | `GPI.exe --smoke`: integridade, servidor, `/api/health`, encerramento |
| B — Servidor local | `http://127.0.0.1:8765` responde; proteção de Host (403) e CSRF (POST sem cabeçalho recusado) |
| C — Interface | `index.html` e os 7 arquivos CSS/JS servidos; lista de fontes carregada |
| D — Machine learning | `GPI.exe --selftest`: importa numpy, scipy, pandas, scikit-learn, statsmodels, LightGBM, XGBoost **dentro do pacote** e executa cada um dos 15 modelos numa série sintética de teste; falha se qualquer modelo exigido falhar |
| E — Persistência | grava dados demonstrativos numa pasta isolada, executa uma previsão pela API, encerra, reabre e confere os mesmos SKUs |
| F — Encerramento | `--stop` encerra o processo, remove `gpi.run.json` e libera a porta 8765 |
| G — Integridade | altera um arquivo do pacote e confirma que o GPI recusa abrir (código 4) |
| I — Relatórios | gera o Relatório Executivo em XLSX e PDF pelo executável, confere os cabeçalhos dos arquivos (PK / %PDF) e, após reabrir, confere que os 2 relatórios continuam no histórico |
| J — Painel e integrações (v0.6.1) | painel de sincronização responde, Google Ads sem campo de developer token, estados das integrações, YouTube e exportação de diagnóstico |
| Q — Product Intelligence Suite (v0.9.1) | suíte responde com modo sem custos ativo, pesquisa de produto conclui 100% das etapas, consulta paga do ImportYeti **não** é feita, busca visual local aceita PNG sem gravar a imagem, exportação XLSX da pesquisa |
| H — Distribuição limpa | todos os testes acima rodam na cópia sem Python no PATH |

Em caso de falha, a etapa mostra a anotação `smoke`/`smoke-excecao` com a linha e o final do `gpi.log`,
e o artefato **logs-build** guarda `pyi.log`, avisos do PyInstaller, dependências e o log do GPI.

## Diagnóstico das falhas corrigidas (out/2026)
| Execução | Falha | Causa | Correção |
|---|---|---|---|
| #1–#2 | PyInstaller: `RuntimeError: Child process call to _collect_submodules() failed` — `xgboost/testing/__init__.py`: `No module named 'hypothesis'` | `collect_submodules("xgboost")` importava o pacote de testes interno do XGBoost | `gpi.spec`: filtro que exclui submódulos `.testing`/`.tests` (sem instalar dependências de desenvolvimento) |
| #2 | Validação: `UnicodeEncodeError` (cp1252) | saída do Python no console do Windows | `PYTHONUTF8=1` e `PYTHONIOENCODING=utf-8` no workflow; JSON gravado em UTF-8 |
| #2 | PTAX CNY vazio, Comex Stat HTTP 429, Comtrade "Maximum number of periods for preview is 1" | conector tratava resposta vazia como erro; intervalo curto entre chamadas; vários períodos numa chamada | resposta vazia = sem dados; 12 s entre chamadas ao Comex Stat; um período por chamada ao Comtrade |
| #4 | Job cancelado após 60 min | teste do `.exe` com `Start-Process -Wait` sem limite; validação dos conectores sem limite (26 min) | todo `GPI.exe` aguardado com tempo máximo; validação limitada (15 min, amostra por fonte) e em job separado |
| #5 | Teste de integridade travado | caixa de diálogo de erro do Windows aguardando clique | sem diálogo nos modos `--smoke/--check/--selftest` |
| #7–#8 | `/api/forecast` retornava 500 no teste do `.exe` | o script de teste enviava a lista de SKUs como `sku` (array JSON do PowerShell 7); a API não validava o tipo | script corrigido; API responde 400 para tipos inválidos; erro inesperado de um modelo não derruba mais a previsão |
| testes Linux | `test_full_start_stop_cycle` intermitente | corrida: `--stop` logo após o início deixava o processo esperando 30 s | inicializador usa o estado do próprio servidor (`server.started`) |
| validação | Wikimedia marcada "validada" com 0 registros | amostra do CI parava antes das consultas de visualizações; status não exigia registros | fonte só é validada com registros gravados ("sem dados" caso contrário); amostra não pula consultas dependentes |

## Dependências empacotadas
Python 3.12 (runtime embutido pelo PyInstaller), Starlette, Uvicorn, NumPy, SciPy, pandas,
scikit-learn, statsmodels, LightGBM, XGBoost, openpyxl, além da interface (HTML/CSS/JS), `config/` e `docs/`.
Excluídos: matplotlib, IPython, notebook, pytest, torch, tensorflow e os submódulos de teste do XGBoost/LightGBM.
A lista exata de versões de cada build está em `relatorios/dependencias.txt` dentro do pacote.

## Build local (opcional, para quem mantém o sistema)
`powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` num Windows com Python 3.12
(necessário só nesse computador, não no do usuário final).

## Riscos conhecidos
- Executável não assinado: antivírus/EDR corporativo pode bloquear ou exigir liberação. Recomenda-se assinar
  `GPI.exe` com o certificado de código da empresa antes da distribuição interna.
- IBGE (`servicodados.ibge.gov.br`) não respondeu a partir dos runners do GitHub (Windows e Ubuntu, nos EUA):
  tempo esgotado em todas as tentativas. A causa provável é bloqueio de acesso a partir do exterior; precisa ser
  confirmada numa rede brasileira (a página *Saúde das Fontes* mostra o resultado na primeira sincronização).
