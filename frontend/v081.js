/* GPI v0.8.1 — dashboard executivo (A–H), Radar de Candidatos, alertas comerciais/estatísticos/de qualidade, dossiê em três
   níveis, públicos linguísticos ≠ países e Assistente de Conexão Meta. Números vindos do backend (resultado único). */
window.GPI_V081 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, errBox, main, $ } = H;
  const pct = (v) => v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v * 100, 0)}%`;
  const num = (v, d = 0) => v == null ? '—' : fmt(v, d);
  const dl = (pid, n) => `<a href="#dossie/${encodeURIComponent(pid)}">${escH(n || pid)}</a>`;
  const tip = (t) => `<span class="tip" title="${escH(t)}">ⓘ</span>`;
  const tbl = (head, rows, empty) => rows.length ? `<div class="scroll"><table class="small compact"><thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`
    : `<p class="muted small">${escH(empty || 'Nada a mostrar com os dados atuais.')}</p>`;
  /* mini série temporal (SVG inline, sem bibliotecas). inv=true: menor é melhor (posição no ranking) */
  function spark(vals, inv = false, w = 110, h = 26) {
    const pts = (vals || []).map((v, i) => [i, v]).filter(([, v]) => v != null && isFinite(v));
    if (pts.length < 2) return '<span class="muted small">—</span>';
    const ys = pts.map(([, v]) => v), lo = Math.min(...ys), hi = Math.max(...ys), n = (vals.length - 1) || 1;
    const Y = (v) => hi === lo ? h / 2 : (inv ? (v - lo) / (hi - lo) : (hi - v) / (hi - lo)) * (h - 4) + 2;
    const d = pts.map(([i, v], k) => `${k ? 'L' : 'M'}${(i / n * (w - 4) + 2).toFixed(1)},${Y(v).toFixed(1)}`).join('');
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="mini série"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
  }
  const SEV = { alta: 'cst1', 'média': 'cst2', baixa: 'cst3' };

  /* ---------------------------------------------------------------- DASHBOARD EXECUTIVO */
  async function pageDashboard() {
    main.innerHTML = `<h1>Dashboard</h1><p class="sub">O que mudou no mercado, quais produtos chamam atenção, quais têm evidência comercial e quais precisam ser investigados.</p><div id="dx">${loading('Consolidando evidências…')}</div>`;
    let d;
    try { d = await api('/api/v081/executivo'); } catch (e) { $('#dx').innerHTML = errBox(e); return; }
    const p = d.panorama, c = d.coberturas || {};
    const K = [['Produtos monitorados', p.produtos_monitorados, 'Produtos do catálogo.'],
      ['Com dados recentes', p.produtos_com_dados_recentes, 'Qualquer evidência nos últimos 45 dias (inclui atenção pública).'],
      ['Com evidência comercial', p.com_evidencia_comercial, 'Classes B (intenção comercial) ou C (interesse de pesquisa) — não inclui Wikipédia/notícias.'],
      ['Novos sinais', p.novos_sinais, 'Primeira observação em ranking comercial ou pesquisa.'],
      ['Interesse recorrente', p.interesse_recorrente, '≥ 4 semanas e ≥ 50% das semanas no ranking comercial.'],
      ['Crescimento confirmado', p.crescimento_confirmado, 'Tendência significativa + confirmação por 2 fontes independentes de demanda.'],
      ['Investigações abertas', p.em_investigacao, 'Lista de Investigação.'],
      ['Cobertura comercial', p.cobertura_comercial == null ? '—' : fmt(p.cobertura_comercial, 1) + '%', p.cobertura_comercial_formula]];
    const covRow = (k, t) => c[k] ? `<tr><td>${t}</td><td class="num"><b>${c[k].valor == null ? '—' : fmt(c[k].valor, 1) + '%'}</b></td><td class="num muted">${num(c[k].numerador)} / ${num(c[k].denominador)}</td><td class="small muted">${escH(c[k].formula)}</td></tr>` : '';
    const geo = c.geografica ? Object.entries(c.geografica.por_mercado).map(([m, v]) => `<tr><td>${escH(m.startsWith('LANG:') ? 'Público ' + m.slice(5) + ' (idioma)' : m)}</td><td class="num">${v.produtos_com_dados}</td><td class="num">${v.com_evidencia_de_demanda}</td><td class="small muted">${escH(v.dimensao)}</td></tr>`).join('') : '';
    const h = d.saude;
    const intl = d.internacional || { mercados: [], publicos_linguisticos: [] };
    const intlRows = (l) => l.map((x) => `<tr><td>${dl(x.produto_id, x.produto)}</td><td class="small">${escH(x.indicador)} (${escH(x.fonte)})</td><td>${escH(x.mercado_a)} ${pct(x.variacao_a)}</td><td>${escH(x.mercado_b)} ${pct(x.variacao_b)}</td><td>${escH(x.antecedencia)}${x.r2 != null ? ` <span class="muted small">r² ${fmt(x.r2 * 100, 0)}%</span>` : ''}</td></tr>`);
    $('#dx').innerHTML = `<div class="banner info small">${escH(d.aviso)} · Análise de ${escH(d.gerado_em || '—')} · Última coleta: ${escH(h.ultima_coleta || '—')}.</div>
      <section><h2>A. Panorama</h2><div class="kpis compact">${K.map(([t, v, x]) => `<div class="kpi" title="${escH(x || '')}"><span>${escH(t)} ${tip(x || '')}</span><b>${escH(v ?? '—')}</b></div>`).join('')}</div>
        <details><summary class="small">Como cada cobertura é calculada</summary><table class="small compact"><thead><tr><th>Cobertura</th><th>Valor</th><th>Cálculo</th><th>Fórmula</th></tr></thead><tbody>
        ${covRow('catalogo', 'Catálogo')}${covRow('comercial', 'Comercial')}${covRow('temporal', 'Temporal')}${covRow('previsao', 'Para previsão')}</tbody></table>
        <table class="small compact"><thead><tr><th>Mercado / público</th><th>Produtos com dados</th><th>Com evidência de demanda</th><th>Dimensão</th></tr></thead><tbody>${geo}</tbody></table>
        <p class="small muted">${escH(c.nota || '')}</p></details></section>
      <div class="panel"><h2>B. Top produtos para investigação</h2>${tbl(['Produto', 'Mercado', 'Sinal', 'Evidência', 'Persistência', 'Confiança', 'Próxima ação'],
        d.top_investigacao.map((x) => `<tr><td>${dl(x.produto_id, x.produto)}<br><span class="muted small">${escH(x.estado)}</span></td><td>${escH(x.mercado || '—')}</td><td class="small">${escH(x.sinal || '—')}</td><td>${escH(x.evidencia)}</td><td class="num">${x.persistencia == null ? '—' : fmt(x.persistencia, 0) + '%'}</td><td>${escH(x.confianca)}</td><td class="small">${escH(x.proxima_acao)}</td></tr>`),
        'Nenhum produto com evidência comercial suficiente para investigação recomendada. A seção não é preenchida artificialmente — veja os sinais preliminares.')}</div>
      <div class="grid2"><div class="panel"><h2>C. Radar comercial</h2><p class="small muted">Mercado Livre e fontes de pesquisa compatíveis. Ranking: posição (linha sobe = posição melhor), não volume.</p>
        ${tbl(['Produto', 'Fonte', 'Histórico', 'Leitura'], d.radar_comercial.map((x) => `<tr><td>${dl(x.produto_id, x.produto)}</td><td class="small">${escH(x.fonte)}<br><span class="muted">${escH(x.mercado || '')}</span></td>
          <td>${x.historico ? spark(x.historico.map((v) => v[1]), true) : spark(x.valores)}</td><td class="small">${x.semanas != null ? `${x.semanas} semana(s) no top 50 · melhor ${num(x.melhor_posicao)}` : x.momentum != null ? `variação ${pct(x.momentum)}` : escH(x.indicador)}</td></tr>`),
          'Sem sinais comerciais coletados. Conecte o Mercado Livre ou uma fonte de pesquisa (Central de Integrações).')}</div>
        <div class="panel"><h2>D. Sinais preliminares</h2><p class="small muted">Interessantes, mas sem confirmação suficiente.</p>
        ${tbl(['Produto', 'Estado', 'Por quê'], d.preliminares.map((x) => `<tr><td>${dl(x.produto_id, x.produto)}</td><td>${escH(x.estado)}</td><td class="small">${escH(x.motivo)}</td></tr>`), 'Nenhum sinal preliminar.')}</div></div>
      <div class="panel"><h2>E. Análise internacional</h2><p class="small muted">${escH(intl.regra || '')}</p>
        <h3>Mercados geográficos</h3>${tbl(['Produto', 'Indicador', 'Mercado A', 'Mercado B', 'Antecedência'], intlRows(intl.mercados), 'Sem séries comparáveis entre países (exige a mesma fonte e métrica de pesquisa nos dois mercados).')}
        ${intl.publicos_linguisticos.length ? `<details><summary class="small">Públicos linguísticos (atenção, não mercados) — ${intl.publicos_linguisticos.length}</summary>${tbl(['Produto', 'Indicador', 'Público A', 'Público B', 'Antecedência'], intlRows(intl.publicos_linguisticos))}</details>` : ''}</div>
      <div class="grid2"><div class="panel"><h2>F. Alertas importantes</h2>${tbl(['', 'Produto', 'Alerta', 'Ação'], d.alertas.map((a) => `<tr><td><span class="cst ${SEV[a.severidade]}">${escH(a.severidade)}</span></td><td>${a.produto_id ? dl(a.produto_id, a.produto) : escH(a.produto)}</td><td class="small">${escH(a.tipo)} — ${escH(a.motivo)}${a.ocorrencias > 1 ? ` (${a.ocorrencias}×)` : ''}</td><td class="small">${escH(a.acao)}</td></tr>`), 'Nenhum alerta comercial ou de qualidade recente.')}<p class="small"><a href="#alertas">Todos os alertas →</a></p></div>
        <div class="panel"><h2>G. Insights automáticos</h2>${d.insights.length ? d.insights.map((i) => `<details><summary>${dl(i.produto_id, i.produto)} — <span class="small">${escH(i.situacao)}</span></summary><p class="small"><b>Evidência:</b> ${escH(i.evidencia)}<br><b>Explicação:</b> ${escH(i.interpretacao)}<br><b>Limitação:</b> ${escH((i.limitacoes || [])[1] || (i.limitacoes || [])[0] || '')}<br><b>Próxima investigação:</b> ${escH(i.proxima_investigacao)}</p></details>`).join('') : '<p class="muted small">Sem conclusões com evidência de demanda.</p>'}</div></div>
      <div class="panel"><h2>H. Saúde dos dados</h2><div class="kpis compact">
        <div class="kpi"><span>Fontes funcionais</span><b>${h.funcionais}</b></div><div class="kpi"><span>Sem credenciais</span><b>${h.sem_credenciais}</b></div>
        <div class="kpi"><span>Com falha</span><b>${h.com_falha}</b></div><div class="kpi"><span>Séries elegíveis (tendência)</span><b>${num(h.series_elegiveis.tendencia)}</b></div>
        <div class="kpi"><span>Séries elegíveis (previsão)</span><b>${num(h.series_elegiveis.previsao)}</b></div></div>
        <p class="small">Gates: ${Object.entries(h.gates).map(([g, s]) => `${g} <b>${escH(s)}</b>`).join(' · ')} — <a href="#qualidade-dados">Qualidade dos Dados</a> · <a href="#fontes">Saúde das Fontes</a></p>
        ${h.problemas.length ? `<ul class="small">${h.problemas.map((a) => `<li>${escH(a.tipo)}: ${escH(a.motivo)}</li>`).join('')}</ul>` : ''}</div>`;
  }

  /* ---------------------------------------------------------------- RADAR DE CANDIDATOS */
  async function pageRadar() {
    main.innerHTML = `<h1>Inteligência de Oportunidades — Radar de Candidatos</h1><p class="sub">Transforme sinais em investigações. Recomendar investigação não exige tendência comprovada: a incerteza de cada produto é explicada.</p><div id="rc">${loading()}</div>`;
    let d, ds;
    try { [d, ds] = await Promise.all([api('/api/v081/candidatos'), api('/api/v081/descoberta')]); } catch (e) { $('#rc').innerHTML = errBox(e); return; }
    const by = {};
    d.itens.forEach((x) => { (by[x.estado] = by[x.estado] || []).push(x); });
    const ev = ds.avaliacao || {};
    $('#rc').innerHTML = `<div class="banner info small">${escH(d.aviso)}</div>
      <div class="kpis compact">${d.estados.map((s) => `<div class="kpi"><span>${escH(s)}</span><b>${(by[s] || []).length}</b></div>`).join('')}</div>
      ${d.estados.filter((s) => (by[s] || []).length).map((s) => `<details class="panel" ${['Investigação recomendada', 'Evidência comercial recorrente', 'Novo sinal'].includes(s) ? 'open' : ''}><summary><h2 style="display:inline">${escH(s)}</h2> <span class="badge">${by[s].length}</span></summary>
        ${tbl(['Produto', 'Mercado', 'Sinal', 'Evidência', 'Prioridade', 'Incerteza', 'Próxima ação', ''], by[s].map((x) => `<tr><td>${dl(x.produto_id, x.produto)}</td><td>${escH(x.mercado || '—')}</td><td class="small">${escH(x.sinal || '—')}</td><td>${escH(x.evidencia)}</td>
          <td class="num">${x.prioridade == null ? '—' : fmt(x.prioridade, 0)} <span class="muted small">${escH(x.prioridade_status)}</span></td><td class="small">${escH(x.incerteza)}</td><td class="small">${escH(x.proxima_acao)}</td>
          <td><button class="btn small" data-add="${escH(x.produto_id)}" data-name="${escH(x.produto)}">Investigar</button></td></tr>`))}</details>`).join('') || '<p class="muted">Nenhum candidato: colete sinais comerciais (Mercado Livre, pesquisa).</p>'}
      <div class="panel"><h2>Descoberta de produtos</h2><p class="small">Termos classificados: ${num(ds.termos_classificados)} — ${Object.entries(ds.por_classe || {}).map(([k, v]) => `${escH(k)} ${v}`).join(' · ')}.
        Avaliação em ${ev.casos} termos rotulados: acurácia ${ev.acuracia == null ? '—' : fmt(ev.acuracia * 100, 1) + '%'}, incorretos ${ev.taxa_incorreta == null ? '—' : fmt(ev.taxa_incorreta * 100, 1) + '%'}, precisão em produto físico ${ev.precision_produto_fisico == null ? '—' : fmt(ev.precision_produto_fisico * 100, 1) + '%'}.</p>
        ${tbl(['Termo', 'Classe', 'Família', 'Fontes', 'Obs.', 'Relevância'], (ds.candidatos || []).slice(0, 40).map((x) => `<tr><td>${x.produto_id ? dl(x.produto_id, x.termo) : escH(x.termo)}${x.novo_produto ? ' <span class="badge">novo?</span>' : ''}</td><td>${escH(x.classe)}</td><td>${escH(x.familia || '—')}</td><td class="small">${escH((x.fontes || []).join(', '))}</td><td class="num">${x.observacoes}</td><td class="num">${fmt(x.relevancia, 1)}</td></tr>`))}
        <p class="small muted">${escH(ds.regra || '')}</p></div>`;
    document.querySelectorAll('[data-add]').forEach((b) => { b.onclick = async () => {
      try { await post('/api/v08/investigacoes', { produto: b.dataset.name, produto_id: b.dataset.add, estado: 'Em observação', motivo: 'Radar de Candidatos' }); b.textContent = 'Na lista ✓'; b.disabled = true; } catch (e) { b.insertAdjacentHTML('afterend', errBox(e)); } }; });
  }

  /* ---------------------------------------------------------------- ALERTAS */
  async function pageAlerts() {
    main.innerHTML = `<h1>Alertas</h1><p class="sub">Comerciais, estatísticos e de qualidade — agrupados, recentes e com ação sugerida. Alertas não são oportunidades.</p><div id="al">${loading()}</div>`;
    const render = async (qs = '') => {
      let d;
      try { d = await api('/api/v081/alertas' + qs); } catch (e) { $('#al').innerHTML = errBox(e); return; }
      const f = d.filtros, sel = (k, l, opts) => `<label class="f">${l}<select name="${k}"><option value="">todos</option>${opts.map((o) => `<option ${new URLSearchParams(qs).get(k) === o ? 'selected' : ''}>${escH(o)}</option>`).join('')}</select></label>`;
      $('#al').innerHTML = `<div class="kpis compact">${['comercial', 'estatístico', 'qualidade'].map((k) => `<div class="kpi"><span>${k}</span><b>${d.contagem[k] || 0}</b></div>`).join('')}</div>
        <form id="alf" class="filters">${sel('categoria_alerta', 'Tipo de alerta', ['comercial', 'estatístico', 'qualidade'])}${sel('severidade', 'Severidade', ['alta', 'média', 'baixa'])}${sel('mercado', 'Mercado', f.mercado)}${sel('categoria', 'Categoria', f.categoria)}${sel('tipo', 'Evento', f.tipo)}${sel('fonte', 'Fonte', f.fonte)}<label class="f">Desde<input name="desde" type="date"></label><button class="btn">Filtrar</button></form>
        <p class="small muted">${escH(d.nota)} ${d.total} alerta(s).</p>
        ${tbl(['Sev.', 'Data', 'Produto', 'Tipo', 'Fonte', 'Motivo', 'Evidência', 'Ação sugerida'], d.itens.map((a) => `<tr><td><span class="cst ${SEV[a.severidade]}">${escH(a.severidade)}</span></td><td class="small">${escH(a.data || '—')}</td><td>${a.produto_id ? dl(a.produto_id, a.produto) : escH(a.produto)}</td><td class="small">${escH(a.categoria_alerta)} · ${escH(a.tipo)}${a.ocorrencias > 1 ? ` (${a.ocorrencias}×)` : ''}</td><td class="small">${escH(a.fonte || '—')}</td><td class="small">${escH(a.motivo)}</td><td class="small">${escH(a.evidencia || '')}</td><td class="small">${escH(a.acao)}</td></tr>`), 'Nenhum alerta com esses filtros.')}`;
      $('#alf').onsubmit = (ev) => { ev.preventDefault(); const p = new URLSearchParams([...new FormData(ev.target).entries()].filter(([, v]) => v)); render(p.toString() ? '?' + p : ''); };
    };
    render();
  }

  /* ---------------------------------------------------------------- DOSSIÊ: níveis, pontuação, regulamentação */
  const origDossier = PAGES['dossie'];
  async function pageDossier(pid) {
    await origDossier(pid);
    let p;
    try { p = await api('/api/v08/dossie/' + encodeURIComponent(pid)); } catch (e) { return; }
    if (!p.niveis) return;
    const L = (a) => `<ul class="small">${a.map((x) => `<li>${escH(x)}</li>`).join('')}</ul>`;
    const S = p.pontuacao || {};
    const SN = [['commercial_evidence', 'Evidência comercial'], ['momentum', 'Momentum'], ['persistence', 'Persistência'], ['cross_source_confirmation', 'Confirmação cruzada'],
      ['data_confidence', 'Confiança dos dados'], ['import_readiness', 'Prontidão para importação'], ['investigation_priority', 'Prioridade de investigação']];
    const sp = (p.evidencias || []).map((e) => `<tr><td class="small">${escH(e.indicador || e.metrica)} <span class="muted">(${escH(e.classe || '')} · ${escH(e.dimensao || '')})</span></td><td>${e.derivado && e.derivado.historico ? spark(e.derivado.historico.map((v) => v[1]), true) : spark(e.serie_valores)}</td></tr>`).join('');
    const box = document.createElement('div');
    box.innerHTML = `<div class="panel"><h2>Inteligência em três níveis</h2><div class="grid3">
        <div><h3>1 · Evidência observada</h3>${L(p.niveis.nivel1_evidencia_observada)}</div>
        <div><h3>2 · Análise estatística</h3>${L(p.niveis.nivel2_analise_estatistica)}</div>
        <div><h3>3 · Inteligência comercial</h3>${L(p.niveis.nivel3_inteligencia_comercial)}</div></div>
        <p class="small muted">Cada nível só usa o que o anterior sustenta: uma observação isolada não vira tendência.</p></div>
      <div class="grid2"><div class="panel"><h2>Pontuação (separada — não é probabilidade)</h2><table class="small">${SN.map(([k, t]) => S[k] ? `<tr title="${escH(S[k].como)}"><td>${t} ${tip(S[k].como)}</td><td class="num"><b>${num(S[k].valor, 0)}</b></td><td><span class="badge">${escH(S[k].status)}</span></td></tr>${S[k].motivo ? `<tr><td colspan="3" class="muted small" style="padding-top:0">${escH(S[k].motivo)}</td></tr>` : ''}` : '').join('')}</table><p class="small muted">${escH(S.aviso || '')}</p></div>
        <div class="panel"><h2>Evolução</h2><table class="small">${sp || '<tr><td class="muted">Sem séries.</td></tr>'}</table></div></div>
      <div class="panel"><h2>Regulamentação</h2><div id="dzreg">${loading('Consultando registros oficiais carregados…')}</div></div>`;
    const anchor = main.querySelector('.panel');
    anchor.parentNode.insertBefore(box, anchor.nextSibling);
    try {
      const r = await post('/api/regulatorio/pesquisar', { produto: (p.identificacao.nomes || {}).pt || p.identificacao.produto, orgao: 'Anatel' });
      const a = r.por_orgao[0] || {};
      $('#dzreg').innerHTML = a.mensagem && !r.resultados.length ? `<p class="small">${escH(a.mensagem)}</p>` :
        `<p class="small">${r.resultados.length} registro(s) relacionados na base oficial da Anatel (${r.empresas.titulares.length} titular(es), ${r.empresas.fabricantes.length} fabricante(s)) — ${r.resultados.filter((x) => x.vigente).length} vigente(s). Correspondência: produto SEMELHANTE (sem modelo informado).</p>
         <p class="small"><a href="#empresas-registros/${encodeURIComponent((p.identificacao.nomes || {}).pt || p.identificacao.produto)}">Ver empresas, modelos e situação →</a> · <a href="#conformidade-analisar">Analisar conformidade</a></p>`;
    } catch (e) { $('#dzreg').innerHTML = errBox(e); }
  }

  /* ---------------------------------------------------------------- PAÍS × PÚBLICO LINGUÍSTICO */
  const origConsumo = PAGES['consumo'];
  async function pageConsumo(cc) {
    await origConsumo(cc);
    let d;
    try { d = await api('/api/consumer/country/' + encodeURIComponent(cc || 'BR')); } catch (e) { return; }
    const b = document.createElement('div');
    b.className = 'banner info small';
    b.innerHTML = d.dimensao === 'público linguístico' ? `<b>Público linguístico — não é um país.</b> ${escH(d.aviso_dimensao)}`
      : `<b>Mercado geográfico: ${escH(d.nome)}.</b> Wikipédia por idioma fica em <a href="#consumo/${encodeURIComponent(d.publico_linguistico_relacionado || 'LANG:pt')}">públicos linguísticos</a> (atenção, não demanda).
         ${d.regional && d.regional.length ? `<br>Presença por UF/região no top 25 do Google Trends (BigQuery — presença, não volume): ${d.regional.slice(0, 8).map((r) => `${escH(r.product_id)} (${r.regioes.length} regiões)`).join('; ')}.` : ''}`;
    main.insertBefore(b, main.children[1] || null);
  }

  /* ---------------------------------------------------------------- ASSISTENTE META (Central de Integrações) */
  const origInteg = PAGES['integracoes'];
  async function pageIntegrations(arg) {
    await origInteg(arg);
    const box = document.createElement('details');
    box.className = 'panel';
    box.id = 'meta-assist';
    box.innerHTML = `<summary><h2 style="display:inline">Assistente de conexão Meta</h2> <span class="muted small">App ID, redirect HTTPS, domínio, login e permissões — verificados na Meta</span></summary><div id="ma">${loading('Carregando…')}</div>`;
    main.insertBefore(box, main.children[2] || null);
    if (arg === 'meta') box.open = true;
    const load = async () => {
      let r;
      try { r = await post('/api/integrations/meta/assistente', {}); } catch (e) { $('#ma').innerHTML = errBox(e); return; }
      $('#ma').innerHTML = `<p>Estado: <b>${escH(r.estado_rotulo)}</b>. <span class="small muted">${escH(r.aviso)}</span></p>
        <form id="maf" class="filters"><label class="f">Retorno do login<select name="modo">${Object.entries(r.modos).map(([k, t]) => `<option value="${k}" ${k === r.modo ? 'selected' : ''}>${escH(t)}</option>`).join('')}</select></label><button class="btn">Salvar</button></form>
        <p class="small">URL a cadastrar na Meta (Login do Facebook → Configurações → URIs de redirecionamento do OAuth válidos): <code>${escH(r.redirect_uri)}</code> · App ID que o GPI enviará: <code>${escH(r.app_id_enviado || '—')}</code></p>
        ${r.checklist ? `<table class="small"><thead><tr><th>#</th><th>Etapa</th><th>Status</th><th>Resultado</th><th>Possível causa / ação</th></tr></thead><tbody>${r.checklist.map((s) => `<tr><td class="num">${s.etapa}</td><td><b>${escH(s.nome)}</b><br><span class="muted">${escH(s.descricao)}</span></td><td>${s.status === 'ok' ? '✓ ok' : s.status === 'falhou' ? '✗ falhou' : s.status === 'pendente' ? '… pendente' : '? não verificado'}</td><td>${escH(s.resultado || '—')}</td><td>${escH(s.possivel_causa || '')}${s.acao ? `<br><span class="muted">Ação: ${escH(s.acao)}</span>` : ''}</td></tr>`).join('')}</tbody></table>
        <p class="small muted">A integração só é considerada validada quando o GPI troca o código, confere o token nesta Meta e uma consulta real (/me) responde — a tela “Continuar como …” do Facebook não basta.</p>`
        : `<ol class="small">${r.etapas.map((s) => `<li>${s.ok === true ? '✓' : s.ok === false ? '✗' : '?'} <b>${escH(s.nome)}</b> — ${escH(s.mensagem)}${s.acao ? `<br><span class="muted">Ação: ${escH(s.acao)}</span>` : ''}</li>`).join('')}</ol>`}
        <div class="btnrow">${Object.entries(r.modulos).map(([k, m]) => { const locked = k !== 'basico' && !(r.checklist && r.checklist[9].status === 'ok'); return `<button class="btn small" data-mod="${k}" ${locked ? 'disabled title="Conclua e valide o Login básico primeiro"' : ''}>Conectar — ${escH(m.nome)}</button>`; }).join('')} <button class="btn small" id="marec">Verificar de novo</button></div>
        <p class="small muted">${escH(r.anuncios.nota)}</p>
        <form id="mapaste" class="filters"><label class="f">Se o navegador não voltar ao GPI, cole o código exibido na página de retorno<input name="colado" size="60"></label><button class="btn small">Concluir</button></form><p id="mamsg" class="small"></p>`;
      $('#maf').onsubmit = async (ev) => { ev.preventDefault(); try { await post('/api/integrations/meta/redirect', Object.fromEntries(new FormData(ev.target))); load(); } catch (e) { $('#mamsg').innerHTML = errBox(e); } };
      $('#marec').onclick = load;
      document.querySelectorAll('[data-mod]').forEach((b) => { b.onclick = async () => {
        try { const s = await post('/api/integrations/meta/oauth/start', { modulo: b.dataset.mod }); window.open(s.url, '_blank', 'noopener'); $('#mamsg').textContent = `Login aberto em nova aba (App ID ${s.app_id_enviado}, retorno ${s.redirect_uri}). Depois volte e clique em “Verificar de novo”.`; } catch (e) { $('#mamsg').innerHTML = errBox(e); } }; });
      $('#mapaste').onsubmit = async (ev) => { ev.preventDefault(); try { const x = await post('/api/oauth/meta/concluir', Object.fromEntries(new FormData(ev.target))); $('#mamsg').textContent = 'Token conferido para o app ' + (x.app_id || '') + ' — permissões: ' + (x.escopos || 'perfil público') + '. Validando consulta real…'; load(); } catch (e) { $('#mamsg').innerHTML = errBox(e); } };
    };
    box.addEventListener('toggle', () => { if (box.open && !box.dataset.ok) { box.dataset.ok = 1; load(); } });
    if (box.open) { box.dataset.ok = 1; load(); }
  }

  return { 'dashboard': pageDashboard, 'inteligencia-oportunidades': pageRadar, 'alertas': pageAlerts, 'dossie': pageDossier,
    'consumo': pageConsumo, 'integracoes': pageIntegrations };
};
