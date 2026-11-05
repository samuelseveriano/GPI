// Página de retorno HTTPS do OAuth da Meta (Login do Facebook) para o GPI local (v0.8.1).
// A Meta exige redirect HTTPS ("Aplicar HTTPS") e domínio cadastrado no app; 127.0.0.1 não é aceito.
// Segurança:
//  * não possui segredos e não faz requisições de rede (CSP: default-src 'none'; só este script);
//  * só navega para http://127.0.0.1:<porta>/oauth/mercadolivre/retorno — host fixo (loopback), porta numérica
//    extraída do state e validada (1024–65535): não é um redirecionador aberto;
//  * code/state são passados no fragmento (#), que não é enviado em requisições HTTP nem aparece em logs;
//  * a query (?code=…) é removida da barra de endereço/histórico imediatamente;
//  * o código sozinho não serve: a troca exige o App Secret, que só existe no GPI, e o state de uso único.
(function () {
  'use strict';
  var STATE_RX = /^(\d{4,5})\.([A-Za-z0-9_-]{32,64})$/;
  var CODE_RX = /^[A-Za-z0-9_\-.~]{8,300}$/;
  var q = new URLSearchParams(window.location.search);
  try { history.replaceState(null, '', window.location.pathname); } catch (e) { /* ignore */ }
  var status = document.getElementById('status');
  function txt(el, t) { el.textContent = t; }

  if (q.get('error') || q.get('error_code')) {
    txt(status, 'A Meta não autorizou a conexão: ' + String(q.get('error_description') || q.get('error_message') || q.get('error_reason') || q.get('error') || q.get('error_code')).slice(0, 200) + ' — volte ao GPI: Central de Integrações → Meta → Assistente de conexão.');
    return;
  }
  var code = q.get('code') || '', state = q.get('state') || '';
  var m = STATE_RX.exec(state);
  var port = m ? parseInt(m[1], 10) : 0;
  if (!CODE_RX.test(code) || !m || port < 1024 || port > 65535) {
    txt(status, 'Retorno inválido ou incompleto. Volte ao GPI e inicie a conexão novamente.');
    return;
  }
  var frag = 'code=' + encodeURIComponent(code) + '&state=' + encodeURIComponent(state);
  var destino = 'http://127.0.0.1:' + port + '/oauth/meta/retorno#' + frag;
  var link = document.getElementById('link');
  link.setAttribute('href', destino);
  document.getElementById('voltar').hidden = false;
  document.getElementById('manual').hidden = false;
  document.getElementById('codigo').value = frag;
  document.getElementById('copiar').addEventListener('click', function () {
    var t = document.getElementById('codigo');
    t.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    if (navigator.clipboard) { navigator.clipboard.writeText(frag).then(function () { txt(document.getElementById('copiado'), 'copiado'); }); }
    else { txt(document.getElementById('copiado'), ok ? 'copiado' : 'selecione e copie (Ctrl+C)'); }
  });
  txt(status, 'Autorização recebida. Voltando ao GPI…');
  // navegação de nível superior (não é requisição em segundo plano); alguns navegadores corporativos pedem
  // confirmação ou bloqueiam o acesso a endereços locais — nesse caso use o botão ou o código manual.
  setTimeout(function () { window.location.replace(destino); }, 600);
})();
