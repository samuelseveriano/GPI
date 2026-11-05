// Testes do Worker gpi-ebay-notifications (node --test). Sem credenciais reais: a API do eBay é simulada; a
// assinatura usa (a) o vetor OFICIAL do SDK do eBay e (b) um par de chaves P-256 gerado no teste.
// Executar: node --test cloudflare/ebay-notifications/tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac, generateKeyPairSync, sign, randomBytes } from 'node:crypto';
import { makeD1 } from './d1.mjs';
import * as W from '../src/index.js';

const MIG = new URL('../migrations/', import.meta.url);
const BASE = 'https://gpi-ebay-notifications.samuelseveriano.workers.dev';
const VT = 'Vt_' + 'k'.repeat(40);                     // token de verificação de TESTE (não é o real)
const SYNC = 'sync_' + 'z'.repeat(43);                 // token de sincronização de TESTE

const { publicKey, privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const PEM_EBAY_STYLE = publicKey.export({ type: 'spki', format: 'pem' }).replace(/\n/g, '');   // eBay devolve sem quebras
const KID = '11111111-2222-4333-8444-555555555555';

function envFor(over = {}) {
  return { DB: makeD1(MIG), EBAY_VERIFICATION_TOKEN: VT, EBAY_CLIENT_ID: 'cid-teste', EBAY_CLIENT_SECRET: 'csecret-teste',
    EBAY_GPI_SYNC_TOKEN: SYNC, ...over };
}
function ebayFetch(calls = []) {
  return async (url, init) => {
    calls.push(String(url));
    if (String(url).includes('/identity/v1/oauth2/token')) return new Response(JSON.stringify({ access_token: 'app-token-teste', expires_in: 7200 }), { status: 200 });
    if (String(url).includes('/commerce/notification/v1/public_key/')) {
      return new Response(JSON.stringify({ key: PEM_EBAY_STYLE, algorithm: 'ECDSA', digest: 'SHA1' }), { status: 200 });
    }
    return new Response('{}', { status: 404 });
  };
}
function message(id = 'n-' + randomBytes(6).toString('hex'), user = { username: 'vendedor_teste', userId: 'uid123ABC' }) {
  return { metadata: { topic: 'MARKETPLACE_ACCOUNT_DELETION', schemaVersion: '1.0', deprecated: false },
    notification: { notificationId: id, eventDate: '2026-11-01T10:00:00.000Z', publishDate: '2026-11-01T10:00:01.000Z',
      publishAttemptCount: 1, data: { ...user, eiasToken: 'nY+eias' } } };
}
function signedHeader(msg, kid = KID, key = privateKey) {
  const sig = sign('sha1', Buffer.from(JSON.stringify(msg)), { key, dsaEncoding: 'der' }).toString('base64');
  return Buffer.from(JSON.stringify({ alg: 'ecdsa', kid, signature: sig, digest: 'SHA1' })).toString('base64');
}
const post = (msg, hdr) => new Request(BASE + '/ebay/notifications', { method: 'POST', body: JSON.stringify(msg),
  headers: { 'Content-Type': 'application/json', ...(hdr ? { 'x-ebay-signature': hdr } : {}) } });

function gpiReq(method, path, body = '', { token = SYNC, ts = Math.floor(Date.now() / 1000), nonce = randomBytes(16).toString('hex') } = {}) {
  const b = body ? JSON.stringify(body) : '';
  const h = createHash('sha256').update(b).digest('hex');
  const sig = createHmac('sha256', token).update([method, path, String(ts), nonce, h].join('\n')).digest('hex');
  return new Request(BASE + path, { method, body: b || undefined,
    headers: { 'x-gpi-timestamp': String(ts), 'x-gpi-nonce': nonce, 'x-gpi-signature': sig, 'Content-Type': 'application/json' } });
}

// 1–3 GET
test('1. GET válido devolve challengeResponse = SHA-256(code + token + endpoint) com JSON', async () => {
  const env = envFor();
  const code = 'a8628072-3d33-45ee-9004-bee86830a22d';
  const r = await W.handle(new Request(BASE + '/ebay/notifications?challenge_code=' + code), env);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('content-type'), 'application/json');
  const expected = createHash('sha256').update(code + VT + W.ENDPOINT_DEFAULT).digest('hex');
  assert.deepEqual(await r.json(), { challengeResponse: expected });
});

