# Centro de Relatórios (GPI v0.6)

Menu **Relatórios → Centro de Relatórios**. Cada cartão gera o relatório em Excel, PDF ou CSV com os
filtros escolhidos (país, categoria, produto, fonte, período). Tudo é gerado neste computador: não é
preciso Excel, Word, LibreOffice nem internet.

## Tipos

| Relatório | Conteúdo principal |
|---|---|
| Radar Global de Produtos | ranking, histórico, países, redes sociais, previsões, oportunidades, fontes, dados brutos permitidos |
| Produtos Mais Pesquisados | volume aproximado de buscas (Google Ads/Bing). **Sem fonte de volume, o título vira "Ranking de Interesse Relativo"** |
| Tendências por País | crescimento, emergentes, declínio e cobertura das fontes de um país |
| Social Media Intelligence | situação das plataformas, Social Trend Score, Viral Radar, indicadores e hashtags |
| Previsões e Machine Learning | modelo, horizonte, previsão, intervalos 80/95%, WAPE, comparação de modelos, sinais sociais com × sem |
| Oportunidades de Importação | as nove dimensões do Opportunity Engine 3.0, riscos e próximas investigações |
| Análise Individual do Produto | identificação, variantes, especificações, tendências, comparação internacional, concorrência, reviews, previsões, riscos |
| Relatório Executivo | resumo, panorama, destaques, tendências internacionais, evidências, oportunidades, riscos, limitações, próximas investigações, fontes |

## Excel
Abas: Resumo Executivo · Ranking de Produtos · Histórico de Indicadores · Tendências por País · Redes Sociais ·
Forecasting · Oportunidades · Fontes e Metodologia · Dados Brutos Permitidos · Gráficos (conforme o tipo).
Tabelas do Excel com filtro, painéis congelados, datas DD/MM/AAAA, porcentagens, hiperlinks para as fontes,
cores nos scores e no crescimento, gráficos nativos e fórmulas de verificação no Resumo (recalculadas ao abrir).
Textos vindos de APIs que começam com `= + - @` são gravados como texto (proteção contra injeção de fórmulas).

## PDF
Capa, sumário, cabeçalho, "Página X de Y", A4 vertical para texto e A4 horizontal para tabelas largas,
gráficos simples. Fonte DejaVu Sans embutida (acentuação completa). Nomes em chinês usam uma fonte CJK do
Windows (Microsoft YaHei/SimSun), embutida por subconjunto; sem ela, a fonte CID padrão do leitor de PDF.
Tabelas longas mostram até 150 linhas (60 no histórico e nos dados brutos) e indicam que a lista completa está no Excel.

## Natureza dos dados
Toda tabela informa se o dado é **Observado** (coletado), **Estimado** (aproximação oficial da fonte),
**Projeção** (previsão de modelo) ou **Derivado** (índice calculado pelo GPI).

## Demonstração
Se a base contém dados demonstrativos (vendas de demonstração ou base de teste), o relatório inteiro recebe
faixa vermelha e marca d'água **DEMONSTRAÇÃO**.

## Histórico, reprodução e auditoria
**Relatórios → Histórico** lista tipo, período, data, país, filtros, versão dos modelos, versão dos dados,
arquivo, tamanho e status. Ações: Abrir (PDF), Baixar, **Reproduzir** (mesmos números, a partir do snapshot
guardado com o relatório), **Gerar novamente** (mesmos filtros, dados atuais) e Excluir (com confirmação; o
registro fica para auditoria). Nenhum arquivo é sobrescrito. Cada relatório tem um identificador de execução
impresso no documento.

## Exportação por página
As páginas Dashboard, Oportunidades, Mais Pesquisados, Brasil/EUA/China, Comparação Internacional, Emergentes,
Alertas, Redes Sociais, Viral Radar, Produto, Previsão de Tendências e Modelos mostram **Exportar Excel** e
**Exportar PDF** na barra superior, com o período escolhido ao lado. O país ou produto da página vira filtro do relatório.

## Relatório semanal automático
Desligado por padrão. Ligue em Centro de Relatórios ou em Configurações (`auto_report_weekly`). Depois de uma
sincronização concluída (e no máximo uma vez a cada ~7 dias) o GPI gera o Relatório Executivo em PDF e Excel e
mostra um aviso na barra superior. Se o GPI estava fechado, o relatório pendente é gerado na próxima abertura.
Nada é enviado para fora do computador.
