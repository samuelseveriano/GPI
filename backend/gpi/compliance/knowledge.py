"""Base de conhecimento regulatória local (Camada 2 do motor — busca de documentos).

* Documentos com metadados completos (órgão, título, número, publicação, vigência, última verificação, URL oficial,
  versão, identificador, hash, status de atualização e texto utilizado).
* Busca textual BM25 (SQLite FTS5; sem FTS5, busca por termos com pontuação simples), com filtros por órgão,
  marcadores técnicos (aplica_a), categoria, prefixo de NCM e vigência.
* Documentos revogados nunca aparecem como vigentes; conflitos são sinalizados; cada mudança preserva histórico.
* Todo texto recuperado é DADO NÃO CONFIÁVEL para a IA local: é marcado e higienizado antes de entrar no prompt.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

BUNDLED = Path(__file__).with_name("kb") / "documentos.json"
REVOGADO = ("revogado", "revogada", "substituido")
VIGENTE_PREFIX = "vigente"
STALE_WARN_DAYS = 120          # aviso de base desatualizada
STALE_BLOCK_DAYS = 365         # acima disso, nenhuma exigência é dada como "identificada"
STATE_LABEL = {1: "EXIGÊNCIA IDENTIFICADA", 2: "POTENCIAL EXIGÊNCIA", 3: "NÃO IDENTIFICADA NAS FONTES CONSULTADAS",
               4: "INFORMAÇÕES INSUFICIENTES", 5: "REVISÃO ESPECIALIZADA NECESSÁRIA"}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9.\- ]+", " ", t)


def text_hash(texto: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", texto or "").strip().encode("utf-8")).hexdigest()


INJECTION = re.compile(r"(?i)(ignore (all |the )?(previous|prior|above) (instructions|rules)|ignore as instru[cç][oõ]es|"
                       r"desconsidere (as )?instru[cç][oõ]es|system prompt|you are now|voc[eê] agora [eé]|"
                       r"<\s*/?\s*(system|assistant|user|documento|instrucoes)\s*>|\[/?INST\]|<\|im_(start|end)\|>)")


def sanitize_untrusted(texto: str, limit: int = 1800) -> tuple[str, bool]:
    """Remove marcadores de papel/instrução de textos recuperados. Retorna (texto, havia_tentativa_de_injeção)."""
    flagged = bool(INJECTION.search(texto or ""))
    t = INJECTION.sub("[trecho removido: instrução embutida no documento]", texto or "")
    t = t.replace("```", "'''")
    return t[:limit], flagged


class KnowledgeBase:
    def __init__(self, db, data_dir: Path | None = None):
        self.db = db
        self.data_dir = data_dir
        self.fts = self._ensure_fts()
        if not self.db.query("SELECT 1 FROM compliance_docs LIMIT 1"):
            self.load_bundled()

    # ------------------------------------------------------------------ carga
    def _ensure_fts(self) -> bool:
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS compliance_fts USING fts5("
                            "doc_id UNINDEXED, titulo, texto, tags, tokenize='unicode61 remove_diacritics 2')")
            return True
        except Exception:  # noqa: BLE001 — SQLite sem FTS5: busca alternativa
            return False

    def load_bundled(self) -> dict:
        pack = json.loads(BUNDLED.read_text(encoding="utf-8"))
        return self.apply_pack(pack, origem="base_embarcada")

    def apply_pack(self, pack: dict, origem: str) -> dict:
        """Insere/atualiza documentos. Mudança de texto/situação → nova versão; a anterior vai para o histórico."""
        if pack.get("formato") != "gpi-base-regulatoria":
            raise ValueError("pacote regulatório em formato desconhecido")
        now = datetime.now().isoformat(timespec="seconds")
        res = {"novos": 0, "alterados": 0, "revogados": 0, "inalterados": 0}
        with self.db.transaction():
            for d in pack["documentos"]:
                self._validate(d)
                h = d.get("hash_sha256") or None
                cur = self.db.query("SELECT * FROM compliance_docs WHERE id = ?", (d["id"],))
                meta = json.dumps(d, ensure_ascii=False)
                if cur:
                    c = cur[0]
                    same = c["texto"] == d["texto"] and c["situacao"] == d["situacao"] and c["meta"] == meta
                    if same:
                        res["inalterados"] += 1
                        continue
                    same_content = (c["texto"] == d["texto"] and c["situacao"] == d["situacao"]
                                    and (c["hash_sha256"] in (None, h) or h is None))
                    if same_content:                # só metadados de verificação mudaram: sem nova versão
                        self.db.execute("UPDATE compliance_docs SET meta = ?, ultima_verificacao = ?, status_atualizacao = ?, "
                                        "hash_sha256 = COALESCE(?, hash_sha256), atualizado_em = ? WHERE id = ?",
                                        (meta, d.get("ultima_verificacao"), d.get("status_atualizacao"), h, now, d["id"]))
                        res["inalterados"] += 1
                        continue
                    self.db.execute("INSERT INTO compliance_doc_history (doc_id, versao, hash_sha256, situacao, meta, texto, "
                                    "substituido_em, motivo) VALUES (?,?,?,?,?,?,?,?)",
                                    (c["id"], c["versao"], c["hash_sha256"], c["situacao"], c["meta"], c["texto"], now, origem))
                    versao = int(c["versao"]) + 1
                    res["revogados" if d["situacao"].startswith(REVOGADO) and not c["situacao"].startswith(REVOGADO)
                        else "alterados"] += 1
                else:
                    versao = int(d.get("versao") or 1)
                    res["novos"] += 1
                self.db.execute(
                    "INSERT OR REPLACE INTO compliance_docs (id, orgao, tipo, numero, titulo, data_publicacao, vigencia_inicio, "
                    "situacao, ultima_verificacao, url_oficial, versao, hash_sha256, status_atualizacao, meta, texto, origem, "
                    "atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["id"], d["orgao"], d.get("tipo"), d.get("numero"), d["titulo"], d.get("data_publicacao"),
                     d.get("vigencia_inicio"), d["situacao"], d.get("ultima_verificacao"), d.get("url_oficial"), versao, h,
                     d.get("status_atualizacao"), meta, d["texto"], origem, now))
                if self.fts:
                    self.db.execute("DELETE FROM compliance_fts WHERE doc_id = ?", (d["id"],))
                    self.db.execute("INSERT INTO compliance_fts (doc_id, titulo, texto, tags) VALUES (?,?,?,?)",
                                    (d["id"], f"{d['orgao']} {d.get('tipo') or ''} {d.get('numero') or ''} {d['titulo']}",
                                     d["texto"], " ".join(d.get("aplica_a", []) + d.get("categorias", []))))
            self.db.execute("INSERT OR REPLACE INTO ncm_meta VALUES ('kb_versao', ?)", (pack.get("versao_base", "?"),))
            self.db.execute("INSERT OR REPLACE INTO ncm_meta VALUES ('kb_gerado_em', ?)", (pack.get("gerado_em", ""),))
        return res

    @staticmethod
    def _validate(d: dict):
        for k in ("id", "orgao", "titulo", "situacao", "texto"):
            if not d.get(k):
                raise ValueError(f"documento sem o campo obrigatório '{k}'")
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{2,80}", d["id"]):
            raise ValueError(f"identificador inválido: {d['id']}")
        u = d.get("url_oficial") or ""
        if u and not u.startswith(("https://", "http://")):
            raise ValueError(f"URL oficial inválida em {d['id']}")

    # ------------------------------------------------------------------ consulta
    def doc(self, doc_id: str) -> dict | None:
        r = self.db.query("SELECT * FROM compliance_docs WHERE id = ?", (doc_id,))
        return self._out(r[0]) if r else None

    def all(self, include_revoked: bool = True) -> list[dict]:
        rows = [self._out(r) for r in self.db.query("SELECT * FROM compliance_docs ORDER BY orgao, id")]
        return rows if include_revoked else [r for r in rows if not r["revogado"]]

    def history(self, doc_id: str) -> list[dict]:
        return self.db.query("SELECT doc_id, versao, hash_sha256, situacao, substituido_em, motivo FROM compliance_doc_history "
                             "WHERE doc_id = ? ORDER BY versao DESC", (doc_id,))

    def _out(self, r: dict) -> dict:
        meta = json.loads(r["meta"])
        rev = str(r["situacao"]).startswith(REVOGADO)
        return {**meta, "versao": r["versao"], "hash_sha256": r["hash_sha256"], "status_atualizacao": r["status_atualizacao"],
                "ultima_verificacao": r["ultima_verificacao"], "situacao": r["situacao"], "texto": r["texto"],
                "revogado": rev, "vigente": (not rev) and str(r["situacao"]).startswith(VIGENTE_PREFIX),
                "origem": r["origem"]}

    def search(self, query: str = "", orgao: str | None = None, tags: list[str] | None = None, categoria: str | None = None,
               ncm: str | None = None, only_current: bool = True, limit: int = 8) -> list[dict]:
        docs = {d["id"]: d for d in self.all()}
        scores: dict[str, float] = {}
        q = norm(query)
        terms = [t for t in re.findall(r"[a-z0-9]{3,}", q)][:20]
        if terms and self.fts:
            expr = " OR ".join(f'"{t}"' for t in terms)
            try:
                for r in self.db.query("SELECT doc_id, bm25(compliance_fts, 0, 3.0, 1.0, 2.0) AS s FROM compliance_fts "
                                       "WHERE compliance_fts MATCH ? ORDER BY s LIMIT 50", (expr,)):
                    scores[r["doc_id"]] = -float(r["s"])
            except Exception:  # noqa: BLE001
                pass
        elif terms:
            for d in docs.values():
                hay = norm(f"{d['titulo']} {d['texto']} {' '.join(d.get('aplica_a', []))}")
                s = sum(hay.count(t) for t in terms)
                if s:
                    scores[d["id"]] = float(s)
        for d in docs.values():               # marcadores técnicos e NCM pesam mais que palavras soltas
            bonus = 0.0
            if tags:
                bonus += 2.0 * len(set(tags) & set(d.get("aplica_a", [])))
            if ncm and any(re.sub(r"\D", "", ncm).startswith(p) for p in d.get("ncm_prefixos", [])):
                bonus += 3.0
            if categoria and categoria in d.get("categorias", []):
                bonus += 1.0
            if bonus:
                scores[d["id"]] = scores.get(d["id"], 0.0) + bonus
        out = []
        for did, s in sorted(scores.items(), key=lambda x: -x[1]):
            d = docs.get(did)
            if not d or (orgao and d["orgao"].lower() != orgao.lower() and not d["orgao"].lower().startswith(orgao.lower())):
                continue
            if only_current and d["revogado"]:
                continue
            out.append({**d, "pontuacao": round(s, 3)})
            if len(out) >= limit:
                break
        return out

    def freshness(self, today: date | None = None) -> dict:
        today = today or date.today()
        datas = [r["ultima_verificacao"] for r in self.db.query("SELECT ultima_verificacao FROM compliance_docs") if r["ultima_verificacao"]]
        if not datas:
            return {"ultima_verificacao": None, "dias": None, "desatualizada": True, "bloquear_exigencias": True,
                    "aviso": "Base regulatória vazia."}
        ultima = min(datas)                # o documento verificado há mais tempo determina a idade da base
        dias = (today - date.fromisoformat(ultima[:10])).days
        aviso = None
        if dias > STALE_BLOCK_DAYS:
            aviso = (f"Base regulatória desatualizada ({dias} dias desde a verificação mais antiga). Os resultados não "
                     "podem indicar exigências como identificadas; atualize a base antes de decidir.")
        elif dias > STALE_WARN_DAYS:
            aviso = f"Base regulatória com {dias} dias desde a verificação mais antiga — atualize a base regulatória."
        kb = {r["k"]: r["v"] for r in self.db.query("SELECT k, v FROM ncm_meta WHERE k LIKE 'kb_%'")}
        return {"ultima_verificacao": ultima, "dias": dias, "desatualizada": dias > STALE_WARN_DAYS,
                "bloquear_exigencias": dias > STALE_BLOCK_DAYS, "aviso": aviso, "versao": kb.get("kb_versao"),
                "documentos": len(datas)}

    def conflicts(self) -> list[dict]:
        """Documentos com conflito declarado ou situação que exige revisão (alterado pelo atualizador)."""
        out = []
        for d in self.all():
            if d.get("conflito") or d.get("status_atualizacao") == "alterado_revisao":
                out.append({"id": d["id"], "titulo": d["titulo"], "motivo": d.get("conflito") or
                            "texto oficial mudou desde a curadoria — revisão humana necessária"})
        return out
