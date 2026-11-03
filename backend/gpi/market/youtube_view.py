"""
YouTube Intelligence (v0.6.1): leitura DIRETA dos vídeos armazenados e diagnóstico em 5 etapas.

Diagnóstico do problema relatado na v0.6: a fonte aparecia como "validada, 494 registros", mas a página
ficava vazia. Os 494 registros são VÍDEOS únicos guardados em `content_items` (source='youtube'); a página
lia apenas um resumo calculado pela análise pós-sincronização, que não roda quando a coleta é disparada
pelo botão "Sincronizar" da própria integração (coleta só daquela fonte). Agora a página lê o banco a cada
abertura. "Em dia (nada a coletar)" significa que as buscas da semana já foram feitas (política semanal) —
os vídeos existentes continuam visíveis.

Políticas do YouTube respeitadas: títulos e canais são atualizados ou excluídos em até 30 dias (job diário de
atualização + limpeza); estatísticas exibidas como publicadas, sem combinação com outras fontes.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime, timedelta

from ..connectors.http import SourceError

UNITS = {"search": 100, "videos": 1, "i18nRegions": 1}


def _names(db) -> dict:
    out = {}
    try:
        for r in db.query("SELECT product_id, canonical, category FROM catalog_products"):
            out[r["product_id"]] = (r["canonical"], r["category"])
    except Exception:  # noqa: BLE001
        pass
    for r in db.query("SELECT product_key, name_pt, name_en, category FROM products"):
        out.setdefault(r["product_key"], (r["name_pt"] or r["name_en"] or r["product_key"], r.get("category")))
    return out


def status(db, cfg: dict) -> dict:
    from ..connectors.content import YouTube
    today = date.today()
    v = db.query("SELECT COUNT(*) AS n, MIN(published_at) AS a, MAX(published_at) AS b, MAX(collected_at) AS c, "
                 "MAX(refreshed_at) AS r, COUNT(DISTINCT product_key) AS p FROM content_items WHERE source = 'youtube' AND kind = 'video'")[0]
    other = db.query("SELECT COUNT(*) AS n FROM content_items WHERE source = 'youtube' AND kind <> 'video'")[0]["n"]
    last_run = db.query("SELECT started_at FROM sync_runs ORDER BY id DESC LIMIT 1")
    new = 0
    if last_run:
        new = db.query("SELECT COUNT(*) AS n FROM content_items WHERE source = 'youtube' AND collected_at >= ?",
                       (last_run[0]["started_at"],))[0]["n"]
    st = db.query("SELECT state, message, last_success, validated FROM source_status WHERE source = 'youtube'")
    used = db.query("SELECT COALESCE(SUM(units), 0) AS u FROM api_quota WHERE provider = 'youtube' AND day = ?",
                    (today.isoformat(),))[0]["u"]
    limit = int(cfg.get("youtube_daily_units", 3000))
    nxt_week = today + timedelta(days=7 - today.weekday())
    return {"videos_armazenados": v["n"], "outros_itens": other, "produtos_com_videos": v["p"],
            "o_que_conta": "Cada registro é um VÍDEO único (identificador do YouTube), não uma observação histórica. "
                           "Visualizações e curtidas de cada vídeo são atualizadas no lugar.",
            "novos_na_ultima_sincronizacao": new, "ultima_coleta": v["c"], "ultima_atualizacao": v["r"],
            "periodo_publicacao": [v["a"], v["b"]], "pais_consulta": YouTube.REGION,
            "fonte": (st[0] if st else {"state": "não coletada"}),
            "cota_usada_hoje_estimada": used, "limite_diario_gpi": limit, "restante_no_limite_gpi": max(0, limit - used),
            "cota_aviso": "Unidades estimadas pelo GPI (busca = 100, detalhes de até 50 vídeos = 1). A cota real restante do "
                          "projeto Google não é informada pela API; consulte o Google Cloud Console.",
            "proxima_busca_elegivel": nxt_week.isoformat(), "proxima_atualizacao_estatisticas": (today + timedelta(days=1)).isoformat(),
            "politica": "Buscas novas: uma vez por semana por produto. Estatísticas: atualizadas diariamente para vídeos com mais "
                        "de 7 dias sem atualização. Vídeos não atualizados em 30 dias são excluídos (política do YouTube)."}


def videos(db, produto=None, categoria=None, q=None, dias=None, canal=None, limit: int = 500) -> dict:
    sql = ("SELECT item_id, title, author, published_at, product_key, query, metrics, url, refreshed_at, collected_at "
           "FROM content_items WHERE source = 'youtube' AND kind = 'video'")
    p = []
    if produto:
        sql += " AND (product_key = ? OR product_key LIKE ?)"
        p += [produto, produto + ":%"]
    if q:
        sql += " AND (LOWER(title) LIKE ? OR LOWER(query) LIKE ?)"
        p += [f"%{q.lower()}%"] * 2
    if canal:
        sql += " AND LOWER(author) LIKE ?"
        p.append(f"%{canal.lower()}%")
    if dias:
        sql += " AND published_at >= ?"
        p.append((date.today() - timedelta(days=int(dias))).isoformat())
    sql += " ORDER BY published_at DESC LIMIT ?"
    p.append(int(limit) * (3 if categoria else 1))
    names = _names(db)
    from ..connectors.content import YouTube
    out = []
    for r in db.query(sql, tuple(p)):
        nm, cat = names.get(r["product_key"] or "", (None, None))
        if categoria and cat != categoria:
            continue
        m = json.loads(r["metrics"] or "{}")
        out.append({"id": r["item_id"], "titulo": r["title"], "canal": r["author"], "publicado": r["published_at"],
                    "produto_id": r["product_key"], "produto": nm or r["query"] or "—", "categoria": cat,
                    "consulta": r["query"], "visualizacoes": m.get("viewCount"), "curtidas": m.get("likeCount"),
                    "comentarios": m.get("commentCount"), "tipos": m.get("tipos"), "url": r["url"],
                    "pais_consulta": YouTube.REGION, "atualizado": r["refreshed_at"]})
        if len(out) >= limit:
            break
    prods = sorted({(o["produto_id"], o["produto"]) for o in out if o["produto_id"]}, key=lambda x: x[1] or "")
    return {"videos": out, "total": len(out), "produtos": [{"id": a, "nome": b} for a, b in prods],
            "categorias": sorted({o["categoria"] for o in out if o["categoria"]})}


def diagnose(http, creds, cfg: dict, db, content) -> dict:
    """A autenticação · B pesquisa real · C detalhes · D persistência · E visualização. Custo estimado ~102 unidades;
    a pesquisa fica em cache por 24 h (repetir o diagnóstico não gasta outra busca)."""
    from ..connectors.content import YouTube
    key = (creds.get("youtube") or {}).get("api_key") if creds else None
    steps, units = [], 0

    def add(nome, ok, msg, **kw):
        steps.append({"etapa": nome, "ok": ok, "mensagem": msg, **kw})
    if not key:
        add("A — Autenticação", False, "informe a chave de API do YouTube")
        return {"etapas": steps, "estado": "nao_configurado", "unidades": 0}
    api = YouTube.API
    today = date.today().isoformat()

    def get(method, params, ttl=0, cost=1):
        nonlocal units
        url = api + method + "?" + urllib.parse.urlencode({**params, "key": key})
        before = http.stats.get("cache_hits", 0) if hasattr(http, "stats") else 0
        r = http.request_json(url, ttl=ttl, min_interval=0.2)
        if not hasattr(http, "stats") or http.stats.get("cache_hits", 0) == before:
            units += cost
            if content:
                content.quota_add("youtube", today, cost)
        return r
    try:
        r = get("i18nRegions", {"part": "snippet", "hl": "pt_BR"})
        add("A — Autenticação", "items" in r, f"chave aceita ({len(r.get('items', []))} regiões)")
    except SourceError as e:
        add("A — Autenticação", False, f"chave recusada: {e}")
        return {"etapas": steps, "estado": "erro", "unidades": units}
    q = "review carregador USB-C"
    try:
        s = get("search", {"part": "id", "type": "video", "q": q, "maxResults": 1, "regionCode": YouTube.REGION,
                           "relevanceLanguage": "pt"}, ttl=24 * 3600, cost=UNITS["search"])
        ids = [i["id"]["videoId"] for i in s.get("items", []) if isinstance(i.get("id"), dict) and i["id"].get("videoId")]
        add("B — Pesquisa", bool(ids), f"pesquisa '{q}' retornou {len(ids)} vídeo" if ids else "pesquisa sem resultados")
        if not ids:
            return {"etapas": steps, "estado": "sem_dados", "unidades": units}
    except SourceError as e:
        add("B — Pesquisa", False, f"pesquisa recusada: {e}" + (" (cota diária do projeto esgotada?)" if e.status == 403 else ""))
        return {"etapas": steps, "estado": "erro", "unidades": units}
    try:
        v = get("videos", {"part": "snippet,statistics", "id": ids[0]}, ttl=0, cost=UNITS["videos"])
        rows = YouTube.parse_videos(v, None, q)
        add("C — Detalhamento", bool(rows), f"'{rows[0]['title'][:70]}' — {rows[0]['metrics'].get('viewCount', '?')} visualizações"
            if rows else "vídeo sem detalhes")
    except SourceError as e:
        add("C — Detalhamento", False, f"detalhes recusados: {e}")
        return {"etapas": steps, "estado": "erro", "unidades": units}
    try:
        from ..products.catalog import Catalog
        m = Catalog(db, cfg).match("carregador usb-c")
        rows[0]["product_key"] = (m or {}).get("familia")
        content.upsert("youtube", rows, keep_product=True)
        back = db.query("SELECT item_id FROM content_items WHERE source = 'youtube' AND item_id = ?", (rows[0]["item_id"],))
        add("D — Persistência", bool(back), "vídeo gravado e lido de volta do banco" if back else "vídeo não encontrado após gravar")
    except Exception as e:  # noqa: BLE001
        add("D — Persistência", False, f"falha ao gravar: {e}")
        return {"etapas": steps, "estado": "erro", "unidades": units}
    vis = videos(db, limit=5000)
    shown = any(x["id"] == rows[0]["item_id"] for x in vis["videos"])
    add("E — Visualização", shown, f"vídeo visível na página YouTube Intelligence ({vis['total']} vídeos listados)" if shown
        else "o vídeo não aparece na listagem da página")
    return {"etapas": steps, "estado": "funcional" if shown else "erro", "unidades": units,
            "aviso": "Diagnóstico gasta ~102 unidades na primeira execução do dia; a pesquisa fica em cache por 24 h."}
