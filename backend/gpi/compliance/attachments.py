"""Anexos da análise regulatória (ficha técnica, manual, catálogo, especificações, relatórios, certificados).

* Ficam só no computador (pasta de dados do GPI); nada é enviado à internet.
* Limites: 10 MB por arquivo, 30 MB por análise, formatos PDF, TXT, CSV, PNG, JPG, XLSX e DOCX.
* O conteúdo é conferido pela assinatura do arquivo (não só pela extensão). Arquivos com macros (vbaProject),
  executáveis, scripts e formatos com conteúdo ativo (.docm, .xlsm, .html, .js, .svg…) são recusados.
* Extração de texto apenas para leitura (PDF via pypdf; DOCX/XLSX lendo o XML do pacote, sem executar nada).
  O texto extraído é DADO NÃO CONFIÁVEL para a IA local.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024
MAX_TEXT = 60_000
ALLOWED = {".pdf": "pdf", ".txt": "texto", ".csv": "texto", ".png": "imagem", ".jpg": "imagem", ".jpeg": "imagem",
           ".xlsx": "planilha", ".docx": "documento"}
MAGIC = {".pdf": [b"%PDF-"], ".png": [b"\x89PNG\r\n\x1a\n"], ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
         ".xlsx": [b"PK\x03\x04"], ".docx": [b"PK\x03\x04"]}
DANGEROUS_ZIP = re.compile(r"(?i)(vbaProject\.bin|\.bin$|activeX|macrosheets|\.exe$|\.dll$|\.js$|\.vbs$|\.ps1$)")


class AttachmentError(ValueError):
    pass


def safe_name(name: str) -> str:
    base = Path(str(name or "anexo")).name
    base = re.sub(r"[^\w.\- ()]+", "_", base, flags=re.UNICODE).strip(" .") or "anexo"
    return base[:120]


def inspect(name: str, data: bytes) -> dict:
    nm = safe_name(name)
    ext = Path(nm).suffix.lower()
    if ext not in ALLOWED:
        raise AttachmentError(f"formato não permitido ({ext or 'sem extensão'}); use PDF, TXT, CSV, PNG, JPG, XLSX ou DOCX")
    if not data:
        raise AttachmentError("arquivo vazio")
    if len(data) > MAX_FILE:
        raise AttachmentError("arquivo maior que 10 MB")
    if ext in MAGIC and not any(data.startswith(m) for m in MAGIC[ext]):
        raise AttachmentError("o conteúdo não corresponde à extensão do arquivo")
    if ext in (".txt", ".csv"):
        if b"\x00" in data[:4096]:
            raise AttachmentError("arquivo de texto com conteúdo binário")
        head = data[:2048].lower()
        if head.startswith((b"mz", b"#!", b"<script", b"<html", b"<?php")):
            raise AttachmentError("conteúdo ativo não permitido")
    if ext in (".xlsx", ".docx"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist()
        except zipfile.BadZipFile:
            raise AttachmentError("pacote Office inválido") from None
        if any(DANGEROUS_ZIP.search(n) for n in names):
            raise AttachmentError("documento com macros ou conteúdo ativo não é aceito")
        if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
            raise AttachmentError("pacote Office com conteúdo descompactado excessivo")
    if ext == ".pdf":
        low = data.lower()
        ativo = any(t in low for t in (b"/javascript", b"/js ", b"/launch", b"/embeddedfile", b"/openaction"))
    else:
        ativo = False
    return {"nome": nm, "ext": ext, "tipo": ALLOWED[ext], "tamanho": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "pdf_com_conteudo_ativo": ativo}


def extract_text(info: dict, data: bytes) -> str:
    ext = info["ext"]
    try:
        if ext in (".txt", ".csv"):
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    return data.decode(enc)[:MAX_TEXT]
                except UnicodeDecodeError:
                    continue
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            r = PdfReader(io.BytesIO(data))
            out = []
            for p in r.pages[:60]:
                out.append(p.extract_text() or "")
                if sum(map(len, out)) > MAX_TEXT:
                    break
            return "\n".join(out)[:MAX_TEXT]
        if ext == ".docx":
            z = zipfile.ZipFile(io.BytesIO(data))
            xml = z.read("word/document.xml")
            root = ET.fromstring(xml)                       # sem DTD/entidades externas: ElementTree não resolve
            return " ".join(t.text or "" for t in root.iter() if t.tag.endswith("}t"))[:MAX_TEXT]
        if ext == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:5]:
                for row in ws.iter_rows(max_row=500, values_only=True):
                    out.append(" ".join(str(v) for v in row if v is not None))
            return "\n".join(out)[:MAX_TEXT]
    except Exception:  # noqa: BLE001 — anexo ilegível não interrompe a análise
        return ""
    return ""


def store(db, data_dir: Path, analysis_id: int | None, name: str, data: bytes) -> dict:
    info = inspect(name, data)
    if analysis_id is not None:
        used = db.query("SELECT COALESCE(SUM(tamanho), 0) AS n FROM compliance_attachments WHERE analysis_id = ?",
                        (analysis_id,))[0]["n"]
        if used + info["tamanho"] > MAX_TOTAL:
            raise AttachmentError("limite de 30 MB de anexos por análise atingido")
    folder = data_dir / "compliance" / "anexos"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{info['sha256'][:32]}{info['ext']}"
    if not path.exists():
        path.write_bytes(data)
    text = extract_text(info, data)
    cur = db.execute("INSERT INTO compliance_attachments (analysis_id, nome, tipo, tamanho, sha256, caminho, texto_extraido, criado_em) "
                     "VALUES (?,?,?,?,?,?,?,?)", (analysis_id, info["nome"], info["tipo"], info["tamanho"], info["sha256"],
                                                   path.name, text, datetime.now().isoformat(timespec="seconds")))
    return {**info, "id": int(cur.lastrowid), "texto_caracteres": len(text)}


def texts(db, ids: list[int]) -> list[str]:
    if not ids:
        return []
    q = ",".join("?" for _ in ids)
    return [r["texto_extraido"] or "" for r in db.query(f"SELECT texto_extraido FROM compliance_attachments WHERE id IN ({q})",
                                                         tuple(int(i) for i in ids))]
