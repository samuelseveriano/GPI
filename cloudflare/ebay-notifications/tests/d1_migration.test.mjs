// v0.9 — migração D1: reproduz "No SQL statements detected." e valida a versão de console.
// O filtro de comentários abaixo é o mesmo do D1 remoto (regex /^\s*--.*/gm, cloudflare/workers-sdk PR #16686).
// Executar: node --test tests/d1_migration.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';

const MIG = readFileSync(new URL('../migrations/0001_init.sql', import.meta.url), 'utf8');
const CONSOLE = readFileSync(new URL('../console/0001_init_console.sql', import.meta.url), 'utf8');
const TABLES = ['audit_log', 'ebay_notifications', 'ebay_public_keys', 'rate_limits', 'schema_migrations', 'sync_nonces'];
const INDEXES = ['idx_audit_at', 'idx_ebay_notifications_status'];

function d1ConsoleFilter(sql) {                     // o que sobra depois do filtro de comentários do D1
  const s = sql.replace(/^\s*--.*/gm, '').trim();
  if (!s) throw new Error('No SQL statements detected.');
  return s;
}
const oneLine = (s) => s.replace(/\r?\n/g, ' ');    // quebras de linha perdidas ao colar
const objects = (db, type) => db.prepare("SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%' ORDER BY name").all(type).map((r) => r.name);

test('reproduz o erro: migração com comentários colada SEM quebras de linha → "No SQL statements detected."', () => {
  assert.throws(() => d1ConsoleFilter(oneLine(MIG)), /No SQL statements detected/);
  assert.doesNotThrow(() => d1ConsoleFilter(MIG));                // com as quebras de linha o arquivo original funciona
});

test('versão de console: sem comentários, funciona com e sem quebras de linha', () => {
  assert.ok(!CONSOLE.includes('--'));
  for (const variant of [CONSOLE, oneLine(CONSOLE), CONSOLE.replace(/\n/g, '\r\n')]) {
    const db = new DatabaseSync(':memory:');
    db.exec(d1ConsoleFilter(variant));
    assert.deepEqual(objects(db, 'table'), TABLES);
    assert.deepEqual(objects(db, 'index'), INDEXES);
  }
});

test('banco vazio → tabelas, índices e registro da migração', () => {
  const db = new DatabaseSync(':memory:');
  db.exec(CONSOLE);
  assert.equal(db.prepare('SELECT version FROM schema_migrations').get().version, '0001_init');
  assert.equal(db.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
});

test('migração parcialmente aplicada → completa sem perder dados', () => {
  const db = new DatabaseSync(':memory:');
  const first = CONSOLE.split('\n')[0];                          // só a primeira tabela foi criada
  db.exec(first);
  db.prepare("INSERT INTO ebay_notifications (notification_id, topic, received_at, last_received_at, status) VALUES ('n1', 'MARKETPLACE_ACCOUNT_DELETION', 't', 't', 'PENDING')").run();
  db.exec(CONSOLE);
  assert.deepEqual(objects(db, 'table'), TABLES);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM ebay_notifications').get().n, 1);
});

test('executada duas vezes (e com tabelas/índices já existentes) → sem erro, sem duplicar', () => {
  const db = new DatabaseSync(':memory:');
  db.exec(MIG);                                                   // aplicada antes pelo Wrangler
  db.prepare("INSERT INTO audit_log (at, actor, action) VALUES ('t', 'gpi', 'x')").run();
  db.exec(CONSOLE);
  db.exec(CONSOLE);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM schema_migrations').get().n, 1);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM audit_log').get().n, 1);
  assert.equal(db.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
});

test('cada instrução executa isoladamente (para colar uma por vez)', () => {
  const db = new DatabaseSync(':memory:');
  const lines = CONSOLE.trim().split('\n');
  assert.equal(lines.length, 9);
  for (const l of lines) db.exec(d1ConsoleFilter(l));
  assert.deepEqual(objects(db, 'table'), TABLES);
});

test('versão de console está em dia com a migração (gerada por scripts/d1_console_sql.py)', () => {
  const out = execFileSync('python3', ['-c', 'import sys; sys.path.insert(0, "scripts"); import d1_console_sql as d; print(d.build()["0001_init_console.sql"], end="")'],
    { cwd: new URL('../../../', import.meta.url).pathname, encoding: 'utf8' });
  assert.equal(out, CONSOLE);
});
