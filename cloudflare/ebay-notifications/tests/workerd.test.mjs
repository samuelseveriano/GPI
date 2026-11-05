// Teste no RUNTIME REAL do Cloudflare (workerd via Miniflare) — roda no CI (workflow cloudflare-worker).
// Confirma o que o teste em Node não prova: que a WebCrypto do Workers verifica ECDSA/SHA-1 (vetor oficial do SDK
// do eBay) e que o SQL do Worker funciona no D1 (simulador oficial do D1 do Miniflare).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash, createHmac, generateKeyPairSync, sign, randomBytes } from 'node:crypto';

let Miniflare;
try { ({ Miniflare } = await import('miniflare')); } catch (e) {
  if (process.env.REQUIRE_WORKERD) throw new Error('miniflare é obrigatório no CI (REQUIRE_WORKERD=1)');
}

const SYNC = 'sync_' + 'z'.repeat(43), VT = 'Vt_' + 'k'.repeat(40);
const BASE = 'https://gpi-ebay-notifications.samuelseveriano.workers.dev';
const { publicKey, privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const PEM = publicKey.export({ type: 'spki', format: 'pem' }).replace(/\n/g, '');

function gpiHeaders(method, path, body) {
  const ts = String(Math.floor(Date.now() / 1000)), nonce = randomBytes(16).toString('hex');
  const sig = createHmac('sha256', SYNC).update([method, path, ts, nonce, createHash('sha256').update(body).digest('hex')].join('\n')).digest('hex');
  return { 'x-gpi-timestamp': ts, 'x-gpi-nonce': nonce, 'x-gpi-signature': sig, 'content-type': 'application/json' };
}

test('workerd: GET, ECDSA/SHA-1 (vetor oficial), POST assinado → D1, claim/ack', { skip: !Miniflare && 'miniflare não instalado' }, async () => {
  const mf = new Miniflare({
    modules: true,
    scriptPath: new URL('../src/index.js', import.meta.url).pathname,
    compatibilityDate: '2025-01-01',
    d1Databases: ['DB'],
    bindings: { EBAY_VERIFICATION_TOKEN: VT, EBAY_CLIENT_ID: 'cid', EBAY_CLIENT_SECRET: 'cs', EBAY_GPI_SYNC_TOKEN: SYNC },
    outboundService: async (req) => {
      const u = new URL(req.url);
      if (u.pathname.includes('/oauth2/token')) return new Response(JSON.stringify({ access_token: 't', expires_in: 7200 }));
      if (u.pathname.includes('/public_key/')) return new Response(JSON.stringify({ key: PEM, algorithm: 'ECDSA', digest: 'SHA1' }));
      return new Response('not found', { status: 404 });
    },
  });
  try {
    const db = await mf.getD1Database('DB');
    const sql = readFileSync(new URL('../migrations/0001_init.sql', import.meta.url), 'utf8')
      .split('\n').filter((l) => !l.trim().startsWith('--')).join('\n')
      .split(';').map((s) => s.trim()).filter(Boolean);
    for (const s of sql) await db.prepare(s).run();

    const g = await mf.dispatchFetch(BASE + '/ebay/notifications?challenge_code=abc');
    assert.equal(g.status, 200);
    assert.equal((await g.json()).challengeResponse,
      createHash('sha256').update('abc' + VT + 'https://gpi-ebay-notifications.samuelseveriano.workers.dev/ebay/notifications').digest('hex'));

    const st = await mf.dispatchFetch(BASE + '/gpi/v1/selftest', { method: 'POST', body: '{}', headers: gpiHeaders('POST', '/gpi/v1/selftest', '{}') });
    const sj = await st.json();
    assert.equal(st.status, 200, JSON.stringify(sj));
    assert.equal(sj.assinatura_valida_aceita, true, 'workerd não verificou o vetor oficial do eBay (ECDSA/SHA-1)');
    assert.equal(sj.assinatura_adulterada_recusada, true);

    const msg = { metadata: { topic: 'MARKETPLACE_ACCOUNT_DELETION', schemaVersion: '1.0', deprecated: false },
      notification: { notificationId: 'n-workerd-0001', eventDate: '2026-11-01T00:00:00Z', publishDate: '2026-11-01T00:00:01Z',
        publishAttemptCount: 1, data: { username: 'u_teste', userId: 'id_teste', eiasToken: 'x' } } };
    const sigB64 = sign('sha1', Buffer.from(JSON.stringify(msg)), { key: privateKey, dsaEncoding: 'der' }).toString('base64');
    const hdr = Buffer.from(JSON.stringify({ alg: 'ecdsa', kid: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', signature: sigB64, digest: 'SHA1' })).toString('base64');
    const p = await mf.dispatchFetch(BASE + '/ebay/notifications', { method: 'POST', body: JSON.stringify(msg),
      headers: { 'content-type': 'application/json', 'x-ebay-signature': hdr } });
    assert.equal(p.status, 204, await p.text());
    const bad = await mf.dispatchFetch(BASE + '/ebay/notifications', { method: 'POST', body: JSON.stringify({ ...msg, metadata: { ...msg.metadata, schemaVersion: '9' } }),
      headers: { 'content-type': 'application/json', 'x-ebay-signature': hdr } });
    assert.equal(bad.status, 412);

    const cb = JSON.stringify({ limit: 5 });
    const c = await (await mf.dispatchFetch(BASE + '/gpi/v1/claim', { method: 'POST', body: cb, headers: gpiHeaders('POST', '/gpi/v1/claim', cb) })).json();
    assert.equal(c.quantidade, 1);
    const ab = JSON.stringify({ notification_id: 'n-workerd-0001', result: 'NOT_FOUND' });
    const a = await (await mf.dispatchFetch(BASE + '/gpi/v1/ack', { method: 'POST', body: ab, headers: gpiHeaders('POST', '/gpi/v1/ack', ab) })).json();
    assert.equal(a.status, 'COMPLETED');
    const row = await db.prepare('SELECT ebay_username, status FROM ebay_notifications').first();
    assert.equal(row.ebay_username, null);
  } finally {
    await mf.dispose();
  }
});
