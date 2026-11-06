"""ImportYeti — provedor OPCIONAL, desligado por padrão.

Documentação pública (data.importyeti.com/v1.0): cabeçalho `IYApiKey`. Só `GET /v1.0/database-updated` é gratuito; as
demais consultas consomem créditos pagos (custos por endpoint não documentados → todas tratadas como pagas). Cobertura:
registros de importação dos EUA (e México em parte). Nada aqui é necessário para o GPI funcionar.

Controle de créditos: consulta paga só com (1) chave configurada, (2) 'sem custos externos' DESLIGADO, (3) autorização
explícita do usuário para a consulta e (4) orçamento restante ≥ custo máximo informado. Caso contrário, nenhuma requisição
é feita e a resposta é a mensagem padrão."""
from __future__ import annotations

import urllib.parse

from . import store as S

BASE = "https://data.importyeti.com/v1.0"
NAME = "importyeti"
BLOCKED = "Consulta detalhada indisponível: créditos não autorizados ou insuficientes."
PAID = {"company_search": "/company/search", "company": "/company/{slug}", "supplier_search": "/supplier/search", "bol": "/bol/{number}"}


def _key(creds) -> str | None:
    try:
        return (creds.get(NAME) or {}).get("api_key") or None
    except Exception:  # noqa: BLE001
        return None


def spent(db) -> float:
    S.ensure(db)
    return float(db.query("SELECT COALESCE(SUM(cost), 0) AS c FROM provider_usage WHERE provider = ?", (NAME,))[0]["c"])


def status(db, creds, settings: dict) -> dict:
    last = db.query("SELECT * FROM provider_usage WHERE provider = ? ORDER BY id DESC LIMIT 1", (NAME,))
    budget = float(settings.get("orcamento_creditos") or 0)
    return {"provedor": "ImportYeti", "configurado": bool(_key(creds)), "gratuito": ["database-updated (data da última atualização)"],
            "pago": list(PAID), "sem_custos_externos": bool(settings.get("sem_custos")), "orcamento": budget, "gasto": spent(db),
            "restante": max(0.0, budget - spent(db)), "creditos_informados_pela_api": last[0]["credits_remaining"] if last else None,
            "estado": "desligado (modo sem custos)" if settings.get("sem_custos") else "configurado" if _key(creds) else "sem chave",
            "capacidades": ["supplier_search", "shipment_search", "historical_data"], "cobertura": "importações dos EUA (registros de embarque)",
            "limitacoes": ["Não cobre importações brasileiras.", "Custos por endpoint não documentados publicamente."]}


def _log(db, endpoint, cost, remaining, ok, detail):
    db.execute("INSERT INTO provider_usage (provider, endpoint, cost, credits_remaining, at, ok, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (NAME, endpoint, cost or 0, remaining, S.now(), 1 if ok else 0, (detail or "")[:300]))


def database_updated(db, http, creds) -> dict:
    key = _key(creds)
    if not key:
        return {"ok": False, "mensagem": "Chave do ImportYeti não configurada (opcional)."}
    try:
        r = http.request_json(f"{BASE}/database-updated", headers={"IYApiKey": key}, ttl=3600, timeout=20)
        _log(db, "database-updated", 0, None, True, None)
        return {"ok": True, "resposta": r, "custo": 0}
    except Exception as e:  # noqa: BLE001
        _log(db, "database-updated", 0, None, False, type(e).__name__)
        return {"ok": False, "mensagem": f"Falha na consulta gratuita: {type(e).__name__}"}


def paid_query(db, http, creds, settings: dict, kind: str, params: dict, authorized: bool, max_cost: float) -> dict:
    """Nenhuma requisição é feita se qualquer condição de custo falhar."""
    S.ensure(db)
    if kind not in PAID:
        return {"ok": False, "mensagem": "consulta não suportada"}
    budget = float(settings.get("orcamento_creditos") or 0)
    remaining = budget - spent(db)
    if settings.get("sem_custos") or not authorized or not _key(creds) or max_cost <= 0 or remaining < max_cost:
        return {"ok": False, "bloqueada": True, "mensagem": BLOCKED, "requisicao_feita": False,
                "motivo": "modo sem custos externos ativo" if settings.get("sem_custos") else "sem autorização explícita" if not authorized
                else "chave não configurada" if not _key(creds) else "orçamento insuficiente"}
    path = PAID[kind]
    for k in ("slug", "number"):
        if "{" + k + "}" in path:
            v = str(params.pop(k, "")).strip()
            if not v:
                return {"ok": False, "mensagem": f"informe {k}"}
            path = path.replace("{" + k + "}", urllib.parse.quote(v, safe=""))
    qs = urllib.parse.urlencode({k: str(v)[:200] for k, v in params.items() if v not in (None, "")})
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    try:
        r = http.request_json(url, headers={"IYApiKey": _key(creds)}, ttl=86400, timeout=40)
    except Exception as e:  # noqa: BLE001
        _log(db, kind, 0, None, False, type(e).__name__)
        return {"ok": False, "mensagem": f"Falha na consulta: {type(e).__name__}"}
    cost = float((r or {}).get("requestCost") or 0) if isinstance(r, dict) else 0.0
    rem = (r or {}).get("creditsRemaining") if isinstance(r, dict) else None
    _log(db, kind, cost, rem, True, None)
    return {"ok": True, "custo": cost, "creditos_restantes": rem, "dados": (r or {}).get("data") if isinstance(r, dict) else r,
            "fonte": "ImportYeti (registros de importação dos EUA)", "nota": "Embarques não indicam capacidade produtiva."}


def shipments_from_response(data) -> list[dict]:
    """Converte registros de embarque da resposta (quando houver) para o formato de trade_shipments."""
    items = data if isinstance(data, list) else (data or {}).get("shipments") or (data or {}).get("bols") or []
    out = []
    for s in items if isinstance(items, list) else []:
        if not isinstance(s, dict):
            continue
        out.append({"doc_id": s.get("bol_number") or s.get("bol") or s.get("id"), "exporter_name": s.get("shipper_name") or s.get("supplier_name"),
                    "importer_name": s.get("consignee_name") or s.get("company_name"), "origin_country": s.get("shipper_country"),
                    "destination_country": s.get("consignee_country") or "US", "date": s.get("arrival_date") or s.get("date"),
                    "description": s.get("product_description") or s.get("description"), "weight_kg": s.get("weight_kg") or s.get("weight"),
                    "quantity": s.get("quantity"), "hs_code": s.get("hs_code"), "port": s.get("port_of_unlading")})
    return [x for x in out if x["exporter_name"] or x["importer_name"]]


def set_key(creds, key: str | None):
    if key:
        creds.set(NAME, {"api_key": key.strip()})
    else:
        try:
            creds.delete(NAME)
        except Exception:  # noqa: BLE001
            creds.set(NAME, {})

