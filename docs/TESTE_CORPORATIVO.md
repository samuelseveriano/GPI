# GPI v0.7.1 — Teste no computador corporativo (04/11/2026)

## Preparação
1. Baixe `GPI-Windows-Portable-v0.7.1.zip` (artefato do GitHub Actions — link no PR) e confira o SHA-256 em `SHA256SUMS.txt`:
   `Get-FileHash .\GPI-Windows-Portable-v0.7.1.zip`.
2. Extraia em uma pasta do usuário (ex.: `Documentos\GPI-0.7.1`). Não precisa de Python, Node, Docker, banco de dados,
   GPU nem administrador.
3. Para **preservar os dados da versão anterior**, não apague `%LOCALAPPDATA%\GPI`: a v0.7.1 abre o mesmo banco. Antes de
   migrar, o GPI faz uma cópia automática em `%LOCALAPPDATA%\GPI\backups\gpi_antes_migracao_*.sqlite`.

## Roteiro de aceitação (marque cada item)
| # | Ação | Resultado esperado |
|---|---|---|
| 1 | Extrair o ZIP | pasta `GPI` com `GPI.exe` |
| 2 | Duplo clique em `GPI.exe` | navegador abre `http://127.0.0.1:8765` (SmartScreen pode avisar: o executável não é assinado — siga a orientação da TI) |
| 3 | Dashboard | painéis Produtos em destaque, Tendências emergentes, Crescimento consistente, Alertas, Comparação internacional, Saúde das fontes |
| 4 | Dados históricos | Inteligência de Consumo → Brasil / Mais pesquisados mostram o que já foi coletado |
| 5 | Central de Integrações | estados de cada integração; Mercado Livre conectado continua conectado |
| 6 | Sincronizar uma fonte autorizada | Mercado Livre → **Sincronizar** (ou Sincronização → **Atualizar fonte**): requisições > 0, "Concluído" com N novos registros |
| 7 | Ver dados coletados | Fontes e Sistema → Saúde das Fontes: matriz A–F, registros e "Ligados a produtos" |
| 8 | Abrir um produto | clique em um produto do ranking |
| 9 | Insights | seção **INSIGHTS DO GPI** no topo do produto |
| 10 | Previsões | aparecem só quando há histórico mensal suficiente (≥ 12 meses); caso contrário, aviso "exploratória" |
| 11 | Exportar Excel | botão Exportar Excel no topo da página |
| 12 | Exportar PDF | botão Exportar PDF |
| 13 | Fechar | ícone de encerrar ou `Stop_GPI.bat` |
| 14 | Abrir novamente | dados e relatórios continuam no Histórico |
| 15 | Dados preservados | contagens da Saúde das Fontes iguais às de antes |

## Teste offline (sem internet)
Desconecte a rede (ou use o modo avião) e repita os passos 2–4, 8–15: o GPI abre com os dados locais; as fontes externas
aparecem com falha de rede, sem impedir o uso. Nenhum dado demonstrativo é exibido como real (relatórios com dados
sintéticos levam a marca DEMONSTRAÇÃO).

## Se algo falhar
* Fontes e Sistema → Saúde das Fontes → copie a linha da fonte (fase e último erro).
* Sincronização → **Exportar diagnóstico** (não contém credenciais) e envie o arquivo.
* Bloqueio de execução pela política da empresa: não tente contornar — peça à TI a liberação do `GPI.exe` pelo hash
  SHA-256 publicado.
