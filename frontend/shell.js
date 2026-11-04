/* GPI v0.5 — moldura da interface: barra lateral com categorias expansíveis (accordion), modo
   recolhido só com ícones, busca global e indicador de status da coleta. Sem bibliotecas externas. */
(function () {
  const store = { get(k) { try { return localStorage.getItem('gpi.' + k); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem('gpi.' + k, v); } catch (e) { /* armazenamento indisponível */ } } };
  const $ = (s, r = document) => r.querySelector(s);
  const groups = [...document.querySelectorAll('#nav .grp')];
  const headerOf = (g) => g.querySelector('.grp-h'), bodyOf = (g) => g.querySelector('.grp-b');
  const mini = () => document.body.classList.contains('side-mini');

  function setOpen(g, open) {
    headerOf(g).setAttribute('aria-expanded', String(open));
    bodyOf(g).classList.toggle('open', open);
  }
  function openOnly(g) { groups.forEach((x) => setOpen(x, x === g)); if (g) store.set('grp', g.dataset.grp); }
  function closeFlyouts() { groups.forEach((g) => g.classList.remove('flyout')); }

  groups.forEach((g) => {
    headerOf(g).addEventListener('click', (e) => {
      e.stopPropagation();
      if (mini()) {                                   // recolhida: submenu flutuante ao lado do ícone
        const was = g.classList.contains('flyout');
        closeFlyouts();
        if (!was) { g.classList.add('flyout'); bodyOf(g).style.top = headerOf(g).getBoundingClientRect().top + 'px'; }
        headerOf(g).setAttribute('aria-expanded', String(!was));
        return;
      }
      const open = headerOf(g).getAttribute('aria-expanded') !== 'true';
      if (open) openOnly(g); else { setOpen(g, false); store.set('grp', ''); }
    });
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('#nav')) closeFlyouts(); });
  document.querySelectorAll('#nav a').forEach((a) => a.addEventListener('click', closeFlyouts));

  // teclado: ↑/↓ entre itens visíveis do menu; Home/End; Esc fecha submenu flutuante
  $('#nav').addEventListener('keydown', (e) => {
    const items = [...document.querySelectorAll('#nav .grp-h, #nav .grp-b.open a, #nav .grp.flyout a')].filter((x) => x.offsetParent !== null);
    const i = items.indexOf(document.activeElement);
    let n = null;
    if (e.key === 'ArrowDown') n = items[Math.min(items.length - 1, i + 1)];
    else if (e.key === 'ArrowUp') n = items[Math.max(0, i - 1)];
    else if (e.key === 'Home') n = items[0];
    else if (e.key === 'End') n = items[items.length - 1];
    else if (e.key === 'Escape') { closeFlyouts(); return; }
    if (n) { e.preventDefault(); n.focus(); }
  });

  // recolher toda a barra lateral
  const btn = $('#collapse');
  function applyMini(on) {
    document.body.classList.toggle('side-mini', on);
    btn.setAttribute('aria-pressed', String(on));
    btn.setAttribute('aria-label', on ? 'Expandir barra lateral' : 'Recolher barra lateral');
    btn.title = btn.getAttribute('aria-label');
    closeFlyouts();
    if (!on) { const g = groups.find((x) => x.classList.contains('has-active')) || groups[0]; openOnly(g); }
  }
  btn.addEventListener('click', () => { const on = !mini(); applyMini(on); store.set('mini', on ? '1' : '0'); });

  // estado inicial: só "Visão Geral" aberta (ou a categoria da página atual)
  groups.forEach((g) => setOpen(g, false));
  if (store.get('mini') === '1') applyMini(true);

  window.GPI_SHELL = {
    onRoute(navKey) {
      let active = null;
      document.querySelectorAll('#nav a[href]').forEach((a) => {
        const on = a.getAttribute('href') === '#' + navKey;
        a.classList.toggle('active', on);
        if (on) { a.setAttribute('aria-current', 'page'); active = a.closest('.grp'); } else a.removeAttribute('aria-current');
      });
      groups.forEach((g) => g.classList.toggle('has-active', g === active));
      if (!mini()) openOnly(active || groups.find((g) => g.dataset.grp === (store.get('grp') || 'overview')) || groups[0]);
      closeFlyouts();
    },
  };

  // ------------------------------------------------------------- busca global
  const q = $('#gq'), res = $('#gres');
  let timer = null, sel = -1, items = [];
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function close() { res.hidden = true; q.setAttribute('aria-expanded', 'false'); sel = -1; }
  function render() {
    res.innerHTML = items.length ? items.map((r, i) => `<a href="${esc(r.href)}" role="option" class="${i === sel ? 'sel' : ''}" aria-selected="${i === sel}">
      <span>${esc(r.titulo)}</span><small>${esc(r.tipo)}${r.detalhe ? ' · ' + esc(r.detalhe) : ''}</small></a>`).join('')
      : '<div class="empty" style="margin:8px">Nada encontrado. O catálogo cresce sozinho conforme as fontes trazem novos produtos.</div>';
    res.hidden = false; q.setAttribute('aria-expanded', 'true');
  }
  q.addEventListener('input', () => {
    clearTimeout(timer);
    const t = q.value.trim();
    if (t.length < 2) { close(); return; }
    timer = setTimeout(async () => {
      try { const r = await fetch('/api/search?q=' + encodeURIComponent(t)); items = (await r.json()).itens || []; sel = -1; render(); } catch (e) { close(); }
    }, 180);
  });
  q.addEventListener('keydown', (e) => {
    if (res.hidden) return;
    if (e.key === 'ArrowDown') { sel = Math.min(items.length - 1, sel + 1); render(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
    else if (e.key === 'Enter' && items[Math.max(0, sel)]) { location.hash = items[Math.max(0, sel)].href.slice(1); close(); q.blur(); }
    else if (e.key === 'Escape') close();
  });
  res.addEventListener('click', () => setTimeout(close, 0));
  document.addEventListener('click', (e) => { if (!e.target.closest('.gsearch')) close(); });

  // ------------------------------------------------------------- status da coleta
  const st = $('#status'), box = $('#statusbox');
  st.addEventListener('click', () => { if (window.GPI_SYNC_OPEN) { window.GPI_SYNC_OPEN(); return; } const open = box.hidden; box.hidden = !open; st.setAttribute('aria-expanded', String(open)); });
  async function poll() {
    if (window.GPI_SYNC) return;                 // v0.6.1: o indicador é atualizado pelos eventos em tempo real
    try {
      const [s, src] = await Promise.all([fetch('/api/sync/status').then((r) => r.json()), fetch('/api/market/sources').then((r) => r.json())]);
      if (window.GPI_SYNC) return;               // v0.6.1 assumiu o indicador durante a requisição
      const failed = src.filter((x) => x.estado === 'falhou');
      let cls = 's-ok', label = 'atualizado';
      if (s.rodando) { cls = 's-sync'; label = `sincronizando ${s.total ? Math.round(100 * s.feitos / s.total) + '%' : ''}`; }
      else if (!s.ultimas || !s.ultimas.length) { cls = ''; label = 'dados locais'; }
      else if (failed.length) { cls = 's-warn'; label = `atualização parcial (${failed.length} fonte${failed.length > 1 ? 's' : ''} indisponíve${failed.length > 1 ? 'is' : 'l'})`; }
      st.className = 'status ' + cls; st.querySelector('span').textContent = label;
      const last = (s.ultimas || []).find((r) => r.finished_at);
      box.innerHTML = `<p><b>Última atualização:</b> ${last ? esc(last.finished_at.replace('T', ' ').slice(0, 16)) + ' (' + esc(last.state) + ')' : 'nenhuma ainda — exibindo dados locais'}</p>
        ${s.rodando ? `<p><b>Agora:</b> ${esc(s.atual || s.fase)}${(s.ativos || []).length ? ' · em paralelo: ' + esc(s.ativos.join(', ')) : ''}</p>` : ''}
        <table class="small"><tbody>${src.filter((x) => x.estado !== 'restrita').map((x) => `<tr><td>${esc(x.nome)}</td><td>${esc(x.estado)}</td><td class="muted">${esc((x.mensagem || '').slice(0, 90))}</td></tr>`).join('')}</tbody></table>
        <p class="muted">Fontes restritas (sem acesso autorizado) não aparecem aqui — veja a Central de Integrações.</p>`;
    } catch (e) { st.className = 'status s-bad'; st.querySelector('span').textContent = 'servidor indisponível'; }
  }
  poll(); setInterval(poll, 6000);
})();
