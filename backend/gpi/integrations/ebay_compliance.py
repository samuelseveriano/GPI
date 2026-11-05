"""GPI v0.8.2 — conformidade eBay (Marketplace Account Deletion) e diagnóstico da Browse API.

Fluxo: eBay → Worker Cloudflare (verifica a assinatura e grava no D1) → GPI consulta as pendências (ao abrir, após cada
sincronização e manualmente) → localiza e exclui os dados do usuário eBay no SQLite, nos backups, no cache HTTP e nos
snapshots de relatórios → confirma ao Worker (que então apaga os identificadores do D1).

Autenticação GPI ↔ Worker: HMAC-SHA256 com o segredo EBAY_GPI_SYNC_TOKEN (guardado com DPAPI no GPI e como Secret na
Cloudflare) sobre método, caminho, horário, nonce e SHA-256 do corpo — o segredo nunca trafega.

Minimização: a partir da v0.8.2 o GPI guarda o vendedor do anúncio apenas como pseudônimo (HMAC com chave local), o
cache HTTP do eBay é desligado e registros antigos com nome de usuário são pseudonimizados. Exclusões usam
PRAGMA secure_delete (o conteúdo apagado é sobrescrito) e alcançam os backups SQLite."""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import time
from pathlib import Path

from ..connectors.http import SourceError

log = logging.getLogger("gpi")
WORKER_DEFAULT = "https://gpi-ebay-notifications.samuelseveriano.workers.dev"
ENDPOINT_PATH = "/ebay/notifications"
STALE_SYNC_DAYS = 7          # sem sincronizar há mais de 7 dias com credenciais configuradas → alerta
OVERDUE_DAYS = 3             # solicitação aberta há mais de 3 dias → alerta

_SCHEMA = """CREATE TABLE IF NOT EXISTS ebay_deletion_log (
    notification_id TEXT PRIMARY KEY, event_date TEXT, received_at TEXT, processed_at TEXT NOT NULL,
    result TEXT NOT NULL, details TEXT, confirmed_at TEXT, error TEXT)"""


# ----------------------------------------------------------------------------------------------- configuração
def worker_url(creds) -> str:
    u = str((creds.get("ebay") or {}).get("worker_url") or WORKER_DEFAULT).strip().rstrip("/")
    if not re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?$", u):
        raise SourceError("o endereço do Worker deve ser https://<host> (sem caminho)", "restrita")
    return u


def configured(creds) -> dict:
    c = creds.get("ebay") or {}
    return {"credenciais_ebay": bool(c.get("client_id") and c.get("client_secret")), "token_sincronizacao": bool(c.get("sync_token")),
            "worker_url": str(c.get("worker_url") or WORKER_DEFAULT)}


def _seller_key(creds) -> bytes:
    p = creds.get("ebay_privacy") or {}
    k = p.get("seller_key")
    if not k:
        k = secrets.token_hex(32)
        creds.set("ebay_privacy", {"seller_key": k})
    return bytes.fromhex(k)


def seller_pseudonym(creds, username: str | None) -> str | None:
    """Pseudônimo estável do vendedor (deduplicação de concorrência sem guardar o nome de usuário)."""
    if not username:
        return None
    return "h:" + hmac.new(_seller_key(creds), username.strip().lower().encode(), hashlib.sha256).hexdigest()[:32]


# ----------------------------------------------------------------------------------------------- Worker
def _signed(http, creds, method: str, path: str, body: dict | None = None) -> dict:
    tok = str((creds.get("ebay") or {}).get("sync_token") or "")
    if len(tok) < 32:
        raise SourceError("token de sincronização do Worker não configurado (Central de Integrações → eBay)", "restrita")
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode() if body is not None else b""
    ts, nonce = str(int(time.time())), secrets.token_urlsafe(18)
    base = "\n".join([method, path, ts, nonce, hashlib.sha256(raw).hexdigest()]).encode()
    sig = hmac.new(tok.encode(), base, hashlib.sha256).hexdigest()
    headers = {"X-GPI-Timestamp": ts, "X-GPI-Nonce": nonce, "X-GPI-Signature": sig, "Content-Type": "application/json"}
    return http.request_json(worker_url(creds) + path, method, headers=headers, ttl=0, _body=raw if method == "POST" else None,
                             timeout=30)


def worker_status(http, creds) -> dict:
    return _signed(http, creds, "GET", "/gpi/v1/status")


