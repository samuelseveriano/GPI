/* Gráficos SVG interativos, sem bibliotecas externas (funciona offline). */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const fmt = (v) => v == null || isNaN(v) ? '—' : Math.abs(v) >= 1000
    ? v.toLocaleString('pt-BR', { maximumFractionDigits: 0 })
    : v.toLocaleString('pt-BR', { maximumFractionDigits: Math.abs(v) < 10 ? 2 : 1 });
  window.fmtNum = fmt;
  const compact = (v) => Math.abs(v) >= 1e9 ? fmt(v / 1e9) + ' bi' : Math.abs(v) >= 1e6 ? fmt(v / 1e6) + ' mi' : Math.abs(v) >= 1e4 ? fmt(v / 1e3) + ' mil' : fmt(v);

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  function niceTicks(min, max, n = 5) {
    if (min === max) { max = min + 1; }
    const span = max - min, step0 = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const t = []; for (let v = lo; v <= hi + step / 2; v += step) t.push(+v.toFixed(10));
    return t;
  }

  /* opts: {labels, series:[{name, values, color, dash, width, dots}], bands:[{lo, hi, color, opacity, name}],
            divider: index, height, yTitle} */
  window.lineChart = function (container, opts) {
    container.innerHTML = '';
    const W = Math.max(container.clientWidth || 600, 320), H = opts.height || 320;
    const m = { l: 56, r: 16, t: 16, b: 48 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart', role: 'img' }, container);
    const n = opts.labels.length;
    const all = [];
    opts.series.forEach((s) => s.values.forEach((v) => v != null && !isNaN(v) && all.push(v)));
    (opts.bands || []).forEach((b) => { b.lo.forEach((v) => v != null && all.push(v)); b.hi.forEach((v) => v != null && all.push(v)); });
    let ymin = Math.min(0, ...all), ymax = Math.max(...all, 1);
    const ticks = niceTicks(ymin, ymax);
    ymin = ticks[0]; ymax = ticks[ticks.length - 1];
    const x = (i) => m.l + (n <= 1 ? iw / 2 : (i * iw) / (n - 1));
    const y = (v) => m.t + ih - ((v - ymin) / (ymax - ymin)) * ih;

    const g = el('g', {}, svg);
    ticks.forEach((t) => {
      el('line', { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: 'grid' }, g);
      const tx = el('text', { x: m.l - 8, y: y(t) + 4, class: 'tick', 'text-anchor': 'end' }, g);
      tx.textContent = compact(t);
    });
    const every = Math.max(1, Math.ceil(n / Math.floor(iw / 70)));
    opts.labels.forEach((lab, i) => {
      if (i % every) return;
      const tx = el('text', { x: x(i), y: H - m.b + 18, class: 'tick', 'text-anchor': 'middle' }, g);
      tx.textContent = lab;
    });
    if (opts.divider != null) {
      el('line', { x1: x(opts.divider), x2: x(opts.divider), y1: m.t, y2: m.t + ih, class: 'divider' }, g);
      const t = el('text', { x: x(opts.divider) + 6, y: m.t + 12, class: 'tick' }, g); t.textContent = 'previsão →';
    }
    (opts.bands || []).forEach((b) => {
      const pts = []; const back = [];
      b.lo.forEach((v, i) => { if (v != null && b.hi[i] != null) { pts.push(`${x(i)},${y(b.hi[i])}`); back.unshift(`${x(i)},${y(v)}`); } });
      if (pts.length) el('polygon', { points: pts.concat(back).join(' '), fill: b.color, 'fill-opacity': b.opacity || 0.18, stroke: 'none' }, g);
    });
    opts.series.forEach((s) => {
      let d = '', pen = false;
      s.values.forEach((v, i) => {
        if (v == null || isNaN(v)) { pen = false; return; }
        d += (pen ? 'L' : 'M') + x(i) + ' ' + y(v) + ' '; pen = true;
      });
      el('path', { d, fill: 'none', stroke: s.color, 'stroke-width': s.width || 2, 'stroke-dasharray': s.dash || '', 'stroke-linejoin': 'round' }, g);
      if (s.dots) s.values.forEach((v, i) => v != null && el('circle', { cx: x(i), cy: y(v), r: 2.5, fill: s.color }, g));
    });
    // legenda
    const leg = document.createElement('div'); leg.className = 'legend';
    opts.series.forEach((s) => leg.insertAdjacentHTML('beforeend', `<span><i style="background:${s.color}${s.dash ? ';opacity:.6' : ''}"></i>${s.name}</span>`));
    (opts.bands || []).forEach((b) => b.name && leg.insertAdjacentHTML('beforeend', `<span><i style="background:${b.color};opacity:${(b.opacity || .18) * 2}"></i>${b.name}</span>`));
    container.appendChild(leg);
    // interação
    const hover = el('line', { y1: m.t, y2: m.t + ih, class: 'hover', visibility: 'hidden' }, svg);
    const tip = document.createElement('div'); tip.className = 'tip'; container.appendChild(tip);
    svg.addEventListener('mousemove', (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.round(((px - m.l) / iw) * (n - 1));
      if (i < 0 || i >= n) { hover.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; return; }
      hover.setAttribute('x1', x(i)); hover.setAttribute('x2', x(i)); hover.setAttribute('visibility', 'visible');
      let h = `<b>${opts.labels[i]}</b>`;
      opts.series.forEach((s) => s.values[i] != null && (h += `<div><i style="background:${s.color}"></i>${s.name}: ${fmt(s.values[i])}</div>`));
      (opts.bands || []).forEach((b) => b.name && b.lo[i] != null && (h += `<div class="muted">${b.name}: ${fmt(b.lo[i])} – ${fmt(b.hi[i])}</div>`));
      tip.innerHTML = h; tip.style.display = 'block';
      const left = (x(i) / W) * r.width;
      tip.style.left = Math.min(left + 12, r.width - 200) + 'px'; tip.style.top = '8px';
    });
    svg.addEventListener('mouseleave', () => { hover.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; });
  };

  /* Dispersão: pts [{x, y, color, label, ring, href}] */
  window.scatterChart = function (container, pts, opts = {}) {
    container.innerHTML = '';
    const W = Math.max(container.clientWidth || 600, 320), H = opts.height || 380, m = 24;
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'chart' }, container);
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const X = (v) => m + ((v - x0) / ((x1 - x0) || 1)) * (W - 2 * m), Y = (v) => H - m - ((v - y0) / ((y1 - y0) || 1)) * (H - 2 * m);
    el('line', { x1: m, x2: W - m, y1: Y(0), y2: Y(0), class: 'grid' }, svg);
    el('line', { x1: X(0), x2: X(0), y1: m, y2: H - m, class: 'grid' }, svg);
    const tip = document.createElement('div'); tip.className = 'tip'; container.appendChild(tip);
    pts.forEach((p) => {
      const c = el('circle', { cx: X(p.x), cy: Y(p.y), r: 6, fill: p.color, 'fill-opacity': 0.8, stroke: p.ring ? 'var(--bad)' : 'none', 'stroke-width': 2.5, style: 'cursor:pointer' }, svg);
      c.addEventListener('mouseenter', () => { tip.innerHTML = p.label; tip.style.display = 'block'; tip.style.left = Math.min(X(p.x) / W * container.clientWidth + 10, container.clientWidth - 200) + 'px'; tip.style.top = (Y(p.y) / H * container.clientHeight) + 'px'; });
      c.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
      if (p.href) c.addEventListener('click', () => { location.hash = p.href.slice(1); });
    });
    const t = el('text', { x: W - m, y: H - 6, class: 'tick', 'text-anchor': 'end' }, svg); t.textContent = 'componente principal 1 →';
    const t2 = el('text', { x: m + 4, y: m - 8, class: 'tick' }, svg); t2.textContent = '↑ componente principal 2 (contorno vermelho = anomalia)';
  };

  /* Barras horizontais: items [{label, value, color, note}] */
  window.barChart = function (container, items, opts = {}) {
    container.innerHTML = '';
    const max = Math.max(...items.map((i) => i.value), 1e-9);
    const wrap = document.createElement('div'); wrap.className = 'bars';
    items.forEach((it) => {
      wrap.insertAdjacentHTML('beforeend',
        `<div class="bar-row"><span class="bar-label" title="${it.label}">${it.label}</span>
         <span class="bar-track"><span class="bar-fill" style="width:${(100 * it.value) / max}%;background:${it.color || 'var(--c1)'}"></span></span>
         <span class="bar-val">${opts.format ? opts.format(it.value) : fmt(it.value)}${it.note ? ' <small>' + it.note + '</small>' : ''}</span></div>`);
    });
    container.appendChild(wrap);
  };
})();