test('2. GET inválido: sem challenge_code → 400; sem token → 500 sem expor nada', async () => {
  const r = await W.handle(new Request(BASE + '/ebay/notifications'), envFor());
  assert.equal(r.status, 400);
  const r2 = await W.handle(new Request(BASE + '/ebay/notifications?challenge_code=x'), envFor({ EBAY_VERIFICATION_TOKEN: '' }));
  assert.equal(r2.status, 500);
  assert.ok(!(await r2.text()).includes(VT));
  const r3 = await W.handle(new Request(BASE + '/ebay/notifications?challenge_code=' + 'x'.repeat(600)), envFor());
  assert.equal(r3.status, 400);
});

test('3. SHA-256 usa exatamente a URL cadastrada (variável EBAY_ENDPOINT_URL quando definida)', async () => {
  const other = 'https://exemplo.workers.dev/ebay/notifications';
  const r = await W.handle(new Request(BASE + '/ebay/notifications?challenge_code=abc'), envFor({ EBAY_ENDPOINT_URL: other }));
  assert.equal((await r.json()).challengeResponse, createHash('sha256').update('abc' + VT + other).digest('hex'));
});

// 4–7 POST
test('4. POST válido (assinatura correta) → 204 depois de gravar no D1, sem eiasToken', async () => {
  const env = envFor(), calls = [];
  const m = message('n-valido-0001');
  const r = await W.handle(post(m, signedHeader(m)), env, ebayFetch(calls));
  assert.equal(r.status, 204);
  const row = env.DB.raw.prepare('SELECT * FROM ebay_notifications').get();
  assert.equal(row.status, 'PENDING');
  assert.equal(row.ebay_username, 'vendedor_teste');
  assert.ok(!JSON.stringify(row).includes('eias'));
  assert.ok(calls.some((u) => u.includes('/public_key/' + KID)));
});

test('4b. vetor OFICIAL do SDK do eBay é aceito; adulterado é recusado', async () => {
  assert.deepEqual(await W.selftest(), { assinatura_valida_aceita: true, assinatura_adulterada_recusada: true });
});

test('5. POST com assinatura inválida/ausente → 412 e nada gravado', async () => {
  const env = envFor();
  const m = message('n-invalido-01');
  const other = generateKeyPairSync('ec', { namedCurve: 'prime256v1' }).privateKey;
  assert.equal((await W.handle(post(m, signedHeader(m, KID, other)), env, ebayFetch())).status, 412);
  assert.equal((await W.handle(post(m), env, ebayFetch())).status, 412);
  const tampered = message('n-invalido-01');
  const hdr = signedHeader(tampered);
  tampered.notification.data.username = 'atacante';
  assert.equal((await W.handle(post(tampered, hdr), env, ebayFetch())).status, 412);
  assert.equal(env.DB.raw.prepare('SELECT COUNT(*) AS n FROM ebay_notifications').get().n, 0);
  const bad = message('n-x'); bad.metadata.topic = 'OUTRO';
  assert.equal((await W.handle(post(bad, signedHeader(bad)), env, ebayFetch())).status, 400);
});

test('6. POST duplicado → 204 de novo, uma linha, contador de recebimentos', async () => {
  const env = envFor();
  const m = message('n-duplicado-1');
  for (let i = 0; i < 3; i++) assert.equal((await W.handle(post(m, signedHeader(m)), env, ebayFetch())).status, 204);
  const rows = env.DB.raw.prepare('SELECT times_received, status FROM ebay_notifications').all();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].times_received, 3);
  assert.equal(rows[0].status, 'PENDING');
});

