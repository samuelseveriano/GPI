# Worker `gpi-ebay-notifications`

Endpoint Marketplace Account Deletion do eBay + fila de exclusões para o GPI local. Arquivo único, sem dependências
(pode ser colado no editor do painel da Cloudflare).

* `src/index.js` — Worker (GET de verificação, POST com assinatura oficial ECDSA/SHA-1, API `/gpi/v1/*` com HMAC).
* `migrations/0001_init.sql` — tabelas do D1 `gpi-ebay-notifications-db` (idempotente).
* `tests/worker.test.mjs` — `node --test tests/worker.test.mjs` (D1 sobre SQLite do Node).
* `tests/workerd.test.mjs` — mesmo fluxo no runtime real do Cloudflare (Miniflare), executado no CI.
* `wrangler.jsonc` — só para quem publica por linha de comando (preencha `database_id`). Nenhum segredo aqui.

Passo a passo de publicação pelo painel: [docs/EBAY_CLOUDFLARE_SETUP.md](../../docs/EBAY_CLOUDFLARE_SETUP.md).

| Rota | Quem chama | Autenticação |
|---|---|---|
| `GET /ebay/notifications?challenge_code=` | eBay | — (resposta é o hash exigido pelo eBay) |
| `POST /ebay/notifications` | eBay | cabeçalho `x-ebay-signature` verificado com a chave pública do eBay |
| `GET /gpi/v1/status`, `GET /gpi/v1/history` | GPI | HMAC-SHA256 (`EBAY_GPI_SYNC_TOKEN`) + horário ±5 min + nonce único |
| `POST /gpi/v1/claim`, `POST /gpi/v1/ack`, `POST /gpi/v1/selftest` | GPI | idem |

Respostas ao eBay: **204** só depois de gravar no D1; **412** assinatura inválida/ausente; **400** mensagem malformada
ou tópico não suportado; **500** quando não é possível verificar ou gravar (o eBay reenvia).
