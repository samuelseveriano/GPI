// Página local de retorno do OAuth da Meta (v0.8.2: mensagens com código de diagnóstico M01–M11).
// Recebe code/state no fragmento (#), remove-os do histórico imediatamente e conclui a troca por POST
// de mesma origem (com o cabeçalho anti-CSRF X-GPI). O código nunca é gravado no navegador.
(function () {
  'use strict';
  var h = window.location.hash.replace(/^#/, '');
  try { history.replaceState(null, '', window.location.pathname); } catch (e) { /* sem histórico */ }
  var q = new URLSearchParams(h);
  var titulo = document.getElementById('titulo'), msg = document.getElementById('msg');
  function show(t, m) { titulo.textContent = t; msg.textContent = m; }
  if (q.get('error')) {
    show('Conexão recusada', 'Meta recusou a autorização: ' + String(q.get('error_description') || q.get('error')).slice(0, 200) + ' (diagnóstico M06)');
    return;
  }
  var code = q.get('code') || '', state = q.get('state') || '';
  if (!code) { show('Conexão não concluída', 'Meta não retornou um código de autorização. (diagnóstico M01)'); return; }
  if (!state) { show('Conexão não concluída', 'Parâmetro de segurança OAuth não recebido. (diagnóstico M03)'); return; }
  fetch('/api/oauth/meta/concluir', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-GPI': '1' },
    body: JSON.stringify({ code: code, state: state }), credentials: 'same-origin', cache: 'no-store'
  }).then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
    .then(function (x) {
      if (x[0]) show('Meta conectada ✔', 'Token conferido na Meta para o app ' + (x[1].app_id || '') + '. Permissões: ' + (x[1].escopos || 'perfil público') + '. O token fica guardado com ' + (x[1].protecao || 'proteção local') + '. Pode fechar esta janela e rodar o Assistente de conexão para validar uma consulta real.');
      else show('Conexão não concluída', (x[1].erro || 'O código foi recebido, mas não foi possível concluir a autenticação. (diagnóstico M08)'));
    })
    .catch(function () { show('Conexão não concluída', 'O navegador não conseguiu concluir a comunicação com o GPI. Verifique se ele está aberto e use Central de Integrações → Meta → Colar código. (diagnóstico M07)'); });
})();