test('7. D1 indisponível → 500 (o eBay reenvia); nunca 204 sem gravação', async () => {
  const env = envFor();
  const m = message('n-d1-down-01');
  await W.getPublicKey(env, KID, ebayFetch());           // chave em cache de memória
  env.DB.state.down = true;
  const r = await W.handle(post(m, signedHeader(m)), env, ebayFetch());
  assert.equal(r.status, 500);
  env.DB.state.down = false;
  assert.equal(env.DB.raw.prepare('SELECT COUNT(*) AS n FROM ebay_notifications').get().n, 0);
});

test('7b. chave pública indisponível → 500 (não aceita o que não pode verificar)', async () => {
  const env = envFor();
  const m = message('n-sem-chave-1');
  const r = await W.handle(post(m, signedHeader(m, '99999999-0000-4000-8000-000000000000')), env, async () => new Response('x', { status: 503 }));
  assert.equal(r.status, 500);
});

// 8–15 GPI
test('8–11. GPI offline acumula pendências; ao voltar retira, exclui e confirma', async () => {
  const env = envFor();
  for (const id of ['n-off-0000001', 'n-off-0000002']) { const m = message(id); await W.handle(post(m, signedHeader(m)), env, ebayFetch()); }
  const st = await (await W.handle(gpiReq('GET', '/gpi/v1/status'), env)).json();
  assert.equal(st.pendentes, 2);
  const c = await (await W.handle(gpiReq('POST', '/gpi/v1/claim', { limit: 10 }), env)).json();
  assert.equal(c.quantidade, 2);
  assert.equal(c.itens[0].ebay_username, 'vendedor_teste');
  const a1 = await (await W.handle(gpiReq('POST', '/gpi/v1/ack', { notification_id: 'n-off-0000001', result: 'DELETED', detail: '3 anúncios' }), env)).json();
  assert.equal(a1.status, 'COMPLETED');
  const again = await (await W.handle(gpiReq('POST', '/gpi/v1/ack', { notification_id: 'n-off-0000001', result: 'DELETED' }), env)).json();
  assert.equal(again.idempotente, true);
  const row = env.DB.raw.prepare("SELECT * FROM ebay_notifications WHERE notification_id = 'n-off-0000001'").get();
  assert.equal(row.ebay_username, null);                   // identificadores apagados ao concluir
  assert.equal(row.ebay_user_id, null);
  assert.equal(row.result, 'DELETED');
});

test('12–13. falha de autenticação: token errado, horário fora da janela, replay de nonce, sem cabeçalhos', async () => {
  const env = envFor();
  assert.equal((await W.handle(gpiReq('GET', '/gpi/v1/status', '', { token: 'errado_' + 'x'.repeat(40) }), env)).status, 401);
  assert.equal((await W.handle(gpiReq('GET', '/gpi/v1/status', '', { ts: Math.floor(Date.now() / 1000) - 3600 }), env)).status, 401);
  const nonce = 'nonce-fixo-1234567890';
  assert.equal((await W.handle(gpiReq('GET', '/gpi/v1/status', '', { nonce }), env)).status, 200);
  assert.equal((await W.handle(gpiReq('GET', '/gpi/v1/status', '', { nonce }), env)).status, 401);   // replay
  assert.equal((await W.handle(new Request(BASE + '/gpi/v1/status'), env)).status, 401);
  assert.equal((await W.handle(gpiReq('GET', '/gpi/v1/status'), envFor({ EBAY_GPI_SYNC_TOKEN: '' }))).status, 503);
});

test('13b. limite de tentativas de autenticação → 429', async () => {
  const env = envFor();
  let last;
  for (let i = 0; i < 25; i++) last = await W.handle(gpiReq('GET', '/gpi/v1/status', '', { token: 'errado_' + 'x'.repeat(40) }), env);
  assert.equal(last.status, 429);
});

