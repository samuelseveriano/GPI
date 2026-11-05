/* GPI v0.9 — Dashboard executivo A–G (estágios de decisão), alertas com estado, dossiê com estágio/próximas ações/
   Investigar/perguntas fundamentadas/evidências de vídeo e revisão humana de associações. Sem rolagem horizontal:
   tabelas resumidas e detalhes expansíveis. Nenhum número é inventado: tudo vem do backend. */
window.GPI_V09 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, errBox, main, $ } = H;
  const num = (v) => v == null ? '—' : fmt(v, 0);
  const dl = (pid, n) => `<a href="#dossie/${encodeURIComponent(pid)}">${escH(n || pid)}</a>`;
  const STG = (n, nome) => `<span class="stg stg${n}" title="Estágio ${n}">${n} · ${escH(nome)}</span>`;
  const list = (rows, empty) => rows.length ? `<ul class="clean small">${rows.join('')}</ul>` : `<p class="muted small">${escH(empty)}</p>`;
  const sect = (id, title, sub, body, open = true) =>
    `<details class="panel" id="${id}" ${open ? 'open' : ''}><summary><h2 style="display:inline">${title}</h2> <span class="muted small">${escH(sub)}</span></summary>${body}</details>`;
  const prodRow = (x) => `<li>${dl(x.produto_id, x.produto)} ${STG(x.estagio, x.nome_estagio)} <span class="muted">${escH(x.categoria || '')}</span>
      <details class="inline"><summary class="small">por quê / próximas ações</summary>
        <p class="small">${escH(x.estagio_evidencia.regra)}.${x.estagio_evidencia.faltando.length ? ' Falta: ' + escH(x.estagio_evidencia.faltando.join('; ')) : ''}</p>
        <ul class="small">${x.proximas_acoes.map((a) => `<li>${escH(a)}</li>`).join('')}</ul></details></li>`;

  /* ------------------------------------------------------------ DASHBOARD EXECUTIVO 2.0 (A–G) */
  async function pageDashboard() {
    main.innerHTML = `<h1>Dashboard</h1><p class="sub">Quais produtos merecem atenção, por quê, e o que ainda falta saber.</p><div id="d9">${loading('Montando o painel…')}</div>`;
    let d;
    try { d = await api('/api/v09/painel'); } catch (e) { $('#d9').innerHTML = errBox(e); return; }
    const A = d.A_resumo, cc = A.cobertura_comercial || {};
    const K = [['Produtos', A.produtos], ['Com evidência comercial', A.com_evidencia_comercial], ['Investigação recomendada', A.investigacao_recomendada],
      ['Sinais preliminares', A.sinais_preliminares], ['Crescimento confirmado', A.crescimento_confirmado], ['Investigações abertas', A.investigacoes_abertas]];
    $('#d9').innerHTML = `
      <section class="kpis compact">${K.map(([l, v]) => `<div class="kpi"><div class="v">${num(v)}</div><div class="l">${l}</div></div>`).join('')}</section>
      <p class="small muted">Cobertura comercial: ${cc.valor == null ? '—' : fmt(cc.valor, 1) + '%'} ${cc.formula ? '(' + escH(cc.formula) + ')' : ''} · análise de ${escH(A.gerado_em || '—')}</p>
      ${sect('d9c', 'C. Oportunidades para investigação', 'somente quando os critérios do estágio 3 são cumpridos',
        d.C_oportunidades.length ? list(d.C_oportunidades.map(prodRow), '') : `<p class="small">${escH(d.C_vazio)}</p>`)}
      ${sect('d9b', 'B. Radar comercial', 'produtos com evidência comercial (ranking de buscas, volume autorizado ou vendas)', list(d.B_radar_comercial.map(prodRow), 'Nenhum produto com evidência comercial.'))}
      ${sect('d9d', 'D. Sinais preliminares', 'precisam de confirmação — não indicam crescimento', list(d.D_sinais_preliminares.map(prodRow), 'Nenhum sinal preliminar.'), false)}
      ${sect('d9e', 'E. Mudanças recentes', d.E_nota, list(d.E_mudancas.map((m) => `<li>${dl(m.produto_id, m.produto)}: ${escH(m.de)} → <b>${escH(m.para)}</b>${m.novo ? ' <span class="badge">novo</span>' : ''}</li>`), 'Nenhuma mudança de estágio desde a análise anterior.'), false)}
      ${sect('d9g', 'G. Investigações em andamento', 'ações e decisões pendentes', list(d.G_investigacoes.map((i) => `<li><a href="#investigacoes">${escH(i.produto)}</a> — ${escH(i.estado)} <span class="muted">(${escH((i.atualizado_em || '').slice(0, 10))})</span></li>`), 'Nenhuma investigação aberta.'), false)}
      ${sect('d9f', 'F. Qualidade e cobertura', 'fontes com problema, associações em revisão', `
        <p class="small">Associações aguardando revisão humana: <a href="#revisao"><b>${num(d.F_qualidade.associacoes_em_revisao)}</b></a></p>
        ${list((d.F_qualidade.fontes_com_problema || []).map((f) => `<li>${escH(f.nome || f.id)} — ${escH(f.estado)}</li>`), 'Nenhuma fonte com problema.')}`, false)}
      <details class="small"><summary>Como os estágios são definidos</summary><ul>${Object.entries(d.regras_estagios).map(([k, v]) => `<li><b>${escH(k)}</b>: ${escH(v)}</li>`).join('')}</ul></details>`;
  }

  /* ------------------------------------------------------------ ALERTAS (executivos / estatísticos / qualidade) */
  async function pageAlerts(arg) {
    const q = new URLSearchParams(arg || '');
    main.innerHTML = `<h1>Alertas</h1><p class="sub">Executivos (mudanças comerciais) separados dos estatísticos e de qualidade. Alertas já vistos aparecem como “conhecido”.</p>
      <div class="btnrow" id="af">${['', 'executivo', 'estatístico', 'qualidade'].map((c) => `<a class="btn small ${q.get('categoria') === c || (!c && !q.get('categoria')) ? 'primary' : ''}" href="#alertas/${c ? 'categoria=' + encodeURIComponent(c) : ''}">${c || 'todos'}</a>`).join('')}
      <a class="btn small" href="#alertas/${q.get('categoria') ? 'categoria=' + encodeURIComponent(q.get('categoria')) + '&' : ''}estado=novo">só novos</a></div><div id="a9">${loading('Carregando…')}</div>`;
    let d;
    try { d = await api('/api/v09/alertas' + (arg ? '?' + arg : '')); } catch (e) { $('#a9').innerHTML = errBox(e); return; }
    const cnt = Object.entries(d.contagem).map(([k, v]) => `${escH(k)}: <b>${v.novo}</b> novos, ${v.conhecido} conhecidos`).join(' · ');
    $('#a9').innerHTML = `<p class="small">${cnt || 'Nenhum alerta.'}</p>
      ${d.itens.length ? `<table class="small compact"><thead><tr><th>Estado</th><th>Severidade</th><th>Alerta</th><th>Produto · fonte</th><th>Evidência / ação</th></tr></thead><tbody>
      ${d.itens.slice(0, 200).map((a) => `<tr><td>${a.estado === 'novo' ? '<span class="badge">novo</span>' : 'conhecido'}<br><span class="muted">desde ${escH(a.primeira_vez)}${a.vezes > 1 ? ` · ${a.vezes}×` : ''}</span></td>
        <td>${escH(a.severidade || '—')}</td><td><b>${escH(a.tipo || '')}</b><br><span class="muted">${escH(a.categoria_v09)}</span></td>
        <td>${a.produto_id ? dl(a.produto_id, a.produto) : escH(a.produto || '—')}<br><span class="muted">${escH(a.fonte || '')} · ${escH(a.data || '')}</span></td>
        <td>${escH(a.evidencia || a.motivo || '')}${a.acao ? `<br><span class="muted">Ação: ${escH(a.acao)}</span>` : ''}</td></tr>`).join('')}</tbody></table>` : ''}
      <details class="small"><summary>Resolvidos recentemente (${d.resolvidos_recentes.length})</summary><ul>${d.resolvidos_recentes.map((r) => `<li>${escH(r.categoria)} · ${escH(r.tipo || '')} · ${escH(r.produto_id || '')} — de ${escH(r.primeira_vez)} a ${escH(r.resolvido_em)}</li>`).join('')}</ul></details>
      <p class="small muted">${escH(d.regra)}</p>`;
  }

  /* ------------------------------------------------------------ DOSSIÊ: decisão, perguntas e vídeos */
  const baseDossier = PAGES.dossie;
  async function pageDossier(arg) {
    await baseDossier(arg);
    const pid = decodeURIComponent(arg || '');
    if (!pid) return;
    const box = document.createElement('section');
    box.className = 'panel';
    box.innerHTML = `<h2>Decisão</h2><div id="v9dz">${loading('Calculando estágio…')}</div>`;
    main.insertBefore(box, main.children[2] || null);
    try {
      const st = await api('/api/v09/estagios');
      const x = st.itens.find((i) => i.produto_id === pid);
      if (!x) { $('#v9dz').innerHTML = '<p class="muted small">Produto sem evidências registradas.</p>'; return; }
      const ev = x.estagio_evidencia;
      $('#v9dz').innerHTML = `<p>${STG(x.estagio, x.nome_estagio)} ${x.estagio_investigacao ? `· investigação: <b>${escH(x.estagio_investigacao.estado)}</b>` : ''}</p>
        <p class="small">${escH(ev.regra)}.${ev.faltando.length ? '<br>Falta: ' + escH(ev.faltando.join('; ')) : ''}</p>
        <p class="small"><b>Próximas ações</b></p><ul class="small">${x.proximas_acoes.map((a) => `<li>${escH(a)}</li>`).join('')}</ul>
        <div class="btnrow"><button class="btn primary small" id="v9inv">Investigar</button>
          ${['por_que', 'evidencias', 'variante', 'crescimento', 'faltando'].map((k) => `<button class="btn small" data-q="${k}">${{ por_que: 'Por que apareceu?', evidencias: 'Quais evidências?', variante: 'Qual variante?', crescimento: 'Crescimento confirmado?', faltando: 'O que falta?' }[k]}</button>`).join('')}</div>
        <div id="v9out" class="small"></div><div id="v9vid"></div>`;
      $('#v9inv').onclick = async () => {
        try { const r = await post('/api/v09/investigar/' + encodeURIComponent(pid), {}); $('#v9out').innerHTML = `<p>${r.ja_existia ? 'Investigação já aberta' : 'Investigação criada'} (nº ${r.id}). Preenchido: ${escH((r.preenchido_automaticamente || []).join(', '))}. ${escH(r.nao_preenchido || '')} <a href="#investigacoes">Abrir lista</a></p>`; } catch (e) { $('#v9out').innerHTML = errBox(e); }
      };
      document.querySelectorAll('[data-q]').forEach((b) => { b.onclick = async () => {
        try { const r = await api(`/api/v09/perguntar?produto=${encodeURIComponent(pid)}&pergunta=${b.dataset.q}`); $('#v9out').innerHTML = `<p><b>${escH(r.pergunta)}</b><br>${escH(r.resposta)}</p>${r.fontes.length ? `<p class="muted">Fontes: ${r.fontes.map((f) => escH(`${f.fonte} (${f.metrica}, ${f.periodo || '—'})`)).join('; ')}</p>` : ''}`; } catch (e) { $('#v9out').innerHTML = errBox(e); }
      }; });
      const v = await api('/api/v09/produto/' + encodeURIComponent(pid) + '/videos');
      $('#v9vid').innerHTML = `<details class="small"><summary><b>Vídeos com associação confirmada (${v.videos.length})</b>${v.nao_confirmados.length ? ` · ${v.nao_confirmados.length} aguardando revisão` : ''}</summary>
        ${v.videos.length ? `<table class="small compact"><thead><tr><th>Vídeo</th><th>Contexto (GPI)</th><th>Atributos citados</th><th>Métricas oficiais do YouTube</th></tr></thead><tbody>${v.videos.slice(0, 30).map((x) => `<tr><td><a href="${escH(x.url)}" target="_blank" rel="noopener">${escH(x.titulo)}</a><br><span class="muted">${escH(x.canal || '')} · ${escH(x.data || '')}</span></td><td>${escH(x.contexto_gpi || '—')}</td><td>${escH(Object.entries(x.atributos_explicitos).map(([k, val]) => `${k}: ${Array.isArray(val) ? val.join(', ') : val}`).join(' · ') || '—')}</td><td>${num(x.metricas_oficiais_youtube.viewCount)} visualizações · ${num(x.metricas_oficiais_youtube.likeCount)} curtidas</td></tr>`).join('')}</tbody></table>` : '<p class="muted">Nenhum vídeo com associação confirmada.</p>'}
        <ul class="muted">${v.avisos.map((a) => `<li>${escH(a)}</li>`).join('')}</ul></details>`;
    } catch (e) { $('#v9dz').innerHTML = errBox(e); }
  }

  /* ------------------------------------------------------------ REVISÃO HUMANA DE ASSOCIAÇÕES */
  async function pageReview() {
    main.innerHTML = `<h1>Revisão de associações</h1><p class="sub">Textos que o GPI não associou com confiança. Enquanto não forem confirmados, não alimentam conclusões comerciais.</p><div id="rv">${loading('Carregando…')}</div>`;
    let d, c;
    try { [d, c] = await Promise.all([api('/api/v09/revisao'), api('/api/v09/compreensao')]); } catch (e) { $('#rv').innerHTML = errBox(e); return; }
    const t = c.avaliacao.teste;
    $('#rv').innerHTML = `<details class="small"><summary>Qualidade da identificação (conjunto de teste independente: ${t.casos} casos)</summary>
        <p>Precisão das associações de alta confiança: <b>${fmt(100 * t.precisao_alta_confianca, 1)}%</b> · recall ${fmt(100 * t.recall, 1)}% · associações incorretas ${fmt(100 * t.taxa_associacao_incorreta, 1)}%.</p><p class="muted">${escH(c.nota)}</p></details>
      ${d.itens.length ? `<table class="small compact"><thead><tr><th>Texto</th><th>Sugestão · motivo</th><th>Decisão</th></tr></thead><tbody>${d.itens.map((r) => `<tr data-id="${r.id}"><td>${escH(r.texto)}<br><span class="muted">${escH(r.fonte)}${r.contexto ? ' · ' + escH(r.contexto) : ''}</span></td>
        <td>${escH(r.sugestao || '—')}<br><span class="muted">${escH((r.motivos || []).join('; '))}</span></td>
        <td><input class="small" placeholder="produto (ex.: doorbell+smart)" value="${escH(r.sugestao || '')}" size="18"> <button class="btn small" data-d="confirmar">Confirmar</button> <button class="btn small" data-d="rejeitar">Rejeitar</button></td></tr>`).join('')}</tbody></table>` : '<p class="muted small">Nenhuma associação aguardando revisão.</p>'}
      <p class="small muted">${escH(d.regra)}</p>`;
    document.querySelectorAll('[data-d]').forEach((b) => { b.onclick = async () => {
      const tr = b.closest('tr');
      try { await post('/api/v09/revisao/' + tr.dataset.id, { decisao: b.dataset.d, produto: tr.querySelector('input').value }); tr.remove(); } catch (e) { alert(e.message); }
    }; });
  }

  return { dashboard: pageDashboard, alertas: pageAlerts, dossie: pageDossier, revisao: pageReview };
};
