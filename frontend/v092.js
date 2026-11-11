/* GPI v0.9.1 — Trade + Product Intelligence: Início (dois motores), Painel de Importações (evolução histórica por
   classificação e país), Empresas e Embarques (embarques documentados, importação de B/L/manifestos), Assistente IA
   (respostas a partir das ferramentas reais do GPI) e Matriz de Fontes. Nenhum número é inventado: tudo vem do backend. */
window.GPI_V092 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, errBox, main, $ } = H;
  const num = (v, d = 0) => v == null ? '—' : fmt(v, d);
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== '' && v != null).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  const tbl = (cols, rows, empty) => rows && rows.length ? `<div class="tw"><table class="small compact"><thead><tr>${cols.map((c) => `<th>${escH(c[1])}</th>`).join('')}</tr></thead><tbody>${rows.map((r) =>
    `<tr>${cols.map((c) => `<td>${c[2] ? c[2](r) : escH(r[c[0]] == null ? '—' : (typeof r[c[0]] === 'number' ? fmt(r[c[0]], 2) : String(r[c[0]])))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : `<p class="small muted">${escH(empty || 'Sem dados.')}</p>`;
  const notes = (a) => (a || []).filter(Boolean).length ? `<ul class="clean small muted">${a.filter(Boolean).map((x) => `<li>${escH(x)}</li>`).join('')}</ul>` : '';
  const head = (t, sub) => `<h1>${t}</h1><p class="sub">${sub}</p>`;
  const pct = (v) => v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v, 1)}%`;
  const bars = (rows, key) => {                       // mini-gráfico de barras (SVG inline, sem dependências)
    const v = rows.map((r) => r[key] || 0); const mx = Math.max(...v, 1); const w = Math.max(4, Math.floor(640 / Math.max(v.length, 1)));
    return `<svg viewBox="0 0 ${w * v.length} 80" class="minibars" role="img" aria-label="evolução mensal" style="width:100%;max-width:680px;height:80px">${v.map((x, i) =>
      `<rect x="${i * w}" y="${80 - (x / mx) * 76}" width="${w - 1}" height="${(x / mx) * 76}" fill="var(--accent)"><title>${escH(rows[i].mes)}: ${fmt(x, 0)}</title></rect>`).join('')}</svg>`;
  };
  async function raw(path, body, name) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(name || 'arquivo') }, body });
  }

  /* ======================================================================= INÍCIO — DOIS MOTORES */
  const chooser = () => `<section class="panel"><div class="btnrow" style="flex-wrap:wrap;gap:12px">
      <a class="btn primary" href="#trade" style="flex:1 1 260px;padding:16px"><b>Investigar importações</b><br><span class="small">NCM/HS/HTS · evolução histórica · países · empresas e embarques</span></a>
      <a class="btn primary" href="#pesquisa-produtos" style="flex:1 1 260px;padding:16px"><b>Descobrir oportunidades de produtos</b><br><span class="small">tendências · marketplaces · URL/imagem · Opportunity Engine</span></a>
      <a class="btn" href="#assistente" style="flex:0 1 200px;padding:16px"><b>Perguntar ao assistente</b><br><span class="small">análises com os dados do GPI</span></a></div></section>`;
  async function inicio() {
    main.innerHTML = head('Global Product Intelligence', 'Trade Intelligence + Product Intelligence. Escolha por onde começar.') + chooser() +
      `<section class="panel"><h2>Atalhos</h2><div class="btnrow" style="flex-wrap:wrap">
        <a class="btn small" href="#empresas-embarques">Empresas e embarques</a><a class="btn small" href="#mkt-intel">Marketplaces</a>
        <a class="btn small" href="#pesquisa-imagem">Pesquisa por imagem</a><a class="btn small" href="#oportunidades-consumo">Opportunity Engine</a>
        <a class="btn small" href="#matriz-fontes">Matriz de fontes</a><a class="btn small" href="#diagnostico-integracoes">Diagnóstico</a></div></section>`;
  }
  const baseDash = PAGES.dashboard;
  async function dashboard(arg) {
    if (baseDash) await baseDash(arg);
    if (main.querySelector('#gpi-two')) return;
    main.insertAdjacentHTML('afterbegin', `<div id="gpi-two">${chooser()}</div>`);
  }

  /* ======================================================================= TRADE INTELLIGENCE */
  async function trade(arg) {
    const a = Object.fromEntries(new URLSearchParams(arg || ''));
    main.innerHTML = head('Painel de Importações', 'Estatísticas OFICIAIS por classificação (NCM/SH no Brasil — Comex Stat; HS/HTS nos EUA — Census) e país de origem. ' +
      'A estatística descreve a classificação inteira, não um produto ou empresa.') + `
      <form class="panel" id="tf"><div class="btnrow" style="flex-wrap:wrap;gap:8px">
        <label class="f" style="flex:2 1 220px">Produto ou categoria<input name="q" value="${escH(a.q || '')}" placeholder="ex.: máquina de waffle"></label>
        <label class="f">ou código NCM/SH/HTS<input name="codigo" value="${escH(a.codigo || '')}" placeholder="ex.: 85167990" size="12"></label>
        <label class="f">Mercado<select name="mercado"><option value="BR">Brasil</option><option value="US" ${a.mercado === 'US' ? 'selected' : ''}>Estados Unidos</option></select></label>
        <label class="f">Período<select name="meses">${[12, 24, 36, 60].map((m) => `<option value="${m}" ${String(m) === (a.meses || '36') ? 'selected' : ''}>${m} meses</option>`).join('')}</select></label>
        <button class="btn primary">Analisar</button></div></form><div id="tout"></div><div id="tpanel">${loading('Carregando painel…')}</div>`;
    $('#tf').onsubmit = (ev) => { ev.preventDefault(); const f = new FormData(ev.target); location.hash = '#trade/' + qs(Object.fromEntries(f)); };
    api('/api/suite/trade/painel').then((p) => {
      const g = p.crescimento_categorias;
      $('#tpanel').innerHTML = `<section class="panel"><h2>Posições SH4 com maior crescimento — importações brasileiras (12m × 12m anteriores)</h2>
        ${tbl([['codigo', 'SH4'], ['descricao', 'Descrição'], ['categoria', 'Categoria'], ['ultimos_12m_usd', 'US$ FOB 12m', (r) => num(r.ultimos_12m_usd)],
          ['variacao_12m_pct', 'Variação', (r) => pct(r.variacao_12m_pct)], ['ate', 'Até'], ['x', '', (r) => `<a class="btn small" href="#trade/${qs({ codigo: r.codigo, mercado: 'BR' })}">Detalhar por país</a>`]], g.itens, g.vazio)}
        ${notes([g.fonte, g.aviso])}</section>
        <section class="panel"><h2>Consultas recentes às fontes oficiais</h2>${tbl([['source', 'Fonte'], ['reporter', 'Mercado'], ['code', 'Código'], ['period_from', 'De'], ['period_to', 'Até'],
          ['state', 'Estado'], ['rows', 'Linhas'], ['message', 'Mensagem'], ['queried_at', 'Quando']], p.consultas_recentes, 'Nenhuma consulta ainda.')}
        ${tbl([['mercado', 'Mercado'], ['fonte', 'Fonte'], ['granularidade', 'Granularidade'], ['estado', 'Estado', (r) => escH(r.estado || 'consulta direta')]], p.fontes)}</section>`;
    }).catch((e) => { $('#tpanel').innerHTML = errBox(e); });
    if (!(a.q || a.codigo)) return;
    const out = $('#tout');
    out.innerHTML = loading('Consultando fontes oficiais (pode levar alguns segundos; respeita limites de requisição)…');
    try {
      const r = await api('/api/suite/trade/relatorio?' + qs(a));
      out.innerHTML = `<section class="panel"><h2>${escH(r.titulo)}</h2>
        ${r.produto ? `<p class="small">Produto entendido: <b>${escH(r.produto.nome || '—')}</b> · categoria ${escH(r.produto.categoria || '—')} · ${escH(r.produto.estado || '')}</p>` : ''}
        <h3>Códigos candidatos</h3>${tbl([['codigo', 'Código'], ['tipo', 'Tipo'], ['abrangencia', 'Abrangência'], ['confianca', 'Confiança'], ['origem', 'Origem']], r.codigos_candidatos, 'Nenhum código candidato — informe a NCM/HS.')}
        ${notes([r.aviso_codigos])}<h3>Conclusões</h3><ul>${r.conclusoes.map((c) => `<li>${escH(c)}</li>`).join('')}</ul>${notes(r.limitacoes)}
        <div class="btnrow"><a class="btn small" href="/api/suite/trade/relatorio.xlsx?${qs(a)}">Exportar XLSX</a><a class="btn small" href="/api/suite/trade/relatorio.pdf?${qs(a)}">Exportar PDF</a></div></section>
        ${r.classificacoes.map((b) => { const an = b.analise; const v = an.variacoes || {}; return `<section class="panel"><h2>${escH(b.tipo_codigo)} ${escH(b.codigo)} — ${b.mercado === 'BR' ? 'Brasil' : 'EUA'}</h2>
          <p class="small">${escH(b.fonte)} · ${escH(b.modo)} · consulta: <b>${escH(b.consulta.state || '—')}</b>${b.consulta.cache ? ' (cache)' : ''} ${escH(b.consulta.message || '')} · período ${escH(b.periodo.de)} a ${escH(b.periodo.ate)}</p>
          ${an.meses ? `${bars(an.mensal, 'valor_usd')}
          <div class="kpis small">Últimos 12m: <b>US$ ${num(v.ultimos_12m_usd)}</b> · variação 12m: <b>${pct(v.variacao_12m_pct)}</b>${v.variacao_12m_kg_pct != null ? ` · peso: ${pct(v.variacao_12m_kg_pct)}` : ''} · CAGR: ${v.cagr_pct != null ? `${pct(v.cagr_pct)} (${escH(v.cagr_periodo)})` : escH(v.cagr_nota || '—')} · China 12m: ${pct(b.china.variacao_12m_pct)}</div>
          <h3>Anual</h3>${tbl([['ano', 'Ano'], ['valor_usd', 'US$', (x) => num(x.valor_usd)], ['kg', 'kg', (x) => num(x.kg)], ['meses', 'Meses'], ['variacao_pct', 'Var.', (x) => pct(x.variacao_pct)]], an.anual)}
          <h3>Países de origem (12 meses)</h3>${tbl([['pais', 'País'], ['valor_12m_usd', 'US$ 12m', (x) => num(x.valor_12m_usd)], ['participacao_12m_pct', 'Part.', (x) => num(x.participacao_12m_pct, 1) + '%'],
            ['participacao_anterior_pct', 'Part. anterior', (x) => x.participacao_anterior_pct == null ? '—' : num(x.participacao_anterior_pct, 1) + '%'], ['variacao_12m_pct', 'Var.', (x) => pct(x.variacao_12m_pct)]], an.paises)}
          ${notes([...(an.mudancas_relevantes || []).map((m) => 'Mudança relevante: ' + m), ...(an.anomalias || []).map((x) => `Anomalia (${x.tipo}) em ${x.mes}: US$ ${fmt(x.valor_usd, 0)}`), 'Previsão: ' + an.previsao.motivo, b.abrangencia])}`
          : '<p class="small muted">Sem estatísticas para este código no período (veja o estado da consulta acima).</p>'}</section>`; }).join('')}`;
    } catch (e) { out.innerHTML = errBox(e); }
  }

  /* ======================================================================= EMPRESAS E EMBARQUES */
  async function empresas(arg) {
    const a = Object.fromEntries(new URLSearchParams(arg || ''));
    main.innerHTML = head('Empresas e Embarques', 'Embarques individuais DOCUMENTADOS (arquivos que você importa ou provedores autorizados). Estatísticas agregadas nunca são atribuídas a empresas.') + `
      <form class="panel" id="ef"><div class="btnrow" style="flex-wrap:wrap;gap:8px"><label class="f" style="flex:2 1 260px">Empresa (importadora/exportadora)<input name="nome" value="${escH(a.nome || '')}" required placeholder="ex.: ACME Imports Inc"></label>
        <label class="f">País<input name="pais" value="${escH(a.pais || '')}" size="6" placeholder="US"></label><button class="btn primary">Investigar</button></div></form>
      <section class="panel"><h2>Importar documentos de embarque</h2><p class="small">B/L, manifestos ou registros comerciais obtidos legitimamente: PDF textual, TXT, CSV ou XLSX. Processado localmente.</p>
        <input type="file" id="edoc" accept=".pdf,.txt,.csv,.xlsx"> <input id="efonte" placeholder="fonte (opcional)"><div id="edo" class="small"></div></section>
      <section class="panel"><h2>Classificar descrição de carga</h2><div class="btnrow"><input id="ecl" style="flex:1" placeholder="ex.: Electric household waffle makers, 220V, 1200W"><button class="btn small" id="eclb">Classificar</button></div><div id="eclo"></div></section>
      <div id="eout"></div><div id="eov"></div>`;
    $('#ef').onsubmit = (ev) => { ev.preventDefault(); location.hash = '#empresas-embarques/' + qs(Object.fromEntries(new FormData(ev.target))); };
    $('#edoc').onchange = async (ev) => { const f = ev.target.files[0]; if (!f) return; $('#edo').innerHTML = loading('Importando…');
      try { const r = await raw('/api/suite/importar/embarques?' + qs({ fonte: $('#efonte').value }), f, f.name);
        $('#edo').innerHTML = `${num(r.novos)} novo(s), ${num(r.duplicados)} duplicado(s), ${(r.rejeitados || []).length} rejeitado(s)${r.documentos_reconhecidos != null ? ` · ${r.documentos_reconhecidos} documento(s) reconhecido(s)` : ''}. ${escH(r.aviso || '')}`;
      } catch (e) { $('#edo').innerHTML = errBox(e); } };
    $('#eclb').onclick = async () => { try { const c = await post('/api/suite/embarques/classificar', { texto: $('#ecl').value });
      $('#eclo').innerHTML = `<p class="small">Produto provável: <b>${escH(c.produto_provavel || 'não identificado')}</b> · categoria ${escH(c.categoria || '—')} · características ${escH(JSON.stringify(c.caracteristicas))} · confiança <b>${escH(c.confianca)}</b></p>
        ${tbl([['codigo', 'Código'], ['tipo', 'Tipo'], ['confianca', 'Confiança']], c.codigos_candidatos, 'Nenhum código candidato.')}${notes([c.aviso])}`; } catch (e) { $('#eclo').innerHTML = errBox(e); } };
    api('/api/suite/embarques/resumo').then((o) => { $('#eov').innerHTML = `<section class="panel"><h2>Base de embarques do GPI</h2><p class="small">${num(o.embarques)} embarque(s), ${num(o.importadores)} importador(es), ${num(o.exportadores)} exportador(es).</p>
      ${tbl([['empresa', 'Importador'], ['embarques', 'Embarques']], o.principais_importadores, o.vazio)}${tbl([['fonte', 'Fonte'], ['modalidade', 'Modalidade'], ['registros', 'Registros'], ['estado', 'Estado', (r) => escH(r.estado || r.ultima || '—')]], o.fontes)}</section>`; }).catch(() => {});
    if (!a.nome) return;
    $('#eout').innerHTML = loading('Investigando…');
    try {
      const r = await api('/api/suite/embarques/empresa?' + qs(a));
      const k = r.fornecedores_observados ? 'fornecedores_observados' : 'clientes_observados';
      $('#eout').innerHTML = `<section class="panel"><h2>${escH(r.consulta)}</h2><p><b>${escH(r.resultado)}</b>${r.confianca ? ` · confiança ${escH(r.confianca)}` : ''}</p>
        <h3>Identidade</h3>${tbl([['legal_name', 'Empresa'], ['country', 'País'], ['company_type', 'Tipo'], ['evidencia_identidade', 'Evidência']], r.correspondencias, 'Nenhuma empresa com este nome normalizado.')}
        ${(r.nomes_parecidos_nao_unidos || []).length ? `<details><summary class="small">Nomes parecidos (não unidos)</summary>${tbl([['legal_name', 'Empresa'], ['similaridade', 'Similaridade'], ['evidencia_identidade', 'Nota']], r.nomes_parecidos_nao_unidos)}</details>` : ''}
        ${r.embarques && r.embarques.length ? `<h3>${k === 'fornecedores_observados' ? 'Fornecedores observados' : 'Clientes observados'}</h3>${tbl([['empresa', 'Empresa'], ['embarques', 'Embarques'], ['participacao_pct', 'Part. %']], r[k])}
          <p class="small">Concentração (HHI): ${num(r.concentracao_parceiros_hhi, 3)}</p>
          <h3>Categorias e produtos prováveis</h3>${tbl([['categoria', 'Categoria'], ['embarques', 'Embarques']], r.categorias)}${tbl([['produto', 'Produto provável'], ['embarques', 'Embarques']], r.produtos_provaveis)}
          <h3>Embarques documentados</h3>${tbl([['date', 'Data'], ['doc_id', 'B/L'], ['exporter_name', 'Exportador'], ['importer_name', 'Importador'], ['origin_country', 'Origem'], ['port_lading', 'Porto embarque'], ['port', 'Porto chegada'],
            ['description', 'Descrição'], ['weight_kg', 'kg'], ['c', 'Classificação', (x) => escH((x.classificacao || {}).produto_provavel || '—')], ['source', 'Fonte']], r.embarques)}
          <h3>Evolução</h3>${tbl([['mes', 'Mês'], ['embarques', 'Embarques'], ['kg', 'kg', (x) => num(x.kg)]], r.evolucao_mensal)}
          <div class="btnrow"><a class="btn small" href="/api/suite/embarques/empresa.xlsx?${qs(a)}">Exportar XLSX</a><a class="btn small" href="/api/suite/embarques/empresa.pdf?${qs(a)}">Exportar PDF</a></div>` : ''}
        ${notes(r.limitacoes)}<h3>Fontes consultadas</h3>${tbl([['fonte', 'Fonte'], ['modalidade', 'Modalidade'], ['registros', 'Registros'], ['estado', 'Estado', (x) => escH(x.estado || '—')]], r.fontes_consultadas)}</section>`;
    } catch (e) { $('#eout').innerHTML = errBox(e); }
  }

  /* ======================================================================= ASSISTENTE IA */
  const EXEMPLOS = ['Quais categorias aumentaram suas importações nos últimos 12 meses?', 'Quais produtos de eletroportáteis estão crescendo nas importações brasileiras?',
    'Quais produtos estão recebendo atenção na internet?', 'Vale investigar a importação de uma máquina de waffle?', 'Compare carregadores GaN 65W encontrados no eBay.',
    'Quais evidências sustentam a oportunidade de air fryer?', 'Quais produtos investigados apresentam evidências mais fortes de crescimento?',
    'Quais fornecedores aparecem nos embarques associados à empresa "ACME Imports"?'];
  async function assistente() {
    main.innerHTML = head('Assistente de Inteligência', 'Responde consultando as ferramentas reais do GPI (comércio exterior, embarques, produtos, marketplaces, tendências). ' +
      'Sem modelo local instalado, responde no Modo Essencial (regras + cálculos).') + `
      <form class="panel" id="af"><div class="btnrow"><input name="pergunta" style="flex:1" required placeholder="Pergunte…"><label class="small"><input type="checkbox" name="ia"> usar IA local (se instalada)</label><button class="btn primary">Perguntar</button></div>
      <p class="small">${EXEMPLOS.map((x) => `<a href="#" data-ex="${escH(x)}">${escH(x)}</a>`).join(' · ')}</p></form><div id="aout"></div>`;
    const f = $('#af');
    document.querySelectorAll('[data-ex]').forEach((a) => { a.onclick = (ev) => { ev.preventDefault(); f.pergunta.value = a.dataset.ex; f.requestSubmit(); }; });
    f.onsubmit = async (ev) => { ev.preventDefault(); const out = $('#aout'); out.innerHTML = loading('Consultando os dados do GPI…');
      try { const r = await post('/api/suite/assistente', { pergunta: f.pergunta.value, ia: f.ia.checked });
        const dados = Array.isArray(r.dados_utilizados) ? r.dados_utilizados : [];
        out.innerHTML = `<section class="panel"><p class="small muted">Ferramenta: ${escH(r.ferramenta)} · ${escH(r.modo)} · consulta ${r.consulta_executada ? 'executada' : '<b>não executada</b>'}</p>
          <h2>Conclusão</h2><p>${escH(r.conclusao_ia || r.conclusao)}</p>${r.conclusao_ia ? `<details><summary class="small">Texto determinístico</summary><p class="small">${escH(r.conclusao)}</p></details>` : ''}
          ${r.ia_descartada ? `<p class="small muted">IA local: ${escH(r.ia_descartada)} — exibida a conclusão calculada.</p>` : ''}
          <p class="small">Confiança: <b>${escH(r.confianca)}</b>${r.periodo ? ` · Período: ${escH(r.periodo)}` : ''} · Fontes: ${escH((r.fontes || []).join('; ') || '—')}</p>
          ${dados.length && typeof dados[0] === 'object' ? tbl(Object.keys(dados[0]).slice(0, 6).map((k) => [k, k, (x) => escH(typeof x[k] === 'object' ? JSON.stringify(x[k]) : (x[k] == null ? '—' : String(x[k])))]), dados) : ''}
          ${Object.keys(r.metricas || {}).length ? `<p class="small">Métricas: ${escH(JSON.stringify(r.metricas))}</p>` : ''}
          <h3>Limitações</h3>${notes(r.limitacoes)}<h3>Próximas investigações</h3>${notes(r.proximas_investigacoes)}</section>`;
      } catch (e) { out.innerHTML = errBox(e); } };
  }

  /* ======================================================================= MATRIZ DE FONTES */
  async function matriz() {
    main.innerHTML = head('Matriz de Fontes', 'Cobertura verificável: uma fonte só aparece como operacional depois de uma consulta bem-sucedida com registros.') + `<div id="mx">${loading('Carregando…')}</div>`;
    try { const d = await api('/api/suite/fontes/matriz');
      $('#mx').innerHTML = `<section class="panel">${tbl([['nome', 'Fonte', (r) => r.url_oficial && r.url_oficial !== '—' ? `<a href="${escH(r.url_oficial)}" target="_blank" rel="noopener noreferrer">${escH(r.nome)}</a>` : escH(r.nome)],
        ['tipo', 'Informação'], ['paises', 'Países'], ['granularidade', 'Granularidade'], ['api', 'API'], ['acesso', 'Acesso'], ['gratuidade', 'Custo'], ['estado', 'Estado', (r) => `<b>${escH(r.estado)}</b>`],
        ['ultima_consulta_ok', 'Última consulta OK'], ['registros', 'Registros'], ['erros', 'Erro'], ['limitacoes', 'Limitações']], d.fontes)}${notes([d.regra])}</section>`;
    } catch (e) { $('#mx').innerHTML = errBox(e); }
  }

  return { inicio, dashboard, trade, 'empresas-embarques': empresas, assistente, 'matriz-fontes': matriz };
};
