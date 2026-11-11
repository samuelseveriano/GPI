# GPI v0.9.1 — Trade Intelligence + Product Intelligence

Reestruturação funcional sobre o MVP (`40affd6` + `c82ad36`). Nada foi reconstruído: os módulos novos reutilizam o
cadastro de empresas/embarques, o Product Understanding, o Listing Match, o Opportunity Engine, a IA local (llama.cpp)
e a exportação existentes.

## Fontes (ver *Fontes e Sistema → Matriz de Fontes*)
| Fonte | Uso | Acesso | Estado no código |
|---|---|---|---|
| Comex Stat (MDIC) `POST /general` | NCM 8 / SH4 × país × mês (FOB, kg, quantidade) | público | consulta direcionada `suite/trade.py` (cache 7 dias, 429 diagnosticado) + conector SH4 existente |
| U.S. Census International Trade API | HS 2–10 × país × mês (valor, quantidade) | público, chave opcional (`census.api_key`) | consulta direcionada; totais/agrupamentos excluídos da partição |
| UN Comtrade | China → EUA/Alemanha/México | público/chave gratuita | conector existente |
| USITC DataWeb | HTS × país | conta gratuita + token | **consulta manual** (API não integrada nesta versão) |
| CBP — manifestos (B/L) | embarques individuais EUA | sem API pública gratuita por empresa | **importação documental** |
| Arquivos do usuário | B/L, manifestos, planilhas (PDF textual, TXT, CSV, XLSX) | local | `suite/shipments.py` |
| ImportYeti | embarques EUA | pago, opcional | adaptador existente, desligado no modo sem custos |
| Páginas públicas de produto | Schema.org/JSON-LD, OpenGraph, tabelas | só se termos + robots.txt permitirem | `suite/webextract.py` |

Validação com as APIs reais (Comex Stat por país, Census) **não foi possível no ambiente de desenvolvimento** (rede
bloqueada); os formatos seguem a documentação pública e os testes usam respostas simuladas. Se a resposta real divergir,
o diagnóstico mostra "formato" com as chaves recebidas.

## Módulos novos
- `suite/trade.py` — códigos candidatos (SH4 do núcleo do produto + NCM oficial carregada), coleta, análise
  determinística (mensal, anual, acumulado, 12m × 12m, CAGR só com ≥ 3 anos completos, países e mudanças de participação,
  anomalias por z robusto, elegibilidade de previsão), modo degradado com séries SH4 locais, ranking de posições SH4.
- `suite/shipments.py` — leitura de B/L/manifestos por rótulo explícito, deduplicação, portos de embarque/chegada,
  transportadora, investigação por empresa (identidade por nome normalizado; parecidos nunca unidos), classificação da
  carga, concentração de parceiros, evolução. Sem registros: "Não há registros de embarques individuais disponíveis nas
  fontes conectadas."
- `suite/webextract.py` — SSRF (DNS checado a cada redirecionamento), lista de sites com termos restritivos/API oficial,
  robots.txt (erro 5xx = não coleta), 2 MB, só HTML, conteúdo tratado como evidência não confiável (padrões de injeção
  removidos).
- `suite/analyst.py` — Assistente de Inteligência: intenção → ferramenta do GPI → resposta com conclusão, dados,
  métricas, fontes, período, confiança, limitações e próximas investigações. IA local opcional apenas reescreve a
  conclusão; números ausentes dos fatos invalidam o texto da IA.
- `suite/sources_matrix.py` — matriz de fontes com estados verificáveis.
- Opportunity Engine: `dimensoes_agrupadas` (Interesse, Mercado, Comércio exterior, Viabilidade, Confiabilidade) e
  `comercio_exterior` (contexto da posição SH4 — não entra no índice).

## API
`GET /api/suite/trade/painel` · `GET /api/suite/trade/relatorio?q=&codigo=&mercado=BR|US&meses=` (+ `.xlsx`/`.pdf`) ·
`GET /api/suite/embarques/empresa?nome=&pais=` (+ `.xlsx`/`.pdf`) · `GET /api/suite/embarques/resumo` ·
`POST /api/suite/embarques/classificar {texto}` · `POST /api/suite/importar/embarques` (agora aceita PDF/TXT) ·
`GET /api/suite/web/pagina?url=` · `POST /api/suite/assistente {pergunta, ia}` · `GET /api/suite/fontes/matriz`.

## Interface
Novas telas: *Início* (escolha dos dois motores, também no topo do Dashboard), *Assistente IA*, *Trade Intelligence →
Painel de Importações / Empresas e Embarques*, *Fontes e Sistema → Matriz de Fontes*. Os grupos do menu passaram a se
chamar *Product Intelligence* e *Trade Intelligence*; as demais telas foram mantidas.
