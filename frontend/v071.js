/* GPI v0.7.1 — Inteligência de Oportunidades, Insights do GPI na página do produto, painel de destaques no dashboard
   e auditoria das fontes (matriz A–F) na Saúde das Fontes. Todos os números vêm do backend (determinísticos). */
window.GPI_V071 = function (H, PAGES) {
  const { api, fmt, escH, loading, errBox, main, $ } = H;
  const pct = (v) => v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v * 100, 0)}%`;
  const plink = (pid, name) => `<a href="#produto-consumo/${encodeURIComponent(pid)}">${escH(name || pid)}</a>`;
  const SIT = { 'EMERGENTE': 'cst2', 'CRESCIMENTO CONSISTENTE': 'cst4', 'ACELERAÇÃO': 'cst1', 'ESTÁVEL': 'cst3', 'SAZONAL': 'cst5',
    'POSSÍVEL SATURAÇÃO': 'cst2', 'DECLÍNIO': 'cst3', 'EVIDÊNCIA INSUFICIENTE': 'cst3' };
  const sit = (s) => `<span class="cst ${SIT[s] || 'cst3'}">${escH(s)}</span>`;
  const pers = (p) => p ? `${p.positivos} de ${p.periodos} períodos positivos` : '—';
  const score = (v) => v == null ? '—' : fmt(v, 0);
  const REG = { 1: 'exigência identificada', 2: 'potencial exigência', 3: 'não identificada', 4: 'faltam dados', 5: 'revisão especializada' };
  const reg = (c) => c ? Object.entries(c.resumo || {}).map(([o, s]) => `${escH(o)}: ${escH(REG[s] || s)}`).join('; ') + ` (<a href="#conformidade-analise/${c.analise_id}">análise</a>)` : '<span class="muted">não analisada</span>';

  function table(items, opts = {}) {
    if (!items.length) return `<p class="muted small">${escH(opts.vazio || 'Nenhum produto neste grupo com os dados atuais.')}</p>`;
    return `<div class="scroll"><table class="small"><thead><tr><th>Produto</th><th>Categoria</th><th>Variante</th><th>País</th><th>Fonte</th><th>Período</th>
      <th class="num">Crescimento</th><th>Persistência</th><th>Volatilidade</th><th>Tendência</th><th>Confiança</th><th class="num" title="Opportunity Score: potencial para investigação (não é probabilidade de sucesso)">Opportunity</th>
      <th class="num" title="Evidence Coverage: quantidade e qualidade da evidência">Cobertura</th><th class="num" title="Forecast Confidence">Previsão</th><th class="num" title="Import Readiness">Prontidão</th><th>Concorrência</th><th>Regulatório</th></tr></thead><tbody>
      ${items.map((i) => `<tr><td>${plink(i.produto_id, i.nome)}</td><td>${escH(i.categoria || '—')}</td><td>${escH(i.variante || '—')}</td>
        <td>${escH((i.serie_principal || {}).pais || '—')}</td><td>${escH((i.serie_principal || {}).fonte || '—')}</td><td class="small">${escH((i.serie_principal || {}).periodo || '—')}</td>
        <td class="num">${pct(i.crescimento_recente)}</td><td>${pers(i.persistencia)}</td><td>${escH(i.volatilidade_rotulo || '—')}</td><td>${sit(i.situacao)}</td><td>${escH(i.confianca)}</td>
        <td class="num"><b>${score(i.opportunity_score)}</b></td><td class="num">${score(i.evidence_coverage)}</td><td class="num">${score(i.forecast_confidence)}</td><td class="num">${score(i.import_readiness)}</td>
        <td>${i.concorrencia == null ? '<span class="muted">sem dados</span>' : i.concorrencia >= 0.66 ? 'baixa' : i.concorrencia >= 0.33 ? 'média' : 'alta'}</td><td class="small">${reg(i.prontidao_regulatoria)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  /* -------------------------------------------------------------- INTELIGÊNCIA DE OPORTUNIDADES */
  const QUESTIONS = [['merecem_investigacao', 'Produtos que merecem investigação', 'Em crescimento, com Opportunity Score ≥ 55 e cobertura de evidência ≥ 40.'],
    ['crescendo', 'Quais produtos estão crescendo?', 'Emergentes, crescimento consistente ou aceleração.'],
    ['crescimento_consistente', 'Quais apresentam crescimento consistente?', 'Tendência significativa com a maioria dos períodos recentes positivos.'],
    ['perdendo_interesse', 'Quais estão perdendo interesse?', 'Declínio sustentado ou possível saturação.'],
    ['possiveis_modismos', 'Quais podem ser modismos passageiros?', 'Emergentes com volatilidade alta ou sinal em uma única fonte.'],
    ['sazonais', 'Quais apresentam sazonalidade?', 'Sazonalidade estatisticamente significativa.'],
    ['eua_antes_do_brasil', 'Quais ganham atenção nos EUA antes do Brasil?', 'Defasagem significativa e estável (sinal exploratório, não causalidade).'],
    ['multiplas_fontes', 'Quais têm evidência em mais de uma fonte?', 'Sinal de alta em duas ou mais fontes independentes.'],
    ['precisam_mais_dados', 'Quais exigem mais dados?', 'Evidência insuficiente ou cobertura baixa — não significa baixa demanda.']];
  async function pageOpp() {
    main.innerHTML = `<h1>Inteligência de Oportunidades</h1><p class="sub">Quais produtos estão ganhando procura e quais merecem investigação para importação — com a evidência de cada conclusão.</p><div id="io">${loading('Calculando indicadores…')}</div>`;
    let d;
    try { d = await api('/api/consumer/insights'); } catch (e) { $('#io').innerHTML = errBox(e); return; }
    const by = Object.fromEntries(d.itens.map((i) => [i.produto_id, i]));
    const pick = (k) => (d.grupos[k] || []).map((p) => by[p]).filter(Boolean);
    const cl = d.clusters || {};
    $('#io').innerHTML = `<div class="banner info small">${escH(d.aviso)}</div>
      <div class="kpis">${QUESTIONS.slice(0, 6).map(([k, t]) => `<div class="kpi"><span>${escH(t.replace('?', ''))}</span><b>${d.contagens[k] || 0}</b></div>`).join('')}</div>
      ${QUESTIONS.map(([k, t, crit], n) => `<details class="panel" ${n === 0 ? 'open' : ''}><summary><h2 style="display:inline">${escH(t)}</h2> <span class="badge">${d.contagens[k] || 0}</span> <span class="muted small">${escH(crit)}</span></summary>${table(pick(k))}</details>`).join('')}
      <div class="panel"><h2>Agrupamento por comportamento</h2>${cl.grupos && cl.grupos.length ? `<p class="small muted">${escH(cl.metodo)} · k = ${cl.k} · silhouette ${fmt(cl.silhouette, 2)} (${escH(cl.qualidade)}) · atributos padronizados: crescimento, volatilidade, aceleração, persistência, sazonalidade. Nomes derivados dos centróides.</p>
        ${cl.grupos.map((g) => `<details><summary><b>${escH(g.nome)}</b> (${g.produtos.length}) <span class="muted small">centróide: crescimento ${pct(g.centroide.crescimento)}, volatilidade ${fmt(g.centroide.volatilidade, 2)}, aceleração ${fmt(g.centroide.aceleracao, 2)}</span></summary><p class="small">${g.produtos.map((p, i) => plink(p, g.nomes[i])).join(', ')}</p></details>`).join('')}`
        : `<p class="muted small">${escH(cl.aviso || 'Sem agrupamento.')}</p>`}
        ${(cl.evidencia_insuficiente || []).length ? `<p class="small muted">Evidência insuficiente (fora do agrupamento): ${cl.evidencia_insuficiente.length} produto(s).</p>` : ''}</div>
      <details class="panel"><summary>Critérios e fórmulas</summary><p class="small">Situação: EMERGENTE (primeira observação recente ou alta &gt; 15% sem significância), CRESCIMENTO CONSISTENTE (Mann-Kendall/Theil-Sen significativo; ano contra ano em séries sazonais), ACELERAÇÃO (tendência significativa e aceleração &gt; 10 p.p.), POSSÍVEL SATURAÇÃO (desaceleração &gt; 10 p.p. perto do máximo), DECLÍNIO (queda significativa ou &lt; −15%), SAZONAL, ESTÁVEL; EVIDÊNCIA INSUFICIENTE para séries mensais com &lt; 6 meses ou base abaixo do mínimo e diárias com &lt; 28 dias. Crescimento: últimos 3 meses contra os 3 anteriores, ou ano contra ano com ≥ 15 meses; séries diárias: 30 dias contra os 30 anteriores. Volatilidade: desvio-padrão das variações ÷ média (baixa &lt; 0,2; moderada &lt; 0,5). Detalhes em docs/ML_VALIDATION.md.</p></details>`;
  }

  /* -------------------------------------------------------------- PRODUTO: INSIGHTS DO GPI */
  const origProduct = PAGES['produto-consumo'];
  async function pageProduct(pid) {
    await origProduct(pid);
    let i;
    try { i = await api('/api/consumer/insights/' + encodeURIComponent(pid)); } catch (e) { return; }
    const box = document.createElement('div');
    box.className = 'panel';
    const fc = i.previsao;
    box.innerHTML = `<h2>INSIGHTS DO GPI</h2><table class="small kv"><tbody>
      <tr><td>Situação</td><td>${sit(i.situacao)}</td></tr>
      <tr><td>Crescimento recente</td><td>${pct(i.crescimento_recente)}${i.base_crescimento ? ` <span class="muted">(${escH(i.base_crescimento)})</span>` : ''}</td></tr>
      <tr><td>Persistência</td><td>${pers(i.persistencia)}</td></tr>
      <tr><td>Fontes com evidência</td><td>${i.fontes_com_evidencia ?? 0}${(i.fontes || []).length ? ` <span class="muted">(dados de: ${i.fontes.map(escH).join(', ')})</span>` : ''}</td></tr>
      <tr><td>Volatilidade</td><td>${escH(i.volatilidade_rotulo || '—')}</td></tr>
      <tr><td>Previsão</td><td>${fc ? `${escH(fc.texto)} <span class="muted">(${escH(fc.modelo || '')}${fc.baseline ? ', baseline' : ''}; qualidade ${escH(fc.qualidade || '—')})</span>` : '<span class="muted">sem previsão validada</span>'}</td></tr>
      <tr><td>Confiança</td><td>${escH(i.confianca || 'baixa')}</td></tr>
      ${i.opportunity_score != null ? `<tr><td>Opportunity / Cobertura / Previsão / Prontidão</td><td>${score(i.opportunity_score)} / ${score(i.evidence_coverage)} / ${score(i.forecast_confidence)} / ${score(i.import_readiness)}</td></tr>` : ''}
      </tbody></table><p><b>Análise:</b> ${escH(i.analise)}</p><p><b>Próxima ação sugerida:</b> ${escH(i.proxima_acao)}</p>
      ${(i.limitacoes || []).length ? `<p class="small muted">Limitações: ${i.limitacoes.map(escH).join(' · ')}</p>` : ''}
      <details><summary class="small">Detalhes técnicos</summary><pre class="small">${escH(JSON.stringify({ janelas: i.crescimentos_janelas, aceleracao: i.aceleracao, volatilidade: i.volatilidade, mudancas_patamar: i.mudancas_patamar, anomalias: i.anomalias, serie: i.serie_principal, previsao: fc && fc.metricas }, null, 2))}</pre></details>`;
    const first = main.querySelector('h1');
    if (first && first.nextSibling) first.parentNode.insertBefore(box, first.nextElementSibling ? first.nextElementSibling.nextSibling : null); else main.appendChild(box);
  }

  /* -------------------------------------------------------------- DASHBOARD: destaques */
  const origDash = PAGES.dashboard;
  async function pageDash(arg) {
    await origDash(arg);
    const box = document.createElement('div');
    box.innerHTML = loading('Carregando destaques…');
    const h = main.querySelector('h1');
    if (h && h.nextSibling) h.parentNode.insertBefore(box, h.nextElementSibling ? h.nextElementSibling.nextSibling : null); else main.prepend(box);
    let d, a;
    try { [d, a] = await Promise.all([api('/api/consumer/insights'), api('/api/sources/audit')]); } catch (e) { box.innerHTML = ''; return; }
    const by = Object.fromEntries(d.itens.map((i) => [i.produto_id, i]));
    const top = (k, n = 5) => (d.grupos[k] || []).map((p) => by[p]).filter(Boolean).slice(0, n);
    const li = (lst) => lst.length ? `<ol class="small">${lst.map((i) => `<li>${plink(i.produto_id, i.nome)} ${sit(i.situacao)} ${pct(i.crescimento_recente)}</li>`).join('')}</ol>` : '<p class="muted small">Nenhum produto com evidência suficiente ainda.</p>';
    const alerts = d.itens.filter((i) => (i.anomalias || []).length || (i.mudancas_patamar || []).length).slice(0, 5);
    const ok = a.fontes.filter((f) => f.fase === 'funcional' || f.fase === 'dados_armazenados').length;
    const bad = a.fontes.filter((f) => f.fase === 'falha');
    box.innerHTML = `<div class="grid g3">
      <div class="panel"><h2>Produtos em destaque</h2>${li(d.itens.filter((i) => i.opportunity_score != null && i.situacao !== 'EVIDÊNCIA INSUFICIENTE').slice(0, 5))}<a class="small" href="#inteligencia-oportunidades">Inteligência de Oportunidades →</a></div>
      <div class="panel"><h2>Tendências emergentes</h2>${li(d.itens.filter((i) => i.situacao === 'EMERGENTE').slice(0, 5))}</div>
      <div class="panel"><h2>Crescimento consistente</h2>${li(top('crescimento_consistente'))}</div>
      <div class="panel"><h2>Alertas</h2>${alerts.length ? `<ul class="small">${alerts.map((i) => `<li>${plink(i.produto_id, i.nome)}: ${(i.mudancas_patamar || []).length ? 'mudança de patamar em ' + escH(i.mudancas_patamar.slice(-1)[0]) : ''}${(i.anomalias || []).length ? ' anomalia em ' + escH(i.anomalias.slice(-1)[0]) : ''}</li>`).join('')}</ul>` : '<p class="muted small">Sem anomalias ou mudanças de patamar recentes.</p>'}</div>
      <div class="panel"><h2>Comparação internacional</h2>${li(top('eua_antes_do_brasil'))}<p class="small muted">Sinais exploratórios de defasagem; correlação não é causalidade.</p></div>
      <div class="panel"><h2>Saúde das fontes</h2><p class="small">${ok} de ${a.fontes.length} fontes com dados armazenados${bad.length ? `; <span class="neg">${bad.length} com falha: ${bad.map((f) => escH(f.nome)).join(', ')}</span>` : ''}.</p><a class="small" href="#fontes">Ver auditoria das fontes →</a></div></div>`;
  }

  /* -------------------------------------------------------------- SAÚDE DAS FONTES: auditoria A–F */
  const origFontes = PAGES.fontes;
  async function pageFontes(arg) {
    if (origFontes) await origFontes(arg); else main.innerHTML = '<h1>Saúde das Fontes</h1>';
    const box = document.createElement('div');
    box.className = 'panel';
    box.innerHTML = loading('Auditando as fontes…');
    const h = main.querySelector('h1');
    if (h && h.nextSibling) h.parentNode.insertBefore(box, h.nextElementSibling ? h.nextElementSibling.nextSibling : null); else main.prepend(box);
    let a, db;
    try { [a, db] = await Promise.all([api('/api/sources/audit'), api('/api/db/integrity')]); } catch (e) { box.innerHTML = errBox(e); return; }
    const yn = (v) => v ? '✓' : '—';
    box.innerHTML = `<h2>Auditoria das fontes (A configuração · B autenticação · C coleta · D processamento · E persistência · F visualização)</h2>
      <p class="small">${Object.entries(a.resumo).map(([k, v]) => `${escH(k)}: <b>${v}</b>`).join(' · ')} · Banco: ${db.ok ? '<span class="pos">íntegro</span>' : '<span class="neg">verificar</span>'} (esquema v${db.versao_esquema}, ${escH(db.journal_mode)})</p>
      <div class="scroll"><table class="small"><thead><tr><th>Fonte</th><th>Exige autenticação</th><th>Credenciais</th><th>Habilitada</th><th>Token</th><th>Jobs (ok/falhos)</th><th>Última coleta OK</th><th class="num">Registros</th><th class="num">Ligados a produtos</th><th>Contagem consistente</th><th>Fase</th><th>Último erro</th><th></th></tr></thead><tbody>
      ${a.fontes.map((f) => `<tr><td>${escH(f.nome)}${f.documentacao ? ` <a href="${escH(f.documentacao)}" target="_blank" rel="noopener">doc</a>` : ''}</td><td>${yn(f.A_configuracao.exige_autenticacao)}</td><td>${yn(f.A_configuracao.credenciais_configuradas)}</td><td>${yn(f.A_configuracao.habilitado)}</td><td>${yn(f.B_autenticacao.token_salvo)}</td>
        <td>${(f.C_coleta.jobs.done || 0)}/${(f.C_coleta.jobs.failed || 0)}</td><td>${escH((f.C_coleta.ultima_coleta_ok || '—').slice(0, 16).replace('T', ' '))}</td><td class="num">${fmt(f.E_persistencia.registros, 0)}</td><td class="num">${fmt(f.F_visualizacao.ligados_a_produto, 0)}</td>
        <td>${f.E_persistencia.contagem_consistente == null ? '—' : f.E_persistencia.contagem_consistente ? '✓' : '<span class="neg">divergente</span>'}</td><td><b>${escH(f.fase_rotulo)}</b></td><td class="wrap small ${f.fase === 'falha' ? 'neg' : 'muted'}">${escH((f.C_coleta.ultimo_erro || '').slice(0, 160))}</td>
        <td>${f.A_configuracao.habilitado ? `<button class="small" data-up="${escH(f.fonte)}">Atualizar fonte</button>` : ''}</td></tr>`).join('')}</tbody></table></div>
      <p class="small muted">"Funcional" exige coleta real gravada e ligada a produtos; um token aceito não basta. Fontes removidas na v0.7: ${a.removidas.map((r) => escH(r.nome)).join(', ')}.</p>`;
    box.querySelectorAll('[data-up]').forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try { const r = await H.post('/api/sync/start', { fontes: [b.dataset.up], manual: true }); b.textContent = r.iniciada ? 'Iniciada' : 'Em andamento'; } catch (e) { alert(e.message); }
    });
  }

  return { 'inteligencia-oportunidades': pageOpp, 'produto-consumo': pageProduct, dashboard: pageDash, fontes: pageFontes };
};