# ----------------------------------------------------------------------------------------------- exclusão local
def _ensure(db):
    db.execute(_SCHEMA)


def _scan_cache(cache_dir: Path, names: set[str]) -> list[Path]:
    """Arquivos do cache HTTP com respostas do eBay que citam o usuário (o cache é descartável)."""
    hits = []
    if not cache_dir or not cache_dir.exists():
        return hits
    for f in cache_dir.glob("*.json"):
        try:
            if f.stat().st_size > 20_000_000:
                continue
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "itemSummaries" not in txt and "seller" not in txt:
            continue
        low = txt.lower()
        if any(f'"{n}"' in low for n in names):
            hits.append(f)
    return hits


def _delete_in_sqlite(path: Path, names: set[str], pseudo: str | None) -> int:
    """Exclui os anúncios do vendedor num arquivo SQLite (banco ou backup) com secure_delete + VACUUM."""
    con = sqlite3.connect(str(path), timeout=30)
    try:
        con.execute("PRAGMA secure_delete = ON")
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(market_listings)")}
        except sqlite3.DatabaseError:
            return 0
        if "seller" not in cols:
            return 0
        keys = sorted(names | ({pseudo} if pseudo else set()))
        q = "DELETE FROM market_listings WHERE source = 'ebay' AND lower(trim(seller)) IN (%s)" % ",".join("?" * len(keys))
        n = con.execute(q, keys).rowcount
        con.commit()
        if n:
            con.execute("VACUUM")
        return n
    finally:
        con.close()


def process_one(db, data_dir: Path, cache_dir: Path, creds, item: dict) -> dict:
    """Localiza e exclui TUDO o que se refere ao usuário eBay notificado. Resultado: DELETED, NOT_FOUND, NEEDS_REVIEW ou ERROR.
    Só confirma DELETED/NOT_FOUND quando a verificação posterior não encontra mais nada."""
    names = {str(x).strip().lower() for x in (item.get("ebay_username"), item.get("ebay_user_id")) if x}
    if not names:
        return {"result": "NEEDS_REVIEW", "detail": "notificação sem identificador do usuário", "contagens": {}}
    pseudo = seller_pseudonym(creds, item.get("ebay_username")) if item.get("ebay_username") else None
    keys = sorted(names | ({pseudo} if pseudo else set()))
    ph = ",".join("?" * len(keys))
    counts = {"banco": 0, "backups": 0, "cache": 0, "relatorios": 0}
    review = []
    # 1) banco principal
    db.execute("PRAGMA secure_delete = ON")
    before = db.query(f"SELECT COUNT(*) AS n FROM market_listings WHERE source = 'ebay' AND lower(trim(seller)) IN ({ph})", keys)[0]["n"]
    if before:
        db.execute(f"DELETE FROM market_listings WHERE source = 'ebay' AND lower(trim(seller)) IN ({ph})", keys)
        counts["banco"] = before
        try:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")      # remove cópias antigas das páginas no arquivo WAL
        except Exception:  # noqa: BLE001
            pass
    # 2) backups SQLite (impede restaurar o que foi excluído)
    for b in sorted((data_dir / "backups").glob("*.sqlite")) if (data_dir / "backups").exists() else []:
        try:
            counts["backups"] += _delete_in_sqlite(b, names, pseudo)
        except sqlite3.Error as e:
            review.append(f"backup {b.name} não pôde ser alterado ({type(e).__name__})")
    # 3) cache HTTP com respostas brutas do eBay
    for f in _scan_cache(cache_dir, names):
        try:
            f.unlink()
            m = f.with_suffix(".meta")
            if m.exists():
                m.unlink()
            counts["cache"] += 1
        except OSError:
            review.append("arquivo de cache não pôde ser removido")
    # 4) snapshots de relatórios (o arquivo gerado é removido; o snapshot fica sem o identificador e pode ser regerado)
    rep = data_dir / "relatorios"
    for snap in sorted(rep.rglob("*.snapshot.json.gz")) if rep.exists() else []:
        try:
            txt = gzip.decompress(snap.read_bytes()).decode("utf-8", "ignore")
        except (OSError, EOFError, ValueError):
            continue
        low = txt.lower()
        if not any(f'"{n}"' in low for n in names):
            continue
        red = txt
        for n in names:
            red = re.sub(re.escape(f'"{n}"'), '"[excluído a pedido do eBay]"', red, flags=re.I)
        snap.write_bytes(gzip.compress(red.encode("utf-8")))
        stem = snap.name[: -len(".snapshot.json.gz")]
        for out in snap.parent.glob(stem + ".*"):
            if out != snap and not out.name.endswith(".snapshot.json.gz"):
                try:
                    out.unlink()
                except OSError:
                    review.append(f"relatório {out.name} não pôde ser removido")
        counts["relatorios"] += 1
    # verificação posterior: não confirmar exclusão só porque a consulta rodou
    left = db.query(f"SELECT COUNT(*) AS n FROM market_listings WHERE source = 'ebay' AND lower(trim(seller)) IN ({ph})", keys)[0]["n"]
    if left:
        review.append(f"{left} registro(s) continuam no banco após a exclusão")
    if review:
        return {"result": "NEEDS_REVIEW", "detail": "; ".join(review)[:280], "contagens": counts}
    total = sum(counts.values())
    return {"result": "DELETED" if total else "NOT_FOUND",
            "detail": ", ".join(f"{k}: {v}" for k, v in counts.items() if v) or "nenhum dado do usuário estava armazenado",
            "contagens": counts}


