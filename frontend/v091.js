/* GPI v0.9.1 — Product Intelligence Suite: Pesquisa de Produtos (dossiê de 9 abas, progresso real), Explorador de Nichos,
   Inteligência de Marketplaces (anúncios, comparação, tendências, avaliações), Palavras-chave, Pesquisa por Imagem (local,
   com recorte), Inteligência de Fornecedores, Investigação de Importação (simulador), Monitorados, Histórico e
   Configurações da suíte. Nenhum número é inventado: tudo vem do backend local. */
window.GPI_V091 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, errBox, main, $ } = H;
  const num = (v, d = 0) => v == null ? '—' : fmt(v, d);
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== '' && v != null).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  const parseArg = (arg) => Object.fromEntries(new URLSearchParams(arg || ''));
  const COR = { VERDE: 'ok', AMARELO: 'demo', VERMELHO: 'bad', CINZA: '' };
  const dec = (d) => d ? `<span class="badge ${COR[d.cor] || ''}" title="${escH(d.significado || '')}">${escH(d.cor)}</span>` : '';
  const tbl = (cols, rows, empty) => rows && rows.length ? `<div class="tw"><table class="small compact"><thead><tr>${cols.map((c) => `<th>${escH(c[1])}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${c[2] ? c[2](r) : escH(r[c[0]] == null ? '—' : r[c[0]])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : `<p class="muted small">${escH(empty || 'Sem dados.')}</p>`;
  const notes = (a) => (a || []).filter(Boolean).length ? `<ul class="clean small muted">${a.filter(Boolean).map((x) => `<li>${escH(x)}</li>`).join('')}</ul>` : '';
  const head = (t, sub) => `<h1>${t}</h1><p class="sub">${sub}</p>`;
  async function raw(path, body, name, ctype) {
    return api(path, { method: 'POST', headers: { 'Content-Type': ctype || 'application/octet-stream', 'X-Filename': encodeURIComponent(name || 'arquivo') }, body });
  }
  const monitor = async (tipo, ref, rotulo, out) => { try { await post('/api/suite/monitorados', { tipo, ref, rotulo }); out.innerHTML = `<span class="badge ok">monitorando</span> <a href="#monitorados">ver monitorados</a>`; } catch (e) { out.innerHTML = errBox(e); } };
  const goResearch = (q) => `#pesquisa-produtos/${encodeURIComponent(qs({ q }))}`;

  /* ======================================================================= PESQUISA DE PRODUTOS */
  const TABS = [['visao_geral', 'Visão geral'], ['demanda', 'Demanda'], ['marketplaces', 'Marketplaces'], ['semelhantes', 'Produtos semelhantes'],
    ['fornecedores', 'Fornecedores'], ['importacao', 'Importação'], ['qualidade', 'Qualidade'], ['previsoes', 'Previsões'], ['evidencias', 'Evidências']];
  async function pageResearch(arg) {
    const a = parseArg(arg);
    main.innerHTML = head('Pesquisa de Produtos', 'Pesquise um produto pelo nome (português ou inglês). Usa os dados já coletados pelo GPI; o que faltar é indicado.') + `
      <form class="panel" id="rf"><div class="btnrow" style="flex-wrap:wrap;gap:8px">
        <label class="f" style="flex:2 1 260px">Produto<input name="consulta" required minlength="2" value="${escH(a.q || '')}" placeholder="ex.: carregador GaN 65W, robot vacuum"></label>
        <label class="f">Mercado<select name="mercado">${['BR', 'US', 'CN'].map((m) => `<option ${a.mercado === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
        <div class="f">Comparar com (completa)<div>${[['US', 'EUA'], ['BR', 'Brasil'], ['CN', 'China']].map(([v, l]) => `<label class="small"><input type="checkbox" name="cmp" value="${v}"> ${l}</label>`).join(' ')}</div></div>
        <label class="f">Período<select name="periodo_meses">${[3, 6, 12, 24].map((m) => `<option value="${m}" ${m === 12 ? 'selected' : ''}>${m} meses</option>`).join('')}<option value="custom">personalizado</option></select></label>
        <label class="f" id="rfc" hidden>De<input type="date" name="inicio"></label><label class="f" id="rfd" hidden>Até<input type="date" name="fim"></label>
        <label class="f">Objetivo<select name="objetivo"><option>importar para revenda</option><option>avaliar demanda</option><option>comparar mercados</option><option>encontrar fornecedores</option><option>monitorar</option></select></label>
        <label class="f">Profundidade<select name="profundidade"><option value="rapida">Rápida</option><option value="completa">Completa (inclui previsões)</option></select></label>
        <label class="small"><input type="checkbox" name="atualizar"> atualizar fontes (ignorar cache)</label>
        <button class="btn primary">Pesquisar</button></div>
        <p class="small muted">Rápida: cache primeiro e poucas fontes do mercado principal. Completa: reaproveita a rápida, consulta fontes adicionais e os mercados de comparação, e roda as análises estatísticas.</p></form><div id="rout"></div>`;
    const f = $('#rf');
    f.periodo_meses.onchange = () => { const c = f.periodo_meses.value === 'custom'; $('#rfc').hidden = !c; $('#rfd').hidden = !c; };
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const b = { consulta: f.consulta.value, mercado: f.mercado.value, comparacao: [...f.querySelectorAll('[name=cmp]:checked')].map((o) => o.value).filter((v) => v !== f.mercado.value),
        periodo_meses: f.periodo_meses.value === 'custom' ? 12 : +f.periodo_meses.value, inicio: f.periodo_meses.value === 'custom' ? f.inicio.value : null,
        fim: f.periodo_meses.value === 'custom' ? f.fim.value : null, objetivo: f.objetivo.value, profundidade: f.profundidade.value, atualizar: f.atualizar.checked };
      try { const r = await post('/api/suite/pesquisa', b); location.hash = '#pesquisa-produtos/' + encodeURIComponent(qs({ id: r.id })); } catch (e) { $('#rout').innerHTML = errBox(e); }
    };
    if (a.id) await follow(+a.id); else if (a.q && a.auto === '1') f.requestSubmit();
  }
  async function follow(id) {
    const out = $('#rout');
    for (;;) {
      let j;
      try { j = await api('/api/suite/pesquisa/' + id); } catch (e) { out.innerHTML = errBox(e); return; }
      if ($('#rf') && j.query) $('#rf').consulta.value = j.query;
      const p = j.progresso, R = j.result || {}, fin = R.mensagem_final, cvs = R.coberturas;
      const SB = { 'concluída com dados': 'ok', 'concluída sem dados': 'demo', 'não autorizada': 'bad', 'indisponível': 'bad', 'falhou': 'bad', 'cancelada': '' };
      const pe = p.por_estado || {}, unav = (pe['não autorizada'] || 0) + (pe['indisponível'] || 0) + (pe['falhou'] || 0);
      const LV = { boa: 'ok', parcial: 'demo', nenhuma: 'bad', alta: 'ok', média: 'demo', baixa: 'bad', insuficiente: 'bad' };
      const covBox = (t, c, tip) => `<div class="kpi" title="${escH(tip || '')}"><div class="v"><span class="badge ${LV[c.nivel] || ''}">${escH(c.nivel)}</span> ${num(c.n)}</div><div class="l">${t}</div></div>`;
      const mk = R.mercados || {};
      out.innerHTML = `<section class="panel"><p><b>${escH(j.query)}</b> · ${escH(j.status)} ${j.finished_at ? '' : '<button class="btn small" id="rcancel">Cancelar</button>'}</p>
        ${mk.principal ? `<p class="small">Mercado principal: <b>${escH(mk.principal)}</b>${mk.comparativos && mk.comparativos.length ? ` · comparativo: ${escH(mk.comparativos.join(', '))}${mk.comparacao_ativa ? '' : ' (só na pesquisa completa)'}` : ''}
          ${Object.entries(mk.cobertura || {}).map(([m, c]) => `<br><span class="muted">${escH(m)} (${escH(c.papel)}): ${escH(c.fontes.join(', ') || '—')}${c.mensagem ? ' — <b>' + escH(c.mensagem) + '</b>' : ''}</span>`).join('')}</p>` : ''}
        <p class="small"><b>Progresso do processamento</b>: ${p.encerradas}/${p.total} etapas encerradas (${p.pct}%) · <span class="badge ok">${pe['concluída com dados'] || 0} com dados</span> <span class="badge demo">${pe['concluída sem dados'] || 0} sem dados</span> <span class="badge bad">${unav} indisponíveis/não autorizadas/falhas</span> ${pe['ignorada por configuração'] ? `<span class="badge">${pe['ignorada por configuração']} ignoradas por configuração</span>` : ''}</p>
        <div class="pbar"><div style="width:${p.pct}%"></div></div>
        ${cvs ? `<p class="small"><b>Cobertura da investigação</b> (não se somam)</p><section class="kpis compact">${covBox('Cobertura comercial', cvs.comercial, cvs.comercial.nota)}${covBox('Cobertura contextual', cvs.contextual, cvs.contextual.nota)}${covBox('Cobertura técnica', cvs.tecnica, cvs.tecnica.nota)}<div class="kpi" title="${escH(cvs.confianca.motivo)}"><div class="v"><span class="badge ${LV[cvs.confianca.nivel] || ''}">${escH(cvs.confianca.nivel)}</span></div><div class="l">Confiança da investigação</div></div></section>` : '<p class="small muted">Cobertura calculada ao fim do processamento.</p>'}
        ${fin ? `<div class="banner ${R.conclusiva ? 'info' : ''}"><b>${escH(fin)}</b></div>` : ''}
        <details ${j.finished_at ? '' : 'open'}><summary class="small">Etapas</summary><ol class="small">${j.steps.map((s) => `<li>${escH(s.nome)} — <span class="badge ${SB[s.estado] || ''}">${escH(s.estado)}</span> <span class="muted">${escH(s.detalhe || '')}</span></li>`).join('')}</ol></details></section><div id="rdos"></div>`;
      if ($('#rcancel')) $('#rcancel').onclick = async () => { await post(`/api/suite/pesquisa/${id}/cancelar`, {}); };
      if (j.result) { renderDossier(j, $('#rdos')); return; }
      if (!location.hash.startsWith('#pesquisa-produtos')) return;
      await new Promise((r) => setTimeout(r, 700));
    }
  }
  function renderDossier(j, box) {
    const R = j.result, A = R.abas, ov = A.visao_geral || {};
    const pid = ov.produto_id;
    const idf = ov.identificacao || {};
    box.innerHTML = `<section class="panel"><h2>${escH(ov.produto || R.consulta)} ${dec(R.decisao)}</h2>
      <p class="small">${idf.familia ? `Categoria: <b>${escH(idf.familia.categoria || '—')}</b> · ` : ''}Mercado: <b>${escH(((R.mercados || {}).principal) || (R.parametros || {}).mercado || 'BR')}</b></p>
      <p class="small muted">${idf.familia ? `Família: ${escH(idf.familia.nome)}${idf.variante ? ' · variante: ' + escH(idf.variante.rotulo) : ''} · ` : ''}${escH(Object.entries(idf.traducoes || {}).map(([k, v]) => `${k}: ${v}`).join(' · '))}${pid ? ` · <span title="identificador canônico interno">ID ${escH(pid)}</span>` : ''} · modo ${escH(R.modo || '')}${ov.registro_criado ? ' · <b>registro canônico criado nesta pesquisa</b>' : ''}</p>
      <p class="small">${escH((R.decisao || {}).significado || '')}</p>${notes((R.decisao || {}).motivos)}
      <div class="btnrow" style="flex-wrap:wrap"><button class="btn small" id="dmon">Monitorar semanalmente</button><button class="btn small" id="dsave">${j.saved ? 'Salva ✓' : 'Salvar pesquisa'}</button>
        <a class="btn small" href="/api/suite/pesquisa/${j.id}.xlsx">Exportar XLSX</a><a class="btn small" href="/api/suite/pesquisa/${j.id}.pdf">Exportar PDF</a>
        ${ov.investigar_url ? `<a class="btn small" href="${ov.investigar_url}">Abrir dossiê / Investigar</a>` : ''}
        <a class="btn small" href="#palavras-chave/${encodeURIComponent(qs({ termo: R.consulta }))}">Palavras-chave</a>
        <a class="btn small" href="#fornecedores-intel/${encodeURIComponent(qs({ q: ov.produto || R.consulta }))}">Investigar fornecedores</a>
        <a class="btn small" href="#importacao-intel/${encodeURIComponent(qs({ q: R.consulta, produto: pid || '' }))}">Investigação de importação</a>
        <a class="btn small" href="#pesquisa-imagem">Pesquisa por imagem</a><span id="dmsg" class="small"></span></div>
      ${R.resultado ? `<section class="panel"><h3>Resultado</h3><p class="small">Classificação executiva: ${dec({ cor: R.resultado.classificacao, significado: R.resultado.significado })} · confiança: <b>${escH((R.resultado.confianca || {}).nivel || '—')}</b> <span class="muted">${escH((R.resultado.confianca || {}).motivo || '')}</span> · ${num(R.resultado.evidencias)} evidência(s) registradas</p>
        ${R.resultado.limitacoes.length ? `<p class="small"><b>Limitações</b></p>${notes(R.resultado.limitacoes)}` : ''}
        ${R.resultado.proximas_acoes.length ? `<p class="small"><b>Próximas ações</b></p><div class="btnrow" style="flex-wrap:wrap">${R.resultado.proximas_acoes.map((a) => a.link ? `<a class="btn small" href="${escH(a.link)}">${escH(a.texto)}</a>` : `<span class="small badge">${escH(a.texto)}</span>`).join('')}</div>` : ''}</section>` : ''}
      <details class="panel" open><summary><b>Fontes e cobertura desta investigação</b></summary>${tbl([['fonte', 'Fonte'], ['capacidade', 'Capacidade requerida'], ['mercado', 'Mercado consultado'], ['papel', 'Papel', (r) => escH(r.papel || r.tipo || '—')], ['cobertura_geografica', 'Cobertura geográfica', (r) => escH(r.cobertura_geografica || '—')],
        ['estado_integracao', 'Integração'], ['autenticacao', 'Autenticação'], ['consulta_realizada', 'Consultada', (r) => r.consulta_realizada ? 'sim' : 'não'],
        ['estado', 'Resultado', (r) => `<span class="badge ${['com dados', 'cache válido'].includes(r.estado) ? 'ok' : ['não autorizada', 'indisponível', 'falhou'].includes(r.estado) ? 'bad' : ''}">${escH(r.estado)}</span>`],
        ['registros', 'Registros válidos', (r) => num(r.registros)], ['motivo', 'Motivo da ausência', (r) => escH(r.motivo || (r.cache ? 'cache ' + r.cache : '') || '—')],
        ['ultima_coleta', 'Última coleta', (r) => escH((r.ultima_coleta || '—').slice(0, 16))], ['acao', 'Ação recomendada', (r) => r.central ? `<a class="btn small" href="${escH(r.central)}">${escH(r.fonte.split(' —')[0])} não conectado — abrir Central de Integrações</a>` : escH(r.acao || '—')]], R.fontes || [], 'Diagnóstico indisponível.')}</details>
      <div class="tabs" id="dtabs">${TABS.map(([k, l], i) => `<button class="btn small ${i ? '' : 'primary'}" data-t="${k}">${l}</button>`).join('')}</div><div id="dtab"></div></section>`;
    $('#dmon').onclick = async () => { try { const r = await post(`/api/suite/pesquisa/${j.id}/monitorar`, {}); $('#dmsg').innerHTML = `<span class="badge ok">monitoramento semanal</span> termos: ${escH(Object.values(r.parametros.termos).join(' / '))} · mercado ${escH(r.parametros.mercado)} · <a href="#monitorados">ver</a>`; } catch (e) { $('#dmsg').innerHTML = errBox(e); } };
    $('#dsave').onclick = async () => { await post(`/api/suite/pesquisa/${j.id}/salvar`, { salvar: true }); $('#dsave').textContent = 'Salva ✓'; };
    const show = (k) => { document.querySelectorAll('#dtabs [data-t]').forEach((b) => b.classList.toggle('primary', b.dataset.t === k)); $('#dtab').innerHTML = TAB[k](A[k] || {}, R); };
    document.querySelectorAll('#dtabs [data-t]').forEach((b) => { b.onclick = () => show(b.dataset.t); });
    show('visao_geral');
  }
  const ind = (o) => Object.entries(o || {}).map(([k, v]) => `<div class="kpi"><div class="v">${escH(v.valor == null ? '—' : typeof v.valor === 'number' ? fmt(v.valor, 1) : v.valor)}</div><div class="l">${escH(k.replace(/_/g, ' '))}</div></div>`).join('');
  const TAB = {
    visao_geral: (t) => `<section class="kpis compact">${ind(t.indicadores)}</section>
      <p class="small">Estágio: <b>${escH(t.nome_estagio || '—')}</b> · situação: ${escH(t.situacao || '—')} · identificação: ${escH((t.entendimento || {}).estado || '—')} (${escH((t.entendimento || {}).nivel_rotulo || '')})</p>
      <p class="small">Taxonomia: ${((t.entendimento || {}).taxonomia || []).map((n) => escH(n.rotulo || n.id)).join(' › ') || '—'}</p>
      <p class="small">Atributos explícitos: ${escH(Object.entries((t.entendimento || {}).atributos || {}).filter(([, v]) => v).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ') || 'nenhum')}</p>
      <p class="small"><b>Próximas ações</b></p>${notes(t.proximas_acoes)}<p class="small muted">Score não é probabilidade. Ausência de dado não é evidência negativa.</p>`,
    demanda: (t) => `<p class="small">Período: ${escH((t.periodo || []).join(' a '))}</p>${(t.mercados || []).map((m) => `<h3>${escH(m.mercado)}</h3><p class="small">${m.termos_observados} termo(s) observados · ${m.com_volume} com volume verificado · ${m.com_historico} com histórico</p>
      ${tbl([['palavra', 'Palavra-chave'], ['fonte', 'Fonte'], ['mercado', 'Mercado'], ['volume_disponivel', 'Volume disponível'], ['tendencia', 'Tendência'], ['classe', 'Tipo']], m.exemplos, 'Nenhum termo observado neste mercado.')}`).join('')}
      <h3>Evidências da inteligência</h3>${tbl([['fonte_nome', 'Fonte'], ['tipo_rotulo', 'Tipo'], ['indicador', 'Indicador'], ['mercado', 'Mercado'], ['periodo', 'Período'], ['observacoes_n', 'Obs.'], ['nao_e', 'Não é']], t.evidencias_inteligencia, t.vazio)}
      ${notes([t.aviso, t.vazio])}`,
    marketplaces: (t) => { const s = t.ultimos_30_dias || t.ultimos_90_dias; return `${s ? `<section class="kpis compact">${[['Anúncios recebidos', s.anuncios], ['Elegíveis (produto/variante)', s.anuncios_elegiveis], ['Preço mín./unid.', s.preco_min], ['Mediana/unid.', s.preco_mediano], ['Preço máx./unid.', s.preco_max], ['Marcas declaradas', s.marcas_distintas]].map(([l, v]) => `<div class="kpi"><div class="v">${num(v, 2)}</div><div class="l">${l}</div></div>`).join('')}</section>
      <p class="small">Janela: ${s.janela_dias} dias · moeda ${escH(s.moeda || '—')}${s.moedas_misturadas ? ' (moedas misturadas: preços não agregados)' : ''} · cobertura da amostra ${s.cobertura_amostra == null ? '—' : fmt(100 * s.cobertura_amostra, 0) + '%'} · kits/lotes: ${num(s.kits_ou_lotes)} · concorrência: <b>${escH(t.competicao)}</b> · fontes: ${escH(s.fontes.join(', '))}</p>
      <p class="small">Correspondência dos anúncios: ${escH(Object.entries(s.por_correspondencia || {}).map(([k, v]) => `${v} ${k}`).join(' · '))}</p>
      ${(s.exemplos_rejeitados || []).length ? `<details class="small"><summary>Exemplos fora da comparação de preços</summary>${tbl([['titulo', 'Anúncio'], ['classe', 'Classe'], ['motivo', 'Motivo']], s.exemplos_rejeitados)}</details>` : ''}` : ''}
      ${tbl([['titulo', 'Anúncio', (r) => `<a href="#mkt-intel/${encodeURIComponent(qs({ ref: r.item_id }))}">${escH(r.title)}</a>`], ['classe', 'Correspondência', (r) => escH((r.correspondencia || {}).classe || '—')], ['brand', 'Marca'], ['price', 'Preço anunciado', (r) => num(r.price, 2) + ' ' + escH(r.currency || '')], ['mercado', 'Mercado'], ['dia', 'Última obs.'], ['source', 'Fonte']], t.anuncios, t.vazio)}
      ${notes([t.aviso, 'Não disponível: ' + (t.nao_disponivel || []).join(', ')])}`; },
    semelhantes: (t) => (t.classes || []).map((c) => (t.grupos[c] || []).length ? `<h3>${escH(c)}</h3>${tbl([['nome', 'Produto', (r) => `<a href="${goResearch(r.nome)}">${escH(r.nome)}</a>`], ['motivo', 'Por quê'], ['situacao', 'Situação'], ['opportunity_score', 'Score', (r) => num(r.opportunity_score, 1)], ['anuncios_30d', 'Anúncios 30d', (r) => num(r.anuncios_30d)]], t.grupos[c])}` : '').join('') + (t.itens && t.itens.length ? '' : `<p class="small muted">${escH(t.vazio || 'Nenhum produto relacionado.')}</p>`) + notes(t.avisos),
    fornecedores: (t) => tbl([['empresa', 'Empresa', (r) => r.company_id ? `<a href="#fornecedores-intel/${encodeURIComponent(qs({ id: r.company_id }))}">${escH(r.empresa)}</a>` : escH(r.empresa)], ['pais', 'País'],
      ['produto_relacionado', 'Produto relacionado', () => escH(t.produto || t.consulta)], ['tipo_correspondencia', 'Tipo de correspondência'], ['comprovacao', 'Comprovação'],
      ['fontes', 'Fonte', (r) => escH(r.fontes.join(', '))], ['evid', 'Evidência', (r) => escH((r.correspondencias || []).map((c) => c.evidencia).join(' | '))],
      ['confianca', 'Confiança'], ['limitacoes', 'Limitações', (r) => escH((r.limitacoes || []).join(' · '))]], t.candidatos, t.vazio) + notes([t.aviso]),
    importacao: (t) => `<h3>NCM candidatas</h3>${tbl([['codigo', 'NCM'], ['descricao', 'Descrição'], ['pontuacao', 'Pontos']], (t.ncm || {}).candidatas, (t.ncm || {}).sem_tabela ? 'Tabela NCM não carregada (Conformidade › Classificação NCM).' : 'Nenhuma candidata.')}
      <h3>Estatísticas agregadas (Comex Stat)</h3>${tbl([['series_key', 'Série'], ['indicator', 'Indicador'], ['country', 'País'], ['ultimos_12', 'Últimos 12 períodos', (r) => num(r.ultimos_12, 0)], ['fim', 'Até']], (t.ncm || {}).estatisticas_agregadas, 'Sem séries do Comex Stat para as NCM candidatas.')}
      ${notes((t.ncm || {}).avisos)}<h3>Regulatório (preliminar)</h3><p class="small">${num((t.regulatorio || {}).registros_encontrados)} registro(s) de produtos semelhantes. ${escH((t.regulatorio || {}).regra || '')}</p>
      <h3>Riscos identificados</h3>${tbl([['risco', 'Risco'], ['origem', 'Origem'], ['acao', 'Ação']], t.riscos, 'Nenhum risco identificado pelos dados (não significa ausência de riscos).')}`,
    qualidade: (t) => `<p class="small">Evidence Coverage: <b>${num((t.evidence_coverage || {}).valor, 1)}</b> · frescor: ${escH((t.frescor || {}).valor || '—')} · identificação: ${escH(t.identificacao || '—')} · associações em revisão: ${num(t.associacoes_em_revisao)}</p>
      <p class="small">Origem das evidências: ${escH(Object.entries(t.origens || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—')}</p><p class="small">Fontes: ${escH((t.fontes || []).join(', ') || '—')}</p>${notes(t.regras)}`,
    previsoes: (t, R) => (R.parametros || {}).profundidade !== 'completa' ? '<p class="small muted">Previsões só na pesquisa completa.</p>' : (t.series || []).length ? t.series.map((s) => `<details class="small" open><summary><b>${escH(s.rotulo)}</b> · ${s.n} meses</summary>
      <p>Tendência: ${s.tendencia ? escH(`${s.tendencia.direcao || '—'} (p=${fmt(s.tendencia.p_valor, 3)}${s.tendencia.significativa ? ', significativa' : ', não significativa'})`) : 'não avaliada'}
      · regime: ${s.mudanca_regime ? escH(JSON.stringify(s.mudanca_regime).slice(0, 120)) : '—'} · aceleração: ${escH((s.aceleracao || {}).classe || '—')} · sazonalidade: ${escH((s.sazonalidade || {}).classe || (s.sazonalidade || {}).estado || '—')}</p>
      ${s.previsao ? `<p>Previsão (${escH(s.previsao.modelo)}): ${s.previsao.meses.map((m, i) => `${m}: ${fmt(s.previsao.valores[i], 1)}`).join(' · ')}<br>WAPE validação ${fmt(100 * s.previsao.backtest_wape, 1)}% vs ingênuo ${fmt(100 * s.previsao.ingenuo_wape, 1)}%. ${escH(s.previsao.nota)}</p>` : ''}${notes(s.limitacoes)}</details>`).join('') + notes([t.nota]) : `<p class="muted small">${escH(t.vazio || 'Sem séries.')}</p>`,
    evidencias: (t) => tbl([['entity_type', 'Entidade'], ['source', 'Fonte'], ['indicator', 'Indicador'], ['value', 'Valor'], ['unit', 'Unidade'], ['period_end', 'Até'], ['source_capability', 'Capacidade'], ['confidence', 'Confiança'], ['origin', 'Origem'], ['usage_restrictions', 'Restrições']], t.itens, 'Nenhuma evidência registrada.') + notes([t.regra]),
  };

  /* ======================================================================= EXPLORADOR DE NICHOS */
  const NF = [['texto', 'Texto'], ['preco_min', 'Preço mín.'], ['preco_max', 'Preço máx.'], ['crescimento_min', 'Crescimento mín. (%)'], ['anuncios_min', 'Anúncios mín.'], ['anuncios_max', 'Anúncios máx.'], ['marcas_max', 'Marcas máx.'], ['cobertura_min', 'Cobertura mín.'], ['atributo', 'Atributo (chave=valor)']];
  async function pageNiches(arg) {
    const f = parseArg(arg);
    main.innerHTML = head('Explorador de Nichos', 'Filtre produtos pelos dados locais do GPI (Opportunity Engine, anúncios observados, evidências).') + `<div id="nz">${loading()}</div>`;
    let d;
    try { d = await api('/api/suite/nichos?' + qs(f)); } catch (e) { $('#nz').innerHTML = errBox(e); return; }
    $('#nz').innerHTML = `<form class="panel" id="nf"><div class="btnrow" style="flex-wrap:wrap;gap:6px">${NF.map(([k, l]) => `<label class="f">${l}<input name="${k}" size="9" value="${escH(f[k] || '')}"></label>`).join('')}
        <label class="f">Categoria<select name="categoria"><option value="">todas</option>${d.categorias.map((c) => `<option ${f.categoria === c ? 'selected' : ''}>${escH(c)}</option>`).join('')}</select></label>
        <label class="f">Competição<select name="competicao"><option value="">todas</option>${['não avaliada', 'indicativa: muitos anunciantes (baixa concentração)', 'indicativa: concentração moderada', 'indicativa: alta concentração de anúncios'].map((c) => `<option ${f.competicao === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <label class="f">Confiança mín.<select name="confianca_min"><option value="">—</option>${['baixa', 'média', 'alta'].map((c) => `<option ${f.confianca_min === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <label class="f">Decisão<select name="cor"><option value="">todas</option>${['VERDE', 'AMARELO', 'VERMELHO', 'CINZA'].map((c) => `<option ${f.cor === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <label class="f">Ordenar<select name="ordem">${['oportunidade', 'crescimento', 'cobertura', 'preco', 'anuncios', 'nome'].map((c) => `<option ${d.ordem === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <button class="btn primary">Filtrar</button></div></form>
      <p class="small">${d.filtrados} de ${d.total} produto(s). ${escH(d.nota)}</p>
      <div class="btnrow"><a class="btn small" href="/api/suite/nichos.xlsx?${qs(d.filtros)}">Exportar XLSX</a><a class="btn small" href="/api/suite/nichos.pdf?${qs(d.filtros)}">Exportar PDF</a>
        <input id="nsn" placeholder="nome do filtro" size="14"><button class="btn small" id="nss">Salvar filtro</button>
        ${d.salvos.map((s) => `<a class="btn small" href="#nichos/${encodeURIComponent(qs(s.filtros))}">${escH(s.nome)}</a>`).join('')}<button class="btn small" id="ncmp">Comparar selecionados</button></div>
      ${tbl([['sel', '', (r) => `<input type="checkbox" data-c="${escH(r.produto_id)}">`], ['produto', 'Produto', (r) => `<a href="#dossie/${encodeURIComponent(r.produto_id)}">${escH(r.produto)}</a>`], ['decisao', 'Decisão', (r) => dec({ cor: r.decisao })], ['nome_estagio', 'Estágio'],
        ['opportunity_score', 'Score', (r) => num(r.opportunity_score, 1)], ['crescimento', 'Cresc. %', (r) => r.crescimento == null ? `<span class="muted" title="${escH(r.crescimento_status)}">—</span>` : num(r.crescimento, 1)],
        ['anuncios', 'Anúncios', (r) => num(r.anuncios)], ['marcas', 'Marcas', (r) => num(r.marcas)], ['preco_mediano', 'Preço med.', (r) => r.preco_mediano == null ? '—' : num(r.preco_mediano, 2) + ' ' + escH(r.moeda || '')],
        ['competicao', 'Competição'], ['confianca', 'Confiança'], ['acoes', 'Ações', (r) => `<a href="${goResearch(r.produto)}">Pesquisar</a> · <a href="#" data-m="${escH(r.produto_id)}">Monitorar</a>`]], d.itens, 'Nenhum produto atende aos filtros.')}<div id="nmsg" class="small"></div><div id="ncmpout"></div>`;
    $('#nf').onsubmit = (e) => { e.preventDefault(); location.hash = '#nichos/' + encodeURIComponent(qs(Object.fromEntries(new FormData($('#nf'))))); };
    $('#nss').onclick = async () => { try { await post('/api/suite/nichos/salvar', { nome: $('#nsn').value, filtros: d.filtros }); route(); } catch (e) { $('#nmsg').innerHTML = errBox(e); } };
    document.querySelectorAll('[data-m]').forEach((a) => { a.onclick = (e) => { e.preventDefault(); monitor('produto', a.dataset.m, a.dataset.m, $('#nmsg')); }; });
    $('#ncmp').onclick = () => {
      const ids = [...document.querySelectorAll('[data-c]:checked')].map((c) => c.dataset.c).slice(0, 5);
      const rows = d.itens.filter((r) => ids.includes(r.produto_id));
      $('#ncmpout').innerHTML = rows.length ? `<section class="panel"><h2>Comparação</h2>${tbl([['campo', 'Campo'], ...rows.map((r, i) => [i, r.produto])], ['decisao', 'nome_estagio', 'opportunity_score', 'evidence_coverage', 'crescimento', 'anuncios', 'vendedores', 'marcas', 'preco_mediano', 'competicao', 'confianca'].map((k) => ({ campo: k, ...Object.fromEntries(rows.map((r, i) => [i, r[k] == null ? '—' : r[k]])) })))}</section>` : '<p class="small muted">Selecione até 5 produtos.</p>';
    };
  }
  const route = () => window.dispatchEvent(new HashChangeEvent('hashchange'));

  /* ======================================================================= PALAVRAS-CHAVE */
  async function pageKeywords(arg) {
    const a = parseArg(arg);
    main.innerHTML = head('Palavras-chave', 'Termos observados nas fontes coletadas × termos gerados pelo léxico do GPI. Volume só quando uma fonte autorizada informa.') + `
      <form class="panel btnrow" id="kf"><label class="f" style="flex:1">Termo principal<input name="termo" required value="${escH(a.termo || '')}"></label><label class="f">Mercado<input name="mercado" size="5" value="${escH(a.mercado || '')}" placeholder="BR"></label><button class="btn primary">Analisar</button></form>
      <form class="panel btnrow" id="kr"><label class="f" style="flex:1">Hipóteses a partir de um anúncio coletado (ID ou URL)<input name="ref"></label><button class="btn">Gerar hipóteses</button></form><div id="kout"></div>`;
    $('#kf').onsubmit = (e) => { e.preventDefault(); location.hash = '#palavras-chave/' + encodeURIComponent(qs(Object.fromEntries(new FormData($('#kf'))))); };
    $('#kr').onsubmit = async (e) => {
      e.preventDefault();
      const ref = $('#kr').ref.value.trim().match(/(\d{9,15}|MLB-?\d+)/i);
      try { const r = await api('/api/suite/palavras/anuncio/' + encodeURIComponent(ref ? ref[1] : $('#kr').ref.value)); $('#kout').innerHTML = r.encontrado ? `<section class="panel"><h2>${escH(r.anuncio.title)}</h2>${tbl([['palavra', 'Hipótese'], ['tipo', 'Origem']], r.hipoteses)}${notes([r.aviso])}</section>` : `<p class="small">${escH(r.mensagem)}</p>`; } catch (er) { $('#kout').innerHTML = errBox(er); }
    };
    if (!a.termo) return;
    $('#kout').innerHTML = loading();
    let d;
    try { d = await api('/api/suite/palavras?' + qs(a)); } catch (e) { $('#kout').innerHTML = errBox(e); return; }
    $('#kout').innerHTML = `<section class="panel"><p class="small">Entendimento: <b>${escH(d.entendimento.produto_id || d.entendimento.principal || 'não identificado')}</b> (${escH(d.entendimento.estado || '')}) · traduções: ${escH(Object.entries(d.traducoes).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—')}</p>
      <div class="btnrow"><a class="btn small" href="/api/suite/palavras.xlsx?${qs(a)}">XLSX</a><a class="btn small" href="/api/suite/palavras.pdf?${qs(a)}">PDF</a><a class="btn small" href="${goResearch(a.termo)}">Pesquisar produto</a></div>
      <h2>Observadas</h2>${tbl([['palavra', 'Palavra-chave'], ['fonte', 'Fonte'], ['mercado', 'Mercado'], ['volume_disponivel', 'Volume disponível'], ['tendencia', 'Tendência'], ['relevancia', 'Relevância'], ['classe', 'Tipo'], ['periodos', 'Períodos']], d.observadas, 'Nenhum termo observado nas fontes coletadas.')}
      <h2>Geradas (não observadas)</h2>${tbl([['palavra', 'Palavra-chave'], ['tipo', 'Origem'], ['idioma', 'Idioma'], ['volume_disponivel', 'Volume']], d.geradas, 'Nenhuma sugestão.')}
      ${notes([d.aviso, ...Object.entries(d.legenda).map(([k, v]) => `${k}: ${v}`)])}</section>`;
  }

  /* ======================================================================= INTELIGÊNCIA DE MARKETPLACES */
  async function pageMarket(arg) {
    const a = parseArg(arg);
    main.innerHTML = head('Inteligência de Marketplaces', 'Anúncios coletados por APIs autorizadas (eBay Browse, Mercado Livre). Sem vendas nem receita estimadas.') + `
      <p class="small">Também: <a href="#marketplaces">Marketplaces</a> · <a href="#comparador">Comparador</a> · <a href="#reviews">Reviews</a> · <a href="#concorrencia">Concorrência</a> · <a href="#nichos">Explorador de nichos</a></p>
      <form class="panel btnrow" id="mf"><label class="f" style="flex:1">Anúncio (nome, URL ou ID)<input name="ref" value="${escH(a.ref || '')}"></label><button class="btn primary">Analisar</button></form>
      <form class="panel btnrow" id="mc"><label class="f" style="flex:1">Comparar até 5 anúncios (IDs ou URLs separados por vírgula)<input name="refs"></label><button class="btn">Comparar</button></form>
      <form class="panel btnrow" id="mt"><label class="f" style="flex:1">Tendências e sazonalidade — produto (ID do catálogo)<input name="produto" value="${escH(a.produto || '')}" placeholder="ex.: charger+gan"></label><button class="btn">Explorar</button></form>
      <section class="panel"><h2>Avaliações</h2><p class="small">Envie um CSV/XLSX de avaliações exportado por você (colunas: produto, nota, comentário, data). Processado localmente.</p><input type="file" id="mrf" accept=".csv,.xlsx"> <a class="btn small" href="#" id="mri">Ver avaliações coletadas</a><div id="mrv"></div></section><div id="mout"></div>`;
    const out = $('#mout');
    const one = (x) => x.encontrado ? `<section class="panel"><h2>${escH(x.titulo)}</h2><p class="small">${escH(x.fonte)} · ${escH(x.id)} · marca ${escH(x.marca || '—')} · vendedor (pseudônimo) ${escH(x.vendedor || '—')} · ${x.observacoes} observação(ões) de ${escH(x.primeira)} a ${escH(x.ultima)} ${x.url ? `· <a href="${escH(x.url)}" target="_blank" rel="noopener noreferrer">abrir anúncio</a>` : ''}</p>
      <p class="small">Preço atual: <b>${num(x.preco_atual, 2)}</b> · variação: ${x.variacao_preco_pct == null ? '—' : num(x.variacao_preco_pct, 1) + '%'}</p>${tbl([['dia', 'Dia'], ['preco', 'Preço', (r) => num(r.preco, 2)], ['moeda', 'Moeda']], x.historico_precos)}${notes([x.aviso])}</section>`
      : `<section class="panel"><p class="small">${escH(x.mensagem)}</p>${x.consulta_api ? `<div class="banner small"><b>${escH(x.consulta_api.provedor || x.consulta_api.tipo || '')}</b>: ${escH(x.consulta_api.motivo || (x.consulta_api.ok ? 'consultado pela API oficial' : ''))} ${x.consulta_api.acao ? '— ' + escH(x.consulta_api.acao) : ''} ${x.consulta_api.central ? `<a class="btn small" href="${escH(x.consulta_api.central)}">Abrir Central de Integrações</a>` : ''}${x.consulta_api.ok && !x.consulta_api.gravado ? `<br>${escH(x.consulta_api.anuncio.titulo)} · ${num(x.consulta_api.anuncio.preco, 2)} ${escH(x.consulta_api.anuncio.moeda || '')} — ${escH(x.consulta_api.nota_gravacao || '')}` : ''}</div>` : ''}${x.url && x.url.motivo ? `<p class="small">${escH(x.url.tipo)}: ${escH(x.url.motivo)}</p>` : ''}${tbl([['title', 'Encontrados pelo nome', (r) => `<a href="#mkt-intel/${encodeURIComponent(qs({ ref: r.item_id }))}">${escH(r.title)}</a>`], ['source', 'Fonte'], ['ultimo', 'Última obs.']], x.busca_por_nome || [], '')}</section>`;
    $('#mf').onsubmit = (e) => { e.preventDefault(); location.hash = '#mkt-intel/' + encodeURIComponent(qs({ ref: $('#mf').ref.value })); };
    $('#mt').onsubmit = (e) => { e.preventDefault(); location.hash = '#mkt-intel/' + encodeURIComponent(qs({ produto: $('#mt').produto.value })); };
    $('#mc').onsubmit = async (e) => {
      e.preventDefault();
      try { const r = await post('/api/suite/anuncios/comparar', { refs: $('#mc').refs.value.split(/[,\s]+/).filter(Boolean) });
        const ok = r.itens.filter((x) => x.encontrado);
        out.innerHTML = `<section class="panel"><h2>Comparação</h2>${tbl([['titulo', 'Anúncio'], ['fonte', 'Fonte'], ['marca', 'Marca'], ['preco_atual', 'Preço atual', (x) => num(x.preco_atual, 2)], ['variacao_preco_pct', 'Variação %', (x) => num(x.variacao_preco_pct, 1)], ['observacoes', 'Obs.'], ['ultima', 'Última']], ok, 'Nenhum anúncio coletado entre os informados.')}${notes([r.aviso])}</section>`;
      } catch (er) { out.innerHTML = errBox(er); }
    };
    $('#mri').onclick = async (e) => { e.preventDefault(); try { const r = await api('/api/suite/avaliacoes'); $('#mrv').innerHTML = tbl([['nome', 'Produto'], ['n', 'Opiniões'], ['negativos', 'Negativas'], ['criticas_lb95', 'Críticas (LI 95%)', (p) => num(p.criticas_lb95, 3)], ['documentos', 'Documentos']], r.produtos || [], 'Nenhuma avaliação coletada.'); } catch (er) { $('#mrv').innerHTML = errBox(er); } };
    $('#mrf').onchange = async () => { const f = $('#mrf').files[0]; if (!f) return; $('#mrv').innerHTML = loading('Analisando localmente…');
      try { const r = await raw('/api/suite/avaliacoes/arquivo', f, f.name); $('#mrv').innerHTML = `<p class="small">${r.avaliacoes_validas} avaliação(ões) válidas de ${r.linhas} linha(s).</p>${tbl([['produto', 'Produto'], ['avaliacoes', 'Avaliações'], ['nota_media', 'Nota média', (p) => num(p.nota_media, 2)], ['negativas', 'Negativas'], ['negativas_lb95', 'Negativas (LI 95%)', (p) => num(p.negativas_lb95, 3)], ['aspectos', 'Aspectos', (p) => escH(p.aspectos.slice(0, 4).map((x) => `${x.aspecto} (${x.classificacao}, ${x.mencoes})`).join('; '))]], r.produtos)}${notes(r.avisos)}`; } catch (er) { $('#mrv').innerHTML = errBox(er); } };
    if (a.ref) { out.innerHTML = loading(); try { out.innerHTML = one(await api('/api/suite/anuncio?' + qs({ ref: a.ref }))); } catch (e) { out.innerHTML = errBox(e); } }
    if (a.produto) {
      out.innerHTML = loading();
      try { const t = await api('/api/suite/tendencias?' + qs({ produto: a.produto })); out.innerHTML = `<section class="panel"><h2>Tendências — ${escH(a.produto)}</h2>${TAB.previsoes(t, { parametros: { profundidade: 'completa' } })}</section>`; } catch (e) { out.innerHTML = errBox(e); }
    }
  }

  /* ======================================================================= PESQUISA POR IMAGEM */
  async function pageImage() {
    main.innerHTML = head('Pesquisa por Imagem', 'Busca LOCAL por semelhança visual no catálogo de imagens do GPI. A imagem consultada não é gravada nem enviada a serviços externos.') + `
      <section class="panel"><div id="drop" class="dropzone" tabindex="0">Arraste uma imagem (JPG, PNG, WEBP), cole (Ctrl+V) ou <label class="btn small">escolha um arquivo<input type="file" id="imf" accept="image/jpeg,image/png,image/webp" hidden></label></div>
        <div class="btnrow"><label class="f" style="flex:1">ou URL pública da imagem<input id="imu" placeholder="https://…"></label><button class="btn small" id="imub">Buscar pela URL</button>
          <label class="small"><input type="checkbox" id="imebay"> enviar a imagem ao eBay (busca por imagem oficial; exige eBay conectado)</label></div>
          <p class="small muted">Aceita URL direta de imagem ou link de anúncio do eBay/Mercado Livre (a foto vem da API oficial). Páginas comuns não são lidas.</p>
          <input id="imfam" type="hidden">
        <div id="crop" hidden><p class="small">Arraste sobre a imagem para recortar a região do produto (opcional).</p><canvas id="cv" style="max-width:100%;border:1px solid var(--line);cursor:crosshair"></canvas>
          <div class="btnrow"><button class="btn primary small" id="imgo">Buscar semelhantes</button><button class="btn small" id="imclr">Remover recorte</button>
          <label class="f">Rótulo<input id="imlbl" size="14"></label><label class="f">Produto (ID)<input id="impid" size="14"></label><button class="btn small" id="imadd">Adicionar ao catálogo visual</button></div></div>
        <p class="small muted">Semelhança visual não comprova o mesmo fabricante, modelo ou origem.</p></section><div id="imout"></div>
      <details class="panel"><summary><b>Catálogo visual</b></summary><div id="imcat"></div></details>`;
    let file = null, img = null, sel = null;
    const cv = $('#cv'), ctx = cv.getContext('2d');
    const draw = () => { ctx.drawImage(img, 0, 0, cv.width, cv.height); if (sel) { ctx.strokeStyle = '#e33'; ctx.lineWidth = 2; ctx.strokeRect(sel.x * cv.width, sel.y * cv.height, sel.w * cv.width, sel.h * cv.height); } };
    const load = (f) => { if (!f || !/^image\/(jpeg|png|webp)$/.test(f.type)) { $('#imout').innerHTML = errBox('Use JPG, PNG ou WEBP.'); return; } file = f; sel = null;
      const u = URL.createObjectURL(f); img = new Image(); img.onload = () => { const s = Math.min(1, 640 / img.width); cv.width = img.width * s; cv.height = img.height * s; draw(); $('#crop').hidden = false; URL.revokeObjectURL(u); }; img.src = u; };
    $('#imf').onchange = () => load($('#imf').files[0]);
    const dz = $('#drop');
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('on'); };
    dz.ondragleave = () => dz.classList.remove('on');
    dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove('on'); load(e.dataTransfer.files[0]); };
    document.onpaste = (e) => { if (!location.hash.startsWith('#pesquisa-imagem')) return; const it = [...(e.clipboardData || {}).items || []].find((i) => i.type.startsWith('image/')); if (it) load(it.getAsFile()); };
    let st = null;
    const pos = (e) => { const r = cv.getBoundingClientRect(); return { x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) }; };
    cv.onpointerdown = (e) => { st = pos(e); };
    cv.onpointermove = (e) => { if (!st) return; const p = pos(e); sel = { x: Math.min(st.x, p.x), y: Math.min(st.y, p.y), w: Math.abs(p.x - st.x), h: Math.abs(p.y - st.y) }; draw(); };
    cv.onpointerup = () => { st = null; if (sel && (sel.w < 0.03 || sel.h < 0.03)) { sel = null; draw(); } };
    $('#imclr').onclick = () => { sel = null; draw(); };
    const qp = () => qs({ familia: $('#imfam').value, ebay: $('#imebay').checked ? '1' : '', recorte: sel ? JSON.stringify({ x: sel.x, y: sel.y, w: sel.w, h: sel.h }) : '' });
    const results = (r) => {
      $('#imout').innerHTML = `<section class="panel"><h2>Resultados (${r.resultados.length} de ${r.catalogo_total} imagem(ns) no catálogo) · ${escH(r.nivel)}</h2>
        <p class="small">Consulta: ${escH(r.consulta.formato)} ${r.consulta.largura}×${r.consulta.altura}${r.consulta.recorte ? ' (recortada)' : ''} · metadados removidos · não gravada.</p>
        ${r.resultados.length ? `<div class="imgrid">${r.resultados.map((x) => `<figure><img src="${x.miniatura}" alt="" loading="lazy"><figcaption><span class="badge">${escH(x.classe)}</span> ${num(x.similaridade, 2)}<br>${escH(x.nome_comercial || x.rotulo || '')}${(x.nome_comercial || x.rotulo) ? `<br><a href="${goResearch(x.nome_comercial || x.rotulo)}">Pesquisar Mercado</a> · <a href="#fornecedores-intel/${encodeURIComponent(qs({ q: x.nome_comercial || x.rotulo }))}">Investigar Fornecedores</a>` : ''}${x.product_id ? ` · <a href="#" data-mi="${escH(x.product_id)}">Monitorar</a>` : ''}<br><span class="muted">${escH(x.motivos.join(' · '))}</span></figcaption></figure>`).join('')}</div>` : '<p class="small muted">Nenhuma correspondência no catálogo visual. Adicione imagens de referência ao catálogo.</p>'}
        <p class="small"><b>${escH(r.aviso)}</b></p><p class="small muted">${escH(r.nota_similaridade)}</p>
        ${r.origem_url && r.origem_url.anuncio ? `<p class="small">Imagem obtida do anúncio pela API oficial: <b>${escH(r.origem_url.anuncio.titulo)}</b> · ${num(r.origem_url.anuncio.preco, 2)} ${escH(r.origem_url.anuncio.moeda || '')} ${r.origem_url.anuncio.url ? `<a href="${escH(r.origem_url.anuncio.url)}" target="_blank" rel="noopener noreferrer">abrir</a>` : ''} · <a href="${goResearch(r.origem_url.anuncio.titulo)}">Pesquisar produto</a></p>` : ''}
        <h3>eBay — busca por imagem</h3>${r.ebay && r.ebay.ok ? tbl([['titulo', 'Anúncio', (x) => x.url ? `<a href="${escH(x.url)}" target="_blank" rel="noopener noreferrer">${escH(x.titulo)}</a>` : escH(x.titulo)], ['preco', 'Preço', (x) => num(+x.preco, 2) + ' ' + escH(x.moeda || '')], ['fonte', 'Fonte']], r.ebay.itens, 'O eBay não devolveu itens.') + `<p class="small muted">${escH(r.ebay.aviso)}</p>` : `<p class="small muted">${escH((r.ebay || {}).motivo || '')}</p>`}
        <h3>Busca reversa assistida (abre no seu navegador)</h3><ul class="small">${r.busca_externa.servicos.map((s) => `<li>${escH(s.servico)}: ${s.por_url ? `<a href="${escH(s.por_url)}" target="_blank" rel="noopener noreferrer">buscar esta URL</a>` : `<a href="${escH(s.abrir)}" target="_blank" rel="noopener noreferrer">abrir página de envio</a> (envio manual, se você quiser)`}</li>`).join('')}</ul>${notes(r.busca_externa.regras)}<div id="immsg" class="small"></div></section>`;
      document.querySelectorAll('[data-mi]').forEach((a) => { a.onclick = (e) => { e.preventDefault(); monitor('produto', a.dataset.mi, a.dataset.mi, $('#immsg')); }; });
    };
    $('#imgo').onclick = async () => { if (!file) return; $('#imout').innerHTML = loading('Comparando localmente…'); try { results(await raw('/api/suite/imagem/buscar?' + qp(), file, file.name)); } catch (e) { $('#imout').innerHTML = errBox(e); } };
    $('#imub').onclick = async () => { const u = $('#imu').value.trim(); if (!u) return; $('#imout').innerHTML = loading('Baixando e comparando…'); try { results(await raw('/api/suite/imagem/buscar?' + qs({ url: u, familia: $('#imfam').value, ebay: $('#imebay').checked ? '1' : '' }), new Blob([]), 'url')); } catch (e) { $('#imout').innerHTML = errBox(e); } };
    $('#imadd').onclick = async () => { if (!file) return; try { const r = await raw('/api/suite/imagem/catalogo?' + qp() + '&' + qs({ rotulo: $('#imlbl').value, produto_id: $('#impid').value }), file, file.name); $('#imout').innerHTML = `<p class="small">${r.duplicada ? escH(r.mensagem) : 'Imagem adicionada ao catálogo visual.'}</p>`; cat(); } catch (e) { $('#imout').innerHTML = errBox(e); } };
    async function cat() {
      try { const c = await api('/api/suite/imagem/catalogo'); $('#imcat').innerHTML = `<p class="small">Nível avançado (opcional): ${c.avancado.ativo ? 'ativo' : 'desligado'} — ${escH(c.avancado.como_ativar)}</p>${c.itens.length ? `<div class="imgrid">${c.itens.map((x) => `<figure><img src="/api/suite/imagem/${x.image_id}.jpg" alt="" loading="lazy"><figcaption>${escH(x.label)}<br><span class="muted">${escH(x.product_id || '')} · ${escH(x.source)}</span> <a href="#" data-del="${x.image_id}">excluir</a></figcaption></figure>`).join('')}</div>` : '<p class="small muted">Catálogo visual vazio.</p>'}`;
        document.querySelectorAll('[data-del]').forEach((a) => { a.onclick = async (e) => { e.preventDefault(); await post(`/api/suite/imagem/${a.dataset.del}/excluir`, {}); cat(); }; });
      } catch (e) { $('#imcat').innerHTML = errBox(e); }
    }
    cat();
  }

  /* ======================================================================= FORNECEDORES */
  async function pageSuppliers(arg) {
    const a = parseArg(arg);
    if (a.id) return supplierProfile(+a.id);
    main.innerHTML = head('Inteligência de Fornecedores', 'Cadastro canônico de empresas, embarques e relações — sempre com fonte e grau de comprovação. Nada é inventado.') + `
      <p class="small">Cadastro anterior continua em <a href="#conformidade-fornecedores">Conformidade › Cadastro de Fornecedores</a> (copiado para cá, sem apagar).</p>
      <form class="panel btnrow" id="sd"><label class="f" style="flex:1">Descobrir fornecedores por produto<input name="q" value="${escH(a.q || '')}" placeholder="ex.: carregador GaN 65W"></label><button class="btn primary">Descobrir</button></form><div id="sdo"></div>
      <section class="panel"><h2>Empresas</h2><form class="btnrow" id="ss"><input name="q" placeholder="nome" value="${escH(a.nome || '')}"><select name="tipo"><option value="">tipo</option></select><input name="pais" size="4" placeholder="país"><button class="btn small">Buscar</button></form><div id="sl">${loading()}</div></section>
      <details class="panel"><summary><b>Cadastrar empresa</b></summary><form id="sa" class="btnrow" style="flex-wrap:wrap">${[['legal_name', 'Razão social*'], ['display_name', 'Nome exibido'], ['country', 'País'], ['city', 'Cidade'], ['website', 'Site'], ['product_families', 'Produtos (separados por vírgula)'], ['contact', 'Contato'], ['notes', 'Observações']].map(([k, l]) => `<label class="f">${l}<input name="${k}"></label>`).join('')}<label class="f">Tipo<select name="company_type"></select></label><button class="btn small primary">Salvar</button></form><div id="sam" class="small"></div></details>
      <details class="panel"><summary><b>Importar planilha (CSV/XLSX)</b></summary><p class="small">Empresas: razão social, país, cidade, site, produtos, tipo… · Embarques: bill_of_lading, shipper/exportador, consignee/importador, origem, destino, data, descrição, peso. Arquivos com macros são recusados; fórmulas não são executadas.</p>
        <div class="btnrow"><select id="sik"><option value="empresas">Empresas</option><option value="embarques">Embarques</option></select><input id="sif" placeholder="fonte (opcional)"><label class="small"><input type="checkbox" id="sidemo"> dados demonstrativos/de teste</label><input type="file" id="sifile" accept=".csv,.xlsx"></div><div id="sio" class="small"></div></details>
      <details class="panel"><summary><b>Relações documentadas gratuitas (Anatel/Inmetro)</b></summary><p class="small">Gera relações fabricante ↔ titular brasileiro a partir dos registros já carregados. Não comprova exclusividade, volume nem relação comercial ativa.</p><button class="btn small" id="sreg">Gerar a partir dos registros</button><div id="sro" class="small"></div></details>
      <details class="panel" id="sdup"><summary><b>Possíveis duplicidades</b> <span id="sdn"></span></summary><div id="sdl"></div></details>
      <details class="panel"><summary><b>ImportYeti (opcional, pago)</b></summary><div id="siy"></div></details>`;
    const load = async (q = {}) => {
      try { const d = await api('/api/suite/empresas?' + qs(q));
        $('#ss').tipo.innerHTML = '<option value="">tipo</option>' + d.tipos.map((t) => `<option ${q.tipo === t ? 'selected' : ''}>${t}</option>`).join('');
        $('#sa').company_type.innerHTML = d.tipos.map((t) => `<option ${t === 'desconhecido' ? 'selected' : ''}>${t}</option>`).join('');
        $('#sdn').textContent = d.pendentes_revisao ? `(${d.pendentes_revisao} pendente(s))` : '';
        $('#sl').innerHTML = tbl([['legal_name', 'Empresa', (r) => `<a href="#fornecedores-intel/${encodeURIComponent(qs({ id: r.company_id }))}">${escH(r.display_name || r.legal_name)}</a>`], ['country', 'País'], ['company_type', 'Tipo'], ['product_families', 'Produtos', (r) => escH(r.product_families.join(', '))], ['source', 'Fonte'], ['verification_status', 'Verificação']], d.itens, 'Nenhuma empresa cadastrada.');
      } catch (e) { $('#sl').innerHTML = errBox(e); }
    };
    load({ q: a.nome || '' });
    $('#ss').onsubmit = (e) => { e.preventDefault(); load(Object.fromEntries(new FormData($('#ss')))); };
    $('#sa').onsubmit = async (e) => { e.preventDefault(); try { const r = await post('/api/suite/empresas', Object.fromEntries(new FormData($('#sa')))); $('#sam').innerHTML = r.criada ? 'Empresa criada.' : 'Empresa já existia (campos vazios completados).'; load(); } catch (er) { $('#sam').innerHTML = errBox(er); } };
    $('#sifile').onchange = async () => { const f = $('#sifile').files[0]; if (!f) return; $('#sio').innerHTML = loading('Validando e importando…');
      try { const r = await raw(`/api/suite/importar/${$('#sik').value}?` + qs({ fonte: $('#sif').value, demonstrativo: $('#sidemo').checked ? '1' : '' }), f, f.name, f.name.endsWith('.csv') ? 'text/csv' : 'application/octet-stream');
        $('#sio').innerHTML = `<p>${r.linhas} linha(s): ${r.criadas != null ? `${r.criadas} criada(s), ${r.atualizadas} atualizada(s)` : `${r.novos} novo(s), ${r.duplicados} duplicado(s), ${r.relacoes} relação(ões)`}; ${(r.rejeitadas || r.rejeitados || []).length} rejeitada(s).</p>${tbl([['linha', 'Linha'], ['motivo', 'Motivo']], (r.rejeitadas || r.rejeitados || []).slice(0, 30), '')}`; load(); dups(); } catch (er) { $('#sio').innerHTML = errBox(er); } };
    $('#sreg').onclick = async () => { $('#sro').innerHTML = loading(); try { const r = await post('/api/suite/relacoes/regulatorias', {}); $('#sro').innerHTML = `${r.relacoes} relação(ões) a partir de ${r.anatel_registros_lidos} registro(s) Anatel e ${r.inmetro_registros_lidos} Inmetro. ${escH(r.nota)}`; load(); } catch (er) { $('#sro').innerHTML = errBox(er); } };
    async function dups() {
      try { const d = await api('/api/suite/duplicidades');
        $('#sdl').innerHTML = (d.itens.length ? d.itens.map((r) => `<div class="small" data-r="${r.id}"><b>${escH(r.a.legal_name)}</b> (${escH(r.a.country || '—')}) × <b>${escH(r.b.legal_name)}</b> (${escH(r.b.country || '—')}) — ${escH(r.motivos.join('; '))} <button class="btn small" data-dd="mesclar">Mesclar em A</button> <button class="btn small" data-dd="distintas">São distintas</button></div>`).join('') : '<p class="small muted">Nenhuma duplicidade pendente.</p>') + `<p class="small muted">${escH(d.regra)}</p>`;
        document.querySelectorAll('[data-dd]').forEach((b) => { b.onclick = async () => { await post('/api/suite/duplicidades/' + b.closest('[data-r]').dataset.r, { decisao: b.dataset.dd }); dups(); load(); }; });
      } catch (e) { $('#sdl').innerHTML = errBox(e); }
    }
    dups();
    const iy = async () => { try { const s = await api('/api/suite/importyeti'); $('#siy').innerHTML = `<p class="small">Estado: <b>${escH(s.estado)}</b> · cobertura: ${escH(s.cobertura)} · orçamento ${num(s.orcamento)} · gasto ${num(s.gasto)} · restante ${num(s.restante)}</p>${notes(s.limitacoes)}
        <p class="small">Configure a chave e o orçamento em <a href="#suite-config">Configurações da suíte</a>. Com o modo sem custos externos ativo, nenhuma consulta paga é feita.</p>
        <div class="btnrow"><button class="btn small" id="iyf">Consulta gratuita: data da base</button><input id="iyq" placeholder="empresa"><input id="iyc" size="4" placeholder="custo máx."><label class="small"><input type="checkbox" id="iya"> autorizo o gasto desta consulta</label><button class="btn small" id="iyp">Consultar (pago)</button></div><div id="iyo" class="small"></div>`;
        $('#iyf').onclick = async () => { const r = await post('/api/suite/importyeti/atualizacao', {}); $('#iyo').textContent = r.ok ? JSON.stringify(r.resposta).slice(0, 300) : r.mensagem; };
        $('#iyp').onclick = async () => { const r = await post('/api/suite/importyeti/consulta', { consulta: 'company_search', parametros: { name: $('#iyq').value }, autorizado: $('#iya').checked, custo_maximo: +$('#iyc').value || 0, gravar_embarques: true }); $('#iyo').textContent = r.ok ? `Consulta feita: custo ${r.custo}, créditos restantes ${r.creditos_restantes ?? '—'}.` : `${r.mensagem}${r.motivo ? ' (' + r.motivo + ')' : ''}`; };
      } catch (e) { $('#siy').innerHTML = errBox(e); } };
    iy();
    $('#sd').onsubmit = async (e) => { e.preventDefault(); const q = $('#sd').q.value.trim(); if (!q) return; $('#sdo').innerHTML = loading();
      try { const d = await api('/api/suite/descobrir?' + qs({ q })); $('#sdo').innerHTML = `<section class="panel">${TAB.fornecedores(d)}</section>`; } catch (er) { $('#sdo').innerHTML = errBox(er); } };
    if (a.q) $('#sd').requestSubmit();
  }
  async function supplierProfile(cid) {
    main.innerHTML = `<p><a href="#fornecedores-intel">← Fornecedores</a></p><div id="sp">${loading()}</div>`;
    let d;
    try { d = await api('/api/suite/empresas/' + cid); } catch (e) { $('#sp').innerHTML = errBox(e); return; }
    const e = d.empresa, nodes = Object.fromEntries(d.rede.nos.map((n) => [n.id, n]));
    $('#sp').innerHTML = `<h1>${escH(e.display_name || e.legal_name)}</h1><p class="sub">${escH(e.legal_name)} · ${escH(e.country || '—')} ${escH(e.city || '')} · tipo: <b>${escH(e.company_type)}</b> · fonte: ${escH(e.source)} · ${escH(e.verification_status)}</p>
      <div class="btnrow"><button class="btn small" id="spm">${d.monitorada ? 'Monitorada ✓' : 'Monitorar'}</button><a class="btn small" href="/api/suite/empresas/${cid}.xlsx">XLSX</a><a class="btn small" href="/api/suite/empresas/${cid}.pdf">PDF</a><span id="spmsg" class="small"></span></div>
      <p class="small">Aliases: ${escH(e.aliases.join(' · ') || '—')} · produtos: ${escH(e.product_families.join(', ') || '—')} · site: ${e.website ? `<a href="${escH(/^https?:\/\//.test(e.website) ? e.website : 'https://' + e.website)}" target="_blank" rel="noopener noreferrer">${escH(e.website)}</a>` : '—'}</p>${notes(d.regras)}
      <section class="panel"><h2>Relações</h2>${tbl([['de', 'De', (r) => escH((nodes[r.de] || {}).nome || r.de)], ['tipo', 'Relação'], ['para', 'Para', (r) => `<a href="#fornecedores-intel/${encodeURIComponent(qs({ id: r.para === cid ? r.de : r.para }))}">${escH((nodes[r.para] || {}).nome || r.para)}</a>`], ['status', 'Comprovação'], ['fonte', 'Fonte'], ['evidencia', 'Evidência'], ['periodo', 'Período', (r) => escH(r.periodo.filter(Boolean).join(' a ') || '—')], ['confianca', 'Confiança']], d.rede.arestas, 'Nenhuma relação registrada.')}${notes(d.rede.avisos)}</section>
      <section class="panel"><h2>Embarques (${d.cobertura_embarques.total})</h2>${tbl([['date', 'Data'], ['exporter_name', 'Exportador'], ['importer_name', 'Importador'], ['description', 'Descrição'], ['weight_kg', 'Peso kg', (r) => num(r.weight_kg)], ['source', 'Fonte']], d.embarques.slice(0, 100), 'Nenhum embarque.')}${notes(d.cobertura_embarques.limitacoes)}</section>
      <section class="panel"><h2>Avaliação</h2>${Object.entries(d.avaliacao).map(([dim, m]) => `<h3>${escH(dim)}</h3>${Object.entries(m).map(([t, l]) => `<p class="small"><b>${escH(t)}</b>: ${l.map((x) => escH(`${x.campo}: ${x.valor}${x.documento ? ' [' + x.documento + ']' : ''}`)).join(' · ')}</p>`).join('')}`).join('') || '<p class="small muted">Sem avaliações.</p>'}
        <form id="spe" class="btnrow" style="flex-wrap:wrap"><select name="dimensao">${['identificação', 'capacidade declarada', 'certificações', 'qualidade', 'comercial', 'logística', 'comunicação', 'riscos'].map((x) => `<option>${x}</option>`).join('')}</select><input name="campo" placeholder="campo"><input name="valor" placeholder="valor"><select name="tipo"><option value="documental">Evidência documental</option><option value="declarado">Declarado pelo fornecedor</option><option value="avaliação">Minha avaliação</option></select><input name="documento" placeholder="documento (obrigatório p/ documental)"><button class="btn small">Registrar</button></form><div id="speo" class="small"></div></section>
      <section class="panel"><h2>Correspondência com produto (preliminar)</h2><form id="spc" class="btnrow"><input name="q" placeholder="produto"><button class="btn small">Avaliar</button><button class="btn small" type="button" id="spl">Vincular produto (declarado)</button></form><div id="spco" class="small"></div></section>`;
    $('#spm').onclick = () => monitor('fornecedor', String(cid), e.legal_name, $('#spmsg'));
    $('#spe').onsubmit = async (ev) => { ev.preventDefault(); try { await post(`/api/suite/empresas/${cid}/avaliar`, Object.fromEntries(new FormData($('#spe')))); supplierProfile(cid); } catch (er) { $('#speo').innerHTML = errBox(er); } };
    $('#spc').onsubmit = async (ev) => { ev.preventDefault(); try { const r = await api(`/api/suite/empresas/${cid}/correspondencia?` + qs({ q: $('#spc').q.value })); $('#spco').innerHTML = `<p>Confiança: <b>${escH(r.confianca)}</b> (${escH(r.natureza)})</p>${notes(r.motivos)}`; } catch (er) { $('#spco').innerHTML = errBox(er); } };
    $('#spl').onclick = async () => { await post(`/api/suite/empresas/${cid}/produtos`, { familia: $('#spc').q.value, relacao: 'fornece (declarado)' }); $('#spco').textContent = 'Vínculo registrado como DECLARADO.'; };
  }

  /* ======================================================================= INVESTIGAÇÃO DE IMPORTAÇÃO */
  async function pageImport(arg) {
    const a = parseArg(arg);
    main.innerHTML = head('Investigação de Importação', 'NCM candidata, estatísticas agregadas, requisitos regulatórios, riscos e simulador preliminar com os SEUS parâmetros.') + `
      <p class="small">Também: <a href="#viabilidade">Viabilidade de Importação</a> · <a href="#conformidade-analisar">Conformidade › Analisar Produto</a> · <a href="#conformidade-ncm">Classificação NCM</a></p>
      <form class="panel btnrow" id="if"><label class="f" style="flex:1">Produto<input name="q" value="${escH(a.q || '')}"></label><input type="hidden" name="produto" value="${escH(a.produto || '')}"><button class="btn primary">Investigar</button></form><div id="io"></div>
      <section class="panel"><h2>Simulador preliminar</h2><form id="sim" class="btnrow" style="flex-wrap:wrap"></form><div id="simo"></div></section>`;
    $('#if').onsubmit = (e) => { e.preventDefault(); location.hash = '#importacao-intel/' + encodeURIComponent(qs(Object.fromEntries(new FormData($('#if'))))); };
    let fields = null, req = [];
    if (a.q || a.produto) {
      $('#io').innerHTML = loading();
      try { const d = await api('/api/suite/importacao?' + qs({ q: a.q, produto: a.produto }));
        fields = d.simulador.campos; req = d.simulador.obrigatorios;
        $('#io').innerHTML = `<section class="panel"><h2>${escH((d.identificacao || {}).nome_comercial || d.consulta)} ${dec(d.decisao)}</h2><p class="small">${escH(d.decisao.significado)}</p>${notes(d.decisao.motivos)}<section class="kpis compact">${ind(d.indicadores)}</section>
          ${TAB.importacao({ ncm: d.ncm, regulatorio: d.regulatorio, riscos: d.riscos })}
          <h3>Cenários salvos</h3>${tbl([['name', 'Nome'], ['created_at', 'Criado'], ['id', 'Exportar', (r) => `<a href="/api/suite/cenarios/${r.id}.xlsx">XLSX</a> · <a href="/api/suite/cenarios/${r.id}.pdf">PDF</a>`]], d.cenarios, 'Nenhum cenário salvo.')}</section>`;
      } catch (e) { $('#io').innerHTML = errBox(e); }
    }
    if (!fields) { try { const d = await api('/api/suite/importacao?' + qs({ q: 'produto' })); fields = d.simulador.campos; req = d.simulador.obrigatorios; } catch { fields = {}; } }
    $('#sim').innerHTML = Object.entries(fields).map(([k, l]) => `<label class="f">${escH(l)}${req.includes(k) ? '*' : ''}<input name="${k}" size="9" inputmode="decimal"></label>`).join('') + '<label class="f">Nome do cenário<input name="_nome"></label><button class="btn primary small">Calcular</button><label class="small"><input type="checkbox" name="_salvar"> salvar</label>';
    $('#sim').onsubmit = async (e) => {
      e.preventDefault();
      const fd = Object.fromEntries(new FormData($('#sim')));
      const p = Object.fromEntries(Object.entries(fd).filter(([k, v]) => !k.startsWith('_') && v !== ''));
      try { const r = await post('/api/suite/simular', { parametros: p, salvar: !!fd._salvar, nome: fd._nome, produto_id: a.produto || null });
        $('#simo').innerHTML = !r.calculado ? `<div class="banner">${escH(r.mensagem || '')} Faltam: ${escH(r.pendentes_obrigatorios.join(', '))}</div>` :
          `${tbl([['k', 'Indicador'], ['Conservador', 'Conservador'], ['Base', 'Base'], ['Otimista', 'Otimista']], ['fob_total_usd', 'fob_total_brl', 'frete_por_unidade_brl', 'custo_total_brl', 'custo_unitario_brl', 'preco_venda_unit_brl', 'receita_liquida_unit_brl', 'margem_bruta_unit_brl', 'margem_bruta_pct', 'markup'].map((k) => ({ k, Conservador: num(r.cenarios.Conservador[k], 2), Base: num(r.cenarios.Base[k], 2), Otimista: num(r.cenarios.Otimista[k], 2) })))}
          ${r.pendentes.length ? `<p class="small"><span class="badge demo">INCOMPLETO</span> Não informados: ${escH(r.pendentes.join(', '))}</p>` : ''}${notes(r.avisos)}${r.salvo ? `<p class="small">Cenário salvo: <a href="/api/suite/cenarios/${r.salvo.id}.xlsx">XLSX</a> · <a href="/api/suite/cenarios/${r.salvo.id}.pdf">PDF</a></p>` : ''}`;
      } catch (er) { $('#simo').innerHTML = errBox(er); }
    };
  }

  /* ======================================================================= MONITORADOS · HISTÓRICO · CONFIG */
  async function pageMonitored() {
    main.innerHTML = head('Produtos Monitorados', 'Produtos e fornecedores acompanhados. Atualizados ao fim de cada sincronização (mesma rotina semanal).') + `<div class="btnrow"><button class="btn small" id="mra">Atualizar agora</button></div><div id="mo">${loading()}</div>`;
    const load = async () => { try { const d = await api('/api/suite/monitorados');
      $('#mo').innerHTML = tbl([['kind', 'Tipo'], ['label', 'Item', (r) => r.kind === 'produto' ? `<a href="#dossie/${encodeURIComponent(r.ref)}">${escH(r.label)}</a>` : `<a href="#fornecedores-intel/${encodeURIComponent(qs({ id: r.ref }))}">${escH(r.label)}</a>`],
        ['semanal', 'Coleta', (r) => r.semanal ? `<span class="badge ok">semanal</span> <span class="muted">${escH(Object.values(r.params.termos || {}).join(' / '))} · ${escH(r.params.mercado || '')}</span>` : '<span class="muted">só acompanhamento</span>'], ['last_checked', 'Verificado'], ['snap', 'Situação atual', (r) => escH(Object.entries(r.last_snapshot || {}).filter(([, v]) => v != null).map(([k, v]) => `${k}: ${typeof v === 'number' ? fmt(v, 1) : v}`).join(' · ') || 'ainda não verificado')],
        ['ev', 'Mudanças recentes', (r) => r.eventos.length ? r.eventos.slice(0, 3).map((e) => `${escH(e.at.slice(0, 10))}: ${escH(e.mudancas.map((m) => `${m.campo} ${m.antes ?? '—'} → ${m.depois ?? '—'}`).join('; '))}`).join('<br>') : '<span class="muted">nenhuma</span>'],
        ['x', '', (r) => `<a href="#" data-x="${r.id}">remover</a>`]], d.itens, 'Nada monitorado. Use “Monitorar” na pesquisa, no nicho ou no fornecedor.') + notes([d.nota]);
      document.querySelectorAll('[data-x]').forEach((a) => { a.onclick = async (e) => { e.preventDefault(); await post(`/api/suite/monitorados/${a.dataset.x}/excluir`, {}); load(); }; });
    } catch (e) { $('#mo').innerHTML = errBox(e); } };
    $('#mra').onclick = async () => { $('#mo').innerHTML = loading('Atualizando…'); await post('/api/suite/monitorados/atualizar', {}); load(); };
    load();
  }
  async function pageHistory() {
    main.innerHTML = head('Histórico de Pesquisas', 'Todas as pesquisas de produto, com parâmetros e resultado.') + `<div id="ho">${loading()}</div>`;
    try { const d = await api('/api/suite/historico');
      $('#ho').innerHTML = tbl([['query', 'Pesquisa', (r) => `<a href="#pesquisa-produtos/${encodeURIComponent(qs({ id: r.id }))}">${escH(r.query)}</a>${r.nome_comercial && r.nome_comercial !== r.query ? ` <span class="muted">(${escH(r.nome_comercial)})</span>` : ''}`], ['decisao', 'Decisão', (r) => r.decisao ? dec({ cor: r.decisao }) : '—'], ['cobertura', 'Fontes c/ evidência', (r) => num(r.cobertura)], ['p', 'Parâmetros', (r) => escH(`${r.params.mercado || ''} · ${r.params.periodo_meses || ''} meses · ${r.params.profundidade || ''}`)], ['status', 'Estado'], ['product_id', 'Produto'], ['created_at', 'Criada'], ['saved', 'Salva', (r) => r.saved ? '✓' : ''], ['x', 'Exportar', (r) => r.finished_at ? `<a href="/api/suite/pesquisa/${r.id}.xlsx">XLSX</a> · <a href="/api/suite/pesquisa/${r.id}.pdf">PDF</a>` : '']], d.itens, 'Nenhuma pesquisa ainda.');
    } catch (e) { $('#ho').innerHTML = errBox(e); }
  }
  async function pageConfig() {
    main.innerHTML = head('Configurações da Product Intelligence', 'Padrões da suíte, provedores, capacidades e controle de custos. Por padrão: modo sem custos externos.') + `<div id="co">${loading()}</div>`;
    let c, p;
    try { [c, p] = await Promise.all([api('/api/suite/config'), api('/api/suite/provedores')]); } catch (e) { $('#co').innerHTML = errBox(e); return; }
    const s = c.configuracoes;
    $('#co').innerHTML = `<form class="panel" id="cf"><div class="btnrow" style="flex-wrap:wrap;gap:8px">
        <label class="f">País padrão<input name="pais_padrao" size="4" value="${escH(s.pais_padrao)}"></label><label class="f">Idioma<select name="idioma">${['pt', 'en'].map((x) => `<option ${s.idioma === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
        <label class="f">Período padrão<select name="periodo_meses">${[3, 6, 12, 24].map((x) => `<option ${s.periodo_meses === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
        <label class="f">Modo padrão<select name="modo"><option value="rapida" ${s.modo === 'rapida' ? 'selected' : ''}>Rápida</option><option value="completa" ${s.modo === 'completa' ? 'selected' : ''}>Completa</option></select></label>
        <label class="small"><input type="checkbox" name="usar_cache" ${s.usar_cache ? 'checked' : ''}> usar cache</label><label class="small"><input type="checkbox" name="imagens_local" checked disabled> processamento local de imagens</label>
        <label class="small"><input type="checkbox" name="modelos_opcionais" ${s.modelos_opcionais ? 'checked' : ''}> modelos opcionais (embeddings locais)</label></div>
        <h3>Controle financeiro</h3><div class="btnrow" style="flex-wrap:wrap"><label class="small"><input type="checkbox" name="sem_custos" ${s.sem_custos ? 'checked' : ''}> <b>modo sem custos externos</b> (nenhum crédito pago é consumido)</label>
        <label class="f">Orçamento de créditos<input name="orcamento_creditos" size="6" value="${escH(s.orcamento_creditos)}"></label><label class="small"><input type="checkbox" name="aprovar_creditos" ${s.aprovar_creditos ? 'checked' : ''}> exigir aprovação por consulta</label>
        <label class="f">Chave ImportYeti (opcional)<input name="importyeti_chave" type="password" autocomplete="off" placeholder="${c.importyeti.configurado ? '(configurada — deixe vazio para manter)' : ''}"></label></div>
        <button class="btn primary">Salvar</button> <span id="cfo" class="small"></span></form>
      <section class="panel"><h2>Provedores</h2>${tbl([['fonte', 'Fonte'], ['status', 'Status'], ['capacidades', 'Capacidades', (r) => escH(r.capacidades.join(', '))], ['custo', 'Custos'], ['limitacoes', 'Limitações']], p.provedores)}
        <h3>Não utilizados</h3>${tbl([['nome', 'Serviço'], ['motivo', 'Motivo']], p.excluidos)}</section>
      <section class="panel"><h2>Busca visual avançada (opcional)</h2><p class="small">${c.visual_avancado.ativo ? 'Ativa.' : 'Desligada.'} ${escH(c.visual_avancado.como_ativar)}</p><p class="small muted">Caminho: ${escH(c.visual_avancado.caminho_esperado)}</p></section>`;
    $('#cf').onsubmit = async (e) => {
      e.preventDefault();
      const f = $('#cf'), b = { pais_padrao: f.pais_padrao.value, idioma: f.idioma.value, periodo_meses: +f.periodo_meses.value, modo: f.modo.value, usar_cache: f.usar_cache.checked,
        modelos_opcionais: f.modelos_opcionais.checked, sem_custos: f.sem_custos.checked, orcamento_creditos: +f.orcamento_creditos.value || 0, aprovar_creditos: f.aprovar_creditos.checked };
      if (f.importyeti_chave.value) b.importyeti_chave = f.importyeti_chave.value;
      try { await post('/api/suite/config', b); f.importyeti_chave.value = ''; $('#cfo').textContent = 'Salvo.'; } catch (er) { $('#cfo').innerHTML = errBox(er); }
    };
  }

  /* ======================================================================= DASHBOARD E DOSSIÊ (integração) */
  const baseDash = PAGES.dashboard, baseDossie = PAGES.dossie;
  function consol(c) {                  // v0.9.1 MVP: visão consolidada (dados reais do banco; motivo + ação quando vazio)
    if (!c || c.erro) return c && c.erro ? `<p class="small muted">Visão consolidada indisponível: ${escH(c.erro)}</p>` : '';
    const A = c.portfolio, V = c.vazios || {};
    const k = (l, n, h) => `<a class="kpi" href="${h}"><div class="v">${num(n)}</div><div class="l">${l}</div></a>`;
    const empty = (m) => m ? `<p class="small muted">${escH(m)}</p>` : '';
    return `<p class="small"><b>A. Portfólio</b></p><section class="kpis compact">${k('Investigações abertas', A.investigacoes_abertas, '#investigacoes')}${k('Oportunidades elegíveis', A.oportunidades_elegiveis, '#inteligencia-oportunidades')}${k('Com crescimento observado', A.com_crescimento_observado, '#inteligencia-oportunidades')}${k('Dados insuficientes', A.dados_insuficientes, '#inteligencia-oportunidades')}</section>
      <div class="two"><div><p class="small"><b>B. Mercado</b> — maiores evidências de interesse</p>${c.mercado.maior_interesse.length ? tbl([['produto', 'Produto', (r) => `<a href="#dossie/${encodeURIComponent(r.produto_id)}">${escH(r.produto)}</a>`], ['score', 'Score', (r) => num(r.score, 1)], ['estagio', 'Estágio'], ['situacao', 'Situação']], c.mercado.maior_interesse) : empty(V.mercado)}
        <p class="small muted">Categorias: ${escH(c.mercado.categorias.map(([x, n]) => `${x} (${n})`).join(' · ') || '—')} · mercados: ${escH(c.mercado.por_mercado.map(([x, n]) => `${x} (${n})`).join(' · ') || '—')}</p>
        ${c.mercado.recem_identificados.length ? `<p class="small muted">Recém-identificados: ${c.mercado.recem_identificados.map((r) => `<a href="${goResearch(r.produto)}">${escH(r.produto)}</a>`).join(' · ')}</p>` : ''}</div>
      <div><p class="small"><b>C. Concorrência</b> — ${num(c.concorrencia.produtos_com_anuncios)} produto(s) com anúncios · ${num(c.concorrencia.marcas_identificadas)} marca(s)</p>${c.concorrencia.faixas_preco.length ? tbl([['produto', 'Produto', (r) => `<a href="${goResearch(r.produto)}">${escH(r.produto)}</a>`], ['elegiveis', 'Elegíveis/anúncios', (r) => `${num(r.elegiveis)}/${num(r.anuncios)}`], ['faixa', 'Faixa/unid.', (r) => r.mediana == null ? '—' : `${num(r.preco_min, 2)}–${num(r.preco_max, 2)} (med. ${num(r.mediana, 2)}) ${escH(r.moeda || '')}`]], c.concorrencia.faixas_preco) : empty(V.concorrencia)}<p class="small muted">${escH(c.concorrencia.nota)}</p></div></div>
      <div class="two"><div><p class="small"><b>D. Comércio exterior</b> — ${num(c.comex.ncm_monitoradas)} NCM</p>${c.comex.maiores_variacoes.length ? tbl([['ncm', 'NCM'], ['pais', 'Origem'], ['variacao_pct', 'Var. 12m', (r) => num(r.variacao_pct, 1) + '%'], ['ultimos_12m', 'Últimos 12m (FOB)', (r) => num(r.ultimos_12m)]], c.comex.maiores_variacoes.slice(0, 6)) : empty(V.comex)}<p class="small muted">${escH(c.comex.nota)}</p></div>
      <div><p class="small"><b>E. Qualidade dos dados</b></p><p class="small">${num(c.qualidade.fontes_funcionando)} fonte(s) funcionando · última sincronização: ${escH((c.qualidade.ultima_sincronizacao || '—').slice(0, 16))} · alertas de qualidade: ${num(c.qualidade.alertas_qualidade)}</p>
        ${c.qualidade.fontes_indisponiveis.length ? `<p class="small">Indisponíveis: ${escH(c.qualidade.fontes_indisponiveis.map((f) => `${f.fonte} (${f.estado})`).join(' · '))} — <a href="#diagnostico-integracoes">diagnóstico</a></p>` : ''}
        <p class="small muted">Coberturas das últimas pesquisas: ${escH(Object.entries(c.qualidade.coberturas_ultimas_pesquisas || {}).map(([k2, v2]) => `${k2}: ${Object.entries(v2).map(([n, q]) => `${q} ${n}`).join(', ')}`).join(' · ') || '—')}</p></div></div>`;
  }
  async function dashboard(arg) {
    await baseDash(arg);
    const box = document.createElement('section');
    box.className = 'panel';
    box.innerHTML = `<h2>Product Intelligence</h2><div id="pi">${loading()}</div>`;
    main.insertBefore(box, main.children[2] || null);
    try { const v = await api('/api/suite/visao'), c = v.contagens;
      const pr = v.produtos, nt = v.notas;
      $('#pi').innerHTML = `${v.tem_demonstrativos ? `<div class="banner warn small">Há dados <b>demonstrativos/de teste</b> no banco (${escH(Object.entries(v.demonstrativos).filter(([, n]) => n).map(([k, n]) => `${n} ${k.replace(/_/g, ' ')}`).join(' · '))}); eles ficam fora das contagens abaixo.</div>` : ''}
        <p class="small"><b>Produtos</b></p><section class="kpis compact">${[['Cadastrados', pr.cadastrados, '#catalogo', nt.cadastrados], ['Identificados', pr.identificados, '#catalogo', nt.identificados], ['Com evidência comercial', pr.com_evidencias_comerciais, '#inteligencia-oportunidades', nt.com_evidencias_comerciais], ['Monitorados', pr.monitorados, '#monitorados', ''], ['Investigação concluída', pr.investigacao_concluida, '#historico-pesquisas', nt.investigacao_concluida], ['Investigação inconclusiva', pr.investigacao_inconclusiva, '#historico-pesquisas', nt.investigacao_inconclusiva]].map(([l, n, h, tip]) => `<a class="kpi" href="${h}" title="${escH(tip)}"><div class="v">${num(n)}</div><div class="l">${l}</div></a>`).join('')}</section>
        ${consol(v.consolidado)}
        <p class="small"><b>Fornecedores e imagens</b></p><section class="kpis compact">${[['Empresas', c.empresas, '#fornecedores-intel'], ['Embarques', c.embarques, '#fornecedores-intel'], ['Fornecedores monitorados', c.fornecedores_monitorados, '#monitorados'], ['Imagens no catálogo', c.imagens_catalogo, '#pesquisa-imagem'], ['Duplicidades p/ revisar', c.duplicidades_pendentes, '#fornecedores-intel']].map(([l, n, h]) => `<a class="kpi" href="${h}"><div class="v">${num(n)}</div><div class="l">${l}</div></a>`).join('')}</section>
        <div class="btnrow" style="flex-wrap:wrap"><a class="btn small primary" href="#pesquisa-produtos">Pesquisar produto</a><a class="btn small" href="#nichos">Explorar nichos</a><a class="btn small" href="#palavras-chave">Palavras-chave</a><a class="btn small" href="#pesquisa-imagem">Pesquisa por imagem</a><a class="btn small" href="#fornecedores-intel">Fornecedores</a><a class="btn small" href="#importacao-intel">Importação</a></div>
        <p class="small muted">${v.modo_sem_custos ? 'Modo sem custos externos ativo.' : '<b>Modo sem custos desligado</b> — consultas pagas exigem autorização e orçamento.'} <a href="#suite-config">Configurações</a></p>
        ${v.recentes.length ? `<p class="small">Recentes: ${v.recentes.map((r) => `<a href="#pesquisa-produtos/${encodeURIComponent(qs({ id: r.id }))}">${escH(r.query)}</a>`).join(' · ')}</p>` : ''}`;
    } catch (e) { $('#pi').innerHTML = errBox(e); }
  }
  async function dossie(arg) {
    await baseDossie(arg);
    const pid = decodeURIComponent(arg || '');
    if (!pid) return;
    const h1 = main.querySelector('h1');
    const name = h1 ? h1.textContent.trim() : pid;
    const bar = document.createElement('div');
    bar.className = 'btnrow';
    bar.innerHTML = `<a class="btn small primary" href="#pesquisa-produtos/${encodeURIComponent(qs({ q: name || pid, auto: '1' }))}">Investigar Produto (Pesquisa completa)</a>
      <a class="btn small" href="#importacao-intel/${encodeURIComponent(qs({ q: name, produto: pid }))}">Investigação de importação</a><a class="btn small" href="#fornecedores-intel/${encodeURIComponent(qs({ q: name }))}">Fornecedores</a>
      <a class="btn small" href="#mkt-intel/${encodeURIComponent(qs({ produto: pid }))}">Tendências</a><button class="btn small" id="v91m">Monitorar</button><span id="v91o" class="small"></span>`;
    (h1 && h1.nextSibling ? main.insertBefore(bar, h1.nextSibling.nextSibling || null) : main.prepend(bar));
    $('#v91m').onclick = () => monitor('produto', pid, name, $('#v91o'));
  }

  /* ======================================================================= DIAGNÓSTICO DE INTEGRAÇÕES */
  const DST = { 'Funcional': 'ok', 'Funcional sem resultados': 'demo', 'Autorizada': 'demo', 'Configurada': '', 'Não configurada': '', 'Permissão insuficiente': 'bad',
    'Token expirado': 'bad', 'Bloqueada pela rede': 'bad', 'Limite de requisições': 'bad', 'Indisponível': 'bad' };
  async function pageDiagnostics() {
    main.innerHTML = head('Diagnóstico de Integrações', 'Estado real de cada fonte usada pela Pesquisa de Produtos. O teste usa uma operação autorizada de baixo custo, não consome créditos pagos e não altera credenciais.') + `
      <p class="small">Configuração das contas: <a href="#integracoes">Central de Integrações</a> · histórico das coletas: <a href="#fontes">Saúde das Fontes</a></p><div id="dg">${loading()}</div>
      <section class="panel"><h2>Teste de pesquisa no Mercado Livre</h2><p class="small">Mostra anúncios devolvidos pela API oficial <b>sem gravar</b> no banco. Preço anunciado não é preço de venda; vendas não são informadas.</p>
        <div class="btnrow"><input id="mlq" value="Carregador GaN 65W" size="28">${['Fritadeira elétrica', 'Carregador GaN 65W', 'Aspirador robô'].map((q) => `<button class="btn small" data-mlq="${escH(q)}">${escH(q)}</button>`).join('')}<button class="btn primary small" id="mlgo">Pesquisar</button></div><div id="mlo"></div></section>`;
    const load = async () => { try { const d = await api('/api/suite/diagnostico');
      $('#dg').innerHTML = tbl([['nome', 'Integração'], ['estado', 'Estado', (r) => `<span class="badge ${DST[r.estado] || ''}">${escH(r.estado)}</span>`], ['configuracao', 'Configuração'], ['autenticacao', 'Autenticação'],
        ['permissoes', 'Permissões verificadas', (r) => escH(r.permissoes.join(', ') || '—')], ['capacidades', 'Capacidades', (r) => escH(r.capacidades.join(', '))],
        ['ultima_tentativa', 'Última tentativa', (r) => escH((r.ultima_tentativa || '—').slice(0, 16))], ['ultima_sucesso', 'Último sucesso', (r) => escH((r.ultima_sucesso || '—').slice(0, 16))],
        ['erro_recente', 'Erro mais recente', (r) => escH(r.erro_recente || '—')], ['dados', 'Dados', (r) => escH(r.dados.registros_na_ultima_coleta != null ? `${r.dados.registros_na_ultima_coleta} registro(s)` : '—')],
        ['acao', 'Ação necessária', (r) => `${escH(r.acao || '—')}${r.configuracao === 'não configurada' ? ` <a class="btn small" href="${escH(r.central)}">Configurar</a>` : ''}`],
        ['t', '', (r) => `<button class="btn small" data-test="${escH(r.id)}">Testar conexão</button>`]], d.itens) + notes(d.regras);
      document.querySelectorAll('[data-test]').forEach((b) => { b.onclick = async () => { b.disabled = true; b.textContent = 'Testando…';
        try { const r = await post(`/api/suite/diagnostico/${b.dataset.test}/testar`, {}); await load();
          const tr = document.querySelector(`[data-test="${r.id}"]`); if (tr) tr.closest('tr').insertAdjacentHTML('afterend', `<tr><td colspan="12" class="small">${escH(r.estado)} — ${escH(r.mensagem || '')}${(r.etapas || []).map((e) => `<br>· ${escH(e.etapa)}: ${e.ok ? 'ok' : 'falhou'} ${escH(e.detalhe || '')}`).join('')}${r.acao ? `<br><b>Ação:</b> ${escH(r.acao)}` : ''}</td></tr>`);
        } catch (e) { b.textContent = 'Falhou'; } }; });
    } catch (e) { $('#dg').innerHTML = errBox(e); } };
    load();
    const ml = async (q) => { $('#mlo').innerHTML = loading('Consultando a API do Mercado Livre…');
      try { const r = await post('/api/suite/diagnostico/mercadolivre/pesquisa', { q });
        $('#mlo').innerHTML = r.ok ? `<p class="small">${r.itens.length} anúncio(s) exibidos (total informado pela API: ${num(r.total_api)}).</p>${tbl([['produto', 'Produto'], ['titulo', 'Título', (x) => x.link ? `<a href="${escH(x.link)}" target="_blank" rel="noopener noreferrer">${escH(x.titulo)}</a>` : escH(x.titulo)], ['preco_anunciado', 'Preço anunciado', (x) => num(x.preco_anunciado, 2)], ['moeda', 'Moeda'], ['marketplace', 'Marketplace'], ['id', 'Identificador'], ['coletado_em', 'Coleta'], ['caracteristicas', 'Características', (x) => escH(Object.entries(x.caracteristicas).map(([k, v]) => `${k}: ${v}`).join(' · '))]], r.itens, 'A API não devolveu anúncios para o termo.')}${notes(r.avisos)}`
          : `<div class="banner"><b>${escH(r.estado)}</b> — ${escH(r.mensagem)}<br>${escH(r.acao || '')} ${r.estado === 'Não configurada' || r.causa === 'token' ? '<a class="btn small" href="#integracoes/mercadolivre">Abrir Central de Integrações</a>' : ''}</div>`;
      } catch (e) { $('#mlo').innerHTML = errBox(e); } };
    $('#mlgo').onclick = () => ml($('#mlq').value);
    document.querySelectorAll('[data-mlq]').forEach((b) => { b.onclick = () => { $('#mlq').value = b.dataset.mlq; ml(b.dataset.mlq); }; });
  }
  const baseInteg = PAGES.integracoes;
  async function integracoes(arg) {           // #integracoes/<id>: abre a Central já posicionada na integração pedida
    await baseInteg(arg);
    const id = decodeURIComponent(arg || '');
    if (!id) return;
    const el = document.getElementById('integ-' + id);
    if (el) { el.scrollIntoView({ block: 'start' }); el.style.outline = '2px solid var(--accent)'; setTimeout(() => { el.style.outline = ''; }, 4000); }
  }

  return { 'pesquisa-produtos': pageResearch, nichos: pageNiches, 'palavras-chave': pageKeywords, 'mkt-intel': pageMarket, 'pesquisa-imagem': pageImage,
    'fornecedores-intel': pageSuppliers, 'importacao-intel': pageImport, monitorados: pageMonitored, 'historico-pesquisas': pageHistory, 'suite-config': pageConfig,
    'diagnostico-integracoes': pageDiagnostics, ...(baseInteg ? { integracoes } : {}), dashboard, dossie };
};
