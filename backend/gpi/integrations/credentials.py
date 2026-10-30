"""
Cofre local de credenciais (chaves de API e tokens OAuth). Nunca guarda senhas de marketplaces.

* Windows: criptografia DPAPI do próprio Windows (CryptProtectData, escopo do usuário):
  só a mesma conta do Windows, na mesma máquina, consegue ler o arquivo.
* Outros sistemas: arquivo com permissão 0600 (somente o usuário). Não é criptografado —
  a interface informa isso.
Os valores secretos nunca são registrados em log nem devolvidos à interface (só mascarados).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class _DPAPI:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        self.ctypes, self.BLOB = ctypes, BLOB
        self.crypt32 = ctypes.windll.crypt32
        self.kernel32 = ctypes.windll.kernel32

    def _call(self, fn, data: bytes, protect: bool) -> bytes:
        c = self.ctypes
        buf = c.create_string_buffer(data, len(data))
        inp = self.BLOB(len(data), c.cast(buf, c.POINTER(c.c_char)))
        out = self.BLOB()
        flags = 0x1                                   # CRYPTPROTECT_UI_FORBIDDEN
        ok = (fn(c.byref(inp), "GPI", None, None, None, flags, c.byref(out)) if protect
              else fn(c.byref(inp), None, None, None, None, flags, c.byref(out)))
        if not ok:
            raise OSError("falha na DPAPI do Windows")
        try:
            return c.string_at(out.pbData, out.cbData)
        finally:
            self.kernel32.LocalFree(out.pbData)

    def protect(self, b: bytes) -> bytes:
        return self._call(self.crypt32.CryptProtectData, b, True)

    def unprotect(self, b: bytes) -> bytes:
        return self._call(self.crypt32.CryptUnprotectData, b, False)


class CredentialStore:
    def __init__(self, data_dir: Path, force_plain: bool = False):
        self.path = Path(data_dir) / "credentials.bin"
        self._lock = threading.Lock()
        self.dpapi = None
        if os.name == "nt" and not force_plain:
            try:
                self.dpapi = _DPAPI()
            except Exception:  # noqa: BLE001
                self.dpapi = None
        self.protection = ("criptografado com DPAPI do Windows (somente seu usuário nesta máquina)"
                           if self.dpapi else "arquivo restrito ao usuário (permissão 0600), sem criptografia")

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        raw = self.path.read_bytes()
        if self.dpapi:
            raw = self.dpapi.unprotect(raw)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def _save(self, d: dict):
        raw = json.dumps(d).encode("utf-8")
        if self.dpapi:
            raw = self.dpapi.protect(raw)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get(self, provider: str) -> dict:
        with self._lock:
            return dict(self._load().get(provider, {}))

    def set(self, provider: str, values: dict):
        with self._lock:
            d = self._load()
            cur = d.get(provider, {})
            cur.update({k: v for k, v in values.items() if v not in (None, "")})
            d[provider] = cur
            self._save(d)

    def delete(self, provider: str):
        with self._lock:
            d = self._load()
            d.pop(provider, None)
            self._save(d)

    def masked(self, provider: str) -> dict:
        out = {}
        for k, v in self.get(provider).items():
            s = str(v)
            out[k] = (s[:3] + "…" + s[-3:]) if len(s) > 10 else "•••"
        return out
