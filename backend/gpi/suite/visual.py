"""Visual Product Search — nível básico 100% local (Pillow + NumPy): hashes perceptuais (pHash/dHash/aHash), histograma
de cores, duplicatas, comparação simples e correspondência com as imagens do catálogo visual do GPI.

Nível avançado OPCIONAL: embeddings com um modelo ONNX que o próprio usuário coloca em <dados>/modelos/visual.onnx e
ativa nas configurações (nada é baixado automaticamente; nenhum serviço pago).

Busca externa ASSISTIDA: o GPI só monta links para o usuário abrir no navegador (Google Lens, TinEye, Yandex). Nenhum
upload automático e nenhuma raspagem dos resultados. Imagens privadas (enviadas pelo usuário) nunca saem do computador.

Regra central: semelhança visual NÃO comprova o mesmo fabricante, o mesmo modelo nem a mesma origem."""
from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import quote

import numpy as np

from . import store as S

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 8000
MAX_PIXELS = 40_000_000
THUMB = 512
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
CLASSES = ["Mesma imagem", "Imagem muito semelhante", "Possível mesmo produto", "Mesma família",
           "Produto visualmente relacionado", "Correspondência incerta"]
WARNING = ("Semelhança visual não comprova o mesmo fabricante, o mesmo modelo nem a mesma origem. Use o resultado para "
           "orientar a pesquisa (mercado, fornecedores, certificações), não como identificação.")


class ImageRejected(ValueError):
    pass


def sniff(raw: bytes) -> str | None:
    """Formato pelo CONTEÚDO (assinatura), nunca pela extensão ou pelo nome do arquivo."""
    if raw[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


def safe_label(name: str | None) -> str:
    """Nome exibido: sem caminho, sem caracteres de controle, curto. O arquivo gravado usa o SHA-256, nunca este nome."""
    n = Path(str(name or "imagem")).name
    n = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", n).strip(" .")
    return (n or "imagem")[:80]


def load(raw: bytes, crop: dict | None = None):
    """Valida e decodifica com limites de tamanho, resolução e descompressão. Devolve (imagem RGB sem metadados, info)."""
    from PIL import Image, ImageOps
    if not raw:
        raise ImageRejected("arquivo vazio")
    if len(raw) > MAX_BYTES:
        raise ImageRejected(f"arquivo maior que {MAX_BYTES // (1024 * 1024)} MB")
    fmt = sniff(raw)
    if not fmt:
        raise ImageRejected("formato não aceito (somente JPG, PNG e WEBP, verificados pelo conteúdo do arquivo)")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format != fmt:
                raise ImageRejected("conteúdo não corresponde ao formato declarado pela assinatura")
            w, h = probe.size
            if w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
                raise ImageRejected(f"resolução acima do limite ({MAX_SIDE}px por lado)")
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except ImageRejected:
        raise
    except Image.DecompressionBombError as e:
        raise ImageRejected("imagem recusada: possível bomba de descompressão") from e
    except Exception as e:  # noqa: BLE001
        raise ImageRejected("imagem corrompida ou inválida") from e
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)
    img = ImageOps.exif_transpose(img).convert("RGB")      # aplica a orientação e DESCARTA EXIF/GPS/metadados
    if crop:
        try:
            x, y, cw, ch = (max(0.0, min(1.0, float(crop.get(k, d)))) for k, d in (("x", 0), ("y", 0), ("w", 1), ("h", 1)))
        except (TypeError, ValueError) as e:
            raise ImageRejected("recorte inválido") from e
        W, Hh = img.size
        box = (int(x * W), int(y * Hh), int(min(1.0, x + cw) * W), int(min(1.0, y + ch) * Hh))
        if box[2] - box[0] < 16 or box[3] - box[1] < 16:
            raise ImageRejected("recorte pequeno demais (mínimo 16×16 pixels)")
        img = img.crop(box)
    return img, {"formato": fmt, "largura": img.size[0], "altura": img.size[1], "bytes": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest(), "metadados_removidos": True}


# ----------------------------------------------------------------------------------------------- impressões digitais
def _bits_hex(bits: np.ndarray) -> str:
    v = 0
    for b in bits.flatten():
        v = (v << 1) | int(bool(b))
    return f"{v:0{len(bits.flatten()) // 4}x}"


def _dct2(a: np.ndarray) -> np.ndarray:
    n = a.shape[0]
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    return m @ a @ m.T


