# GPI v0.8 — Teste no computador corporativo

## Preparação

1. Baixe `GPI-Windows-Portable-v0.8.zip` (artefato do GitHub Actions; o link está no PR) e confira o SHA-256 em
   `SHA256SUMS.txt`: `Get-FileHash .\GPI-Windows-Portable-v0.8.zip`.
2. Extraia em uma pasta do usuário. Não é preciso Python, Node, Docker, banco de dados, GPU nem permissão de
   administrador.
3. **Não apague `%LOCALAPPDATA%\GPI`**: a v0.8 abre o mesmo banco. Antes da migração para o esquema 9, ela faz uma
   cópia automática em `%LOCALAPPDATA%\GPI\backups\gpi_antes_migracao_v8_para_v9_*.sqlite`.

## Roteiro de aceitação (critério de sucesso da v0.8)

| # | Ação | Resultado esperado |
|---|---|---|
| 1 | Duplo clique em `GPI.exe` | o navegador abre `http://127.0.0.1:8765`. O SmartScreen pode avisar porque o executável não é assinado: siga a orientação da TI |
| 2 | Dashboard | 8 seções: visão executiva, top para investigar, radar comercial, emergentes, consistentes, alertas, comparação internacional e insights |
| 3 | Dados reais | Visão executiva com "Com dados recentes" > 0 após sincronizar |
| 4 | Produtos monitorados | Catálogo e KPI "Produtos monitorados" |
| 5 | Significado dos indicadores | Fontes e Sistema → **Qualidade dos Dados** → catálogo semântico (o que cada métrica "não é") |
| 6 | Evidências por produto | clique num produto → **Dossiê**: índices separados, evidências por tipo, linhagem |
| 7 | Sinais comerciais | Mercado Livre → Sincronizar. No dossiê, "Ranking de mais buscados": semanas presente, melhor posição, sem % de volume. Na 1ª semana: **NOVO SINAL COMERCIAL** |
| 8 | Tendência × sinal insuficiente | situações como "Sinal em observação" e "Variação não confirmada" no lugar de "crescendo"/"declínio" sem evidência |
| 9 | Análises válidas | Qualidade dos Dados → Gate 4 mostra o que cada série permite e por quê |
| 10 | Previsões | só em séries elegíveis (≥ 18 meses). Nas demais, o motivo aparece no dossiê |
| 11 | Por que investigar | Dashboard → Top produtos: próxima ação, ou o motivo de estar "em observação" |
| 12 | Comparar mercados | Dashboard seção 7 (só com dados comparáveis) |
| 13 | Anatel | Conformidade → Homologações e Certificados → **Atualizar dados da Anatel**. Depois, **Empresas com Produtos Homologados** → pesquisar "carregador": titulares, fabricantes, situação |
| 14 | Inmetro | mesma página: **Importar arquivo oficial** (baixado no portal de dados abertos) ou **Registrar consulta manual assistida** |
| 15 | Modelos e fabricantes | pesquisa por modelo: correspondência EXATA, PROVÁVEL ou SEMELHANTE, com fonte oficial |
| 16 | Comparar especificações | "Comparar produto com registro existente" |
| 17 | Checklist | Conformidade → Analisar Produto → análise → Checklist (pt/en/zh) |
| 18 | Relatórios | Centro de Relatórios → Executivo (5–6 páginas), Técnico e Homologações (PDF e Excel) |
| 19 | Fechar e reabrir | dados, relatórios e Lista de Investigação preservados |

## Teste offline

Desconecte a rede e repita os passos 1–6, 9, 18 e 19. O GPI abre com os dados locais; falhas de API não impedem o
acesso ao histórico.

## Se algo falhar

- Qualidade dos Dados: anote o gate reprovado e a verificação.
- Sincronização → **Exportar diagnóstico** (o arquivo não contém credenciais).
- Bloqueio pela política da empresa: não tente contornar. Peça à TI a liberação do `GPI.exe` pelo hash SHA-256
  publicado.
