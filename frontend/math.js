/* Conversor mínimo de um subconjunto de TeX para MathML (nativo do navegador).
   Sem dependências externas — funciona offline em Edge/Chrome/Firefox. */
(function () {
  const SYM = {
    alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε', theta: 'θ',
    lambda: 'λ', mu: 'μ', sigma: 'σ', tau: 'τ', phi: 'φ', ell: 'ℓ', pi: 'π', rho: 'ρ',
    Phi: 'Φ', Sigma: 'Σ', Delta: 'Δ', Gamma: 'Γ', Theta: 'Θ', hat: null,
  };
  const OPS = {
    cdot: '·', le: '≤', ge: '≥', leq: '≤', geq: '≥', times: '×', pm: '±', approx: '≈',
    sim: '∼', in: '∈', lfloor: '⌊', rfloor: '⌋', infty: '∞', to: '→', ne: '≠', neq: '≠',
    mid: '|', qquad: '\u2003\u2003', cap: '∩', cup: '∪', ldots: '…', cdots: '⋯', bmod: ' mod ', '%': '%', dots: '…', quad: ' ', ',': ' ', ';': ' ',
    lvert: '|', rvert: '|', forall: '∀', land: '∧', Rightarrow: '⇒', '{': '{', '}': '}',
  };
  const FUNCS = ['max', 'min', 'ln', 'log', 'exp', 'sin', 'cos', 'Var', 'E', 'P', 'arg', 'sign', 'mean', 'median'];
  const BIG = { sum: '∑', prod: '∏' };

  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  function tokenize(src) {
    const t = []; let i = 0;
    while (i < src.length) {
      const c = src[i];
      if (c === '\\') {
        let j = i + 1;
        if (/[a-zA-Z]/.test(src[j])) { while (j < src.length && /[a-zA-Z]/.test(src[j])) j++; }
        else j++;
        const name = src.slice(i + 1, j);
        if (['text', 'mathrm', 'mathbb', 'operatorname'].includes(name) && src[j] === '{') {
          const end = src.indexOf('}', j);
          const raw = src.slice(j + 1, end).replace(/\\([%,&_#])/g, (_, c) => (c === ',' ? '\u2009' : c));
          t.push({ k: 'txt', cmd: name, v: raw }); i = end + 1; continue;
        }
        t.push({ k: 'cmd', v: name }); i = j;
      } else if (/\s/.test(c)) { i++; }
      else if (/[0-9]/.test(c)) {   // aceita 1.234,56 (pt-BR) como um único número
        let j = i; while (j < src.length && (/[0-9]/.test(src[j]) || (/[.,]/.test(src[j]) && /[0-9]/.test(src[j + 1] || '')))) j++;
        t.push({ k: 'num', v: src.slice(i, j) }); i = j;
      } else { t.push({ k: 'ch', v: c }); i++; }
    }
    return t;
  }

  function parse(tokens) {
    let p = 0;
    function peek() { return tokens[p]; }
    function group() {               // lê {…} ou um átomo único
      const t = peek();
      if (t && t.k === 'ch' && t.v === '{') { p++; const r = seq('}'); p++; return '<mrow>' + r + '</mrow>'; }
      return atom();
    }
    function atom() {
      const t = tokens[p++];
      if (!t) return '';
      if (t.k === 'num') return '<mn>' + t.v + '</mn>';
      if (t.k === 'txt') {
        if (t.cmd === 'text') return '<mtext>' + esc(t.v) + '</mtext>';
        if (t.cmd === 'mathbb') return '<mi mathvariant="double-struck">' + esc(t.v) + '</mi>';
        return '<mi mathvariant="normal">' + esc(t.v) + '</mi>';
      }
      if (t.k === 'ch') {
        if (/[a-zA-Z]/.test(t.v)) return '<mi>' + t.v + '</mi>';
        if (t.v === '{') { const r = seq('}'); p++; return '<mrow>' + r + '</mrow>'; }
        return '<mo>' + esc(t.v === '-' ? '−' : t.v) + '</mo>';
      }
      const c = t.v;
      if (c === 'frac') { const a = group(), b = group(); return '<mfrac>' + a + b + '</mfrac>'; }
      if (c === 'sqrt') return '<msqrt>' + group() + '</msqrt>';
      if (c === 'hat') return '<mover accent="true">' + group() + '<mo>^</mo></mover>';
      if (c === 'bar') return '<mover accent="true">' + group() + '<mo>‾</mo></mover>';
      if (c === 'tilde') return '<mover accent="true">' + group() + '<mo>~</mo></mover>';
      if (c === 'left' || c === 'right') return atom();
      if (BIG[c]) return '<mo largeop="true" movablelimits="false">' + BIG[c] + '</mo>';
      if (SYM[c]) return '<mi>' + SYM[c] + '</mi>';
      if (OPS[c] !== undefined) return '<mo>' + esc(OPS[c]) + '</mo>';
      if (FUNCS.includes(c)) return '<mi mathvariant="normal">' + c + '</mi><mo>⁡</mo>';
      return '<mi>' + esc(c) + '</mi>';
    }
    function seq(close) {
      let out = '';
      while (p < tokens.length) {
        const t = peek();
        if (close && t.k === 'ch' && t.v === close) break;
        const startTok = t;
        let base = atom();
        let sub = null, sup = null;
        while (peek() && peek().k === 'ch' && (peek().v === '_' || peek().v === '^')) {
          const op = tokens[p++].v; const g = group();
          if (op === '_') sub = g; else sup = g;
        }
        const big = startTok.k === 'cmd' && BIG[startTok.v];
        if (sub && sup) base = big ? `<munderover>${base}${sub}${sup}</munderover>` : `<msubsup>${base}${sub}${sup}</msubsup>`;
        else if (sub) base = big ? `<munder>${base}${sub}</munder>` : `<msub>${base}${sub}</msub>`;
        else if (sup) base = big ? `<mover>${base}${sup}</mover>` : `<msup>${base}${sup}</msup>`;
        out += base;
      }
      return out;
    }
    return seq(null);
  }

  window.tex = function (src, block = true) {
    return `<math xmlns="http://www.w3.org/1998/Math/MathML"${block ? ' display="block"' : ''}><mrow>${parse(tokenize(src))}</mrow></math>`;
  };
})();