def fingerprints(img) -> dict:
    from PIL import Image
    g = img.convert("L")
    a32 = np.asarray(g.resize((32, 32), Image.Resampling.LANCZOS), float)
    d = _dct2(a32)[:8, :8]
    flat = d.flatten()[1:]
    ph = d > np.median(flat)
    a9 = np.asarray(g.resize((9, 8), Image.Resampling.LANCZOS), float)
    dh = a9[:, 1:] > a9[:, :-1]
    a8 = np.asarray(g.resize((8, 8), Image.Resampling.LANCZOS), float)
    ah = a8 > a8.mean()
    rgb = np.asarray(img.resize((64, 64), Image.Resampling.BILINEAR), int) // 64
    idx = rgb[..., 0] * 16 + rgb[..., 1] * 4 + rgb[..., 2]
    hist = np.bincount(idx.flatten(), minlength=64).astype(float)
    hist /= hist.sum() or 1
    return {"phash": _bits_hex(ph), "dhash": _bits_hex(dh), "ahash": _bits_hex(ah), "color": [round(float(x), 5) for x in hist]}


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def color_sim(a: list, b: list) -> float:
    return float(np.minimum(np.asarray(a), np.asarray(b)).sum())


def classify(q: dict, c: dict, same_family: bool) -> tuple[str, float, list[str]]:
    """Classe + similaridade 0–1 (não é probabilidade) + motivos legíveis."""
    if q.get("sha256") and q["sha256"] == c.get("sha256"):
        return CLASSES[0], 1.0, ["arquivo idêntico (mesmo SHA-256)"]
    dp, dd, da = hamming(q["phash"], c["phash"]), hamming(q["dhash"], c["dhash"]), hamming(q["ahash"], c["ahash"])
    cs = color_sim(q["color"], c["color"])
    sim = round(max(0.0, 1 - (0.5 * dp + 0.3 * dd + 0.2 * da) / 64) * 0.8 + 0.2 * cs, 3)
    why = [f"distância pHash {dp}/64", f"dHash {dd}/64", f"aHash {da}/64", f"cores {cs:.0%}"]
    if dp <= 4 and dd <= 8:
        return CLASSES[1], sim, why + ["estrutura praticamente igual (provável redimensionamento/compressão da mesma foto)"]
    if dp <= 12 and cs >= 0.7:
        return CLASSES[2], sim, why + ["forma e cores parecidas — pode ser o mesmo produto em outra foto"]
    if same_family and dp <= 22:
        return CLASSES[3], sim, why + ["a imagem do catálogo pertence à mesma família de produto informada"]
    if dp <= 20 or cs >= 0.85:
        return CLASSES[4], sim, why + ["semelhança parcial de forma ou de cores"]
    return CLASSES[5], sim, why + ["semelhança fraca"]


# ----------------------------------------------------------------------------------------------- nível avançado opcional
def advanced_status(data_dir: Path, settings: dict) -> dict:
    model = Path(data_dir) / "modelos" / "visual.onnx"
    try:
        import onnxruntime  # noqa: F401
        rt = True
    except Exception:  # noqa: BLE001
        rt = False
    on = bool(settings.get("modelos_opcionais")) and model.exists() and rt
    return {"ativo": on, "modelo_presente": model.exists(), "onnxruntime": rt, "caminho_esperado": str(model),
            "como_ativar": "Coloque um modelo ONNX de embeddings de imagem (entrada 1×3×224×224) nesse caminho e ative "
                           "'Modelos opcionais' nas configurações. Nada é baixado automaticamente; o processamento é local.",
            "nota": "Opcional. O nível básico (hashes perceptuais e cores) funciona sem nenhum modelo."}


def embedding(img, data_dir: Path) -> np.ndarray | None:
    try:
        import onnxruntime as ort
        from PIL import Image
        sess = ort.InferenceSession(str(Path(data_dir) / "modelos" / "visual.onnx"), providers=["CPUExecutionProvider"])
        x = np.asarray(img.resize((224, 224), Image.Resampling.BILINEAR), np.float32) / 255.0
        x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
        out = np.asarray(sess.run(None, {sess.get_inputs()[0].name: x})[0], np.float32).flatten()
        n = np.linalg.norm(out)
        return out / n if n else None
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------------------------- catálogo visual
def _thumb(img, folder: Path, sha: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    t = img.copy()
    t.thumbnail((THUMB, THUMB))
    p = folder / f"{sha}.jpg"
    t.save(p, "JPEG", quality=85)                         # re-codificado: sem EXIF/ICC/metadados do original
    return p.name


def add_to_catalog(db, data_dir: Path, raw: bytes, label: str | None, product_id: str | None, family: str | None,
                   source: str = "enviada pelo usuário", crop: dict | None = None, settings: dict | None = None) -> dict:
    S.ensure(db)
    img, info = load(raw, crop)
    fp = fingerprints(img)
    if crop:
        info["sha256"] = hashlib.sha256(img.tobytes()).hexdigest()
    dup = db.query("SELECT image_id, label, product_id FROM product_images WHERE sha256 = ?", (info["sha256"],))
    if dup:
        return {"ok": True, "duplicada": True, "image_id": dup[0]["image_id"], "mensagem": "Imagem já estava no catálogo visual."}
    emb = embedding(img, data_dir) if (settings or {}).get("modelos_opcionais") else None
    name = _thumb(img, Path(data_dir) / "imagens_catalogo", info["sha256"])
    cur = db.execute("INSERT INTO product_images (sha256, phash, dhash, ahash, color, width, height, label, product_id, family, source, "
                     "stored_path, embedding, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (info["sha256"], fp["phash"], fp["dhash"], fp["ahash"], json.dumps(fp["color"]), info["largura"], info["altura"],
                      safe_label(label), product_id, family, source, name, emb.tobytes() if emb is not None else None, S.now()))
    return {"ok": True, "duplicada": False, "image_id": cur.lastrowid, "info": info}


