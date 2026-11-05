// GPI v0.8.2 — Worker "gpi-ebay-notifications": eBay Marketplace Account Deletion + sincronização com o GPI local.
//
// Arquivo único, sem dependências: pode ser colado no editor do painel da Cloudflare (Workers → Edit code).
// Bindings/segredos (nenhum valor fica neste arquivo):
//   DB                       D1 "gpi-ebay-notifications-db" (já vinculado)
//   EBAY_VERIFICATION_TOKEN  segredo existente (32–80 caracteres) — verificação GET
//   EBAY_CLIENT_ID           App ID (Client ID) Production do keyset — para buscar a chave pública do eBay
//   EBAY_CLIENT_SECRET       Cert ID (Client Secret) Production
//   EBAY_GPI_SYNC_TOKEN      segredo compartilhado com o GPI (assinatura HMAC das chamadas /gpi/v1/*)
//   EBAY_ENDPOINT_URL        (opcional, variável) URL cadastrada no eBay; padrão: ENDPOINT_DEFAULT
//
// Protocolo seguido: o do SDK oficial do eBay (github.com/eBay/event-notification-nodejs-sdk):
//   GET  ?challenge_code=… → {"challengeResponse": hex(SHA-256(challengeCode + verificationToken + endpoint))}
//   POST → cabeçalho x-ebay-signature = base64(JSON {alg, kid, signature, digest}); chave pública em
//          GET https://api.ebay.com/commerce/notification/v1/public_key/{kid} (token de aplicativo);
//          verificação ECDSA/SHA-1 da assinatura (DER, base64) sobre JSON.stringify(mensagem);
//          204 se válida, 412 se a assinatura não confere, 500 em falha interna (o eBay reenvia).
// Único export: o handler padrão (o runtime do Workers recusa exports nomeados que não sejam handlers).
// O 204 só é devolvido DEPOIS de a notificação ser gravada no D1. Recebimento ≠ exclusão concluída: a exclusão é
// feita pelo GPI no computador do usuário e confirmada depois por /gpi/v1/ack.

const VERSION = '0.8.2';
const ENDPOINT_DEFAULT = 'https://gpi-ebay-notifications.samuelseveriano.workers.dev/ebay/notifications';
const NOTIFY_PATH = '/ebay/notifications';
const TOPIC = 'MARKETPLACE_ACCOUNT_DELETION';
const PUBLIC_KEY_URL = 'https://api.ebay.com/commerce/notification/v1/public_key/';
const OAUTH_URL = 'https://api.ebay.com/identity/v1/oauth2/token';
const KEY_TTL_S = 3600;                    // recomendado pelo eBay: cache de 1 hora
const MAX_BODY = 64 * 1024;
const SYNC_SKEW_S = 300;                   // relógio do GPI pode diferir em até 5 min
const PROCESSING_LEASE_S = 3600;           // PROCESSING sem resposta por 1 h volta para RETRY_SCHEDULED
const MAX_ATTEMPTS = 10;
const RETRY_BACKOFF_S = 900;               // nova tentativa só 15 min depois de um ERROR
const AUTH_FAIL_LIMIT = 20;                // falhas de autenticação por IP por minuto
const ALERT_AFTER_DAYS = 3;

const mem = { keys: new Map(), token: null, tokenExp: 0 };   // caches do isolate (voláteis)
const enc = new TextEncoder();

