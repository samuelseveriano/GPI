/* GPI — interface (JavaScript puro, sem dependências externas). */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const main = $('#main');
  const COLORS = { hist: 'var(--c6)', fit: 'var(--c4)', fc: 'var(--c1)', band: 'var(--c1)' };
  let STATUS = null;
  const state = { freq: 'M', sku: null, run: null };

  const fmt = (v, d) => (v == null || (typeof v === 'number' && isNaN(v))) ? '—'
    : typeof v === 'number' ? v.toLocaleString('pt-BR', { maximumFractionDigits: d ?? 2, minimumFractionDigits: d ?? 0 }) : v;
  const pct = (v, d = 1) => v == null ? '—' : (100 * v).toLocaleString('pt-BR', { maximumFractionDigits: d, minimumFractionDigits: d }) + '%';
  const money = (v) => v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  const escH = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const freqLabel = (f) => (f === 'W' ? 'semanal' : 'mensal');

  async function api(path, opts = {}) {
    opts = { ...opts, headers: { 'X-GPI': '1', ...(opts.headers || {}) } };
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch { /* sem corpo */ }
    if (!r.ok) throw new Error((data && data.erro) || `erro ${r.status}`);
    return data;
  }
  const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const loading = (msg = 'Calculando…') => `<p class="muted"><span class="spinner"></span> ${msg}</p>`;
  const errBox = (e) => `<div class="banner">${escH(e.message || e)}</div>`;

  function demoBanner() {
    if (!STATUS || !STATUS.tem_demo) return '';
    return `<div class="banner"><b>Dados demonstrativos sintéticos presentes.</b> Itens com código DEMO-* foram gerados para teste e não representam vendas reais. Remova-os em <a href="#dados">Importação e Qualidade</a>.</div>`;
  }
  function freqSelect(id = 'freq') {
    return `<label class="f">Frequência<select id="${id}"><option value="M" ${state.freq === 'M' ? 'selected' : ''}>Mensal</option><option value="W" ${state.freq === 'W' ? 'selected' : ''}>Semanal</option></select></label>`;
  }
  function emptyState() {
    return `<div class="panel"><h2>Nenhum dado importado</h2><p>Importe uma planilha de vendas (CSV ou XLSX) com colunas de <b>data</b>, <b>SKU ou produto</b> e <b>quantidade</b>, ou carregue os dados demonstrativos para conhecer o sistema.</p><a class="btn" href="#dados">Ir para Importação</a></div>`;
  }
  function seriesInfo(info) {
    const parts = [`${info.n} períodos (${info.frequencia})`];
    if (info.tratamento_lacunas) parts.push(`${info.periodos_sem_registro} período(s) sem registro considerados como 0`);
    if (info.descartados && info.descartados.length) parts.push('descartado(s) por estarem incompletos: ' + info.descartados.join('; '));
    return `<p class="muted" style="font-size:12.5px">Série: ${parts.map(escH).join(' · ')}</p>`;
  }
  function trendText(t) {
    if (!t || t.aviso) return `<span class="muted">${t ? t.aviso : '—'}</span>`;
    const cls = t.direcao === 'crescimento' ? 'ok' : t.direcao === 'queda' ? 'bad' : '';
    return `<span class="badge ${cls}">${t.direcao}</span> inclinação Theil–Sen ${fmt(t.inclinacao, 2)}/período (${t.inclinacao_relativa != null ? pct(t.inclinacao_relativa) + ' da média' : '—'}), τ de Kendall = ${fmt(t.tau, 3)}, p = ${fmt(t.p_valor, 4)}`;
  }

  /* ----------------------------------------------------------------- Visão geral */
  async function pageOverview() {
    main.innerHTML = `<h1>Visão Geral</h1><p class="sub">Resumo dos dados de vendas armazenados localmente.</p>${demoBanner()}<div id="ov">${loading()}</div>`;
    if (!STATUS.linhas) { $('#ov').innerHTML = emptyState(); return; }
    const d = await api(`/api/overview?freq=${state.freq}`);
    const k = d.kpis;
    $('#ov').innerHTML = `
      <div class="kpis">
        <div class="kpi"><span>SKUs</span><b>${fmt(k.skus, 0)}</b></div>
        <div class="kpi"><span>Unidades vendidas</span><b>${fmt(k.quantidade, 0)}</b></div>
        <div class="kpi"><span>Receita registrada</span><b>${money(k.receita)}</b></div>
        <div class="kpi"><span>Período dos dados</span><b style="font-size:15px">${k.inicio.split('-').reverse().join('/')} – ${k.fim.split('-').reverse().join('/')}</b></div>
      </div>
      <div class="panel"><div class="form" style="justify-content:space-between"><h2>Unidades vendidas — total</h2>${freqSelect()}</div>
        <div class="chartbox" id="ovchart"></div>${seriesInfo(d.info)}
        <p style="font-size:13px">Tendência do total: ${trendText(d.tendencia_total)}</p></div>
      <div class="grid g2">
        <div class="panel"><h2>Unidades por categoria</h2><div id="ovcat"></div></div>
        <div class="panel"><h2>Atalhos</h2><ul>
          <li><a href="#tendencias">Quais produtos crescem ou caem de forma estatisticamente significativa?</a></li>
          <li><a href="#forecasting">Prever a demanda de um produto e comparar modelos</a></li>
          <li><a href="#abcxyz">Classificar o portfólio por valor e previsibilidade</a></li>
          <li><a href="#estoque">Calcular estoque de segurança e quantidade a comprar</a></li>
          <li><a href="#metodologia">Ver todas as fórmulas usadas</a></li></ul></div>
      </div>`;
    lineChart($('#ovchart'), { labels: d.labels, series: [{ name: 'Unidades', values: d.valores, color: COLORS.fc, dots: d.labels.length < 60 }] });
    barChart($('#ovcat'), d.categorias.map((c) => ({ label: c.category, value: c.quantidade, note: c.receita ? money(c.receita) : '' })));
    $('#freq').onchange = (e) => { state.freq = e.target.value; pageOverview(); };
  }

  /* ----------------------------------------------------------------- Produtos */
  async function pageProducts() {
    main.innerHTML = `<h1>Produtos e Histórico</h1><p class="sub">Pesquise um SKU para ver a série histórica, estatísticas e o padrão de demanda.</p>${demoBanner()}
      <div class="panel"><div class="form"><label class="f">Buscar<input id="q" placeholder="SKU ou nome" style="width:240px"></label>${freqSelect()}</div>
      <div class="scroll" id="skutable" style="margin-top:10px">${loading('Carregando…')}</div></div><div id="detail"></div>`;
    if (!STATUS.linhas) { main.insertAdjacentHTML('beforeend', emptyState()); $('#skutable').innerHTML = ''; return; }
    const load = async () => {
      const rows = await api(`/api/skus?q=${encodeURIComponent($('#q').value)}`);
      $('#skutable').innerHTML = `<table><tr><th>SKU</th><th>Produto</th><th>Categoria</th><th class="num">Unidades</th><th class="num">Receita</th><th>Primeira venda</th><th>Última venda</th></tr>
        ${rows.map((r) => `<tr class="click ${r.sku === state.sku ? 'sel' : ''}" data-sku="${escH(r.sku)}"><td>${escH(r.sku)} ${r.demo ? '<span class="badge demo">demo</span>' : ''}</td><td>${escH(r.produto)}</td><td>${escH(r.categoria)}</td><td class="num">${fmt(r.quantidade, 0)}</td><td class="num">${r.receita ? money(r.receita) : '—'}</td><td>${r.primeira}</td><td>${r.ultima}</td></tr>`).join('')}</table>`;
      main.querySelectorAll('tr[data-sku]').forEach((tr) => tr.onclick = () => { state.sku = tr.dataset.sku; load(); detail(); });
    };
    let t; $('#q').oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
    $('#freq').onchange = (e) => { state.freq = e.target.value; detail(); };
    await load();
    if (state.sku) detail();
  }

  async function detail() {
    const box = $('#detail'); if (!box || !state.sku) return;
    box.innerHTML = `<div class="panel">${loading()}</div>`;
    try {
      const h = await api(`/api/history?sku=${encodeURIComponent(state.sku)}&freq=${state.freq}`);
      const s = h.estatisticas, p = h.padrao_demanda;
      box.innerHTML = `<div class="panel"><div class="form" style="justify-content:space-between"><h2>${escH(h.sku)} — ${escH(h.produto)}</h2>
          <span><a class="btn small" href="/api/export/historico.csv?sku=${encodeURIComponent(h.sku)}&freq=${state.freq}">CSV</a> <a class="btn small" href="/api/export/historico.xlsx?sku=${encodeURIComponent(h.sku)}&freq=${state.freq}">XLSX</a>
          <button class="small primary" id="gofc">Prever demanda →</button></span></div>
        <div class="chartbox" id="hchart"></div>${seriesInfo(h.info)}</div>
        <div class="grid g2">
          <div class="panel"><h2>Estatísticas</h2><div class="kv">
            <span>Total</span><b>${fmt(s.total, 0)}</b><span>Média por período</span><b>${fmt(s.media, 2)}</b>
            <span>Desvio-padrão</span><b>${fmt(s.desvio, 2)}</b><span>Coef. de variação</span><b>${fmt(s.cv, 3)}</b>
            <span>Períodos com zero</span><b>${s.zeros}</b><span>Sazonalidade</span><b>${h.forca_sazonal == null ? 'requer 2 ciclos completos' : `${h.forca_sazonal.significativa ? '<span class="badge ok">significativa</span>' : '<span class="badge">não significativa</span>'} F<sub>S</sub> = ${fmt(h.forca_sazonal.fs, 3)}, p = ${fmt(h.forca_sazonal.p_valor, 4)}`}</b></div></div>
          <div class="panel"><h2>Tendência e padrão de demanda</h2><p style="font-size:13px">${trendText(h.tendencia)}</p>
            <p style="font-size:13px">Padrão (Syntetos–Boylan): <span class="badge">${p.padrao}</span> ADI = ${fmt(p.adi, 2)}, CV² = ${fmt(p.cv2, 3)}
            ${['intermitente', 'irregular (lumpy)'].includes(p.padrao) ? '<br><span class="muted">Sugestão: avaliar Croston-SBA e TSB no laboratório.</span>' : ''}</p>
            <p class="muted" style="font-size:12px">Fórmulas na <a href="#metodologia">Metodologia</a>, seções 8 e 9.</p></div></div>`;
      lineChart($('#hchart'), { labels: h.labels, series: [{ name: 'Unidades', values: h.valores, color: COLORS.fc, dots: h.labels.length < 60 }] });
      $('#gofc').onclick = () => { location.hash = 'forecasting'; };
    } catch (e) { box.innerHTML = errBox(e); }
  }

  /* ----------------------------------------------------------------- Tendências */
  async function pageTrends() {
    main.innerHTML = `<h1>Tendências</h1><p class="sub">Teste de Mann–Kendall e inclinação de Theil–Sen por SKU. “Estável” significa que não há evidência estatística de tendência (p ≥ 0,05).</p>${demoBanner()}
      <div class="panel"><div class="form">${freqSelect()}</div><div id="tt" style="margin-top:10px">${loading()}</div></div>`;
    if (!STATUS.linhas) { $('#tt').innerHTML = emptyState(); return; }
    $('#freq').onchange = (e) => { state.freq = e.target.value; pageTrends(); };
    const rows = await api(`/api/trends?freq=${state.freq}`);
    rows.sort((a, b) => (b.inclinacao_relativa ?? -9) - (a.inclinacao_relativa ?? -9));
    const count = (d) => rows.filter((r) => r.direcao === d).length;
    $('#tt').innerHTML = `<p><span class="badge ok">${count('crescimento')} em crescimento</span> <span class="badge">${count('estável')} estáveis</span> <span class="badge bad">${count('queda')} em queda</span></p>
      <div class="scroll"><table><tr><th>SKU</th><th>Produto</th><th class="num">Períodos</th><th>Direção</th><th class="num">Variação por período (% da média)</th><th class="num">p-valor</th></tr>
      ${rows.map((r) => `<tr class="click" data-sku="${escH(r.sku)}"><td>${escH(r.sku)}</td><td>${escH(r.produto)}</td><td class="num">${r.n}</td>
        <td><span class="badge ${r.direcao === 'crescimento' ? 'ok' : r.direcao === 'queda' ? 'bad' : ''}">${r.direcao}</span></td>
        <td class="num">${pct(r.inclinacao_relativa, 2)}</td><td class="num">${fmt(r.p_valor, 4)}</td></tr>`).join('')}</table></div>`;
    main.querySelectorAll('tr[data-sku]').forEach((tr) => tr.onclick = () => { state.sku = tr.dataset.sku; location.hash = 'produtos'; });
  }

  /* ----------------------------------------------------------------- Forecasting */
  async function pageForecast() {
    main.innerHTML = `<h1>Laboratório de Previsão</h1><p class="sub">Cada modelo é avaliado por backtesting temporal (sem vazamento de dados). O de menor erro fora da amostra é sugerido; você pode escolher outro.</p>${demoBanner()}<div id="fcform"></div><div id="fcres"></div>`;
    if (!STATUS.linhas) { $('#fcform').innerHTML = emptyState(); return; }
    const skus = await api('/api/skus');
    if (!state.sku) state.sku = skus[0].sku;
    const models = STATUS.modelos;
    $('#fcform').innerHTML = `<div class="panel"><div class="form">
      <label class="f">Produto<select id="fsku" style="max-width:300px">${skus.map((s) => `<option value="${escH(s.sku)}" ${s.sku === state.sku ? 'selected' : ''}>${escH(s.sku)} — ${escH(s.produto)}</option>`).join('')}</select></label>
      ${freqSelect()}
      <label class="f">Horizonte<select id="fh"></select></label>
      <label class="f">Critério de seleção<select id="fcrit"><option value="wape">WAPE</option><option value="rmsse">RMSSE</option><option value="mae">MAE</option></select></label>
      <label class="f">Origens do backtest<input id="forig" type="number" min="2" max="24" value="6" style="width:80px"></label>
      <button class="primary" id="frun">Executar</button></div>
      <h3>Modelos</h3><div class="checks">${Object.entries(models).map(([k, v]) => `<label><input type="checkbox" value="${k}" ${k === 'naive' ? 'checked disabled' : 'checked'}> ${v}</label>`).join('')}</div></div>`;
    const setH = () => {
      const f = $('#freq').value;
      const opts = f === 'W' ? [[4, '4 semanas'], [8, '8 semanas'], [12, '12 semanas'], [26, '26 semanas']] : [[3, '3 meses'], [6, '6 meses'], [12, '12 meses']];
      $('#fh').innerHTML = opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
      $('#fh').value = f === 'W' ? 12 : 6;
    };
    setH();
    $('#freq').onchange = (e) => { state.freq = e.target.value; setH(); };
    $('#fsku').onchange = (e) => { state.sku = e.target.value; };
    $('#frun').onclick = runForecast;
    if (state.run && state.run.sku === state.sku) showForecast(state.run, state.run.modelo_escolhido);
  }

  async function runForecast() {
    const btn = $('#frun'); btn.disabled = true;
    $('#fcres').innerHTML = `<div class="panel">${loading('Ajustando modelos e executando backtesting… pode levar alguns segundos.')}</div>`;
    try {
      const models = [...main.querySelectorAll('.checks input:checked')].map((i) => i.value);
      const r = await post('/api/forecast', { sku: $('#fsku').value, freq: $('#freq').value, horizon: +$('#fh').value,
        criterion: $('#fcrit').value, n_origins: +$('#forig').value, models });
      state.run = r;
      showForecast(r, r.modelo_escolhido);
    } catch (e) { $('#fcres').innerHTML = errBox(e); }
    btn.disabled = false;
  }

  function modelFormula(key, p) {
    const n = (v, d = 3) => fmt(v, d);
    if (key === 'naive') return tex('\\hat{y}_{T+h|T} = y_{T}');
    if (key === 'seasonal_naive') return tex(`\\hat{y}_{T+h|T} = y_{T+h-${p.m}(k+1)}`);
    if (key === 'moving_average') return tex(`\\hat{y}_{T+h|T} = \\frac{1}{${p.k}} \\sum_{i=0}^{${p.k - 1}} y_{T-i}`);
    if (key.startsWith('croston')) return tex(`\\hat{y} = (1 - ${n(p.alpha, 2)}/2) \\frac{z_{T}}{p_{T}}, \\quad \\alpha = ${n(p.alpha, 2)}`);
    if (key === 'tsb') return tex(`\\hat{y} = d_{T} z_{T}, \\quad \\alpha = ${n(p.alpha, 2)}, \\; \\beta = ${n(p.beta, 2)}`);
    if (p.spec) {
      const trend = p.spec[1] === 'A', damped = p.spec.includes('d'), seas = p.spec.slice(-1) === 'A';
      const ph = damped ? n(p.phi) + ' ' : '';
      let s = `\\ell_{t} = \\ell_{t-1}${trend ? ' + ' + ph + 'b_{t-1}' : ''} + ${n(p.alpha)} e_{t}`;
      if (trend) s += ` \\quad b_{t} = ${ph}b_{t-1} + ${n(p.beta, 4)} e_{t}`;
      if (seas) s += ` \\quad s_{t} = s_{t-${p.m}} + ${n(p.gamma, 4)} e_{t}`;
      return tex(s);
    }
    return '';
  }

  function showForecast(r, key) {
    const fit = r.modelos[key], bt = r.backtest, res = bt.resultados || {};
    const nh = r.labels.length, labels = r.labels.concat(r.labels_futuro);
    const pad = (arr, before) => before ? Array(nh).fill(null).concat(arr) : arr.concat(Array(r.horizonte).fill(null));
    const last = r.valores[nh - 1];
    const fcLine = Array(nh - 1).fill(null).concat([last], fit.previsao);
    const rows = Object.entries(res).map(([k, v]) => ({ k, ...v }));
    const best = r.modelo_escolhido;
    const anyFva = rows.some((x) => x.k !== 'naive' && x.fva_vs_naive > 0);
    const btSum = res[key] || {};
    $('#fcres').innerHTML = `
      ${r.info.demo ? '<div class="banner">Este SKU é <b>demonstrativo (sintético)</b>.</div>' : ''}
      ${bt.aviso ? `<div class="banner">${escH(bt.aviso)}. A previsão abaixo não foi validada fora da amostra — trate-a como indicativa.</div>` : ''}
      <div class="panel"><div class="form" style="justify-content:space-between"><h2>${escH(r.sku)} — ${escH(fit.nome)} ${key === best ? '<span class="badge best">sugerido</span>' : ''}</h2>
        <span><a class="btn small" href="/api/export/previsao.xlsx?run_id=${r.run_id}&model=${key}">Exportar previsão XLSX</a>
        <a class="btn small" href="/api/export/previsao.csv?run_id=${r.run_id}&model=${key}">CSV</a>
        <a class="btn small" href="#estoque">Planejar estoque →</a></span></div>
        <div class="chartbox" id="fchart"></div>${seriesInfo(r.info)}
        <p class="muted" style="font-size:12.5px">Intervalos ${fit.intervalo === 'aproximado' ? '<b>aproximados</b>' : 'analíticos'} de 80% e 95%. Cobertura empírica do intervalo de 80% no backtesting: <b>${pct(btSum.cobertura_80)}</b>${btSum.cobertura_80 != null && btSum.cobertura_80 < 0.65 ? ' — <span class="err">abaixo do nominal; a incerteza real é maior que a mostrada</span>' : ''}.</p></div>
      <div class="panel"><h2>Comparação por backtesting</h2>
        <p class="muted" style="font-size:12.5px">${bt.origens && bt.origens.length ? `${bt.origens.length} origens (treino de ${bt.origens[0]} a ${bt.origens[bt.origens.length - 1]} períodos), horizonte ${r.horizonte}, critério ${r.criterio.toUpperCase()}. Clique em uma linha para ver o modelo.` : ''}</p>
        ${!anyFva && rows.length > 1 ? '<div class="banner info">Nenhum modelo superou o Naive (FVA ≤ 0). Para este produto, a previsão mais simples é a mais confiável com os dados disponíveis.</div>' : ''}
        <div class="scroll"><table><tr><th>Modelo</th><th class="num">WAPE</th><th class="num">MAE</th><th class="num">RMSE</th><th class="num">RMSSE</th><th class="num">Bias</th><th class="num">Bias %</th><th class="num">Cobertura 80%</th><th class="num">FVA vs Naive</th></tr>
        ${rows.map((x) => x.erro ? `<tr><td>${escH(r.nomes[x.k])}</td><td colspan="8" class="muted">não aplicável: ${escH(x.erro)}</td></tr>`
          : `<tr class="click ${x.k === key ? 'sel' : ''}" data-k="${x.k}"><td>${escH(r.nomes[x.k])} ${x.k === best ? '<span class="badge best">melhor</span>' : ''}</td>
          <td class="num">${pct(x.wape)}</td><td class="num">${fmt(x.mae)}</td><td class="num">${fmt(x.rmse)}</td><td class="num">${fmt(x.rmsse, 3)}</td>
          <td class="num">${fmt(x.bias)}</td><td class="num">${pct(x.bias_pct)}</td><td class="num">${pct(x.cobertura_80, 0)}</td>
          <td class="num">${x.fva_vs_naive == null ? '—' : `<span class="${x.fva_vs_naive > 0 ? '' : 'muted'}">${pct(x.fva_vs_naive)}</span>`}</td></tr>`).join('')}</table></div>
        <p style="margin-top:8px"><a class="btn small" href="/api/export/backtest.xlsx?run_id=${r.run_id}">Exportar backtesting XLSX</a></p></div>
      <div class="grid g2">
        <div class="panel"><h2>Previsão</h2><div class="scroll"><table><tr><th>Período</th><th class="num">Previsão</th><th class="num">80%</th><th class="num">95%</th></tr>
          ${r.labels_futuro.map((l, i) => `<tr><td>${l}</td><td class="num"><b>${fmt(fit.previsao[i], 1)}</b></td><td class="num">${fmt(fit.lo80[i], 1)} – ${fmt(fit.hi80[i], 1)}</td><td class="num">${fmt(fit.lo95[i], 1)} – ${fmt(fit.hi95[i], 1)}</td></tr>`).join('')}</table></div>
          <p class="muted" style="font-size:12px">Total previsto no horizonte: <b>${fmt(fit.previsao.reduce((a, b) => a + b, 0), 0)}</b> unidades.</p></div>
        <div class="panel"><h2>Modelo ajustado</h2><div class="formula">${modelFormula(key, fit.parametros)}</div>
          <div class="kv">${Object.entries(fit.parametros).filter(([k]) => !['aicc_candidatos', 'convergiu'].includes(k)).map(([k, v]) => `<span>${k}</span><b>${typeof v === 'number' ? fmt(v, Number.isInteger(v) ? 0 : 4) : escH(v)}</b>`).join('')}
            <span>σ (resíduos)</span><b>${fmt(fit.sigma, 3)}</b>${fit.aicc != null ? `<span>AICc</span><b>${fmt(fit.aicc, 2)}</b>` : ''}</div>
          ${fit.parametros.aicc_candidatos ? `<h3>AICc dos candidatos ETS</h3><div class="kv">${Object.entries(fit.parametros.aicc_candidatos).map(([k, v]) => `<span>${k}</span><b>${fmt(v, 2)}</b>`).join('')}</div>` : ''}
          ${fit.parametros.convergiu === false ? '<p class="err">O otimizador não confirmou convergência; interprete com cautela.</p>' : ''}
          <p class="muted" style="font-size:12px">Detalhes em <a href="#metodologia">Metodologia</a>.</p></div></div>`;
    lineChart($('#fchart'), {
      labels, divider: nh - 1, height: 340,
      series: [{ name: 'Histórico', values: pad(r.valores, false), color: COLORS.hist, dots: nh < 60 },
               { name: 'Ajuste 1 passo', values: pad(fit.ajustado, false), color: COLORS.fit, dash: '4 3', width: 1.5 },
               { name: 'Previsão', values: fcLine, color: COLORS.fc, width: 2.5 }],
      bands: [{ lo: pad(fit.lo95, true), hi: pad(fit.hi95, true), color: COLORS.band, opacity: 0.12, name: 'Intervalo 95%' },
              { lo: pad(fit.lo80, true), hi: pad(fit.hi80, true), color: COLORS.band, opacity: 0.2, name: 'Intervalo 80%' }],
    });
    main.querySelectorAll('tr[data-k]').forEach((tr) => tr.onclick = () => { state.runModel = tr.dataset.k; showForecast(r, tr.dataset.k); });
    state.runModel = key;
  }

  /* ----------------------------------------------------------------- ABC/XYZ */
  async function pageAbc() {
    main.innerHTML = `<h1>ABC / XYZ</h1><p class="sub">Valor (ABC) cruzado com variabilidade (XYZ) e padrão de demanda (Syntetos–Boylan).</p>${demoBanner()}
      <div class="panel"><div class="form">${freqSelect()}<label class="f">Janela (períodos)<input id="an" type="number" value="12" min="3" max="104" style="width:90px"></label><button id="arun">Atualizar</button>
      <a class="btn" id="ax" href="#">Exportar XLSX</a></div></div><div id="ares">${loading()}</div>`;
    if (!STATUS.linhas) { $('#ares').innerHTML = emptyState(); return; }
    const load = async () => {
      const f = $('#freq').value, n = $('#an').value;
      state.freq = f; $('#ax').href = `/api/export/abcxyz.xlsx?freq=${f}&n=${n}`;
      const d = await api(`/api/abcxyz?freq=${f}&n=${n}`);
      const M = d.matriz;
      const cell = (a, x) => `<div style="background:color-mix(in srgb, var(--c3) ${Math.min(60, M[a + x] * 12)}%, var(--bg))"><b>${M[a + x]}</b><br><small>${a}${x}</small></div>`;
      $('#ares').innerHTML = `<div class="grid g2"><div class="panel"><h2>Matriz</h2><div class="matrix"><div class="h"></div><div class="h">X</div><div class="h">Y</div><div class="h">Z</div>
          ${['A', 'B', 'C'].map((a) => `<div class="h">${a}</div>${cell(a, 'X')}${cell(a, 'Y')}${cell(a, 'Z')}`).join('')}</div>
          <p class="muted" style="font-size:12px">ABC por ${d.base_abc}, janela ${d.janela.join(' a ')}. Limites: A &lt; ${pct(d.limites.abc[0], 0)}, B &lt; ${pct(d.limites.abc[1], 0)} acumulado; X ≤ ${d.limites.xyz[0]}, Y ≤ ${d.limites.xyz[1]} de CV.</p></div>
        <div class="panel"><h2>Curva de Pareto</h2><div id="pareto"></div></div></div>
        <div class="panel"><div class="scroll"><table><tr><th>SKU</th><th>Produto</th><th>Classe</th><th class="num">Valor</th><th class="num">Participação</th><th class="num">Acumulado</th><th class="num">CV</th><th>Padrão</th><th class="num">ADI</th><th class="num">CV²</th></tr>
        ${d.linhas.map((r) => `<tr><td>${escH(r.sku)}</td><td>${escH(r.produto)}</td><td><span class="badge">${r.classe}</span></td><td class="num">${d.base_abc === 'receita' ? money(r.valor) : fmt(r.valor, 0)}</td>
          <td class="num">${pct(r.participacao)}</td><td class="num">${pct(r.acumulado)}</td><td class="num">${fmt(r.cv, 3)}</td><td>${r.padrao}</td><td class="num">${fmt(r.adi, 2)}</td><td class="num">${fmt(r.cv2, 3)}</td></tr>`).join('')}</table></div></div>`;
      const cols = { A: 'var(--c3)', B: 'var(--c2)', C: 'var(--c6)' };
      barChart($('#pareto'), d.linhas.slice(0, 15).map((r) => ({ label: r.sku, value: r.participacao, color: cols[r.abc], note: 'acum. ' + pct(r.acumulado, 0) })), { format: (v) => pct(v) });
    };
    $('#arun').onclick = load; $('#freq').onchange = load;
    load().catch((e) => { $('#ares').innerHTML = errBox(e); });
  }

  /* ----------------------------------------------------------------- Estoque */
  async function pageStock() {
    main.innerHTML = `<h1>Planejamento de Estoque</h1><p class="sub">Estoque de segurança, ponto de reposição e quantidade sugerida a partir de uma previsão já executada. A sugestão exige aprovação humana — nenhuma compra é feita pelo sistema.</p><div id="st"></div>`;
    const runs = await api('/api/runs');
    if (!runs.length) { $('#st').innerHTML = `<div class="panel"><p>Execute uma previsão no <a href="#forecasting">Laboratório de Previsão</a> primeiro.</p></div>`; return; }
    const cur = state.run ? state.run.run_id : runs[0].id;
    $('#st').innerHTML = `<div class="panel"><div class="form">
      <label class="f">Previsão base<select id="srun">${runs.map((r) => `<option value="${r.id}" ${r.id === cur ? 'selected' : ''}>#${r.id} · ${escH(r.sku)} · ${freqLabel(r.freq)} · ${r.horizon} per. · ${r.created_at.replace('T', ' ')}</option>`).join('')}</select></label>
      <label class="f">Modelo<select id="smodel"></select></label></div>
      <h3>Parâmetros</h3><div class="form">
      <label class="f">Lead time (dias)<input id="lt" type="number" value="60" min="0"></label>
      <label class="f">Desvio do lead time (dias)<input id="ltsd" type="number" value="10" min="0"></label>
      <label class="f">Revisão a cada (dias)<input id="rv" type="number" value="30" min="0"></label>
      <label class="f">Nível de serviço<select id="sl">${[0.8, 0.85, 0.9, 0.95, 0.975, 0.99].map((v) => `<option value="${v}" ${v === 0.95 ? 'selected' : ''}>${pct(v, 1)}</option>`).join('')}</select></label>
      <label class="f">Estoque em mãos<input id="oh" type="number" value="0" min="0"></label>
      <label class="f">Em trânsito<input id="it" type="number" value="0" min="0"></label>
      <label class="f">MOQ<input id="moq" type="number" value="0" min="0"></label>
      <label class="f">Múltiplo de compra<input id="mult" type="number" value="1" min="1"></label>
      <label class="f">Custo unitário (R$)<input id="uc" type="number" step="0.01" placeholder="opcional"></label>
      <label class="f">Custo por pedido (R$)<input id="oc" type="number" step="0.01" placeholder="opcional"></label>
      <label class="f">Taxa de manutenção anual<input id="hr" type="number" step="0.01" placeholder="ex.: 0,25"></label>
      <button class="primary" id="scalc">Calcular</button></div></div><div id="sres"></div>`;
    const loadModels = async () => {
      const run = await api(`/api/runs/${$('#srun').value}`);
      state.run = run;
      $('#smodel').innerHTML = Object.entries(run.modelos).filter(([, v]) => !v.erro).map(([k, v]) => `<option value="${k}" ${k === run.modelo_escolhido ? 'selected' : ''}>${escH(v.nome)}${k === run.modelo_escolhido ? ' (sugerido)' : ''}</option>`).join('');
    };
    $('#srun').onchange = loadModels;
    await loadModels();
    $('#scalc').onclick = calcStock;
  }

  async function calcStock() {
    const v = (id) => $('#' + id).value;
    const body = { run_id: +v('srun'), model: v('smodel'), lead_time_days: v('lt'), lead_time_sd_days: v('ltsd'), review_days: v('rv'),
      service_level: v('sl'), on_hand: v('oh'), in_transit: v('it'), moq: v('moq'), order_multiple: v('mult'),
      unit_cost: v('uc'), order_cost: v('oc'), holding_rate_year: v('hr').replace(',', '.') };
    try {
      const r = await post('/api/inventory', body);
      const n = (x, d = 1) => fmt(x, d);
      $('#sres').innerHTML = `
        ${r.horizonte_insuficiente ? '<div class="banner">O horizonte da previsão é menor que lead time + revisão; o último valor previsto foi repetido para completar o período. Prefira um horizonte maior.</div>' : ''}
        <div class="kpis">
          <div class="kpi"><span>Estoque de segurança</span><b>${n(r.estoque_seguranca)}</b></div>
          <div class="kpi"><span>Ponto de reposição</span><b>${n(r.ponto_reposicao)}</b></div>
          <div class="kpi"><span>Posição atual</span><b>${n(r.posicao_estoque)}</b></div>
          <div class="kpi"><span>Quantidade sugerida</span><b>${n(r.qtd_sugerida, 0)}</b></div>
          ${r.capital_necessario != null ? `<div class="kpi"><span>Capital necessário</span><b>${money(r.capital_necessario)}</b></div>` : ''}
          ${r.eoq != null ? `<div class="kpi"><span>EOQ (referência)</span><b>${n(r.eoq, 0)}</b></div>` : ''}
        </div>
        <div class="panel"><h2>${r.deve_pedir_agora ? '<span class="badge bad">posição ≤ ponto de reposição</span>' : '<span class="badge ok">posição acima do ponto de reposição</span>'}</h2>
          ${r.efeito_moq ? `<div class="banner">A quantidade calculada (${n(r.qtd_calculada, 0)}) é menor que o MOQ; a sugestão foi elevada ao MOQ, o que gera excesso de estoque.</div>` : ''}
          <h3>Cálculo passo a passo</h3>
          <div class="formula">${tex(`L = ${n(r.L_periodos, 3)}, \\quad R = ${n(r.R_periodos, 3)} \\; \\text{períodos}, \\quad z = ${n(r.z, 4)}, \\quad \\sigma_{d} = ${n(r.sigma_d, 3)}`)}</div>
          <p class="muted" style="font-size:12px">σ<sub>d</sub>: ${escH(r.fonte_sigma)} do modelo ${escH(r.modelo)}.</p>
          <div class="formula">${tex(`SS = z \\sqrt{L \\sigma_{d}^{2} + \\bar{d}^{2} \\sigma_{L}^{2}} = ${n(r.z, 3)} \\times ${n(r.sigma_lead_time, 3)} = ${n(r.estoque_seguranca)}`)}</div>
          <div class="formula">${tex(`\\mathrm{ROP} = \\sum_{t=1}^{L} \\hat{y}_{T+t} + SS = ${n(r.demanda_lead_time)} + ${n(r.estoque_seguranca)} = ${n(r.ponto_reposicao)}`)}</div>
          <div class="formula">${tex(`S = \\sum_{t=1}^{L+R} \\hat{y}_{T+t} + z \\sigma_{L+R} = ${n(r.demanda_L_mais_R)} + ${n(r.estoque_seguranca_revisao)} = ${n(r.nivel_alvo_S)}`)}</div>
          <div class="formula">${tex(`Q = \\max(0; \\; S - E_{\\text{mão}} - E_{\\text{trânsito}}) = \\max(0; \\; ${n(r.nivel_alvo_S)} - ${n(r.posicao_estoque)}) = ${n(r.qtd_calculada)} \\to ${n(r.qtd_sugerida, 0)}`)}</div>
          ${r.eoq != null ? `<div class="formula">${tex(`\\mathrm{EOQ} = \\sqrt{\\frac{2 D K}{i c}}, \\quad D = ${n(r.demanda_anual_estimada, 0)} \\; \\text{un/ano} \\quad \\Rightarrow \\quad ${n(r.eoq, 0)}`)}</div>` : ''}
          <p class="muted" style="font-size:12px">Cobertura atual: ${r.cobertura_periodos == null ? '—' : n(r.cobertura_periodos, 2) + ' períodos'}. Nível de serviço de ciclo = probabilidade de não romper durante um ciclo; não é fill rate. Premissas na <a href="#metodologia">Metodologia</a>, seção 10.</p></div>`;
    } catch (e) { $('#sres').innerHTML = errBox(e); }
  }

  /* ----------------------------------------------------------------- Dados */
  async function pageData() {
    main.innerHTML = `<h1>Importação e Qualidade dos Dados</h1><p class="sub">Arquivos CSV ou XLSX com uma linha por venda (ou por dia/SKU). Tudo fica gravado localmente.</p>
      <div class="panel"><div class="drop" id="drop">Arraste aqui um arquivo .csv ou .xlsx, ou <label style="color:var(--c1);cursor:pointer"><u>escolha um arquivo</u><input type="file" id="file" accept=".csv,.xlsx,.txt" hidden></label></div>
        <div id="impres"></div>
        <h3>Colunas reconhecidas</h3><table><tr><th>Campo</th><th>Obrigatório</th><th>Nomes aceitos (sem acento, maiúsc./minúsc.)</th></tr>
        <tr><td>Data</td><td>sim</td><td>data, date, dia, data_venda, periodo — formatos dd/mm/aaaa ou aaaa-mm-dd</td></tr>
        <tr><td>Quantidade</td><td>sim</td><td>quantidade, qtd, qtde, qty, unidades, vendas</td></tr>
        <tr><td>SKU / Produto</td><td>ao menos um</td><td>sku, codigo, cod_produto, id_produto · produto, descricao, nome</td></tr>
        <tr><td>Categoria</td><td>não</td><td>categoria, grupo, familia, departamento</td></tr>
        <tr><td>Preço unitário</td><td>não</td><td>preco, preco_unitario, valor_unitario — aceita 1.234,56</td></tr></table></div>
      <div class="panel"><div class="form" style="justify-content:space-between"><h2>Importações</h2>
        <span><button id="demo">Carregar dados demonstrativos</button> <button id="bkp">Fazer backup do banco</button></span></div><div id="imps"></div></div>`;
    renderImports();
    const drop = $('#drop');
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
    drop.ondragleave = () => drop.classList.remove('over');
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); };
    $('#file').onchange = (e) => e.target.files[0] && upload(e.target.files[0]);
    $('#demo').onclick = async () => { $('#impres').innerHTML = loading('Gerando…'); try { showImport(await post('/api/demo', {})); } catch (e) { $('#impres').innerHTML = errBox(e); } await refresh(); renderImports(); };
    $('#bkp').onclick = async () => { try { const r = await post('/api/backup', {}); alert('Backup criado em data/backups/' + r.arquivo); } catch (e) { alert(e.message); } };
  }
  async function upload(file) {
    $('#impres').innerHTML = loading('Importando e validando…');
    try {
      const r = await api('/api/import', { method: 'POST', headers: { 'X-Filename': encodeURIComponent(file.name).replace(/%20/g, ' ') }, body: file });
      showImport(r);
    } catch (e) { $('#impres').innerHTML = errBox(e); }
    await refresh(); renderImports();
  }
  function showImport(r) {
    $('#impres').innerHTML = `<div class="banner info" style="margin-top:12px"><b>${fmt(r.linhas_validas, 0)} linhas importadas</b>, ${fmt(r.linhas_rejeitadas, 0)} rejeitadas · ${r.skus} SKUs · período ${r.periodo.join(' a ')}<br>
      Mapeamento: ${Object.entries(r.colunas).map(([k, v]) => `${k} ← <code>${escH(v)}</code>`).join(' · ')}</div>
      ${r.rejeicoes.length ? `<h3>Linhas rejeitadas (primeiras ${r.rejeicoes.length})</h3><div class="scroll" style="max-height:200px"><table><tr><th>Linha do arquivo</th><th>Motivo</th></tr>${r.rejeicoes.map((x) => `<tr><td>${x.linha}</td><td>${escH(x.motivo)}</td></tr>`).join('')}</table></div>` : ''}`;
  }
  function renderImports() {
    const box = $('#imps'); if (!box) return;
    const im = STATUS.importacoes;
    box.innerHTML = !im.length ? '<p class="muted">Nenhuma importação.</p>' : `<table><tr><th>#</th><th>Arquivo</th><th>Origem</th><th>Data</th><th class="num">Linhas válidas</th><th class="num">Rejeitadas</th><th></th></tr>
      ${im.map((i) => `<tr><td>${i.id}</td><td>${escH(i.filename)}</td><td>${i.is_demo ? '<span class="badge demo">' + escH(i.source) + '</span>' : escH(i.source)}</td><td>${i.imported_at.replace('T', ' ')}</td>
      <td class="num">${fmt(i.rows_ok, 0)}</td><td class="num">${fmt(i.rows_rejected, 0)}</td><td><button class="small" data-del="${i.id}">Remover</button></td></tr>`).join('')}</table>`;
    box.querySelectorAll('[data-del]').forEach((b) => b.onclick = async () => {
      if (!confirm('Remover esta importação e todas as suas linhas? Esta ação não pode ser desfeita (faça backup antes, se necessário).')) return;
      await api('/api/imports/' + b.dataset.del, { method: 'DELETE' });
      state.run = null; state.sku = null; await refresh(); renderImports();
    });
  }

  /* ----------------------------------------------------------------- Sistema */
  function pageSystem() {
    const s = STATUS;
    main.innerHTML = `<h1>Sistema e Configurações</h1><p class="sub">Informações para o usuário e para revisão da equipe de TI.</p>
      <div class="grid g2"><div class="panel"><h2>Estado</h2><div class="kv">
        <span>Versão</span><b>${s.versao}</b><span>Banco de dados</span><b>${s.motor_banco === 'duckdb' ? 'DuckDB' : 'SQLite (embutido no Python)'}</b>
        <span>Versão do schema</span><b>${s.versao_schema}</b><span>Linhas de vendas</span><b>${fmt(s.linhas, 0)}</b><span>SKUs</span><b>${fmt(s.skus, 0)}</b>
        <span>Período</span><b>${s.periodo[0] || '—'} a ${s.periodo[1] || '—'}</b></div></div>
      <div class="panel"><h2>Segurança e privacidade</h2><ul style="font-size:13px">
        <li>Servidor escuta somente em <code>127.0.0.1</code> — não acessível pela rede.</li>
        <li>Requisições com cabeçalho Host diferente de localhost são recusadas.</li>
        <li>Conexões externas apenas para as APIs públicas listadas em docs/TI.md (somente leitura); telemetria inexistente.</li>
        <li>Dados, logs e backups ficam na pasta <code>data/</code> do programa.</li>
        <li>Encerramento por <code>Stop_GPI.bat</code> usa token local de uso único.</li></ul></div></div>
      <div class="panel"><h2>Encerrar o GPI</h2><p class="small">Fecha o servidor local com segurança (o mesmo que fechar a janela "GPI em execução"). Os dados ficam salvos.</p><button id="quit">Encerrar GPI</button></div>
      <div class="panel"><h2>Conectores externos</h2><p>O estado real de cada fonte (funcional, restrita, com falha) está em <a href="#fontes">Saúde das fontes</a>. Endereços acessados e configuração de proxy/certificados: <code>docs/TI.md</code>.</p></div>`;
  }

  document.addEventListener('click', async (e) => {
    if (e.target.id !== 'quit' || !confirm('Encerrar o GPI agora?')) return;
    await post('/api/app/quit', {}).catch(() => {});
    document.body.innerHTML = '<main style="padding:40px"><h1>GPI encerrado</h1><p>Pode fechar esta aba. Para abrir novamente, clique duas vezes em GPI.exe.</p></main>';
  });

  /* ----------------------------------------------------------------- Roteamento */
  const PAGES = { 'visao-geral': pageOverview, produtos: pageProducts, tendencias: pageTrends, forecasting: pageForecast,
    abcxyz: pageAbc, estoque: pageStock, dados: pageData, metodologia: () => { main.innerHTML = METHODOLOGY(); }, sistema: pageSystem };
  Object.assign(PAGES, window.GPI_MARKET({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }));
  Object.assign(PAGES, window.GPI_MARKET3({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }));
  Object.assign(PAGES, window.GPI_CONSUMER({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }));
  Object.assign(PAGES, window.GPI_V05({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  Object.assign(PAGES, window.GPI_V06({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  Object.assign(PAGES, window.GPI_V061({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  Object.assign(PAGES, window.GPI_V07({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  Object.assign(PAGES, window.GPI_V071({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  if (window.GPI_V08) Object.assign(PAGES, window.GPI_V08({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  if (window.GPI_V081) Object.assign(PAGES, window.GPI_V081({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));
  if (window.GPI_V09) Object.assign(PAGES, window.GPI_V09({ api, post, fmt, pct, money, escH, loading, errBox, main, $ }, PAGES));


  async function refresh() {
    STATUS = await api('/api/status');
    $('#foot').innerHTML = `Vendas próprias: ${fmt(STATUS.linhas, 0)} linhas<br>banco ${STATUS.motor_banco} · v${STATUS.versao}${STATUS.tem_demo ? '<br><span style="color:#f5c26b">contém dados demonstrativos</span>' : ''}`;
  }

  async function route() {
    const id = location.hash.slice(1).split('?')[0];
    if (id.startsWith('m-')) { // âncoras da metodologia
      if (!document.querySelector('.method')) { await PAGES.metodologia(); document.getElementById(id)?.scrollIntoView(); }
      return;
    }
    const [page, ...rest] = id.split('/');
    const arg = rest.length ? decodeURIComponent(rest.join('/')) : undefined;
    const key = PAGES[page] ? page : 'dashboard';
    const navKey = key === 'produto' ? 'oportunidades' : key === 'produto-consumo' ? 'dashboard'
      : key.startsWith('conformidade-') && !document.querySelector(`#nav a[href="#${key}"]`) ? 'conformidade'
      : key === 'consumo' ? 'consumo/' + ((arg || 'BR').toUpperCase())
      : (key === 'social' || key === 'relatorios') && arg ? key + '/' + arg : key;
    document.title = 'GPI — ' + ((document.querySelector(`#nav a[href="#${navKey}"]`) || {}).textContent || 'Global Product Intelligence');
    window.GPI_SHELL.onRoute(navKey);
    if (window.GPI_EXPORT) window.GPI_EXPORT.onRoute(key, arg);
    try { if (!STATUS) await refresh(); await PAGES[key](arg); window.scrollTo(0, 0); }
    catch (e) { main.innerHTML = `<h1>Erro</h1>${errBox(e)}<p class="muted">Se o problema persistir, consulte data/logs/gpi.log.</p>`; }
  }
  window.addEventListener('hashchange', route);
  window.addEventListener('resize', () => { clearTimeout(window._rz); window._rz = setTimeout(() => { if (['#visao-geral', '#produtos', '#clusters'].includes(location.hash)) route(); }, 300); });
  route();
})();
