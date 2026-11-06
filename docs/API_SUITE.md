# API local — Product Intelligence Suite (v0.9.1)

Servidor local `http://127.0.0.1:8765`. Requisições que alteram estado exigem o cabeçalho `X-GPI: 1` (como o resto do GPI).
Uploads são enviados como **corpo binário** (`Content-Type: application/octet-stream` ou `text/csv`), com o nome em
`X-Filename` (apenas exibido) e os campos na query string.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/suite/visao` | contagens, pesquisas recentes, modo sem custos |
| GET/POST | `/api/suite/config` | configurações (país, idioma, período, modo, cache, modelos opcionais, sem custos, orçamento, `importyeti_chave`) |
| GET | `/api/suite/provedores` | fontes, status, capacidades, custos, limitações; serviços não usados |
| POST | `/api/suite/pesquisa` | `{consulta, mercado, comparacao[], periodo_meses|inicio+fim, objetivo, profundidade: rapida|completa, atualizar?, sincrono?}` → `{id}` |
| GET | `/api/suite/pesquisa/{id}` | estado, etapas (7 estados), progresso do processamento, cobertura e resultado (dossiê + `fontes`) |
| POST | `/api/suite/pesquisa/{id}/cancelar` · `/monitorar` | cancelar · transformar em monitoramento semanal |
| POST | `/api/suite/pesquisa/{id}/salvar` | marcar como salva |
| GET | `/api/suite/pesquisa/{id}.xlsx` · `.pdf` | exportação |
| GET | `/api/suite/historico` | histórico de pesquisas |
| GET | `/api/suite/nichos?…filtros` | Niche Finder (`texto, categoria, preco_min, preco_max, crescimento_min, anuncios_min, anuncios_max, marcas_max, competicao, confianca_min, cobertura_min, atributo, cor, estagio_min, situacao, ordem`) |
| POST | `/api/suite/nichos/salvar` | `{nome, filtros}` |
| GET | `/api/suite/nichos.xlsx` · `.pdf` | exportação |
| GET | `/api/suite/palavras?termo=&mercado=` | Keyword Intelligence (+ `.xlsx`/`.pdf`) |
| GET | `/api/suite/palavras/anuncio/{id}` | hipóteses a partir de um anúncio coletado |
| GET | `/api/suite/anuncio?ref=` | anúncio por nome, URL ou ID (histórico de preços real) |
| POST | `/api/suite/anuncios/comparar` | `{refs: [...], alvo?: "<produto_id>"}` (até 5; anúncios ou `produto:<id>`; especificações só declaradas, compatibilidade, vantagens, limitações e síntese) |
| GET | `/api/suite/tendencias?produto=&horizonte=` | Trend & Seasonality Explorer |
| GET | `/api/suite/avaliacoes?produto=` | avaliações coletadas |
| POST | `/api/suite/avaliacoes/arquivo` | CSV/XLSX de avaliações (local) |
| POST | `/api/suite/imagem/buscar?familia=&recorte={x,y,w,h}&url=` | busca visual local (corpo = imagem, ou `url` pública) |
| GET/POST | `/api/suite/imagem/catalogo` | catálogo visual / adicionar (`rotulo, produto_id, familia, recorte`) |
| POST | `/api/suite/imagem/comparar` | `{a, b}` em base64 |
| GET | `/api/suite/imagem/{id}.jpg` · POST `/api/suite/imagem/{id}/excluir` | miniatura / exclusão |
| GET/POST | `/api/suite/empresas` | busca (`q, tipo, pais`) / cadastro |
| GET | `/api/suite/empresas/{id}` (+ `.xlsx`/`.pdf`) | perfil: empresa, embarques, cobertura, produtos, avaliação, rede |
| GET | `/api/suite/empresas/{id}/rede?profundidade=` | rede de relações |
| POST | `/api/suite/empresas/{id}/avaliar` | `{dimensao, campo, valor, tipo: documental|declarado|avaliação, fonte, documento}` |
| POST | `/api/suite/empresas/{id}/produtos` | vínculo produto↔empresa |
| GET | `/api/suite/empresas/{id}/correspondencia?q=&produto=&familia=` | correspondência preliminar |
| GET | `/api/suite/duplicidades` · POST `/api/suite/duplicidades/{id}` | fila de revisão; `{decisao: mesclar|distintas}` |
| POST | `/api/suite/importar/empresas` · `/api/suite/importar/embarques` | CSV/XLSX (`fonte` e `demonstrativo=1` opcionais) |
| POST | `/api/suite/relacoes` | relação manual `{a, b, tipo, status, fonte, evidencia, inicio, fim}` |
| POST | `/api/suite/relacoes/regulatorias` | relações a partir dos registros Anatel/Inmetro carregados |
| GET | `/api/suite/descobrir?q=&familia=&produto=` | fornecedores candidatos |
| GET | `/api/suite/importyeti` · POST `/importyeti/atualizacao` · POST `/importyeti/consulta` | status · consulta gratuita · consulta paga controlada (`consulta, parametros, autorizado, custo_maximo, gravar_embarques`) |
| GET | `/api/suite/importacao?q=&produto=` | Import Intelligence |
| POST | `/api/suite/simular` | `{parametros, salvar?, nome?, produto_id?}` |
| GET | `/api/suite/cenarios/{id}.xlsx` · `.pdf` | exportação de cenário |
| GET/POST | `/api/suite/monitorados` · POST `/monitorados/{id}/excluir` · POST `/monitorados/atualizar` | monitoramento |

Resposta padrão de consulta paga bloqueada: `{"ok": false, "bloqueada": true, "requisicao_feita": false,
"mensagem": "Consulta detalhada indisponível: créditos não autorizados ou insuficientes.", "motivo": "…"}`.
