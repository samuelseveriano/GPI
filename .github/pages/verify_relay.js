// Verifica a lógica de segurança da página de retorno OAuth (local ou publicada).
// Uso: node verify_relay.js caminho/para/relay.js [mercadolivre|meta]
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const PROV = process.argv[3] || 'mercadolivre';
const S = 'a'.repeat(43);
const cases = [
  ['?code=TG-abc123&state=8765.' + S, 'http://127.0.0.1:8765/oauth/' + PROV + '/retorno#code=TG-abc123&state=8765.' + S],
  ['?code=TG-abc123&state=8770.' + S, 'http://127.0.0.1:8770/oauth/' + PROV + '/retorno#code=TG-abc123&state=8770.' + S],
  ['?code=TG-abc123&state=80.' + S, null],                       // porta privilegiada/curta
  ['?code=TG-abc123&state=99999.' + S, null],                    // porta inválida
  ['?code=TG-abc123&state=8765.evil.com/' + S, null],            // tentativa de redirecionamento aberto
  ['?code=TG-abc123&state=8765.x@evil.com' + S, null],
  ['?code=<script>alert(1)</script>&state=8765.' + S, null],     // código malformado
  ['?code=TG-abc123', null],                                     // sem state
  ['?error=access_denied&error_description=negado', null],
  ['', null],
];
if (PROV === 'meta') {          // v0.8.2: códigos reais do Login do Facebook passam de 300 caracteres
  for (const n of [301, 412, 2048]) {
    const c = 'AQ' + 'x'.repeat(n - 4) + '-_';
    cases.push(['?code=' + c + '&state=8765.' + S, 'http://127.0.0.1:8765/oauth/meta/retorno#code=' + c + '&state=8765.' + S]);
  }
  cases.push(['?code=' + 'A'.repeat(2049) + '&state=8765.' + S, null]);
}
const DIAG = PROV === 'meta' ? [['?state=8765.' + S, 'M01'], ['?code=a%20b%3Ccd%3Eefgh&state=8765.' + S, 'M02'],
  ['?code=AQabcdefgh', 'M03'], ['?code=AQabcdefgh&state=8765.evil', 'M04'],
  ['?error=access_denied&error_reason=user_denied&error_description=Permissions+error', 'M06']] : [];
let fail = 0;
for (const [search, expect] of cases) {
  const els = {};
  const el = (id) => (els[id] = els[id] || { id, hidden: true, textContent: '', value: '', attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, select() {} });
  let replaced = null;
  const ctx = { document: { getElementById: el, execCommand: () => false }, navigator: {},
    window: { location: { search, pathname: '/GPI/oauth/' + PROV + '/', replace: (u) => { replaced = u; } } },
    history: { replaceState() {} }, setTimeout: (f) => f(), URLSearchParams };
  vm.runInNewContext(src, ctx);
  const link = (els.link || { attrs: {} }).attrs.href || null;
  const ok = replaced === expect && link === expect;
  if (!ok) fail++;
  console.log(`${ok ? 'OK ' : 'ERRO'} ${search.slice(0, 60) || '(vazio)'} -> ${replaced}`);
}
for (const [search, diag] of DIAG) {
  const els = {};
  const el = (id) => (els[id] = els[id] || { id, hidden: true, textContent: '', value: '', attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, select() {} });
  let replaced = null;
  vm.runInNewContext(src, { document: { getElementById: el, execCommand: () => false }, navigator: {},
    window: { location: { search, pathname: '/GPI/oauth/meta/', replace: (u) => { replaced = u; } } },
    history: { replaceState() {} }, setTimeout: (f) => f(), URLSearchParams });
  const got = (els.diag || {}).textContent;
  const leak = /abcdefgh|a b/.test((els.status || {}).textContent || '');
  const ok = got === diag && replaced === null && !leak;
  if (!ok) fail++;
  console.log(`${ok ? 'OK ' : 'ERRO'} diagnóstico ${diag} <- ${search.slice(0, 50)} (obtido ${got}${leak ? ', VAZOU O CÓDIGO' : ''})`);
}
if (/fetch\(|XMLHttpRequest|localStorage|sessionStorage|document\.cookie|eval\(|new Function/.test(src)) { console.log('ERRO: API proibida na página'); fail++; }
process.exit(fail ? 1 : 0);
