# v0.9.1 — Revisão do PR #18: pesquisa direcionada e validação

Correções aplicadas na própria branch do PR #18 (sem nova versão, sem merge).

## 1. Pesquisa em duas camadas

`backend/gpi/suite/targeted.py` (novo) executa **consultas direcionadas** reaproveitando os conectores existentes
(mesmos tokens, limites, cache HTTP, pseudonimização de vendedores e tabelas):

| Fonte | Capacidade | Quando | Credencial |
|---|---|---|---|
| Mercado Livre — busca de anúncios (`/sites/MLB/search`) | marketplace_listings | rápida e completa (BR) | OAuth do usuário |
| eBay Browse | marketplace_listings | rápida e completa (US) | Client ID/Secret + fluxo de exclusão de contas |
| Google Ads Keyword Planner | search_volume (12 meses) | rápida: mercado principal · completa: + comparação | OAuth + conta Google Ads |
| Microsoft Advertising | search_volume | completa | OAuth + developer token |
| YouTube Data API | product_search (vídeos) | completa | chave da API (cota diária do GPI) |
| GDELT | news_mentions (atenção pública ≠ demanda) | completa | pública |

Não consultadas por produto (e o diagnóstico diz por quê): Google Trends RSS e BigQuery (só termos em alta), ranking de
tendências do Mercado Livre (lista geral) e Comex Stat (só pela NCM candidata). Um produto **ausente do SQLite** é
entendido pelo Product Understanding; com identificação **confirmada**, ganha registro canônico no catálogo
(`Catalog.observe`, origem `pesquisa_usuario`); sem identificação, a investigação segue pelo termo digitado.

## 2. Rápida × completa

| | Rápida | Completa |
|---|---|---|
| Cache | 7 dias; com evidências locais não consulta externamente (salvo "Atualizar") | 1 dia — reaproveita a rápida do mesmo dia |
| Fontes | ML, eBay, Keyword Planner no mercado principal | + Microsoft Ads, YouTube, GDELT e mercados de comparação |
| Análises | avaliação preliminar | tendência/regime/aceleração/sazonalidade e previsões elegíveis, similaridade visual |

## 3. Progresso × cobertura

Estados das etapas: concluída com dados · concluída sem dados · ignorada por configuração · não autorizada ·
indisponível · falhou · cancelada. O painel mostra **Progresso do processamento** (etapas encerradas ÷ previstas) e
**Cobertura da investigação** (fontes que trouxeram evidência útil). Sem evidência: "Processamento concluído — dados
insuficientes para análise comercial." Pesquisas podem ser canceladas.

Decisão: evidências diretas também contam (`research.direct_stage`): VERDE exige identificação confirmada e ≥ 12 meses de
volume autorizado com crescimento estatisticamente significativo; anúncios e pouco histórico → AMARELO; notícias e
vídeos **não** sobem o estágio.

## 4–7. Identificação, semelhantes, fornecedores e diagnóstico

* `suite/naming.py`: ID canônico interno (`charger+gan:65w`) × **nome comercial** ("Carregador GaN 65W"), família,
  variante, características e traduções na resposta e na interface.
* Semelhantes em 6 classes: possível mesmo produto, variante da mesma família, tecnicamente semelhante, mesma categoria
  (marcado "NÃO é equivalente"), similaridade visual (aviso de fabricante) e não confirmada.
* Fornecedores: cada candidato traz tipo de correspondência (fabricante confirmado · fabricante documentado em registro
  regulatório · exportador por embarques · fornecedor declarado · fornecedor cadastrado · candidato por similaridade),
  fonte, evidência concreta (documentos/registros), comprovação, confiança e limitações. **Origem do candidato visto na
  revisão:** a regra "exportador (embarques)" sobre a planilha de embarques SIMULADA importada no teste da interface —
  ou seja, dado de teste; agora esses arquivos podem ser marcados como demonstrativos.
* Painel **Fontes e cobertura desta investigação** (também exportado): capacidade, integração, autenticação, consulta
  feita, resultado, registros válidos, motivo concreto, última coleta e ação recomendada.

## 8–9. Dashboard e monitoramento

* Dashboard: produtos cadastrados × identificados × com evidência comercial × monitorados × investigação concluída ×
  inconclusiva. Importações marcadas como **demonstrativas** ficam fora das contagens e aparecem num aviso.
* "Monitorar semanalmente" grava termos (pt/en), mercado e fontes; na sincronização seguinte (mesma rotina semanal) as
  consultas compatíveis são repetidas em modo rápido (cache/cotas respeitados). Não depende do Radar Comercial.

## O que foi testado de verdade

| Integração | Teste |
|---|---|
| Mercado Livre, eBay, Google Ads, Microsoft Ads, YouTube | **simulado** (respostas falsas em `tests/test_v091_targeted.py`); sem credenciais neste ambiente |
| GDELT | **real** no CI (`scripts/real_targeted_research_v091.py`, job real-data-audit). No ambiente de desenvolvimento o proxy bloqueia — registrado como "indisponível", não como falha |
| Comportamento sem credenciais | **real** (banco vazio, servidor real): todas as fontes privadas aparecem como "não autorizada" com o motivo, decisão CINZA, "dados insuficientes" |

Pendente no Windows/no seu computador: executar uma pesquisa completa com as suas integrações conectadas (Mercado Livre,
eBay, Google Ads) — é a única forma de validar as consultas autenticadas reais.
