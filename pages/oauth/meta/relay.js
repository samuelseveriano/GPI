// Página de retorno HTTPS do OAuth da Meta (Login do Facebook) para o GPI local (v0.8.2).
// A Meta exige redirect HTTPS ("Aplicar HTTPS") e domínio cadastrado no app; 127.0.0.1 não é aceito.
//
// v0.8.2 — causa do "Retorno inválido ou incompleto": esta página aceitava códigos de no máximo 300 caracteres,
// enquanto o GPI aceita até 1.024. A Meta não documenta o tamanho do código ("an encrypted string unique to each
// login request") e códigos reais do Login do Facebook passam de 300 caracteres. Agora a regra é a MESMA do GPI
// (conjunto de caracteres seguro para URL, 8–2.048) e cada recusa mostra um código de diagnóstico (M01–M06),
// com o TAMANHO do código recebido — nunca o valor.
//
// Segurança:
//  * não possui segredos e não faz requisições de rede (CSP: default-src 'none'; só este script);
//  * só navega para http://127.0.0.1:<porta>/oauth/meta/retorno — host fixo (loopback), porta numérica
//    extraída do state e validada (1024–65535): não é um redirecionador aberto;
//  * code/state seguem no fragmento (#), que não é enviado em requisições HTTP;
//  * a query (?code=…) é removida da barra de endereço/histórico imediatamente;
//  * a validação aqui é só de formato: quem decide é o GPI (state de uso único, expiração, troca com o App Secret).
(function () {
  'use strict';
  var STATE_RX = /^(\d{4,5})\.([A-Za-z0-9_-]{32,64})$/;
  var CODE_CHARS = /^[A-Za-z0-9_\-.~]+$/;
  var CODE_MIN = 8, CODE_MAX = 2048;           // igual a backend/gpi/integrations/meta.py (CODE_RX)
  var q = new URLSearchParams(window.location.search);
  try { history.replaceState(null, '', window.location.pathname); } catch (e) { /* ignore */ }
  var status = document.getElementById('status');
  function txt(el, t) { el.textContent = t; }
  function fail(diag, msg, detail) {
    txt(status, msg + ' ' + (detail ? detail + ' ' : '') + 'Volte ao GPI: Central de Integrações → Meta → Assistente de conexão. ' +
        '(diagnóstico ' + diag + ')');
    var d = document.getElementById('diag');
    if (d) { txt(d, diag); }
  }

  if (q.get('error') || q.get('error_code') || q.get('error_reason')) {
    var why = String(q.get('error_description') || q.get('error_message') || q.get('error_reason') || q.get('error') ||
                     q.get('error_code')).replace(/\+/g, ' ').slice(0, 200);
    fail('M06', 'Meta recusou a autorização.', 'Motivo informado pela Meta: ' + why + '.');
    return;
  }
  var code = q.get('code'), state = q.get('state');
  if (!code) { fail('M01', 'Meta não retornou um código de autorização.'); return; }
  if (code.length < CODE_MIN || code.length > CODE_MAX || !CODE_CHARS.test(code)) {
    fail('M02', 'O código recebido não corresponde ao formato esperado.',
         '(' + code.length + ' caracteres' + (CODE_CHARS.test(code) ? '' : ', com caracteres fora do padrão de URL') + ')');
    return;
  }
  if (!state) { fail('M03', 'Parâmetro de segurança OAuth não recebido.'); return; }
  var m = STATE_RX.exec(state);
  var port = m ? parseInt(m[1], 10) : 0;
  if (!m || port < 1024 || port > 65535) { fail('M04', 'A solicitação de autorização não corresponde à sessão iniciada.'); return; }

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
  txt(status, 'Autorização recebida (código com ' + code.length + ' caracteres). Voltando ao GPI…');
  // navegação de nível superior (não é requisição em segundo plano); alguns navegadores corporativos pedem
  // confirmação ou bloqueiam o acesso a endereços locais — nesse caso use o botão ou o código manual (M07 no GPI).
  setTimeout(function () { window.location.replace(destino); }, 600);
})();
