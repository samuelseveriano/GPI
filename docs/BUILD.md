# Relatório de build — GPI v0.3 (Fase 3)

## Situação: executável Windows NÃO gerado neste ambiente

| Item | Situação |
|---|---|
| `GPI-Windows-Portable.zip` | **Pendente.** O ambiente de desenvolvimento é Linux, sem acesso à internet (PyPI bloqueado), sem PyInstaller/Nuitka e sem Wine. Não foi possível compilar nem testar um `.exe`. |
| Inicializador (`backend/gpi/main.py`) | Pronto e testado (Linux): integridade de arquivos, pasta de dados separada, porta, servidor, navegador, janela de controle, encerramento seguro, modo `--smoke`. |
| Especificação PyInstaller (`packaging/gpi.spec`) | Escrita, **não executada**. One-folder, `GPI.exe` sem console, sem UPX (reduz falsos positivos de antivírus). |
| Workflow GitHub Actions (`.github/workflows/windows-build.yml`) | Escrito, **não executado**. Testes → validação real dos conectores → PyInstaller → manifesto → testes de inicialização do `.exe` → ZIP como artefato. |
| Testes de inicialização do `.exe` (`packaging/smoke_test.ps1`) | Escritos, **não executados**: `--smoke`, acesso a 127.0.0.1:8765, interface, proteção de Host, `--stop`, persistência, detecção de arquivo alterado. |
| Testes automatizados (Python) | **89 aprovados, 3 ignorados** (SARIMA/LightGBM/XGBoost: bibliotecas indisponíveis aqui; rodam no CI do Windows). |

## Como gerar o executável (uma vez, por quem mantém o sistema)

**Opção A — GitHub Actions (recomendada, sem instalar nada):**
1. Envie este projeto para um repositório no GitHub.
2. Aba *Actions* → *windows-build* → *Run workflow* (ou faça push na branch `main`).
3. Ao terminar (~15–25 min), baixe o artefato **GPI-Windows-Portable**: contém o ZIP, o `relatorio_build.txt` e `validacao_conectores.json` (resultado das coletas reais no runner com internet).

Runners gratuitos: ilimitados em repositório público. Em repositório privado, consomem a cota mensal do plano, e minutos de Windows são cobrados em dobro em relação ao Linux. Artefatos ficam disponíveis por 30 dias (configurado no workflow).

**Opção B — computador Windows de desenvolvimento:** `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` (requer Python 3.12 nesse computador, não no do usuário final).

## Riscos conhecidos do empacotamento (a confirmar no primeiro build)
- `collect_submodules` e os hooks do PyInstaller para scikit-learn/scipy cobrem os imports usados; se algum faltar, o teste `--smoke` do CI falha e indica o módulo.
- Antivírus/EDR corporativo pode bloquear executáveis não assinados. Assinatura de código (certificado da empresa) é recomendada antes da distribuição interna.
- Tamanho estimado do pacote: 250–400 MB descompactado (numpy, scipy, pandas, scikit-learn, LightGBM, XGBoost, statsmodels).
