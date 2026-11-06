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

---

# Correções finais (validação com dados reais)

## Coberturas que não se misturam

| Cobertura | Conta | Não conta |
|---|---|---|
| **Comercial** | volume de buscas autorizado (Keyword Planner/Bing), histórico local de procura, anúncios e preços anunciados do mercado principal (oferta observada), histórico de preços (≥ 2 coletas) | imagens, notícias, vídeos, fornecedores; anúncios nunca viram vendas |
| **Contextual** | notícias (GDELT, global), vídeos (YouTube), imagens do catálogo visual, produtos relacionados, categoria | — não comprova intenção de compra |
| **Técnica** | identificação confirmada, família, variante, especificações explícitas, fornecedores candidatos, NCM candidata, registros regulatórios | — |
| **Confiança da investigação** | alta (≥ 2 fontes comerciais no mercado principal + identificação confirmada) · média (1 fonte) · baixa (só contexto/técnica, ou identificação não confirmada) · insuficiente | |

A cor continua dependendo só de evidências elegíveis: apenas imagens e/ou fornecedores → **CINZA**. `cobertura.fontes_com_evidencia`
passou a contar só fontes comerciais (as demais aparecem em `fontes_contextuais`).

## Erros HTTP com causa específica (`connectors/http.py` + `suite/diagnostics.py`)

| Situação | Estado | Mensagem |
|---|---|---|
| HTTP 429 | Limite de requisições | "Limite de requisições atingido." — `Retry-After` respeitado, backoff exponencial com teto, nº de tentativas e espera total limitados |
| Túnel/proxy recusou (CONNECT 403/407, `X-Squid-Error`, `Proxy-Authenticate`) | Bloqueada pela rede | "Não foi possível estabelecer conexão com a fonte. Verifique as configurações de rede ou consulte a TI." — sem novas tentativas, sem contorno |
| 403 do servidor sem credencial | Indisponível | "o servidor de destino recusou o acesso (HTTP 403)" |
| 403 com credencial | Permissão insuficiente | credencial válida, sem permissão para o recurso |
| 401 | Token expirado | token ausente/inválido/expirado |
| DNS · TLS · timeout · conexão recusada · 5xx | Indisponível / Bloqueada pela rede (TLS) | causa própria em cada caso |

O GDELT indisponível não interrompe a pesquisa completa; as outras fontes seguem e o motivo fica registrado.

## Mercados

* Rápida: só fontes do **mercado principal**. Brasil não consulta o eBay (EUA) como substituto — aparece como "não cobre o mercado".
* Completa: principal + comparativos escolhidos + fontes globais. Anúncios e volumes de mercados comparativos aparecem separados e
  não entram na decisão do mercado principal.
* GDELT é **GLOBAL** e nunca é atribuído ao Brasil.
* China (ou outro país sem conector): "Não existem fontes de consulta direcionada disponíveis para este mercado." — nada americano
  como substituto silencioso.

## Diagnóstico de Integrações (Fontes e Sistema → Diagnóstico de Integrações)

Nome, configuração, autenticação, permissões verificadas, capacidades, última tentativa, último sucesso, erro recente, dados e
ação necessária, com os estados: Não configurada · Configurada · Autorizada · Funcional · Funcional sem resultados · Permissão
insuficiente · Token expirado · Bloqueada pela rede · Limite de requisições · Indisponível. "Testar conexão" reaproveita o teste da
Central (operação de baixo custo; não consome créditos; não altera credenciais). O Mercado Livre é testado em dois passos
(`users/me` e uma busca de 1 item) — credencial válida sem permissão de busca aparece como **Autorizada**, não Funcional.
"Configurar" abre a Central já posicionada na integração (`#integracoes/<id>`).

## Mercado Livre

* Busca oficial `sites/MLB/search` com o token OAuth do usuário; callback HTTPS e fluxo de autenticação preservados.
* 401 → uma única renovação pelo refresh token oficial e nova tentativa; 403 → "permissão insuficiente" com as opções oficiais
  (DevCenter: aplicativo ativo, escopos, domínio MLB; reconectar); 429 → limite de requisições.
* Teste de pesquisa ("Fritadeira elétrica", "Carregador GaN 65W", "Aspirador robô"): produto, título, preço anunciado, moeda,
  marketplace, identificador, link, data da coleta e características — **sem gravar** e sem vendas.

## Cache

Chave = fonte + mercado + idioma + termo + produto + parâmetros da consulta + versão do método (data de coleta registrada).
Rápida: validade de 7 dias; completa: 1 dia (reaproveita a rápida do dia). "Atualizar fontes" força nova consulta, mas não repete
uma consulta idêntica com menos de 10 minutos e continua respeitando permissões, cotas, custos e políticas.

## APIs necessárias para os testes reais

| Fonte | Requisito |
|---|---|
| Mercado Livre | aplicativo no DevCenter + Conectar (OAuth) na Central; a busca pode exigir permissão específica do aplicativo |
| eBay | Client ID/Secret + fluxo Marketplace Account Deletion (Cloudflare) |
| Google Ads Keyword Planner | Entrar com Google + conta Google Ads com acesso Basic/Standard |
| Microsoft Advertising | OAuth + developer token + customer/account ID |
| YouTube | chave gratuita da Data API v3 |
| GDELT | nenhuma (público; sujeito a limite por IP) |

## Testes