// ------------------------------------------------------------------------------------------- utilidades
function json(obj, status = 200, extra = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...extra },
  });
}
const empty = (status) => new Response(null, { status, headers: { 'Cache-Control': 'no-store' } });
const nowIso = () => new Date().toISOString();
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
async function sha256hex(s) { return hex(await crypto.subtle.digest('SHA-256', typeof s === 'string' ? enc.encode(s) : s)); }
function b64decode(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
// mensagens de erro sem dados pessoais, sem segredos e curtas
function sanitize(msg) {
  return String(msg || '').replace(/[A-Za-z0-9+/_=-]{24,}/g, '[…]').replace(/[^\x20-\x7EÀ-ſ]/g, ' ').slice(0, 300);
}
async function audit(env, actor, action, nid = null, detail = null) {
  try {
    await env.DB.prepare('INSERT INTO audit_log (at, actor, action, notification_id, detail) VALUES (?, ?, ?, ?, ?)')
      .bind(nowIso(), actor, action, nid, detail ? sanitize(detail) : null).run();
  } catch (e) { /* auditoria nunca derruba a requisição */ }
}

// ------------------------------------------------------------------------------------------- GET (verificação)
async function challengeResponse(code, token, endpoint) {
  return sha256hex(code + token + endpoint);
}

async function handleChallenge(url, env) {
  const code = url.searchParams.get('challenge_code');
  if (!code || code.length > 512) return json({ error: 'challenge_code ausente ou inválido' }, 400);
  const token = env.EBAY_VERIFICATION_TOKEN;
  if (!token || !/^[A-Za-z0-9_-]{32,80}$/.test(token)) return json({ error: 'verificação não configurada' }, 500);
  const endpoint = env.EBAY_ENDPOINT_URL || ENDPOINT_DEFAULT;
  return json({ challengeResponse: await challengeResponse(code, token, endpoint) }, 200);
}

// ------------------------------------------------------------------------------------------- assinatura eBay
function parseSignatureHeader(h) {
  if (!h || h.length > 4096) return null;
  let o;
  try { o = JSON.parse(new TextDecoder().decode(b64decode(h))); } catch (e) { return null; }
  if (!o || typeof o !== 'object' || typeof o.signature !== 'string' || typeof o.kid !== 'string') return null;
  if (!/^[A-Za-z0-9-]{8,64}$/.test(o.kid)) return null;
  return o;
}

// DER (SEQUENCE{INTEGER r, INTEGER s}) → r||s de tamanho fixo (formato exigido pela WebCrypto)
function derToP1363(der, size = 32) {
  let i = 0;
  if (der[i++] !== 0x30) throw new Error('assinatura DER inválida');
  let len = der[i++];
  if (len & 0x80) { i += len & 0x7f; }
  const out = new Uint8Array(size * 2);
  for (let k = 0; k < 2; k++) {
    if (der[i++] !== 0x02) throw new Error('assinatura DER inválida');
    let l = der[i++];
    let v = der.slice(i, i + l);
    i += l;
    while (v.length > size && v[0] === 0) v = v.slice(1);
    if (v.length > size) throw new Error('assinatura DER inválida');
    out.set(v, k * size + (size - v.length));
  }
  return out;
}

function pemToDer(pem) {
  const b = String(pem).replace(/-----BEGIN PUBLIC KEY-----|-----END PUBLIC KEY-----|\s+/g, '');
  return b64decode(b);
}

async function verifyEcdsaSha1(pem, sigB64, data) {
  const key = await crypto.subtle.importKey('spki', pemToDer(pem), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  const sig = derToP1363(b64decode(sigB64));
  return crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-1' }, key, sig, enc.encode(data));
}

async function appToken(env, fetcher) {
  if (mem.token && mem.tokenExp > Date.now() + 60000) return mem.token;
  if (!env.EBAY_CLIENT_ID || !env.EBAY_CLIENT_SECRET) throw new Error('EBAY_CLIENT_ID/EBAY_CLIENT_SECRET não configurados');
  const r = await fetcher(OAUTH_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Authorization: 'Basic ' + btoa(env.EBAY_CLIENT_ID + ':' + env.EBAY_CLIENT_SECRET) },
    body: 'grant_type=client_credentials&scope=' + encodeURIComponent('https://api.ebay.com/oauth/api_scope'),
  });
  if (!r.ok) throw new Error('token de aplicativo do eBay recusado (HTTP ' + r.status + ')');
  const d = await r.json();
  mem.token = d.access_token;
  mem.tokenExp = Date.now() + 1000 * Number(d.expires_in || 3600);
  return mem.token;
}

