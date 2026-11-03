/* GPI v0.5 — Modelos e Desempenho, Análise de Concorrência, Viabilidade de Importação, Configurações,
   Review Intelligence 2.0 e complementos da página de produto. Estados vazios sempre explicam o que falta. */
window.GPI_V05 = function (H, PAGES) {
  const { api, post, fmt, pct, escH, loading, main, $ } = H;
  const empty = (what, why, source, how) => `<div class="empty"><b>${escH(what)}</b><br>${escH(why)}${source ? `<br>Fonte que fornece: ${escH(source)}.` : ''}${how ? ` ${how}` : ''}</div>`;
  const LIB = (v) => v ? `<span class="badge ok">${escH(v)}</span>` : '<span class="badge">não instalada</span>';
  const NAMES = { local: 'Modelo local (melhor da série)', hist_gb_global: 'Global · HistGradientBoosting', lightgbm_global: 'Global · LightGBM',
    xgboost_global: 'Global · XGBoost', catboost_global: 'Global · CatBoost' };
  const METRIC = { volume_mensal_aprox: 'Volume de buscas (Google Ads)', volume_bing: 'Volume de buscas (Bing)', visualizacoes: 'Leitura de artigos (Wikipédia)' };

  /* ---------------------------------------------------------------- MODELOS E DESEMPENHO */
  async function pageModels() {
    main.innerHTML = `<h1>Modelos e Desempenho</h1><p class="sub">Modelo global multi-série × modelos locais, intervalos conformais, explicabilidade e mudanças de comportamento — por grupo de métrica (unidades nunca misturadas).</p><div id="md">${loading()}</div>`;
    const d = await api('/api/consumer/models');
    const ml = d.ml || {}, grupos = Object.entries(ml.grupos || {});
    $('#md').innerHTML = `<div class="panel"><h2>Bibliotecas disponíveis neste computador</h2><table class="small"><tbody>
        ${Object.entries(d.bibliotecas).map(([k, v]) => `<tr><td>${escH(k)}</td><td>${LIB(v)}</td></tr>`).join('')}</tbody></table>
        <p class="small muted">Similaridade de produtos: ${escH(d.descoberta.similaridade)} · embeddings: ${escH(d.descoberta.embeddings)}. Sem uma biblioteca opcional, o GPI usa a alternativa interna documentada na Metodologia.</p></div>
      ${grupos.length ? grupos.map(([m, g]) => group(m, g)).join('') : empty('Nenhum modelo global treinado ainda.', 'É preciso pelo menos 3 séries mensais com 24 meses ou mais da mesma métrica (ex.: volume de buscas do Google Ads ou leitura de artigos da Wikipédia).', 'Google Ads (Planejador), Microsoft Advertising, Wikimedia', 'O treino roda automaticamente após cada sincronização (pode ser desligado em <a href="#configuracoes">Configurações</a>).')}
      <div class="panel"><h2>Mudanças de comportamento (ADWIN / Page-Hinkley)</h2>
        ${d.mudancas.length ? `<table class="small"><thead><tr><th>Série</th><th>Detector</th><th>Período</th><th>Direção</th><th>Registrado</th></tr></thead><tbody>${d.mudancas.map((e) => `<tr><td>${escH(e.detail || e.series_id)}</td><td>${escH(e.detector)}</td><td>${escH(e.ref_date)}</td><td>${escH(e.direction)}</td><td>${escH((e.created_at || '').slice(0, 10))}</td></tr>`).join('')}</tbody></table><p class="small muted">Uma mudança recente marca a série para reavaliação; só os grupos afetados são retreinados.</p>`
          : empty('Nenhuma mudança persistente detectada.', 'Os detectores rodam sobre as séries mensais elegíveis a cada sincronização.')}</div>`;
  }
  function group(m, g) {
    const res = (g.backtest || {}).resumo || {};
    const rows = Object.entries(res).sort((a, b) => a[1].wape_medio - b[1].wape_medio);
    const conf = g.conformal || {};
    const fac = (g.explicacao_global || {}).fatores || [];
    return `<div class="panel"><h2>${escH(METRIC[m] || m)} <span class="badge">${g.series} séries</span> ${g.reutilizado ? '<span class="badge">reaproveitado (dados sem mudança)</span>' : ''}</h2>
      ${g.aviso ? `<p class="small muted">${escH(g.aviso)}</p>` : ''}
      ${rows.length ? `<table class="small"><thead><tr><th>Modelo</th><th class="num">WAPE médio</th><th class="num">WAPE mediano</th><th class="num">Avaliações</th><th class="num">Séries em que venceu</th></tr></thead><tbody>
        ${rows.map(([k, v]) => `<tr><td>${escH(NAMES[k] || k)}${k === g.melhor_global ? ' <span class="badge ok">melhor global</span>' : ''}</td><td class="num">${pct(v.wape_medio)}</td><td class="num">${pct(v.wape_mediano)}</td><td class="num">${v.n}</td><td class="num">${(g.backtest.vitorias_por_serie || {})[k] || 0}</td></tr>`).join('')}</tbody></table>
        <p class="small muted">Backtesting de origem móvel (${g.backtest.origens} origens, horizonte ${g.backtest.horizonte} meses). Em cada série vale o modelo com menor erro — o global não é presumido melhor.</p>` : ''}
      ${conf.quantis ? `<h3>Intervalos conformais</h3><table class="small"><thead><tr><th>Nível</th><th class="num">Cobertura observada (origem recente)</th></tr></thead><tbody>${Object.keys(conf.quantis).map((l) => `<tr><td>${Math.round(+l * 100)}%</td><td class="num">${conf.cobertura_observada[l] == null ? '—' : pct(conf.cobertura_observada[l])}</td></tr>`).join('')}</tbody></table>
        <p class="small muted">Calibrado em ${conf.n_calibracao} previsões; testado em ${conf.n_teste}. Mudanças de regime podem reduzir a cobertura — ela não é garantida.</p>` : ''}
      ${fac.length ? `<h3>O que mais pesa nas previsões (${escH(g.explicacao_global.metodo)})</h3>${fac.slice(0, 8).map((f) => `<div class="bar-row"><span class="bar-label">${escH(f.fator)}</span><span class="score"><i style="width:${Math.round(100 * f.peso)}%"></i></span><span>${pct(f.peso, 0)}</span></div>`).join('')}<p class="small muted">${escH(g.explicacao_global.aviso || '')}</p>` : ''}
      ${g.otimizacao && g.otimizacao.melhores_parametros ? `<p class="small">Optuna: ${g.otimizacao.tentativas} tentativas · WAPE de validação ${pct(g.otimizacao.wape_validacao)} · <code>${escH(JSON.stringify(g.otimizacao.melhores_parametros))}</code></p>` : `<p class="small muted">Otimização: ${escH((g.otimizacao || {}).aviso || '—')}</p>`}
      ${g.hierarquia && Object.keys(g.hierarquia).length && !g.hierarquia.aviso ? `<h3>Reconciliação hierárquica (total da categoria, 1º mês)</h3><table class="small"><thead><tr><th>País · categoria</th><th class="num">Base (total previsto)</th><th class="num">Bottom-Up</th><th class="num">Top-Down</th><th class="num">MinT OLS</th><th class="num">MinT WLS</th></tr></thead><tbody>${Object.entries(g.hierarquia).map(([k, v]) => `<tr><td>${escH(k)}</td><td class="num">${fmt(v.total_base[0], 0)}</td>${['bu', 'td', 'mint_ols', 'mint_wls'].map((x) => `<td class="num">${fmt(v.reconciliado[x][0], 0)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : (g.hierarquia && g.hierarquia.aviso ? `<p class="small muted">${escH(g.hierarquia.aviso)}</p>` : '')}
    </div>`;
  }

  /* ---------------------------------------------------------------- CONCORRÊNCIA */
  async function pageCompetition() {
    main.innerHTML = `<h1>Análise de Concorrência</h1><p class="sub">Preços, vendedores únicos, marcas e pressão competitiva a partir de anúncios de fontes autorizadas.</p><div id="cc">${loading()}</div>`;
    const d = await api('/api/consumer/competition');
    $('#cc').innerHTML = `<div class="banner info small">${escH(d.aviso)} ${d.definicao_pressao ? '<br><b>Pressão competitiva:</b> ' + escH(d.definicao_pressao) : ''}</div>
      ${d.itens.length ? `<div class="panel" style="overflow-x:auto"><table class="small"><thead><tr><th>Produto</th><th>Fonte</th><th class="num">Anúncios</th><th class="num">Vendedores únicos</th><th class="num">Preço mediano</th><th class="num">Q1–Q3</th><th class="num">Em promoção</th><th>Marcas (nos anúncios)</th><th class="num">HHI</th><th class="num">Pressão</th></tr></thead><tbody>
        ${d.itens.map((c) => `<tr><td><a href="#produto-consumo/${encodeURIComponent(c.product_id)}">${escH(c.product_id)}</a></td><td>${escH(c.fonte)}</td><td class="num">${c.anuncios}</td><td class="num">${c.vendedores_unicos}</td><td class="num">${escH(c.moeda)} ${fmt(c.preco_mediano, 2)}</td><td class="num">${fmt(c.preco_q1, 2)}–${fmt(c.preco_q3, 2)}</td><td class="num">${c.anuncios_em_promocao}</td><td>${c.marcas.slice(0, 4).map((b) => `${escH(b.marca)} (${b.anuncios})`).join(', ')}</td><td class="num">${fmt(c.hhi_marcas_anuncios, 2)}</td><td class="num"><b>${fmt(c.pressao_competitiva, 0)}</b></td></tr>`).join('')}</tbody></table></div>`
      : empty('Nenhum anúncio coletado ainda.', 'A análise de concorrência precisa de anúncios com preço e vendedor de uma fonte autorizada.', 'eBay Browse API (gratuita, chave de aplicativo)', 'Conecte em <a href="#integracoes">Central de Integrações → eBay</a>.')}`;
  }

  /* ---------------------------------------------------------------- VIABILIDADE */
  const FIELDS = [['fob_usd', 'Preço FOB por unidade (US$)', true], ['exw_usd', 'ou preço EXW (US$)', true], ['frete_china_usd', 'Frete interno na China (US$/un., com EXW)', false],
    ['frete_usd', 'Frete internacional (US$/un.)', true], ['seguro_pct', 'Seguro (% do FOB+frete)', false], ['cambio', 'Câmbio R$/US$', true],
    ['ii', 'Imposto de Importação (%)', false], ['ipi', 'IPI (%)', false], ['pis', 'PIS-Importação (%)', false], ['cofins', 'COFINS-Importação (%)', false], ['icms', 'ICMS (%)', false],
    ['despesas_brl_unidade', 'Despesas aduaneiras e logísticas (R$/un.)', false], ['preco_venda_brl', 'Preço de venda (R$/un.)', true], ['demanda_mensal', 'Demanda mensal estimada (un.)', true],
    ['moq', 'MOQ (un.)', false], ['lote', 'Múltiplo do pedido (un.)', false], ['lead_time_dias', 'Lead time (dias)', false], ['horizonte_meses', 'Horizonte de venda (meses)', false],
    ['orcamento_brl', 'Orçamento disponível (R$)', false], ['nivel_servico', 'Nível de serviço (0,90/0,95/0,98)', false]];
  async function pageViability() {
    const dft = await api('/api/import/defaults');
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('gpi.viab') || '{}'); } catch (e) { saved = {}; }
    if (!saved.cambio && dft.cambio_ptax) saved.cambio = { base: dft.cambio_ptax.value };
    const cell = (k, lab, rng) => { const v = saved[k] || {}; const b = typeof v === 'object' ? v : { base: v };
      return `<div class="panel" style="padding:10px 12px;margin:0"><label class="small"><b>${escH(lab)}</b></label><div class="form" style="gap:6px;margin-top:4px">
        ${rng ? `<input data-k="${k}" data-p="min" placeholder="mín" value="${b.min ?? ''}" style="width:80px">` : ''}<input data-k="${k}" data-p="base" placeholder="${rng ? 'base' : 'valor'}" value="${b.base ?? ''}" style="width:90px">${rng ? `<input data-k="${k}" data-p="max" placeholder="máx" value="${b.max ?? ''}" style="width:80px">` : ''}</div></div>`; };
    main.innerHTML = `<h1>Viabilidade de Importação</h1><p class="sub">Simulação com os SEUS dados: custo nacionalizado, Monte Carlo, cenários, sensibilidade, estoque e quantidade de pedido. O GPI não inventa preços, custos ou margens.</p>
      ${dft.cambio_ptax ? `<div class="banner info small">Câmbio pré-preenchido com a PTAX de venda de ${escH(dft.cambio_ptax.ref_date)} (Banco Central): R$ ${fmt(dft.cambio_ptax.value, 4)}. Ajuste a faixa conforme seu cenário.</div>` : ''}
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px">${FIELDS.map(([k, l, r]) => cell(k, l, r)).join('')}</div>
      <p><button class="primary" id="vsim">Simular</button> <span class="muted small">Campos com mín/base/máx entram no Monte Carlo (distribuição triangular). Os valores ficam guardados neste navegador.</span></p><div id="vres"></div>`;
    $('#vsim').onclick = async () => {
      const p = {};
      main.querySelectorAll('[data-k]').forEach((i) => { if (i.value === '') return; const v = +i.value.replace(',', '.'); (p[i.dataset.k] ||= {})[i.dataset.p] = v; });
      for (const k of Object.keys(p)) { const v = p[k]; if (v.min == null && v.max == null) p[k] = v.base; else { v.base ??= v.min ?? v.max; v.min ??= v.base; v.max ??= v.base; } }
      try { localStorage.setItem('gpi.viab', JSON.stringify(p)); } catch (e) { /* sem armazenamento */ }
      $('#vres').innerHTML = loading();
      try { showSim(await post('/api/import/simulate', { parametros: p })); } catch (e) { $('#vres').innerHTML = `<div class="banner">${escH(e.message || e)}</div>`; }
    };
  }
  function showSim(r) {
    if (r.status !== 'ok') { $('#vres').innerHTML = `<div class="panel">${empty('Faltam dados para simular.', r.aviso)}<ul class="small">${r.faltando.map((x) => `<li>${escH(x)}</li>`).join('')}</ul></div>`; return; }
    const c = r.custo_base;
    $('#vres').innerHTML = `<div class="kpis"><div class="kpi"><span>Quantidade sugerida</span><b>${r.quantidade_sugerida == null ? 'nenhuma viável' : fmt(r.quantidade_sugerida, 0)}</b></div>
      <div class="kpi"><span>Custo nacionalizado (base)</span><b>R$ ${fmt(c.custo_unitario, 2)}</b></div><div class="kpi"><span>Investimento</span><b>R$ ${fmt(r.investimento_base, 0)}</b></div>
      <div class="kpi"><span>Lucro esperado (P10–P90)</span><b>R$ ${fmt(r.lucro.media, 0)}</b><small class="muted">R$ ${fmt(r.lucro.p10, 0)} a ${fmt(r.lucro.p90, 0)}</small></div>
      <div class="kpi"><span>Chance de prejuízo</span><b>${pct(r.lucro.prob_prejuizo)}</b></div><div class="kpi"><span>Margem unitária (P50)</span><b>${pct(r.margem_unitaria.p50)}</b></div></div>
      <div class="grid g2"><div class="panel"><h2>Composição do custo (base)</h2><table class="small"><tbody>${['cif', 'ii', 'ipi', 'pis', 'cofins', 'icms', 'despesas'].map((k) => `<tr><td>${k.toUpperCase()}</td><td class="num">R$ ${fmt(c[k], 2)}</td></tr>`).join('')}</tbody></table></div>
        <div class="panel"><h2>Cenários (quantidade sugerida)</h2><table class="small"><tbody>${Object.entries(r.cenarios).map(([k, v]) => `<tr><td>${k}</td><td class="num ${v < 0 ? 'neg' : 'pos'}">R$ ${fmt(v, 0)}</td></tr>`).join('')}</tbody></table>
          <h2>Estoque</h2><p class="small">Estoque de segurança: <b>${fmt(r.estoque.estoque_seguranca, 0)}</b> un. · ponto de reposição: <b>${fmt(r.estoque.ponto_reposicao, 0)}</b> un. (lead time ${fmt(r.estoque.lead_time_meses, 1)} meses)</p></div></div>
      <div class="panel"><h2>Sensibilidade (lucro com cada variável no mínimo e no máximo)</h2><table class="small"><thead><tr><th>Variável</th><th class="num">No mínimo</th><th class="num">No máximo</th><th class="num">Amplitude</th></tr></thead><tbody>
        ${r.sensibilidade.map((x) => `<tr><td>${escH(x.variavel)}</td><td class="num">R$ ${fmt(x.lucro_no_minimo, 0)}</td><td class="num">R$ ${fmt(x.lucro_no_maximo, 0)}</td><td class="num">R$ ${fmt(x.amplitude, 0)}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">Informe faixas (mín/máx) para ver a sensibilidade.</td></tr>'}</tbody></table>
        <p class="small muted">${escH(r.aviso)} ${fmt(r.cenarios_simulados, 0)} cenários simulados.</p></div>`;
  }

  /* ---------------------------------------------------------------- CONFIGURAÇÕES */
  async function pageSettings() {
    main.innerHTML = `<h1>Configurações</h1><p class="sub">Ajustes de coleta, limites de memória e machine learning — sem editar arquivos.</p><div id="cfg">${loading()}</div>`;
    const d = await api('/api/settings');
    $('#cfg').innerHTML = `<div class="panel"><table class="small"><tbody>${d.campos.map((f) => {
      const v = d.valores[f.chave];
      const inp = f.tipo === 'bool' ? `<input type="checkbox" data-c="${f.chave}" ${v ? 'checked' : ''}>`
        : `<input data-c="${f.chave}" value="${escH(Array.isArray(v) ? v.join(', ') : (v ?? ''))}" style="width:140px">${f.min != null ? ` <span class="muted">(${f.min}–${f.max})</span>` : ''}`;
      return `<tr><td style="width:55%">${escH(f.descricao)}<br><code class="muted">${escH(f.chave)}</code></td><td>${inp}</td></tr>`; }).join('')}</tbody></table>
      <p><button class="primary" id="csave">Salvar</button> <span id="cmsg" class="small"></span></p>
      <p class="small muted">Alguns ajustes valem a partir da próxima sincronização. Sistema e diagnóstico: <a href="#sistema">página Sistema</a>.</p></div>`;
    $('#csave').onclick = async () => {
      const body = {};
      main.querySelectorAll('[data-c]').forEach((i) => { body[i.dataset.c] = i.type === 'checkbox' ? i.checked : (i.dataset.c === 'trends_geos' ? i.value.split(',') : i.value); });
      try { await post('/api/settings', body); $('#cmsg').innerHTML = '<span class="pos">Salvo.</span>'; } catch (e) { $('#cmsg').innerHTML = `<span class="neg">${escH(e.message || e)}</span>`; }
    };
  }

  /* ---------------------------------------------------------------- REVIEWS 2.0 e PRODUTO */
  const origReviews = PAGES.reviews;
  async function pageReviews() {
    await origReviews();
    const d = await api('/api/consumer/reviews2');
    const box = document.createElement('div');
    const cl = (d.clusters || {}).grupos || [];
    box.innerHTML = `<h2 style="margin-top:22px">Review Intelligence 2.0 — por produto do catálogo</h2><div class="banner info small">${escH(d.aviso)}</div>
      ${d.produtos.length ? `<div class="panel" style="overflow-x:auto"><table class="small"><thead><tr><th>Produto</th><th class="num">Opiniões</th><th>Principais elogios</th><th>Principais críticas</th><th>Problemas técnicos recorrentes</th><th>Alvo das reclamações</th><th>Marcas (saldo)</th></tr></thead><tbody>
        ${d.produtos.slice(0, 60).map((p) => `<tr><td><a href="#produto-consumo/${encodeURIComponent(p.product_id)}">${escH(p.product_id)}</a>${p.suficiente ? '' : ' <span class="badge">amostra pequena</span>'}</td><td class="num">${p.n}</td><td>${p.elogios.map((x) => `${escH(x.aspecto)} (${x.mencoes})`).join(', ') || '—'}</td><td>${p.criticas.map((x) => `${escH(x.aspecto)} (${x.mencoes})`).join(', ') || '—'}</td><td>${p.problemas_tecnicos.map((x) => `${escH(x.aspecto)} (${x.mencoes})`).join(', ') || '—'}</td><td>${Object.entries(p.alvos).map(([k, v]) => `${escH(k)}: ${v}`).join(', ') || '—'}</td><td>${p.marcas.map((b) => `${escH(b.marca)} ${b.saldo >= 0 ? '+' : ''}${fmt(b.saldo, 2)}`).join(', ') || '—'}</td></tr>`).join('')}</tbody></table></div>`
        : empty('Nenhuma opinião associada a produtos do catálogo ainda.', 'As opiniões vêm de manchetes e discussões (RSS, Reddit, Google Notícias opt-in).', 'Feeds RSS (automático), Reddit e Google Notícias (Central de Integrações)')}
      <div class="panel"><h2>Agrupamento de reclamações</h2>${cl.length ? `<p class="small muted">TF-IDF + K-Means (silhueta ${fmt(d.clusters.silhueta, 2)}).</p><table class="small"><thead><tr><th>Grupo (termos característicos)</th><th class="num">Reclamações</th><th>Produtos</th><th>Exemplos</th></tr></thead><tbody>${cl.map((g) => `<tr><td>${escH(g.rotulo)}</td><td class="num">${g.reclamacoes}</td><td>${g.produtos.map(escH).join(', ')}</td><td>${g.exemplos.map((e) => e.url ? `<a href="${escH(e.url)}" target="_blank" rel="noopener">${escH(e.titulo || 'abrir')}</a>` : escH(e.titulo)).join('<br>')}</td></tr>`).join('')}</tbody></table>` : `<p class="small muted">${escH((d.clusters || {}).aviso || 'Sem reclamações suficientes para agrupar.')}</p>`}</div>`;
    main.appendChild(box);
  }

  const origProduct = PAGES['produto-consumo'];
  async function pageProduct(pid) {
    await origProduct(pid);
    let d;
    try { d = await api('/api/consumer/product/' + encodeURIComponent(pid)); } catch (e) { return; }
    const box = document.createElement('div');
    const mls = Object.entries(d.ml || {});
    box.innerHTML = `<div class="panel"><h2>Previsão com intervalos calibrados e fatores</h2>${mls.length ? mls.map(([sid, v]) => `<p class="small"><b>${escH(sid.split('|').slice(1).join(' · '))}</b> — modelo ${escH(NAMES[v.modelo] || v.modelo)} (${escH(v.escolha)})</p>
        <table class="small"><thead><tr><th>Mês</th>${v.previsao.map((_, i) => `<th class="num">+${i + 1}</th>`).join('')}</tr></thead><tbody><tr><td>Previsão</td>${v.previsao.map((x) => `<td class="num">${fmt(x, 0)}</td>`).join('')}</tr>
        ${Object.entries(v.intervalos || {}).map(([l, b]) => `<tr><td>${Math.round(+l * 100)}%</td>${b.lo.map((x, i) => `<td class="num">${fmt(x, 0)}–${fmt(b.hi[i], 0)}</td>`).join('')}</tr>`).join('')}</tbody></table>
        ${v.fatores.length ? `<p class="small">Fatores que mais pesaram: ${v.fatores.map((f) => `${escH(f.fator)} (${pct(f.peso, 0)})`).join(', ')} <span class="muted">— contribuição preditiva, não causalidade.</span></p>` : ''}`).join('')
        : empty('Sem previsão do modelo avançado para este produto.', 'Requer série mensal de volume de buscas ou de leitura de artigos com 24 meses ou mais.', 'Google Ads, Microsoft Advertising, Wikimedia')}</div>
      <div class="grid g2"><div class="panel"><h2>Concorrência</h2>${(d.concorrencia || []).length ? d.concorrencia.map((c) => `<p class="small">${escH(c.fonte)}: ${c.anuncios} anúncios, ${c.vendedores_unicos} vendedores únicos, preço mediano ${escH(c.moeda)} ${fmt(c.preco_mediano, 2)}, pressão competitiva <b>${fmt(c.pressao_competitiva, 0)}</b></p>`).join('')
        : empty('Sem anúncios coletados.', 'Necessário para preços e concorrência.', 'eBay Browse API', '<a href="#integracoes">Conectar</a>.')}</div>
        <div class="panel"><h2>Avaliações e opiniões</h2>${d.reviews ? `<p class="small">${d.reviews.n} opiniões · críticas: ${d.reviews.criticas.map((x) => escH(x.aspecto)).join(', ') || '—'} · elogios: ${d.reviews.elogios.map((x) => escH(x.aspecto)).join(', ') || '—'}</p>`
        : empty('Sem opiniões associadas.', 'Opiniões vêm de RSS, Reddit e Google Notícias.')}</div></div>`;
    main.appendChild(box);
  }

  return { modelos: pageModels, concorrencia: pageCompetition, viabilidade: pageViability, configuracoes: pageSettings,
           reviews: pageReviews, 'produto-consumo': pageProduct };
};
