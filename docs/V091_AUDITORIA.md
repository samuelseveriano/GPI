# v0.9.1 — Auditoria inicial (antes das alterações)

Objetivo: não reconstruir o GPI nem duplicar módulos. Cada componente pedido foi classificado.

| Componente pedido | Já existia | Decisão |
|---|---|---|
| Catálogo canônico, aliases, variantes | `products/catalog.py`, `catalog_products`, `product_aliases` | reutilizado |
| Product Understanding (taxonomia 5 níveis, atributos) | `intel/understanding.py` | reutilizado |
| Opportunity/Decision Engine, estágios, índices | `intel/service.py`, `intel/commercial.py`, `intel/decision.py` | reutilizado; cor da decisão é um mapeamento novo sobre os estágios |
| Data Quality / origem dos dados | `intel/quality.py`, `intel/semantics.origin_of` | reutilizado |
| Anúncios e preços | `market_listings` (eBay Browse) | reutilizado (sem nova coleta) |
| Palavras-chave observadas | `search_observations`, `discovery_candidates` | reutilizado |
| Tendências, sazonalidade, mudança de regime | `products/trends.py`, `analytics/classification.py` | reutilizado |
| Previsões | `forecasting/advanced.local_forecast` | reutilizado + validação na janela final |
| Avaliações | `market/content_intel.review_summary`, `nlp/reviews.py` | reutilizado; upload de CSV/XLSX é novo |
| NCM candidata | `compliance/ncm.NcmTable.candidates` | reutilizado |
| Comex Stat | `market_series` (`source='comexstat'`) | reutilizado como estatística agregada |
| Anatel/Inmetro | `regulatory/registry.py`, `regulatory/api.search_all` | reutilizado; relações fabricante↔titular são novas |
| Cadastro de fornecedores | `suppliers` (Conformidade) | **estendido** por cópia para `companies` (o antigo continua) |
| Lista de Investigação | `intel/investigations.py` | reutilizado (dossiê → Investigar) |
| Relatórios XLSX/PDF | `reports/xlsx.py`, `reports/pdf.py` | reutilizadas a proteção contra fórmulas e as fontes |
| Agendamento | sincronização semanal (`market/sync.SyncManager`) | monitorados atualizados no `analyzer` existente — sem agendador novo |
| Credenciais | cofre DPAPI (`sync.creds`) | reutilizado (chave ImportYeti) |
| Proteção SSRF / limite de corpo | `security.public_url_problem`, `BodyLimit` | reutilizado |
| Busca visual | — | **novo** (Pillow + NumPy, já presentes como dependências) |
| Empresas canônicas, embarques, rede de relações | — | **novo** |
| ImportYeti | — | **novo**, opcional, bloqueado por padrão |
| Simulador de custos | `market/viability.py` (viabilidade v0.6, outro escopo) | **novo** simulador só com parâmetros do usuário; a página antiga continua e é referenciada |

Dependências: nenhuma nova obrigatória. Pillow passou a constar explicitamente em `requirements.txt` (já era instalada
como dependência do ReportLab). Upload de arquivos usa corpo binário — sem `python-multipart`.
