# Changelog

## 0.9.1 — Product Intelligence Suite (2026-11)

Somente ferramentas gratuitas; nenhuma dependência paga obrigatória.

### Adicionado
- **Trade + Product Intelligence**: Painel de Importações (Comex Stat por NCM/SH × país e U.S. Census por HS × país,
  evolução mensal/anual, 12m × 12m, CAGR, países, anomalias, modo degradado), Empresas e Embarques (importação de B/L e
  manifestos em PDF/TXT, investigação por empresa, classificação de carga), leitura de páginas públicas permitidas
  (Schema.org/OpenGraph, robots.txt, anti-SSRF), Assistente de Inteligência sobre as ferramentas reais do GPI, Matriz de
  Fontes, Início com os dois motores. Ver docs/V091_TRADE_PRODUCT.md.
- **MVP final — evidência comercial integrada**: oferta observada filtrada por equivalência técnica (sem cabos/
  acessórios) por produto × mercado alimenta as dimensões existentes do Opportunity Engine (só Brasil no índice; EUA
  como contexto), recálculo só dos produtos afetados após cada coleta, Dashboard com tipos de evidência, comparador
  comercial com especificações declaradas e síntese, aba "Oferta e oportunidade" na exportação.
- **Pesquisa de Produtos**: pesquisa por nome (pt/en), mercado, mercados de comparação, período (3/6/12/24 meses ou
  personalizado), objetivo e profundidade; 11 etapas reais com progresso gravado; dossiê com Visão geral, Demanda,
  Marketplaces, Produtos semelhantes, Fornecedores, Importação, Qualidade, Previsões e Evidências; salvar, histórico,
  exportação XLSX/PDF; "Investigar Produto" no dossiê.
- **Classificação da decisão** VERDE/AMARELO/VERMELHO/CINZA sobre os estágios da v0.9 (falta de dado = CINZA, nunca VERMELHO).
- **Registro de evidências** rastreável (`research_evidence`) sem dupla contagem.
- **Explorador de Nichos**, **Palavras-chave** (observadas × geradas; volume só de fonte autorizada; hipóteses por anúncio),
  **Inteligência de Marketplaces** (anúncio por nome/URL/ID, comparação de 5, histórico de preço real, tendências,
  avaliações coletadas e por arquivo).
- **Pesquisa por Imagem** local: JPG/PNG/WEBP, colar, arrastar, URL pública (com proteção SSRF), recorte, catálogo visual,
  6 classes de correspondência, embeddings ONNX opcionais, links de busca reversa assistida (Lens/TinEye/Yandex).
- **Inteligência de Fornecedores**: empresas canônicas, aliases, normalização (inclui sufixos chineses), fila de
  duplicidades com decisão humana, importação CSV/XLSX validada, embarques com deduplicação, relações
  documentadas/declaradas/inferidas/incertas, relações gratuitas a partir de Anatel/Inmetro, descoberta por produto,
  avaliação documental × declarada × do usuário, correspondência preliminar produto↔fornecedor.
- **ImportYeti** opcional com controle de créditos (bloqueado por padrão).
- **Investigação de Importação**: NCM candidata, estatísticas agregadas do Comex Stat, regulatório preliminar, riscos e
  simulador (FOB, frete por unidade, custos, custo total, margem, markup; cenários Conservador/Base/Otimista; pendências).
- **Monitorados** (produtos e fornecedores) atualizados na sincronização existente; **Provedores e custos**.
- Interface: 10 páginas em "Inteligência de Consumo" (o "Radar de Candidatos" passou para lá como "Radar Comercial"),
  cartões no Dashboard e atalhos no Dossiê.

### Alterado
- `requirements.txt` declara Pillow explicitamente (já vinha com o ReportLab).
- `tests/test_v05.py` passa a verificar as rotas dos módulos `v09*.js`.

### Revisão do PR #18
- Product Research em duas camadas: dados locais + **consultas direcionadas** por capacidade (Mercado Livre busca de
  anúncios, eBay, Google Ads KP, Microsoft Ads, YouTube, GDELT), com cache, cotas, falhas isoladas e motivos concretos.
- Rápida × completa com diferenças reais; estados explícitos das etapas; progresso × cobertura; cancelamento.
- Nome comercial × ID canônico; semelhantes em 6 classes; fornecedores com tipo de correspondência e evidência.
- Painel "Fontes e cobertura desta investigação"; Dashboard com contagens separadas e dados demonstrativos à parte.
- Monitoramento semanal a partir de uma pesquisa (termos, mercado e fontes). Ver docs/V091_REVISAO.md.

### Correções finais
- Coberturas comercial × contextual × técnica + confiança da investigação; imagens/notícias/fornecedores não contam como demanda.
- Erros HTTP com causa específica (429 com Retry-After e backoff limitado; 403 de proxy × servidor × permissão; 401; DNS/TLS/timeout/5xx).
- Seleção de mercados: sem substituição silenciosa (eBay EUA não vira Brasil); GDELT global; China sem cobertura informada.
- Página "Diagnóstico de Integrações" com "Testar conexão" e teste de pesquisa do Mercado Livre (sem gravar).
- Mercado Livre: renovação única em 401, mensagens para 403/429. Cache com chave completa e intervalo mínimo na atualização forçada.

### MVP RC
- Sincronização eBay passa a contar os anúncios gravados; carregador × cabo × acessório; preços comparáveis por unidade.
- Opportunity Score parcial (não elegível) com explicação; invalidação de resultados dependentes após nova evidência.
- URL de anúncio e imagem por URL pela API oficial (eBay/Mercado Livre); busca por imagem do eBay opcional.
- Ficha regulatória e relatório de conformidade preliminar; Meta Business com config_id; Dashboard consolidado A–E.

### Banco de dados
- Apenas tabelas novas, criadas sob demanda; nenhuma tabela existente alterada. Cadastro antigo de fornecedores copiado.
- Revisão: tabela `research_source_runs` (cache das consultas direcionadas) e coluna `monitored.params` (ADD COLUMN).
- Correções finais: colunas `cache_key`, `lang`, `product_id`, `params` em `research_source_runs` (ADD COLUMN).