async function getPublicKey(env, kid, fetcher = fetch) {
  const now = Math.floor(Date.now() / 1000);
  const m = mem.keys.get(kid);
  if (m && m.fetched_at > now - KEY_TTL_S) return m;
  try {
    const row = await env.DB.prepare('SELECT kid, pem, algorithm, digest, fetched_at FROM ebay_public_keys WHERE kid = ?').bind(kid).first();
    if (row && row.fetched_at > now - KEY_TTL_S) { mem.keys.set(kid, row); return row; }
  } catch (e) { /* segue para a API */ }
  const tok = await appToken(env, fetcher);
  const r = await fetcher(PUBLIC_KEY_URL + encodeURIComponent(kid), { headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' } });
  if (!r.ok) throw new Error('chave pública do eBay indisponível (HTTP ' + r.status + ')');
  const d = await r.json();
  if (!d || typeof d.key !== 'string') throw new Error('chave pública do eBay em formato inesperado');
  const rec = { kid, pem: d.key, algorithm: d.algorithm || null, digest: d.digest || null, fetched_at: now };
  if ((rec.algorithm && rec.algorithm.toUpperCase() !== 'ECDSA') || (rec.digest && rec.digest.toUpperCase() !== 'SHA1')) {
    throw new Error('algoritmo de assinatura não suportado: ' + rec.algorithm + '/' + rec.digest);
  }
  mem.keys.set(kid, rec);
  try {
    await env.DB.prepare('INSERT INTO ebay_public_keys (kid, pem, algorithm, digest, fetched_at) VALUES (?, ?, ?, ?, ?) ' +
      'ON CONFLICT(kid) DO UPDATE SET pem = excluded.pem, algorithm = excluded.algorithm, digest = excluded.digest, fetched_at = excluded.fetched_at')
      .bind(kid, rec.pem, rec.algorithm, rec.digest, now).run();
  } catch (e) { /* cache é opcional */ }
  return rec;
}

// ------------------------------------------------------------------------------------------- POST (notificação)
function validateMessage(m) {
  if (!m || typeof m !== 'object' || !m.metadata || !m.notification) return 'mensagem sem metadata/notification';
  if (m.metadata.topic !== TOPIC) return 'tópico não suportado';
  const n = m.notification;
  if (typeof n.notificationId !== 'string' || !/^[A-Za-z0-9_.:-]{8,200}$/.test(n.notificationId)) return 'notificationId ausente ou inválido';
  const d = n.data || {};
  if (typeof d.userId !== 'string' && typeof d.username !== 'string') return 'notificação sem userId/username';
  for (const k of ['userId', 'username']) {
    if (d[k] != null && (typeof d[k] !== 'string' || d[k].length > 200)) return k + ' inválido';
  }
  return null;
}

async function handleNotification(request, env, fetcher) {
  const len = Number(request.headers.get('content-length') || 0);
  if (len > MAX_BODY) return json({ error: 'mensagem grande demais' }, 413);
  const raw = await request.text();
  if (raw.length > MAX_BODY) return json({ error: 'mensagem grande demais' }, 413);
  let msg;
  try { msg = JSON.parse(raw); } catch (e) { return json({ error: 'JSON inválido' }, 400); }
  const bad = validateMessage(msg);
  if (bad) { await audit(env, 'ebay', 'rejeitada', null, bad); return json({ error: bad }, 400); }
  const sh = parseSignatureHeader(request.headers.get('x-ebay-signature'));
  if (!sh) { await audit(env, 'ebay', 'assinatura_ausente', null); return empty(412); }
  const nid = msg.notification.notificationId;
  let ok = false;
  try {
    const key = await getPublicKey(env, sh.kid, fetcher);
    ok = await verifyEcdsaSha1(key.pem, sh.signature, JSON.stringify(msg));
  } catch (e) {
    // não foi possível VERIFICAR (chave/token indisponível): não aceitar e deixar o eBay reenviar
    await audit(env, 'ebay', 'verificacao_indisponivel', nid, e.message);
    return json({ error: 'verificação temporariamente indisponível' }, 500);
  }
  if (!ok) { await audit(env, 'ebay', 'assinatura_invalida', nid); return empty(412); }
  const n = msg.notification, d = n.data || {}, t = nowIso();
  try {
    await env.DB.prepare(
      'INSERT INTO ebay_notifications (notification_id, topic, schema_version, ebay_user_id, ebay_username, event_date, publish_date, ' +
      'publish_attempts, received_at, last_received_at, times_received, validated_at, status, attempts) ' +
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'PENDING', 0) " +
      'ON CONFLICT(notification_id) DO UPDATE SET times_received = times_received + 1, last_received_at = excluded.last_received_at, ' +
      'publish_attempts = MAX(COALESCE(publish_attempts, 0), COALESCE(excluded.publish_attempts, 0))')
      .bind(nid, TOPIC, String(msg.metadata.schemaVersion || ''), d.userId || null, d.username || null, n.eventDate || null,
        n.publishDate || null, Number(n.publishAttemptCount || 0), t, t, t).run();
  } catch (e) {
    // sem gravação durável não há confirmação: 500 faz o eBay reenviar
    return json({ error: 'armazenamento indisponível' }, 500);
  }
  await audit(env, 'ebay', 'recebida_validada', nid, 'tentativa de envio ' + Number(n.publishAttemptCount || 0));
  return empty(204);
}

// ------------------------------------------------------------------------------------------- autenticação GPI
async function syncSignature(token, method, path, ts, nonce, body) {
  const key = await crypto.subtle.importKey('raw', enc.encode(token), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', key, enc.encode([method, path, ts, nonce, await sha256hex(body || '')].join('\n'))));
}

async function rateLimited(env, bucket, limit) {
  const now = Math.floor(Date.now() / 1000), win = now - (now % 60);
  try {
    const r = await env.DB.prepare('INSERT INTO rate_limits (bucket, count, window_start) VALUES (?, 1, ?) ' +
      'ON CONFLICT(bucket) DO UPDATE SET count = CASE WHEN window_start = excluded.window_start THEN count + 1 ELSE 1 END, ' +
      'window_start = excluded.window_start RETURNING count').bind(bucket, win).first();
    return r && r.count > limit;
  } catch (e) { return false; }
}

async function authenticate(request, env, body) {
  const ip = request.headers.get('cf-connecting-ip') || 'desconhecido';
  const fail = async (why) => {
    await audit(env, 'gpi', 'autenticacao_recusada', null, why);
    if (await rateLimited(env, 'authfail:' + ip, AUTH_FAIL_LIMIT)) return json({ error: 'muitas tentativas' }, 429, { 'Retry-After': '60' });
    return json({ error: 'não autorizado' }, 401);
  };
  const token = env.EBAY_GPI_SYNC_TOKEN;
  if (!token || token.length < 32) return json({ error: 'sincronização não configurada no Worker (EBAY_GPI_SYNC_TOKEN)' }, 503);
  const ts = request.headers.get('x-gpi-timestamp') || '', nonce = request.headers.get('x-gpi-nonce') || '';
  const sig = request.headers.get('x-gpi-signature') || '';
  if (!/^\d{10}$/.test(ts) || !/^[A-Za-z0-9_-]{16,64}$/.test(nonce) || !/^[0-9a-f]{64}$/.test(sig)) return fail('cabeçalhos ausentes');
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - Number(ts)) > SYNC_SKEW_S) return fail('horário fora da janela');
  const url = new URL(request.url);
  const key = await crypto.subtle.importKey('raw', enc.encode(token), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify']);
  const data = enc.encode([request.method, url.pathname, ts, nonce, await sha256hex(body || '')].join('\n'));
  const sigBytes = new Uint8Array(sig.match(/../g).map((h) => parseInt(h, 16)));
  if (!(await crypto.subtle.verify('HMAC', key, sigBytes, data))) return fail('assinatura inválida');   // comparação em tempo constante
  try {
    await env.DB.prepare('INSERT INTO sync_nonces (nonce, ts) VALUES (?, ?)').bind(nonce, now).run();
  } catch (e) {
    return fail('nonce repetido (replay)');
  }
  return null;
}

// ------------------------------------------------------------------------------------------- API do GPI
const PUBLIC_COLS = 'notification_id, status, event_date, received_at, last_received_at, times_received, attempts, ' +
  'last_error, processing_started_at, processed_at, completed_at, result';

async function requeueStale(env) {
  const cut = new Date(Date.now() - PROCESSING_LEASE_S * 1000).toISOString();
  await env.DB.prepare("UPDATE ebay_notifications SET status = 'RETRY_SCHEDULED', last_error = 'processamento sem confirmação (prazo expirado)' " +
    "WHERE status = 'PROCESSING' AND processing_started_at < ?").bind(cut).run();
}

async function statusView(env) {
  const counts = {};
  const rs = await env.DB.prepare('SELECT status, COUNT(*) AS n FROM ebay_notifications GROUP BY status').all();
  for (const r of rs.results || []) counts[r.status] = r.n;
  const last = await env.DB.prepare('SELECT MAX(last_received_at) AS t FROM ebay_notifications').first();
  const old = await env.DB.prepare("SELECT MIN(received_at) AS t FROM ebay_notifications WHERE status IN ('PENDING','RETRY_SCHEDULED','PROCESSING','FAILED')").first();
  const pend = ['PENDING', 'RETRY_SCHEDULED', 'PROCESSING'].reduce((a, k) => a + (counts[k] || 0), 0);
  const ageDays = old && old.t ? (Date.now() - Date.parse(old.t)) / 86400000 : 0;
  return {
    versao: VERSION, endpoint_url: env.EBAY_ENDPOINT_URL || ENDPOINT_DEFAULT,
    segredos: { verification_token: Boolean(env.EBAY_VERIFICATION_TOKEN), ebay_client: Boolean(env.EBAY_CLIENT_ID && env.EBAY_CLIENT_SECRET),
      sync_token: Boolean(env.EBAY_GPI_SYNC_TOKEN) },
    d1: 'ok', contagens: counts, pendentes: pend, falhas: counts.FAILED || 0, concluidas: counts.COMPLETED || 0,
    ultima_notificacao_em: last && last.t, pendente_mais_antiga_em: old && old.t,
    alerta: ageDays > ALERT_AFTER_DAYS ? `há solicitações de exclusão abertas há ${Math.floor(ageDays)} dia(s): abra o GPI e sincronize` : null,
  };
}

async function claim(env, body) {
  const limit = Math.max(1, Math.min(100, Number((body && body.limit) || 50)));
  await requeueStale(env);
  const t = nowIso(), retryCut = new Date(Date.now() - RETRY_BACKOFF_S * 1000).toISOString();
  const rs = await env.DB.prepare(
    "UPDATE ebay_notifications SET status = 'PROCESSING', processing_started_at = ?, attempts = attempts + 1 " +
    "WHERE notification_id IN (SELECT notification_id FROM ebay_notifications WHERE status = 'PENDING' " +
    "OR (status = 'RETRY_SCHEDULED' AND (processed_at IS NULL OR processed_at < ?)) " +
    'ORDER BY received_at LIMIT ?) RETURNING notification_id, ebay_user_id, ebay_username, event_date, received_at, attempts')
    .bind(t, retryCut, limit).all();
  const items = rs.results || [];
  for (const it of items) await audit(env, 'gpi', 'retirada_para_processamento', it.notification_id);
  return { itens: items, quantidade: items.length };
}

const RESULTS = { DELETED: 'COMPLETED', NOT_FOUND: 'COMPLETED', NEEDS_REVIEW: 'FAILED', ERROR: 'RETRY_SCHEDULED' };

async function ack(env, body) {
  const nid = body && body.notification_id, res = body && body.result;
  if (typeof nid !== 'string' || !RESULTS[res]) return json({ error: 'notification_id e result (DELETED, NOT_FOUND, NEEDS_REVIEW, ERROR) são obrigatórios' }, 400);
  const row = await env.DB.prepare('SELECT status, attempts FROM ebay_notifications WHERE notification_id = ?').bind(nid).first();
  if (!row) return json({ error: 'notificação desconhecida' }, 404);
  if (row.status === 'COMPLETED') return json({ ok: true, status: 'COMPLETED', idempotente: true });
  let status = RESULTS[res];
  if (status === 'RETRY_SCHEDULED' && row.attempts >= MAX_ATTEMPTS) status = 'FAILED';
  const t = nowIso(), err = body.error ? sanitize(body.error) : null;
  if (status === 'COMPLETED') {
    // concluída: os identificadores pessoais deixam de ser necessários e são apagados do D1
    await env.DB.prepare("UPDATE ebay_notifications SET status = 'COMPLETED', result = ?, processed_at = ?, completed_at = ?, " +
      'last_error = NULL, ebay_user_id = NULL, ebay_username = NULL WHERE notification_id = ?').bind(res, t, t, nid).run();
  } else {
    await env.DB.prepare('UPDATE ebay_notifications SET status = ?, result = ?, processed_at = ?, last_error = ? WHERE notification_id = ?')
      .bind(status, res, t, err, nid).run();
  }
  await audit(env, 'gpi', 'confirmacao_' + res.toLowerCase(), nid, body.detail ? sanitize(body.detail) : err);
  return json({ ok: true, status, idempotente: false });
}

// Autoteste no runtime publicado: confirma que ESTE runtime verifica ECDSA/SHA-1 (vetor oficial do SDK do eBay).
const SDK_VECTOR = {
  pem: '-----BEGIN PUBLIC KEY-----MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEZhhxXKtR+TOvtDbgTPCkSof02qgBB7IsYOyf76ilExJ/upAa/vKIKheOoCyOpcLmi4t0b4uepb7LLjmMr90FUg==-----END PUBLIC KEY-----',
  signature: 'MEYCIQCfxfIWuxmWcIBQJ9c5/X7iGDJqs2RCGsBEaAjinyrrfAIhAIV6wGcTiBuV5KJUif2hokyrL+Q9ssHkad+mx2nEE25w',
  message: { metadata: { topic: TOPIC, schemaVersion: '1.0', deprecated: false }, notification: { notificationId: '49feeaeb-4982-42d9-a377-9645b8479411_33f7e043-fed8-442b-9d44-791923bd9a6d', eventDate: '2021-03-19T20:43:59.462Z', publishDate: '2021-03-19T20:43:59.679Z', publishAttemptCount: 1, data: { username: 'test_user', userId: 'ma8vp1jySJC', eiasToken: ['nY+sHZ2PrBmdj6wV', 'nY+sEZ2PrA2dj6wJ', 'nY+gAZGEpwmdj6x9', 'nY+seQ=='].join('') } } },   // eiasToken: valor público do teste do SDK
};

async function selftest() {
  const good = await verifyEcdsaSha1(SDK_VECTOR.pem, SDK_VECTOR.signature, JSON.stringify(SDK_VECTOR.message));
  const tampered = JSON.parse(JSON.stringify(SDK_VECTOR.message));
  tampered.notification.data.username = 'outro_usuario';
  const bad = await verifyEcdsaSha1(SDK_VECTOR.pem, SDK_VECTOR.signature, JSON.stringify(tampered));
  return { assinatura_valida_aceita: good === true, assinatura_adulterada_recusada: bad === false };
}

async function handleGpi(request, env, path) {
  const body = request.method === 'POST' ? await request.text() : '';
  if (body.length > MAX_BODY) return json({ error: 'requisição grande demais' }, 413);
  const denied = await authenticate(request, env, body);
  if (denied) return denied;
  let b = {};
  if (body) { try { b = JSON.parse(body); } catch (e) { return json({ error: 'JSON inválido' }, 400); } }
  try {
    if (path === '/gpi/v1/status' && request.method === 'GET') return json(await statusView(env));
    if (path === '/gpi/v1/claim' && request.method === 'POST') return json(await claim(env, b));
    if (path === '/gpi/v1/ack' && request.method === 'POST') return await ack(env, b);
    if (path === '/gpi/v1/history' && request.method === 'GET') {
      const lim = Math.max(1, Math.min(500, Number(new URL(request.url).searchParams.get('limit') || 100)));
      const rs = await env.DB.prepare(`SELECT ${PUBLIC_COLS} FROM ebay_notifications ORDER BY received_at DESC LIMIT ?`).bind(lim).all();
      return json({ itens: rs.results || [] });
    }
    if (path === '/gpi/v1/selftest' && request.method === 'POST') {
      let st;
      try { st = await selftest(); } catch (e) { st = { erro: sanitize(e.message) }; }
      return json({ ...st, ...(await statusView(env)) });
    }
  } catch (e) {
    return json({ error: 'armazenamento indisponível', detalhe: sanitize(e.message) }, 503);
  }
  return json({ error: 'não encontrado' }, 404);
}

// ------------------------------------------------------------------------------------------- cron (monitoramento)
async function runScheduled(env) {
  try {
    await requeueStale(env);
    await env.DB.prepare('DELETE FROM sync_nonces WHERE ts < ?').bind(Math.floor(Date.now() / 1000) - 2 * SYNC_SKEW_S).run();
    await env.DB.prepare('DELETE FROM rate_limits WHERE window_start < ?').bind(Math.floor(Date.now() / 1000) - 3600).run();
    const st = await statusView(env);
    if (st.alerta) await audit(env, 'cron', 'alerta_pendencias', null, st.alerta);
  } catch (e) { /* o próximo ciclo tenta de novo */ }
}

// ------------------------------------------------------------------------------------------- roteamento
async function handle(request, env, fetcher = fetch) {
  const url = new URL(request.url);
  if (url.protocol !== 'https:' && !env.ALLOW_HTTP_FOR_TESTS) return json({ error: 'HTTPS obrigatório' }, 400);
  if (url.pathname === NOTIFY_PATH) {
    if (request.method === 'GET') return handleChallenge(url, env);
    if (request.method === 'POST') return handleNotification(request, env, fetcher);
    return json({ error: 'método não permitido' }, 405, { Allow: 'GET, POST' });
  }
  if (url.pathname.startsWith('/gpi/v1/')) return handleGpi(request, env, url.pathname);
  return json({ error: 'não encontrado' }, 404);
}

export default {
  fetch: (request, env) => handle(request, env, fetch),
  scheduled: (event, env, ctx) => ctx.waitUntil(runScheduled(env)),
};