def pseudonymize_existing(db, creds) -> int:
    """Troca nomes de usuário de vendedores eBay já gravados por pseudônimos (análise de concorrência preservada)."""
    rows = db.query("SELECT DISTINCT seller FROM market_listings WHERE source = 'ebay' AND seller IS NOT NULL AND seller NOT LIKE 'h:%'")
    if not rows:
        return 0
    db.execute("PRAGMA secure_delete = ON")
    n = 0
    with db.transaction():
        for r in rows:
            db.execute("UPDATE market_listings SET seller = ? WHERE source = 'ebay' AND seller = ?", (seller_pseudonym(creds, r["seller"]), r["seller"]))
            n += 1
    return n


def sync(db, http, creds, data_dir: Path, cache_dir: Path, store=None, trigger: str = "manual") -> dict:
    """Retira as pendências do Worker, processa e confirma. Seguro para rodar a qualquer momento (idempotente)."""
    _ensure(db)
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = {"inicio": t0, "gatilho": trigger, "processadas": 0, "resultados": {}, "erros": [], "situacao": "ok"}
    cf = configured(creds)
    if not cf["token_sincronizacao"]:
        out["situacao"] = "nao_configurado"
        out["erros"].append("token de sincronização não configurado")
        _save(store, out)
        return out
    try:
        out["pseudonimizados"] = pseudonymize_existing(db, creds)
        seen: set[str] = set()
        for _ in range(20):                                      # até 20 lotes por execução
            got = _signed(http, creds, "POST", "/gpi/v1/claim", {"limit": 25})
            items = [i for i in (got.get("itens") or []) if i["notification_id"] not in seen]
            if not items:                                        # nada novo neste ciclo (retentativas ficam para depois)
                break
            for it in items:
                seen.add(it["notification_id"])
                try:
                    r = process_one(db, data_dir, cache_dir, creds, it)
                except Exception as e:  # noqa: BLE001 — registra e devolve como ERROR para nova tentativa
                    r = {"result": "ERROR", "detail": "", "error": type(e).__name__, "contagens": {}}
                db.execute("INSERT INTO ebay_deletion_log (notification_id, event_date, received_at, processed_at, result, details, error) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(notification_id) DO UPDATE SET processed_at = excluded.processed_at, "
                           "result = excluded.result, details = excluded.details, error = excluded.error",
                           (it["notification_id"], it.get("event_date"), it.get("received_at"), time.strftime("%Y-%m-%dT%H:%M:%S"),
                            r["result"], json.dumps(r.get("contagens") or {}), r.get("error")))
                ack = _signed(http, creds, "POST", "/gpi/v1/ack", {"notification_id": it["notification_id"], "result": r["result"],
                                                                   "detail": r.get("detail", "")[:280], "error": r.get("error")})
                if ack.get("ok"):
                    db.execute("UPDATE ebay_deletion_log SET confirmed_at = ? WHERE notification_id = ?",
                               (time.strftime("%Y-%m-%dT%H:%M:%S"), it["notification_id"]))
                out["processadas"] += 1
                out["resultados"][r["result"]] = out["resultados"].get(r["result"], 0) + 1
        out["worker"] = worker_status(http, creds)
    except SourceError as e:
        out["situacao"] = "falhou"
        out["erros"].append(classify_worker_error(e))
    out["fim"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(store, out)
    return out


def classify_worker_error(e: SourceError) -> str:
    st = getattr(e, "status", None)
    if st == 401:
        return "o Worker recusou a autenticação: o token de sincronização do GPI difere do Secret EBAY_GPI_SYNC_TOKEN, ou o relógio do computador está errado"
    if st == 503:
        return "o Worker está sem o Secret EBAY_GPI_SYNC_TOKEN ou o D1 está indisponível"
    if st == 429:
        return "o Worker limitou as requisições após falhas de autenticação; tente em 1 minuto"
    if st == 404:
        return "o Worker publicado é anterior à v0.8.2 (rotas /gpi/v1 ausentes): publique o código atualizado"
    if e.kind in ("rede", "tls"):
        return "não foi possível alcançar o Worker (rede corporativa, proxy ou certificado)"
    return f"falha ao falar com o Worker ({e.kind})"


def _save(store, out):
    if store is not None:
        try:
            store.save_result("ebay:conformidade", {"resultado": out})
        except Exception:  # noqa: BLE001
            pass


def local_status(db, creds, store=None) -> dict:
    _ensure(db)
    last = (store.load_result("ebay:conformidade") or {}).get("resultado") if store is not None else None
    cnt = {r["result"]: r["n"] for r in db.query("SELECT result, COUNT(*) AS n FROM ebay_deletion_log GROUP BY result")}
    unconfirmed = db.query("SELECT COUNT(*) AS n FROM ebay_deletion_log WHERE confirmed_at IS NULL")[0]["n"]
    plain = db.query("SELECT COUNT(DISTINCT seller) AS n FROM market_listings WHERE source = 'ebay' AND seller IS NOT NULL "
                     "AND seller NOT LIKE 'h:%'")[0]["n"]
    listings = db.query("SELECT COUNT(*) AS n, MAX(collected_at) AS m FROM market_listings WHERE source = 'ebay'")[0]
    cf = configured(creds)
    alerts = []
    w = (last or {}).get("worker") or {}
    if cf["credenciais_ebay"] and not cf["token_sincronizacao"]:
        alerts.append("Credenciais do eBay configuradas sem a conformidade de exclusão: a coleta do eBay fica bloqueada até configurar o Worker.")
    if last and last.get("fim"):
        age = (time.time() - time.mktime(time.strptime(last["fim"], "%Y-%m-%dT%H:%M:%S"))) / 86400
        if age > STALE_SYNC_DAYS and cf["token_sincronizacao"]:
            alerts.append(f"A última sincronização de conformidade foi há {int(age)} dias: abra o GPI e sincronize.")
    if w.get("alerta"):
        alerts.append(w["alerta"])
    if (w.get("falhas") or 0) > 0:
        alerts.append(f"{w['falhas']} solicitação(ões) de exclusão exigem análise (ver histórico).")
    return {"configuracao": cf, "ultima_sincronizacao": last, "processadas_local": cnt, "nao_confirmadas": unconfirmed,
            "vendedores_em_texto": plain, "anuncios": listings["n"], "ultima_coleta": listings["m"], "alertas": alerts,
            "coleta_permitida": cf["credenciais_ebay"] and cf["token_sincronizacao"]}


# ----------------------------------------------------------------------------------------------- Browse API
BROWSE_STATES = {"rede": "Problema de rede", "credencial_invalida": "Credencial inválida", "keyset_desativado": "Keyset desativado",
                 "permissao_ausente": "Permissão ausente", "api_nao_autorizada": "API não autorizada", "limite": "Limite de requisições",
                 "falha_interna": "Falha interna do eBay", "ok": "Consulta real aprovada", "nao_configurado": "Não configurado"}


def _classify(e: SourceError, stage: str) -> str:
    st, body = getattr(e, "status", None), (getattr(e, "body", None) or str(e)).lower()
    if e.kind in ("rede", "tls") and not st:
        return "rede"
    if st == 429 or e.kind == "limite":
        return "limite"
    if st and st >= 500:
        return "falha_interna"
    if stage == "token":
        if "disabled" in body or "desativ" in body or "not active" in body:
            return "keyset_desativado"
        return "credencial_invalida"
    if st == 401:
        return "credencial_invalida"
    if st == 403:
        return "api_nao_autorizada" if ("not authorized" in body or "access denied" in body or "1100" in body) else "permissao_ausente"
    return "falha_interna"


def browse_diagnose(http, creds, db, store=None) -> dict:
    """10 verificações separadas. Token emitido NÃO prova que a Browse API está autorizada."""
    steps = []

    def add(n, nome, ok, msg, acao=None):
        steps.append({"etapa": n, "nome": nome, "ok": ok, "mensagem": msg, "acao": acao})
    c = creds.get("ebay") or {}
    cfg = bool(c.get("client_id") and c.get("client_secret"))
    add(1, "Credenciais Production configuradas", cfg, "App ID e Cert ID informados" if cfg else "App ID/Cert ID ausentes",
        None if cfg else "Central de Integrações → eBay: informe o App ID e o Cert ID do keyset Production.")
    if not cfg:
        return _browse_out(steps, "nao_configurado", db, creds, store)
    from ..connectors.sources5 import ebay_token
    creds.set("ebay", {"access_token": "", "expires_at": "0"})          # força um token novo (teste real)
    try:
        tok = ebay_token(http, creds)
    except SourceError as e:
        st = _classify(e, "token")
        cmp = local_status(db, creds, store)
        add(2, "Keyset ativo", False, "o eBay recusou o token de aplicativo",
            "Se o portal mostra 'Your keyset is currently disabled', conclua a conformidade de exclusão de contas (endpoint + "
            "token de verificação cadastrados) — ver docs/EBAY_CLOUDFLARE_SETUP.md." if not cmp["coleta_permitida"] or st == "keyset_desativado"
            else "Confira App ID e Cert ID (keyset Production, não Sandbox).")
        add(3, "Token OAuth válido", False, BROWSE_STATES[st])
        return _browse_out(steps, "keyset_desativado" if st == "credencial_invalida" and not cmp["coleta_permitida"] else st, db, creds, store)
    add(2, "Keyset ativo", True, "o eBay emitiu token para este keyset")
    add(3, "Token OAuth válido", True, "token de aplicativo (client credentials) emitido")
    add(4, "Escopos corretos", True, "escopo público https://api.ebay.com/oauth/api_scope solicitado e aceito")
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?q=usb+c+charger&limit=3"
    try:
        r = http.request_json(url, headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}, ttl=0)
    except SourceError as e:
        st = _classify(e, "browse")
        add(5, "Permissões da Browse API", False if st in ("permissao_ausente", "api_nao_autorizada") else None, BROWSE_STATES[st])
        add(6, "Aprovação de Production", False if st == "api_nao_autorizada" else None,
            "o eBay exige aprovação para uso de Buy APIs em produção" if st == "api_nao_autorizada" else "não verificável sem a consulta",
            "Solicite acesso de produção à Browse API no portal do desenvolvedor (Application Growth Check / Buy APIs)."
            if st == "api_nao_autorizada" else None)
        add(7, "Conectividade", st != "rede", "api.ebay.com alcançado" if st != "rede" else "api.ebay.com inacessível (rede/proxy)")
        return _browse_out(steps, st, db, creds, store)
    add(5, "Permissões da Browse API", True, "item_summary/search respondeu")
    add(6, "Aprovação de Production", True, "consulta de produção aceita")
    add(7, "Conectividade", True, "api.ebay.com alcançado")
    n = len(r.get("itemSummaries") or [])
    add(8, "Consulta real", True, f"total informado pelo eBay: {r.get('total', 0)}")
    add(9, "Recebimento de anúncios", n > 0, f"{n} anúncio(s) recebidos na amostra" if n else "nenhum anúncio na amostra")
    ls = local_status(db, creds, store)
    add(10, "Armazenamento permitido", ls["coleta_permitida"],
        "conformidade de exclusão configurada: a coleta pode gravar anúncios" if ls["coleta_permitida"] else
        "conformidade de exclusão não configurada: o GPI não grava dados do eBay",
        None if ls["coleta_permitida"] else "Configure o token de sincronização e sincronize a conformidade.")
    return _browse_out(steps, "ok" if n and ls["coleta_permitida"] else ("ok" if n else "falha_interna"), db, creds, store)


def _browse_out(steps, state, db, creds, store):
    out = {"etapas": steps, "estado": state, "estado_rotulo": BROWSE_STATES.get(state, state),
           "aviso": "Anúncios ativos não são vendas nem volume de pesquisa. Um token emitido não prova acesso à Browse API."}
    if store is not None:
        try:
            store.save_result("ebay:browse_diag", {"resultado": out})
        except Exception:  # noqa: BLE001
            pass
    return out
