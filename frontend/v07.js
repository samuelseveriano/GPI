/* GPI v0.7 — Conformidade de Importação: painel, Analisar Produto (com anexos locais), resultado por órgão em cinco
   estados, NCM, homologações/certificados, base regulatória, fornecedores, assistente (IA local ou Modo Essencial)
   e integração com o catálogo ("Analisar requisitos de importação"). Nenhum estado "liberado para importar". */
window.GPI_V07 = function (H, PAGES) {
  const { api, post, fmt, escH, loading, errBox, main, $ } = H;
  const dt = (s) => s ? escH(String(s).replace('T', ' ').slice(0, 16)) : '—';
  const STATE = { 1: 'EXIGÊNCIA IDENTIFICADA', 2: 'POTENCIAL EXIGÊNCIA', 3: 'NÃO IDENTIFICADA NAS FONTES CONSULTADAS', 4: 'INFORMAÇÕES INSUFICIENTES', 5: 'REVISÃO ESPECIALIZADA NECESSÁRIA' };
  const st = (n) => `<span class="cst cst${n}">${n} — ${escH(STATE[n])}</span>`;
  const DISCLAIMER = '<div class="banner info small"><b>Triagem regulatória.</b> O GPI não é autoridade certificadora e não substitui Receita Federal, Siscomex, Anatel, Inmetro, órgãos anuentes, despachante aduaneiro ou profissionais de conformidade. “Não identificada nas fontes consultadas” não é dispensa.</div>';
  const link = (u, t) => u ? `<a href="${escH(u)}" target="_blank" rel="noopener noreferrer">${escH(t || u)}</a>` : '—';
  const tabs = (cur) => `<div class="form ctabs">${[['conformidade', 'Painel'], ['conformidade-analisar', 'Analisar Produto'], ['conformidade-historico', 'Análises'],
    ['conformidade-ncm', 'NCM'], ['conformidade-certificados', 'Homologações e certificados'], ['conformidade-base', 'Base regulatória'],
    ['conformidade-fornecedores', 'Fornecedores'], ['conformidade-assistente', 'Assistente'], ['conformidade-ia', 'IA local']]
    .map(([h, t]) => `<a class="btn small ${h === cur ? 'primary' : ''}" href="#${h}">${t}</a>`).join(' ')}</div>`;
  async function upload(path, file, extraHeaders = {}) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name), ...extraHeaders }, body: file });
  }
  async function report(tipo, formato, aid, btn) {
    const t = btn.textContent; btn.disabled = true; btn.textContent = 'Gerando…';
    try {
      const r = await post('/api/reports/generate', { tipo, formato, filtros: { analise_id: aid } });
      if (r.status === 'gerado') location.href = `/api/reports/${r.id}/download`; else alert('Falha: ' + (r.erro || ''));
    } catch (e) { alert(e.message || e); } finally { btn.disabled = false; btn.textContent = t; }
  }

  /* --------------------------------------------------------------- PAINEL */
  async function pagePanel() {
    main.innerHTML = `<h1>Conformidade de Importação</h1><p class="sub">Investigue certificações, homologações, registros, licenças, anuências e documentos que podem ser necessários para importar um produto ao Brasil — com fontes oficiais e datas de verificação.</p>${tabs('conformidade')}${DISCLAIMER}<div id="cp">${loading('Carregando…')}</div>`;
    const s = await api('/api/compliance/status');
    const b = s.base;
    const an = await api('/api/compliance/analises');
    $('#cp').innerHTML = `${b.aviso ? `<div class="banner">${escH(b.aviso)}</div>` : ''}${s.conflitos.length ? `<div class="banner">Documentos que exigem revisão: ${s.conflitos.map((c) => escH(c.id + ' — ' + c.motivo)).join('; ')}</div>` : ''}
      <div class="kpis"><div class="kpi"><span>Documentos na base</span><b>${s.documentos}</b><small>versão ${escH(b.versao || '?')}</small></div>
      <div class="kpi"><span>Verificação mais antiga</span><b>${escH(b.ultima_verificacao || '—')}</b><small>${b.dias == null ? '' : b.dias + ' dias'}</small></div>
      <div class="kpi"><span>Tabela NCM oficial</span><b>${s.ncm.carregada ? fmt(s.ncm.codigos, 0) + ' códigos' : 'não carregada'}</b><small>${escH(s.ncm.atualizacao_oficial || s.ncm.carregada_em || '')}</small></div>
      <div class="kpi"><span>Homologações Anatel (dados abertos)</span><b>${s.anatel.carregada ? fmt(s.anatel.registros, 0) : 'não carregadas'}</b><small>${dt(s.anatel.carregada_em)}</small></div>
      <div class="kpi"><span>IA local</span><b>${s.ia.modo_efetivo === 'ia_local' ? 'IA Local' : 'Modo Essencial'}</b><small>${s.ia.pacote_encontrado ? 'pacote encontrado' : 'sem pacote (regras + documentos)'}</small></div></div>
      <div class="grid g2"><div class="panel"><h2>Começar</h2><p><a class="btn primary" href="#conformidade-analisar">Analisar Produto</a> <a class="btn" href="#conformidade-assistente">Perguntar ao assistente</a></p>
        <p class="small muted">Do catálogo: abra um produto e use <b>Analisar requisitos de importação</b>. Cada variante é analisada separadamente (ex.: versão com Wi-Fi × sem comunicação sem fio).</p>
        <h3>Os cinco estados</h3>${[1, 2, 3, 4, 5].map((n) => `<p class="small">${st(n)}</p>`).join('')}</div>
      <div class="panel"><h2>Últimas análises</h2>${an.analises.length ? `<table class="small"><tr><th>#</th><th>Produto</th><th>Data</th><th>Resumo</th></tr>${an.analises.slice(0, 8).map((a) => `<tr class="click" data-a="${a.id}"><td>${a.id}</td><td>${escH(a.produto)}</td><td>${dt(a.criado_em)}</td><td>${a.resumo.map((r) => `${escH(r.orgao)}: ${r.estado}`).join(' · ')}</td></tr>`).join('')}</table>` : '<p class="muted">Nenhuma análise ainda.</p>'}</div></div>
      <div class="panel"><h2>Atualizações da base</h2>${s.atualizacoes.length ? `<table class="small"><tr><th>Quando</th><th>Origem</th><th class="num">Novos</th><th class="num">Alterados</th><th class="num">Falhas</th></tr>${s.atualizacoes.map((u) => `<tr><td>${dt(u.concluido_em)}</td><td>${escH(u.origem)}</td><td class="num">${u.novos}</td><td class="num">${u.alterados}</td><td class="num">${u.falhas}</td></tr>`).join('')}</table>` : '<p class="muted small">Nenhuma verificação registrada. Use <a href="#conformidade-base">Base regulatória → Verificar fontes oficiais</a>.</p>'}</div>`;
    main.querySelectorAll('[data-a]').forEach((tr) => tr.onclick = () => { location.hash = 'conformidade-analise/' + tr.dataset.a; });
  }

  /* --------------------------------------------------------------- ANALISAR PRODUTO */
  const TRI = (k, label) => `<label class="f">${label}<select data-k="${k}"><option value="">não sei</option><option value="sim">sim</option><option value="nao">não</option></select></label>`;
  const TXT = (k, label, w = 260, ph = '') => `<label class="f">${label}<input data-k="${k}" style="width:${w}px" placeholder="${escH(ph)}"></label>`;
  async function pageAnalyze(pid) {
    main.innerHTML = `<h1>Analisar Produto</h1><p class="sub">Informe as características técnicas. O GPI não infere exigências só pelo nome: características vindas do nome ou da categoria viram perguntas.</p>${tabs('conformidade-analisar')}${DISCLAIMER}
      <div class="panel"><h2>Identificação</h2><div class="form">${TXT('nome_comercial', 'Nome comercial')}${TXT('categoria', 'Categoria', 180)}${TXT('marca', 'Marca', 160)}${TXT('modelo', 'Modelo técnico exato', 180)}
        ${TXT('fabricante', 'Fabricante', 220)}${TXT('pais_origem', 'País de origem', 120, 'China')}</div>
        <input type="hidden" data-k="product_id"><input type="hidden" data-k="familia"><input type="hidden" data-k="variante"><p class="small muted" id="catinfo"></p></div>
      <div class="panel"><h2>Operação</h2><div class="form"><label class="f">Uso próprio ou comercialização<select data-k="destinacao"><option value="">não informado</option><option value="comercializacao">comercialização</option><option value="uso_proprio">uso próprio</option><option value="amostra">amostra para ensaio</option></select></label>
        ${TXT('finalidade', 'Finalidade', 240)}${TXT('tipo_importacao', 'Tipo de importação', 220, 'ex.: importação direta, remessa expressa')}
        <label class="f">Produto completo ou componente<select data-k="produto_completo"><option value="">não informado</option><option value="completo">produto completo</option><option value="componente">componente/módulo</option></select></label>
        ${TXT('ncm', 'NCM informada ou sugerida', 130, '0000.00.00')}</div></div>
      <div class="panel"><h2>Características técnicas</h2><label class="f" style="display:block">Descrição técnica<textarea data-k="descricao_tecnica" rows="4" style="width:100%" placeholder="Funções, interfaces de comunicação, alimentação, bateria, materiais… (aceita PT/EN/中文)"></textarea></label>
        <div class="form">${TXT('tensao', 'Tensão elétrica', 120, '100–240 V')}${TXT('potencia', 'Potência', 100, 'W')}${TXT('frequencia', 'Frequência', 140, 'Hz / GHz')}${TXT('material', 'Material', 180)}${TXT('componentes', 'Componentes', 260)}</div>
        <div class="form">${TRI('wifi', 'Wi-Fi')}${TRI('bluetooth', 'Bluetooth')}${TRI('radiofrequencia', 'Outro transmissor de RF')}${TRI('celular', 'Comunicação celular')}${TRI('bateria', 'Bateria')}${TRI('bateria_litio', 'Bateria de lítio')}
          ${TRI('alimentacao_rede', 'Ligado à rede elétrica')}${TRI('carregador_fonte', 'Carregador/fonte')}${TRI('brinquedo', 'Brinquedo')}${TRI('publico_infantil', 'Destinado a crianças')}${TRI('instrumento_medicao', 'Instrumento de medição')}
          ${TRI('equipamento_medico', 'Equipamento médico')}${TRI('contato_alimentos', 'Contato com alimentos')}${TRI('produto_controlado', 'Produto controlado')}</div>
        ${TXT('documentacao_disponivel', 'Documentação disponível', 520, 'ex.: datasheet, relatório de ensaio RF, certificado CE')}</div>
      <div class="panel"><h2>Anexos (ficam só neste computador)</h2><p class="small muted">Ficha técnica, manual, catálogo, especificações, relatórios de ensaio, certificados. PDF, TXT, CSV, PNG, JPG, XLSX ou DOCX; até 10 MB cada e 30 MB no total. Arquivos com macros ou conteúdo ativo são recusados; nada é enviado à internet.</p>
        <input type="file" id="files" multiple accept=".pdf,.txt,.csv,.png,.jpg,.jpeg,.xlsx,.docx"><div id="flist" class="small"></div></div>
      <div class="panel"><div class="form"><label class="f">Modo<select id="mode"><option value="essencial">Essencial (regras + documentos)</option><option value="ia_local">IA Local (explicação gerada e verificada)</option></select></label>
        <button class="primary" id="go">Analisar</button><span id="gomsg" class="small"></span></div></div><div id="res"></div>`;
    const anex = [];
    $('#files').onchange = async (e) => {
      for (const f of e.target.files) {
        const row = document.createElement('div'); row.textContent = `${f.name} — enviando…`; $('#flist').appendChild(row);
        try { const r = await upload('/api/compliance/anexos', f); anex.push(r.id); row.textContent = `✔ ${r.nome} (${fmt(r.tamanho / 1024, 0)} KB, ${r.texto_caracteres} caracteres de texto lidos)${r.pdf_com_conteudo_ativo ? ' — contém elementos ativos de PDF (não executados)' : ''}`; }
        catch (err) { row.textContent = `✖ ${f.name}: ${err.message}`; }
      }
      e.target.value = '';
    };
    if (pid) {
      try {
        const d = await api('/api/consumer/product/' + encodeURIComponent(pid));
        const p = d.produto;
        const set = (k, v) => { const el = main.querySelector(`[data-k="${k}"]`); if (el && v) el.value = v; };
        set('nome_comercial', p.name_pt || p.canonical); set('categoria', p.category); set('product_id', p.product_id);
        set('familia', p.family); if (p.level === 'variante') set('variante', p.canonical);
        $('#catinfo').innerHTML = `Produto do catálogo: <b>${escH(p.canonical)}</b> · categoria ${escH(p.category)} · família ${escH(p.family)} · ${escH(p.level)}${p.ncm_hint ? ` · SH4 de referência ${escH(p.ncm_hint)} (não é NCM)` : ''}.${(p.variantes || []).length ? ` Variantes: ${p.variantes.map((v) => `<a href="#conformidade-analisar/${encodeURIComponent(v.product_id)}">${escH(v.canonical)}</a>`).join(', ')} — analise cada uma separadamente.` : ''}`;
      } catch (e) { $('#catinfo').textContent = 'Produto do catálogo não encontrado; preencha manualmente.'; }
    }
    $('#go').onclick = async () => {
      const form = {};
      main.querySelectorAll('[data-k]').forEach((el) => { if (el.value) form[el.dataset.k] = el.value; });
      $('#go').disabled = true; $('#gomsg').innerHTML = '<span class="spinner"></span> analisando…';
      try {
        const r = await post('/api/compliance/analisar', { formulario: form, anexos: anex, modo: $('#mode').value });
        location.hash = 'conformidade-analise/' + r.id;
      } catch (e) { $('#gomsg').innerHTML = `<span class="neg">${escH(e.message)}</span>`; } finally { $('#go').disabled = false; }
    };
  }

  /* --------------------------------------------------------------- RESULTADO */
  function finding(a) {
    return `<div class="cfind cb${a.estado}"><div>${st(a.estado)} <b>${escH(a.titulo)}</b> <span class="muted small">regra ${escH(a.regra)}</span></div>
      <p class="small"><b>Motivo:</b> ${escH(a.motivo)}</p>${a.observacao ? `<p class="small"><b>${escH(a.observacao)}</b></p>` : ''}
      ${a.evidencias.length ? `<p class="small"><b>Evidências:</b> ${a.evidencias.map(escH).join(' · ')}</p>` : ''}
      ${a.perguntas.length ? `<p class="small"><b>Informações necessárias:</b> ${a.perguntas.map(escH).join(' · ')}</p>` : ''}
      ${a.proxima_acao ? `<p class="small"><b>Próxima ação:</b> ${escH(a.proxima_acao)}</p>` : ''}
      <p class="small"><b>Fontes:</b> ${a.fontes.map((f) => `${link(f.url_oficial, f.orgao + ' ' + (f.numero && f.numero !== '—' ? f.numero : f.titulo))} <span class="muted">(verificado ${escH(f.ultima_verificacao || '?')}, ${escH(f.status_atualizacao || '')})</span>`).join(' · ') || '—'}</p></div>`;
  }
  async function pageResult(aid) {
    main.innerHTML = `<h1>Análise regulatória</h1>${tabs('')}<div id="rr">${loading('Carregando…')}</div>`;
    let r;
    try { r = await api('/api/compliance/analises/' + encodeURIComponent(aid)); } catch (e) { $('#rr').innerHTML = errBox(e); return; }
    const p = r.produto;
    const nome = p.nome_comercial || p.modelo || 'produto';
    const cert = r.certificados;
    $('#rr').innerHTML = `<h2>PRODUTO: ${escH(nome.toUpperCase())}</h2><p class="small muted">Análise nº ${r.id} · ${dt(r.criado_em)} · modo ${escH(r.modo)} · base ${escH(r.frescor_base.versao || '?')} (verificação mais antiga ${escH(r.frescor_base.ultima_verificacao || '?')})${p.product_id ? ` · catálogo <a href="#produto-consumo/${encodeURIComponent(p.product_id)}">${escH(p.product_id)}</a>` : ''}${p.variante ? ' · variante ' + escH(p.variante) : ''}</p>
      ${DISCLAIMER}${r.frescor_base.aviso ? `<div class="banner">${escH(r.frescor_base.aviso)}</div>` : ''}
      <div class="form"><button data-rep="regulatorio" data-f="pdf">Relatório PDF</button> <button data-rep="regulatorio" data-f="xlsx">Relatório Excel</button>
        <button data-rep="checklist_fornecedor" data-f="pdf">Checklist PDF</button> <button data-rep="checklist_fornecedor" data-f="xlsx">Checklist Excel</button>
        <a class="btn" href="#conformidade-assistente/${r.id}">Perguntar sobre esta análise</a></div>
      ${r.por_orgao.map((o) => `<div class="panel"><h2>${escH(o.orgao.toUpperCase())} <span class="small">${st(o.pior_estado)}</span></h2>${o.achados.map(finding).join('')}</div>`).join('')}
      ${r.explicacao ? `<div class="panel"><h2>Explicação (${r.explicacao.modo === 'ia_local' ? 'IA local, verificada' : 'Modo Essencial'})</h2>${r.explicacao.aviso ? `<p class="small neg">${escH(r.explicacao.aviso)}</p>` : ''}<p style="white-space:pre-wrap">${escH(r.explicacao.texto)}</p>
        ${r.explicacao.verificacao && r.explicacao.verificacao.removidos.length ? `<details><summary class="small">Trechos removidos pela verificação (${r.explicacao.verificacao.removidos.length})</summary>${r.explicacao.verificacao.removidos.map((x) => `<p class="small">✖ ${escH(x.trecho)} — <i>${escH(x.motivo)}</i></p>`).join('')}</details>` : ''}</div>` : ''}
      <div class="grid g2"><div class="panel"><h2>DOCUMENTOS NECESSÁRIOS</h2>${r.documentos_necessarios.length ? '<ul class="small">' + r.documentos_necessarios.map((d) => `<li>${escH(d)}</li>`).join('') + '</ul>' : '<p class="muted small">—</p>'}
        <h2>INFORMAÇÕES FALTANTES</h2>${r.informacoes_faltantes.length ? '<ul class="small">' + r.informacoes_faltantes.map((d) => `<li>${escH(d)}</li>`).join('') + '</ul>' : '<p class="muted small">—</p>'}</div>
        <div class="panel"><h2>PRÓXIMA AÇÃO</h2><ul class="small">${r.proximas_acoes.map((d) => `<li>${escH(d)}</li>`).join('')}${r.consulta_manual.map((m) => `<li>${escH(m.orgao)}: ${link(m.url, m.nome)} — ${escH(m.como)}</li>`).join('')}</ul>
        <h2>RISCOS</h2><ul class="small">${r.riscos.map((d) => `<li>${escH(d)}</li>`).join('') || '<li class="muted">—</li>'}</ul></div></div>
      <div class="panel"><h2>NCM</h2>${r.ncm ? `<p>Código <b>${escH(r.ncm.codigo_formatado)}</b> — ${escH(r.ncm.estado)}${r.ncm.descricao ? ': ' + escH(r.ncm.descricao) : ''}</p>${(r.ncm.hierarquia || []).map((h) => `<p class="small">${escH(h.nivel)} ${escH(h.codigo)} — ${escH(h.descricao)}</p>`).join('')}${(r.ncm.alertas || []).map((x) => `<p class="small neg">${escH(x)}</p>`).join('')}<p class="small muted">${escH(r.ncm.observacao || r.ncm.aviso || '')}</p>`
        : r.ncm_candidatos.length ? `<p class="small">Candidatos para investigação (não são classificação):</p><table class="small">${r.ncm_candidatos.map((c) => `<tr><td>${escH(c.codigo)}</td><td>${escH(c.descricao)}</td></tr>`).join('')}</table>` : '<p class="muted small">NCM não informada; carregue a tabela NCM oficial para ver candidatos.</p>'}</div>
      <div class="panel"><h2>Homologações e certificados</h2>${cert ? (cert.resultados.length ? `<table class="small"><tr><th>Nº</th><th>Fabricante</th><th>Modelo</th><th>Situação</th><th>Correspondência</th></tr>${cert.resultados.map((x) => `<tr><td>${escH(x.numero || '')}</td><td>${escH(x.fabricante || '')}</td><td>${escH(x.modelo || '')}</td><td>${escH(x.situacao || '')}</td><td class="${x.correspondencia === 'modelo_exato' ? 'pos' : 'neg'}">${escH(x.nota)}</td></tr>`).join('')}</table>` : `<p class="small muted">${escH(cert.mensagem || 'Nenhum registro encontrado nos dados abertos para o modelo informado.')}</p>`) + `<p class="small"><b>${escH(cert.aviso)}</b></p>` : '<p class="small muted">Consulta automática feita quando há exigência Anatel e o modelo é informado.</p>'}
        <p class="small"><a href="#conformidade-certificados/${r.id}">Registrar consulta manual (Anatel/Inmetro)</a></p></div>
      <div class="panel"><h2>Checklist técnico para o fornecedor</h2><div class="form"><label class="f">Idioma<select id="cklang"><option value="pt">Português</option><option value="en">English</option><option value="zh">简体中文</option></select></label></div>
        <ol class="small" id="ckl"></ol><p class="small muted">${escH(r.checklist.aviso_internacional)} ${escH(r.checklist.aviso_traducao)}</p></div>
      <div class="panel"><h2>FONTES</h2><div class="scroll"><table class="small"><tr><th>Órgão</th><th>Norma/fonte</th><th>Situação</th><th>Última verificação</th><th>Status</th></tr>${r.fontes.map((f) => `<tr><td>${escH(f.orgao)}</td><td>${link(f.url_oficial, (f.numero && f.numero !== '—' ? f.numero + ' — ' : '') + f.titulo)}${f.localizar_no_portal ? ` <span class="muted">(${escH(f.localizar_no_portal)})</span>` : ''}</td><td>${escH(f.situacao)}</td><td>${escH(f.ultima_verificacao || '')}</td><td>${escH(f.status_atualizacao || '')}</td></tr>`).join('')}</table></div>
        <p class="small muted">${r.limitacoes.map(escH).join(' ')}</p></div>`;
    const ck = () => { const l = $('#cklang').value; $('#ckl').innerHTML = r.checklist.itens.map((i) => `<li>${escH(i[l] || i.pt)}</li>`).join(''); };
    $('#cklang').onchange = ck; ck();
    main.querySelectorAll('[data-rep]').forEach((b) => b.onclick = () => report(b.dataset.rep, b.dataset.f, r.id, b));
  }

  async function pageHistory() {
    main.innerHTML = `<h1>Análises regulatórias</h1>${tabs('conformidade-historico')}<div id="hh">${loading()}</div>`;
    const d = await api('/api/compliance/analises');
    $('#hh').innerHTML = d.analises.length ? `<div class="panel"><table><tr><th>#</th><th>Produto</th><th>Catálogo</th><th>Data</th><th>Modo</th><th>Resumo por órgão</th></tr>${d.analises.map((a) => `<tr class="click" data-a="${a.id}"><td>${a.id}</td><td>${escH(a.produto)}</td><td>${escH(a.product_id || '')}</td><td>${dt(a.criado_em)}</td><td>${escH(a.modo)}</td><td class="small">${a.resumo.map((r) => `${escH(r.orgao)}: ${st(r.estado)}`).join(' ')}</td></tr>`).join('')}</table></div>` : '<div class="empty">Nenhuma análise ainda. <a href="#conformidade-analisar">Analisar Produto</a></div>';
    main.querySelectorAll('[data-a]').forEach((tr) => tr.onclick = () => { location.hash = 'conformidade-analise/' + tr.dataset.a; });
  }

  /* --------------------------------------------------------------- NCM */
  async function pageNcm() {
    main.innerHTML = `<h1>Assistência à classificação NCM</h1>${tabs('conformidade-ncm')}<div class="banner info small">O GPI valida formato, existência e vigência na tabela oficial e sugere candidatos — não faz classificação fiscal definitiva. Valide no Sistema Classif e, havendo dúvida, por consulta formal à Receita Federal.</div>
      <div class="panel" id="nmeta">${loading()}</div>
      <div class="grid g2"><div class="panel"><h2>Validar código</h2><div class="form"><input id="ncmc" placeholder="8517.62.77" style="width:140px"><button class="primary" id="ncmv">Validar</button></div><div id="ncmo"></div></div>
      <div class="panel"><h2>Códigos candidatos</h2><textarea id="ncmt" rows="3" style="width:100%" placeholder="Descrição técnica: função, materiais, alimentação, interfaces…"></textarea><button id="ncms">Buscar candidatos</button><div id="ncml"></div></div></div>`;
    const meta = async () => {
      const s = await api('/api/compliance/status'); const m = s.ncm;
      $('#nmeta').innerHTML = `<h2>Tabela NCM oficial</h2><p class="small">${m.carregada ? `${fmt(m.codigos, 0)} códigos · ${escH(m.atualizacao_oficial || '')} · ${escH(m.ato || '')} · fonte ${escH(m.fonte || '')} · carregada ${dt(m.carregada_em)} · SHA-256 ${escH((m.sha256 || '').slice(0, 16))}…` : 'Não carregada.'}</p>
        <div class="form"><button id="nup">Baixar tabela oficial agora</button> <label class="btn">Carregar arquivo da TI (JSON oficial)<input type="file" id="nfile" accept=".json" hidden></label> <span class="small muted">Origem: ${link(m.url_oficial, 'Portal Único — download público')}</span></div><div id="nmsg" class="small"></div>`;
      $('#nup').onclick = async () => { $('#nmsg').innerHTML = '<span class="spinner"></span> baixando…'; try { const r = await post('/api/compliance/ncm/atualizar', {}); $('#nmsg').textContent = `✔ ${r.codigos} códigos carregados.`; meta(); } catch (e) { $('#nmsg').innerHTML = `<span class="neg">${escH(e.message)}</span>`; } };
      $('#nfile').onchange = async (e) => { try { const r = await upload('/api/compliance/ncm/arquivo', e.target.files[0]); $('#nmsg').textContent = `✔ ${r.codigos} códigos carregados do arquivo.`; meta(); } catch (err) { $('#nmsg').innerHTML = `<span class="neg">${escH(err.message)}</span>`; } };
    };
    await meta();
    $('#ncmv').onclick = async () => {
      const v = await post('/api/compliance/ncm/validar', { ncm: $('#ncmc').value });
      $('#ncmo').innerHTML = `<p><b>${escH(v.codigo_formatado)}</b> — ${escH(v.estado)}${v.descricao ? ': ' + escH(v.descricao) : ''}</p>${(v.hierarquia || []).map((h) => `<p class="small">${escH(h.nivel)} ${escH(h.codigo)} — ${escH(h.descricao)}</p>`).join('')}<p class="small muted">${escH(v.observacao || v.aviso || '')}</p>`;
    };
    $('#ncms').onclick = async () => {
      const d = await post('/api/compliance/ncm/candidatos', { texto: $('#ncmt').value });
      $('#ncml').innerHTML = `<p class="small muted">${escH(d.aviso)}</p>${d.candidatos.length ? `<table class="small">${d.candidatos.map((c) => `<tr><td>${escH(c.codigo)}</td><td>${escH(c.descricao)}<br><span class="muted">${c.hierarquia.map((h) => escH(h.codigo + ' ' + h.descricao)).join(' › ')}</span></td></tr>`).join('')}</table>` : '<p class="muted small">Sem candidatos (tabela não carregada ou descrição insuficiente).</p>'}`;
    };
  }

  /* --------------------------------------------------------------- HOMOLOGAÇÕES / CERTIFICADOS */
  async function pageCerts(aid) {
    main.innerHTML = `<h1>Homologações e certificados</h1>${tabs('conformidade-certificados')}<div class="banner info small">Homologação ou certificado de produto semelhante, de outra marca ou de outro modelo <b>não</b> vale para o produto analisado. Não confunda fabricante, marca comercial e modelo técnico.</div>
      <div class="panel" id="ameta">${loading()}</div>
      <div class="panel"><h2>Consultar homologações Anatel (dados abertos, localmente)</h2><div class="form"><input id="qn" placeholder="Nº de homologação" style="width:160px"><input id="qf" placeholder="Fabricante" style="width:200px"><input id="qm" placeholder="Modelo técnico exato" style="width:200px"><button class="primary" id="qgo">Consultar</button></div><div id="qres"></div></div>
      <div class="panel"><h2>Consulta manual assistida e registro</h2><div id="links"></div><div class="form"><label class="f">Órgão<select id="ro"><option>Anatel</option><option>Inmetro</option></select></label>
        <label class="f">Resultado<select id="rr2"><option value="encontrado_modelo_exato">encontrado — modelo exato</option><option value="encontrado_semelhante">encontrado — só semelhante</option><option value="nao_encontrado">não encontrado</option><option value="inconclusivo">inconclusivo</option></select></label>
        <input id="rq" placeholder="O que foi pesquisado (marca/modelo/nº)" style="width:260px"><input id="re" placeholder="Evidência (nº do registro, data, observação)" style="width:300px"><button id="rsave">Registrar</button></div><div id="rlist" class="small"></div></div>`;
    const load = async () => {
      const s = await api('/api/compliance/status'); const m = s.anatel;
      $('#ameta').innerHTML = `<h2>Dados abertos da Anatel</h2><p class="small">${m.carregada ? `${fmt(m.registros, 0)} registros · carregados ${dt(m.carregada_em)} · SHA-256 ${escH((m.sha256 || '').slice(0, 16))}…` : 'Não carregados.'} Origem: ${link(m.url_oficial, 'dados abertos — produtos homologados')}</p>
        <div class="form"><button id="aup">Baixar dados oficiais agora</button> <label class="btn">Carregar ZIP da TI<input type="file" id="afile" accept=".zip" hidden></label></div><div id="amsg" class="small"></div>`;
      $('#aup').onclick = async () => { $('#amsg').innerHTML = '<span class="spinner"></span> baixando (pode levar alguns minutos)…'; try { const r = await post('/api/compliance/anatel/atualizar', {}); $('#amsg').textContent = `✔ ${r.registros} registros.`; load(); } catch (e) { $('#amsg').innerHTML = `<span class="neg">${escH(e.message)}</span>`; } };
      $('#afile').onchange = async (e) => { try { const r = await upload('/api/compliance/anatel/arquivo', e.target.files[0]); $('#amsg').textContent = `✔ ${r.registros} registros.`; load(); } catch (err) { $('#amsg').innerHTML = `<span class="neg">${escH(err.message)}</span>`; } };
      const c = await api('/api/compliance/certificados' + (aid ? '?analise_id=' + encodeURIComponent(aid) : ''));
      $('#links').innerHTML = '<ul class="small">' + c.links.map((l) => `<li>${escH(l.orgao)}: ${link(l.url, l.nome)} — ${escH(l.como)}</li>`).join('') + '</ul>';
      $('#rlist').innerHTML = c.consultas.length ? `<table><tr><th>Quando</th><th>Órgão</th><th>Consulta</th><th>Resultado</th><th>Evidência</th></tr>${c.consultas.map((x) => `<tr><td>${dt(x.criado_em)}</td><td>${escH(x.orgao)}</td><td>${escH(x.consulta)}</td><td>${escH(x.resultado)}</td><td>${escH(x.evidencia || '')}</td></tr>`).join('')}</table>` : '<p class="muted">Nenhuma consulta registrada.</p>';
    };
    await load();
    $('#qgo').onclick = async () => {
      const d = await post('/api/compliance/anatel/consultar', { numero: $('#qn').value, fabricante: $('#qf').value, modelo: $('#qm').value });
      $('#qres').innerHTML = `${d.mensagem ? `<p class="small">${escH(d.mensagem)}</p>` : ''}${d.resultados.length ? `<table class="small"><tr><th>Nº</th><th>Fabricante</th><th>Modelo</th><th>Nome comercial</th><th>Tipo</th><th>Data</th><th>Situação</th><th>Correspondência</th></tr>${d.resultados.map((x) => `<tr><td>${escH(x.numero || '')}</td><td>${escH(x.fabricante || '')}</td><td>${escH(x.modelo || '')}</td><td>${escH(x.nome_comercial || '')}</td><td>${escH(x.tipo_produto || '')}</td><td>${escH(x.data_homologacao || '')}</td><td>${escH(x.situacao || '')}</td><td class="${x.correspondencia === 'modelo_exato' ? 'pos' : 'neg'}">${escH(x.nota)}</td></tr>`).join('')}</table>` : ''}<p class="small"><b>${escH(d.aviso)}</b> Consulta manual: ${link(d.consulta_manual, 'sistema oficial da Anatel')}</p>`;
    };
    $('#rsave').onclick = async () => {
      try { await post('/api/compliance/certificados', { analise_id: aid ? +aid : null, orgao: $('#ro').value, consulta: { texto: $('#rq').value }, resultado: $('#rr2').value, evidencia: $('#re').value }); load(); }
      catch (e) { alert(e.message); }
    };
  }

  /* --------------------------------------------------------------- BASE REGULATÓRIA */
  async function pageBase() {
    main.innerHTML = `<h1>Base regulatória</h1>${tabs('conformidade-base')}<div class="banner info small">Documentos oficiais usados pelas regras, com número, datas, URL oficial, versão, hash e status de verificação. O texto exibido é um resumo do GPI — confira sempre o texto oficial. Mudanças detectadas nas fontes oficiais são marcadas para revisão e nunca alteram as regras automaticamente.</div>
      <div class="panel"><div class="form"><input id="bq" placeholder="Buscar (ex.: bluetooth, brinquedos, LPCO)" style="width:300px"><select id="bo"><option value="">todos os órgãos</option><option>Anatel</option><option>Inmetro</option><option>Receita Federal</option><option>Siscomex</option><option>Anvisa</option><option>MAPA</option><option>Ibama</option><option>Exército</option></select><button id="bgo">Buscar</button>
        <button id="bcheck">Verificar fontes oficiais agora</button> <a class="btn" href="/api/compliance/base/exportar">Exportar pacote</a> <label class="btn">Importar pacote offline<input type="file" id="bpack" accept=".zip" hidden></label> <input id="bsha" placeholder="SHA-256 publicado do pacote" style="width:260px"></div><div id="bmsg" class="small"></div></div>
      <div class="panel" id="bl">${loading()}</div>`;
    const list = async () => {
      const q = new URLSearchParams(); if ($('#bq').value) q.set('q', $('#bq').value); if ($('#bo').value) q.set('orgao', $('#bo').value);
      const d = await api('/api/compliance/docs?' + q.toString());
      $('#bl').innerHTML = `${d.frescor.aviso ? `<div class="banner">${escH(d.frescor.aviso)}</div>` : ''}<table class="small"><tr><th>Órgão</th><th>Número</th><th>Título</th><th>Publicação</th><th>Vigência</th><th>Situação</th><th>Última verificação</th><th>Status</th><th>Versão</th><th>Hash</th></tr>
        ${d.documentos.map((x) => `<tr class="click" data-d="${escH(x.id)}"><td>${escH(x.orgao)}</td><td>${escH(x.numero || '—')}</td><td>${link(x.url_oficial, x.titulo)}</td><td>${escH(x.data_publicacao || '—')}</td><td>${escH(x.vigencia_inicio || '—')}</td><td class="${x.revogado ? 'neg' : ''}">${escH(x.situacao)}</td><td>${escH(x.ultima_verificacao || '')}</td><td>${escH(x.status_atualizacao || '')}</td><td>${x.versao}</td><td>${escH((x.hash_sha256 || '—').slice(0, 10))}</td></tr>`).join('')}</table><div id="bd"></div>`;
      main.querySelectorAll('[data-d]').forEach((tr) => tr.onclick = async (ev) => {
        if (ev.target.tagName === 'A') return;
        const x = await api('/api/compliance/docs/' + encodeURIComponent(tr.dataset.d));
        $('#bd').innerHTML = `<div class="panel"><h3>${escH(x.orgao)} ${escH(x.numero || '')} — ${escH(x.titulo)}</h3><p class="small">${escH(x.texto)}</p><p class="small muted">Identificador ${escH(x.id)} · ${escH(x.texto_tipo)} · verificação em ${escH(x.ultima_verificacao)} (${(x.fontes_da_verificacao || []).map((u) => link(u, new URL(u).hostname)).join(', ') || '—'})${x.conflito ? ` · <b class="neg">${escH(x.conflito)}</b>` : ''}</p>
          ${x.historico.length ? `<p class="small"><b>Histórico:</b> ${x.historico.map((h) => `v${h.versao} (${escH(h.situacao)}, ${dt(h.substituido_em)}, ${escH(h.motivo || '')})`).join(' · ')}</p>` : ''}</div>`;
      });
    };
    await list();
    $('#bgo').onclick = list;
    $('#bcheck').onclick = async () => { $('#bmsg').innerHTML = '<span class="spinner"></span> lendo as URLs oficiais…'; try { const r = await post('/api/compliance/base/verificar', {}); $('#bmsg').textContent = `Registrados ${r.registrados}, inalterados ${r.inalterados}, alterados (revisão) ${r.alterados}, falhas ${r.falhas}.`; list(); } catch (e) { $('#bmsg').innerHTML = `<span class="neg">${escH(e.message)}</span>`; } };
    $('#bpack').onchange = async (e) => { try { const r = await upload('/api/compliance/base/pacote', e.target.files[0], { 'X-SHA256': $('#bsha').value.trim() }); $('#bmsg').textContent = `✔ Pacote ${r.versao}: novos ${r.novos}, alterados ${r.alterados}, revogados ${r.revogados}.`; list(); } catch (err) { $('#bmsg').innerHTML = `<span class="neg">${escH(err.message)}</span>`; } e.target.value = ''; };
  }

  /* --------------------------------------------------------------- FORNECEDORES */
  async function pageSuppliers() {
    main.innerHTML = `<h1>Fornecedores (informados por você)</h1>${tabs('conformidade-fornecedores')}<p class="sub">Cadastro de fabricantes chineses e de outros países fornecidos pelo usuário. O GPI não coleta dados de plataformas de fornecedores sem autorização.</p>
      <div class="panel"><div class="form">${['nome:Nome (razão social)', 'nome_local:Nome no idioma local (ex.: 中文)', 'cidade:Cidade', 'provincia:Província', 'site:Site', 'contato:Contato', 'produtos:Produtos', 'certificacoes:Certificações informadas', 'observacoes:Observações'].map((x) => { const [k, l] = x.split(':'); return `<label class="f">${l}<input data-s="${k}" style="width:220px"></label>`; }).join('')}
        <label class="f">País<input data-s="pais" value="CN" style="width:60px"></label><input type="hidden" data-s="id"><button class="primary" id="ssave">Salvar</button></div></div><div class="panel" id="sl">${loading()}</div>`;
    const list = async () => {
      const d = await api('/api/compliance/fornecedores');
      $('#sl').innerHTML = d.fornecedores.length ? `<table class="small"><tr><th>Nome</th><th>Local</th><th>Cidade/Província</th><th>Produtos</th><th>Certificações informadas</th><th>Fonte</th><th></th></tr>${d.fornecedores.map((s) => `<tr><td>${escH(s.nome)}</td><td>${escH(s.nome_local || '')}</td><td>${escH([s.cidade, s.provincia].filter(Boolean).join(' / '))}</td><td>${escH(s.produtos || '')}</td><td>${escH(s.certificacoes || '')}</td><td>${escH(s.fonte)}</td><td><button class="small" data-e="${s.id}">Editar</button> <button class="small" data-x="${s.id}">Excluir</button></td></tr>`).join('')}</table><p class="small muted">Certificações informadas pelo fornecedor não comprovam homologação/certificação brasileira.</p>` : '<p class="muted">Nenhum fornecedor cadastrado.</p>';
      main.querySelectorAll('[data-e]').forEach((b) => b.onclick = () => { const s = d.fornecedores.find((x) => x.id === +b.dataset.e); main.querySelectorAll('[data-s]').forEach((el) => { el.value = s[el.dataset.s] ?? ''; }); });
      main.querySelectorAll('[data-x]').forEach((b) => b.onclick = async () => { if (confirm('Excluir este fornecedor?')) { await post(`/api/compliance/fornecedores/${b.dataset.x}/excluir`, { confirmar: true }); list(); } });
    };
    $('#ssave').onclick = async () => { const v = {}; main.querySelectorAll('[data-s]').forEach((el) => { v[el.dataset.s] = el.value; }); try { await post('/api/compliance/fornecedores', v); main.querySelectorAll('[data-s]').forEach((el) => { el.value = el.dataset.s === 'pais' ? 'CN' : ''; }); list(); } catch (e) { alert(e.message); } };
    await list();
  }

  /* --------------------------------------------------------------- ASSISTENTE */
  async function pageAssistant(aid) {
    main.innerHTML = `<h1>Assistente regulatório</h1>${tabs('conformidade-assistente')}<p class="sub">Perguntas sobre homologação, certificação, anuência, NCM e documentos. As respostas citam a base local; a IA local (quando instalada) só explica o que as regras e os documentos sustentam.</p>${DISCLAIMER}
      <div class="panel"><textarea id="aq" rows="3" style="width:100%" placeholder="Ex.: Um produto com Bluetooth precisa de homologação?"></textarea>
        <div class="form"><label class="f">Modo<select id="am"><option value="">padrão da configuração</option><option value="essencial">Essencial</option><option value="ia_local">IA Local</option></select></label>${aid ? `<span class="small">Contexto: análise nº ${escH(aid)}</span>` : ''}<button class="primary" id="ago">Perguntar</button><button id="acancel" disabled>Cancelar</button></div>
        <p class="small muted">Exemplos: ${['Uma fechadura eletrônica precisa de homologação da Anatel?', 'Uma luminária LED precisa de certificação do Inmetro?', 'Existe exigência de LPCO para essa mercadoria?', 'Qual é a diferença entre certificação, homologação e anuência?'].map((q) => `<a href="#" data-q="${escH(q)}">${escH(q)}</a>`).join(' · ')}</p></div><div id="aa"></div>`;
    main.querySelectorAll('[data-q]').forEach((a) => a.onclick = (e) => { e.preventDefault(); $('#aq').value = a.dataset.q; });
    let req = null;
    $('#acancel').onclick = async () => { if (req) await post('/api/compliance/assistente/cancelar', { req_id: req }); };
    $('#ago').onclick = async () => {
      req = Math.random().toString(36).slice(2) + Date.now().toString(36);
      $('#ago').disabled = true; $('#acancel').disabled = false; $('#aa').innerHTML = loading('Consultando a base local…');
      try {
        const r = await post('/api/compliance/assistente', { pergunta: $('#aq').value, modo: $('#am').value || undefined, analise_id: aid, req_id: req });
        $('#aa').innerHTML = `<div class="panel"><h2>Resposta <span class="badge">${r.modo === 'ia_local' ? 'IA local verificada' : 'Modo Essencial'}</span></h2>${r.aviso_ia ? `<p class="small neg">${escH(r.aviso_ia)}</p>` : ''}${r.frescor && r.frescor.aviso ? `<div class="banner">${escH(r.frescor.aviso)}</div>` : ''}
          <p style="white-space:pre-wrap">${escH(r.resposta)}</p>${r.geracao ? `<p class="small muted">${escH(r.geracao.modelo || '')} · ${fmt(r.geracao.segundos, 1)} s</p>` : ''}
          ${r.verificacao && r.verificacao.removidos.length ? `<details><summary class="small">Removido pela verificação (${r.verificacao.removidos.length})</summary>${r.verificacao.removidos.map((x) => `<p class="small">✖ ${escH(x.trecho)} — <i>${escH(x.motivo)}</i></p>`).join('')}</details>` : ''}
          <h3>Fontes</h3><ul class="small">${r.fontes.map((f) => `<li>[${escH(f.id)}] ${link(f.url_oficial, f.orgao + ' — ' + f.titulo)} <span class="muted">(${escH(f.situacao)}, verificado ${escH(f.ultima_verificacao || '?')})</span></li>`).join('')}</ul></div>${ficha(r.investigacao)}`;
      } catch (e) { $('#aa').innerHTML = errBox(e); } finally { $('#ago').disabled = false; $('#acancel').disabled = true; req = null; }
    };
  }

  function ficha(f) {                 // v0.9.1: ficha de investigação regulatória (sem afirmar obrigações)
    if (!f || f.erro) return f && f.erro ? `<p class="small muted">Ficha indisponível: ${escH(f.erro)}</p>` : '';
    const t = (rows, cols) => rows && rows.length ? `<div class="tw"><table class="small compact"><thead><tr>${cols.map((c) => `<th>${escH(c[1])}</th>`).join('')}</tr></thead><tbody>${rows.map((x) => `<tr>${cols.map((c) => `<td>${escH(x[c[0]] == null ? '—' : String(x[c[0]]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '<p class="small muted">Nada encontrado.</p>';
    return `<div class="panel"><h2>Ficha de investigação — ${escH(f.produto)}</h2><p class="small">Categoria provável: <b>${escH(f.categoria_provavel)}</b> · família técnica: ${escH(f.familia_tecnica || '—')} · identificação: ${escH(f.identificacao)}</p>
      <h3>Questões técnicas relevantes</h3>${t(f.questoes_tecnicas, [['questao', 'Questão'], ['resposta', 'Informado'], ['situacao', 'Situação']])}
      <h3>Requisitos potenciais (a confirmar)</h3>${t(f.requisitos_potenciais, [['requisito_potencial', 'Requisito potencial'], ['orgao', 'Órgão'], ['fundamento', 'Documentos-base'], ['aplicabilidade', 'Aplicabilidade'], ['evidencia', 'Evidência'], ['situacao', 'Situação'], ['pendencia', 'Pendência']])}
      <h3>Registros locais (Anatel/Inmetro) — ${f.registros_locais.total}</h3>${t(f.registros_locais.itens, [['correspondencia', 'Correspondência'], ['orgao', 'Órgão'], ['registro', 'Registro'], ['fabricante', 'Fabricante'], ['modelo', 'Modelo'], ['empresa', 'Titular'], ['data', 'Data']])}
      <p class="small muted">${escH(f.registros_locais.regra)}</p><h3>Checklist</h3><ol class="small">${f.checklist.map((x) => `<li>${escH(x)}</li>`).join('')}</ol>
      <ul class="small muted">${f.avisos.map((x) => `<li>${escH(x)}</li>`).join('')}</ul>
      <button class="btn small" onclick="(async()=>{const r=await fetch('/api/suite/conformidade/relatorio.xlsx',{method:'POST',headers:{'Content-Type':'application/json','X-GPI':'1'},body:JSON.stringify(${escH(JSON.stringify({ q: f.produto }))})});const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='gpi-conformidade-preliminar.xlsx';a.click();})()">Gerar relatório de conformidade preliminar</button></div>`;
  }

  /* --------------------------------------------------------------- IA LOCAL */
  async function pageAI() {
    main.innerHTML = `<h1>IA local</h1>${tabs('conformidade-ia')}<div id="ia">${loading()}</div>`;
    const s = await api('/api/ia/status?verificar=1');
    const L = s.limites;
    const v = s.verificacao;
    $('#ia').innerHTML = `<div class="panel"><h2>Situação</h2><p>Modo efetivo: <b>${s.modo_efetivo === 'ia_local' ? 'IA Local' : 'Essencial (regras + documentos)'}</b> · modelo ${s.carregado ? 'carregado (' + escH(s.modelo) + ', ' + fmt(s.tempo_carga_s, 1) + ' s)' : 'não carregado (carrega sob demanda)'}</p>
        ${s.ultimo_erro ? `<p class="neg small">${escH(s.ultimo_erro)}</p>` : ''}
        ${s.pacote_encontrado ? `<p class="small">Pacote em ${escH(v.pasta)} — ${v.ok ? '<span class="pos">íntegro (SHA-256 conferido)</span>' : '<span class="neg">inválido: ' + escH(v.problemas.join('; ')) + '</span>'}</p><table class="small"><tr><th>Arquivo</th><th>Papel</th><th>Licença</th><th>Origem</th><th>OK</th></tr>${v.arquivos.map((f) => `<tr><td>${escH(f.nome)}</td><td>${escH(f.papel || '')}</td><td>${escH(f.licenca || '')}</td><td class="wrap">${escH(f.origem || '')}</td><td>${f.ok ? '✔' : '✖'}</td></tr>`).join('')}</table>`
        : `<p class="small">Pacote não encontrado. Copie a pasta <code>ia</code> do <b>GPI-Local-AI-Model-Pack-v0.7.zip</b> (obtido pelo procedimento aprovado pela TI) para: ${s.pastas_procuradas.map(escH).join(' ou ')}. O GPI não baixa nem executa binários automaticamente.</p>`}
        <div class="form"><button id="iload" ${s.pacote_encontrado && v && v.ok ? '' : 'disabled'}>Carregar agora</button> <button id="iun">Descarregar</button><span id="imsg" class="small"></span></div></div>
      <div class="panel"><h2>Configuração e limites</h2><div class="form"><label class="f">Modo<select data-c="ia_modo"><option value="essencial">Essencial</option><option value="ia_local">IA Local</option></select></label>
        ${[['ia_ram_mb', 'RAM máxima (MB)'], ['ia_threads', 'Threads'], ['ia_contexto', 'Contexto (tokens)'], ['ia_timeout_s', 'Tempo máximo (s)'], ['ia_docs', 'Documentos recuperados'], ['ia_max_tokens', 'Tamanho máximo da resposta (tokens)']].map(([k, l]) => `<label class="f">${l}<input data-c="${k}" type="number" value="${L[k]}" style="width:100px"></label>`).join('')}
        <button class="primary" id="isave">Salvar</button></div><p class="small muted">A IA roda em processo separado, só em 127.0.0.1, sem acesso à internet, a comandos ou a arquivos fora da pasta do modelo; é encerrada junto com o GPI.</p></div>`;
    main.querySelector('[data-c="ia_modo"]').value = L.ia_modo;
    $('#isave').onclick = async () => { const b = {}; main.querySelectorAll('[data-c]').forEach((el) => { b[el.dataset.c] = el.type === 'number' ? +el.value : el.value; }); try { await post('/api/ia/config', b); pageAI(); } catch (e) { alert(e.message); } };
    $('#iload').onclick = async () => { $('#imsg').innerHTML = '<span class="spinner"></span> carregando…'; try { await post('/api/ia/carregar', {}); pageAI(); } catch (e) { $('#imsg').innerHTML = `<span class="neg">${escH(e.message)}</span>`; } };
    $('#iun').onclick = async () => { await post('/api/ia/descarregar', {}); pageAI(); };
  }

  /* --------------------------------------------------------------- CATÁLOGO → análise */
  const origProduct = PAGES['produto-consumo'];
  async function pageProduct(pid) {
    await origProduct(pid);
    const box = document.createElement('div');
    box.className = 'panel';
    let hist = [];
    try { hist = (await api('/api/compliance/analises?product_id=' + encodeURIComponent(pid))).analises; } catch (e) { /* sem análises */ }
    box.innerHTML = `<h2>Conformidade de Importação</h2><p><a class="btn primary" href="#conformidade-analisar/${encodeURIComponent(pid)}">Analisar requisitos de importação</a></p>
      ${hist.length ? `<p class="small">Análises anteriores: ${hist.slice(0, 5).map((a) => `<a href="#conformidade-analise/${a.id}">nº ${a.id} (${dt(a.criado_em)})</a>`).join(' · ')}</p>` : '<p class="small muted">Nenhuma análise regulatória deste produto ainda.</p>'}
      <p class="small muted">A análise é feita por variante: uma versão com Wi-Fi pode ter exigências diferentes de uma sem comunicação sem fio.</p>`;
    main.appendChild(box);
  }

  return { conformidade: pagePanel, 'conformidade-analisar': pageAnalyze, 'conformidade-analise': pageResult, 'conformidade-historico': pageHistory,
    'conformidade-ncm': pageNcm, 'conformidade-certificados': pageCerts, 'conformidade-base': pageBase, 'conformidade-fornecedores': pageSuppliers,
    'conformidade-assistente': pageAssistant, 'conformidade-ia': pageAI, 'produto-consumo': pageProduct };
};
