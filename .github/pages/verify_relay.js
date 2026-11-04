// Verifica a lógica de segurança da página de retorno OAuth (local ou publicada).
// Uso: node verify_relay.js caminho/para/relay.js
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const S = 'a'.repeat(43);
const cases = [
  ['?code=TG-abc123&state=8765.' + S, 'http://127.0.0.1:8765/oauth/mercadolivre/retorno#code=TG-abc123&state=8765.' + S],
  ['?code=TG-abc123&state=8770.' + S, 'http://127.0.0.1:8770/oauth/mercadolivre/retorno#code=TG-abc123&state=8770.' + S],
  ['?code=TG-abc123&state=80.' + S, null],                       // porta privilegiada/curta
  ['?code=TG-abc123&state=99999.' + S, null],                    // porta inválida
  ['?code=TG-abc123&state=8765.evil.com/' + S, null],            // tentativa de redirecionamento aberto
  ['?code=TG-abc123&state=8765.x@evil.com' + S, null],
  ['?code=<script>alert(1)</script>&state=8765.' + S, null],     // código malformado
  ['?code=TG-abc123', null],                                     // sem state
  ['?error=access_denied&error_description=negado', null],
  ['', null],
];
let fail = 0;
for (const [search, expect] of cases) {
  const els = {};
  const el = (id) => (els[id] = els[id] || { id, hidden: true, textContent: '', value: '', attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, select() {} });
  let replaced = null;
  const ctx = { document: { getElementById: el, execCommand: () => false }, navigator: {},
    window: { location: { search, pathname: '/GPI/oauth/mercadolivre/', replace: (u) => { replaced = u; } } },
    history: { replaceState() {} }, setTimeout: (f) => f(), URLSearchParams };
  vm.runInNewContext(src, ctx);
  const link = (els.link || { attrs: {} }).attrs.href || null;
  const ok = replaced === expect && link === expect;
  if (!ok) fail++;
  console.log(`${ok ? 'OK ' : 'ERRO'} ${search.slice(0, 60) || '(vazio)'} -> ${replaced}`);
}
if (/fetch\(|XMLHttpRequest|localStorage|sessionStorage|document\.cookie|eval\(|new Function/.test(src)) { console.log('ERRO: API proibida na página'); fail++; }
process.exit(fail ? 1 : 0);
