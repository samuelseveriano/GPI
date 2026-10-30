"""
Cliente HTTP para coleta de fontes públicas (biblioteca padrão — sem dependências).

  * Retry com backoff exponencial + jitter em 429, 5xx, timeouts e falhas de rede;
    respeita o cabeçalho Retry-After.
  * Rate limiting por host (intervalo mínimo entre requisições).
  * Cache em disco com validade (evita coleta duplicada).
  * Proxy corporativo: usa o configurado em config/gpi.json ("proxy") ou as
    variáveis HTTPS_PROXY do sistema. Nunca tenta contornar o proxy.
  * TLS sempre verificado. Se a cadeia do certificado não for reconhecida (ex.:
    ICP-Brasil), a TI pode indicar um arquivo de CA em "ca_bundle". Nunca desativa
    a verificação.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("gpi.http")

USER_AGENT = "GPI-GlobalProductIntelligence/0.2 (uso analitico local; contato: configure 'contact' em config/gpi.json)"


class SourceError(Exception):
    """Falha ao obter dados de uma fonte (rede, HTTP, formato)."""

    def __init__(self, msg: str, kind: str = "erro", retryable: bool = False, status: int | None = None):
        super().__init__(msg)
        self.kind = kind            # rede | http | tls | formato | restrita | limite
        self.retryable = retryable
        self.status = status


@dataclass
class HttpConfig:
    timeout: float = 45.0
    max_attempts: int = 4
    backoff_base: float = 2.0
    backoff_max: float = 60.0
    min_interval: float = 1.0          # segundos entre requisições ao mesmo host
    cache_ttl: float = 6 * 3600
    proxy: str | None = None
    ca_bundle: str | None = None
    contact: str | None = None


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
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0}

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

    def _cache_put(self, key, data):
        try:
            tmp = self.cache_dir / f"{key}.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_dir / f"{key}.json")
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
                     min_interval: float | None = None, max_bytes: int = 5_000_000) -> str:
        """GET de conteúdo textual (ex.: RSS/XML). Cacheado como {"_text": ...}."""
        out = self.request_json(url, headers={"Accept": "application/rss+xml, application/xml, text/xml, */*",
                                              **(headers or {})}, ttl=ttl, min_interval=min_interval,
                                _raw=True, _max_bytes=max_bytes)
        return out["_text"]

    def request_json(self, url: str, method: str = "GET", body: dict | None = None,
                     headers: dict | None = None, ttl: float | None = None,
                     min_interval: float | None = None, form: dict | None = None,
                     _raw: bool = False, _max_bytes: int = 50_000_000):
        if form is not None:
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
            return cached
        host = urllib.parse.urlsplit(url).netloc
        h = {"User-Agent": self.ua, "Accept": "application/json"}
        if data is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded" if form is not None else "application/json"
        h.update(headers or {})
        last_err = None
        for attempt in range(1, self.cfg.max_attempts + 1):
            if self.cancel_event.is_set():
                raise SourceError("sincronização cancelada", "cancelada")
            self._wait_turn(host, self.cfg.min_interval if min_interval is None else min_interval)
            req = urllib.request.Request(url, data=data, method=method, headers=h)
            self.stats["requests"] += 1
            retry_after = None
            try:
                with self.opener.open(req, timeout=self.cfg.timeout) as r:
                    raw = r.read(_max_bytes + 1)
                if len(raw) > _max_bytes:
                    raise SourceError("resposta maior que o limite permitido", "formato")
                if _raw:
                    out = {"_text": raw.decode("utf-8", "replace")}
                else:
                    try:
                        out = json.loads(raw.decode("utf-8-sig"))
                    except ValueError as e:
                        raise SourceError(f"resposta não é JSON válido ({e})", "formato") from e
                if ttl:
                    self._cache_put(key, out)
                return out
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    detail = e.read()[:300].decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    detail = ""
                if status in (401, 403):
                    raise SourceError(f"acesso negado (HTTP {status}); a fonte exige credenciais "
                                      f"ou o acesso foi bloqueado pela rede", "restrita", status=status)
                if status == 404:
                    raise SourceError(f"recurso não encontrado (HTTP 404) {detail}", "http", status=404)
                if status == 429 or status >= 500:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    retry_after = float(ra) if ra and ra.isdigit() else None
                    last_err = SourceError(f"HTTP {status}: {detail}", "limite" if status == 429 else "http",
                                           True, status)
                else:
                    raise SourceError(f"HTTP {status}: {detail}", "http", status=status)
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
            if attempt < self.cfg.max_attempts:
                self.stats["retries"] += 1
                delay = retry_after or min(self.cfg.backoff_max, self.cfg.backoff_base * 2 ** (attempt - 1))
                delay *= 1 + random.random() * 0.25
                log.info("tentativa %d falhou para %s (%s); nova tentativa em %.1fs", attempt, host, last_err, delay)
                self._sleep(delay)
        raise last_err or SourceError("falha desconhecida", "rede", True)
