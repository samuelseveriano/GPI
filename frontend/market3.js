/* GPI Fase 3 — Central de Integrações, YouTube, Reviews, Comparador e Marketplaces. */
window.GPI_MARKET3 = function (H) {
  const { api, post, fmt, pct, escH, loading, errBox, main, $ } = H;
  const STATE = { funcional: ['ok', 'funcional'], restrita: ['', 'não conectada'], falhou: ['bad', 'falhou'], nao_testada: ['', 'aguardando coleta'], aguardando: ['', 'aguardando'], 'sem dados': ['', 'sem dados'] };
  const badge = (s) => { const [c, t] = STATE[s] || ['', s]; return `<span class="badge ${c}">${t}</span>`; };
  const TYPE = { auto: 'Automática', api_key: 'Chave de API', client_id: 'ID de aplicativo', oauth: 'Login OAuth (PKCE)', optin: 'Aceite de termos', approval: 'Exige aprovação do provedor' };
  const del = (path) => api(path, { method: 'DELETE' });
  const n0 = (v) => fmt(v || 0, 0);

  /* ------------------------------------------------------------ CENTRAL DE INTEGRAÇÕES */
  async function pageIntegrations() {
    main.innerHTML = `<h1>Central de Integrações</h1><p class="sub">Conecte fontes de dados sem editar arquivos. Fontes públicas já estão conectadas; as demais pedem uma chave, um login oficial ou aprovação do provedor.</p><div id="ib">${loading()}</div>`;
    const list = await api('/api/integrations');
    const grp = (t) => list.filter((p) => t.includes(p.tipo));
    $('#ib').innerHTML = `<div class="banner info small">Credenciais ficam guardadas neste computador: <b>${escH(list[0].protecao)}</b>. O GPI nunca pede senha de marketplaces e não usa raspagem de sites.</div>
      <h2>Conectadas automaticamente</h2>${grp(['auto']).map(card).join('')}
      <h2 style="margin-top:22px">Exigem chave, login ou aceite</h2>${grp(['api_key', 'client_id', 'oauth', 'optin']).map(card).join('')}
      <h2 style="margin-top:22px">Exigem aprovação ou contrato do provedor</h2><div class="grid g2">${grp(['approval']).map(card).join('')}</div>`;
    main.querySelectorAll('[data-act]').forEach((b) => b.onclick = () => act(b.dataset.act, b.dataset.pid, b));
  }

  function card(p) {
    const fields = (p.campos || []).map((f) => f.checkbox
      ? `<label class="small" style="display:flex;gap:6px;align-items:flex-start;max-width:520px"><input type="checkbox" data-f="${f.nome}" ${p.credenciais[f.nome] ? 'checked' : ''}> ${escH(f.rotulo)}</label>`
      : `<label class="f">${escH(f.rotulo)}<input data-f="${f.nome}" type="${f.secreto ? 'password' : 'text'}" autocomplete="off" placeholder="${p.credenciais[f.nome] ? 'configurado (' + escH(p.credenciais[f.nome]) + ')' : ''}" style="width:280px"></label>`).join('');
    const conns = p.conectores.map((c) => `<tr><td>${escH(c.nome)}</td><td>${badge(c.estado)}${c.validada ? ' <span class="badge ok" title="Coleta real validada">validada</span>' : ''}</td>
      <td class="small">${c.ultima_coleta ? c.ultima_coleta.replace('T', ' ').slice(0, 16) : '—'}</td><td class="num">${n0(c.registros)}</td>
      <td class="small">${c.cobertura && c.cobertura[0] ? c.cobertura[0].slice(0, 7) + ' a ' + (c.cobertura[1] || '').slice(0, 7) : '—'}</td><td class="small wrap">${escH(c.mensagem || '')}</td></tr>`).join('');
    const btn = [];
    if (p.campos) btn.push(`<button class="primary" data-act="save" data-pid="${p.id}">${p.tipo === 'oauth' ? 'Salvar dados do aplicativo' : 'Conectar'}</button>`);
    if (p.tipo === 'oauth') btn.push(`<button class="primary" data-act="oauth" data-pid="${p.id}">Entrar com ${escH(p.nome)}</button>`);
    if (p.tipo === 'optin') btn.push(p.optin ? `<button data-act="optout" data-pid="${p.id}">Desativar</button>` : `<button class="primary" data-act="optin" data-pid="${p.id}">Aceito os termos — ativar</button>`);
    if (p.tipo !== 'approval') btn.push(`<button data-act="test" data-pid="${p.id}">Testar conexão</button>`, `<button data-act="sync" data-pid="${p.id}">Sincronizar</button>`);
    if (p.campos && Object.keys(p.credenciais).length) btn.push(`<button data-act="disconnect" data-pid="${p.id}">Desconectar</button>`);
    if (p.link) btn.push(`<a class="btn" href="${escH(p.link)}" target="_blank" rel="noopener">${p.tipo === 'approval' ? 'Solicitar acesso (site oficial)' : 'Obter credencial (site oficial)'}</a>`);
    const extra = p.id === 'rss' ? `<details><summary>Editar lista de feeds (${p.feeds.length})</summary><textarea id="feeds" rows="6" style="width:100%;font-family:var(--mono);font-size:12px">${p.feeds.map((f) => `${f.nome} | ${f.url} | ${f.idioma}`).join('\n')}</textarea><button class="small" data-act="feeds" data-pid="rss">Salvar feeds</button> <span class="muted small">Formato: nome | URL do feed | idioma (pt/en)</span></details>`
      : p.id === 'youtube' ? `<p class="small">Limite diário de uso definido no GPI: <input id="ytq" type="number" value="${p.cota_diaria}" min="100" max="10000" style="width:90px"> unidades <button class="small" data-act="ytq" data-pid="youtube">Salvar</button></p>` : '';
    return `<div class="panel integ"><div class="form" style="justify-content:space-between"><h2>${escH(p.nome)} <span class="badge">${TYPE[p.tipo]}</span> ${p.conectado ? '<span class="badge ok">conectada</span>' : p.tipo === 'approval' ? '<span class="badge">indisponível sem aprovação</span>' : '<span class="badge">não conectada</span>'}</h2></div>
      <p class="small">${escH(p.descricao)}</p><p class="small muted"><b>Permissões e regras:</b> ${escH(p.permissoes)}</p>
      ${p.como_obter ? `<p class="small muted"><b>Como obter:</b> ${escH(p.como_obter)}</p>` : ''}
      ${p.redirect_uri ? `<p class="small">URL de redirecionamento a cadastrar no provedor: <code>${escH(p.redirect_uri)}</code></p>` : ''}
      ${fields ? `<div class="form" data-form="${p.id}">${fields}</div>` : ''}${extra}
      <div class="form" style="margin-top:10px">${btn.join(' ')}</div><div class="small" id="msg-${p.id}"></div>
      ${p.tipo !== 'approval' || p.conectores.length ? `<details ${p.tipo === 'auto' ? 'open' : ''}><summary>Detalhes das fontes (${p.conectores.length})</summary><table class="rich"><tr><th>Fonte</th><th>Estado</th><th>Última coleta</th><th class="num">Registros</th><th>Cobertura</th><th>Mensagem</th></tr>${conns}</table></details>` : ''}
      ${p.documentacao ? `<p class="small"><a href="${escH(p.documentacao)}" target="_blank" rel="noopener">Documentação oficial</a></p>` : ''}</div>`;
  }

  async function act(a, pid, btn) {
    const msg = $('#msg-' + pid);
    const say = (t, ok) => { msg.innerHTML = `<span class="${ok ? 'pos' : 'neg'}">${escH(t)}</span>`; };
    btn.disabled = true;
    try {
      if (a === 'save') {
        const vals = {};
        main.querySelectorAll(`[data-form="${pid}"] [data-f]`).forEach((i) => { if (i.type === 'checkbox') vals[i.dataset.f] = i.checked; else if (i.value.trim()) vals[i.dataset.f] = i.value.trim(); });
        await post(`/api/integrations/${pid}/credentials`, vals);
        const t = await post(`/api/integrations/${pid}/test`, {});
        say(t.ok ? 'Conectado. ' + t.mensagem : 'Dados salvos, mas o teste falhou: ' + t.mensagem, t.ok);
        if (t.ok) setTimeout(pageIntegrations, 1200);
      } else if (a === 'test') {
        msg.innerHTML = '<span class="spinner"></span> testando…';
        const t = await post(`/api/integrations/${pid}/test`, {}); say(t.mensagem, t.ok);
      } else if (a === 'sync') {
        const r = await post(`/api/integrations/${pid}/sync`, {}); say(r.iniciada ? 'Sincronização iniciada (acompanhe na barra superior).' : 'Já existe uma sincronização em andamento.', r.iniciada);
      } else if (a === 'disconnect') {
        if (!confirm('Remover as credenciais desta integração deste computador?')) return;
        await del(`/api/integrations/${pid}`); pageIntegrations();
      } else if (a === 'oauth') {
        const r = await post(`/api/integrations/${pid}/oauth/start`, {});
        window.open(r.url, '_blank', 'noopener'); say('Conclua o login na janela do provedor e depois clique em "Testar conexão".', true);
      } else if (a === 'optin' || a === 'optout') {
        await post(`/api/integrations/${pid}/settings`, { google_news_optin: a === 'optin' }); pageIntegrations();
      } else if (a === 'feeds') {
        const feeds = $('#feeds').value.split('\n').map((l) => l.split('|').map((x) => x.trim())).filter((x) => x[1]).map(([nome, url, idioma]) => ({ nome, url, idioma: idioma || 'pt' }));
        await post('/api/integrations/rss/settings', { rss_feeds: feeds }); say('Feeds salvos.', true);
      } else if (a === 'ytq') {
        await post('/api/integrations/youtube/settings', { youtube_daily_units: +$('#ytq').value }); say('Limite salvo.', true);
      }
    } catch (e) { say(e.message, false); } finally { btn.disabled = false; }
  }

  /* ------------------------------------------------------------ YOUTUBE */
  async function pageYoutube() {
    main.innerHTML = `<h1>YouTube Intelligence</h1><p class="sub">Vídeos de review, unboxing, comparativos, testes, reclamações, lançamentos e recomendações sobre os produtos identificados, pela API oficial.</p><div id="yb">${loading()}</div>`;
    const d = await api('/api/market/youtube');
    if (!d.total_videos) { $('#yb').innerHTML = `<div class="panel"><p>Nenhum vídeo coletado. A API do YouTube exige uma chave gratuita: <a href="#integracoes">Central de Integrações → YouTube</a>.</p></div>`; return; }
    const tipos = {};
    d.produtos.forEach((p) => Object.entries(p.tipos).forEach(([k, v]) => { tipos[k] = (tipos[k] || 0) + v; }));
    $('#yb').innerHTML = `<div class="banner info small">${escH(d.aviso)} Cota usada hoje: ${n0(d.cota_hoje)} unidades.</div>
      <div class="kpis"><div class="kpi"><span>Vídeos</span><b>${n0(d.total_videos)}</b></div>${Object.entries(tipos).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => `<div class="kpi"><span>${escH(k)}</span><b>${n0(v)}</b></div>`).join('')}</div>
      <div class="panel"><h2>Por produto (somas e médias das métricas públicas)</h2><div class="scroll"><table><tr><th>Produto</th><th class="num">Vídeos</th><th class="num">Canais</th><th class="num">Visualizações</th><th class="num">Média por vídeo</th><th class="num">Curtidas</th><th class="num">Comentários</th><th>Tipos</th></tr>
      ${d.produtos.map((p) => `<tr class="click" data-yt="${escH(p.product_key)}"><td>${escH(p.nome)}</td><td class="num">${p.videos}</td><td class="num">${p.canais}</td><td class="num">${n0(p.visualizacoes_total)}</td><td class="num">${n0(p.visualizacoes_media)}</td><td class="num">${n0(p.curtidas_total)}</td><td class="num">${n0(p.comentarios_total)}</td><td class="small">${Object.entries(p.tipos).map(([k, v]) => `${escH(k)} ${v}`).join(', ')}</td></tr>`).join('')}</table></div></div><div id="ytd"></div>`;
    main.querySelectorAll('[data-yt]').forEach((tr) => tr.onclick = () => {
      const p = d.produtos.find((x) => x.product_key === tr.dataset.yt);
      $('#ytd').innerHTML = `<div class="panel"><h2>${escH(p.nome)} — vídeos mais vistos</h2><table class="rich"><tr><th>Vídeo</th><th>Canal</th><th>Publicado</th><th class="num">Visualizações</th><th class="num">Curtidas</th><th class="num">Comentários</th><th>Tipo</th></tr>
        ${p.top.map((v) => `<tr><td><a href="${escH(v.url)}" target="_blank" rel="noopener">${escH(v.titulo)}</a></td><td>${escH(v.canal)}</td><td>${escH(v.data || '')}</td><td class="num">${n0(v.visualizacoes)}</td><td class="num">${v.curtidas == null ? '—' : n0(v.curtidas)}</td><td class="num">${v.comentarios == null ? '—' : n0(v.comentarios)}</td><td class="small">${(v.tipos || []).join(', ')}</td></tr>`).join('')}</table></div>`;
    });
  }

  /* ------------------------------------------------------------ REVIEWS */
  async function pageReviews(key) {
    main.innerHTML = `<h1>Review Intelligence</h1><p class="sub">Opiniões de consumidores (Reddit, notícias e feeds) analisadas por NLP local: sentimento, aspectos e alvo da reclamação.</p><div id="rb">${loading()}</div>`;
    const d = await api('/api/market/reviews');
    if (!d.total_opinioes) { $('#rb').innerHTML = `<div class="panel"><p>Nenhuma opinião analisada ainda. Os feeds RSS são coletados automaticamente; para discussões de consumidores, conecte o Reddit na <a href="#integracoes">Central de Integrações</a>.</p><p class="muted small">Trustpilot e Reclame Aqui não oferecem acesso público às avaliações; não são raspados.</p></div>`; return; }
    const byk = Object.fromEntries(d.produtos.map((p) => [p.product_key, p]));
    const lst = (keys) => keys.map((k) => byk[k]).filter(Boolean);
    const bar = (p) => `<span class="sent"><i class="p" style="width:${100 * p.positivos / p.n}%"></i><i class="u" style="width:${100 * p.neutros / p.n}%"></i><i class="n" style="width:${100 * p.negativos / p.n}%"></i></span>`;
    const row = (p, short) => `<tr class="click" data-rv="${escH(p.product_key)}"><td>${escH(p.nome)}</td><td class="num">${p.n}</td><td>${bar(p)}</td><td class="num">${p.saldo == null ? '—' : (p.saldo > 0 ? '+' : '') + fmt(p.saldo, 2)}</td>${short ? '' : `<td class="small">${p.problemas.slice(0, 3).map((x) => escH(x.aspecto)).join(', ') || '—'}</td>`}</tr>`;
    const head = '<thead><tr><th>Produto</th><th class="num">Opiniões</th><th>Positivas / neutras / negativas</th><th class="num">Saldo</th><th>Problemas mais citados</th></tr></thead>';
    const headS = '<thead><tr><th>Produto</th><th class="num">Opiniões</th><th>Positivas / neutras / negativas</th><th class="num">Saldo</th></tr></thead>';
    $('#rb').innerHTML = `<div class="banner small">${escH(d.aviso)} Produtos com menos de ${d.minimo_opinioes} opiniões não entram nos rankings.</div>
      <div class="grid g2"><div class="panel"><h2>Mais elogiados</h2><div class="scroll"><table>${headS}${lst(d.mais_elogiados).slice(0, 8).map((p) => row(p, true)).join('')}</table></div></div>
      <div class="panel"><h2>Mais criticados</h2><div class="scroll"><table>${headS}${lst(d.mais_criticados).slice(0, 8).map((p) => row(p, true)).join('')}</table></div></div></div>
      <div class="grid g2"><div class="panel"><h2>Problemas recorrentes (todas as categorias)</h2><div id="probs"></div></div>
      <div class="panel"><h2>Todos os produtos</h2><div class="scroll"><table>${headS}${d.produtos.map((p) => row(p, true)).join('')}</table></div></div></div><div id="rvd"></div>`;
    barChart($('#probs'), d.problemas_recorrentes.map((x) => ({ label: x.aspecto, value: x.mencoes, color: 'var(--c5)' })), { format: (v) => n0(v) + ' menções' });
    const show = (k) => {
      const p = byk[k]; if (!p) return;
      const ex = (arr) => arr.map((e) => `<blockquote class="small">"${escH(e.trecho)}"<br><span class="muted">— ${escH(e.autor || e.fonte)}, ${escH(e.data || '')} · <a href="${escH(e.url)}" target="_blank" rel="noopener">fonte</a>${e.aspectos.length ? ' · ' + e.aspectos.join(', ') : ''}</span></blockquote>`).join('') || '<p class="muted small">—</p>';
      $('#rvd').innerHTML = `<div class="panel"><h2>${escH(p.nome)} — ${p.n} opiniões</h2><div class="grid g2"><div>
        <h3>Elogios</h3><p class="small">${p.elogios.map((x) => `${escH(x.aspecto)} (${x.mencoes})`).join(', ') || '—'}</p>
        <h3>Reclamações por aspecto</h3><p class="small">${p.problemas.map((x) => `${escH(x.aspecto)} (${x.mencoes})`).join(', ') || '—'}</p>
        <h3>Alvo das reclamações</h3><p class="small">${Object.entries(p.alvo_reclamacoes).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'}</p></div>
        <div><h3>Exemplos negativos</h3>${ex(p.exemplos_negativos)}<h3>Exemplos positivos</h3>${ex(p.exemplos_positivos)}</div></div>
        <p class="muted small">Trechos curtos com link para a fonte original. Classificação automática por léxico — pode errar com ironia ou gírias.</p></div>`;
      $('#rvd').scrollIntoView({ behavior: 'smooth' });
    };
    main.querySelectorAll('[data-rv]').forEach((tr) => tr.onclick = () => show(tr.dataset.rv));
    if (key) show(key);
  }

  /* ------------------------------------------------------------ COMPARADOR */
  async function pageCompare(keysArg) {
    main.innerHTML = `<h1>Comparador de Produtos</h1><p class="sub">Compare de 2 a 4 produtos. Cada atributo mostra a fonte e o nível de confiabilidade; nada é inventado.</p><div id="cf">${loading()}</div><div id="cr"></div>`;
    const opp = await api('/api/market/opportunities');
    const items = (opp.itens || []);
    if (!items.length) { $('#cf').innerHTML = '<div class="panel"><p>Ainda não há produtos analisados.</p></div>'; return; }
    const sel = (keysArg ? keysArg.split(',') : items.filter((i) => i.product_key.startsWith('wiki:')).slice(0, 2).map((i) => i.product_key));
    const opts = (v) => `<option value="">—</option>${items.map((i) => `<option value="${escH(i.product_key)}" ${i.product_key === v ? 'selected' : ''}>${escH(i.nome)} (${escH(i.categoria || '')})</option>`).join('')}`;
    $('#cf').innerHTML = `<div class="panel"><div class="form">${[0, 1, 2, 3].map((i) => `<label class="f">Produto ${i + 1}<select data-c="${i}" style="max-width:260px">${opts(sel[i])}</select></label>`).join('')}<button class="primary" id="cgo">Comparar</button></div></div>`;
    const go = async () => {
      const keys = [...main.querySelectorAll('[data-c]')].map((s) => s.value).filter(Boolean);
      if (keys.length < 2) { $('#cr').innerHTML = errBox('Selecione ao menos 2 produtos.'); return; }
      $('#cr').innerHTML = loading();
      try {
        const c = await api('/api/market/compare?keys=' + encodeURIComponent(keys.join(',')));
        const val = (v) => v == null || v.valor == null ? '<span class="muted">—</span>' : typeof v.valor === 'number'
          ? (Math.abs(v.valor) < 5 ? (v.valor > 0 ? '+' : '') + pct(v.valor, 0) : fmt(v.valor, Math.abs(v.valor) < 100 ? 2 : 0)) : escH(v.valor);
        $('#cr').innerHTML = `<div class="panel"><div class="scroll" style="max-height:none"><table class="rich cmp"><tr><th>Atributo</th>${c.produtos.map((p) => `<th>${escH(p.nome)}<br><span class="muted small">${escH(p.categoria || '')}</span></th>`).join('')}</tr>
          ${c.linhas.map((l) => `<tr><td><b>${escH(l.atributo)}</b></td>${l.valores.map((v) => `<td>${val(v)}${v && v.fonte ? `<br><span class="muted small">${v.url ? `<a href="${escH(v.url)}" target="_blank" rel="noopener">${escH(v.fonte)}</a>` : escH(v.fonte)} · ${escH(v.confiabilidade || '')}</span>` : v && v.confiabilidade && v.confiabilidade !== '—' ? `<br><span class="muted small">${escH(v.confiabilidade)}</span>` : ''}</td>`).join('')}</tr>`).join('')}</table></div>
          <p class="muted small">${escH(c.aviso)} Confiabilidade: A = estatística oficial · B = plataforma/NLP local · C = extraído de texto livre.</p></div>`;
        history.replaceState(null, '', '#comparador/' + encodeURIComponent(keys.join(',')));
      } catch (e) { $('#cr').innerHTML = errBox(e); }
    };
    $('#cgo').onclick = go;
    go();
  }

  /* ------------------------------------------------------------ MARKETPLACES */
  async function pageMarketplaces() {
    main.innerHTML = `<h1>Marketplaces</h1><p class="sub">Sinais de marketplaces obtidos somente por APIs oficiais autorizadas.</p><div id="mb">${loading()}</div>`;
    const d = await api('/api/market/marketplaces');
    $('#mb').innerHTML = `<div class="panel"><h2>Mercado Livre — tendências de busca</h2>${d.tendencias_ml.length ? `<table><tr><th class="num">Posição atual</th><th>Termo</th><th class="num">Semanas registradas</th><th>Desde</th></tr>${d.tendencias_ml.map((t) => `<tr><td class="num">${t.posicao}</td><td>${escH(t.termo)}</td><td class="num">${t.semanas}</td><td>${escH(t.primeira)}</td></tr>`).join('')}</table>` : '<p class="muted">Sem dados. Conecte o Mercado Livre (login OAuth) na <a href="#integracoes">Central de Integrações</a>. O histórico é construído a cada semana a partir da conexão.</p>'}</div>
      <div class="panel"><h2>Estado das integrações de marketplaces</h2><table class="rich"><tr><th>Marketplace</th><th>Estado</th><th>Situação</th></tr>
      ${d.fontes.map((s) => `<tr><td><b>${escH(s.nome)}</b></td><td>${s.estado === 'funcional' ? '<span class="badge ok">funcional</span>' : `<span class="badge">${escH(s.estado)}</span>`}</td><td class="small">${escH(s.estado === 'restrita' ? s.restricao : (s.mensagem || ''))} ${s.documentacao ? `<a href="${escH(s.documentacao)}" target="_blank" rel="noopener">site oficial</a>` : ''}</td></tr>`).join('')}</table>
      <p class="muted small">Preços indicativos de importação (Comex Stat) estão na página <a href="#china">China</a>.</p></div>`;
  }

  return { integracoes: pageIntegrations, youtube: pageYoutube, reviews: pageReviews, comparador: pageCompare, marketplaces: pageMarketplaces };
};
