# Registro de integrações — GPI v0.3 (Fase 3)

**Regra:** uma fonte só aparece como *funcional* na página **Saúde das fontes** depois de uma
coleta real validada **na instalação em uso**. Este documento registra o que foi implementado
e como foi verificado durante o desenvolvimento.

## Situação da verificação nesta entrega

O ambiente onde o código foi desenvolvido **não tinha acesso de rede** às APIs públicas
(todas as conexões eram bloqueadas). Por isso:

- Os conectores foram escritos a partir da documentação oficial e de clientes de código aberto
  dessas APIs, e os **parsers** foram testados com respostas sintéticas no formato documentado
  (`tests/fake_sources.py`, usadas somente nos testes).
- **Nenhuma coleta real foi executada durante o desenvolvimento.** A primeira coleta real
  acontece quando o GPI é aberto em uma máquina com acesso à internet. Se o formato real
  divergir do esperado, o conector falha com mensagem clara, não grava nada daquela coleta,
  e as demais fontes seguem funcionando.

| Fonte | Endpoint | Autenticação | Implementação | Confiança no formato |
|---|---|---|---|---|
| Banco Central — PTAX | `olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo` | não | completa (USD, CNY, EUR; diário + média mensal derivada) | alta — campos `cotacaoVenda`, `dataHoraCotacao`, `tipoBoletim` confirmados na documentação/clientes |
| Wikimedia — pageviews | `wikimedia.org/api/rest_v1/metrics/pageviews/per-article/...` e `en.wikipedia.org/w/api.php` (langlinks) | não (User-Agent identificado) | completa (46 conceitos × pt/en/zh, mensal desde 07/2015) | alta |
| Comex Stat (MDIC) | `POST api-comexstat.mdic.gov.br/general` | não | completa (todas as posições SH4, China e total, FOB e kg, mensal) | média — corpo da requisição confirmado no doc.yaml oficial; os nomes dos campos da resposta não constam do doc.yaml, então o parser aceita as variações conhecidas e falha de forma explícita se nenhuma corresponder |
| IBGE — PMC | `servicodados.ibge.gov.br/api/v3/agregados` | não | completa, com localização automática da tabela pelos metadados | média — se o IBGE renomear a pesquisa/tabela, o conector informa "tabela não localizada" |
| UN Comtrade (preview) | `comtradeapi.un.org/public/v1/preview/C/M/HS` | não (limitada) | completa (EUA, Alemanha, México ← China, posições prioritárias) | média — a API pública pode limitar volume ou passar a exigir chave |
| Feeds RSS (6 sites padrão, lista editável) | URLs dos feeds | não | completa (RSS 2.0 e Atom; rejeita XML com DTD) | alta para o formato; os endereços dos feeds podem mudar — cada feed mostra seu próprio erro |
| Google Notícias (RSS) | `news.google.com/rss/search` | não, mas exige aceite dos termos (opt-in) | completa, desativada por padrão | média |
| YouTube Data API v3 | `googleapis.com/youtube/v3/search`, `videos` | **chave de API** do usuário | completa; cota diária limitada pelo GPI; atualização/exclusão em 30 dias; sem NLP nem mistura com outras fontes (políticas do YouTube) | alta (documentação oficial); não testada ao vivo |
| Reddit | `www.reddit.com/api/v1/access_token` (installed client), `oauth.reddit.com/search`, `/comments` | **Client ID** + confirmação de uso autorizado | completa | média; uso comercial exige contrato com o Reddit |
| Mercado Livre — trends | `api.mercadolibre.com/trends/MLB` | **OAuth com PKCE** pela Central de Integrações | implementada; inativa até a conexão | não testada; o DevCenter precisa aceitar a URL de redirecionamento `http://127.0.0.1:8765/oauth/callback` |
| Trustpilot / Reclame Aqui / comparadores de preço | — | contrato/parceria | restritas (sem raspagem) | — |
| Amazon BR / US | PA-API 5 | credenciais de Associado | restrita (não implementada) | — |
| Shopee | Open Platform | parceiro aprovado | restrita | — |
| AliExpress / Alibaba / Taobao | Open Platforms | app key aprovada | restritas | — |
| Google Trends | API oficial em acesso restrito (alfa) | inscrição | restrita (substituída por Wikimedia para interesse público) | — |

Scraping não é usado em nenhuma fonte. Nenhum login, CAPTCHA, limite ou bloqueio é contornado.

## Lista de conectores validados com resposta real

**Nenhum até esta entrega.** O workflow do GitHub Actions executa `scripts/validate_connectors.py` num runner
com internet e publica `validacao_conectores.json` com o resultado real de cada fonte pública — esse arquivo é a
lista oficial de conectores validados. Na instalação do usuário, a página *Saúde das Fontes* marca "validada"
somente após a primeira coleta real bem-sucedida.

## O que verificar na primeira execução
1. Abrir o GPI e aguardar a sincronização (barra azul no topo).
2. Em **Saúde das fontes**, cada fonte pública deve ficar *funcional* com registros > 0.
3. Se alguma falhar, a coluna *Situação* mostra o motivo:
   - "falha de rede" / "acesso negado": a rede da empresa bloqueia o endereço (ver `docs/TI.md`);
   - "certificado TLS não verificado": configurar `ca_bundle` com a cadeia fornecida pela TI;
   - "campos esperados ausentes" / "tabela não localizada": a fonte mudou o formato — o log
     `data/logs/gpi.log` traz o detalhe para ajuste do conector.