test('14. retentativas: ERROR → RETRY_SCHEDULED; após o limite → FAILED; PROCESSING vencido volta à fila', async () => {
  const env = envFor();
  const m = message('n-retry-00001');
  await W.handle(post(m, signedHeader(m)), env, ebayFetch());
  for (let i = 0; i < 10; i++) {
    await W.handle(gpiReq('POST', '/gpi/v1/claim', {}), env);
    await W.handle(gpiReq('POST', '/gpi/v1/ack', { notification_id: 'n-retry-00001', result: 'ERROR', error: 'disco cheio' }), env);
    if (i === 0) {   // dentro da espera de 15 min a mesma notificação NÃO é entregue de novo
      const c = await (await W.handle(gpiReq('POST', '/gpi/v1/claim', {}), env)).json();
      assert.equal(c.quantidade, 0);
    }
    env.DB.raw.prepare("UPDATE ebay_notifications SET processed_at = '2000-01-01T00:00:00Z'").run();   // simula a espera
  }
  const row = env.DB.raw.prepare('SELECT status, attempts, ebay_username FROM ebay_notifications').get();
  assert.equal(row.status, 'FAILED');
  assert.equal(row.attempts, 10);
  assert.equal(row.ebay_username, 'vendedor_teste');      // não concluída: identificadores mantidos para nova análise
  const m2 = message('n-stale-00001');
  await W.handle(post(m2, signedHeader(m2)), env, ebayFetch());
  await W.handle(gpiReq('POST', '/gpi/v1/claim', {}), env);
  env.DB.raw.prepare("UPDATE ebay_notifications SET processing_started_at = '2000-01-01T00:00:00Z' WHERE notification_id = 'n-stale-00001'").run();
  await W.scheduled(env);
  assert.equal(env.DB.raw.prepare("SELECT status FROM ebay_notifications WHERE notification_id = 'n-stale-00001'").get().status, 'RETRY_SCHEDULED');
});

test('15–16. histórico persiste e não expõe dados pessoais; rotas sem autenticação não vazam nada', async () => {
  const env = envFor();
  const m = message('n-hist-000001');
  await W.handle(post(m, signedHeader(m)), env, ebayFetch());
  const h = await (await W.handle(gpiReq('GET', '/gpi/v1/history'), env)).text();
  assert.ok(h.includes('n-hist-000001'));
  assert.ok(!h.includes('vendedor_teste') && !h.includes('uid123ABC'));
  const st = await (await W.handle(gpiReq('GET', '/gpi/v1/status'), env)).text();
  assert.ok(!st.includes('vendedor_teste') && !st.includes(VT) && !st.includes(SYNC) && !st.includes('csecret'));
  for (const p of ['/gpi/v1/history', '/gpi/v1/claim', '/', '/ebay/notifications/x']) {
    const t = await (await W.handle(new Request(BASE + p, { method: p.includes('claim') ? 'POST' : 'GET' }), env)).text();
    assert.ok(!t.includes('vendedor_teste'));
  }
  const audit = JSON.stringify(env.DB.raw.prepare('SELECT * FROM audit_log').all());
  assert.ok(!audit.includes('vendedor_teste') && !audit.includes('uid123ABC'));
});

test('autoteste autenticado devolve o resultado do vetor oficial e a situação dos segredos (booleanos)', async () => {
  const r = await (await W.handle(gpiReq('POST', '/gpi/v1/selftest', {}), envFor())).json();
  assert.equal(r.assinatura_valida_aceita, true);
  assert.equal(r.assinatura_adulterada_recusada, true);
  assert.deepEqual(r.segredos, { verification_token: true, ebay_client: true, sync_token: true });
});

test('HTTP sem TLS é recusado; métodos não suportados → 405', async () => {
  assert.equal((await W.handle(new Request('http://x.workers.dev/ebay/notifications?challenge_code=a'), envFor())).status, 400);
  assert.equal((await W.handle(new Request(BASE + '/ebay/notifications', { method: 'PUT' }), envFor())).status, 405);
});
