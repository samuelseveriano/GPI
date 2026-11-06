# eBay Production + Cloudflare — configuração (GPI v0.8.2)

Tudo abaixo é feito pelo **navegador** (painel da Cloudflare e portal do eBay). Não exige Node.js, Wrangler nem
privilégios de administrador no computador da empresa. Nenhum recurso pago é criado.

## Por que isso é necessário

O eBay desativa o keyset de Production ("Your keyset is currently disabled") até o app **assinar as notificações de
exclusão de contas** (Marketplace Account Deletion) **ou** obter isenção. A isenção só vale para apps que **não
guardam nenhum dado do eBay**. O GPI guarda histórico de anúncios do eBay (título, preço, item, vendedor) no SQLite,
então **não é elegível à isenção** — o caminho correto é o endpoint de notificações.

Fluxo: **eBay → Worker (verifica assinatura, grava no D1, responde 204) → GPI (ao abrir, a cada sincronização ou no
botão Sincronizar) → exclui os dados → confirma ao Worker → Worker apaga os identificadores.**

## 1. Publicar o Worker atualizado (painel web)

1. dash.cloudflare.com → **Workers & Pages** → `gpi-ebay-notifications` → **Edit code**.
2. Apague o conteúdo do arquivo aberto e cole **todo** o conteúdo de
   [`cloudflare/ebay-notifications/src/index.js`](../cloudflare/ebay-notifications/src/index.js).
3. Clique em **Deploy**. O endereço continua o mesmo; a verificação GET continua igual (mesma fórmula e o mesmo
   secret `EBAY_VERIFICATION_TOKEN`).

## 2. Aplicar a migração no D1 existente (v0.9: versão para o Console)

**Por que aparecia "No SQL statements detected."** O Console do D1 apaga as linhas que começam com `--` (comentários)
antes de executar. O arquivo `migrations/0001_init.sql` começa com comentários; se as quebras de linha se perdem ao
colar, tudo vira uma linha iniciada por `--` e nada sobra. Use a **versão de console**, que não tem nenhum comentário
e funciona com ou sem quebras de linha. (O arquivo `migrations/0001_init.sql` continua sendo o usado pelo Wrangler.)

**Copiar o arquivo RAW do GitHub** (evita copiar números de linha ou HTML):

1. Abra `https://github.com/samuelseveriano/GPI/blob/main/cloudflare/ebay-notifications/console/0001_init_console.sql`.
2. Clique em **Raw** (canto superior direito do quadro do arquivo). Abre uma página só com texto, começando por
   `CREATE TABLE IF NOT EXISTS ebay_notifications`.
3. `Ctrl+A` e `Ctrl+C` nessa página Raw. Não copie da visualização normal do GitHub.

**Executar no Console:**

1. **Storage & Databases → D1 SQL Database → `gpi-ebay-notifications-db` → Console**.
2. Cole e clique em **Execute**. São 9 instruções; todas usam `IF NOT EXISTS`/`OR IGNORE`: não apagam nada, podem
   ser repetidas, e completam uma migração aplicada pela metade.
3. Se o Console recusar o bloco inteiro, cole **uma linha por vez** (cada linha do arquivo Raw é uma instrução
   completa, terminada em `;`).

**Verificar:** cole o conteúdo de `console/verificar.sql` (uma linha). O resultado deve listar 6 tabelas
(`audit_log`, `ebay_notifications`, `ebay_public_keys`, `rate_limits`, `schema_migrations`, `sync_nonces`) e 2 índices
(`idx_audit_at`, `idx_ebay_notifications_status`). Depois: `SELECT version FROM schema_migrations;` → `0001_init`.

**Se algo falhar:** nada é destrutivo — corrija e execute de novo. Se uma tabela antiga com o mesmo nome e estrutura
diferente já existir (por exemplo, criada pelo seu código anterior), **não a apague**: anote o resultado de
`PRAGMA table_info(ebay_notifications);` e abra uma issue; o GPI não executa `DROP` em produção.

