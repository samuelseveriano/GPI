/* GPI Fase 2 — páginas de inteligência de mercado (painel autônomo). */
window.GPI_MARKET = function (H) {
  const { api, post, fmt, pct, escH, loading, errBox, main, $ } = H;
  const usd = (v) => v == null ? '—' : 'US$ ' + (Math.abs(v) >= 1e9 ? fmt(v / 1e9, 2) + ' bi' : Math.abs(v) >= 1e6 ? fmt(v / 1e6, 1) + ' mi' : fmt(v, 0));
  const growth = (v) => v == null ? '<span class="muted">—</span>' : `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${v > 0 ? '+' : ''}${pct(v, 0)}</span>`;
  const STATE = { funcional: ['ok', 'funcional'], restrita: ['', 'restrita'], falhou: ['bad', 'falhou'], nao_testada: ['', 'não testada'], aguardando: ['', 'aguardando'], 'sem dados': ['', 'sem dados'] };
  const badgeState = (s, validated) => { const [c, t] = STATE[s] || ['', s]; return `<span class="badge ${c}">${t}</span>${s === 'falhou' && validated ? ' <span class="badge ok" title="Já realizou coleta real validada anteriormente">validada antes</span>' : ''}`; };
  const DISCLAIMER = '<p class="muted small">O score é uma classificação heurística para priorizar investigação — <b>não é probabilidade de sucesso nem recomendação de importação</b>. Custos, margem, demanda efetiva e risco precisam ser estimados antes de qualquer compra.</p>';
  const label = (r) => r ? `<span class="badge lbl">${escH(r)}</span>` : '';
  const prodLink = (r) => `<a href="#produto/${encodeURIComponent(r.product_key)}">${escH(r.nome || r.product_key)}</a>`;
  const scoreBar = (s) => s == null ? '—' : `<span class="score"><i style="width:${s}%"></i><b>${fmt(s, 0)}</b></span>`;

  /* ------------------------------------------------------------ barra de sincronização */
  let pollT = null;
  async function pollSync() {
    clearTimeout(pollT);
    if (window.GPI_SYNC) return;                 // v0.6.1: barra e painel em tempo real (v061.js)
    let st; try { st = await api('/api/sync/status'); } catch { pollT = setTimeout(pollSync, 10000); return; }
    const bar = $('#syncbar');
    if (st.rodando) {
      const p = st.total ? Math.round((100 * st.feitos) / st.total) : 0;
      bar.innerHTML = `<span class="spinner"></span> <b>Sincronizando</b> — ${escH(st.fase)}: ${escH(st.atual || '')} ${st.total ? `(${st.feitos}/${st.total})` : ''}
        <span class="prog"><i style="width:${st.fase === 'analisando' ? 100 : p}%"></i></span> <button class="small" id="sync-cancel">Cancelar</button>
        <span class="muted small">Os dados anteriores continuam disponíveis.</span>`;
      bar.style.display = 'flex';
      $('#sync-cancel').onclick = () => post('/api/sync/cancel', {});
      pollT = setTimeout(pollSync, 2500);
      window._wasSyncing = true;
    } else {
      bar.style.display = 'none';
      if (window._wasSyncing) { window._wasSyncing = false; if (['', '#painel', '#fontes', '#oportunidades'].includes(location.hash)) window.dispatchEvent(new HashChangeEvent('hashchange')); }
      pollT = setTimeout(pollSync, 30000);
    }
  }
  setTimeout(pollSync, 300);

  /* ------------------------------------------------------------ modal de série (gráfico + proveniência) */
  async function openSeries(id) {
    const m = $('#modal'); m.style.display = 'flex';
    m.querySelector('.modal-body').innerHTML = loading('Carregando série…');
    try {
      const s = await api('/api/market/series/' + id);
      const f = s.previsao, meta = s.meta;
      const nh = s.labels.length;
      let labels = s.labels, series = [{ name: 'Observado', values: s.valores, color: 'var(--c6)', dots: nh < 50 }], bands = [], divider = null;
      if (f && f.status === 'prevista') {
        const fl = f.labels_futuro, pad = (a) => Array(nh).fill(null).concat(a);
        labels = labels.concat(fl);
        series[0].values = s.valores.concat(Array(fl.length).fill(null));
        series.push({ name: 'Projeção', values: Array(nh - 1).fill(null).concat([s.valores[nh - 1]], f.previsao), color: 'var(--c1)', width: 2.5 });
        bands = [{ lo: pad(f.lo95), hi: pad(f.hi95), color: 'var(--c1)', opacity: .12, name: 'Intervalo 95%' },
                 { lo: pad(f.lo80), hi: pad(f.hi80), color: 'var(--c1)', opacity: .2, name: 'Intervalo 80%' }];
        divider = nh - 1;
      }
      const prov = [['Fonte', meta.source], ['Indicador', meta.indicator], ['Tipo de dado', s.tipo_descricao], ['Produto', meta.product_name || '—'],
        ['Categoria', meta.category || '—'], ['País / fluxo', meta.country || '—'], ['Unidade', meta.unit || '—'], ['Moeda', meta.currency || '—'],
        ['Frequência', meta.freq === 'M' ? 'mensal' : meta.freq === 'D' ? 'diária' : meta.freq], ['Confiabilidade', `${meta.reliability} — ${s.confiabilidade_descricao || ''}`],
        ['Método de obtenção', meta.method], ['Origem (URL)', `<a href="${escH(meta.origin_url)}" target="_blank" rel="noopener" style="word-break:break-all">${escH(meta.origin_url)}</a>`],
        ['Período de referência', `${s.labels[0] || '—'} a ${s.labels[nh - 1] || '—'} (${nh} observações)`], ['Primeira coleta', meta.first_collected], ['Última coleta', s.ultima_coleta],
        ['Observações revisadas pela fonte', s.revisoes]];
      m.querySelector('.modal-body').innerHTML = `<h2>${escH(meta.product_name || meta.indicator)}</h2><p class="muted">${escH(meta.indicator)} · ${escH(meta.country || '')}</p>
        <div class="chartbox" id="mchart"></div>
        ${f ? (f.status === 'prevista' ? `<div class="banner info small"><b>${escH(f.tipo_descricao)}.</b> Modelo escolhido automaticamente: <b>${escH(f.modelo_nome)}</b> entre ${f.candidatos.length} candidatos · qualidade <b>${escH(f.qualidade)}</b> (WAPE no backtesting ${pct(f.metricas && f.metricas.wape)}, cobertura do intervalo 80%: ${pct(f.metricas && f.metricas.cobertura_80, 0)}).
            ${(f.limitacoes || []).length ? '<br>Limitações: ' + f.limitacoes.map(escH).join('; ') : ''}</div>
            <details><summary>Comparação dos modelos candidatos</summary><table><tr><th>Modelo</th><th class="num">WAPE</th><th class="num">RMSSE</th><th class="num">Cobertura 80%</th><th class="num">FVA</th></tr>
            ${Object.entries(f.backtest || {}).map(([k, v]) => v.erro ? `<tr><td>${k}</td><td colspan="4" class="muted">${escH(v.erro)}</td></tr>` : `<tr><td>${k}${k === f.modelo ? ' <span class="badge best">escolhido</span>' : ''}</td><td class="num">${pct(v.wape)}</td><td class="num">${fmt(v.rmsse, 3)}</td><td class="num">${pct(v.cobertura_80, 0)}</td><td class="num">${pct(v.fva_vs_naive)}</td></tr>`).join('')}</table></details>
            ${(f.avaliacao_anteriores || []).length ? `<p class="small">Previsões anteriores avaliadas contra o realizado: ${f.avaliacao_anteriores.map((a) => `${a.criada_em.slice(0, 10)} (${a.modelo}): WAPE ${pct(a.wape_realizado)} em ${a.periodos_avaliados} meses`).join('; ')}</p>` : ''}`
          : `<div class="banner small">${escH(f.limitacao || 'Sem previsão quantitativa')}</div>`) : '<p class="muted small">Sem previsão automática para esta série (somente séries mensais prioritárias são projetadas).</p>'}
        <h3>Origem do dado</h3><div class="kv">${prov.map(([k, v]) => `<span>${k}</span><b>${typeof v === 'string' && v.startsWith('<a') ? v : escH(v ?? '—')}</b>`).join('')}</div>`;
      lineChart($('#mchart'), { labels, series, bands, divider, height: 300 });
    } catch (e) { m.querySelector('.modal-body').innerHTML = errBox(e); }
  }
  window.openSeries = openSeries;
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-series]'); if (t) { e.preventDefault(); openSeries(t.dataset.series); }
    if (e.target.id === 'modal' || e.target.classList.contains('modal-close')) $('#modal').style.display = 'none';
  });

  function rankTable(rows, opts = {}) {
    if (!rows || !rows.length) return `<p class="muted small">${opts.empty || 'Sem itens com dados suficientes.'}</p>`;
    if (opts.compact) return `<div class="scroll"><table><tr><th>#</th><th>Produto</th><th class="num">12 meses</th><th>Score</th></tr>
      ${rows.map((r, i) => `<tr><td>${i + 1}</td><td class="trunc" title="${escH(r.nome)} — ${escH(r.rotulo || '')}">${prodLink(r)}<br><span class="muted small">${escH(r.categoria || '')} · ${escH((r.tipo_sinal || '').split(' (')[0])}</span></td>
      <td class="num">${growth(r.crescimento_12m)}</td><td>${scoreBar(r.score)}</td></tr>`).join('')}</table></div>`;
    return `<div class="scroll"><table><tr><th>#</th><th>Produto</th><th>Categoria</th><th>Sinal</th><th class="num">12 meses</th><th>Classificação</th><th>Score</th><th></th></tr>
      ${rows.map((r, i) => `<tr><td>${i + 1}</td><td>${prodLink(r)}</td><td>${escH(r.categoria || '')}</td><td class="small muted">${escH(r.tipo_sinal || '')}</td>
      <td class="num">${growth(r.crescimento_12m)}</td><td>${label(r.rotulo)}</td><td>${scoreBar(r.score)}</td>
      <td>${r.serie_principal ? `<a href="#" data-series="${r.serie_principal}" class="small">série</a>` : ''}</td></tr>`).join('')}</table></div>`;
  }

  /* ------------------------------------------------------------ PAINEL */
  const TITLES = { resumo: 'Visão Geral', global: 'Radar Global', brasil: 'Brasil', china: 'China', ml: 'Machine Learning' };
  async function pagePainel(tab) {
    tab = tab || 'resumo';
    main.innerHTML = `<div class="form" style="justify-content:space-between;align-items:center"><div><h1>${TITLES[tab] || 'Inteligência de Mercado'}</h1>
      <p class="sub" id="psub">Coleta, análise e previsões automáticas a partir de fontes públicas.</p></div>
      <button id="psync" class="primary">Atualizar agora</button></div><div id="pbody">${loading('Carregando resultados…')}</div>`;
    $('#psync').onclick = async () => { await post('/api/sync/run', {}); pollSync(); };
    let d, src;
    try { [d, src] = await Promise.all([api('/api/market/overview'), api('/api/market/sources')]); } catch (e) { $('#pbody').innerHTML = errBox(e); return; }
    const ok = src.filter((s) => s.estado === 'funcional').length, restr = src.filter((s) => s.estado === 'restrita').length, fail = src.filter((s) => s.estado === 'falhou').length;
    $('#psub').innerHTML = `${d.gerado_em ? 'Análise de ' + d.gerado_em.replace('T', ' ').slice(0, 16) : 'Ainda sem análise'} · ${fmt(d.n_series, 0)} séries, ${fmt(d.n_obs, 0)} observações · fontes: <span class="badge ok">${ok} funcionais</span> <span class="badge">${restr} restritas</span> ${fail ? `<span class="badge bad">${fail} com falha</span>` : ''}`;
    if (!d.n_obs) {
      const title = fail && !ok ? 'Nenhuma fonte pública acessível a partir desta rede' : 'Aguardando a primeira coleta';
      $('#pbody').innerHTML = `<div class="panel"><h2>${title}</h2>
        <p>O GPI busca dados automaticamente em fontes públicas (Comex Stat, Banco Central, IBGE, Wikimedia, UN Comtrade). A primeira sincronização começa sozinha ao abrir o programa e pode levar alguns minutos; a análise completa (previsões e ranking) roda em seguida.</p>
        <p>Se nada aparecer, verifique em <a href="#fontes">Saúde das fontes</a> se a rede da empresa permite acesso a esses endereços. Nenhum dado é inventado enquanto as fontes estiverem indisponíveis.</p>${sourcesTable(src, true)}</div>`;
      return;
    }
    $('#pbody').innerHTML = `<div id="tabbody"></div>`;
    const tb = $('#tabbody'), rk = d.rankings || {};
    if (tab === 'resumo') {
      let rv = {}, yt = {};
      try { [rv, yt] = await Promise.all([api('/api/market/reviews'), api('/api/market/youtube')]); } catch { /* opcionais */ }
      const named = (keys) => (keys || []).map((k) => (rv.produtos || []).find((p) => p.product_key === k)).filter(Boolean);
      tb.innerHTML = `<div class="kpis">
          <div class="kpi"><span>Fontes funcionais</span><b>${ok} <small class="muted">de ${src.length}</small></b><span><a href="#fontes">saúde das fontes</a></span></div>
          <div class="kpi"><span>Produtos analisados</span><b>${fmt(d.n_produtos, 0)}</b><span><a href="#oportunidades">ranking</a></span></div>
          <div class="kpi"><span>Opiniões analisadas (NLP local)</span><b>${fmt(rv.total_opinioes || 0, 0)}</b><span><a href="#reviews">reviews</a></span></div>
          <div class="kpi"><span>Vídeos do YouTube</span><b>${fmt(yt.total_videos || 0, 0)}</b><span><a href="#youtube">YouTube</a></span></div>
          <div class="kpi"><span>Previsões automáticas</span><b>${fmt((d.ml && d.ml.total) || 0, 0)}</b><span><a href="#previsoes">forecasting</a></span></div></div>
        <div class="grid g2"><div class="panel"><h2>Promissores para investigação de importação</h2>${DISCLAIMER}${rankTable((rk.promissores_importacao || rk.investigacao_importacao || []).slice(0, 8), { compact: true })}</div>
        <div class="panel"><h2>Produtos emergentes</h2>${rankTable((rk.produtos_emergentes || rk.emergentes || []).slice(0, 8), { compact: true, empty: 'Nenhum produto emergente nesta análise.' })}</div></div>
        <div class="grid g2"><div class="panel"><h2>Mais criticados nas opiniões</h2>${named(rv.mais_criticados).slice(0, 6).map((p) => `<p class="small"><a href="#reviews/${encodeURIComponent(p.product_key)}">${escH(p.nome)}</a> — ${p.negativos} de ${p.n} opiniões negativas${p.problemas.length ? ': ' + p.problemas.slice(0, 2).map((x) => escH(x.aspecto)).join(', ') : ''}</p>`).join('') || '<p class="muted small">Sem opiniões suficientes (conecte Reddit ou aguarde os feeds RSS).</p>'}</div>
        <div class="panel"><h2>Categorias com maior aceleração</h2><div id="catacc"></div></div></div>`;
      const cats = d.categorias_aceleracao || [];
      if (cats.length) barChart($('#catacc'), cats.map((c) => ({ label: c.categoria, value: Math.abs(c.aceleracao_media) + 1e-9, color: c.aceleracao_media >= 0 ? 'var(--c3)' : 'var(--c5)' })), { format: () => '' });
      main.querySelectorAll('#catacc .bar-val').forEach((el, i) => { el.innerHTML = `<b>${(cats[i].aceleracao_media > 0 ? '+' : '') + pct(cats[i].aceleracao_media, 0)}</b>`; });
    } else if (tab === 'global') {
      tb.innerHTML = `<div class="grid g2"><div class="panel"><h2>Tendências emergentes e aceleradas</h2>${rankTable((rk.emergentes || []).slice(0, 10), { compact: true, empty: 'Nenhum produto com crescimento acelerado ou emergente nesta análise.' })}</div>
        <div class="panel"><h2>Categorias com maior aceleração</h2><div id="catacc"></div><p class="muted small">Mediana da aceleração (crescimento dos últimos 6 meses menos o dos últimos 12) dos produtos da categoria.</p></div></div>
        <div class="grid g2"><div class="panel"><h2>Crescimento consistente</h2>${rankTable((rk.crescimento_consistente || []).slice(0, 10), { compact: true })}</div>
        <div class="panel"><h2>Comparação entre países <span class="muted small">(importações vindas da China, 12 meses)</span></h2>${countriesTable(d.paises)}</div></div>
        <div class="panel"><h2>Possível declínio</h2>${rankTable((rk.possivel_declinio || []).slice(0, 10), { empty: 'Nenhum produto com queda significativa.' })}</div>`;
      const cats = d.categorias_aceleracao || [];
      if (cats.length) barChart($('#catacc'), cats.map((c) => ({ label: c.categoria, value: Math.max(c.aceleracao_media, 0) + 1e-9, note: `cresc. ${pct(c.crescimento_medio, 0)} · ${c.produtos} produtos`, color: c.aceleracao_media >= 0 ? 'var(--c3)' : 'var(--c5)' })), { format: () => '' });
      else $('#catacc').innerHTML = '<p class="muted small">Dados insuficientes.</p>';
      main.querySelectorAll('#catacc .bar-val').forEach((el, i) => { el.innerHTML = `<b>${(cats[i].aceleracao_media > 0 ? '+' : '') + pct(cats[i].aceleracao_media, 0)}</b> <small>${escH(cats[i].produtos + ' prod.')}</small>`; });
    } else if (tab === 'brasil') {
      const cam = d.cambio || {};
      tb.innerHTML = `<div class="kpis">${['USD', 'CNY', 'EUR'].filter((c) => cam[c]).map((c) => `<div class="kpi"><span>PTAX ${c}/BRL · ${cam[c].data}</span><b>R$ ${fmt(cam[c].valor, 4)}</b><span>${growth(cam[c].var_12m)} em ~12 meses · <a href="#" data-series="${cam[c].id}">origem</a></span></div>`).join('') || '<p class="muted">Câmbio indisponível.</p>'}</div>
        <div class="panel"><h2>Sinais de demanda no Brasil</h2><p class="muted small">Interesse crescente na Wikipédia em português e/ou importações brasileiras em alta.</p>${rankTable((rk.sinais_brasil || []).slice(0, 20))}</div>
        <div class="grid g2"><div class="panel"><h2>Indicadores de importação — categorias prioritárias</h2>${importTable(d.descoberta.prioritarias)}</div>
        <div class="panel"><h2>Varejo brasileiro (IBGE)</h2>${(d.brasil_ibge || []).length ? `<table><tr><th>Atividade</th><th class="num">Volume 12m vs ano anterior</th><th>Até</th><th></th></tr>${d.brasil_ibge.map((r) => `<tr><td>${escH(r.nome)}</td><td class="num">${growth(r.crescimento_12m)}</td><td>${(r.fim || '').slice(0, 7)}</td><td><a href="#" data-series="${r.id}" class="small">série</a></td></tr>`).join('')}</table>` : '<p class="muted small">IBGE ainda sem dados coletados.</p>'}
        <p class="muted small">Comparações regionais (por UF) ainda não coletadas.</p></div></div>`;
    } else if (tab === 'china') {
      tb.innerHTML = `<div class="banner small">Fornecedores chineses: cadastre e analise os fabricantes informados por você (Conformidade de Importação → Fornecedores); AliExpress e Taobao exigem app key aprovada. Os preços abaixo são <b>preços médios indicativos de importação</b> (valor FOB ÷ peso) do Comex Stat, não cotações de fornecedores.</div>
        <div class="grid g2"><div class="panel"><h2>Preços indicativos de importação da China</h2>${chinaTable(d.china_precos)}</div>
        <div class="panel"><h2>Novas categorias descobertas automaticamente</h2><p class="muted small">Posições fora das categorias prioritárias com importações da China crescendo mais de 30% em 12 meses.</p>${importTable(d.descoberta.novas_categorias)}</div></div>
        <div class="panel"><h2>Produtos e categorias identificados (China → Brasil)</h2><p class="muted small">${d.descoberta.total || 0} posições SH4 com ${escH(d.descoberta.criterio || '')}.</p>${importTable(d.descoberta.prioritarias, true)}</div>`;
    } else if (tab === 'ml') {
      const m = d.ml;
      tb.innerHTML = `<div class="kpis"><div class="kpi"><span>Séries com previsão automática</span><b>${m.total - m.exploratorias}</b></div><div class="kpi"><span>Somente exploratórias (histórico curto)</span><b>${m.exploratorias}</b></div>
        ${Object.entries(m.por_qualidade).map(([k, v]) => `<div class="kpi"><span>Qualidade ${k}</span><b>${v}</b></div>`).join('')}</div>
        <div class="grid g2"><div class="panel"><h2>Modelos escolhidos pelo AutoML</h2><div id="mlmod"></div><p class="muted small">Cada série é avaliada por backtesting; o modelo com menor erro fora da amostra é escolhido, e o Naive vence se nenhum outro o superar.</p></div>
        <div class="panel"><h2>Projeções de importação (próximos 12 meses vs. últimos 12)</h2><div class="scroll">${(m.destaques || []).length ? `<table><tr><th>Posição</th><th class="num">Variação projetada</th><th>Modelo</th><th>Qualidade</th><th></th></tr>${m.destaques.slice(0, 25).map((r) => `<tr><td>${escH(r.nome)}</td><td class="num">${growth(r.variacao_prevista)}</td><td class="small">${escH(r.modelo)}</td><td>${escH(r.qualidade)}</td><td><a href="#" data-series="${r.id}" class="small">ver</a></td></tr>`).join('')}</table>` : '<p class="muted">Sem projeções ainda.</p>'}</div>
        <p class="muted small">São projeções de indicadores de mercado (valor importado), não previsões de vendas da empresa.</p></div></div>
        <p><a href="#previsoes">Ver todas as previsões automáticas →</a></p>`;
      barChart($('#mlmod'), Object.entries(m.por_modelo).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v })), { format: (v) => fmt(v, 0) });
    } else if (tab === 'oport') {
      tb.innerHTML = `<div class="panel"><h2>Top 20 — oportunidades para investigação de importação</h2>${DISCLAIMER}${rankTable(rk.investigacao_importacao)}<p><a href="#oportunidades">Ranking completo, pesos e evidências →</a></p></div>`;
    } else if (tab === 'fontes') {
      tb.innerHTML = `<div class="panel">${sourcesTable(src)}</div>`;
    }
  }

  function countriesTable(rows) {
    if (!rows || !rows.length) return '<p class="muted small">UN Comtrade ainda sem dados (coletado após a descoberta das posições prioritárias).</p>';
    const cs = [...new Set(rows.flatMap((r) => Object.keys(r.crescimento)))];
    return `<div class="scroll"><table><tr><th>Produto</th><th class="num">Brasil</th>${cs.map((c) => `<th class="num">${escH(c.replace('China → ', '').replace('Estados Unidos', 'EUA'))}</th>`).join('')}</tr>
      ${rows.map((r) => `<tr><td class="trunc" title="${escH(r.nome)}">${escH(r.nome)}</td><td class="num">${growth(r.brasil)}</td>${cs.map((c) => `<td class="num">${growth(r.crescimento[c])}</td>`).join('')}</tr>`).join('')}</table></div>`;
  }
  function importTable(rows, full) {
    if (!rows || !rows.length) return '<p class="muted small">Sem dados do Comex Stat ainda.</p>';
    return `<div class="scroll"><table><tr><th>SH4</th><th>Descrição</th>${full ? '<th>Categoria</th>' : ''}<th class="num">Importado da China (12m)</th><th class="num">Cresc. 12m</th><th class="num">Participação China</th></tr>
      ${rows.map((r) => `<tr><td><a href="#produto/${encodeURIComponent(r.product_key)}">${r.codigo}</a></td><td class="trunc" title="${escH(r.nome)}">${escH(r.nome)}</td>${full ? `<td>${escH(r.categoria)}</td>` : ''}<td class="num">${usd(r.importado_12m_usd)}</td><td class="num">${growth(r.crescimento_12m)}</td><td class="num">${pct(r.participacao_china, 0)}</td></tr>`).join('')}</table></div>`;
  }
  function chinaTable(rows) {
    if (!rows || !rows.length) return '<p class="muted small">Sem dados.</p>';
    return `<div class="scroll"><table><tr><th>SH4</th><th>Descrição</th><th class="num">US$/kg (média 3m)</th><th class="num">Var. 12m</th><th></th></tr>
      ${rows.map((r) => `<tr><td>${r.codigo}</td><td class="trunc" title="${escH(r.nome)}">${escH(r.nome)}</td><td class="num">${fmt(r.preco_kg, 2)}</td><td class="num">${growth(r.var_preco_12m)}</td><td><a href="#" data-series="${r.id}" class="small">série</a></td></tr>`).join('')}</table></div>`;
  }
  function sourcesTable(src, compact) {
    return `<div><table class="rich"><tr><th>Fonte</th><th>Estado</th><th>Última coleta</th><th class="num">Registros</th><th>Cobertura</th><th>Situação</th>${compact ? '' : '<th>Documentação</th>'}</tr>
      ${src.map((s) => `<tr><td><b>${escH(s.nome)}</b>${compact ? '' : `<br><span class="muted small">${escH(s.descricao || '')}</span>`}</td><td>${badgeState(s.estado, s.validada)}</td>
        <td class="small">${s.ultima_coleta ? s.ultima_coleta.replace('T', ' ').slice(0, 16) : '—'}</td><td class="num">${fmt(s.registros, 0)}</td>
        <td class="small">${s.cobertura && s.cobertura[0] ? s.cobertura[0].slice(0, 7) + ' a ' + s.cobertura[1].slice(0, 7) : '—'}</td>
        <td class="small wrap">${escH(s.estado === 'restrita' ? s.restricao : (s.mensagem || ''))}${!compact && s.limitacoes ? `<br><span class="muted">Limitações: ${escH(s.limitacoes)}</span>` : ''}</td>
        ${compact ? '' : `<td class="small">${s.documentacao ? `<a href="${escH(s.documentacao)}" target="_blank" rel="noopener">docs</a>` : ''}</td>`}</tr>`).join('')}</table></div>
      <p class="muted small">Uma fonte só aparece como <b>funcional</b> depois de uma coleta real validada nesta instalação. Fontes restritas exigem credenciais ou aprovação e não são acessadas por outros meios.</p>`;
  }

  /* ------------------------------------------------------------ OPORTUNIDADES */
  async function pageOpp() {
    main.innerHTML = `<h1>Ranking de Oportunidades</h1><p class="sub">Score heurístico 0–100 calculado automaticamente a partir de todas as fontes disponíveis.</p>${DISCLAIMER}<div id="ob">${loading()}</div>`;
    const d = await api('/api/market/opportunities');
    if (!d.itens || !d.itens.length) { $('#ob').innerHTML = '<div class="panel"><p>Ainda não há produtos analisados. Aguarde a sincronização.</p></div>'; return; }
    const RK = { produtos_emergentes: 'Produtos emergentes', mais_pesquisados: 'Mais pesquisados', em_crescimento: 'Em crescimento',
      avaliacoes_favoraveis: 'Avaliações favoráveis', problemas_recorrentes: 'Problemas recorrentes', promissores_importacao: 'Promissores para importação',
      alto_risco: 'Alto risco comercial', possivel_declinio: 'Possível declínio' };
    const NAMES = { mencoes: 'Menções em notícias/discussões', sentimento: 'Sentimento das opiniões', problemas_recorrentes: 'Problemas recorrentes (inverso)', crescimento_interesse: 'Crescimento de interesse', persistencia: 'Persistência da tendência', evidencia_demanda: 'Evidência de demanda (importações)', diversidade_fontes: 'Diversidade de fontes', concorrencia: 'Concorrência observável (inverso)', sazonalidade: 'Sazonalidade (inverso)', volatilidade: 'Volatilidade (inverso)', risco_comercial: 'Risco comercial (inverso)', qualidade_dados: 'Qualidade dos dados' };
    const cats = [...new Set(d.itens.map((i) => i.categoria))].sort();
    $('#ob').innerHTML = `<div class="grid g2"><div class="panel"><h2>Pesos</h2><table><tr><th>Componente</th><th class="num">Peso</th></tr>${Object.entries(d.pesos).map(([k, v]) => `<tr><td>${NAMES[k]}</td><td class="num">${pct(v, 0)}</td></tr>`).join('')}</table>
      <p class="muted small">Componentes sem dados são excluídos e os pesos restantes renormalizados — a falta de uma fonte não reduz o score. <b>Cobertura</b> = peso dos componentes com dados; <b>confiança</b> = confiabilidade das fontes × corroboração × histórico. Dados do YouTube não entram no score (políticas do YouTube). Fórmulas na <a href="#metodologia">Metodologia</a>, seções 17 e 19.</p></div>
      <div class="panel"><h2>Filtros</h2><div class="form"><label class="f">Ranking<select id="or"><option value="">Todos os produtos</option>${Object.entries(RK).filter(([k]) => (d.rankings || {})[k]).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label><label class="f">Buscar<input id="oq" placeholder="nome, SH4, inglês…"></label><label class="f">Categoria<select id="oc"><option value="">Todas</option>${cats.map((c) => `<option>${escH(c)}</option>`).join('')}</select></label>
      <a class="btn" href="/api/market/export/oportunidades.xlsx">Exportar XLSX</a></div><p class="muted small" style="margin-top:12px">${d.itens.length} produtos analisados · gerado em ${(d._gerado_em || '').replace('T', ' ').slice(0, 16)}</p></div></div>
      <div class="panel" id="otable"></div>`;
    const draw = () => {
      const q = $('#oq').value.toLowerCase(), c = $('#oc').value, rkk = $('#or').value;
      const byk = Object.fromEntries(d.itens.map((i) => [i.product_key, i]));
      const base = rkk ? (d.rankings[rkk] || []).map((k) => byk[k]).filter(Boolean) : d.itens;
      const rows = base.filter((i) => (!c || i.categoria === c) && (!q || [i.nome, i.nome_en, i.nome_zh, i.product_key].join(' ').toLowerCase().includes(q)));
      $('#otable').innerHTML = `<div class="scroll" style="max-height:720px"><table class="rich"><tr><th>#</th><th>Produto</th><th>Categoria</th><th>Score</th><th class="num">Cobertura</th><th>Confiança</th><th>Classificação</th><th class="num">12m</th><th>Fontes</th><th>Evidências e riscos</th></tr>
        ${rows.map((r, i) => `<tr><td>${i + 1}</td><td>${prodLink(r)}${r.nome_en && r.nome_en !== r.nome ? `<br><span class="muted small">${escH(r.nome_en)}${r.nome_zh ? ' · ' + escH(r.nome_zh) : ''}</span>` : ''}</td><td>${escH(r.categoria)}</td><td>${scoreBar(r.score)}</td><td class="num">${pct(r.cobertura, 0)}</td><td><span class="badge ${r.confianca_rotulo === 'alta' ? 'ok' : r.confianca_rotulo === 'baixa' ? 'bad' : ''}">${escH(r.confianca_rotulo || '—')}</span></td><td>${label(r.rotulo)}</td><td class="num">${growth(r.crescimento_12m)}</td>
        <td class="small">${r.fontes.map(escH).join(', ')}</td><td class="small wrap">${r.evidencias.slice(0, 2).map((e) => '✓ ' + escH(e)).join('<br>')}${r.riscos.length ? '<br><span class="neg">⚠ ' + r.riscos.slice(0, 2).map(escH).join('; ') + '</span>' : ''}</td></tr>`).join('')}</table></div>`;
    };
    $('#oq').oninput = draw; $('#oc').onchange = draw; $('#or').onchange = draw; draw();
  }

  /* ------------------------------------------------------------ PRODUTO */
  async function pageProduct(key) {
    main.innerHTML = loading();
    let d; try { d = await api('/api/market/product/' + encodeURIComponent(key)); } catch (e) { main.innerHTML = errBox(e); return; }
    const o = d.oportunidade || {}, p = d.perfil || {};
    const names = [o.nome || p.nome, p.nome_en, p.nome_zh].filter(Boolean);
    main.innerHTML = `<p><a href="#oportunidades">← Oportunidades</a></p><h1>${escH(names[0] || key)}</h1>
      <p class="sub">${names.slice(1).map(escH).join(' · ')} ${names.length > 1 ? '·' : ''} ${escH(o.categoria || p.categoria || '')} · <code>${escH(key)}</code></p>
      <div class="grid g2"><div class="panel"><h2>Score de oportunidade: ${o.score == null ? '—' : fmt(o.score, 0)} ${label(o.rotulo)}</h2>
        <p class="small">${escH(o.justificativa_rotulo || '')}</p>
        <table><tr><th>Componente</th><th class="num">Valor (0–1)</th><th class="num">Peso</th><th></th></tr>${Object.entries(o.componentes || {}).map(([k, v]) => `<tr><td>${k.replace(/_/g, ' ')}</td><td class="num">${v == null ? '<span class="muted">sem dados</span>' : fmt(v, 2)}</td><td class="num">${pct(d.pesos[k], 0)}</td><td>${v == null ? '' : `<span class="score sm"><i style="width:${100 * v}%"></i></span>`}</td></tr>`).join('')}</table>
        ${DISCLAIMER}</div>
        <div class="panel"><h2>Evidências</h2><ul class="small">${(o.evidencias || []).map((e) => `<li>${escH(e)}</li>`).join('') || '<li class="muted">—</li>'}</ul>
        <h2>Riscos</h2><ul class="small">${(o.riscos || []).map((e) => `<li>${escH(e)}</li>`).join('') || '<li class="muted">—</li>'}</ul>
        ${(o.importacao_relacionada || []).length ? `<h3>Posições SH4 relacionadas</h3><ul class="small">${o.importacao_relacionada.map((r) => `<li><a href="#produto/sh4:${r.codigo}">${r.codigo}</a> ${escH(r.nome)} — ${usd(r.nivel_12m)}, ${growth(r.crescimento_12m)}</li>`).join('')}</ul>` : ''}</div></div>
      <div class="panel"><h2>Séries de dados (clique para ver gráfico, previsão e origem)</h2><table><tr><th>Indicador</th><th>País / fluxo</th><th>Fonte</th><th>Tipo</th><th>Unidade</th><th class="num">Obs.</th><th>Período</th></tr>
        ${d.series.map((s) => `<tr class="click" data-series="${s.id}"><td>${escH(s.indicator)}</td><td>${escH(s.country || '')}</td><td>${escH(s.source)}</td><td>${escH(s.kind)}</td><td>${escH(s.unit || '')}</td><td class="num">${s.n_obs}</td><td class="small">${(s.inicio || '').slice(0, 7)} a ${(s.fim || '').slice(0, 7)}</td></tr>`).join('')}</table></div>`;
  }

  /* ------------------------------------------------------------ DESCOBERTOS (busca) */
  async function pageFound() {
    main.innerHTML = `<h1>Produtos descobertos</h1><p class="sub">Busca em português, inglês ou chinês (com tolerância a variações de escrita) em todos os produtos identificados automaticamente.</p>
      <div class="panel"><div class="form"><label class="f">Buscar<input id="fq" placeholder="ex.: fritadeira, LED, 8539, power bank" style="width:320px"></label></div><div id="fr" style="margin-top:10px"></div></div>`;
    const go = async () => { const r = await api('/api/market/search?q=' + encodeURIComponent($('#fq').value)); $('#fr').innerHTML = rankTable(r, { empty: 'Nenhum produto encontrado.' }); };
    let t; $('#fq').oninput = () => { clearTimeout(t); t = setTimeout(go, 250); }; go();
  }

  /* ------------------------------------------------------------ PREVISÕES */
  async function pageForecasts() {
    main.innerHTML = `<h1>Previsões automáticas</h1><p class="sub">Geradas pelo AutoML sem intervenção. Interesse de pesquisa, indicadores de mercado e vendas são tipos diferentes e nunca são convertidos entre si.</p><div id="pf">${loading()}</div>`;
    const rows = await api('/api/market/forecasts');
    const T = { interesse: 'Interesse (Wikipédia)', indicador: 'Indicador de mercado', vendas: 'Vendas' };
    $('#pf').innerHTML = !rows.length ? '<div class="panel"><p>Nenhuma previsão gerada ainda.</p></div>' : `<div class="panel"><div class="form"><label class="f">Tipo<select id="pt"><option value="">Todos</option>${Object.entries(T).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label></div>
      <div class="scroll" style="max-height:640px" id="ptab"></div></div>`;
    const draw = () => { const t = $('#pt').value; $('#ptab').innerHTML = `<table><tr><th>Série</th><th>Indicador</th><th>País / fluxo</th><th>Tipo</th><th>Modelo</th><th>Qualidade</th><th class="num">WAPE</th><th class="num">Próx. 12m vs últ. 12m</th><th class="num">Meses</th></tr>
      ${rows.filter((r) => !t || r.tipo === t).map((r) => `<tr class="click" data-series="${r.id}"><td>${escH(r.nome)}</td><td class="small">${escH(r.indicador)}</td><td class="small">${escH(r.pais || '')}</td><td class="small">${T[r.tipo]}</td><td class="small">${r.status === 'prevista' ? escH(r.modelo) : '<span class="muted">exploratória</span>'}</td><td>${escH(r.qualidade || '—')}</td><td class="num">${pct(r.wape)}</td><td class="num">${growth(r.variacao_prevista)}</td><td class="num">${r.meses}</td></tr>`).join('')}</table>`; };
    if (rows.length) { $('#pt').onchange = draw; draw(); }
  }

  /* ------------------------------------------------------------ CLUSTERS */
  async function pageClusters() {
    main.innerHTML = `<h1>Clusterização automática</h1><p class="sub">Agrupamento dos produtos pelo comportamento das séries (não pelo nome). Sem configuração manual.</p><div id="cb">${loading()}</div>`;
    const d = await api('/api/market/clusters');
    if (!d.itens || !d.itens.length) { $('#cb').innerHTML = `<div class="panel"><p>${escH(d.aviso || 'Ainda sem dados suficientes.')}</p></div>`; return; }
    const pal = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)', '#0891b2', '#65a30d'];
    $('#cb').innerHTML = `<div class="kpis"><div class="kpi"><span>Grupos (K-Means, k por silhueta)</span><b>${d.k}</b></div><div class="kpi"><span>Silhueta</span><b>${fmt(d.silhueta, 3)}</b></div>
      <div class="kpi"><span>Concordância Aglomerativo × K-Means (ARI)</span><b>${fmt(d.ari_aglomerativo_vs_kmeans, 2)}</b></div><div class="kpi"><span>HDBSCAN</span><b>${d.hdbscan_grupos} grupos · ${d.hdbscan_ruido} ruído</b></div><div class="kpi"><span>Anomalias (Isolation Forest)</span><b>${d.anomalias}</b></div></div>
      <div class="panel"><h2>Mapa PCA (${pct(d.pca_variancia_explicada[0], 0)} + ${pct(d.pca_variancia_explicada[1], 0)} da variância)</h2><div class="chartbox" id="sc"></div></div>
      <div class="grid g2">${d.clusters.map((c) => `<div class="panel"><h2><i class="dot" style="background:${pal[c.id % 8]}"></i> ${escH(c.nome)} <span class="muted small">(${c.n})</span></h2>
        <p class="small">Rótulos dos membros: ${Object.entries(c.composicao_rotulos).map(([k, v]) => `${escH(k)} (${v})`).join(', ')}</p>
        <div class="kv small">${Object.entries(c.centroide_mediano).map(([k, v]) => `<span>${k.replace(/_/g, ' ')}</span><b>${k === 'nivel_pct' || k === 'persistencia' || k === 'sazonalidade' ? fmt(v, 2) : pct(v, 0)}</b>`).join('')}</div>
        <p class="small">${d.itens.filter((i) => i.cluster === c.id).slice(0, 12).map((i) => prodLink(i) + (i.anomalia ? ' <span class="badge bad">anômalo</span>' : '')).join(', ')}</p></div>`).join('')}</div>`;
    scatterChart($('#sc'), d.itens.map((i) => ({ x: i.x, y: i.y, color: pal[i.cluster % 8], label: `${i.nome} — ${i.rotulo || ''}`, ring: i.anomalia, href: '#produto/' + encodeURIComponent(i.product_key) })));
  }

  /* ------------------------------------------------------------ FONTES */
  async function pageSources() {
    main.innerHTML = `<h1>Saúde das fontes</h1><p class="sub">Estado real de cada conector nesta instalação.</p><div id="sb">${loading()}</div>`;
    const [src, st] = await Promise.all([api('/api/market/sources'), api('/api/sync/status')]);
    $('#sb').innerHTML = `<div class="panel"><div class="form" style="justify-content:space-between"><span>Sincronização automática: ${st.auto_sync ? 'ativada (na abertura e semanalmente)' : 'desativada'} · ${st.devida ? 'atualização pendente' : 'em dia nesta semana'}</span><button id="ss" class="primary">Sincronizar agora</button></div></div>
      <div class="panel">${sourcesTable(src)}</div>
      <div class="panel"><h2>Últimas sincronizações</h2><table><tr><th>#</th><th>Início</th><th>Fim</th><th>Origem</th><th>Resultado</th></tr>${st.ultimas.map((r) => `<tr><td>${r.id}</td><td>${(r.started_at || '').replace('T', ' ').slice(0, 19)}</td><td>${(r.finished_at || '').replace('T', ' ').slice(0, 19)}</td><td>${escH(r.trigger)}</td><td>${escH(r.state)}</td></tr>`).join('')}</table></div>`;
    $('#ss').onclick = async () => { await post('/api/sync/run', {}); pollSync(); };
  }

  return { painel: () => pagePainel('resumo'), radar: () => pagePainel('global'), brasil: () => pagePainel('brasil'),
           china: () => pagePainel('china'), ml: () => pagePainel('ml'), oportunidades: pageOpp, produto: pageProduct, descobertos: pageFound,
           previsoes: pageForecasts, clusters: pageClusters, fontes: pageSources };
};