`tests/test_v091_final.py` (21 testes, respostas simuladas) cobre os 21 itens pedidos; a suíte completa roda no CI. Dados reais:
somente o job real-data-audit (banco vazio, sem credenciais) — GDELT respondeu 429 no GitHub Actions e, neste ambiente de
desenvolvimento, o proxy bloqueia o endereço (agora classificado como "Bloqueada pela rede").

---

# MVP RC — integração dos dados

* **Sincronização eBay "30 requisições, 0 registros":** os anúncios eram gravados em `market_listings`, mas essa tabela não estava
  entre as tabelas contadas pela sincronização → o resultado e o diagnóstico diziam "sem dados". Corrigido (`market/sync.py`).
* **Carregador × cabo:** `suite/listing_match.py` classifica cada anúncio contra o produto (exato · variante compatível ·
  tecnicamente semelhante · mesma família · acessório · incompatível · não confirmada); preços mín./mediana/máx. só entre
  exato/variante, por unidade (kits/lotes divididos); concorrência "não avaliada" sem amostra suficiente (≥ 30 elegíveis, ≥ 2 coletas).
* **Opportunity Score 100 com "Evidência insuficiente":** o índice era renormalizado pelos pesos disponíveis (1 dimensão a 100 → 100).
  Agora fica como **parcial, não elegível** e a tela mostra componentes, pesos, contribuições e dimensões ausentes.
* **Nova evidência → recálculo:** consulta direcionada com dados invalida só os resultados dependentes (sem reiniciar).
* **URL de anúncio:** eBay `get_item_by_legacy_id` e Mercado Livre `/items`/`/products` (API oficial, credenciais do usuário);
  grava pelo mesmo fluxo (vendedor pseudonimizado; eBay só com o fluxo de exclusão de contas). Páginas comuns não são lidas.
* **Imagem por URL:** o download sempre falhava ("URL não devolveu uma imagem") porque o cliente HTTP devolve `{"_bytes": ...}`.
  Corrigido; HTML é detectado; link de anúncio → foto pela API oficial; busca por imagem oficial do eBay só com autorização marcada.
* **Assistente regulatório:** ficha de investigação (identificação, categoria, questões técnicas, requisitos "a confirmar" das
  regras fundamentadas, registros Anatel/Inmetro locais por classe de correspondência, checklist) + relatório preliminar XLSX/PDF.
* **Meta Business:** `config_id` (Facebook Login for Business) sem `scope`; Login básico inalterado; callback preservado.
* **Dashboard:** visão consolidada A–E (portfólio, mercado, concorrência, comércio exterior, qualidade) a partir do banco real.
* **Fornecedores na China:** link de verificação assistida no GSXT/SAMR (sem consulta automática).


## Finalização do MVP — evidência comercial → Opportunity Engine → Dashboard

- **Oferta observada por produto × mercado** (`market/reviews2.competition`, reaproveitado — sem novo motor): anúncios
  associados ao produto canônico e filtrados pelo Listing Match; só produto exato/variante compatível entra (cabos,
  acessórios, outros produtos e potências diferentes ficam fora; kits divididos por unidade). Indicadores: anúncios
  elegíveis/excluídos, preços mín/Q1/mediana/Q3/máx, faixas de posicionamento (quartis), vendedores (concorrentes
  observados), marcas declaradas e HHI, pressão competitiva (só com ≥ 10 elegíveis), dias de coleta e fonte rastreada.
  Uma coleta única nunca gera variação/crescimento.
- **Brasil × EUA**: eBay = EUA, Mercado Livre = Brasil; moedas nunca misturadas. O Opportunity Engine (índice para
  importação ao Brasil) usa na dimensão existente `competition_pressure` e em "Preços observados" **só** a oferta
  brasileira; a oferta dos EUA aparece como `oferta_observada` contextual (`afeta_indicadores_do_mercado: false`).
- Cada linha do Opportunity Engine distingue **Oferta observada · Interesse de pesquisa · Crescimento comprovado ·
  Informações contextuais · Evidência insuficiente**. Anúncio nunca conta como demanda; sem 2 dimensões de demanda o
  índice continua parcial (não elegível — CINZA).
- **Atualização após coleta**: `targeted.invalidate` → `refresh_commercial` recalcula só os indicadores e a linha de
  oportunidade dos produtos afetados (os demais ficam do cache). Volume de busca invalida os dependentes de busca
  (recalculados no próximo acesso). Resultados ausentes são recalculados sob demanda (`competition_cached`).
- **Dashboard**: concorrência por mercado (elegíveis, faixa, vendedores/marcas, pressão/estado) e contagem dos tipos
  de evidência; dossiê da pesquisa com "Indicadores comerciais" e exportação (aba "Oferta e oportunidade").
- **Comparador comercial** (até 5 anúncios ou `produto:<id>`): marca declarada, preço unitário, moeda, potência/
  capacidade/conector/tecnologias **só quando declaradas**, compatibilidade com o alvo, diferenças técnicas, vantagens
  observadas, limitações, fonte/mercado e síntese. Itens incompatíveis ficam fora da síntese.
- Cenário de demonstração (Carregador GaN 65W, EUA) coberto por `tests/test_v091_commercial.py` com respostas
  SIMULADAS; o teste autenticado com a Browse API real ocorre no computador do usuário.
- HTTP 429 de API pública: diagnóstico "Limite de requisições" (causa `limite`, HTTP 429), sem confundir com falha
  de implementação.
