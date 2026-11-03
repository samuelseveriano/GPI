"""
Cliente HTTP para coleta de fontes públicas (biblioteca padrão — sem dependências).

v0.6.1:
  * Conexões persistentes (keep-alive) reaproveitadas por host e por thread: uma conexão TCP/TLS
    atende várias requisições, em vez de uma conexão nova por chamada.
  * Tempo de conexão e tempo de leitura separados (connect_timeout / timeout) e tempo total por
    operação (total_timeout), incluindo as novas tentativas.
  * Métricas por host: DNS, conexão (TCP+TLS), tempo até a primeira resposta, tempo total, bytes,
    tentativas, espera por limite (429/Retry-After) e conexões reaproveitadas.
  * Concorrência máxima por host (semáforo) além do intervalo mínimo entre requisições.
  * Retry-After em segundos ou data HTTP; erros permanentes (401/403/400/404) nunca são repetidos.
  * Segredos (key, token, secret, code…) são removidos de URLs e mensagens de log e de erro.

  * Retry com backoff exponencial + jitter em 429, 5xx, timeouts e falhas de rede;
    respeita o cabeçalho Retry-After.
  * Rate limiting por host (intervalo mínimo entre requisições).
  * Cache em disco com validade (evita coleta duplicada) e revalidação condicional com
    ETag / Last-Modified (HTTP 304 reaproveita o conteúdo sem novo download).
  * Respostas comprimidas (gzip/deflate) são descomprimidas uma única vez, conforme o
    cabeçalho Content-Encoding ou a assinatura do gzip (0x1f 0x8b) — o urllib não descomprime.
  * Disjuntor (circuit breaker) por host: após falhas transitórias consecutivas o host é
    suspenso até o fim da sincronização, sem insistir.
  * Métricas por host: requisições, cache, bytes, tempo de resposta e erros.
  * Proxy corporativo: usa o configurado em config/gpi.json ("proxy") ou as
    variáveis HTTPS_PROXY do sistema. Nunca tenta contornar o proxy.
  * TLS sempre verificado. Se a cadeia do certificado não for reconhecida (ex.:
    ICP-Brasil), a TI pode indicar um arquivo de CA em "ca_bundle". Nunca desativa
    a verificação.
"""
from __future__ import annotations

import base64
import email.utils
import gzip
import hashlib
import http.client
import io
import json
import logging
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("gpi.http")

SECRET_PARAMS = re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|refresh_token|token|client_secret|secret|code|"
                           r"auth_code|fb_exchange_token|password|senha)=)[^&#\s]*")
SECRET_TEXT = re.compile(r"(?i)(bearer\s+|access[-_]token[\"':=\s]+|refresh[-_]token[\"':=\s]+|client[-_]secret[\"':=\s]+|"
                         r"api[-_]?key[\"':=\s]+)[A-Za-z0-9._\-~+/=|]{6,}")


def redact(text) -> str:
    """Remove segredos de URLs e textos (parâmetros key/token/secret/code e cabeçalhos Bearer)."""
    s = SECRET_PARAMS.sub(r"\1***", str(text))
    return SECRET_TEXT.sub(r"\1***", s)