def search(db, data_dir: Path, raw: bytes, crop: dict | None = None, family: str | None = None, limit: int = 20,
           settings: dict | None = None) -> dict:
    """Busca local. A imagem consultada NÃO é gravada nem enviada a nenhum serviço."""
    S.ensure(db)
    img, info = load(raw, crop)
    q = {**fingerprints(img), "sha256": info["sha256"] if not crop else None}
    emb = embedding(img, data_dir) if (settings or {}).get("modelos_opcionais") else None
    res = []
    for r in db.query("SELECT * FROM product_images"):
        c = {**r, "color": json.loads(r["color"] or "[]")}
        cls, sim, why = classify(q, c, bool(family and r.get("family") == family))
        if emb is not None and r.get("embedding"):
            e2 = np.frombuffer(r["embedding"], np.float32)
            if e2.shape == emb.shape:
                cos = float(emb @ e2)
                why.append(f"embedding (nível avançado, local): cosseno {cos:.2f}")
                if cls in CLASSES[4:] and cos >= 0.85:
                    cls = CLASSES[2]
        if cls == CLASSES[5] and sim < 0.55:
            continue
        res.append({"image_id": r["image_id"], "classe": cls, "similaridade": sim, "motivos": why, "rotulo": r["label"],
                    "product_id": r["product_id"], "familia": r["family"], "fonte": r["source"], "miniatura": f"/api/suite/imagem/{r['image_id']}.jpg"})
    order = {c: i for i, c in enumerate(CLASSES)}
    res.sort(key=lambda x: (order[x["classe"]], -x["similaridade"]))
    dups = [x for x in res if x["classe"] in CLASSES[:2]]
    return {"consulta": {**info, "recorte": crop or None, "gravada": False}, "resultados": res[:limit], "duplicatas": dups,
            "catalogo_total": db.query("SELECT COUNT(*) AS n FROM product_images")[0]["n"], "aviso": WARNING,
            "classes": CLASSES, "nivel": "avançado + básico" if emb is not None else "básico (local)",
            "nota_similaridade": "Similaridade 0–1 combina hashes e cores; não é probabilidade de ser o mesmo produto."}


def compare(raw_a: bytes, raw_b: bytes) -> dict:
    a, ia = load(raw_a)
    b, ib = load(raw_b)
    fa, fb = {**fingerprints(a), "sha256": ia["sha256"]}, {**fingerprints(b), "sha256": ib["sha256"]}
    cls, sim, why = classify(fa, fb, False)
    return {"classe": cls, "similaridade": sim, "motivos": why, "aviso": WARNING}


def external_links(public_url: str | None = None) -> dict:
    """Busca reversa ASSISTIDA. Com URL pública, links prontos; sem URL (imagem privada), apenas as páginas de envio
    manual — o usuário decide se e onde envia. O GPI não envia a imagem nem lê os resultados."""
    base = [{"servico": "Google Lens", "abrir": "https://lens.google.com/"},
            {"servico": "TinEye", "abrir": "https://tineye.com/"},
            {"servico": "Yandex Imagens", "abrir": "https://yandex.com/images/"}]
    if public_url:
        u = quote(public_url, safe="")
        base[0]["por_url"] = f"https://lens.google.com/uploadbyurl?url={u}"
        base[1]["por_url"] = f"https://tineye.com/search?url={u}"
        base[2]["por_url"] = f"https://yandex.com/images/search?rpt=imageview&url={u}"
    return {"servicos": base, "regras": ["O GPI apenas abre a página no seu navegador; não faz upload automático.",
                                          "Os resultados externos não são lidos nem raspados pelo GPI.",
                                          "Imagens enviadas por você ficam somente neste computador, a menos que você mesmo as envie."]}
