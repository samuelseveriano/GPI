// Página local de retorno do OAuth da Meta (v0.8.1).
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
    show('Conexão recusada', 'A Meta informou: ' + String(q.get('error_description') || q.get('error')).slice(0, 200));
    return;
  }
  var code = q.get('code') || '', state = q.get('state') || '';
  if (!code || !state) { show('Conexão não concluída', 'Código de autorização ausente. Inicie a conexão novamente no GPI.'); return; }
  fetch('/api/oauth/meta/concluir', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-GPI': '1' },
    body: JSON.stringify({ code: code, state: state }), credentials: 'same-origin', cache: 'no-store'
  }).then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
    .then(function (x) {
      if (x[0]) show('Meta conectada ✔', 'Permissões: ' + (x[1].escopos || 'perfil público') + '. O token fica guardado com ' + (x[1].protecao || 'proteção local') + '. Pode fechar esta janela.');
      else show('Conexão não concluída', x[1].erro || 'Falha desconhecida.');
    })
    .catch(function () { show('Conexão não concluída', 'O GPI não respondeu. Verifique se ele está aberto e tente novamente.'); });
})();