def retry_after_seconds(value: str | None) -> float | None:
    """Retry-After em segundos ("120") ou data HTTP ("Wed, 21 Oct 2026 07:28:00 GMT")."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return float(v)
    try:
        dt = email.utils.parsedate_to_datetime(v)
        return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


LOOPBACK = {"127.0.0.1", "localhost", "::1"}

USER_AGENT = "GPI-GlobalProductIntelligence/0.6 (uso analitico local; contato: configure 'contact' em config/gpi.json)"


class SourceError(Exception):
    """Falha ao obter dados de uma fonte (rede, HTTP, formato)."""

    def __init__(self, msg: str, kind: str = "erro", retryable: bool = False, status: int | None = None,
                 body: str | None = None):
        super().__init__(redact(msg))
        self.kind = kind            # rede | http | tls | formato | restrita | limite
        self.retryable = retryable
        self.status = status
        self.body = redact(body) if body else None     # corpo do erro (ex.: códigos do Google Ads), sem segredos


@dataclass
class HttpConfig:
    timeout: float = 30.0              # tempo máximo de leitura (sem dados chegando)
    connect_timeout: float = 8.0       # tempo máximo para DNS + TCP + TLS
    total_timeout: float = 150.0       # tempo máximo de uma operação, somando as novas tentativas
    per_host: int = 2                  # requisições simultâneas por host
    # hosts com aceite de conexão comprovadamente lento (medido no CI): tempo de conexão próprio
    connect_timeouts: dict = field(default_factory=lambda: {"api.gdeltproject.org": 25.0, "servicodados.ibge.gov.br": 15.0})
    backoff_429: float = 15.0          # 429 sem Retry-After: espera 15 s, 30 s, 60 s (respeita o limite do servidor)
    limit_wait_budget: float = 90.0    # espera máxima por limite (429) por host em uma sincronização; depois, adia a fonte
    max_attempts: int = 4
    backoff_base: float = 2.0
    backoff_max: float = 60.0
    min_interval: float = 1.0          # segundos entre requisições ao mesmo host
    cache_ttl: float = 6 * 3600
    proxy: str | None = None
    ca_bundle: str | None = None
    contact: str | None = None
    breaker_threshold: int = 3         # falhas transitórias consecutivas que suspendem o host


def decode_body(raw: bytes, encoding: str | None) -> bytes:
    """Descomprime o corpo conforme Content-Encoding. Se o cabeçalho faltar mas o corpo tiver a
    assinatura do gzip (1f 8b), descomprime também (alguns servidores, como o do IBGE, enviam gzip
    sem o cliente pedir). Corpo já descomprimido nunca é descomprimido de novo."""
    enc = (encoding or "").lower().strip()
    try:
        if "gzip" in enc or raw[:2] == b"\x1f\x8b":
            return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        if "deflate" in enc:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)      # deflate "cru" (sem cabeçalho zlib)
    except (OSError, EOFError, zlib.error) as e:
        raise SourceError(f"resposta comprimida corrompida ({e})", "formato") from e
    return raw


def parse_json_body(raw: bytes, ctype: str | None = None):
    text = raw.decode("utf-8-sig", "strict") if raw else ""
    try:
        return json.loads(text)
    except ValueError as e:
        head = text.lstrip()[:200].lower()
        if head.startswith("<!doctype html") or head.startswith("<html") or "text/html" in (ctype or ""):
            raise SourceError("a fonte devolveu uma página HTML em vez de JSON (manutenção, bloqueio ou "
                              "endereço alterado)", "formato") from e
        raise SourceError(f"resposta não é JSON válido ({e})", "formato") from e


class _Transport:
    """Conexões HTTP/HTTPS persistentes por (thread, esquema, host, porta), com proxy (CONNECT para HTTPS),
    tempos de DNS/conexão/primeira resposta medidos e erros convertidos nos tipos do urllib (HTTPError/URLError)
    para preservar o tratamento já existente."""

    def __init__(self, cfg: "HttpConfig"):
        self.cfg = cfg
        self.local = threading.local()
        self.ctx = ssl.create_default_context(cafile=cfg.ca_bundle) if cfg.ca_bundle else ssl.create_default_context()

    def _proxy_for(self, scheme, host):
        if host in LOOPBACK:
            return None
        if self.cfg.proxy:
            return self.cfg.proxy
        envp = urllib.request.getproxies()
        if urllib.request.proxy_bypass(host):
            return None
        return envp.get(scheme) or envp.get("all")

    def _pool(self) -> dict:
        if not hasattr(self.local, "conns"):
            self.local.conns = {}
        return self.local.conns

    def close(self):
        for c in list(self._pool().values()):
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self._pool().clear()

    def _connect(self, scheme, host, port, timing):
        proxy = self._proxy_for(scheme, host)
        ct = (self.cfg.connect_timeouts or {}).get(host, self.cfg.connect_timeout)
        t = time.perf_counter()
        if proxy:
            pu = urllib.parse.urlsplit(proxy if "://" in proxy else "http://" + proxy)
            ph, pp = pu.hostname, pu.port or 8080
            socket.getaddrinfo(ph, pp)
            timing["dns"] = time.perf_counter() - t
            auth = {}
            if pu.username:
                tok = base64.b64encode(f"{urllib.parse.unquote(pu.username)}:{urllib.parse.unquote(pu.password or '')}".encode()).decode()
                auth = {"Proxy-Authorization": f"Basic {tok}"}
            if scheme == "https":
                c = http.client.HTTPSConnection(ph, pp, timeout=ct, context=self.ctx)
                c.set_tunnel(host, port, headers=auth)
            else:
                c = http.client.HTTPConnection(ph, pp, timeout=ct)
                c._gpi_proxy_auth = auth                              # noqa: SLF001 — HTTP simples via proxy
            c._gpi_via_proxy = scheme != "https"                      # noqa: SLF001
        else:
            socket.getaddrinfo(host, port)                          # DNS medido separadamente (fica no cache do SO)
            timing["dns"] = time.perf_counter() - t
            c = (http.client.HTTPSConnection(host, port, timeout=ct, context=self.ctx)
                 if scheme == "https" else http.client.HTTPConnection(host, port, timeout=ct))
            c._gpi_via_proxy = False                                # noqa: SLF001
        t = time.perf_counter()
        try:
            c.connect()
        except OSError as e:
            c.close()
            if "Tunnel connection failed" in str(e):
                raise urllib.error.URLError(str(e)) from e
            if isinstance(e, (TimeoutError, socket.timeout)):
                raise TimeoutError(f"tempo de conexão esgotado ({ct:.0f} s) com {host}") from e
            raise
        timing["conexao"] = time.perf_counter() - t
        return c

    def send(self, method, url, headers, data, read_timeout, timing):
        u = urllib.parse.urlsplit(url)
        scheme, host = u.scheme, u.hostname
        port = u.port or (443 if scheme == "https" else 80)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        key = (scheme, host, port)
        pool = self._pool()
        for attempt in (1, 2):
            c = pool.get(key)
            reused = c is not None
            if c is None:
                c = self._connect(scheme, host, port, timing)
                pool[key] = c
            timing["reaproveitada"] = reused
            target = url if getattr(c, "_gpi_via_proxy", False) else path
            h = dict(headers)
            h.setdefault("Host", u.netloc)
            h.update(getattr(c, "_gpi_proxy_auth", {}) or {})
            try:
                if c.sock:
                    c.sock.settimeout(read_timeout)
                t = time.perf_counter()
                c.request(method, target, body=data, headers=h)
                r = c.getresponse()
                timing["primeira_resposta"] = time.perf_counter() - t
                body = r.read()
                if r.will_close:
                    c.close()
                    pool.pop(key, None)
                return r.status, r.headers, body
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.CannotSendRequest,
                    http.client.ResponseNotReady) as e:
                c.close()
                pool.pop(key, None)
                if reused and attempt == 1:
                    continue                                       # conexão ociosa fechada pelo servidor: reconecta
                raise ConnectionError(str(e)) from e
            except (TimeoutError, socket.timeout) as e:
                c.close()
                pool.pop(key, None)
                raise TimeoutError(f"tempo de leitura esgotado ({read_timeout:.0f} s)") from e
            except Exception:
                c.close()
                pool.pop(key, None)
                raise
        raise ConnectionError("conexão encerrada")


class HttpClient:
    def __init__(self, cache_dir: Path, cfg: HttpConfig | None = None, sleep=time.sleep):
        self.cfg = cfg or HttpConfig()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._sleep = sleep
        self.cancel_event = threading.Event()
        handlers = []
        if self.cfg.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": self.cfg.proxy, "https": self.cfg.proxy}))
        ctx = ssl.create_default_context(cafile=self.cfg.ca_bundle) if self.cfg.ca_bundle else ssl.create_default_context()
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)
        self.ua = USER_AGENT if not self.cfg.contact else USER_AGENT.replace(
            "configure 'contact' em config/gpi.json", self.cfg.contact)
        self.transport = _Transport(self.cfg)
        self._sems: dict[str, threading.BoundedSemaphore] = {}
        self.on_event = None                      # callback de log estruturado (definido pela sincronização)
        self.ctx_local = threading.local()        # fonte/job atual da thread (para métricas e logs)
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0}
        self.host_stats: dict[str, dict] = {}
        self._fails: dict[str, int] = {}          # falhas transitórias consecutivas por host
        self._open: dict[str, str] = {}           # hosts com disjuntor aberto → motivo
        self.source_stats: dict[str, dict] = {}   # por fonte (thread da sincronização): requisições, cache, espera

    def reset_breakers(self):
        with self._lock:
            self._fails.clear()
            self._open.clear()
            for hs in self.host_stats.values():
                hs["espera_limite_s"] = 0.0          # orçamento de espera por limite vale por sincronização

    def _hs(self, host) -> dict:
        with self._lock:
            return self.host_stats.setdefault(host, {"requisicoes": 0, "cache": 0, "revalidadas_304": 0, "bytes": 0,
                                                     "segundos": 0.0, "erros": 0, "retentativas": 0, "dns_s": 0.0,
                                                     "conexao_s": 0.0, "primeira_resposta_s": 0.0, "conexoes_novas": 0,
                                                     "conexoes_reaproveitadas": 0, "espera_limite_s": 0.0})

    def _sem(self, host) -> threading.BoundedSemaphore:
        with self._lock:
            if host not in self._sems:
                self._sems[host] = threading.BoundedSemaphore(max(1, int(self.cfg.per_host)))
            return self._sems[host]

    def _emit(self, **ev):
        """Evento estruturado (sem segredos) para o log da execução e para o painel de sincronização."""
        cur = getattr(self.ctx_local, "cur", None) or {}
        src = cur.get("fonte")
        if src:
            with self._lock:
                st = self.source_stats.setdefault(src, {"requisicoes": 0, "cache": 0, "erros": 0, "retentativas": 0,
                                                        "espera_s": 0.0})
                for k, f in (("requisicoes", "req"), ("cache", "cache"), ("erros", "erro"), ("retentativas", "retry")):
                    if ev.get(f):
                        st[k] += 1
                st["espera_s"] += ev.get("espera", 0.0)
        if self.on_event:
            try:
                self.on_event({**cur, **{k: v for k, v in ev.items() if k not in ("req", "cache", "retry")}})
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ cache
    def _ckey(self, method, url, body):
        return hashlib.sha256(f"{method} {url} {body or ''}".encode()).hexdigest()

    def _cache_get(self, key, ttl):
        f = self.cache_dir / f"{key}.json"
        if ttl and f.exists() and time.time() - f.stat().st_mtime < ttl:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def _cache_stale(self, key):
        """Conteúdo vencido + validadores (ETag/Last-Modified) para revalidação condicional."""
        f, m = self.cache_dir / f"{key}.json", self.cache_dir / f"{key}.meta"
        if not (f.exists() and m.exists()):
            return None, {}
        try:
            return json.loads(f.read_text(encoding="utf-8")), json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, {}

    def _cache_put(self, key, data, validators: dict | None = None):
        try:
            tmp = self.cache_dir / f"{key}.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_dir / f"{key}.json")
            if validators:
                (self.cache_dir / f"{key}.meta").write_text(json.dumps(validators), encoding="utf-8")
        except OSError:
            pass

    def _touch(self, key):
        try:
            (self.cache_dir / f"{key}.json").touch()
        except OSError:
            pass

    # ------------------------------------------------------------------ rate limit
    def _wait_turn(self, host, min_interval):
        with self._lock:
            now = time.monotonic()
            wait = self._last.get(host, 0) + min_interval - now
            self._last[host] = max(now, self._last.get(host, 0) + min_interval)
        if wait > 0:
            self._sleep(wait)

    # ------------------------------------------------------------------ request
    def request_text(self, url: str, headers: dict | None = None, ttl: float | None = None,
                     min_interval: float | None = None, max_bytes: int = 5_000_000, timeout: float | None = None,
                     method: str = "GET", data: bytes | None = None) -> str:
        """Conteúdo textual (RSS/XML, ou POST SOAP com `data`). Cacheado como {"_text": ...}."""
        out = self.request_json(url, method, headers={"Accept": "application/rss+xml, application/xml, text/xml, */*",
                                                      **(headers or {})}, ttl=ttl, min_interval=min_interval,
                                _raw=True, _max_bytes=max_bytes, timeout=timeout, _body=data)
        return out["_text"]

    def request_json(self, url: str, method: str = "GET", body: dict | None = None,
                     headers: dict | None = None, ttl: float | None = None,
                     min_interval: float | None = None, form: dict | None = None,
                     _raw: bool = False, _max_bytes: int = 50_000_000, timeout: float | None = None,
                     _body: bytes | None = None):
        if _body is not None:
            data = _body
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
        else:
            data = json.dumps(body).encode() if body is not None else None
        ttl = self.cfg.cache_ttl if ttl is None else ttl
        if form is not None:
            ttl = 0                                   # chamadas de token nunca são cacheadas
        key = self._ckey(method, url, data)
        cached = self._cache_get(key, ttl)
        if cached is not None:
            self.stats["cache_hits"] += 1
            self._emit(endpoint=redact(url.split("?")[0]), cache=True, status="cache")
            return cached
        host = urllib.parse.urlsplit(url).netloc
        hs = self._hs(host)
        if host in self._open:
            raise SourceError(f"{host} suspenso nesta sincronização após falhas consecutivas "
                              f"({self._open[host]})", "rede", False)
        h = {"User-Agent": self.ua, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"}
        stale, validators = (None, {})
        if ttl and method == "GET":
            stale, validators = self._cache_stale(key)
            if stale is not None:
                if validators.get("etag"):
                    h["If-None-Match"] = validators["etag"]
                if validators.get("last_modified"):
                    h["If-Modified-Since"] = validators["last_modified"]
        if data is not None and _body is None:
            h["Content-Type"] = "application/x-www-form-urlencoded" if form is not None else "application/json"
        h.update(headers or {})
        last_err = None
        t_start = time.monotonic()
        for attempt in range(1, self.cfg.max_attempts + 1):
            if self.cancel_event.is_set():
                raise SourceError("sincronização cancelada", "cancelada")
            self._wait_turn(host, self.cfg.min_interval if min_interval is None else min_interval)
            self.stats["requests"] += 1
            hs["requisicoes"] += 1
            retry_after = None
            t0 = time.perf_counter()
            timing = {}
            try:
                with self._sem(host):
                    status, rh, raw = self.transport.send(method, url, h, data, timeout or self.cfg.timeout, timing)
                hs["dns_s"] += timing.get("dns", 0.0)
                hs["conexao_s"] += timing.get("conexao", 0.0)
                hs["primeira_resposta_s"] += timing.get("primeira_resposta", 0.0)
                hs["conexoes_reaproveitadas" if timing.get("reaproveitada") else "conexoes_novas"] += 1
                if status >= 400 or status == 304:
                    raise urllib.error.HTTPError(url, status, "", rh, io.BytesIO(raw))
                enc, ctype = rh.get("Content-Encoding"), rh.get("Content-Type")
                new_val = {"etag": rh.get("ETag"), "last_modified": rh.get("Last-Modified")}
                hs["segundos"] += time.perf_counter() - t0
                self._emit(endpoint=redact(url.split("?")[0]), metodo=method, status=status, req=True, tentativa=attempt,
                           segundos=round(time.perf_counter() - t0, 3), bytes=len(raw),
                           conexao="reaproveitada" if timing.get("reaproveitada") else "nova")
                hs["bytes"] += len(raw)
                if len(raw) > _max_bytes:
                    raise SourceError("resposta maior que o limite permitido", "formato")
                raw = decode_body(raw, enc)
                if _raw:
                    out = {"_text": raw.decode("utf-8", "replace")}
                else:
                    out = parse_json_body(raw, ctype)
                if ttl:
                    self._cache_put(key, out, {k: v for k, v in new_val.items() if v} or None)
                self._fails[host] = 0
                return out
            except urllib.error.HTTPError as e:
                hs["segundos"] += time.perf_counter() - t0
                status = e.code
                self._emit(endpoint=redact(url.split("?")[0]), metodo=method, status=status, req=True, erro=True,
                           tentativa=attempt, segundos=round(time.perf_counter() - t0, 3))
                if status == 304 and stale is not None:
                    hs["revalidadas_304"] += 1
                    self._touch(key)                       # conteúdo inalterado: renova a validade local
                    self._fails[host] = 0
                    return stale
                try:
                    full = decode_body(e.read(), (e.headers or {}).get("Content-Encoding")).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    full = ""
                detail = full[:300]
                if status in (401, 403):
                    raise SourceError(f"acesso negado (HTTP {status}); a fonte exige credenciais, permissão "
                                      f"ou o acesso foi bloqueado pela rede", "restrita", status=status, body=full[:4000])
                if status == 404:
                    raise SourceError(f"recurso não encontrado (HTTP 404) {detail}", "http", status=404, body=full[:4000])
                if status == 429 or status >= 500:
                    retry_after = retry_after_seconds(e.headers.get("Retry-After") if e.headers else None)
                    last_err = SourceError(f"HTTP {status}: {detail}", "limite" if status == 429 else "http",
                                           True, status, body=full[:4000])
                else:
                    raise SourceError(f"HTTP {status}: {detail}", "http", status=status, body=full[:4000])
            except ssl.SSLError as e:
                raise SourceError(f"certificado TLS não verificado ({e.__class__.__name__}). Peça à TI "
                                  f"a cadeia de certificados e configure 'ca_bundle' em config/gpi.json", "tls")
            except urllib.error.URLError as e:
                if isinstance(e.reason, ssl.SSLError) or "CERTIFICATE" in str(e.reason).upper():
                    raise SourceError(f"certificado TLS não verificado ({e.reason}). Peça à TI a cadeia "
                                      f"de certificados e configure 'ca_bundle' em config/gpi.json", "tls")
                reason = str(e.reason)
                if "Tunnel connection failed" in reason or " 403" in reason or " 407" in reason:
                    # bloqueio do proxy corporativo: não insistir, não contornar
                    raise SourceError(f"a rede/proxy da empresa bloqueou o acesso a {host} ({reason}). "
                                      f"Solicite à TI a liberação do endereço (ver docs/TI.md)", "bloqueada")
                last_err = SourceError(f"falha de rede: {e.reason}", "rede", True)
            except (TimeoutError, ConnectionError, OSError) as e:
                last_err = SourceError(f"falha de rede: {e}", "rede", True)
            hs["erros"] += 1
            if timing.get("primeira_resposta") is None:
                self._emit(endpoint=redact(url.split("?")[0]), metodo=method, status=None, req=True, erro=True,
                           tentativa=attempt, motivo=str(last_err)[:200], segundos=round(time.perf_counter() - t0, 3))
            if attempt < self.cfg.max_attempts:
                base = self.cfg.backoff_429 if (last_err.kind == "limite" and retry_after is None) else self.cfg.backoff_base
                delay = retry_after if retry_after is not None else min(self.cfg.backoff_max, base * 2 ** (attempt - 1))
                delay *= 1 + random.random() * 0.25
                if time.monotonic() - t_start + delay > self.cfg.total_timeout:
                    log.info("tempo total da operação esgotado para %s; sem novas tentativas", host)
                    break
                if last_err.kind == "limite" and hs["espera_limite_s"] + delay > self.cfg.limit_wait_budget:
                    last_err = SourceError(f"{last_err} — limite de requisições do servidor; coleta adiada para a próxima "
                                           f"execução (espera acumulada {hs['espera_limite_s']:.0f} s)", "limite", True, 429,
                                           body=last_err.body)
                    break
                self.stats["retries"] += 1
                hs["retentativas"] += 1
                if last_err.kind == "limite":
                    hs["espera_limite_s"] += delay
                self._emit(endpoint=redact(url.split("?")[0]), retry=True, espera=delay, motivo=str(last_err)[:200])
                log.info("tentativa %d falhou para %s (%s); nova tentativa em %.1fs", attempt, host, last_err, delay)
                self._sleep(delay)
        err = last_err or SourceError("falha desconhecida", "rede", True)
        with self._lock:
            self._fails[host] = self._fails.get(host, 0) + 1
            if self._fails[host] >= self.cfg.breaker_threshold and err.kind in ("rede", "http"):
                self._open[host] = str(err)[:120]
                log.warning("disjuntor aberto para %s após %d falhas consecutivas", host, self._fails[host])
        raise err
