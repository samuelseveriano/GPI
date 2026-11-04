"""Gravação de sinais sociais: identificação do produto, retenção por fonte e cotas."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from ..market.store import now_iso

# Prazos de retenção padrão (dias), configuráveis em Configurações. Somente AGREGADOS são guardados
# (contagens, posições, somas de engajamento) e o link público de referência — nunca textos de
# publicações, nomes de usuários ou dados pessoais.
#  * YouTube: estatísticas podem ser guardadas por até 36 meses (política de métricas derivadas,
#    atualizada em 14/09/2026); títulos e descrições seguem a regra de 30 dias (não são guardados aqui).
#  * TikTok e Meta: as políticas pedem excluir dados que não são mais necessários e atender
#    pedidos de exclusão; o GPI adota 90 dias por padrão (escolha conservadora, configurável).
RETENTION_DEFAULT = {"tiktok": 90, "instagram": 90, "facebook": 90, "meta_ads": 90, "youtube": 1095, "reddit": 365}
PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "facebook": "Facebook", "meta_ads": "Biblioteca de Anúncios da Meta",
                  "youtube": "YouTube", "reddit": "Reddit"}
_CAMEL = re.compile(r"(?<=[a-zà-ú])(?=[A-ZÀ-Ú])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")


def retention_days(cfg: dict, platform: str) -> int:
    return int(cfg.get(f"retencao_dias_{platform}", RETENTION_DEFAULT.get(platform, 90)))


def hashtag_text(tag: str) -> str:
    t = tag.lstrip("#").replace("_", " ")
    return _CAMEL.sub(" ", t).strip()


def identify(db, cfg: dict, text: str, source: str, country: str | None, record: bool = True) -> tuple[str | None, dict]:
    """Produto do catálogo para uma hashtag/palavra-chave + intenção. Hashtags compostas
    ('miniprojetor', 'airfryer') são comparadas com os apelidos do catálogo sem espaços."""
    from ..products.catalog import Catalog
    from ..products.intent import classify
    cat = Catalog(db, cfg)
    words = hashtag_text(text)
    intent = classify(words)
    pid = cat.observe(words, source, country, intent["intencao"]) if record else (cat.match(words) or {}).get("familia")
    if not pid:
        compact = re.sub(r"[^a-z0-9à-ú]", "", words.lower())
        if len(compact) >= 5:
            if not hasattr(identify, "_cache") or identify._cache[0] is not db:
                rows = db.query("SELECT alias_norm, product_id FROM product_aliases WHERE lang <> 'zh'")
                identify._cache = (db, {re.sub(r"[^a-z0-9]", "", r["alias_norm"]): r["product_id"] for r in rows})
            pid = identify._cache[1].get(re.sub(r"[^a-z0-9]", "", compact.encode("ascii", "ignore").decode()) or compact)
    commercial = int(bool(pid) and intent["intencao"] not in ("noticia", "entretenimento"))
    return pid, {"intencao": intent["intencao"], "comercial": commercial}


def store(db, cfg, platform, country, item_type, item, ref_date, period, metric, value, unit, url=None, extra=None,
          pid=None, intent=None, commercial=0, today: date | None = None):
    today = today or date.today()
    keep = (today + timedelta(days=retention_days(cfg, platform))).isoformat()
    db.execute(
        "INSERT INTO social_observations (platform, country, item_type, item, ref_date, period, metric, value, unit, product_id,"
        " intent, commercial, url, extra, collected_at, retain_until) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(platform, country, item_type, item, ref_date, period, metric) DO UPDATE SET value = excluded.value,"
        " product_id = excluded.product_id, intent = excluded.intent, commercial = excluded.commercial, url = excluded.url,"
        " extra = excluded.extra, collected_at = excluded.collected_at, retain_until = excluded.retain_until",
        (platform, country, item_type, item[:200], ref_date, period, metric, float(value), unit, pid, intent, int(commercial),
         url, json.dumps(extra, ensure_ascii=False) if extra else None, now_iso(), keep))


def purge(db, today: date | None = None) -> dict:
    """Aplica os prazos de retenção (executado a cada análise) e limpa o controle de cota vencido."""
    today = today or date.today()
    n = db.execute("DELETE FROM social_observations WHERE retain_until IS NOT NULL AND retain_until < ?", (today.isoformat(),)).rowcount
    db.execute("DELETE FROM social_quota WHERE first_used < ?", ((today - timedelta(days=7)).isoformat(),))
    return {"removidas": n}


def quota_used(db, platform: str, today: date) -> set:
    return {r["item"] for r in db.query("SELECT item FROM social_quota WHERE platform = ? AND first_used >= ?",
                                        (platform, (today - timedelta(days=7)).isoformat()))}


def quota_add(db, platform: str, item: str, today: date):
    db.execute("INSERT OR IGNORE INTO social_quota (platform, item, first_used) VALUES (?, ?, ?)", (platform, item, today.isoformat()))