**O Worker publicado é o da v0.8.2+?** Abra no navegador
`https://gpi-ebay-notifications.samuelseveriano.workers.dev/gpi/v1/status`. O código atual responde
`{"error":"não autorizado"}` (HTTP 401) ou, sem o secret de sincronização, uma mensagem sobre `EBAY_GPI_SYNC_TOKEN`
(HTTP 503). Qualquer outra resposta (por exemplo, 404 ou 503 genérico) indica que ainda está publicado o código
antigo — refaça o passo 1.

## 3. Secrets do Worker

Worker → **Settings → Variables and Secrets → Add** (tipo **Secret**):

| Nome | Valor | Para quê |
|---|---|---|
| `EBAY_VERIFICATION_TOKEN` | **já existe — não altere** | verificação GET |
| `EBAY_CLIENT_ID` | App ID (Client ID) do keyset **Production** | buscar a chave pública do eBay para verificar a assinatura |
| `EBAY_CLIENT_SECRET` | Cert ID (Client Secret) **Production** | idem |
| `EBAY_GPI_SYNC_TOKEN` | token novo (abaixo) | autenticar o GPI no Worker |

Gerar o `EBAY_GPI_SYNC_TOKEN` no Windows (PowerShell comum, sem administrador):

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
```

Copie o resultado (64 caracteres) para o Secret na Cloudflare **e** para o GPI (passo 7). Não o envie por e-mail nem o
coloque no GitHub. O mesmo valor nos dois lados é o que permite ao GPI falar com o Worker; ele nunca trafega (cada
chamada é assinada com HMAC, horário e nonce de uso único).

## 4. Monitoramento diário (opcional, gratuito)

Worker → **Settings → Triggers → Cron Triggers → Add**: `17 11 * * *`. Uma vez por dia o Worker devolve à fila
processamentos sem confirmação e registra alerta de pendências antigas.

## 5. Verificar o endpoint

Abra no navegador:
`https://gpi-ebay-notifications.samuelseveriano.workers.dev/ebay/notifications?challenge_code=teste`
→ deve aparecer `{"challengeResponse":"…64 caracteres…"}`.

## 6. Cadastrar no eBay e testar uma notificação

1. developer.ebay.com → **Application Keys** → keyset **Production** → **Notifications** (Alerts & Notifications).
2. Selecione **Marketplace Account Deletion**, informe o e-mail de alerta, o endpoint
   `https://gpi-ebay-notifications.samuelseveriano.workers.dev/ebay/notifications` e o **Verification Token** (o mesmo
   valor do Secret `EBAY_VERIFICATION_TOKEN`). **Save** — o eBay faz a verificação GET.
3. Clique em **Send Test Notification**. O Worker verifica a assinatura e responde 204.
4. No D1 Console: `SELECT notification_id, status, received_at FROM ebay_notifications;` mostra a notificação de teste
   (`PENDING`).

## 7. Configurar o GPI

Central de Integrações → **eBay — Browse API**: App ID, Cert ID, **Token de sincronização do Worker** e (opcional)
endereço do Worker. Depois, no painel **eBay — Produção e Conformidade**:

1. **Testar conexão** — o Worker responde e mostra quais secrets existem (só sim/não).
2. **Verificar conformidade** — o endpoint público responde e o Worker **verifica a assinatura oficial do eBay no
   runtime publicado** (vetor de teste do SDK do eBay). Se aparecer "FALHOU", não habilite em produção.
3. **Sincronizar** — o GPI processa as pendências (a notificação de teste vira `NOT_FOUND`: nenhum dado daquele
   usuário estava guardado) e confirma ao Worker.

Sem o token de sincronização o GPI **não grava dados do eBay** (a coleta fica bloqueada).

## 8. Ativação das chaves Production

