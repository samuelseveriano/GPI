"""Atualização regulatória (seção 23).

* Online: lê somente as URLs oficiais dos documentos da base (domínios governamentais na lista abaixo), de forma
  incremental; registra novos/alterados/falhas; quando o conteúdo de um documento muda, marca "alterado_revisao" e
  preserva a versão anterior — as REGRAS nunca são alteradas automaticamente.
* Offline: pacote .zip gerado pelo GPI/CI com manifesto e SHA-256 de cada arquivo; o usuário/TI informa o SHA-256 do
  pacote publicado (verificação de procedência). Nada é executado: só JSON é lido.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import zipfile
from datetime import date, datetime
from urllib.parse import urlsplit

OFFICIAL_HOSTS = ("gov.br", "planalto.gov.br", "anatel.gov.br", "inmetro.gov.br", "siscomex.gov.br", "receita.fazenda.gov.br",
                  "eb.mil.br", "in.gov.br")
INDEX_URLS = ("https://informacoes.anatel.gov.br/legislacao/", "http://www.inmetro.gov.br/legislacao/")
MAX_DOC = 20 * 1024 * 1024


def is_official(url: str) -> bool:
    h = (urlsplit(url or "").hostname or "").lower()
    return any(h == d or h.endswith("." + d) for d in OFFICIAL_HOSTS)


def content_hash(raw: bytes, ctype_hint: str = "") -> str:
    """Hash do conteúdo relevante: PDF pelos bytes; HTML pelo texto visível (ignora scripts/estilos dinâmicos)."""
    if raw[:5] == b"%PDF-":
        return hashlib.sha256(raw).hexdigest()
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def check_online(db, kb, http, today: date | None = None, only: list[str] | None = None) -> dict:
    today = today or date.today()
    started = datetime.now().isoformat(timespec="seconds")
    det, novos, alterados, falhas, ok = [], 0, 0, 0, 0
    for d in kb.all():
        if only and d["id"] not in only:
            continue
        url = d.get("url_oficial") or ""
        if not url or url in INDEX_URLS:
            det.append({"id": d["id"], "resultado": "ignorado", "motivo": "URL de índice — conferência manual no portal"})
            continue
        if not is_official(url):
            det.append({"id": d["id"], "resultado": "ignorado", "motivo": "URL fora dos domínios oficiais"})
            continue
        try:
            r = http.request_json(url, _binary=True, ttl=0, _max_bytes=MAX_DOC, timeout=60,
                                  headers={"Accept": "text/html,application/pdf,application/json,*/*"})
            h = content_hash(r["_bytes"])
        except Exception as e:  # noqa: BLE001
            falhas += 1
            det.append({"id": d["id"], "resultado": "falha", "motivo": str(e)[:200]})
            continue
        prev = d.get("hash_sha256")
        meta = {k: v for k, v in d.items() if k not in ("versao", "revogado", "vigente", "origem", "pontuacao")}
        if not prev:
            novos += 1
            meta.update(hash_sha256=h, ultima_verificacao=today.isoformat(), status_atualizacao="verificado_automatico")
            res = "registrado"
        elif prev != h:
            alterados += 1
            meta.update(hash_sha256=h, ultima_verificacao=today.isoformat(), status_atualizacao="alterado_revisao",
                        conflito=f"conteúdo oficial mudou em {today.isoformat()} — revisar a regra e o resumo do GPI")
            res = "alterado"
        else:
            ok += 1
            meta.update(ultima_verificacao=today.isoformat(),
                        status_atualizacao=d.get("status_atualizacao") if d.get("status_atualizacao") == "alterado_revisao" else "verificado_automatico")
            res = "inalterado"
        kb.apply_pack({"formato": "gpi-base-regulatoria", "versao_base": _kb_version(db), "gerado_em": today.isoformat(),
                       "documentos": [meta]}, origem="atualizador_online")
        det.append({"id": d["id"], "resultado": res})
    fin = datetime.now().isoformat(timespec="seconds")
    cur = db.execute("INSERT INTO compliance_updates (iniciado_em, concluido_em, origem, novos, alterados, revogados, falhas, detalhes) "
                     "VALUES (?,?,?,?,?,?,?,?)", (started, fin, "online", novos, alterados, 0, falhas, json.dumps(det, ensure_ascii=False)))
    return {"id": int(cur.lastrowid), "registrados": novos, "alterados": alterados, "inalterados": ok, "falhas": falhas, "detalhes": det}


def _kb_version(db) -> str:
    r = db.query("SELECT v FROM ncm_meta WHERE k = 'kb_versao'")
    return r[0]["v"] if r else "?"


def export_pack(kb, versao: str) -> bytes:
    docs = [{k: v for k, v in d.items() if k not in ("revogado", "vigente", "origem", "pontuacao")} for d in kb.all()]
    body = json.dumps({"formato": "gpi-base-regulatoria", "versao_formato": 1, "versao_base": versao,
                       "gerado_em": date.today().isoformat(), "documentos": docs}, ensure_ascii=False, indent=1).encode("utf-8")
    man = {"formato": "gpi-pacote-regulatorio", "versao_base": versao,
           "arquivos": [{"nome": "documentos.json", "sha256": hashlib.sha256(body).hexdigest(), "tamanho": len(body)}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifesto.json", json.dumps(man, ensure_ascii=False, indent=1))
        z.writestr("documentos.json", body)
    return buf.getvalue()


def import_pack(db, kb, raw: bytes, expected_sha256: str) -> dict:
    got = hashlib.sha256(raw).hexdigest()
    if not expected_sha256 or got != expected_sha256.strip().lower():
        raise ValueError("SHA-256 do pacote não confere com o valor publicado — pacote recusado")
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = set(z.namelist())
    if names - {"manifesto.json", "documentos.json"}:
        raise ValueError("pacote contém arquivos inesperados — recusado")
    man = json.loads(z.read("manifesto.json"))
    if man.get("formato") != "gpi-pacote-regulatorio":
        raise ValueError("manifesto em formato desconhecido")
    body = z.read("documentos.json")
    f = next((x for x in man.get("arquivos", []) if x.get("nome") == "documentos.json"), None)
    if not f or hashlib.sha256(body).hexdigest() != f.get("sha256"):
        raise ValueError("documentos.json não confere com o manifesto")
    res = kb.apply_pack(json.loads(body), origem=f"pacote_offline:{got[:12]}")
    db.execute("INSERT INTO compliance_updates (iniciado_em, concluido_em, origem, novos, alterados, revogados, falhas, detalhes) "
               "VALUES (?,?,?,?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"),
                                            "pacote_offline", res["novos"], res["alterados"], res["revogados"], 0,
                                            json.dumps({"sha256": got, "versao": man.get("versao_base")})))
    return {**res, "sha256": got, "versao": man.get("versao_base")}


def history(db, limit: int = 20) -> list[dict]:
    rows = db.query("SELECT * FROM compliance_updates ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        try:
            r["detalhes"] = json.loads(r["detalhes"] or "null")
        except ValueError:
            pass
    return rows
