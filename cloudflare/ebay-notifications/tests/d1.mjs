// Adaptador mínimo com a API do Cloudflare D1 sobre node:sqlite (SQLite real, mesma linguagem SQL do D1).
// Usado só nos testes locais; no CI os mesmos testes também rodam no runtime real (workerd/Miniflare).
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';

export function makeD1(migrationsDir) {
  const db = new DatabaseSync(':memory:');
  const state = { down: false };
  for (const f of ['0001_init.sql']) db.exec(readFileSync(new URL(f, migrationsDir), 'utf8'));
  const check = () => { if (state.down) throw new Error('D1_ERROR: banco indisponível (simulado)'); };
  const norm = (a) => a.map((v) => (v === undefined ? null : v));
  return {
    state,
    raw: db,
    prepare(sql) {
      let args = [];
      const st = {
        bind(...a) { args = norm(a); return st; },
        async run() { check(); const r = db.prepare(sql).run(...args); return { success: true, meta: { changes: Number(r.changes) } }; },
        async first(col) { check(); const r = db.prepare(sql).get(...args); return r ? (col ? r[col] : { ...r }) : null; },
        async all() { check(); return { success: true, results: db.prepare(sql).all(...args).map((r) => ({ ...r })) }; },
      };
      return st;
    },
  };
}
