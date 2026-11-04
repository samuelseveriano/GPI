"""
OAuth 2.0 Authorization Code com PKCE (RFC 7636, método S256).

O navegador do usuário é enviado à página oficial do provedor; o GPI nunca vê a senha.
O retorno chega em http://127.0.0.1:<porta>/oauth/callback, o `state` é conferido
(proteção contra CSRF) e o código é trocado pelo token junto com o code_verifier.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import urllib.parse


def make_verifier() -> str:
    # 43–128 caracteres do conjunto [A-Z a-z 0-9 - . _ ~]
    return secrets.token_urlsafe(64)[:96]


def challenge_s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


class PendingFlows:
    """Fluxos em andamento (memória, expiram em 10 min, uso único)."""

    def __init__(self, ttl: float = 600):
        self.ttl = ttl
        self._d: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, provider: str, extra: dict | None = None) -> tuple[str, str]:
        state, verifier = secrets.token_urlsafe(32), make_verifier()      # 256 bits
        with self._lock:
            now = time.time()
            self._d = {k: v for k, v in self._d.items() if v["exp"] > now}
            self._d[state] = {"provider": provider, "verifier": verifier, "exp": now + self.ttl, **(extra or {})}
        return state, verifier

    def rekey(self, old: str, new: str):
        """Troca a chave de um fluxo (ex.: state público com a porta local acrescentada)."""
        with self._lock:
            if old in self._d:
                self._d[new] = self._d.pop(old)

    def consume(self, state: str) -> dict | None:
        with self._lock:
            f = self._d.pop(state, None)
        if not f or f["exp"] < time.time():
            return None
        return f


def authorize_url(base: str, client_id: str, redirect_uri: str, state: str, verifier: str, scope: str | None = None) -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state,
         "code_challenge": challenge_s256(verifier), "code_challenge_method": "S256"}
    if scope:
        q["scope"] = scope
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(q)
