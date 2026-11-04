/* GPI Fase 4 — Inteligência de consumo: dashboard de produtos, países, rankings, comparação
   internacional, produto, oportunidades, alertas, tendências, anomalias, catálogo e desempenho. */
window.GPI_CONSUMER = function (H) {
  const { api, fmt, pct, escH, loading, errBox, main, $ } = H;
  const COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)'];
  const CC = { BR: 'Brasil', US: 'Estados Unidos', CN: 'China' };
  const CLS = { emergente: 'ok', 'crescimento consistente': 'ok', crescimento: 'ok', 'declínio': 'bad', sazonal: 'lbl', 'estável': '', 'sem dados': '' };
  const cls = (c) => c ? `<span class="badge ${CLS[c] ?? ''}">${escH(c)}</span>` : '—';
  const g = (v) => v == null ? '—' : `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${v > 0 ? '+' : ''}${pct(v)}</span>`;
  const score = (v) => v == null ? '<span class="muted">—</span>' : `<span class="score sm"><i style="width:${Math.max(4, v)}%"></i></span> <b>${fmt(v, 0)}</b>`;
  const plink = (pid, name) => `<a href="#produto-consumo/${encodeURIComponent(pid)}">${escH(name || pid)}</a>`;
  const val = (v, unit) => v == null ? '—' : (typeof v === 'number' ? fmt(v, v < 10 && v % 1 ? 2 : 0) : escH(v)) + (unit ? ` <span class="muted small">${escH(unit)}</span>` : '');
  const metricNote = (M) => `<details class="small"><summary>O que cada indicador mede</summary><ul>${Object.values(M).map((m) =>
    `<li><b>${escH(m.rotulo)}</b> (${escH(m.unidade)}): ${escH(m.mede)}</li>`).join('')}</ul></details>`;

  function lineFromSeries(box, list, opts = {}) {
    // séries mensais: rótulos YYYY-MM; normaliza pela média quando métricas diferem ou quando pedido
    const labels = [...new Set(list.flatMap((s) => s.ind.labels || Object.keys(s.ind.valores_semanais || {})))].sort();
    const multi = new Set(list.map((s) => s.product_id)).size > 1;
    const series = list.map((s, i) => {
      const lab = s.ind.labels || Object.keys(s.ind.valores_semanais || {});
      const vals = s.ind.valores || Object.values(s.ind.valores_semanais || {});
      const map = Object.fromEntries(lab.map((l, k) => [l, vals[k]]));
      const mean = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 1;
      return { name: `${multi ? s.nome + ' — ' : ''}${s.pais_nome} · ${s.metrica.rotulo}`, color: COLORS[i % COLORS.length],
               values: labels.map((l) => map[l] == null ? null : (opts.norm ? (mean ? 100 * map[l] / mean : null) : map[l])) };
    });
    if (!labels.length) { box.innerHTML = '<p class="muted small">Sem pontos suficientes para o gráfico.</p>'; return; }
    window.lineChart(box, { labels, series, height: opts.height || 280 });   // a legenda é desenhada pelo próprio gráfico
  }

  /* ----------------------------------------------------------------- DASHBOARD */
  async function pageDashboard() {
    main.innerHTML = `<h1>Dashboard de consumo</h1><p class="sub">Produtos específicos com interesse crescente no Brasil, nos EUA e na China — cada indicador com fonte, unidade e período.</p><div id="db">${loading()}</div>`;
    const d = await api('/api/consumer/dashboard');
    const k = d.kpis;
    const noSearch = !k.paises_com_buscas.length;
    $('#db').innerHTML = `
      ${noSearch ? `<div class="banner">Ainda não há dados de <b>busca</b> coletados. A primeira sincronização consulta o Google Trends (buscas em alta); para volumes mensais por produto, conecte o <a href="#integracoes">Planejador do Google Ads</a>. Enquanto isso, o painel mostra sinais auxiliares (Wikipédia, menções) com o rótulo correto.</div>` : ''}
      <div class="kpis">
        <div class="kpi"><span>Produtos monitorados</span><b>${fmt(k.produtos_monitorados, 0)}</b><small class="muted">${fmt(k.variantes, 0)} variantes · ${fmt(k.descobertos, 0)} descobertos</small></div>
        <div class="kpi"><span>Produtos emergentes</span><b>${fmt(k.emergentes, 0)}</b></div>
        <div class="kpi"><span>Tendências identificadas</span><b>${fmt(k.tendencias, 0)}</b></div>
        <div class="kpi"><span>Países com dados de busca</span><b>${k.paises_analisados.length ? escH(k.paises_analisados.join(', ')) : '—'}</b></div>
        <div class="kpi"><span>Fontes com dados</span><b>${fmt(k.fontes_disponiveis, 0)}</b><small class="muted">${escH(k.fontes_com_dados.join(', '))}</small></div>
        <div class="kpi"><span>Última atualização</span><b style="font-size:15px">${k.ultima_atualizacao ? escH(k.ultima_atualizacao.replace('T', ' ').slice(0, 16)) : 'aguardando 1ª coleta'}</b></div>
      </div>
      <div class="grid g2">
        <div class="panel"><h2>Evolução do interesse — produtos de maior score</h2><div id="evo"></div><p class="small muted">Índice 100 = média de cada série (compara formas, não níveis).</p></div>
        <div class="panel"><h2>Crescimento por país (mediana das séries)</h2><div id="gpais"></div>
          <h2 style="margin-top:16px">Emergentes</h2>${d.emergentes.length ? `<ul class="small">${d.emergentes.map((s) => `<li>${plink(s.product_id, s.nome)} — ${escH(s.pais_nome)} · ${escH(s.metrica.rotulo)} · desde ${escH(s.ind.primeiro || '')}</li>`).join('')}</ul>` : '<p class="muted small">Nenhum produto emergente no momento.</p>'}</div>
      </div>
      <div class="panel"><h2>Produtos</h2><p class="small muted">Para cada produto, o sinal mais forte disponível (busca &gt; leitura de artigos &gt; menções). ${metricNote(d.metricas)}</p>
        <div class="scroll" style="max-height:560px"><table><thead><tr><th>Produto</th><th>Categoria</th><th>País</th><th>Indicador de interesse</th><th class="num">Valor</th><th class="num">Crescimento</th><th>Tendência</th><th>Confiança</th><th>Score</th><th>Fonte</th></tr></thead><tbody>
        ${d.tabela.map((r) => `<tr><td>${plink(r.product_id, r.nome)}</td><td class="small">${escH(r.categoria || '')}</td><td class="small">${escH(r.pais)}</td><td class="small">${escH(r.indicador)}</td>
          <td class="num">${val(r.valor)}</td><td class="num">${g(r.crescimento)}</td><td>${cls(r.tendencia)}</td><td class="num small">${r.confianca == null ? '—' : fmt(r.confianca, 0)}</td><td>${score(r.score)}</td><td class="small">${escH(r.fonte)}</td></tr>`).join('') || '<tr><td colspan="10" class="muted">Sem séries ainda.</td></tr>'}
        </tbody></table></div></div>
      <div class="panel"><h2>Alertas recentes</h2>${alertsTable(d.alertas)}<p><a href="#alertas">ver todos</a></p></div>`;
    lineFromSeries($('#evo'), d.evolucao, { norm: true });
    const gp = Object.entries(d.crescimento_por_pais);
    if (gp.length) window.barChart($('#gpais'), gp.map(([k2, v]) => ({ label: k2, value: Math.max(0, v), note: pct(v) })), {});
    else $('#gpais').innerHTML = '<p class="muted small">Sem séries com crescimento calculável.</p>';
  }

  function alertsTable(list) {
    return list.length ? `<table><thead><tr><th>Tipo</th><th>Produto</th><th>País</th><th>Indicador</th><th>Detalhe</th></tr></thead><tbody>${list.map((a) =>
      `<tr><td><span class="badge lbl">${escH(a.tipo)}</span></td><td>${plink(a.product_id, a.produto)}</td><td class="small">${escH(a.pais)}</td><td class="small">${escH(a.metrica)} · ${escH(a.fonte)}</td><td class="small">${escH(a.detalhe)}</td></tr>`).join('')}</tbody></table>`
      : '<p class="muted small">Nenhum alerta.</p>';
  }

  async function pageAlerts() {
    main.innerHTML = `<h1>Alertas de tendências</h1><p class="sub">Produtos que entraram nas buscas em alta, mudaram de patamar, tiveram anomalia no último período ou alta forte.</p><div id="al">${loading()}</div>`;
    const d = await api('/api/consumer/alerts');
    $('#al').innerHTML = `<div class="panel">${alertsTable(d.itens)}</div>`;
  }

  /* ----------------------------------------------------------------- RANKINGS / PAÍSES */
  const RK = [['mais_pesquisados', 'Mais pesquisados (volume)'], ['listas_de_busca', 'Listas de mais buscados'], ['em_alta', 'Em alta no Google'],
    ['maior_crescimento', 'Maior crescimento'], ['emergentes', 'Emergentes'], ['crescimento_acelerado', 'Crescimento acelerado'],
    ['crescimento_consistente', 'Crescimento consistente'], ['estaveis', 'Tendências estáveis'], ['saturacao', 'Possível saturação'],
    ['maior_aceleracao', 'Maior aceleração'], ['sazonais', 'Interesse sazonal'], ['declinio', 'Em declínio'], ['sinal_internacional', 'Sinal internacional'],
    ['categorias', 'Categorias']];

  async function pageRankings(arg) {
    const [cc0, rk0] = (arg || 'BR/mais_pesquisados').split('/');
    const cc = (cc0 || 'BR').toUpperCase(), rk = rk0 || 'mais_pesquisados';
    main.innerHTML = `<h1>Produtos mais pesquisados</h1><p class="sub">Rankings separados por tipo de indicador. Cada ranking declara o que mede — volume de buscas, buscas em alta, leitura de artigos e menções nunca são misturados.</p>
      <div class="tabs">${Object.entries(CC).map(([c, n]) => `<button class="${c === cc ? 'on' : ''}" data-cc="${c}">${n}</button>`).join('')}</div><div id="rkb">${loading()}</div>`;
    main.querySelectorAll('[data-cc]').forEach((b) => b.onclick = () => { location.hash = `mais-pesquisados/${b.dataset.cc}/${rk}`; });
    const d = await api('/api/consumer/country/' + cc);
    $('#rkb').innerHTML = `${d.limitacoes.map((l) => `<div class="banner">${escH(l)}</div>`).join('')}
      <div class="tabs">${RK.map(([k, n]) => `<button class="${k === rk ? 'on' : ''}" data-rk="${k}">${n}</button>`).join('')}</div>
      <div class="form" style="margin-bottom:10px"><label class="f">Categoria<select id="fcat"><option value="">todas</option></select></label>
        <label class="f">Indicador<select id="fmet"><option value="">todos</option>${Object.entries(d.metricas).map(([k, m]) => `<option value="${k}">${escH(m.rotulo)}</option>`).join('')}</select></label>
        <label class="f">Classe de tendência<select id="fcls"><option value="">todas</option>${Object.keys(CLS).map((c) => `<option>${c}</option>`).join('')}</select></label></div>
      <div id="rkt"></div>`;
    main.querySelectorAll('[data-rk]').forEach((b) => b.onclick = () => { location.hash = `mais-pesquisados/${cc}/${b.dataset.rk}`; });
    const R = d.rankings[rk] || { mede: 'Ranking disponível apenas para o Brasil.', itens: [] };
    const cats = [...new Set((R.itens || []).map((i) => i.categoria).filter(Boolean))].sort();
    $('#fcat').insertAdjacentHTML('beforeend', cats.map((c) => `<option>${escH(c)}</option>`).join(''));
    const draw = () => {
      const fc = $('#fcat').value, fm = $('#fmet').value, fl = $('#fcls').value;
      const items = (R.itens || []).filter((i) => (!fc || i.categoria === fc) && (!fm || i.metrica === fm) && (!fl || i.classe === fl));
      const isCat = rk === 'categorias';
      $('#rkt').innerHTML = `<div class="panel"><p class="small"><b>O que este ranking mede:</b> ${escH(R.mede)}</p>
        ${R.limitacao ? `<div class="banner">${escH(R.limitacao)}</div>` : ''}
        ${isCat ? `<table><thead><tr><th>Categoria</th><th class="num">Produtos</th><th class="num">Soma do indicador de busca</th></tr></thead><tbody>${items.map((i) => `<tr><td>${escH(i.categoria)}</td><td class="num">${i.produtos}</td><td class="num">${fmt(i.valor, 0)}</td></tr>`).join('') || '<tr><td colspan="3" class="muted">Sem dados.</td></tr>'}</tbody></table>`
        : `<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Produto</th><th>Categoria</th><th>Indicador</th><th class="num">Valor</th><th>Tendência</th><th>Período</th><th>Fonte</th><th>Score</th></tr></thead><tbody>
          ${items.map((i, n) => `<tr><td>${n + 1}</td><td>${plink(i.product_id, i.nome)}</td><td class="small">${escH(i.categoria || '')}</td><td class="small">${escH(i.metrica_rotulo)}<br><span class="muted">${escH(i.unidade)}</span></td>
            <td class="num">${['maior_crescimento', 'declinio', 'maior_aceleracao', 'crescimento_consistente'].includes(rk) ? g(i.valor) : rk === 'sazonais' ? fmt(i.valor, 2) : val(i.valor)}${i.dias_em_alta ? `<br><span class="muted small">${i.dias_em_alta} dia(s) em alta</span>` : ''}</td>
            <td>${cls(i.classe)}</td><td class="small">${escH(i.periodo)}</td><td class="small">${escH(i.fonte)}</td><td>${score(i.score)}</td></tr>`).join('') || '<tr><td colspan="9" class="muted">Nenhum produto neste ranking com os filtros atuais.</td></tr>'}
          </tbody></table></div>`}</div>`;
    };
    ['#fcat', '#fmet', '#fcls'].forEach((s) => $(s).onchange = draw);
    draw();
  }

  async function pageCountry(arg) {
    const cc = (arg || 'BR').toUpperCase();
    main.innerHTML = `<h1>${escH(CC[cc] || cc)} — inteligência de consumo</h1><p class="sub">Interesse por produtos neste país: buscas (quando disponíveis) e sinais auxiliares identificados.</p><div id="cp">${loading()}</div>`;
    const d = await api('/api/consumer/country/' + cc);
    const top = (k, n = 10) => (d.rankings[k].itens || []).slice(0, n);
    const mini = (title, k, fmtv) => `<div class="panel"><h2>${title}</h2><p class="small muted">${escH(d.rankings[k].mede)}</p>
      ${d.rankings[k].limitacao ? `<p class="small muted">${escH(d.rankings[k].limitacao)}</p>` : ''}
      <table><tbody>${top(k).map((i) => `<tr><td>${plink(i.product_id, i.nome)}</td><td class="small">${escH(i.metrica_rotulo)}</td><td class="num">${fmtv(i)}</td></tr>`).join('') || '<tr><td class="muted">Sem itens.</td></tr>'}</tbody></table>
      <p class="small"><a href="#mais-pesquisados/${cc}/${k}">ranking completo</a></p></div>`;
    $('#cp').innerHTML = `${d.limitacoes.map((l) => `<div class="banner">${escH(l)}</div>`).join('')}
      <div class="kpis"><div class="kpi"><span>Séries de busca</span><b>${d.series_busca}</b></div><div class="kpi"><span>Séries auxiliares</span><b>${d.series_auxiliares}</b></div></div>
      <div class="grid g2">${mini('Maior interesse de busca (volume)', 'mais_pesquisados', (i) => val(i.valor))}
        ${mini('Em alta no Google', 'em_alta', (i) => val(i.valor))}
        ${mini('Maior crescimento', 'maior_crescimento', (i) => g(i.valor))}
        ${mini('Emergentes', 'emergentes', (i) => escH(i.valor || ''))}
        ${mini('Interesse decrescente', 'declinio', (i) => g(i.valor))}
        ${mini('Sazonais', 'sazonais', (i) => fmt(i.valor, 2))}</div>
      <div class="panel"><h2>Categorias mais pesquisadas</h2><div id="cats"></div></div>
      <div class="panel"><h2>Sinais auxiliares (não são buscas)</h2><p class="small muted">Leitura de artigos da Wikipédia no idioma e menções em notícias/discussões. Idioma não é país${cc === 'CN' ? ' — a Wikipédia em chinês NÃO representa buscas na China continental' : ''}.</p>
        <div class="scroll"><table><thead><tr><th>Produto</th><th>Indicador</th><th>Público</th><th class="num">Último valor</th><th class="num">Crescimento</th><th>Tendência</th></tr></thead><tbody>
        ${d.auxiliares.map((s) => `<tr><td>${plink(s.product_id, s.nome)}</td><td class="small">${escH(s.metrica.rotulo)}</td><td class="small">${escH(s.pais_nome)}</td><td class="num">${val(s.ind.ultimo_valor ?? s.ind.soma_30d)}</td><td class="num">${g(s.ind.crescimento)}</td><td>${cls(s.ind.classe)}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Sem sinais auxiliares.</td></tr>'}</tbody></table></div></div>`;
    const ci = d.rankings.categorias.itens || [];
    if (ci.length) window.barChart($('#cats'), ci.slice(0, 12).map((c) => ({ label: c.categoria, value: c.valor, note: `${c.produtos} produto(s)` })), {});
    else $('#cats').innerHTML = '<p class="muted small">Sem dados de busca por categoria.</p>';
  }

  /* ----------------------------------------------------------------- PRODUTO */
  async function pageProduct(pid) {
    main.innerHTML = loading();
    const d = await api('/api/consumer/product/' + encodeURIComponent(pid));
    const p = d.produto, sc = d.score || {};
    const per = [['7d', 7], ['30d', 30], ['90d', 90], ['12m', 365], ['tudo', 1e6]];
    main.innerHTML = `<p class="small"><a href="#dashboard">← Dashboard</a></p><h1>${escH(p.canonical)}</h1>
      <p class="sub">${escH(p.category)} · família <b>${escH(p.family)}</b> · ${p.level === 'variante' ? 'variante' : 'produto'} · origem: ${p.origin === 'descoberto' ? 'descoberto automaticamente' : 'catálogo de referência'}
       · EN: ${escH(p.name_en || '—')} · 中文: ${escH(p.name_zh || '—')}${p.ncm_hint ? ` · SH4 de referência: <b>${escH(p.ncm_hint)}</b>` : ''}</p>
      <div class="kpis"><div class="kpi"><span>Opportunity Score</span><b>${sc.opportunity_score == null ? '—' : fmt(sc.opportunity_score, 0)}</b></div>
        <div class="kpi"><span>Evidence Coverage</span><b>${fmt(sc.evidence_coverage, 0)}</b></div>
        <div class="kpi"><span>Forecast Confidence</span><b>${fmt(sc.forecast_confidence, 0)}</b></div>
        <div class="kpi"><span>Import Readiness</span><b>${fmt(sc.import_readiness, 0)}</b></div></div>
      <div class="panel"><div class="form" style="justify-content:space-between"><h2>Histórico de interesse</h2><div class="tabs" id="per">${per.map(([k], i) => `<button data-p="${i}" class="${k === 'tudo' ? 'on' : ''}">${k}</button>`).join('')}</div></div>
        <div id="hist"></div><p class="small muted">Cada série no seu próprio indicador; índice 100 = média da série no período exibido. Filtros só mostram períodos realmente coletados.</p></div>
      <div class="panel"><h2>Séries e tendências</h2><div class="scroll"><table><thead><tr><th>País/público</th><th>Indicador</th><th>Fonte</th><th class="num">n</th><th class="num">Crescimento</th><th>Tendência</th><th>Mudanças/anomalias</th></tr></thead><tbody>
        ${d.series.map((s) => `<tr><td class="small">${escH(s.pais_nome)}</td><td class="small">${escH(s.metrica.rotulo)}<br><span class="muted">${escH(s.metrica.unidade)}</span></td><td class="small">${escH(s.fonte_nome)}</td><td class="num">${s.ind.n}</td><td class="num">${g(s.ind.crescimento)}<br><span class="muted small">${escH(s.ind.base_crescimento || '')}</span></td><td>${cls(s.ind.classe)}</td>
          <td class="small">${(s.ind.pontos_mudanca || []).map((x) => `<span class="badge">mudança ${escH(x)}</span>`).join(' ')} ${(s.ind.anomalias || []).slice(-3).map((x) => `<span class="badge bad">anomalia ${escH(x)}</span>`).join(' ')}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">Ainda sem séries para este produto (aguardando coleta ou sem dados nas fontes conectadas).</td></tr>'}</tbody></table></div></div>
      <div class="grid g2"><div class="panel"><h2>Riscos e prontidão para importação</h2><ul class="small">${(sc.riscos || []).map((r) => `<li>${escH(r)}</li>`).join('')}</ul>
          <table class="small"><tbody>${Object.entries(sc.checklist_importacao || {}).map(([k, v]) => `<tr><td>${v ? '✅' : '⬜'}</td><td>${escH(k)}</td></tr>`).join('')}</tbody></table>
          <p class="small muted">${escH(sc.aviso || '')}</p></div>
        <div class="panel"><h2>Previsão</h2><div id="fc"></div></div></div>
      <div class="panel"><h2>Comparação entre países (exploratória)</h2>${leadTable(d.comparacoes)}</div>
      <div class="grid g2"><div class="panel"><h2>Variantes e produtos relacionados</h2>
        ${p.variantes.length ? `<p class="small"><b>Variantes:</b> ${p.variantes.map((v) => plink(v.product_id, v.canonical)).join(' · ')}</p>` : ''}
        <ul class="small">${p.relacionados.map((r) => `<li>${plink(r.product_id, r.canonical)} <span class="muted">(${escH(r.relacao)})</span></li>`).join('') || '<li class="muted">—</li>'}</ul>
        <p class="small"><b>Sinônimos observados:</b> ${p.aliases.map((a) => `${escH(a.alias)} <span class="muted">(${a.lang})</span>`).join(', ') || '—'}</p></div>
        <div class="panel"><h2>Evidências e fontes</h2><div class="scroll"><table class="small"><thead><tr><th>Data</th><th>Fonte</th><th>País</th><th>Termo</th><th>Indicador</th><th>Intenção</th></tr></thead><tbody>
        ${d.evidencias.map((o) => `<tr><td>${escH(o.ref_date)}</td><td>${escH(o.source)}</td><td>${escH(o.country)}</td><td>${o.url ? `<a href="${escH(o.url)}" target="_blank" rel="noopener">${escH(o.term)}</a>` : escH(o.term)}${o.extra && o.extra.faixa ? ` <span class="muted">(${escH(o.extra.faixa)})</span>` : ''}</td><td>${escH((d.metricas[o.metric] || {}).rotulo || o.metric)}: ${fmt(o.value, 0)}</td><td>${escH(o.intent || '')}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Sem evidências diretas ainda.</td></tr>'}</tbody></table></div>
        <p class="small muted">Dados do Google Trends: "Fonte: Google Trends".</p></div></div>`;
    const draw = (i) => {
      const days = per[i][1];
      const cut = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
      const ss = d.series.map((s) => {
        const lab = s.ind.labels || Object.keys(s.ind.valores_semanais || {});
        const vals = s.ind.valores || Object.values(s.ind.valores_semanais || {});
        const keep = lab.map((l, k) => [l, vals[k]]).filter(([l]) => (l.length === 7 ? l + '-31' : l) >= cut);
        return { ...s, ind: { ...s.ind, labels: keep.map((x) => x[0]), valores: keep.map((x) => x[1]), valores_semanais: null } };
      }).filter((s) => s.ind.labels.length);
      main.querySelectorAll('#per button').forEach((b) => b.classList.toggle('on', +b.dataset.p === i));
      if (!ss.length) { $('#hist').innerHTML = '<p class="muted small">Não há dados coletados neste período.</p>'; return; }
      lineFromSeries($('#hist'), ss, { norm: true });
    };
    main.querySelectorAll('#per button').forEach((b) => b.onclick = () => draw(+b.dataset.p));
    draw(per.length - 1);
    const fcs = Object.values(d.previsoes || {}).filter((f) => f.status === 'prevista');
    if (!fcs.length) $('#fc').innerHTML = '<p class="muted small">Sem previsão: é preciso uma série mensal elegível (volume de buscas com ≥ 24 meses, ou leitura de artigos já prevista pelo AutoML). Interesse relativo não é convertido em unidades vendidas.</p>';
    else {
      const f = fcs[0];
      $('#fc').innerHTML = `<p class="small"><b>${escH(f.tipo_descricao || '')}</b> · série: ${escH(f.serie || '')} · fonte: ${escH(f.fonte || '')} · modelo: ${escH(f.modelo_nome || f.modelo || '')} · qualidade: ${escH(f.qualidade || '')} · horizonte ${(f.previsao || []).length} meses · histórico ${f.perfil ? f.perfil.n : '?'} meses</p><div id="fcc"></div>
        ${(f.limitacoes || []).length ? `<p class="small muted">Limitações: ${f.limitacoes.map(escH).join('; ')}</p>` : ''}
        ${f.metricas ? `<p class="small muted">Backtesting: WAPE ${pct(f.metricas.wape)} · MAE ${fmt(f.metricas.mae, 0)} · RMSSE ${fmt(f.metricas.rmsse, 2)} · viés ${pct((f.metricas.bias_pct || 0) / 100)} · cobertura 80% ${pct(f.metricas.cobertura_80)}</p>` : ''}`;
      const labels = [...f.labels.slice(-24), ...f.labels_futuro];
      const hist = f.valores.slice(-24);
      window.lineChart($('#fcc'), { labels, height: 260, divider: hist.length - 0.5,
        series: [{ name: 'histórico', values: [...hist, ...f.previsao.map(() => null)], color: 'var(--c1)' },
                 { name: 'previsão', values: [...hist.map(() => null), ...f.previsao], color: 'var(--c2)', dash: true }],
        bands: [{ name: 'IC 80%', lo: [...hist.map(() => null), ...f.lo80], hi: [...hist.map(() => null), ...f.hi80], color: 'var(--c2)', opacity: .15 }] });
    }
  }

  function leadTable(list) {
    if (!list || !list.length) return '<p class="muted small">Sem pares comparáveis (mesma métrica e fonte em dois países, com ≥ 18 meses em comum).</p>';
    return `<table class="small"><thead><tr><th>Indicador</th><th>A</th><th>B</th><th class="num">Defasagem</th><th class="num">Correlação</th><th>Significativa</th><th>Estável</th><th class="num">Ganho no backtest</th><th>Leitura</th></tr></thead><tbody>
      ${list.map((c) => `<tr><td>${escH(c.metrica)} · ${escH(c.fonte)}</td><td>${escH(c.a_nome)}</td><td>${escH(c.b_nome)}</td><td class="num">${c.lag} mês(es)</td><td class="num">${fmt(c.correlacao, 2)} <span class="muted">(±${fmt(c.limite_significancia, 2)})</span></td>
        <td>${c.significativa ? '<span class="badge ok">sim</span>' : '<span class="badge">não</span>'}</td><td>${c.estavel ? '<span class="badge ok">sim</span>' : '<span class="badge">não</span>'}</td><td class="num">${c.ganho_backtest == null ? '—' : pct(c.ganho_backtest)}</td><td>${escH(c.interpretacao)}</td></tr>`).join('')}
      </tbody></table><p class="small muted">${escH(list[0].aviso)}</p>`;
  }

  /* ----------------------------------------------------------------- COMPARAÇÃO INTERNACIONAL */
  async function pageCompareIntl(arg) {
    main.innerHTML = `<h1>Comparação internacional</h1><p class="sub">Evolução do mesmo produto em Brasil, EUA e China (ou públicos por idioma), com análise exploratória de antecedência (lead-lag).</p><div id="ci">${loading()}</div>`;
    const d = await api('/api/consumer/compare' + (arg ? '?produto=' + encodeURIComponent(arg) : ''));
    if (!d.produtos.length) { $('#ci').innerHTML = '<div class="banner">Ainda não há produtos com séries em dois ou mais países/públicos.</div>'; return; }
    $('#ci').innerHTML = `<div class="form" style="margin-bottom:12px"><label class="f">Produto<select id="cprod">${d.produtos.map((p) => `<option value="${escH(p.product_id)}" ${p.product_id === d.produto ? 'selected' : ''}>${escH(p.nome)}</option>`).join('')}</select></label></div>
      <div class="panel"><h2>Séries (índice 100 = média de cada série)</h2><div id="cch"></div><p class="small muted">${escH(d.normalizacao)}</p></div>
      <div class="panel"><h2>Antecedência entre mercados</h2>${leadTable(d.comparacoes)}</div>
      <div class="panel"><h2>Indicadores por país</h2><table class="small"><thead><tr><th>País/público</th><th>Indicador</th><th class="num">Crescimento</th><th>Tendência</th><th>Sazonalidade</th><th class="num">Aceleração</th></tr></thead><tbody>
      ${d.series.map((s) => `<tr><td>${escH(s.pais_nome)}</td><td>${escH(s.metrica.rotulo)} · ${escH(s.fonte_nome)}</td><td class="num">${g(s.ind.crescimento)}</td><td>${cls(s.ind.classe)}</td><td>${s.ind.sazonalidade && s.ind.sazonalidade.significativa ? 'sim (' + fmt(s.ind.sazonalidade.fs, 2) + ')' : 'não'}</td><td class="num">${g(s.ind.aceleracao)}</td></tr>`).join('')}</tbody></table></div>`;
    $('#cprod').onchange = () => { location.hash = 'comparacao-internacional/' + encodeURIComponent($('#cprod').value); };
    lineFromSeries($('#cch'), d.series.filter((s) => s.period === 'mes'), { norm: true });
  }

  /* ----------------------------------------------------------------- OPORTUNIDADES */
  async function pageOpportunities() {
    main.innerHTML = `<h1>Oportunidades</h1><p class="sub">Produtos promissores para investigação — quatro medidas separadas. Nenhuma delas estima margem ou quantidade de compra.</p><div id="op">${loading()}</div>`;
    const d = await api('/api/consumer/opportunities');
    $('#op').innerHTML = `<div class="panel small">${Object.entries(d.definicoes).map(([k, v]) => `<p><b>${k}</b>: ${escH(v)}</p>`).join('')}
      <p class="muted">Ranking de importação por posição SH4 (Fase 2): <a href="#oportunidades">Comércio exterior → oportunidades de importação</a>.</p></div>
      <div class="panel"><div class="scroll" style="max-height:640px"><table><thead><tr><th>Produto</th><th>Categoria</th><th>Opportunity</th><th class="num">Evidence</th><th class="num">Forecast conf.</th><th class="num">Import readiness</th><th>Principais riscos</th></tr></thead><tbody>
      ${d.itens.map((i) => `<tr><td>${plink(i.product_id, i.nome)}</td><td class="small">${escH(i.categoria || '')}</td><td>${score(i.opportunity_score)}</td><td class="num">${fmt(i.evidence_coverage, 0)}</td><td class="num">${fmt(i.forecast_confidence, 0)}</td><td class="num">${fmt(i.import_readiness, 0)}</td><td class="small">${(i.riscos || []).slice(0, 2).map(escH).join('; ')}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">Sem produtos com sinais ainda.</td></tr>'}</tbody></table></div></div>`;
  }

  /* ----------------------------------------------------------------- EMERGENTES E DESCOBERTA */
  async function pageEmerging() {
    main.innerHTML = `<h1>Tendências emergentes</h1><p class="sub">Produtos que acabaram de aparecer nas fontes e termos novos descobertos automaticamente.</p><div id="em">${loading()}</div>`;
    const [br, us, disc] = await Promise.all([api('/api/consumer/country/BR'), api('/api/consumer/country/US'), api('/api/consumer/discovery')]);
    const em = [...br.rankings.emergentes.itens, ...us.rankings.emergentes.itens];
    $('#em').innerHTML = `<div class="panel"><h2>Produtos emergentes</h2><table class="small"><thead><tr><th>Produto</th><th>País</th><th>Indicador</th><th>Desde</th><th>Fonte</th></tr></thead><tbody>
      ${em.map((i) => `<tr><td>${plink(i.product_id, i.nome)}</td><td>${escH(i.pais)}</td><td>${escH(i.metrica_rotulo)}</td><td>${escH(i.valor || '')}</td><td>${escH(i.fonte)}</td></tr>`).join('') || '<tr><td colspan="5" class="muted">Nenhum produto emergente.</td></tr>'}</tbody></table></div>
      <div class="grid g2"><div class="panel"><h2>Produtos descobertos automaticamente</h2><table class="small"><tbody>${disc.descobertos.slice(0, 40).map((p) => `<tr><td>${plink(p.product_id, p.canonical)}</td><td>${escH(p.category)}</td><td class="muted">${escH(p.first_seen.slice(0, 10))}</td></tr>`).join('') || '<tr><td class="muted">Nenhum ainda.</td></tr>'}</tbody></table></div>
        <div class="panel"><h2>Termos observados recentemente</h2><div class="scroll"><table class="small"><thead><tr><th>Termo</th><th>Produto</th><th class="num">Ocorrências</th><th>Fontes</th><th>Intenções</th></tr></thead><tbody>
        ${disc.candidatos.slice(0, 120).map((c) => `<tr><td>${escH(c.term)}</td><td>${c.product_id ? plink(c.product_id, c.family_hint) : `<span class="muted">${escH(c.family_hint)} (candidato)</span>`}</td><td class="num">${c.occurrences}</td><td>${escH(Object.keys(c.sources).join(', '))}</td><td>${escH(Object.keys(c.intents).join(', '))}</td></tr>`).join('')}</tbody></table></div></div></div>`;
  }

  /* ----------------------------------------------------------------- ML: PREVISÃO DE TENDÊNCIAS E ANOMALIAS */
  async function pageTrendForecasts() {
    main.innerHTML = `<h1>Previsão de tendências</h1><p class="sub">Previsões de INTERESSE por produto, escolhidas por backtesting temporal. Não equivalem a unidades vendidas.</p><div id="tf">${loading()}</div>`;
    const d = await api('/api/consumer/forecasts');
    $('#tf').innerHTML = `<div class="banner info small">${escH(d.aviso)} Séries de volume de buscas precisam de ≥ 24 meses (o Google Ads devolve 12 meses por consulta; o histórico se forma com as coletas mensais). Séries da Wikipédia reaproveitam o AutoML da Fase 2.</div>
      <div class="panel"><table class="small"><thead><tr><th>Produto</th><th>País/público</th><th>Indicador</th><th>Fonte</th><th>Modelo</th><th>Qualidade</th><th class="num">WAPE</th><th class="num">Histórico</th><th>Limitações</th></tr></thead><tbody>
      ${d.itens.map((f) => `<tr><td>${f.serie ? plink(f.serie.split('|')[0], f.nome) : '—'}</td><td>${escH(f.pais || '')}</td><td>${escH(f.metrica || '')}</td><td>${escH(f.fonte || '')}</td><td>${escH(f.modelo_nome || f.modelo || f.status)}</td><td>${escH(f.qualidade || '—')}</td><td class="num">${f.metricas ? pct(f.metricas.wape) : '—'}</td><td class="num">${f.perfil ? f.perfil.n + ' m' : '—'}</td><td>${escH((f.limitacoes || [f.limitacao || '']).join('; '))}</td></tr>`).join('') || '<tr><td colspan="9" class="muted">Nenhuma série elegível ainda.</td></tr>'}</tbody></table></div>`;
  }

  async function pageAnomalies() {
    main.innerHTML = `<h1>Anomalias e mudanças de patamar</h1><p class="sub">Pontos fora do padrão (z robusto &gt; 3,5 sobre a mediana móvel) e mudanças de regime (segmentação binária com penalidade 2·ln(n)·σ²).</p><div id="an">${loading()}</div>`;
    const d = await api('/api/consumer/anomalies');
    $('#an').innerHTML = `<div class="panel"><table class="small"><thead><tr><th>Produto</th><th>País/público</th><th>Indicador</th><th>Mudanças de patamar</th><th>Anomalias</th></tr></thead><tbody>
      ${d.itens.map((s) => `<tr><td>${plink(s.product_id, s.nome)}</td><td>${escH(s.pais_nome)}</td><td>${escH(s.metrica.rotulo)} · ${escH(s.fonte_nome)}</td><td>${(s.ind.pontos_mudanca || []).map(escH).join(', ')}</td><td>${(s.ind.anomalias || []).map(escH).join(', ')}</td></tr>`).join('') || '<tr><td colspan="5" class="muted">Nenhuma anomalia detectada.</td></tr>'}</tbody></table></div>`;
  }

  /* ----------------------------------------------------------------- CATÁLOGO, NLP E DESEMPENHO */
  async function pageCatalog() {
    main.innerHTML = `<h1>Catálogo e descoberta de produtos</h1><p class="sub">Catálogo canônico (Categoria → Família → Produto → Variante), em português, inglês e chinês, separado dos códigos NCM/SH.</p>
      <div class="panel"><h2>Testar o NLP</h2><div class="form"><label class="f">Termo de busca ou manchete<input id="nt" style="width:380px" value="Melhor carregador rápido para iPhone"></label><button class="primary" id="nb">Analisar</button></div><div id="nr" class="small"></div></div>
      <div class="panel"><div class="form"><label class="f">Buscar<input id="cq" style="width:240px"></label></div><div id="cl">${loading()}</div></div>`;
    const run = async () => {
      const r = await api('/api/consumer/analyze?texto=' + encodeURIComponent($('#nt').value));
      const p = r.produto;
      $('#nr').innerHTML = `<p>Idioma: <b>${escH(r.idioma)}</b> · Intenção: <b>${escH(r.intencao.intencao)}</b> (${escH(r.intencao.metodo)}, confiança ${fmt(r.intencao.confianca, 2)}) · comercial: ${r.intencao.comercial ? 'sim' : 'não'}</p>
        <p>Produto: ${p ? `<b>${escH(p.nome_pt)}</b> / ${escH(p.nome_en)} / ${escH(p.nome_zh)} — chave <code>${escH(p.chave)}</code>${p.variante ? `, variante <b>${escH(p.variante)}</b>` : ''} · ${escH(p.categoria)} ${r.catalogo ? '<span class="badge ok">no catálogo</span>' : '<span class="badge">novo (candidato)</span>'}` : '<span class="muted">nenhum produto identificado</span>'}</p>
        <p>Atributos: <code>${escH(JSON.stringify(r.atributos))}</code> · Tokens: <code>${escH(r.tokens.join(' | '))}</code></p>`;
    };
    $('#nb').onclick = run; run();
    const load = async () => {
      const d = await api('/api/consumer/catalog?q=' + encodeURIComponent($('#cq').value || ''));
      $('#cl').innerHTML = `<p class="small muted">${d.total} itens</p><div class="scroll" style="max-height:600px"><table class="small"><thead><tr><th>Produto</th><th>EN</th><th>中文</th><th>Categoria</th><th>Nível</th><th>SH4</th><th>Origem</th><th class="num">Evidências</th></tr></thead><tbody>
        ${d.itens.map((p) => `<tr><td>${plink(p.product_id, p.canonical)}</td><td>${escH(p.name_en || '')}</td><td>${escH(p.name_zh || '')}</td><td>${escH(p.category)}</td><td>${escH(p.level)}</td><td>${escH(p.ncm_hint || '—')}</td><td>${escH(p.origin)}</td><td class="num">${p.evidence}</td></tr>`).join('')}</tbody></table></div>`;
    };
    $('#cq').oninput = () => { clearTimeout(window._cq); window._cq = setTimeout(load, 250); };
    load();
  }

  async function pagePerformance() {
    main.innerHTML = `<h1>Desempenho da sincronização</h1><p class="sub">Tempo por fonte, registros por segundo e uso das conexões (cache, revalidação, erros) — para comparar execuções em condições equivalentes.</p><div id="pf">${loading()}</div>`;
    const d = await api('/api/consumer/performance');
    $('#pf').innerHTML = d.execucoes.map((r) => `<div class="panel"><h2>Execução #${r.id} <span class="badge">${escH(r.estado)}</span></h2>
      <p class="small">${escH((r.inicio || '').replace('T', ' ').slice(0, 19))} → ${escH((r.fim || '').replace('T', ' ').slice(0, 19))}${r.desempenho ? ` · coleta: <b>${fmt(r.desempenho.coleta_segundos, 1)} s</b> com ${r.desempenho.trabalhadores} fonte(s) em paralelo` : ''}</p>
      <table class="small"><thead><tr><th>Fonte</th><th>Estado</th><th class="num">Segundos</th><th class="num">Jobs ok</th><th class="num">Falhas</th><th class="num">Registros</th><th class="num">Registros/s</th></tr></thead><tbody>
      ${r.fontes.map((f) => `<tr><td>${escH(f.source)}</td><td>${escH(f.state || '')}</td><td class="num">${fmt(f.seconds, 1)}</td><td class="num">${f.jobs_ok ?? '—'}</td><td class="num">${f.jobs_failed ?? '—'}</td><td class="num">${fmt(f.records, 0)}</td><td class="num">${fmt(f.records_per_s, 1)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">Sem métricas (execução anterior à Fase 4).</td></tr>'}</tbody></table>
      ${r.desempenho && r.desempenho.hosts ? `<details class="small"><summary>Conexões por host</summary><table><thead><tr><th>Host</th><th class="num">Requisições</th><th class="num">Cache</th><th class="num">304</th><th class="num">MB</th><th class="num">s</th><th class="num">Erros</th></tr></thead><tbody>${Object.entries(r.desempenho.hosts).map(([h, s]) => `<tr><td>${escH(h)}</td><td class="num">${s.requisicoes}</td><td class="num">${s.cache}</td><td class="num">${s.revalidadas_304}</td><td class="num">${fmt(s.bytes / 1e6, 2)}</td><td class="num">${fmt(s.segundos, 1)}</td><td class="num">${s.erros}</td></tr>`).join('')}</tbody></table></details>` : ''}</div>`).join('') || '<p class="muted">Nenhuma sincronização registrada.</p>';
  }

  return { dashboard: pageDashboard, alertas: pageAlerts, 'mais-pesquisados': pageRankings, consumo: pageCountry,
           'produto-consumo': pageProduct, 'comparacao-internacional': pageCompareIntl, 'oportunidades-consumo': pageOpportunities,
           emergentes: pageEmerging, 'previsao-tendencias': pageTrendForecasts, anomalias: pageAnomalies,
           catalogo: pageCatalog, desempenho: pagePerformance };
};
