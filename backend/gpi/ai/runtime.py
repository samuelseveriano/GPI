"""IA local (Camada 3): llama.cpp (llama-server) + modelo GGUF, executados pelo próprio GPI em processo controlado.

Regras de segurança (seção 19):
* Nada é baixado nem executado automaticamente: o pacote de IA (GPI-Local-AI-Model-Pack) é copiado pelo usuário/TI
  para a pasta ``ia`` ao lado do GPI.exe ou para a pasta de dados; o manifesto ``gpi-model-pack.json`` traz licença,
  procedência e SHA-256 de cada arquivo, conferidos antes da primeira execução.
* O servidor do modelo escuta só em 127.0.0.1, porta aleatória, com chave aleatória por sessão; não recebe
  ferramentas, comandos do sistema, credenciais nem acesso a arquivos (só o modelo indicado).
* Limites configuráveis: RAM (Job Object do Windows / RLIMIT_AS), threads, contexto, tempo máximo e documentos.
* Carregamento sob demanda (não sobe com o GPI), geração cancelável e encerramento junto com o GPI (o Job Object
  com KILL_ON_JOB_CLOSE garante o encerramento mesmo se o GPI for finalizado à força).
* Se o pacote não existir, estiver adulterado ou a política corporativa bloquear a execução, o GPI segue no
  Modo Essencial (regras + documentos), com mensagem clara.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("gpi.ia")
MANIFEST = "gpi-model-pack.json"
SERVER_NAMES = ("llama-server.exe", "llama-server")

DEFAULTS = {"ia_modo": "essencial", "ia_ram_mb": 2048, "ia_threads": 0, "ia_contexto": 4096, "ia_timeout_s": 90,
            "ia_docs": 5, "ia_max_tokens": 600, "ia_temperatura": 0.2}


def limits(cfg: dict) -> dict:
    out = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    cpu = os.cpu_count() or 2
    out["ia_threads"] = int(out["ia_threads"]) or max(1, min(8, cpu // 2))
    out["ia_ram_mb"] = max(512, min(16384, int(out["ia_ram_mb"])))
    out["ia_contexto"] = max(1024, min(32768, int(out["ia_contexto"])))
    out["ia_timeout_s"] = max(10, min(600, int(out["ia_timeout_s"])))
    out["ia_docs"] = max(1, min(12, int(out["ia_docs"])))
    out["ia_max_tokens"] = max(64, min(2048, int(out["ia_max_tokens"])))
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_pack(dirs: list[Path]) -> Path | None:
    for d in dirs:
        if d and (d / MANIFEST).is_file():
            return d
    return None


def verify_pack(folder: Path, cache: dict | None = None) -> dict:
    """Confere manifesto, presença, tamanho e SHA-256 de cada arquivo. Não executa nada."""
    try:
        man = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "erro": f"manifesto ilegível: {e}"}
    if man.get("formato") != "gpi-model-pack":
        return {"ok": False, "erro": "manifesto em formato desconhecido"}
    files, problems = [], []
    for f in man.get("arquivos", []):
        nome = Path(str(f.get("nome", ""))).name             # sem subpastas nem ../
        p = folder / nome
        item = {"nome": nome, "papel": f.get("papel"), "licenca": f.get("licenca"), "origem": f.get("origem"),
                "sha256_esperado": f.get("sha256"), "tamanho": f.get("tamanho")}
        if not p.is_file():
            problems.append(f"{nome}: ausente")
            item["ok"] = False
        else:
            st = p.stat()
            ck = f"{p}:{st.st_size}:{int(st.st_mtime)}"
            got = (cache or {}).get(ck) or sha256_file(p)
            if cache is not None:
                cache[ck] = got
            item.update(sha256=got, ok=(got == str(f.get("sha256", "")).lower()), tamanho_real=st.st_size)
            if not item["ok"]:
                problems.append(f"{nome}: SHA-256 diferente do manifesto (arquivo alterado ou corrompido)")
        files.append(item)
    roles = {f["papel"] for f in files if f.get("ok")}
    if "servidor" not in roles:
        problems.append("executável do llama.cpp (papel 'servidor') ausente ou inválido")
    if "modelo" not in roles:
        problems.append("modelo GGUF (papel 'modelo') ausente ou inválido")
    lic_missing = [f["nome"] for f in files if not f.get("licenca")]
    if lic_missing:
        problems.append("arquivos sem licença declarada: " + ", ".join(lic_missing))
    return {"ok": not problems, "problemas": problems, "arquivos": files, "manifesto": {k: v for k, v in man.items() if k != "arquivos"},
            "pasta": str(folder)}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _WinJob:
    """Job Object do Windows: limite de memória por processo + encerra o filho quando o GPI fecha."""

    def __init__(self, mem_bytes: int):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.k32 = k32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        self.h = k32.CreateJobObjectW(None, None)
        info = EXT()
        info.Basic.LimitFlags = 0x2000 | 0x100      # KILL_ON_JOB_CLOSE | PROCESS_MEMORY
        info.ProcessMemoryLimit = mem_bytes
        if not k32.SetInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject falhou")

    def assign(self, proc: subprocess.Popen):
        if not self.k32.AssignProcessToJobObject(self.h, int(proc._handle)):  # noqa: SLF001
            raise OSError("AssignProcessToJobObject falhou")

    def close(self):
        try:
            self.k32.CloseHandle(self.h)
        except Exception:  # noqa: BLE001
            pass


class LocalLLM:
    def __init__(self, cfg: dict, dirs: list[Path]):
        self.cfg = cfg
        self.dirs = dirs
        self.proc: subprocess.Popen | None = None
        self.job = None
        self.port = None
        self.key = None
        self.lock = threading.Lock()
        self.cancel_flags: dict[str, threading.Event] = {}
        self._hash_cache: dict = {}
        self.last_error: str | None = None
        self.load_seconds: float | None = None
        self.model_name: str | None = None

    # ------------------------------------------------------------------ estado
    def status(self, verify: bool = False) -> dict:
        lim = limits(self.cfg)
        folder = find_pack(self.dirs)
        st = {"modo_configurado": lim["ia_modo"], "limites": lim, "pacote_encontrado": bool(folder),
              "pastas_procuradas": [str(d) for d in self.dirs], "carregado": self.running(), "modelo": self.model_name,
              "tempo_carga_s": self.load_seconds, "ultimo_erro": self.last_error}
        if folder and verify:
            st["verificacao"] = verify_pack(folder, self._hash_cache)
        st["modo_efetivo"] = "ia_local" if (lim["ia_modo"] == "ia_local" and folder) else "essencial"
        return st

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # ------------------------------------------------------------------ ciclo de vida
    def ensure_started(self) -> None:
        with self.lock:
            if self.running():
                return
            lim = limits(self.cfg)
            folder = find_pack(self.dirs)
            if not folder:
                raise RuntimeError("pacote de IA local não encontrado (copie o GPI-Local-AI-Model-Pack para a pasta 'ia')")
            v = verify_pack(folder, self._hash_cache)
            if not v["ok"]:
                raise RuntimeError("pacote de IA local inválido: " + "; ".join(v["problemas"]))
            server = next(folder / f["nome"] for f in v["arquivos"] if f["papel"] == "servidor")
            model = next(folder / f["nome"] for f in v["arquivos"] if f["papel"] == "modelo")
            self.port, self.key = _free_port(), secrets.token_urlsafe(24)
            args = [str(server), "-m", str(model), "--host", "127.0.0.1", "--port", str(self.port),
                    "--api-key", self.key, "-c", str(lim["ia_contexto"]), "-t", str(lim["ia_threads"]),
                    "--parallel", "1"]
            extra = v["manifesto"].get("argumentos_extras") or []
            args += [a for a in extra if isinstance(a, str) and a.startswith("--") and a in
                     ("--no-webui", "--no-mmap", "--mlock", "--jinja", "--no-warmup")]
            env = {k: v2 for k, v2 in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")}
            env["LLAMA_ARG_HF_REPO"] = ""                      # nunca baixar modelos
            import tempfile
            self._errf = tempfile.TemporaryFile()               # diagnóstico de falha na inicialização (sem segredos)
            kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": self._errf,
                  "cwd": str(folder), "env": env}
            t0 = time.perf_counter()
            if sys.platform == "win32":
                kw["creationflags"] = 0x08000000 | 0x00000200        # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
                try:
                    self.proc = subprocess.Popen(args, **kw)     # noqa: S603 — binário conferido por SHA-256
                except OSError as e:
                    raise RuntimeError(f"a execução do llama-server foi bloqueada ou falhou ({e}). Se a política "
                                       "corporativa impede executáveis, use o Modo Essencial.") from None
                try:
                    self.job = _WinJob(lim["ia_ram_mb"] * 1024 * 1024)
                    self.job.assign(self.proc)
                except OSError as e:
                    log.warning("limite de memória (Job Object) não aplicado: %s", e)
            else:
                mem = lim["ia_ram_mb"] * 1024 * 1024

                def _limit():  # pragma: no cover — roda no processo filho
                    import resource
                    resource.setrlimit(resource.RLIMIT_AS, (mem * 4, mem * 4))   # memória virtual > residente
                kw["preexec_fn"] = _limit
                kw["start_new_session"] = True
                self.proc = subprocess.Popen(args, **kw)         # noqa: S603
            self.model_name = model.name
            deadline = time.time() + max(60, lim["ia_timeout_s"])
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    tail = ""
                    try:
                        self._errf.seek(0)
                        tail = self._errf.read()[-1200:].decode("utf-8", "replace").replace(self.key, "***")
                    except OSError:
                        pass
                    self.last_error = (f"o servidor do modelo encerrou ao iniciar (código {self.proc.returncode}) — RAM "
                                       f"insuficiente ou binário incompatível. Saída: {tail.strip()[-600:]}")
                    self.proc = None
                    raise RuntimeError(self.last_error)
                try:
                    st, body = self._req("GET", "/health", None, 3)
                    if st == 200 and b"ok" in body:
                        self.load_seconds = round(time.perf_counter() - t0, 2)
                        self.last_error = None
                        log.info("IA local carregada em %.1f s (%s)", self.load_seconds, self.model_name)
                        return
                except OSError:
                    pass
                time.sleep(0.3)
            self.stop()
            self.last_error = "tempo esgotado ao carregar o modelo"
            raise RuntimeError(self.last_error)

    def stop(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        if self.job:
            self.job.close()
            self.job = None
        f, self._errf = getattr(self, "_errf", None), None
        if f:
            try:
                f.close()
            except OSError:
                pass

    # ------------------------------------------------------------------ geração
    def _req(self, method, path, body, timeout):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            c.request(method, path, body=json.dumps(body) if body is not None else None,
                      headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def cancel(self, req_id: str) -> bool:
        ev = self.cancel_flags.get(req_id)
        if ev:
            ev.set()
            return True
        return False

    def generate(self, messages: list[dict], req_id: str) -> dict:
        """Geração em streaming; cancelável (fecha a conexão) e limitada por tempo e tokens."""
        lim = limits(self.cfg)
        self.ensure_started()
        ev = self.cancel_flags.setdefault(req_id, threading.Event())
        body = {"messages": messages, "stream": True, "temperature": lim["ia_temperatura"], "max_tokens": lim["ia_max_tokens"],
                "cache_prompt": False}
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=lim["ia_timeout_s"])
        t0 = time.perf_counter()
        first = None
        parts = []
        status = "concluida"
        try:
            c.request("POST", "/v1/chat/completions", body=json.dumps(body),
                      headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            r = c.getresponse()
            if r.status != 200:
                raise RuntimeError(f"o servidor do modelo respondeu HTTP {r.status}")
            while True:
                if ev.is_set():
                    status = "cancelada"
                    break
                if time.perf_counter() - t0 > lim["ia_timeout_s"]:
                    status = "tempo_esgotado"
                    break
                line = r.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if delta and first is None:
                    first = time.perf_counter() - t0
                parts.append(delta)
        finally:
            c.close()                                    # fechar a conexão interrompe a geração no servidor
            self.cancel_flags.pop(req_id, None)
        return {"texto": "".join(parts), "status": status, "segundos": round(time.perf_counter() - t0, 2),
                "primeiro_token_s": round(first, 2) if first is not None else None, "modelo": self.model_name}
