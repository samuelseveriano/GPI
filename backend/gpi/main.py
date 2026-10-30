"""
Inicializador do GPI (também é o ponto de entrada do GPI.exe).

  GPI.exe / python -m gpi.main     inicia, abre o navegador e mostra a janela de controle
  --stop        encerra com segurança uma instância em execução
  --check       diagnóstico (arquivos, dependências, porta, pasta de dados) e sai
  --smoke       teste de inicialização: sobe o servidor, confere /api/health e encerra (CI)
  --no-browser  não abre o navegador
  --console     sem janela de controle (encerrar com Ctrl+C)

Sequência ao abrir: integridade dos arquivos → pasta de dados gravável → instância já
aberta? → porta livre → servidor em 127.0.0.1 → navegador → sincronização em segundo plano.

Não requer administrador, não altera registro nem políticas e só escuta em 127.0.0.1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__

HOST = "127.0.0.1"
APP_ID = "gpi-global-product-intelligence"
DEFAULTS = {"port": 8765, "port_range": 10, "open_browser": True, "data_dir": None, "telemetry": False,
            "log_level": "INFO", "auto_sync": True, "history_start_year": 2016, "proxy": None,
            "ca_bundle": None, "contact": None, "mercadolivre_access_token": None, "automl_budget_s": 420,
            "youtube_daily_units": 3000}


# ---------------------------------------------------------------------- caminhos
def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Pasta dos arquivos do programa (somente leitura em uso normal)."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Onde estão frontend/, config/ e docs/ (no PyInstaller: pasta _internal)."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return app_dir()


def data_dir(cfg: dict) -> Path:
    """Dados persistentes SEPARADOS dos executáveis.
    Ordem: variável GPI_DATA_DIR → 'data_dir' da configuração → arquivo portable.flag ao lado do
    executável (modo pen-drive) → %LOCALAPPDATA%\\GPI no Windows (ou ~/.local/share/GPI) quando
    empacotado → pasta data/ do projeto em modo desenvolvimento."""
    if os.environ.get("GPI_DATA_DIR"):
        return Path(os.environ["GPI_DATA_DIR"])
    if cfg.get("data_dir"):
        p = Path(cfg["data_dir"])
        return p if p.is_absolute() else app_dir() / p
    if (app_dir() / "portable.flag").exists():
        return app_dir() / "dados"
    if frozen():
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")
        return Path(base) / "GPI"
    return app_dir() / "data"


def load_config(user_data: Path | None = None) -> dict:
    """Padrões → config/gpi.json do pacote → config.json do usuário (gravado pela Central de Integrações)."""
    cfg = dict(DEFAULTS)
    f = resource_dir() / "config" / "gpi.json"
    if f.exists():
        cfg.update(json.loads(f.read_text(encoding="utf-8-sig")))
    if user_data is not None:
        uf = user_data / "config.json"
        if uf.exists():
            try:
                cfg.update(json.loads(uf.read_text(encoding="utf-8-sig")))
            except ValueError:
                logging.getLogger("gpi").warning("config.json do usuário inválido; usando padrões")
    return cfg


# ---------------------------------------------------------------------- integridade
def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path) -> dict:
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in ("manifest.json", "portable.flag") and "dados" not in p.relative_to(root).parts:
            files[p.relative_to(root).as_posix()] = {"sha256": file_hash(p), "size": p.stat().st_size}
    return {"app": APP_ID, "version": __version__, "files": files}


def verify_integrity(root: Path, state_file: Path | None = None) -> tuple[bool, list[str]]:
    """Compara os arquivos com manifest.json (gerado no build). Para não atrasar toda abertura,
    só recalcula o hash quando o tamanho ou a data de modificação mudaram desde a última
    verificação bem-sucedida."""
    mf = root / "manifest.json"
    if not mf.exists():
        return True, ["sem manifest.json (modo desenvolvimento)"]
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    known = {}
    if state_file and state_file.exists():
        try:
            known = json.loads(state_file.read_text(encoding="utf-8"))
        except ValueError:
            known = {}
    problems, seen = [], {}
    for rel, meta in manifest["files"].items():
        p = root / rel
        if not p.exists():
            problems.append(f"ausente: {rel}")
            continue
        st = p.stat()
        sig = f"{st.st_size}:{int(st.st_mtime)}"
        if st.st_size != meta["size"]:
            problems.append(f"tamanho diferente: {rel}")
            continue
        if known.get(rel) == sig:
            seen[rel] = sig
            continue
        if file_hash(p) != meta["sha256"]:
            problems.append(f"conteúdo alterado: {rel}")
            continue
        seen[rel] = sig
    if not problems and state_file:
        try:
            state_file.write_text(json.dumps(seen), encoding="utf-8")
        except OSError:
            pass
    return not problems, problems


# ---------------------------------------------------------------------- utilidades
def setup_logging(data: Path, level: str):
    (data / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(data / "logs" / "gpi.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    handlers = [fh]
    if sys.stderr is not None:                 # exe sem console não tem stderr
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        handlers.append(sh)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":   # ignora conexões em TIME_WAIT (no Windows SO_REUSEADDR teria outro sentido)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def gpi_running(port: int) -> bool:
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f"http://{HOST}:{port}/api/health", timeout=1.5) as r:
            d = json.loads(r.read())
            return d.get("ok") is True and d.get("app", APP_ID) == APP_ID
    except Exception:
        return False


def writable(p: Path) -> tuple[bool, str]:
    try:
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".write_test"
        t.write_text("ok")
        t.unlink()
        return True, str(p)
    except OSError as e:
        return False, f"{p}: {e}"


def diagnose(cfg: dict, data: Path) -> list[tuple[str, bool, str]]:
    out = [("GPI", True, __version__), ("Python", sys.version_info >= (3, 10), sys.version.split()[0]),
           ("Modo", True, "executável empacotado" if frozen() else "desenvolvimento")]
    ok, probs = verify_integrity(app_dir())
    out.append(("Integridade dos arquivos", ok, "; ".join(probs[:3])))
    for mod in ("numpy", "pandas", "scipy", "openpyxl", "sklearn", "starlette", "uvicorn"):
        try:
            m = __import__(mod)
            out.append((mod, True, getattr(m, "__version__", "ok")))
        except ImportError as e:
            out.append((mod, False, str(e)))
    for mod in ("statsmodels", "lightgbm", "xgboost"):
        try:
            m = __import__(mod)
            out.append((f"{mod} (opcional)", True, getattr(m, "__version__", "ok")))
        except ImportError:
            out.append((f"{mod} (opcional)", True, "ausente — modelo não será usado"))
    w, msg = writable(data)
    out.append(("Pasta de dados gravável", w, msg))
    running = gpi_running(cfg["port"])
    out.append((f"Porta {cfg['port']}", port_free(cfg["port"]) or running, "em uso pelo GPI" if running else ""))
    out.append(("Interface", (resource_dir() / "frontend" / "index.html").exists(), str(resource_dir() / "frontend")))
    return out


def stop(data: Path) -> int:
    try:
        info = json.loads((data / "gpi.run.json").read_text())
        token = (data / "shutdown.token").read_text().strip()
    except OSError:
        print("Nenhuma instância do GPI registrada.")
        return 0
    req = urllib.request.Request(f"http://{HOST}:{info['port']}/api/shutdown", method="POST",
                                 headers={"X-Token": token})
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)
        print("GPI encerrado.")
    except Exception as e:  # noqa: BLE001
        print(f"Não foi possível contatar o GPI ({e}). Talvez já esteja fechado.")
    return 0


_NO_DIALOG = False  # --smoke/--check (testes automatizados): sem caixa de diálogo bloqueante


def fatal(msg: str):
    """Mensagem de erro amigável (caixa de diálogo no Windows quando não há console)."""
    logging.getLogger("gpi").error(msg)
    if sys.stderr is not None:
        print(msg, file=sys.stderr)
    if os.name == "nt" and frozen() and not _NO_DIALOG and not os.environ.get("GPI_NO_DIALOG"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "GPI — erro ao iniciar", 0x10)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------- janela de controle
def control_window(url: str, server, on_close):
    """Janela pequena 'GPI em execução' — fechar a janela encerra o servidor com segurança.
    Retorna False se Tk não estiver disponível (então usa-se o modo console)."""
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001 — sem display
        return False
    root.title("GPI — Global Product Intelligence")
    root.geometry("380x150")
    root.resizable(False, False)
    tk.Label(root, text="GPI em execução", font=("Segoe UI", 12, "bold")).pack(pady=(14, 2))
    tk.Label(root, text=url, fg="#0f766e").pack()
    tk.Label(root, text="Feche esta janela para encerrar o GPI.", fg="#555").pack(pady=(2, 8))
    bar = tk.Frame(root)
    bar.pack()
    tk.Button(bar, text="Abrir painel", width=14, command=lambda: webbrowser.open(url)).pack(side="left", padx=6)

    def close():
        on_close()
        root.destroy()

    tk.Button(bar, text="Encerrar GPI", width=14, command=close).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", close)

    def poll():                                    # encerrado pelo navegador ou --stop
        if server.should_exit or getattr(server, "_gpi_finished", False):
            root.destroy()
        else:
            root.after(500, poll)
    root.after(500, poll)
    root.mainloop()
    return True


# ---------------------------------------------------------------------- principal
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Global Product Intelligence")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--console", action="store_true")
    ap.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    global _NO_DIALOG
    _NO_DIALOG = bool(args.smoke or args.check)

    cfg0 = load_config()
    data = data_dir(cfg0)
    cfg = load_config(data)
    if args.port:
        cfg["port"] = args.port
    if args.stop:
        return stop(data)
    if args.check:
        ok = True
        for name, good, detail in diagnose(cfg, data):
            print(f"[{'OK ' if good else 'ERRO'}] {name} {detail}")
            ok &= good
        return 0 if ok else 1

    ok, msg = writable(data)
    if not ok:
        fatal(f"Não foi possível gravar na pasta de dados ({msg}). Defina GPI_DATA_DIR para uma pasta "
              "com permissão de escrita ou fale com a TI.")
        return 3
    setup_logging(data, cfg["log_level"])
    log = logging.getLogger("gpi")
    log.info("GPI %s — programa em %s; dados em %s", __version__, app_dir(), data)

    # 1. integridade
    ok, probs = verify_integrity(app_dir(), data / "integrity.json")
    if not ok:
        fatal("Arquivos do GPI ausentes ou alterados — extraia novamente o pacote.\n\n" + "\n".join(probs[:10]))
        return 4
    # primeira execução: copia o config de exemplo para a pasta do usuário
    ucfg = data / "config.json"
    if not ucfg.exists():
        try:
            shutil.copy2(resource_dir() / "config" / "gpi.json", ucfg)
        except OSError:
            pass

    # 2. instância já aberta / porta
    port = None
    for p in range(cfg["port"], cfg["port"] + cfg["port_range"]):
        if gpi_running(p):
            log.info("GPI já está em execução na porta %d; abrindo navegador.", p)
            if args.smoke:
                return 0
            if cfg["open_browser"] and not args.no_browser:
                webbrowser.open(f"http://{HOST}:{p}/")
            return 0
        if port_free(p):
            port = p
            break
    if port is None:
        fatal(f"Nenhuma porta livre entre {cfg['port']} e {cfg['port'] + cfg['port_range'] - 1}. "
              "Feche outros programas ou altere 'port' em config.json.")
        return 2

    # 3. servidor
    import uvicorn
    from .app import create_app

    holder = {}

    def shutdown():
        holder["server"].should_exit = True

    app = create_app(data, resource_dir() / "frontend", shutdown_cb=shutdown, cfg=cfg,
                     start_sync=cfg.get("auto_sync", True) and not args.smoke)
    (data / "gpi.run.json").write_text(json.dumps({"port": port, "pid": os.getpid()}))
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False,
                                           workers=1, log_config=None,
                                           timeout_graceful_shutdown=5))   # conexões keep-alive do navegador não seguram o encerramento
    holder["server"] = server
    url = f"http://{HOST}:{port}/"
    t = threading.Thread(target=server.run, daemon=True, name="gpi-server")
    t.start()
    for _ in range(120):
        if gpi_running(port):
            break
        time.sleep(0.25)
    else:
        fatal("O servidor local não respondeu. Veja o log em " + str(data / "logs" / "gpi.log"))
        shutdown()
        return 5
    log.info("GPI iniciado em %s (somente acesso local)", url)

    def finish():
        shutdown()
        t.join(15)
        try:
            app.state.sync.stop()
            app.state.db.close()
        except Exception:  # noqa: BLE001
            pass
        for f in ("gpi.run.json", "shutdown.token"):
            try:
                (data / f).unlink()
            except OSError:
                pass
        log.info("GPI encerrado.")

    if args.smoke:
        finish()
        print(f"SMOKE OK {url}")
        return 0

    if cfg["open_browser"] and not args.no_browser:
        webbrowser.open(url)
    try:
        if args.console or not control_window(url, server, shutdown):
            while t.is_alive():
                t.join(0.5)
    except KeyboardInterrupt:
        pass
    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