Depois do passo 6, a página Application Keys deve deixar de mostrar "keyset is currently disabled". Se continuar,
confira se o endpoint aparece como **verificado** e se o e-mail de alerta foi salvo.

## 9. Testar a Browse API

Painel → **Diagnosticar integração**. São 10 verificações separadas. Um token emitido **não** prova acesso à Browse API.

| Estado | Significado | O que fazer |
|---|---|---|
| Problema de rede | api.ebay.com inacessível | proxy/firewall corporativo |
| Credencial inválida | App ID/Cert ID errados ou de Sandbox | copie do keyset **Production** |
| Keyset desativado | conformidade ainda não concluída | passos 5–6 |
| Permissão ausente | escopo/permissão negada (HTTP 403) | confira o escopo público `api_scope` |
| API não autorizada | o eBay exige aprovação de produção para Buy APIs | solicitar acesso no portal (Application Growth Check / Buy APIs) |
| Limite de requisições | HTTP 429 | aguardar; limite diário do app |
| Falha interna | HTTP 5xx do eBay | tentar mais tarde |

## 10. Solicitações de exclusão pendentes

* Painel **eBay — Produção e Conformidade**: pendentes no Worker, processadas, falhas e **Ver histórico**.
* D1 Console: `SELECT status, COUNT(*) FROM ebay_notifications GROUP BY status;`
* `FAILED` com resultado `NEEDS_REVIEW`: algum arquivo (backup, relatório) não pôde ser alterado — veja o detalhe no
  histórico, feche o programa que o usa e sincronize de novo.

## O que o GPI apaga

Para cada notificação: anúncios daquele vendedor no banco (`market_listings`, pelo nome antigo **e** pelo pseudônimo),
os mesmos registros em **todos os backups SQLite**, respostas brutas do eBay no **cache HTTP** e, em **relatórios**, o
arquivo gerado (o snapshot é reescrito sem o identificador e pode ser regerado). As exclusões usam
`PRAGMA secure_delete` e `VACUUM` nos backups. Nada fora do pedido é apagado (outros vendedores e outras fontes ficam).
O GPI só confirma `DELETED`/`NOT_FOUND` depois de conferir que não sobrou nada; caso contrário informa `NEEDS_REVIEW`.

Desde a v0.8.2 o GPI guarda o vendedor só como **pseudônimo** (HMAC com chave local) e não guarda respostas do eBay em
cache; nomes de usuário antigos são pseudonimizados na primeira sincronização.

## Limitação: computador desligado

O Worker recebe e confirma as notificações 24 h por dia, mas **a exclusão só acontece quando o GPI abre** — os dados
ficam no computador. O eBay não fixa prazo, mas exige ação. Procedimento:

* abra o GPI pelo menos **uma vez por semana** (a sincronização de abertura processa as pendências);
* o GPI alerta quando há pedido aberto há mais de **3 dias** ou sem sincronizar há mais de **7 dias**;
* em férias/ausência longa, peça a quem tiver acesso para abrir o GPI, ou **desative a coleta do eBay** (apague o
  token de sincronização): sem coleta nova, só restam pseudônimos antigos.

Se a empresa precisar de exclusão garantida com o computador desligado, a alternativa é guardar os dados do eBay
num banco remoto (ex.: o próprio D1) em vez do SQLite local — mudança de arquitetura que não foi feita nesta versão.

## Custos e limites

Plano gratuito da Cloudflare: Workers (100 mil requisições/dia), D1 (5 GB, 5 milhões de linhas lidas/dia) e Cron
Triggers. O volume de notificações de exclusão é baixo. Nenhum recurso pago é criado pelo GPI.

## Publicação por linha de comando (opcional)

Quem tiver Node.js pode usar `cloudflare/ebay-notifications/wrangler.jsonc`: preencha `database_id` (painel → D1 → o
banco), depois `npx wrangler d1 migrations apply gpi-ebay-notifications-db --remote` e `npx wrangler deploy`. Os
secrets continuam no painel (`wrangler secret put`).
