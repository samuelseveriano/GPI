# GPI v0.9 — Relatório de auditoria inicial

Feito **antes** de qualquer alteração, sobre o código real da `main` em 05/11/2026 (commit `6e710eb`, v0.8.2 completa:
PRs #13–#16 mesclados). Branch de trabalho: `feature/gpi-v0.9-product-intelligence`.

Tipos de causa: **1** falta de dados · **2** falha de integração · **3** interpretação semântica · **4** modelo
estatístico · **5** regra restritiva · **6** erro de associação · **7** falta de histórico · **8** mistura demo/real ·
**9** apresentação.

## 1. Estado do repositório

| Item | Verificado |
|---|---|
| Versão na `main` | 0.8.2, completa (Worker, conformidade eBay, correção do OAuth Meta). |
| Migrações SQLite pendentes | nenhuma no código; a v0.9 cria tabelas novas sem alterar as existentes. |
| Dados demonstrativos | existem só em **Vendas Próprias** (`imports.is_demo = 1`, origem "DADOS DEMONSTRATIVOS (sintéticos)"). O motor de oportunidades (`intel/`) **não lê** `sales`: hoje a demonstração não entra nos rankings — mas não havia rótulo de origem por observação nem teste que garantisse isso. O painel sintético do autoteste fica só em memória. |
| IA local | opcional; modo Essencial sem LLM preservado. |

## 2. Causas verificadas das observações

| Observação | Causa verificada | Tipo |
|---|---|---|
| Vídeo de **campainha** associado a **fechadura** | O casador calcula a relação com o produto consultado (`estado_alvo` = "outro produto"), mas o conector do YouTube decide pelo campo genérico `estado` ("confirmada"). **Reproduzido**: `match("Campainha inteligente com câmera…", target="fechadura+inteligente")` → `estado = confirmada`. | 6 |
| "Video doorbell **vs** smart lock" vira fechadura | Dois produtos da mesma categoria no mesmo texto não eram tratados como comparação; o casador escolhia um. | 3 |
| Produtos genéricos (celular, cadeira, carregador) | O léxico identifica família e alguns modificadores; **marca e código de modelo não são extraídos** (JBL Tune 520BT, HY300, Xiaomi S10 → sem modelo). Não há níveis persistentes categoria → família → produto → variante → modelo. | 3 |
| Notícia tratada como produto | "Anatel apreende carregadores…" → "família de produtos": o filtro de notícias não cobre verbos como *apreende*. | 3 |
| Vídeos de brinquedo/entretenimento em famílias comerciais | "Brinquedo slime caseiro DIY" → família *toy* confirmada; contexto (entretenimento × review) não separado. | 3 |
| "Mais criticados" com produtos neutros | Ranking pelo menor saldo `(pos − neg)/n`: produto com muitas opiniões neutras e poucas negativas entra como "criticado". Fontes (notícia, discussão, avaliação de comprador) não são separadas. | 4 · 9 |
| 6 produtos com evidência comercial; cobertura comercial 3,4% | Só o ranking de buscas do Mercado Livre fornece evidência comercial autorizada; Google Ads/BigQuery não configurados. A cobertura é **correta** (6 ÷ 174). | 1 · 2 |
| Nenhum crescimento comercial confirmado | O ranking do ML tem poucas semanas; crescimento confirmado exige série com histórico — ausência **legítima**. | 7 |
| Nenhuma investigação recomendada | A regra exige evidência comercial persistente — correta. Faltava dizer **o que fazer** com sinais novos (estágios e próximas ações). | 9 |
| 66 alertas estatísticos × 3 comerciais | Alertas recalculados a cada execução, sem estado (novo/conhecido) nem histórico — o mesmo evento reaparece. | 9 |
| Lista de Investigação manual | A ficha não é preenchida com o que o dossiê já tem. | 9 |

## 3. Cloudflare D1 — "No SQL statements detected."

* O SQL de `0001_init.sql` é válido (testado em SQLite e no simulador oficial do D1 no CI da v0.8.2).
* O Console do D1 remove linhas que começam com `--` (regex `/^\s*--.*/gm`, a mesma do D1 remoto) e responde
  exatamente "No SQL statements detected." quando nada sobra ([cloudflare/workers-sdk#16686](https://github.com/cloudflare/workers-sdk/pull/16686)).
* O arquivo começa com comentários. **Reproduzido**: se as quebras de linha se perdem ao colar, o texto vira uma linha
  iniciada por `--` e é descartado inteiro. Também ocorre se só o cabeçalho for colado.
* Não foi possível verificar o que foi colado nem se o Worker publicado é o da v0.8.2 (o endereço não é acessível
  daqui) — o guia traz a verificação pelo navegador.

## 4. Meta — "Invalid Scopes: pages_show_list, pages_read_engagement"

* Documentação oficial: o caso de uso **"Authenticate and request data from users with Facebook Login" é
  incompatível com "Manage everything on your Page"**, e casos de uso não podem ser removidos depois de criado o app.
* O app `1663502878474287` foi criado com o caso de uso de Login → permissões de Páginas nunca serão aceitas nele.
  Pôr o escopo na URL não resolve.
* Instagram: o objetivo do GPI (hashtags e descoberta de contas) só existe na **Instagram API with Facebook Login**
  (Página vinculada, `instagram_basic` + `pages_show_list` + `pages_read_engagement`, recurso *Instagram Public
  Content Access* com revisão; 30 hashtags únicas por 7 dias). A *Instagram API with Instagram Login* não oferece
  busca de hashtags.
* Biblioteca de Anúncios: endpoint `ads_archive`; anúncios comerciais completos só para a UE (fora dela, só temas
  sociais/eleitorais/políticos); exige acesso à API da Biblioteca (confirmação de identidade).
* O GPI usava um único app para todos os módulos → precisa de **um app de Login (atual) e outro para os módulos de
  negócio**, mantendo o Login básico intacto.

## 5. Políticas

* YouTube (Derived Metrics Policy): somas, médias e *content tags* são permitidas se **distinguidas** dos dados da
  API e informadas como do GPI; combinação com outras plataformas não é tratada — o GPI mantém o YouTube separado e
  fora da confirmação de demanda.
