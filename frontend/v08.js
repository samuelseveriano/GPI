/* GPI v0.8 — dashboard orientado à decisão, Product Intelligence Dossier, Qualidade dos Dados, Empresas com Produtos
   Homologados/Registrados e Lista de Investigação. Todos os números vêm do backend (resultado único "intel08"). */
window.GPI_V08 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, errBox, main, $ } = H;
  const pct = (v) => v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v * 100, 0)}%`;
  const num = (v, d = 0) => v == null ? '—' : fmt(v, d);
  const dl = (pid, name) => `<a href="#dossie/${encodeURIComponent(pid)}">${escH(name || pid)}</a>`;
  const SIT = { 'NOVO SINAL COMERCIAL': 'cst2', 'EMERGENTE': 'cst2', 'SINAL EM OBSERVAÇÃO': 'cst5', 'INTERESSE RECORRENTE': 'cst4',
    'SINAL INTERMITENTE': 'cst5', 'CRESCIMENTO CONSISTENTE': 'cst4', 'ACELERAÇÃO': 'cst1', 'ESTÁVEL': 'cst3', 'SAZONAL': 'cst5',
    'POSSÍVEL SATURAÇÃO': 'cst2', 'VARIAÇÃO NÃO CONFIRMADA': 'cst3', 'DECLÍNIO': 'cst3', 'ATENÇÃO PÚBLICA EM ALTA': 'cst5',
    'EVIDÊNCIA INSUFICIENTE': 'cst3' };
  const sit = (s) => `<span class="cst ${SIT[s] || 'cst3'}">${escH(s)}</span>`;
  const IDX = [['search_interest_index', 'Interesse de pesquisa'], ['commercial_intent_index', 'Sinais comerciais'],
    ['public_attention_index', 'Atenção pública'], ['evidence_coverage', 'Cobertura de evidências'],
    ['forecast_confidence', 'Confiança da previsão'], ['opportunity_score', 'Prioridade de investigação'], ['import_readiness', 'Prontidão para importação']];
  const tbl = (head, rows, empty) => rows.length ? `<div class="scroll"><table class="small"><thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`
    : `<p class="muted small">${escH(empty || 'Nada a mostrar com os dados atuais.')}</p>`;

  /* ------------------------------------------------------------------ DASHBOARD (seção 14) */
  async function pageDashboard() {
    main.innerHTML = `<h1>Dashboard</h1><p class="sub">Quais produtos estão ganhando procura e quais merecem investigação — com a evidência de cada conclusão.</p><div id="d8">${loading('Consolidando evidências…')}</div>`;
    let d;
    try { d = await api('/api/v08/visao'); } catch (e) { $('#d8').innerHTML = errBox(e); return; }
    const k = d.kpis;
    const kp = [['Produtos monitorados', k.produtos_monitorados], ['Com dados recentes', k.produtos_com_dados_recentes],
      ['Com interesse comercial', k.com_interesse_comercial], ['Emergentes / novos sinais', k.emergentes],
      ['Crescimento consistente', k.crescimento_consistente], ['Em investigação', k.em_investigacao],
      ['Fontes funcionais', k.fontes_funcionais], ['Cobertura real', `${fmt(k.cobertura_real, 0)}%`]];
    const rank = (rows) => tbl(['Produto', 'País', 'Indicador', 'Crescimento', 'Persistência', 'Fontes', 'Confiança', 'Situação', 'Próxima ação'],
      rows.map((r) => `<tr><td>${dl(r.produto_id, r.produto)}</td><td>${escH(r.pais || '—')}</td><td>${escH(r.indicador || '—')}</td>
        <td class="num">${pct(r.crescimento)}</td><td class="num">${r.persistencia == null ? '—' : fmt(r.persistencia * 100, 0) + '%'}</td>
        <td class="num" title="${escH((r.fontes_nomes || []).join(', '))}">${r.fontes}</td><td>${escH(r.confianca)}</td><td>${sit(r.situacao)}</td>
        <td class="small">${escH(r.proxima_acao)}${r.motivo_nivel ? `<br><span class="muted">em observação: ${escH(r.motivo_nivel)}</span>` : ''}</td></tr>`),
      'Nenhum produto reúne, por enquanto, evidência suficiente. Os critérios não são reduzidos para preencher a lista.');
    const RAD = [['crescimento confirmado por fontes independentes', 'Crescimento confirmado por fontes independentes'],
      ['crescimento observado', 'Crescimento observado'], ['interesse recorrente', 'Interesse recorrente'], ['primeira observação', 'Primeira observação']];
    const plist = (l) => l.length ? `<ul class="small">${l.map((p) => `<li>${dl(p.produto_id, p.produto)} — ${sit(p.situacao)} <span class="muted">${escH((p.fontes || []).join(', '))}</span></li>`).join('')}</ul>` : '<p class="muted small">Nenhum produto.</p>';
    $('#d8').innerHTML = `<div class="banner info small">${escH(d.aviso)} Atualizado em ${escH(k.ultima_atualizacao || d.gerado_em || '—')}.
      Qualidade: ${Object.entries(d.gates).map(([g, s]) => `Gate ${g} <b>${escH(s)}</b>`).join(' · ')} — <a href="#qualidade-dados">detalhes</a>.</div>
      <h2>1. Visão executiva</h2><div class="kpis">${kp.map(([t, v]) => `<div class="kpi"><span>${escH(t)}</span><b>${escH(v)}</b></div>`).join('')}</div>
      <p class="small muted">${escH(k.cobertura_real_nota)}.</p>
      <div class="panel"><h2>2. Top produtos para investigar</h2>${rank(d.top_investigar)}
        ${d.em_observacao.length ? `<details><summary>Sinais interessantes ainda insuficientes (${d.em_observacao.length})</summary>${rank(d.em_observacao)}</details>` : ''}</div>
      <div class="panel"><h2>3. Radar comercial</h2><p class="small muted">Mercado Livre e outras fontes de demanda. Wikipédia e notícias não contam como confirmação.</p>
        <div class="grid2">${RAD.map(([key, t]) => `<div><h3>${escH(t)}</h3>${plist(d.radar[key] || [])}</div>`).join('')}</div></div>
      <div class="grid2"><div class="panel"><h2>4. Tendências emergentes</h2><p class="small muted">Sinais iniciais — não são tendência confirmada.</p>${plist(d.emergentes)}</div>
        <div class="panel"><h2>5. Tendências consistentes</h2><p class="small muted">Histórico suficiente e tendência significativa ou presença recorrente.</p>${plist(d.consistentes)}</div></div>
      <div class="panel"><h2>6. Alertas</h2><p class="small muted">Mudanças de patamar, anomalias, reversões, declínio e qualidade dos dados. Alertas não são oportunidades.</p>
        ${tbl(['Tipo', 'Produto', 'Fonte', 'Quando / detalhe'], d.alertas.map((a) => `<tr><td>${escH(a.tipo)}</td><td>${a.produto_id ? dl(a.produto_id, a.produto) : escH(a.produto)}</td><td>${escH(a.fonte || '—')}</td><td class="small">${escH(a.quando || (a.detalhe && typeof a.detalhe === 'object' ? `tendência de ${a.detalhe.de} passou para ${a.detalhe.para} (inclinação ${fmt(a.detalhe.inclinacao_anterior * 100, 1)}%/mês → ${fmt(a.detalhe.inclinacao_recente * 100, 1)}%/mês)` : a.detalhe) || '')}</td></tr>`), 'Sem alertas.')}</div>
      <div class="panel"><h2>7. Comparação internacional</h2>${d.comparacao_internacional.length ? tbl(['Produto', 'Indicador (fonte)', 'Mercado A', 'Variação', 'Mercado B', 'Variação', 'Nota'],
        d.comparacao_internacional.map((c) => `<tr><td>${dl(c.produto_id, c.produto)}</td><td>${escH(c.indicador)} (${escH(c.fonte)})</td><td>${escH(c.mercado_a)}</td><td class="num">${pct(c.variacao_a)}</td><td>${escH(c.mercado_b)}</td><td class="num">${pct(c.variacao_b)}</td><td class="small muted">${escH(c.nota)}</td></tr>`))
        : '<p class="muted small">Sem dados comparáveis: exige a mesma fonte e métrica com série elegível nos dois mercados.</p>'}</div>
      <div class="panel"><h2>8. Insights do GPI</h2>${d.insights.length ? d.insights.map((i) => `<details><summary>${dl(i.produto_id, i.produto)} — ${sit(i.situacao)} <span class="muted small">confiança ${escH(i.confianca)}</span></summary>
        <dl class="small"><dt>O que aconteceu?</dt><dd>${escH(i.perguntas.o_que_aconteceu)}</dd><dt>Qual é a evidência?</dt><dd>${escH(i.perguntas.qual_a_evidencia)}</dd>
        <dt>O que isso significa?</dt><dd>${escH(i.perguntas.o_que_significa)}</dd><dt>Qual é a incerteza?</dt><dd>${escH(i.perguntas.qual_a_incerteza)}</dd>
        <dt>O que investigar agora?</dt><dd>${escH(i.perguntas.o_que_investigar)}</dd></dl>
        <p class="small muted">Método: ${escH(i.metodo)} · ${escH(i.gerado_por)} · observações: ${(i.observacoes_ids || []).length} de ${i.observacoes_total ?? '—'}</p></details>`).join('')
        : '<p class="muted small">Sem insights: colete dados de pesquisa ou ranking comercial.</p>'}</div>`;
  }

  /* ------------------------------------------------------------------ DOSSIÊ (seção 15) */
  async function pageDossier(pid) {
    main.innerHTML = `<p><a href="#dashboard">← Dashboard</a></p><div id="dz">${loading('Montando o dossiê…')}</div>`;
    let p;
    try { p = await api('/api/v08/dossie/' + encodeURIComponent(pid)); } catch (e) { $('#dz').innerHTML = errBox(e); return; }
    if (!p.identificacao) { $('#dz').innerHTML = `<h1>${escH(pid)}</h1><div class="banner">${escH(p.mensagem)}</div>`; return; }
    const id = p.identificacao, ins = p.insight || {};
    const ev = p.evidencias || [];
    const byType = {};
    ev.forEach((e) => { (byType[e.tipo_rotulo || 'Outros'] = byType[e.tipo_rotulo || 'Outros'] || []).push(e); });
    const elig = (e) => Object.entries(e.elegibilidade || {}).map(([m, ok]) => `${ok ? '✓' : '✗'} ${m}`).join(' · ');
    const evRow = (e) => {
      const d = e.derivado || {};
      const det = e.metrica === 'posicao_tendencia' ? `${d.semanas_presente}/${d.semanas_coletadas} semanas · melhor ${num(d.melhor_posicao)} · média ${num(d.posicao_media, 1)} · ${escH(d.classe || '')}`
        : e.frequencia === 'dia' ? `${num(d.dias_em_alta_30d)} dia(s) em alta em 30 dias`
          : `momentum ${pct(d.momentum)}${d.atencao_relativa != null ? ` · relativo à coorte ${pct(d.atencao_relativa)}` : ''} · persistência ${d.persistencia == null ? '—' : fmt(d.persistencia * 100, 0) + '%'} · volatilidade ${num(d.volatilidade, 2)}${d.reversao ? ' · possível reversão' : ''}`;
      return `<tr><td>${escH(e.indicador || e.metrica)}</td><td>${escH(e.fonte_nome)}</td><td>${escH(e.mercado)}</td><td class="small">${escH(e.periodo)}</td>
        <td class="num">${num(e.observacoes_n)}</td><td class="small">${det}</td><td class="small muted">${escH(elig(e))}</td>
        <td class="small">${e.previsto ? `${escH(e.previsto.modelo)}${e.previsto.baseline_selecionado ? ' (baseline)' : ''} · WAPE ${pct((e.previsto.metricas || {}).wape).replace('+', '')}` : escH(e.previsao_bloqueada || (e.motivos_inelegibilidade || {}).previsao || '—')}</td></tr>`;
    };
    $('#dz').innerHTML = `<h1>${escH(id.produto)}</h1>
      <p class="sub">${escH(id.categoria || '—')} › ${escH(id.familia || '—')}${id.variante ? ' › ' + escH(id.variante) : ''} ${sit(p.situacao)} ${p.cluster ? `<span class="badge">${escH(p.cluster)}</span>` : ''}</p>
      <p class="small muted">${escH(p.definicao_situacao)}</p>
      <div class="panel"><h2>Importação</h2><div class="btnrow">
        <a class="btn" href="#conformidade-analisar">Analisar conformidade</a>
        <a class="btn" href="#empresas-registros/${encodeURIComponent(id.nomes.pt || id.produto)}">Consultar homologações</a>
        <a class="btn" href="#empresas-registros/${encodeURIComponent(id.nomes.pt || id.produto)}">Pesquisar empresas registradas</a>
        <a class="btn" href="#conformidade-historico">Gerar checklist técnico</a>
        <button class="btn" id="addinv">${p.investigacao ? 'Na investigação: ' + escH(p.investigacao.estado) : 'Adicionar à investigação'}</button>
        <button class="btn" id="exprep">Exportar relatório</button></div><p id="dzmsg" class="small"></p></div>
      <div class="grid2"><div class="panel"><h2>Identificação</h2><dl class="small"><dt>Produto</dt><dd>${escH(id.produto)}</dd><dt>Categoria / família</dt><dd>${escH(id.categoria || '—')} / ${escH(id.familia || '—')}</dd>
        <dt>Variante</dt><dd>${escH(id.variante || '—')}</dd><dt>Marca / modelo</dt><dd>${escH(id.marca || '—')} / ${escH(id.modelo || '—')}</dd>
        <dt>Especificações</dt><dd>${escH(JSON.stringify(id.especificacoes || {}))}</dd><dt>Nomes</dt><dd>${escH(id.nomes.pt || '')} · ${escH(id.nomes.en || '')} · ${escH(id.nomes.zh || '')}</dd>
        <dt>Correspondência dos termos</dt><dd>${p.correspondencia && p.correspondencia.termos ? `${fmt((p.correspondencia.fracao_confirmada || 0) * 100, 0)}% de ${p.correspondencia.termos} termo(s) confirmados` : '—'}</dd></dl></div>
        <div class="panel"><h2>Índices (separados — não são probabilidade)</h2><table class="small wrap">${IDX.map(([key, t]) => `<tr><td>${escH(t)}</td><td class="num"><b>${num((p.indices || {})[key], 0)}</b></td><td class="muted small">${escH((p.indices_motivos || {})[key] || '')}</td></tr>`).join('')}</table>
        <p class="small">Confirmação por fontes independentes: <b>${p.confirmacao_cruzada.confirmado ? 'sim' : 'não'}</b> ${escH((p.confirmacao_cruzada.fontes_independentes_positivas || []).join(', '))}. <span class="muted">${escH(p.confirmacao_cruzada.nota)}</span></p></div></div>
      <div class="panel"><h2>Inteligência comercial</h2><dl class="small"><dt>O que aconteceu?</dt><dd>${escH((ins.perguntas || {}).o_que_aconteceu)}</dd><dt>Principais evidências</dt><dd>${escH(ins.evidencia)}</dd>
        <dt>Interpretação</dt><dd>${escH(ins.interpretacao)}</dd><dt>Incerteza</dt><dd>${escH((ins.perguntas || {}).qual_a_incerteza)}</dd><dt>Riscos e alertas</dt><dd>${(p.alertas || []).map((a) => escH(a.tipo + (a.quando ? ' (' + a.quando + ')' : ''))).join('; ') || 'nenhum'}</dd>
        <dt>Limitações</dt><dd>${(ins.limitacoes || []).map(escH).join(' ')}</dd><dt>Próxima investigação</dt><dd><b>${escH(p.proxima_acao)}</b></dd></dl></div>
      <div class="panel"><h2>Mercado e histórico — evidências por tipo</h2>${Object.entries(byType).map(([t, l]) => `<h3>${escH(t)} <span class="muted small">${escH((l[0] || {}).nao_e || '')}</span></h3>
        ${tbl(['Indicador', 'Fonte', 'Mercado', 'Período', 'Obs.', 'Indicadores derivados', 'Métodos elegíveis', 'Previsão'], l.map(evRow))}`).join('') || '<p class="muted">Sem evidências.</p>'}</div>
      <details class="panel"><summary>Linhagem dos dados (observações que fundamentam o dossiê)</summary><p class="small muted">${escH((p.linhagem || {}).consulta || '')} — ${(p.linhagem || {}).total ?? 0} observação(ões)</p>
        <pre class="small">${escH(((ins.observacoes_ids || []).concat((p.linhagem || {}).ids || [])).slice(0, 40).join('\n'))}</pre></details>`;
    $('#addinv').onclick = async () => {
      try { const r = await post('/api/v08/investigacoes', { produto: id.produto, produto_id: p.produto_id, estado: 'Novo sinal', motivo: p.definicao_situacao, evidencias: ins.evidencia ? [ins.evidencia] : [], fontes: p.fontes, proximas_acoes: [p.proxima_acao] });
        $('#dzmsg').innerHTML = `Na lista de investigação (${escH(r.estado)}). <a href="#investigacoes">Abrir lista</a>`; } catch (e) { $('#dzmsg').innerHTML = errBox(e); }
    };
    $('#exprep').onclick = async () => {
      try { const r = await post('/api/reports/generate', { tipo: 'produto', formato: 'pdf', filtros: { produto: p.produto_id } });
        $('#dzmsg').innerHTML = r.status === 'gerado' ? `<a href="/api/reports/${r.id}/download">Baixar relatório do produto (PDF)</a>` : errBox(r.erro || 'falha'); } catch (e) { $('#dzmsg').innerHTML = errBox(e); }
    };
  }

  /* ------------------------------------------------------------------ QUALIDADE DOS DADOS (gates) */
  async function pageQuality() {
    main.innerHTML = `<h1>Qualidade dos Dados</h1><p class="sub">Gates obrigatórios entre coleta, análise e modelagem. Dados reprovados não entram nos modelos.</p><div id="q8">${loading('Executando os gates…')}</div>`;
    let d, m;
    try { [d, m] = await Promise.all([api('/api/v08/qualidade'), api('/api/v08/metricas')]); } catch (e) { $('#q8').innerHTML = errBox(e); return; }
    const g = d.gates;
    const chk = (l) => tbl(['Verificação', 'Resultado', 'Detalhe'], (l || []).map((c) => `<tr><td>${escH(c.verificacao)}</td><td>${c.ok ? '✓' : (c.severidade === 'alerta' ? '⚠ alerta' : '✗')}</td><td class="small">${escH(c.detalhe || '')}</td></tr>`));
    const t2 = g['2'] ? g['2'].avaliacao_teste : null;
    $('#q8').innerHTML = `<div class="kpis">${Object.entries(g).map(([k, v]) => `<div class="kpi"><span>Gate ${k} — ${escH(v.nome)}</span><b>${escH(v.status)}</b></div>`).join('')}</div>
      <div class="panel"><h2>Gate 1 — Integridade</h2>${chk(g['1'].verificacoes)}${g['1'].excluidos_da_modelagem.length ? `<p class="banner small">Fora da modelagem: ${escH(g['1'].excluidos_da_modelagem.join(', '))}</p>` : ''}</div>
      <div class="panel"><h2>Gate 2 — Identificação de produtos</h2>${t2 ? `<p class="small">Conjunto de TESTE rotulado manualmente (nunca usado para ajustar regras): ${t2.casos} casos · precision <b>${fmt(t2.precision * 100, 1)}%</b> · recall ${fmt(t2.recall * 100, 1)}% · F1 ${fmt(t2.f1 * 100, 1)}% · associações incorretas ${fmt(t2.taxa_incorreta * 100, 1)}% · abstenção ${fmt(t2.taxa_abstencao * 100, 1)}%. Metas: precision ≥ ${fmt(g['2'].metas.precision * 100, 0)}%, incorretas ≤ ${fmt(g['2'].metas.taxa_incorreta * 100, 0)}%.</p>
        ${tbl(['Grupo', 'Casos', 'Corretos', 'Incorretos', 'Abstenções'], Object.entries(t2.por_grupo).map(([k, v]) => `<tr><td>${escH(k)}</td><td>${v.casos}</td><td>${v.corretos}</td><td>${v.incorretos}</td><td>${v.abstencoes}</td></tr>`))}
        <p class="small">Associações gravadas reavaliadas: ${escH(JSON.stringify(g['2'].associacoes_gravadas.por_estado))} · YouTube: ${escH(JSON.stringify(g['2'].youtube.por_estado))}</p>
        ${g['2'].associacoes_gravadas.baixa_confianca.length ? `<details><summary>Termos com correspondência não confirmada (${g['2'].associacoes_gravadas.n_baixa_confianca})</summary>${tbl(['Termo', 'Produto gravado', 'Estado', 'Motivo'], g['2'].associacoes_gravadas.baixa_confianca.map((x) => `<tr><td>${escH(x.termo)}</td><td>${escH(x.produto_gravado)}</td><td>${escH(x.estado)}</td><td class="small">${escH(x.motivos.join('; '))}</td></tr>`))}</details>` : ''}` : ''}</div>
      <div class="panel"><h2>Gate 3 — Semântica das fontes</h2>${chk(g['3'].verificacoes)}</div>
      <div class="panel"><h2>Gate 4 — Elegibilidade estatística</h2><p class="small">${g['4'].series} série(s): ${Object.entries(g['4'].elegiveis).map(([k, v]) => `${escH(k)} ${v}`).join(' · ')}</p>
        ${Object.entries(g['4'].motivos_principais).filter(([, v]) => v.length).map(([k, v]) => `<p class="small"><b>${escH(k)}</b> não elegível: ${v.map(([r, n]) => `${escH(r)} (${n})`).join('; ')}</p>`).join('')}</div>
      <div class="panel"><h2>Gate 6 — Interpretação · Gate 8 — Consistência fim a fim</h2>${chk((g['8'] || {}).verificacoes)}</div>
      <div class="panel"><h2>Fontes elegíveis por indicador</h2><p class="small muted">Por que algumas fontes com dados não aparecem em certos indicadores.</p>
        ${d.fontes_por_indicador.map((x) => `<h3>${escH(x.nome)} <span class="muted small">${escH(x.descricao)}</span></h3><p class="small">Elegíveis: ${x.fontes_elegiveis.map((e) => `${escH(e.nome)} (${num(e.registros)})`).join(', ') || '—'}</p>
          ${x.fontes_nao_elegiveis.length ? `<p class="small muted">Não elegíveis: ${x.fontes_nao_elegiveis.map((e) => `${escH(e.nome)} — ${escH(e.motivo)}`).join('; ')}</p>` : ''}`).join('')}</div>
      <div class="panel"><h2>Catálogo semântico de métricas</h2>${tbl(['Métrica', 'Tipo', 'Unidade', 'Frequência', 'Não é…', 'Modelagem', 'Índices'],
        m.metricas.map((x) => `<tr><td>${escH(x.nome_comercial)}<br><span class="muted small">${escH(x.metrica)}</span></td><td>${escH(x.tipo_rotulo)}</td><td class="small">${escH(x.unidade)}</td><td>${escH(x.frequencia)}</td><td class="small">${escH(x.nao_e)}</td><td>${x.modelagem ? 'sim' : 'não'}</td><td class="small">${escH(x.indices.join(', ') || '—')}</td></tr>`))}
        <p class="small muted">${escH(m.regra)}</p></div>`;
  }

  /* ------------------------------------------------------------------ EMPRESAS COM PRODUTOS HOMOLOGADOS (seções 16–20) */
  async function pageRegistry(term) {
    main.innerHTML = `<h1>Empresas com Produtos Homologados ou Registrados</h1><p class="sub">Registros oficiais da Anatel e do Inmetro: titulares, fabricantes, modelos e situação. Registro semelhante não comprova nada para outro produto.</p><div id="rg">${loading()}</div>`;
    let st;
    try { st = await api('/api/regulatorio/status'); } catch (e) { $('#rg').innerHTML = errBox(e); return; }
    const F = [['produto', 'Produto'], ['marca', 'Marca'], ['modelo', 'Modelo'], ['fabricante', 'Fabricante'], ['titular', 'Empresa/titular'], ['cnpj', 'CNPJ'],
      ['numero', 'Número do registro'], ['tipo', 'Tipo/categoria'], ['situacao', 'Situação'], ['de', 'De (AAAA-MM-DD)'], ['ate', 'Até']];
    $('#rg').innerHTML = `<div class="grid2"><div class="panel small"><b>Anatel</b> — ${st.anatel.carregada ? `${fmt(st.anatel.registros)} registros oficiais carregados em ${escH(st.anatel.carregada_em)}` : 'base oficial não carregada: use <a href="#conformidade-certificados">Homologações e Certificados → Atualizar dados da Anatel</a>'} · <a href="${escH(st.anatel.consulta_oficial)}" target="_blank" rel="noopener">consulta oficial</a></div>
        <div class="panel small"><b>Inmetro</b> — ${st.inmetro.carregada ? `${fmt(st.inmetro.registros)} registros do arquivo ${escH(st.inmetro.arquivo)}` : escH(st.inmetro.nota)} · <a href="${escH(st.inmetro.consulta_oficial)}" target="_blank" rel="noopener">consulta oficial</a>
          <form id="inmf"><input type="file" name="arquivo" accept=".csv,.txt"> <button class="btn">Importar arquivo oficial</button></form></div></div>
      <div class="panel"><form id="rgf" class="filters">${F.map(([k, t]) => `<label class="f">${t}<input name="${k}" value="${k === 'produto' && term ? escH(term) : ''}"></label>`).join('')}
        <label class="f">Órgão<select name="orgao"><option value="todos">Anatel e Inmetro</option><option>Anatel</option><option>Inmetro</option></select></label><button class="btn">Pesquisar</button> <button type="button" class="btn" id="rgrep">Relatório (PDF)</button></form><div id="rgres"></div></div>
      <div class="panel"><h2>Comparar produto com registro existente</h2><form id="cmpf" class="filters">${[['marca', 'Marca'], ['modelo', 'Modelo'], ['fabricante', 'Fabricante'], ['potencia', 'Potência'], ['tensao', 'Tensão'], ['frequencia', 'Frequência'], ['tecnologia', 'Tecnologia'], ['comunicacao_sem_fio', 'Comunicação sem fio'], ['componentes', 'Componentes'], ['certificado', 'Certificado informado pelo fornecedor']].map(([k, t]) => `<label class="f">${t}<input name="${k}"></label>`).join('')}<button class="btn">Comparar</button></form><div id="cmpres"></div></div>
      <details class="panel"><summary><h2 style="display:inline">Registrar consulta manual assistida</h2></summary><p class="small">Para fontes que não permitem consulta automatizada. Registre exatamente o que viu na consulta oficial.</p>
        <form id="manf" class="filters"><label class="f">Órgão<select name="orgao"><option>Anatel</option><option>Inmetro</option></select></label><label class="f">Endereço da consulta oficial<input name="fonte_url" value="${escH(st.inmetro.consulta_oficial)}"></label>
          <label class="f">Data<input name="data_consulta" placeholder="AAAA-MM-DD"></label><label class="f">Número do registro<input name="numero_registro"></label>
          <label class="f">Resultado<select name="resultado"><option value="encontrado_exato">encontrado — modelo exato</option><option value="encontrado_provavel">encontrado — provável</option><option value="encontrado_semelhante">encontrado — semelhante</option><option value="nao_encontrado">não encontrado</option><option value="fonte_indisponivel">fonte indisponível</option><option value="inconclusivo">inconclusivo</option></select></label>
          <label class="f">Informações obtidas<input name="info"></label><label class="f">Responsável<input name="responsavel"></label><button class="btn">Registrar</button></form><p id="manmsg" class="small"></p></details>`;
    const form = (f) => Object.fromEntries([...new FormData(f).entries()].filter(([, v]) => v));
    const show = (r) => {
      const res = r.resultados;
      $('#rgres').innerHTML = `${r.por_orgao.map((p) => p.mensagem ? `<p class="banner small">${escH(p.orgao)}: ${escH(p.mensagem)}</p>` : '').join('')}
        ${tbl(['Empresa', 'Papel', 'Fabricante', 'Marca', 'Modelo', 'Registro', 'Situação', 'Correspondência', 'Fonte'], r.empresas.tabela.slice(0, 300).map((x) => `<tr><td>${escH(x.empresa)}${x.cnpj ? `<br><span class="muted small">${escH(x.cnpj)}</span>` : ''}</td><td>${escH(x.papel)}</td><td>${escH(x.fabricante || '—')}</td><td>${escH(x.marca)}</td><td>${escH(x.modelo || '—')}</td><td>${escH(x.registro || '—')}</td><td>${escH(x.situacao || '—')}</td><td>${escH(x.correspondencia)}</td><td class="small">${escH(x.fonte)}</td></tr>`), 'Nenhum registro.')}
        ${res.length ? `<div class="grid2"><div><h3>Titulares (${r.empresas.titulares.length})</h3>${tbl(['Empresa', 'Registros', 'Modelos'], r.empresas.titulares.slice(0, 15).map((t) => `<tr><td>${escH(t.empresa)}</td><td>${t.registros}</td><td>${t.modelos}</td></tr>`))}</div>
          <div><h3>Fabricantes (${r.empresas.fabricantes.length})</h3>${tbl(['Fabricante', 'Registros', 'Países'], r.empresas.fabricantes.slice(0, 15).map((f) => `<tr><td>${escH(f.fabricante)}</td><td>${f.registros}</td><td class="small">${escH(Object.keys(f.paises).join(', '))}</td></tr>`))}</div></div>` : ''}
        <p class="small muted">${r.empresas.avisos.map(escH).join(' ')} ${r.limitacoes.map(escH).join(' ')}</p>`;
    };
    $('#rgf').onsubmit = async (ev) => { ev.preventDefault(); $('#rgres').innerHTML = loading('Pesquisando registros oficiais…'); try { show(await post('/api/regulatorio/pesquisar', form(ev.target))); } catch (e) { $('#rgres').innerHTML = errBox(e); } };
    $('#rgrep').onclick = async () => { try { const r = await post('/api/reports/generate', { tipo: 'homologacoes', formato: 'pdf', filtros: form($('#rgf')) }); $('#rgres').insertAdjacentHTML('afterbegin', r.status === 'gerado' ? `<p><a href="/api/reports/${r.id}/download">Baixar relatório de homologações (PDF)</a></p>` : errBox(r.erro || 'falha')); } catch (e) { $('#rgres').insertAdjacentHTML('afterbegin', errBox(e)); } };
    $('#cmpf').onsubmit = async (ev) => {
      ev.preventDefault(); $('#cmpres').innerHTML = loading();
      try { const r = await post('/api/regulatorio/comparar', { especificacao: form(ev.target) });
        $('#cmpres').innerHTML = r.mensagem ? `<p class="banner small">${escH(r.mensagem)}</p>` : r.comparacoes.map((c) => `<div class="panel small"><b>${escH(c.rotulo)}</b> — registro ${escH(c.registro || '—')} (${escH(c.fonte)}) · ${escH(c.motivo)}
          <p>Coincidentes: ${c.coincidentes.map((x) => escH(x.caracteristica)).join(', ') || '—'} · Diferentes: ${c.diferentes.map((x) => `${escH(x.caracteristica)} (${escH(x.informado)} × ${escH(x.registro)})`).join(', ') || '—'} · Faltantes: ${c.faltantes.map((x) => escH(x.caracteristica)).join(', ') || '—'}</p>
          <p class="muted">${escH(c.conclusao)}</p></div>`).join(''); } catch (e) { $('#cmpres').innerHTML = errBox(e); }
    };
    $('#manf').onsubmit = async (ev) => { ev.preventDefault(); const d = form(ev.target); d.informacoes = { texto: d.info || '' }; delete d.info;
      try { const r = await post('/api/regulatorio/consultas', d); $('#manmsg').textContent = `Consulta registrada (nº ${r.id}).`; } catch (e) { $('#manmsg').innerHTML = errBox(e); } };
    $('#inmf').onsubmit = async (ev) => { ev.preventDefault();
      try { const r = await api('/api/regulatorio/inmetro/arquivo', { method: 'POST', body: new FormData(ev.target) }); alertBox(`${r.registros} registros importados; colunas reconhecidas: ${r.colunas_reconhecidas.join(', ')}`); pageRegistry(term); } catch (e) { alertBox(e.message); } };
    const alertBox = (t) => $('#rg').insertAdjacentHTML('afterbegin', `<div class="banner info small">${escH(t)}</div>`);
    if (term) $('#rgf').requestSubmit();
  }

  /* ------------------------------------------------------------------ LISTA DE INVESTIGAÇÃO (seção 25) */
  async function pageInvestigations() {
    main.innerHTML = `<h1>Lista de Investigação</h1><p class="sub">Transforme análises em atividades: motivo, evidências, fornecedores, concorrentes, exigências, documentos e próximas ações.</p><div id="iv">${loading()}</div>`;
    let d;
    try { d = await api('/api/v08/investigacoes'); } catch (e) { $('#iv').innerHTML = errBox(e); return; }
    const L = (a) => (a || []).map(escH).join('<br>') || '—';
    $('#iv').innerHTML = `<div class="kpis">${d.estados.map((s) => `<div class="kpi"><span>${escH(s)}</span><b>${d.contagem[s]}</b></div>`).join('')}</div>
      <div class="panel"><form id="ivn" class="filters"><label class="f">Produto<input name="produto" required></label><label class="f">Motivo<input name="motivo"></label><button class="btn">Adicionar</button></form></div>
      ${d.itens.map((i) => `<details class="panel"><summary><b>${i.produto_id ? dl(i.produto_id, i.produto) : escH(i.produto)}</b> — <span class="badge">${escH(i.estado)}</span> <span class="muted small">atualizado ${escH(i.atualizado_em)}</span></summary>
        <form class="ivf filters" data-id="${i.id}"><label class="f">Estado<select name="estado">${d.estados.map((s) => `<option ${s === i.estado ? 'selected' : ''}>${escH(s)}</option>`).join('')}</select></label>
        ${['motivo', 'evidencias', 'fontes', 'fornecedores', 'concorrentes', 'exigencias', 'documentos', 'proximas_acoes'].map((k) => `<label class="f">${escH(k.replace('_', ' '))}<textarea name="${k}" rows="2">${escH(Array.isArray(i[k]) ? i[k].join('\n') : (i[k] || ''))}</textarea></label>`).join('')}
        <label class="f">Nota<input name="nota"></label><button class="btn">Salvar</button></form>
        <p class="small muted">Histórico: ${(i.historico || []).map((h) => `${escH(h.criado_em)} ${escH(h.estado)}${h.nota ? ' — ' + escH(h.nota) : ''}`).join(' · ') || L([])}</p></details>`).join('') || '<p class="muted">Nenhum produto em investigação. Use “Adicionar à investigação” no dossiê de um produto.</p>'}`;
    $('#ivn').onsubmit = async (ev) => { ev.preventDefault(); try { await post('/api/v08/investigacoes', Object.fromEntries(new FormData(ev.target))); pageInvestigations(); } catch (e) { $('#iv').insertAdjacentHTML('afterbegin', errBox(e)); } };
    document.querySelectorAll('.ivf').forEach((f) => { f.onsubmit = async (ev) => { ev.preventDefault(); try { await post('/api/v08/investigacoes/' + f.dataset.id, Object.fromEntries(new FormData(f))); pageInvestigations(); } catch (e) { f.insertAdjacentHTML('beforeend', errBox(e)); } }; });
  }

  /* produto (v0.7.1) ganha atalho para o dossiê */
  const origProduct = PAGES['produto-consumo'];
  async function pageProduct(pid) {
    await origProduct(pid);
    main.insertAdjacentHTML('afterbegin', `<div class="banner info small">Visão consolidada (evidências por tipo, índices separados, linhagem e importação): <a href="#dossie/${encodeURIComponent(pid)}">abrir o Dossiê do produto</a>.</div>`);
  }

  return { 'dashboard': pageDashboard, 'dossie': pageDossier, 'qualidade-dados': pageQuality, 'empresas-registros': pageRegistry,
    'investigacoes': pageInvestigations, 'produto-consumo': pageProduct };
};
