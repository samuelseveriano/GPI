"""Assistência à classificação fiscal (NCM) — nunca uma classificação definitiva.

* Fonte: tabela NCM oficial do Portal Único (download público em JSON), carregada pelo usuário (botão "Atualizar
  tabela NCM"), por arquivo entregue pela TI ou pelo instantâneo incluído no pacote Windows (com data e hash).
* Valida formato, existência e vigência; mostra a hierarquia (capítulo → posição → subposição → item → subitem);
  sugere candidatos por palavras da descrição TÉCNICA (não só do nome) e aponta possíveis incompatibilidades.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

OFFICIAL_URL = "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json?perfil=PUBLICO"
MAX_BYTES = 40 * 1024 * 1024
STOP = set("de da do das dos e em para com sem por a o as os um uma outros outras outro outra suas seus".split())


def digits(code: str) -> str:
    return re.sub(r"\D", "", str(code or ""))


def fmt(code: str) -> str:
    d = digits(code)
    if len(d) == 8:
        return f"{d[:4]}.{d[4:6]}.{d[6:]}"
    if len(d) > 4:
        return f"{d[:4]}.{d[4:]}"
    return d


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _date(v):
    if not v:
        return None
    v = str(v).strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v[:19], f).date().isoformat()
        except ValueError:
            continue
    return None


def parse_official(raw: bytes | str) -> tuple[list[dict], dict]:
    """Lê o JSON oficial (tolerante a nomes de campos). Devolve (linhas, metadados)."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    data = json.loads(raw)
    items, meta = None, {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                items = v
            elif isinstance(v, (str, int, float)):
                meta[k] = v
    elif isinstance(data, list):
        items = data
    if not items:
        raise ValueError("arquivo NCM sem a lista de nomenclaturas")

    def pick(d, *subs):
        for k, v in d.items():
            kl = k.lower()
            if all(s in kl for s in subs):
                return v
        return None
    rows = []
    for it in items:
        cod = pick(it, "codigo") or pick(it, "code")
        desc = pick(it, "descri")
        if not cod or desc is None:
            continue
        ato = " ".join(str(x) for x in (pick(it, "tipo", "ato", "ini"), pick(it, "numero", "ato", "ini"),
                                         pick(it, "ano", "ato", "ini")) if x)
        rows.append({"codigo": digits(cod), "descricao": str(desc).strip(), "data_inicio": _date(pick(it, "inicio")),
                     "data_fim": _date(pick(it, "fim")), "ato": ato or None})
    if len(rows) < 10:
        raise ValueError("arquivo NCM com poucas linhas — formato inesperado")
    return rows, meta


class NcmTable:
    def __init__(self, db, bundled: Path | None = None):
        self.db = db
        self.bundled = bundled
        if bundled and bundled.exists() and not self.loaded():
            try:
                self.load_bytes(bundled.read_bytes(), origem=f"instantâneo incluído no pacote ({bundled.name})")
            except Exception:  # noqa: BLE001
                pass

    def loaded(self) -> bool:
        return bool(self.db.query("SELECT 1 FROM ncm_table LIMIT 1"))

    def meta(self) -> dict:
        m = {r["k"]: r["v"] for r in self.db.query("SELECT k, v FROM ncm_meta WHERE k LIKE 'ncm_%'")}
        n = self.db.query("SELECT COUNT(*) AS n FROM ncm_table")[0]["n"]
        return {"carregada": n > 0, "codigos": n, "fonte": m.get("ncm_fonte"), "carregada_em": m.get("ncm_carregada_em"),
                "sha256": m.get("ncm_sha256"), "atualizacao_oficial": m.get("ncm_atualizacao"), "ato": m.get("ncm_ato"),
                "url_oficial": OFFICIAL_URL}

    def load_bytes(self, raw: bytes, origem: str) -> dict:
        if len(raw) > MAX_BYTES:
            raise ValueError("arquivo NCM maior que o limite")
        rows, meta = parse_official(raw)
        h = hashlib.sha256(raw).hexdigest()
        with self.db.transaction():
            self.db.execute("DELETE FROM ncm_table")
            self.db.executemany("INSERT OR REPLACE INTO ncm_table VALUES (?,?,?,?,?)",
                                [(r["codigo"], r["descricao"], r["data_inicio"], r["data_fim"], r["ato"]) for r in rows])
            for k, v in (("ncm_fonte", origem), ("ncm_carregada_em", datetime.now().isoformat(timespec="seconds")),
                         ("ncm_sha256", h), ("ncm_atualizacao", str(next((v for k, v in meta.items() if "atualiza" in k.lower()), ""))),
                         ("ncm_ato", str(next((v for k, v in meta.items() if k.lower() == "ato"), "")))):
                self.db.execute("INSERT OR REPLACE INTO ncm_meta VALUES (?, ?)", (k, v))
        return {"codigos": len(rows), "sha256": h}

    def update_official(self, http) -> dict:
        r = http.request_json(OFFICIAL_URL, _binary=True, ttl=0, _max_bytes=MAX_BYTES, timeout=120)
        raw = r["_bytes"]
        return self.load_bytes(raw, origem=OFFICIAL_URL)

    # ------------------------------------------------------------------ consulta
    def get(self, code: str) -> dict | None:
        r = self.db.query("SELECT * FROM ncm_table WHERE codigo = ?", (digits(code),))
        return r[0] if r else None

    def hierarchy(self, code: str) -> list[dict]:
        d = digits(code)
        out = []
        for n in (2, 4, 5, 6, 7, 8):
            r = self.get(d[:n]) if len(d) >= n else None
            if r:
                out.append({"nivel": {2: "capítulo", 4: "posição", 5: "subposição (1º nível)", 6: "subposição",
                                      7: "item", 8: "subitem"}[n], "codigo": fmt(d[:n]), "descricao": r["descricao"]})
        return out

    def validate(self, code: str, feats: dict | None = None, today: date | None = None) -> dict:
        today = today or date.today()
        d = digits(code)
        out = {"codigo": d, "codigo_formatado": fmt(d), "alertas": [], "perguntas": [], "fontes": ["siscomex-tabela-ncm", "siscomex-classif"]}
        if not d:
            return {**out, "estado": "ausente"}
        if len(d) != 8:
            return {**out, "estado": "formato_invalido"}
        if not self.loaded():
            out["estado"] = "tabela_nao_carregada"
            out["aviso"] = "Carregue a tabela NCM oficial para verificar existência, descrição e vigência."
        else:
            r = self.get(d)
            if not r:
                out["estado"] = "inexistente"
            else:
                fim = r.get("data_fim")
                ini = r.get("data_inicio")
                vig = (not fim or fim >= today.isoformat()) and (not ini or ini <= today.isoformat())
                out.update(estado="valida" if vig else "expirada", descricao=r["descricao"], data_inicio=ini, data_fim=fim,
                           ato=r.get("ato"), hierarquia=self.hierarchy(d))
        if feats:
            out["alertas"] = mismatches(d, feats)
        out["observacao"] = ("O GPI não confirma a classificação fiscal: validar com as notas legais e explicativas, o "
                             "Sistema Classif e, havendo dúvida, consulta formal à Receita Federal.")
        return out

    def candidates(self, text: str, limit: int = 8) -> list[dict]:
        """Candidatos por sobreposição de palavras com as descrições oficiais (apenas sugestões para investigar)."""
        if not self.loaded():
            return []
        words = [w for w in _norm(text).split() if len(w) > 3 and w not in STOP][:12]
        if not words:
            return []
        like = " OR ".join("lower(descricao) LIKE ?" for _ in words)
        rows = self.db.query(f"SELECT codigo, descricao FROM ncm_table WHERE length(codigo) = 8 AND ({like}) LIMIT 400",
                             tuple(f"%{w}%" for w in words))
        scored = []
        for r in rows:
            nd = _norm(r["descricao"])
            s = sum(1 for w in words if w in nd)
            path = self.hierarchy(r["codigo"])
            ctx = " ".join(_norm(p["descricao"]) for p in path)
            s += 0.5 * sum(1 for w in words if w in ctx)
            scored.append((s, r["codigo"], r["descricao"], path))
        scored.sort(key=lambda x: -x[0])
        return [{"codigo": fmt(c), "descricao": desc, "pontuacao": round(s, 2), "hierarquia": path,
                 "aviso": "candidato para investigação — não é classificação"} for s, c, desc, path in scored[:limit]]


def mismatches(code: str, feats: dict) -> list[str]:
    """Incompatibilidades grosseiras entre o capítulo da NCM e características técnicas informadas."""
    d = digits(code)
    ch = d[:2]
    c = feats.get("caracteristicas", {})
    out = []
    radio = any(c.get(k, {}).get("valor") for k in ("wifi", "bluetooth", "rf", "celular"))
    if c.get("brinquedo", {}).get("valor") and ch != "95":
        out.append(f"produto informado como brinquedo, mas a NCM está no capítulo {ch} (brinquedos costumam estar no capítulo 95)")
    if radio and ch not in ("84", "85", "90", "95", "87", "88", "91", "94"):
        out.append(f"produto com transmissor de RF e NCM no capítulo {ch}, fora dos capítulos típicos de máquinas e aparelhos")
    if c.get("medico", {}).get("valor") and ch not in ("90", "30", "94", "84", "85", "40", "39"):
        out.append(f"produto de saúde com NCM no capítulo {ch}")
    return out
