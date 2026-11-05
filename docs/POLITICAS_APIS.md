# Políticas das APIs — o que o GPI faz e não faz (v0.9)

| Plataforma | Como o GPI usa | Restrições respeitadas |
|---|---|---|
| **YouTube** (Data API v3) | título, descrição, canal, data e métricas oficiais (visualizações, curtidas, comentários) | Métricas oficiais aparecem como "métricas oficiais do YouTube". O **contexto** (review, unboxing…) é classificação **do GPI**, identificada como tal — a Derived Metrics Policy permite tags e somas/médias desde que distinguidas dos dados da API. O YouTube não é combinado com outras plataformas nem usado como confirmação de demanda. |
| **Meta** (Facebook, Instagram, Anúncios) | módulos separados; Login básico num app, dados de negócio em outro | Casos de uso incompatíveis não são forçados; sem aprovação, o módulo fica "Aprovação necessária". Sem scraping. Anúncios comerciais só da UE. |
| **Mercado Livre** | ranking semanal de termos mais buscados | Posição não é volume; 1 semana não é crescimento sustentado. |
| **eBay** (Browse API) | anúncios ativos (EUA) | Coleta só com a conformidade de exclusão de contas; vendedor guardado como pseudônimo; sem cache de respostas; anúncios ativos não são vendas. |
| **Reddit** | discussões públicas | Relato de experiência ≠ avaliação de comprador; discussão geral não conta como opinião. |
| **Google Trends** (RSS e BigQuery) | interesse de pesquisa (índice relativo) | Índice relativo, não volume; idioma ≠ país. |
| **Microsoft Advertising / Google Ads** | volume de pesquisa (faixas) quando autorizado | Faixas marcadas como ESTIMADO. |
| **Wikimedia** | atenção pública | Nunca demanda comercial; nunca país. |

Funcionalidades que dependem de aprovação externa ficam desabilitadas com o motivo visível — nunca contornadas.
