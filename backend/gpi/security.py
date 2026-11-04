"""Proteções transversais do GPI (v0.7).

* ``RedactFilter``: filtro de logging aplicado a todos os handlers; remove tokens, segredos, códigos OAuth e
  verificadores PKCE de qualquer mensagem antes de gravar (sanitização automática).
* ``public_url_problem``: proteção contra SSRF para URLs informadas pelo usuário (feeds RSS etc.): só http/https,
  sem credenciais na URL, sem endereços de loopback, rede privada, link-local, multicast ou metadados de nuvem.
  A resolução DNS é verificada no momento da coleta (reduz DNS rebinding).
* ``BodyLimit``: middleware ASGI que limita o tamanho do corpo das requisições (413 acima do limite), inclusive
  para corpo sem Content-Length (chunked).
* ``safe_cell``: neutraliza injeção de fórmulas em CSV/XLSX (=, +, -, @, tab, CR no início da célula).
* ``CSP``: política de segurança de conteúdo do front-end (somente scripts do próprio GPI, sem inline/eval).
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlsplit

from .connectors.http import redact

EXTRA_SECRET = re.compile(
    r"(?i)(code_verifier[\"':=\s]+|code[\"':=\s]+(?=[A-Za-z0-9._\-~]{20,})|\"?authorization\"?\s*[:=]\s*\"?)"
    r"[A-Za-z0-9._\-~+/=| ]{6,}")
TOKEN_SHAPES = re.compile(
    r"AIza[0-9A-Za-z_\-]{35}|GOCSPX-[0-9A-Za-z_\-]{10,}|1//0[0-9A-Za-z_\-]{30,}|\bEAA[A-Za-z0-9]{40,}"
    r"|\b(?:APP_USR|TG)-[0-9A-Za-z\-]{20,}|\b(?:ghp|gho|ghs)_[0-9A-Za-z]{30,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")


def scrub(text) -> str:
    s = redact(str(text))
    s = EXTRA_SECRET.sub(lambda m: m.group(1) + "***", s)
    return TOKEN_SHAPES.sub("***", s)


class RedactFilter(logging.Filter):
    """Aplica ``scrub`` à mensagem final (inclusive argumentos e traceback) de cada registro."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        record.msg = scrub(msg)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            # o texto da exceção pode conter a URL completa; o traceback é formatado depois, então
            # substituímos pelo texto já sanitizado e descartamos o objeto original
            import traceback
            record.exc_text = scrub("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return True


BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
    "::1/128", "::/128", "fc00::/7", "fe80::/10", "ff00::/8", "::ffff:0:0/96")]


def _ip_blocked(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return any(a in n for n in BLOCKED_NETS if n.version == a.version)


def public_url_problem(url: str, resolve: bool = True, resolver=socket.getaddrinfo) -> str | None:
    """Devolve None se a URL for aceitável para busca externa, senão o motivo da recusa."""
    try:
        p = urlsplit(url)
    except ValueError:
        return "URL inválida"
    if p.scheme not in ("http", "https"):
        return "apenas http/https"
    if not p.hostname:
        return "URL sem servidor"
    if p.username or p.password:
        return "credenciais embutidas na URL não são permitidas"
    host = p.hostname.strip("[]").lower()
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
        return "endereço local não permitido"
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        return "endereço interno/reservado não permitido" if _ip_blocked(host) else None
    if not resolve:
        return None
    try:
        infos = resolver(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError:
        return None          # sem DNS local (ex.: proxy corporativo resolve) — o proxy aplica a política dele
    for info in infos:
        if _ip_blocked(info[4][0]):
            return "o nome aponta para endereço interno/reservado"
    return None


class BodyLimit:
    """Middleware ASGI: recusa corpos maiores que ``default`` bytes (ou o limite específico do caminho)."""

    def __init__(self, app, default: int = 2 * 1024 * 1024, per_path: dict[str, int] | None = None):
        self.app = app
        self.default = default
        self.per_path = per_path or {}

    def limit_for(self, path: str) -> int:
        for prefix, lim in self.per_path.items():
            if path.startswith(prefix):
                return lim
        return self.default

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope.get("path", ""))
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > limit:
                        return await _too_large(send, limit)
                except ValueError:
                    return await _too_large(send, limit)
        total = 0
        started = False

        async def guarded_receive():
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > limit:
                    raise _TooLarge()
            return msg

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, guarded_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _too_large(send, limit)


class _TooLarge(Exception):
    pass


async def _too_large(send, limit):
    body = ('{"erro":"conteúdo maior que o limite permitido (%d MB)"}' % max(1, limit // 1_048_576)).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    """Prefixa com apóstrofo textos que planilhas interpretariam como fórmula (CSV/Excel injection)."""
    if isinstance(v, str) and v.startswith(FORMULA_START):
        try:
            float(v.replace(",", "."))
            return v                 # número negativo/positivo legítimo
        except ValueError:
            return "'" + v
    return v


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
       "form-action 'self'")
