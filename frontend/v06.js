/* GPI v0.6 — Centro de Relatórios, Histórico, Tendências nas Redes Sociais, Viral Product Radar,
   Opportunity Engine 3.0 e exportação por página (Excel/PDF com os filtros da página). */
window.GPI_V06 = function (H, PAGES) {
  const { api, post, fmt, pct, escH, loading, main, $ } = H;
  const empty = (what, why, how) => `<div class="empty"><b>${escH(what)}</b><br>${escH(why)}${how ? `<br>${how}` : ''}</div>`;
  const g = (v) => v == null ? '—' : `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${v > 0 ? '+' : ''}${pct(v)}</span>`;
  const score = (v) => v == null ? '<span class="muted">—</span>' : `<span class="score sm"><i style="width:${Math.max(4, v)}%"></i></span> <b>${fmt(v, 0)}</b>`;
  const plink = (pid, name) => `<a href="#produto-consumo/${encodeURIComponent(pid)}">${escH(name || pid)}</a>`;
  const dt = (s) => s ? escH(String(s).replace('T', ' ').slice(0, 16)) : '—';
  const size = (b) => b == null ? '—' : b > 1e6 ? fmt(b / 1e6, 1) + ' MB' : fmt(b / 1e3, 0) + ' kB';
  const FMT = { xlsx: 'Excel', pdf: 'PDF', csv: 'CSV' };
  const GROUP = { executivo: 'Relatórios Executivos', produtos: 'Relatórios de Produtos', tendencias: 'Relatórios de Tendências' };
  let FILT = null;

  /* ---------------------------------------------------------------- CENTRO DE RELATÓRIOS */
  async function pageReports(group) {
    const title = GROUP[group] || 'Centro de Relatórios';
    main.innerHTML = `<h1>${escH(title)}</h1><p class="sub">Relatórios em Excel, PDF e CSV gerados neste computador, com os dados armazenados no GPI. Cada arquivo registra filtros, fontes, versões e um identificador de execução.</p><div id="rc">${loading()}</div>`;
    const d = await api('/api/reports/types');
    FILT = d.filtros;
    const types = d.tipos.filter((t) => !group || t.grupo === group);
    const opt = (list, all) => `<option value="">${all}</option>` + list.map((x) => `<option value="${escH(x.id ?? x)}">${escH(x.nome ?? x)}</option>`).join('');
    $('#rc').innerHTML = `
      <div class="panel"><h2>Filtros</h2><div class="form" id="rfil">
        <label class="f">País<select data-k="pais">${opt(FILT.paises, 'Todos')}</select></label>
        <label class="f">Categoria<select data-k="categoria">${opt(FILT.categorias, 'Todas')}</select></label>
        <label class="f">Produto<select data-k="produto" style="max-width:240px">${opt(FILT.produtos, 'Todos')}</select></label>
        <label class="f">Fonte<select data-k="fonte">${opt(FILT.fontes, 'Todas')}</select></label>
        <label class="f">Período<select data-k="periodo_meses">${opt(FILT.periodos, 'Todo o histórico')}</select></label>
        <label class="f">Tipo de relatório<select id="rtype">${opt(types.map((t) => ({ id: t.id, nome: t.nome })), 'Todos')}</select></label></div>
        <p class="small muted">Os filtros valem para todas as seções do relatório e são impressos no documento. Relatórios feitos com dados de demonstração saem marcados como <b>DEMONSTRAÇÃO</b>.</p></div>
      <div class="banner info small">Relatório semanal automático: <b>${d.relatorio_semanal ? 'ligado' : 'desligado'}</b>.
        <label style="margin-left:8px"><input type="checkbox" id="weekly" ${d.relatorio_semanal ? 'checked' : ''}> Gerar relatório semanal automaticamente (executivo em PDF e Excel após a sincronização; salvo só neste computador)</label></div>
      <div class="grid g3" id="cards">${types.map(card).join('')}</div>
      <div id="rmsg"></div>`;
    $('#weekly').onchange = async (e) => { await post('/api/settings', { auto_report_weekly: e.target.checked }); };
    $('#rtype').onchange = (e) => main.querySelectorAll('.rcard').forEach((c) => { c.hidden = !!e.target.value && c.dataset.t !== e.target.value; });
    main.querySelectorAll('[data-gen]').forEach((b) => b.onclick = () => generate(b.dataset.t, b.dataset.gen, b));
  }
  function card(t) {
    return `<div class="panel rcard" data-t="${t.id}"><h2>${escH(t.nome)}</h2><p class="small">${escH(t.descricao)}</p>
      <p class="small muted">Formatos: ${t.formatos.map((f) => FMT[f]).join(' · ')}${t.exige_produto ? ' · exige um produto selecionado' : ''}<br>Última geração: ${dt(t.ultima_geracao)}</p>
      <div class="form">${t.formatos.map((f) => `<button class="${f === 'csv' ? '' : 'primary'}" data-gen="${f}" data-t="${t.id}">Gerar ${FMT[f]}</button>`).join(' ')}</div></div>`;
  }
  function filters() {
    const f = {};
    main.querySelectorAll('#rfil [data-k]').forEach((s) => { if (s.value) f[s.dataset.k] = s.value; });
    return f;
  }
  async function generate(tipo, formato, btn) {
    const box = $('#rmsg');
    btn.disabled = true;
    box.innerHTML = `<div class="panel"><span class="spinner"></span> Gerando ${escH(FMT[formato])}…</div>`;
    try {
      const r = await post('/api/reports/generate', { tipo, formato, filtros: filters() });
      box.innerHTML = result(r);
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    } catch (e) { box.innerHTML = `<div class="banner">Não foi possível gerar: ${escH(e.message || e)}</div>`; }
    finally { btn.disabled = false; }
  }
  function result(r) {
    return `<div class="panel"><h2>${r.status === 'gerado' ? 'Relatório gerado' : 'Falha na geração'}</h2>
      ${r.demo ? '<p><span class="badge bad">DEMONSTRAÇÃO</span> a base contém dados demonstrativos.</p>' : ''}
      <p class="small">${escH(r.titulo || '')}<br>Arquivo: <code>${escH(r.arquivo || '—')}</code> · ${size(r.size)} · execução <code>${escH((r.run_id || '').slice(0, 12))}</code></p>
      ${r.erro ? `<p class="neg small">${escH(r.erro)}</p>` : ''}
      ${r.status === 'gerado' ? `<div class="form">${r.formato === 'pdf' ? `<a class="btn primary" href="/api/reports/${r.id}/download?abrir=1" target="_blank" rel="noopener">Abrir</a>` : ''}
        <a class="btn" href="/api/reports/${r.id}/download">Baixar</a> <a class="btn" href="#relatorios-historico">Histórico de Relatórios</a></div>` : ''}</div>`;
  }

  /* ---------------------------------------------------------------- HISTÓRICO */
  async function pageHistory() {
    main.innerHTML = `<h1>Histórico de Relatórios</h1><p class="sub">Todos os relatórios gerados, com filtros, versões dos modelos e dos dados. Relatórios anteriores são preservados quando os dados mudam.</p><div id="rh">${loading()}</div>`;
    await post('/api/reports/notifications', {}).catch(() => {});
    const d = await api('/api/reports');
    const ST = { gerado: 'ok', erro: 'bad', excluido: '' };
    const filt = (f) => f && Object.keys(f).length ? Object.entries(f).map(([k, v]) => `${k}: ${v}`).join(' · ') : 'sem filtros';
    $('#rh').innerHTML = d.relatorios.length ? `<div class="panel scroll"><table class="small"><thead><tr><th>Tipo</th><th>Formato</th><th>Período</th><th>Gerado em</th><th>País</th><th>Filtros</th><th>Versão dos modelos</th><th>Versão dos dados</th><th>Arquivo</th><th class="num">Tamanho</th><th>Status</th><th>Ações</th></tr></thead><tbody>
      ${d.relatorios.map((r) => `<tr><td>${escH(r.tipo_nome)}${r.demo ? ' <span class="badge bad">DEMONSTRAÇÃO</span>' : ''}${r.origem === 'automatico' ? ' <span class="badge">semanal</span>' : r.origem === 'reproducao' ? ' <span class="badge">reprodução</span>' : ''}</td>
        <td>${escH(FMT[r.formato] || r.formato)}</td><td>${escH(r.periodo || '')}</td><td>${dt(r.created_at)}</td><td>${escH(r.pais || '')}</td><td class="wrap">${escH(filt(r.filtros))}</td>
        <td class="wrap">${escH((r.modelos || []).map((m) => m.modelo).slice(0, 3).join(', ') || 'nenhum')}</td><td><code>${escH(r.versao_dados || '')}</code></td>
        <td class="wrap"><code>${escH(r.arquivo || '—')}</code></td><td class="num">${size(r.size)}</td><td><span class="badge ${ST[r.status] || ''}">${escH(r.status)}</span>${r.erro ? `<br><span class="neg">${escH(r.erro.slice(0, 120))}</span>` : ''}</td>
        <td style="white-space:nowrap">${r.disponivel ? `${r.formato === 'pdf' ? `<a class="btn small" href="/api/reports/${r.id}/download?abrir=1" target="_blank" rel="noopener">Abrir</a> ` : ''}<a class="btn small" href="/api/reports/${r.id}/download">Baixar</a> ` : ''}
          ${r.status !== 'erro' ? `<button class="small" data-re="${r.id}" data-m="snapshot" ${r.disponivel ? '' : 'disabled'} title="Mesmos dados (snapshot guardado)">Reproduzir</button> ` : ''}
          <button class="small" data-re="${r.id}" data-m="atual" title="Mesmos filtros com os dados atuais">Gerar novamente</button>
          ${r.status !== 'excluido' ? ` <button class="small" data-del="${r.id}">Excluir</button>` : ''}</td></tr>`).join('')}</tbody></table></div><div id="hmsg"></div>
      <p class="small muted">Reproduzir usa o snapshot dos dados guardado com o relatório (mesmos números); Gerar novamente usa os mesmos filtros com os dados atuais. Excluir apaga o arquivo e mantém o registro para auditoria.</p>`
      : empty('Nenhum relatório gerado ainda.', 'Gere o primeiro no Centro de Relatórios ou pelos botões Exportar das páginas.', '<a href="#relatorios">Abrir o Centro de Relatórios</a>');
    main.querySelectorAll('[data-re]').forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try { const r = await post(`/api/reports/${b.dataset.re}/regenerate`, { modo: b.dataset.m }); $('#hmsg').innerHTML = result(r); setTimeout(pageHistory, 2500); }
      catch (e) { $('#hmsg').innerHTML = `<div class="banner">${escH(e.message || e)}</div>`; } finally { b.disabled = false; }
    });
    main.querySelectorAll('[data-del]').forEach((b) => b.onclick = async () => {
      if (!confirm('Excluir este relatório? O arquivo será apagado deste computador; o registro fica no histórico.')) return;
      await api(`/api/reports/${b.dataset.del}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmar: true }) });
      pageHistory();
    });
  }

  /* ---------------------------------------------------------------- REDES SOCIAIS */
  const PLAT = { tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook', meta_ads: 'Biblioteca de Anúncios da Meta', youtube: 'YouTube', reddit: 'Reddit' };
  const RCLS = { 'Tendência emergente': 'ok', 'Crescimento sustentado': 'ok', 'Viralização recente': 'lbl', 'Popularidade estável': '', 'Possível saturação': 'lbl', 'Interesse em declínio': 'bad' };
  async function pageSocial(p) {
    if (p) return pagePlatform(p);
    main.innerHTML = `<h1>Tendências nas Redes Sociais</h1><p class="sub">Atenção a produtos específicos em TikTok, Instagram, Facebook, YouTube e Reddit — somente APIs oficiais e autorizadas. Atenção social não é compra nem volume de pesquisas.</p><div id="so">${loading()}</div>`;
    const d = await api('/api/social/overview');
    const plats = Object.entries(d.plataformas);
    const anyData = plats.some(([, v]) => v.observacoes);
    $('#so').innerHTML = `
      ${anyData ? '' : `<div class="banner">Nenhuma rede social conectada ainda. As páginas mostram dados assim que uma integração autorizada for conectada na <a href="#integracoes">Central de Integrações</a>.</div>`}
      <div class="kpis">${plats.map(([k, v]) => `<div class="kpi"><span>${escH(v.nome)}</span><b>${fmt(v.observacoes, 0)}</b><small class="muted">${escH(v.situacao)}${v.ultima_coleta ? ' · ' + escH(v.ultima_coleta) : ''} · retenção ${escH(v.retencao)}</small></div>`).join('')}</div>
      <div class="panel"><h2>Social Trend Score — produtos com atenção crescente</h2>
        ${d.ranking.length ? `<div class="scroll" style="max-height:520px"><table class="small"><thead><tr><th>Produto</th><th>Score (0–100)</th><th>Viral Product Radar</th><th>Plataformas</th><th class="num">Crescimento social</th><th>Componentes</th><th class="num">Cobertura</th><th>Hashtags</th></tr></thead><tbody>
          ${d.ranking.map((r) => `<tr><td>${plink(r.product_id, r.nome)}</td><td>${score(r.social_trend_score)}</td><td><span class="badge ${RCLS[r.classe_radar] || ''}">${escH(r.classe_radar)}</span></td>
            <td>${escH(r.plataformas.join(', '))}${r.somente_uma_plataforma ? ' <span class="badge">só uma plataforma</span>' : ''}</td><td class="num">${g(r.crescimento_social)}</td>
            <td class="wrap">${Object.entries(r.componentes).map(([k, v]) => `${escH(k.replace(/_/g, ' '))} ${fmt(v * 100, 0)}`).join(' · ')}</td><td class="num">${fmt(r.cobertura * 100, 0)}%</td><td class="wrap">${escH(r.hashtags.slice(0, 4).join(', '))}</td></tr>`).join('')}</tbody></table></div>`
          : empty('Sem produtos com sinais sociais.', 'O índice precisa de observações sociais associadas a produtos do catálogo (hashtags de entretenimento não contam).')}
        <p class="small muted">Pesos: ${Object.entries(d.pesos).map(([k, v]) => `${escH(k.replace(/_/g, ' '))} ${fmt(v * 100, 0)}%`).join(' · ')}. Crescimento e engajamento são normalizados dentro de cada plataforma e métrica (percentil); nada é somado entre plataformas. Índice exploratório de atenção — não é probabilidade de compra.</p></div>
      <div class="panel"><h2>Search vs. Social Interest</h2>
        ${d.search_vs_social.length ? `<table class="small"><thead><tr><th>Produto</th><th class="num">Search Growth</th><th class="num">Social Growth</th><th class="num">Marketplace Signals</th><th class="num">Evidence Coverage</th><th class="num">Cross-Source Consistency</th><th>Leitura</th><th>Fontes</th></tr></thead><tbody>
          ${d.search_vs_social.map((r) => `<tr><td>${plink(r.product_id, r.nome)}</td><td class="num">${g(r.search_growth)}</td><td class="num">${g(r.social_growth)}</td><td class="num">${r.marketplace_signals == null ? '—' : fmt(r.marketplace_signals, 0)}</td>
            <td class="num">${fmt(r.evidence_coverage, 0)}</td><td class="num">${r.cross_source_consistency == null ? '—' : fmt(r.cross_source_consistency, 2)}</td><td>${escH(r.leitura)}${r.correlacao_mensal ? `<br><span class="muted">Spearman ${fmt(r.correlacao_mensal.spearman, 2)} (${r.correlacao_mensal.meses} meses)</span>` : ''}</td><td class="wrap">${escH(r.fontes.join(', '))}</td></tr>`).join('')}</tbody></table>
          <p class="small muted">Cada crescimento é calculado na própria fonte e unidade; a consistência compara apenas a DIREÇÃO das variações (−1 = divergem, +1 = concordam).</p>`
          : empty('Sem produtos com busca e sinais sociais ou de marketplace ao mesmo tempo.', 'A comparação exige pelo menos dois tipos de fonte para o mesmo produto.')}</div>
      <div class="panel"><h2>Viral Product Radar</h2><div class="kpis">${Object.entries(d.radar_contagem).map(([k, v]) => `<div class="kpi"><span>${escH(k)}</span><b>${v}</b></div>`).join('')}</div><p><a href="#radar-viral">Abrir o radar</a></p></div>
      <div class="panel small muted">${d.avisos.map(escH).join('<br>')}</div>`;
  }
  async function pagePlatform(p) {
    main.innerHTML = `<h1>${escH(PLAT[p] || p)} — inteligência social</h1><div id="sp">${loading()}</div>`;
    const d = await api('/api/social/platform/' + encodeURIComponent(p));
    const st = d.status || {};
    $('#sp').innerHTML = `<p class="sub">${escH(st.situacao || '')} · ${fmt(st.observacoes || 0, 0)} observações · retenção ${escH(st.retencao || '')}</p>
      ${d.series.length ? `<div class="panel"><h2>Produtos e indicadores</h2><table class="small"><thead><tr><th>Produto</th><th>País</th><th>Hashtag/termo</th><th>Indicador</th><th>Unidade</th><th class="num">Último valor</th><th class="num">Crescimento</th><th>Classe</th><th>Evidência</th></tr></thead><tbody>
          ${d.series.map((s) => `<tr><td>${plink(s.product_id, s.nome)}</td><td>${escH(s.pais_nome)}</td><td class="wrap">${escH(s.item)}</td><td>${escH(s.metrica.rotulo)}</td><td class="small muted">${escH(s.metrica.unidade)}</td>
            <td class="num">${fmt(s.ind.ultimo_valor ?? s.ind.soma_30d, 0)}</td><td class="num">${g(s.ind.crescimento)}</td><td>${escH(s.ind.classe || '')}</td><td>${s.url ? `<a href="${escH(s.url)}" target="_blank" rel="noopener">abrir</a>` : '—'}</td></tr>`).join('')}</tbody></table></div>`
        : empty('Sem dados desta plataforma.', 'Conecte a integração autorizada correspondente.', escH(d.como_conectar || ''))}
      ${d.hashtags.length ? `<div class="panel"><h2>Hashtags e termos em alta (listas oficiais)</h2><table class="small"><thead><tr><th class="num">Posição</th><th>Hashtag/termo</th><th>País</th><th>Produto identificado</th><th>Intenção comercial</th><th>Data</th></tr></thead><tbody>
          ${d.hashtags.map((h) => `<tr><td class="num">${h.posicao}</td><td>${escH(h.item)}</td><td>${escH(h.pais_nome)}</td><td>${h.product_id ? plink(h.product_id.split(':')[0], h.produto || h.product_id) : '<span class="muted">—</span>'}</td><td>${h.comercial ? 'sim' : 'não'}</td><td>${escH(h.data)}</td></tr>`).join('')}</tbody></table>
          <p class="small muted">Hashtags sem produto identificado (entretenimento, memes) não contam como evidência comercial.</p></div>` : ''}
      <details class="panel small"><summary>O que cada indicador mede</summary><ul>${Object.values(d.metricas).map((m) => `<li><b>${escH(m.rotulo)}</b> (${escH(m.unidade)}): ${escH(m.mede)}</li>`).join('')}</ul></details>`;
  }
  async function pageViral() {
    main.innerHTML = `<h1>Viral Product Radar</h1><p class="sub">Produtos com aceleração nas redes sociais, separados em seis classes. Um produto viral não tem demanda comercial sustentável garantida.</p><div id="vr">${loading()}</div>`;
    const d = await api('/api/social/viral');
    $('#vr').innerHTML = `<div class="grid g3">${Object.entries(d.radar).map(([k, items]) => `<div class="panel"><h2><span class="badge ${RCLS[k] || ''}">${escH(k)}</span> ${items.length}</h2>
      ${items.length ? `<ul class="small">${items.map((i) => `<li>${plink(i.product_id, i.nome)} — score ${i.score == null ? '—' : fmt(i.score, 0)} · ${escH(i.plataformas.join(', '))}${i.somente_uma_plataforma ? ' <span class="badge">só uma plataforma</span>' : ''}${i.pico_passageiro_possivel ? ' <span class="badge">pico possivelmente passageiro</span>' : ''}${i.mudanca_de_patamar ? ' <span class="badge">mudança de patamar</span>' : ''}</li>`).join('')}</ul>` : '<p class="muted small">Nenhum produto.</p>'}</div>`).join('')}</div>
      <div class="panel small muted">${d.avisos.map(escH).join('<br>')}<br>Critérios: emergente = primeira observação recente; sustentado = crescimento &gt; 15% com persistência ≥ 50%; viralização recente = salto de curto prazo (mais que dobrou em 7 dias ou anomalia no último período) com persistência baixa; saturação = crescimento desacelerando perto do máximo; declínio = queda &gt; 15%.</div>`;
  }

  /* ---------------------------------------------------------------- OPORTUNIDADES (Engine 3.0) */
  const PR = { 'Alta': 'ok', 'Média': 'lbl', 'Baixa': '', 'Evidência insuficiente': '' };
  const DIM = [['consumer_search_strength', 'Busca'], ['social_momentum', 'Social'], ['marketplace_evidence', 'Marketplace'], ['trend_persistence', 'Persistência'],
    ['competition_pressure', 'Concorrência'], ['product_quality_risk', 'Risco de qualidade'], ['evidence_coverage', 'Cobertura'], ['forecast_confidence', 'Previsão'], ['import_readiness', 'Prontidão']];
  async function pageOpp3() {
    main.innerHTML = `<h1>Oportunidades</h1><p class="sub">Product Opportunity Engine 3.0 — pesquisas, marketplaces e redes sociais transformados em oportunidades de INVESTIGAÇÃO. Não é probabilidade de sucesso, margem nem recomendação de compra.</p><div id="o3">${loading()}</div>`;
    const d = await api('/api/opportunities3');
    $('#o3').innerHTML = d.produtos.length ? `<div class="panel scroll"><table class="small"><thead><tr><th>Produto</th><th>Prioridade</th><th>Índice</th>${DIM.map(([, n]) => `<th class="num">${n}</th>`).join('')}<th>Riscos</th><th>Próximas investigações</th></tr></thead><tbody>
      ${d.produtos.map((r) => `<tr><td>${plink(r.product_id, r.nome)}<br><span class="muted">${escH(r.categoria || '')}</span></td><td><span class="badge ${PR[r.prioridade]}">${escH(r.prioridade)}</span></td><td>${score(r.indice)}</td>
        ${DIM.map(([k]) => `<td class="num">${r.dimensoes[k] == null ? '<span class="muted">—</span>' : fmt(r.dimensoes[k], 0)}</td>`).join('')}
        <td class="wrap">${escH(r.riscos.slice(0, 3).join('; '))}</td><td class="wrap">${escH(r.proximos_passos.slice(0, 3).join('; '))}</td></tr>`).join('')}</tbody></table></div>
      <div class="panel small muted">Pesos do índice: ${Object.entries(d.pesos).map(([k, v]) => `${escH(k.replace(/_/g, ' '))} ${fmt(v * 100, 0)}%`).join(' · ')} (concorrência e risco entram invertidos). Dimensões sem dados ficam vazias e não entram no índice. ${escH(d.aviso)}
        <br><a href="#oportunidades-v5">Ver o Opportunity Score por país (versão anterior)</a></div>`
      : empty('Sem produtos com evidências ainda.', 'As oportunidades aparecem depois da primeira sincronização com dados de busca, marketplaces ou redes sociais.');
  }

  /* ---------------------------------------------------------------- EXPORTAÇÃO POR PÁGINA */
  const EXPORT = { dashboard: ['executivo'], 'oportunidades-consumo': ['oportunidades'], 'mais-pesquisados': ['mais_pesquisados'],
    consumo: ['tendencias_pais', (a) => ({ pais: (a || 'BR').toUpperCase() })], 'comparacao-internacional': ['radar_global'], emergentes: ['radar_global'],
    alertas: ['radar_global'], social: ['social'], 'radar-viral': ['social'], 'produto-consumo': ['produto', (a) => ({ produto: a })],
    'previsao-tendencias': ['previsoes'], modelos: ['previsoes'] };
  let CUR = null;
  const bar = document.getElementById('exportbar');
  if (bar && !bar.querySelector('select')) {
    bar.insertAdjacentHTML('afterbegin', '<select id="exper" aria-label="Período do relatório"><option value="">todo o histórico</option><option value="3">últimos 3 meses</option><option value="6">últimos 6 meses</option><option value="12">últimos 12 meses</option><option value="24">últimos 24 meses</option></select>');
    bar.querySelectorAll('[data-exp]').forEach((b) => b.onclick = async () => {
      if (!CUR) return;
      const f = { ...(CUR.filtros || {}) };
      const per = document.getElementById('exper').value;
      if (per) f.periodo_meses = per;
      b.disabled = true; const t = b.textContent; b.textContent = 'Gerando…';
      try {
        const r = await post('/api/reports/generate', { tipo: CUR.tipo, formato: b.dataset.exp, filtros: f, pagina: true });
        if (r.status === 'gerado') location.href = `/api/reports/${r.id}/download`; else alert('Falha: ' + (r.erro || ''));
      } catch (e) { alert('Não foi possível gerar: ' + (e.message || e)); } finally { b.disabled = false; b.textContent = t; }
    });
  }
  window.GPI_EXPORT = {
    onRoute(key, arg) {
      const e = EXPORT[key];
      CUR = e ? { tipo: e[0], filtros: e[1] ? e[1](arg) : {} } : null;
      if (bar) { bar.hidden = !CUR; bar.title = CUR ? `Exporta esta página como relatório (${CUR.tipo}) com os filtros: ${JSON.stringify(CUR.filtros)}` : ''; }
    },
  };
  // notificação de relatórios automáticos
  async function notes() {
    try {
      const d = await api('/api/reports/notifications');
      const a = document.getElementById('repnote');
      if (a) { a.hidden = !d.novos.length; a.textContent = d.novos.length ? `${d.novos.length} relatório(s) semanal(is) novo(s)` : ''; }
    } catch (e) { /* silencioso */ }
  }
  notes(); setInterval(notes, 60000);

  return { relatorios: pageReports, 'relatorios-historico': pageHistory, social: pageSocial, 'radar-viral': pageViral,
    'oportunidades-v5': PAGES['oportunidades-consumo'], 'oportunidades-consumo': pageOpp3 };
};
