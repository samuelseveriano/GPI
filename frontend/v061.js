/* GPI v0.6.1 — painel de sincronização em tempo real (SSE com reconexão e polling de reserva), estados das
   integrações com diagnóstico, assistente do Google Ads, módulos Meta e YouTube Intelligence com os vídeos armazenados. */
window.GPI_V061 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, main, $ } = H;
  const dt = (s) => s ? escH(String(s).replace('T', ' ').slice(0, 16)) : '—';
  const dur = (s) => s == null ? '—' : s < 60 ? `${fmt(s, 1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  const CLS = { concluido: 'ok', atualizado: 'ok', em_cache: 'ok', sem_novidades: 'ok', pendente: 'bad', sem_coleta: '', executando: 'lbl', aguardando: '', ignorado: '', requer_autorizacao: '', erro: 'bad', limite: 'bad', cancelado: '' };
  const badge = (f) => `<span class="badge st-${escH(f.estado)} ${CLS[f.estado] || ''}"><span aria-hidden="true">${escH(f.simbolo || '')}</span> ${escH(f.rotulo || f.estado)}</span>`;
  let SNAP = null, es = null, fails = 0, pollT = null, lastFase = null;

  /* ---------------------------------------------------------------- barra superior + painel lateral */
  const bar = document.getElementById('syncbar');
  document.body.insertAdjacentHTML('beforeend', `<div id="syncpanel" class="syncpanel" hidden role="dialog" aria-modal="false" aria-labelledby="sp-title">
    <div class="sp-head"><h2 id="sp-title">Sincronização</h2><button class="small" id="sp-close" aria-label="Fechar painel">Fechar ✕</button></div><div id="sp-body"></div></div>`);
  const panel = document.getElementById('syncpanel');
  document.getElementById('sp-close').onclick = () => { panel.hidden = true; };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) panel.hidden = true; });

  function progress(s) {
    return s.indeterminado || s.percentual == null
      ? '<span class="prog indet" role="progressbar" aria-label="progresso indeterminado"><i></i></span>'
      : `<span class="prog" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${s.percentual}"><i style="width:${s.percentual}%"></i></span>`;
  }
  function renderBar(s) {
    if (!bar) return;
    const final = !s.rodando && s.fim && (Date.now() - Date.parse(s.fim) < 60000);
    if (!s.rodando && !final) { bar.style.display = 'none'; return; }
    bar.style.display = 'flex';
    bar.dataset.resultado = s.rodando ? '' : (s.resultado || '');
    bar.innerHTML = `${s.rodando ? '<span class="spinner" aria-hidden="true"></span>' : ''}<b>${s.rodando ? 'SINCRONIZAÇÃO' : escH(s.titulo).toUpperCase()}${s.percentual != null && s.rodando ? ' — ' + s.percentual + '%' : ''}</b>
      ${s.rodando ? progress(s) : ''}<span class="small">${escH(s.resumo || s.titulo || '')}</span>
      <button class="small" data-sp="open">Ver detalhes</button>
      ${s.rodando ? '<button class="small" data-sp="cancel">Cancelar</button>' : ''}${!s.rodando && (s.contagem || {}).falhas ? '<button class="small" data-sp="retry">Tentar novamente fontes com falha</button>' : ''}
      ${s.rodando ? '<span class="muted small">Os dados já coletados continuam disponíveis.</span>' : ''}`;
    bar.querySelectorAll('[data-sp]').forEach((b) => b.onclick = () => act(b.dataset.sp));
  }
  function sourceRow(id, f) {
    const kv = [['Início', dt(f.inicio)], ['Duração', dur(f.segundos)], ['Jobs', f.jobs_total ? `${f.jobs_feitos || 0} de ${f.jobs_total}` : '—'],
      ['Requisições', f.requisicoes ?? 0], ['Respostas do cache', f.cache ?? 0], ['Registros novos', f.novos ?? 0], ['Registros atualizados', f.atualizados ?? 0],
      ['Registros armazenados', f.registros_armazenados ?? '—'], ['Tentativas extras', f.tentativas ?? 0], ['Espera por limite', f.espera_s ? dur(f.espera_s) : '—'],
      ['Cota estimada usada', f.cota_unidades != null ? `${f.cota_unidades} unidades` : '—'], ['Última sincronização bem-sucedida', dt(f.ultima_ok)],
      ['Próxima execução prevista', f.proxima ? dt(f.proxima) : 'conforme a política da fonte']];
    return `<details class="sp-src"><summary><span class="sp-name">${escH(f.nome || id)}</span> ${badge(f)} <span class="muted small">${f.segundos != null ? dur(f.segundos) : ''}</span></summary>
      <table class="small"><tbody>${kv.map(([k, v]) => `<tr><td>${k}</td><td>${typeof v === 'number' ? fmt(v, 0) : v}</td></tr>`).join('')}</tbody></table>
      ${f.motivo ? `<p class="small ${f.estado === 'erro' || f.estado === 'limite' ? 'neg' : 'muted'}">Motivo: ${escH(f.motivo)}</p>` : ''}</details>`;
  }
  function renderPanel(s) {
    if (panel.hidden) return;
    const fontes = Object.entries(s.fontes || {});
    const groups = {};
    fontes.forEach(([id, f]) => { (groups[f.prioridade || 3] = groups[f.prioridade || 3] || []).push([id, f]); });
    $('#sp-body').innerHTML = `<p class="muted small">GLOBAL PRODUCT INTELLIGENCE</p>
      <p><b>${escH(s.titulo || '')}</b>${s.percentual != null ? ` · progresso geral: <b>${s.percentual}%</b>` : ''}</p>${s.rodando ? progress(s) : ''}
      <p class="small">${escH(s.resumo || 'Nenhuma fonte nesta execução.')}</p>${s.rodando && s.atual ? `<p class="small muted">Agora: ${escH(s.atual)}</p>` : ''}
      <div class="form"><button class="small primary" data-sp="run" ${s.rodando ? 'disabled' : ''}>Atualizar fontes</button>
        <button class="small" data-sp="cancel" ${s.rodando ? '' : 'disabled'}>Cancelar sincronização</button>
        <button class="small" data-sp="retry" ${s.rodando ? 'disabled' : ''}>Tentar novamente fontes com falha</button>
        <button class="small" data-sp="hist">Ver histórico</button> <a class="btn small" href="/api/diagnostics/export">Exportar diagnóstico</a></div>
      <div id="sp-msg" class="small"></div>
      ${Object.keys(groups).sort().map((g) => `<h3 class="sp-grp">${g}. ${escH((s.prioridades || {})[g] || '')}</h3>${groups[g].map(([id, f]) => sourceRow(id, f)).join('')}`).join('') || '<p class="muted">Sem execução recente nesta sessão. Use "Atualizar fontes" ou veja o histórico.</p>'}
      <p class="small muted">Legenda: ${Object.values(s.estados || {}).map(([l, sym]) => `${sym} ${escH(l)}`).join(' · ')}. O percentual considera as fontes desta execução e as etapas da análise — nunca o tempo decorrido.</p>`;
    $('#sp-body').querySelectorAll('[data-sp]').forEach((b) => b.onclick = () => act(b.dataset.sp));
  }
  async function act(a) {
    const msg = (t) => { const m = document.getElementById('sp-msg'); if (m) m.textContent = t; };
    try {
      if (a === 'open') { panel.hidden = false; renderPanel(SNAP || await api('/api/sync/panel')); }
      else if (a === 'cancel') { await post('/api/sync/cancel', {}); msg('Cancelamento solicitado: as gravações em andamento terminam com segurança.'); }
      else if (a === 'run') { const r = await post('/api/sync/start', {}); msg(r.iniciada ? 'Sincronização iniciada.' : 'Já existe uma sincronização em andamento.'); }
      else if (a === 'retry') { const r = await post('/api/sync/retry-failed', {}); panel.hidden = false; msg(r.iniciada ? `Tentando novamente: ${r.fontes.join(', ')}` : (r.mensagem || 'Não foi possível iniciar.')); }
      else if (a === 'hist') { panel.hidden = false; await history(); }
    } catch (e) { msg(e.message || String(e)); }
  }
  async function history() {
    const d = await api('/api/sync/history');
    $('#sp-body').innerHTML = `<p><button class="small" id="sp-back">← Voltar ao progresso</button></p><h3>Histórico de sincronizações</h3>
      ${d.execucoes.map((r) => `<details class="sp-src"><summary>#${r.id} · ${dt(r.inicio)} · <b>${escH(r.rotulo)}</b> <span class="muted small">${escH(r.gatilho || '')}${r.segundos_coleta ? ' · ' + dur(r.segundos_coleta) : ''}</span></summary>
        <table class="small"><tbody>${Object.entries(r.fontes).map(([k, f]) => `<tr><td>${escH(k)}</td><td>${escH(f.estado || '')}</td><td>${f.segundos != null ? dur(f.segundos) : ''}</td><td>${f.novos != null ? fmt(f.novos, 0) + ' novos' : ''}</td><td class="muted">${escH((f.motivo || '').slice(0, 120))}</td></tr>`).join('')}</tbody></table></details>`).join('') || '<p class="muted">Nenhuma sincronização registrada.</p>'}`;
    document.getElementById('sp-back').onclick = () => renderPanel(SNAP || {});
  }
  function onSnap(s) {
    SNAP = s;
    renderBar(s);
    renderPanel(s);
    const st = document.getElementById('status');
    if (st) {
      st.className = 'status ' + (s.rodando ? 's-sync' : (s.contagem || {}).falhas ? 's-warn' : s.fim ? 's-ok' : '');
      st.querySelector('span').textContent = s.rodando ? `sincronizando${s.percentual != null ? ' ' + s.percentual + '%' : ''}` : (s.fim ? s.titulo.toLowerCase() : 'dados locais');
    }
    if (lastFase && lastFase !== s.fase && !s.rodando && ['concluida', 'parcial'].includes(s.fase)) window.dispatchEvent(new CustomEvent('gpi-sync-done'));
    lastFase = s.fase;
    if (document.getElementById('syncpage')) syncPage(true);
  }
  function poll() { clearTimeout(pollT); api('/api/sync/panel').then(onSnap).catch(() => {}).finally(() => { pollT = setTimeout(poll, SNAP && SNAP.rodando ? 2500 : 15000); }); }
  function connect() {
    if (!window.EventSource) { poll(); return; }
    es = new EventSource('/api/sync/events');
    es.addEventListener('estado', (e) => { fails = 0; try { onSnap(JSON.parse(e.data)); } catch (_) { /* ignora quadro inválido */ } });
    es.onerror = () => { fails += 1; if (fails >= 3) { es.close(); poll(); setTimeout(() => { clearTimeout(pollT); connect(); }, 60000); } };
  }
  window.GPI_SYNC = { stopLegacy: true };
  window.GPI_SYNC_OPEN = () => act('open');
  connect();

  /* ---------------------------------------------------------------- página Sincronização */
  async function syncPage(refresh) {
    if (!refresh) main.innerHTML = `<h1>Sincronização</h1><p class="sub">Acompanhe cada API em tempo real: o que está executando, o que terminou, o que falhou e por quê. O painel usa os dados locais enquanto a coleta continua em segundo plano.</p><div id="syncpage">${loading()}</div>`;
    const s = SNAP || await api('/api/sync/panel');
    const box = document.getElementById('syncpage');
    if (!box) return;
    const keep = new Set([...box.querySelectorAll('details[open]')].map((d) => d.dataset.id));
    const fontes = Object.entries(s.fontes || {});
    box.innerHTML = `<div class="panel"><h2>${escH(s.titulo)}${s.percentual != null ? ' — ' + s.percentual + '%' : ''}</h2>${s.rodando ? progress(s) : ''}<p>${escH(s.resumo || '')}</p>
      <div class="form"><button class="primary" data-sp="run" ${s.rodando ? 'disabled' : ''}>Atualizar fontes</button><button data-sp="cancel" ${s.rodando ? '' : 'disabled'}>Cancelar sincronização</button>
      <button data-sp="retry" ${s.rodando ? 'disabled' : ''}>Tentar novamente fontes com falha</button><button data-sp="hist">Ver histórico</button><a class="btn" href="/api/diagnostics/export">Exportar diagnóstico</a></div></div>
      <div class="panel scroll"><table class="small"><thead><tr><th>Fonte</th><th>Prioridade</th><th>Estado</th><th>Início</th><th>Duração</th><th class="num">Jobs</th><th class="num">Novos</th><th class="num">Atualizados</th><th class="num">Tentativas</th><th>Espera</th><th>Cota</th><th>Última OK</th><th>Próxima</th><th>Motivo</th><th>Ações</th></tr></thead><tbody>
      ${fontes.map(([id, f]) => `<tr><td>${escH(f.nome || id)}</td><td>${escH(f.grupo || '')}</td><td>${badge(f)}</td><td>${dt(f.inicio)}</td><td>${dur(f.segundos)}</td>
        <td class="num">${f.jobs_total ? `${f.jobs_feitos || 0}/${f.jobs_total}` : '—'}</td><td class="num">${fmt(f.novos || 0, 0)}</td><td class="num">${fmt(f.atualizados || 0, 0)}</td><td class="num">${f.tentativas || 0}</td>
        <td>${f.espera_s ? dur(f.espera_s) : '—'}</td><td>${f.cota_unidades != null ? f.cota_unidades + ' un.' : '—'}</td><td>${dt(f.ultima_ok)}</td><td>${f.proxima ? dt(f.proxima) : '—'}</td><td class="wrap ${f.estado === 'erro' || f.estado === 'pendente' ? 'neg' : 'muted'}">${escH((f.motivo || '').slice(0, 220))}</td>
        <td><button class="small" data-src="${escH(id)}" ${s.rodando ? 'disabled' : ''} title="Coleta manual desta fonte (respeita as cotas da API)">Atualizar fonte</button> <a class="small" href="#integracoes">Diagnosticar</a></td></tr>`).join('') || '<tr><td colspan="15" class="muted">Nenhuma execução nesta sessão. Clique em "Atualizar fontes" ou veja o histórico.</td></tr>'}</tbody></table></div>`;
    box.querySelectorAll('[data-sp]').forEach((b) => b.onclick = () => (b.dataset.sp === 'hist' ? act('hist') : act(b.dataset.sp)));
    box.querySelectorAll('[data-src]').forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try { const r = await post('/api/sync/start', { fontes: [b.dataset.src], manual: true }); if (!r.iniciada) alert('Já existe uma sincronização em andamento.'); }
      catch (e) { alert(e.message || e); } finally { setTimeout(() => syncPage(true), 800); }
    });
    keep.forEach((id) => { const d = box.querySelector(`details[data-id="${id}"]`); if (d) d.open = true; });
  }

  /* ---------------------------------------------------------------- Central de Integrações: estados + diagnóstico */
  const lastForm = (card) => { const f = card.querySelectorAll(':scope > .form'); return f.length ? f[f.length - 1] : null; };
  const LEVELS = ['configurado', 'autenticado', 'autorizado', 'validado', 'funcional'];
  const LNAME = { configurado: 'Configurado', autenticado: 'Autenticado', autorizado: 'Autorizado', validado: 'Validado', funcional: 'Funcional' };
  function chain(st) {
    if (!st) return '';
    if (['restrito', 'erro', 'disponivel', 'nao_configurado'].includes(st.nivel)) {
      return `<p class="small"><span class="badge ${st.nivel === 'erro' ? 'bad' : ''}">${escH(st.rotulo)}</span>${st.nivel === 'disponivel' ? ' — fonte pública; vira Funcional após a primeira coleta real gravada' : ''}</p>`;
    }
    const k = LEVELS.indexOf(st.nivel);
    return `<ol class="chain" aria-label="Estado da integração">${LEVELS.map((l, i) => `<li class="${i <= k ? 'on' : ''}"><span aria-hidden="true">${i <= k ? '✓' : '○'}</span> ${LNAME[l]}</li>`).join('')}</ol>`;
  }
  function steps(res) {
    if (!res || !res.etapas || !res.etapas.length) return '';
    return `<table class="small diag"><tbody>${res.etapas.map((s) => `<tr><td>${s.ok ? '✓' : '✕'}</td><td><b>${escH(s.etapa)}</b></td><td>${escH(s.mensagem || '')}${s.codigo ? ` <code>${escH(s.codigo)}</code>` : ''}${s.acao ? `<br><span class="muted">Ação: ${escH(s.acao)}</span>` : ''}
      ${s.resultados ? `<table class="small"><thead><tr><th>Palavra-chave</th><th class="num">Média mensal (aprox.)</th><th class="num">Meses</th><th>País</th><th>Idioma</th><th>Fonte</th></tr></thead><tbody>${s.resultados.map((r) => `<tr><td>${escH(r.palavra_chave)}</td><td class="num">${r.media_mensal_aprox == null ? '—' : fmt(r.media_mensal_aprox, 0)}</td><td class="num">${r.meses_historico}</td><td>${r.pais}</td><td>${r.idioma}</td><td>${escH(r.fonte)}</td></tr>`).join('')}</tbody></table>` : ''}
      ${s.contas ? `<p class="muted">${s.contas.length} conta(s) encontrada(s).</p>` : ''}</td></tr>`).join('')}</tbody></table>
      ${res.nivel_acesso ? `<p class="small">Nível de acesso da API: ${escH(res.nivel_acesso)}</p>` : ''}${res.unidades != null ? `<p class="small muted">Cota estimada usada no diagnóstico: ${res.unidades} unidades.</p>` : ''}${res.aviso ? `<p class="small muted">${escH(res.aviso)}</p>` : ''}`;
  }
  async function augmentIntegrations() {
    const d = await api('/api/integrations?v=6');
    for (const p of d.integracoes) {
      const card = document.getElementById('integ-' + p.id);
      if (!card) continue;
      const st = p.estados || {};
      card.querySelector('h2').insertAdjacentHTML('afterend', `<div class="integ-state">${chain(st)}
        <p class="small muted">Credenciais: ${Object.keys(p.credenciais || {}).length ? 'configuradas' : 'nenhuma'} · Registros: ${fmt(st.registros || 0, 0)} · Última atualização: ${dt(p.ultima_sincronizacao)}${st.diagnostico_em ? ` · Diagnóstico: ${dt(st.diagnostico_em)}` : ''}</p>
        ${p.diagnosticavel ? `<button class="small" data-diag="${p.id}">Diagnosticar integração</button>` : ''}<div class="diag-out" id="diag-${p.id}">${st.passos && st.passos.length ? steps({ etapas: st.passos }) : ''}</div></div>`);
      if (p.id === 'google_ads') gadsWizard(card);
      if (p.id === 'meta') metaModules(card);
      if (p.id === 'youtube') lastForm(card)?.insertAdjacentHTML('beforeend', ' <button data-ytnow="1">Atualizar agora</button> <a class="btn" href="#youtube">Ver vídeos armazenados</a>');
    }
    main.querySelectorAll('[data-diag]').forEach((b) => b.onclick = async () => {
      const out = document.getElementById('diag-' + b.dataset.diag);
      b.disabled = true; out.innerHTML = '<span class="spinner"></span> executando testes pequenos e seguros…';
      try { const r = await post(`/api/integrations/${b.dataset.diag}/diagnose`, {}); out.innerHTML = steps(r.resultado); } catch (e) { out.innerHTML = `<span class="neg">${escH(e.message)}</span>`; } finally { b.disabled = false; }
    });
    main.querySelectorAll('[data-ytnow]').forEach((b) => b.onclick = async () => { const r = await post('/api/integrations/youtube/refresh', {}); alert(r.mensagem); });
  }
  async function gadsWizard(card) {
    const info = await api('/api/integrations/google_ads/info');
    const form = card.querySelector('[data-form="google_ads"]');
    const contas = info.contas || [];
    const html = `<div class="wizard"><h3>Google Ads — Planejador de palavras-chave</h3>
      <p class="small"><b>Etapa 1 — Configuração.</b> Informe OAuth Client ID e Client Secret acima e clique em <i>Salvar dados do aplicativo</i>. Developer token: <b>${escH(info.developer_token)}</b>.</p>
      <p class="small"><b>Etapa 2 — Autorização.</b> ${info.autenticado ? '✓ Login Google autorizado.' : 'Clique em <i>Entrar com Google</i>.'}</p>
      <p class="small"><b>Etapa 3 — Identificação de conta.</b> <button class="small" data-gads="accounts" ${info.autenticado ? '' : 'disabled'}>Identificar contas disponíveis</button></p>
      <div id="gads-accts">${accounts(contas, info)}</div>
      <p class="small"><b>Etapa 4 — Diagnóstico.</b> OAuth, conta, nível de acesso da API e permissão de planejamento: <button class="small" data-diag2="google_ads">Verificar acesso</button> <button class="small" data-act="sync" data-pid="google_ads">Sincronizar dados</button></p>
      <div id="gads-diag">${info.ultimo_diagnostico && info.ultimo_diagnostico.resultado ? steps(info.ultimo_diagnostico.resultado) : ''}</div></div>`;
    (form || card.querySelector('.form')).insertAdjacentHTML('afterend', html);
    card.querySelector('[data-gads="accounts"]').onclick = async (e) => {
      e.target.disabled = true; $('#gads-accts').innerHTML = '<span class="spinner"></span> consultando contas acessíveis…';
      try { const r = await post('/api/integrations/google_ads/accounts', {}); $('#gads-accts').innerHTML = (r.mensagem ? `<p class="neg small">${escH(r.mensagem)}${r.codigo ? ` <code>${escH(r.codigo)}</code>` : ''}</p><p class="small muted">${escH(r.acao || '')}</p>` : '') + accounts(r.contas || [], await api('/api/integrations/google_ads/info')); bindSel(); } finally { e.target.disabled = false; }
    };
    card.querySelector('[data-diag2]').onclick = async (e) => {
      e.target.disabled = true; $('#gads-diag').innerHTML = '<span class="spinner"></span> verificando (1 listagem, 1 leitura de conta, 1 consulta com 3 palavras-chave)…';
      try { const r = await post('/api/integrations/google_ads/diagnose', {}); $('#gads-diag').innerHTML = steps(r.resultado); } finally { e.target.disabled = false; }
    };
    bindSel();
  }
  function accounts(contas, info) {
    if (!contas.length) return '<p class="small muted">Nenhuma conta listada ainda.</p>';
    return `<table class="small"><thead><tr><th></th><th>Conta</th><th>Customer ID</th><th>Tipo</th><th>Via administradora</th></tr></thead><tbody>${contas.map((c) => `<tr>
      <td><input type="radio" name="gads-acct" value="${escH(c.customer_id)}" data-login="${escH(c.via_gerente || '')}" ${c.customer_id === info.conta ? 'checked' : ''} ${c.gerente ? 'disabled title="Conta administradora (MCC): escolha uma conta-cliente"' : ''}></td>
      <td>${escH(c.nome || '')}</td><td><code>${escH(c.customer_id)}</code></td><td>${c.gerente ? 'administradora (MCC)' : c.teste ? 'conta de teste' : c.gerente === false ? 'conta de anúncios' : '—'}</td><td>${escH(c.via_gerente || '—')}</td></tr>`).join('')}</tbody></table>
      <p class="small muted">Conta administradora é opcional: usada só quando a conta é acessada por uma MCC.</p>`;
  }
  function bindSel() {
    main.querySelectorAll('input[name="gads-acct"]').forEach((r) => r.onchange = async () => {
      await post('/api/integrations/google_ads/select', { customer_id: r.value, login_customer_id: r.dataset.login || null });
    });
  }
  async function metaModules(card) {
    const d = await api('/api/integrations/meta/modules');
    const kb = d.bloqueio_conhecido;
    (lastForm(card) || card).insertAdjacentHTML('beforebegin', `<div class="wizard"><h3>Módulos de autorização (cada um pede só as suas permissões)</h3>
      <table class="small"><thead><tr><th>Módulo</th><th>Permissões</th><th>Situação</th><th>Uso</th><th></th></tr></thead><tbody>
      ${Object.entries(d.modulos).map(([k, m]) => `<tr><td><b>${escH(m.nome)}</b></td><td><code>${escH(m.escopos.join(', '))}</code></td><td>${m.concedido ? '✓ concedido' : `○ ${m.faltando.length ? 'faltando: ' + escH(m.faltando.join(', ')) : ''}`}</td>
        <td class="wrap">${escH(m.uso)}${m.revisao ? `<br><span class="muted">${escH(m.revisao)}</span>` : ''}</td><td><button class="small" data-metamod="${k}">Conectar</button></td></tr>`).join('')}</tbody></table>
      <details class="small"><summary>Se a Meta mostrar “${escH(kb.texto)}”</summary><p>${escH(kb.causa)}</p><ol>${kb.etapas.map((e) => `<li>${escH(e)}</li>`).join('')}</ol>
      <p class="muted">Esse bloqueio acontece na página da Meta, antes de qualquer retorno ao GPI; reduzir permissões ajuda a isolar o problema, mas não garante que ele desapareça.</p></details></div>`);
    card.querySelectorAll('[data-metamod]').forEach((b) => b.onclick = async () => {
      try { const r = await post('/api/integrations/meta/oauth/start', { modulo: b.dataset.metamod }); window.open(r.url, '_blank', 'noopener'); }
      catch (e) { alert(e.message); }
    });
  }
  const origIntegrations = PAGES.integracoes;
  async function pageIntegrations() { await origIntegrations(); await augmentIntegrations(); }

  /* ---------------------------------------------------------------- YouTube Intelligence */
  async function pageYoutube() {
    main.innerHTML = `<h1>YouTube Intelligence</h1><p class="sub">Vídeos de review, unboxing e comparativos sobre os produtos, pela API oficial. A lista vem direto do banco local — inclusive quando não há vídeos novos nesta semana.</p><div id="yt">${loading()}</div>`;
    const s = await api('/api/youtube/status');
    const src = s.fonte || {};
    $('#yt').innerHTML = `<div class="kpis">
        <div class="kpi"><span>Vídeos armazenados</span><b>${fmt(s.videos_armazenados, 0)}</b><small class="muted">${fmt(s.produtos_com_videos, 0)} produtos</small></div>
        <div class="kpi"><span>Novos na última sincronização</span><b>${fmt(s.novos_na_ultima_sincronizacao, 0)}</b></div>
        <div class="kpi"><span>Última coleta</span><b style="font-size:15px">${dt(s.ultima_coleta)}</b><small class="muted">estatísticas: ${dt(s.ultima_atualizacao)}</small></div>
        <div class="kpi"><span>Período de publicação</span><b style="font-size:15px">${escH((s.periodo_publicacao[0] || '—'))} a ${escH(s.periodo_publicacao[1] || '—')}</b><small class="muted">país da consulta: ${escH(s.pais_consulta)}</small></div>
        <div class="kpi"><span>Status da fonte</span><b style="font-size:15px">${escH(src.state || '—')}</b><small class="muted">${escH((src.message || '').slice(0, 80))}</small></div>
        <div class="kpi"><span>Cota usada hoje (estimada)</span><b>${fmt(s.cota_usada_hoje_estimada, 0)}</b><small class="muted">restante no limite do GPI: ${fmt(s.restante_no_limite_gpi, 0)} de ${fmt(s.limite_diario_gpi, 0)}</small></div>
        <div class="kpi"><span>Próxima busca elegível</span><b style="font-size:15px">${escH(s.proxima_busca_elegivel)}</b><small class="muted">estatísticas: ${escH(s.proxima_atualizacao_estatisticas)}</small></div></div>
      <div class="banner info small">${escH(s.o_que_conta)} ${escH(s.politica)} ${escH(s.cota_aviso)}</div>
      <div class="panel"><div class="form" id="ytf">
        <label class="f">Produto<select data-k="produto"><option value="">Todos</option></select></label>
        <label class="f">Categoria<select data-k="categoria"><option value="">Todas</option></select></label>
        <label class="f">Palavra-chave<input data-k="q" placeholder="ex.: carregador"></label>
        <label class="f">Período<select data-k="dias"><option value="">Todos</option><option value="30">30 dias</option><option value="90">90 dias</option><option value="180">180 dias</option></select></label>
        <label class="f">Canal<input data-k="canal"></label>
        <button class="primary" id="ytgo">Consultar vídeos armazenados</button> <button id="ytnow">Atualizar agora</button></div>
        <div id="ytl"></div></div>`;
    const load = async (first) => {
      const qs = new URLSearchParams();
      main.querySelectorAll('#ytf [data-k]').forEach((i) => { if (i.value) qs.set(i.dataset.k, i.value); });
      $('#ytl').innerHTML = loading('Consultando o banco local…');
      const d = await api('/api/youtube/videos?' + qs.toString());
      if (first) {
        const sp = main.querySelector('[data-k="produto"]'), sc = main.querySelector('[data-k="categoria"]');
        d.produtos.forEach((p) => sp.insertAdjacentHTML('beforeend', `<option value="${escH(p.id)}">${escH(p.nome)}</option>`));
        d.categorias.forEach((c) => sc.insertAdjacentHTML('beforeend', `<option>${escH(c)}</option>`));
      }
      $('#ytl').innerHTML = d.videos.length ? `<p class="small muted">${d.total} vídeo(s)${d.total >= 500 ? ' (primeiros 500)' : ''}.</p><div class="scroll" style="max-height:620px"><table class="small"><thead><tr><th>Título</th><th>Canal</th><th>Publicação</th><th>Produto identificado</th><th class="num">Visualizações</th><th class="num">Curtidas</th><th>País da consulta</th><th>Última atualização</th></tr></thead><tbody>
        ${d.videos.map((v) => `<tr><td class="wrap"><a href="${escH(v.url)}" target="_blank" rel="noopener">${escH(v.titulo)}</a></td><td>${escH(v.canal || '')}</td><td>${escH(v.publicado || '')}</td><td>${escH(v.produto)}</td>
          <td class="num">${v.visualizacoes == null ? '—' : fmt(v.visualizacoes, 0)}</td><td class="num">${v.curtidas == null ? 'não divulgadas' : fmt(v.curtidas, 0)}</td><td>${escH(v.pais_consulta)}</td><td>${dt(v.atualizado)}</td></tr>`).join('')}</tbody></table></div>
        <p class="small muted">Estatísticas públicas do YouTube, exibidas como publicadas e sem combinação com outras fontes.</p>`
        : `<div class="empty"><b>Nenhum vídeo com estes filtros.</b><br>${s.videos_armazenados ? 'Há vídeos armazenados: limpe os filtros.' : 'Conecte a chave do YouTube na <a href="#integracoes">Central de Integrações</a> e sincronize.'}</div>`;
    };
    $('#ytgo').onclick = () => load(false);
    $('#ytnow').onclick = async () => { const r = await post('/api/integrations/youtube/refresh', {}); alert(r.mensagem); };
    await load(true);
  }

  return { integracoes: pageIntegrations, youtube: pageYoutube, sincronizacao: () => syncPage(false) };
};
