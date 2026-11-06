"""v0.9.1 — correções finais (PR #18): coberturas comercial/contextual/técnica, classificação dos erros HTTP (GDELT 429,
proxy 403, timeout…), seleção de mercados, diagnóstico das integrações, Mercado Livre (OAuth, 401, 403, 429), chave de
cache. Respostas externas SIMULADAS (FakeHttp/FakeTransport); dados reais só no CI (scripts/real_targeted_research_v091.py)."""
from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta

import pytest

from gpi.connectors.http import HttpClient, HttpConfig, SourceError
from gpi.suite import diagnostics as DG
from gpi.suite import monitor as MON
from gpi.suite import research as RS
from gpi.suite import targeted as TG
from test_v091_targeted import ALL, TODAY, Creds, FakeHttp, db, fake_tokens, rctx, run, sctx  # noqa: F401


# ================================================================================================ 3. mercados
def test_main_market_brazil_only_brazilian_sources(db):                                       # 1
    fn, http = sctx(db)
    _, out, _ = run(db, "carregador GaN 65W", fn, mercado="BR")
    col = {(r["id"], r["mercado"]): r for r in out["coleta"]["resultados"]}
    assert col[("mercadolivre_busca", "BR")]["papel"] == "principal" and col[("google_ads_kp", "BR")]["estado"] == "com dados"
    assert col[("ebay", "US")]["estado"] == "não cobre o mercado" and "não é usada como substituta" in col[("ebay", "US")]["motivo"]
    assert not any("item_summary" in u for u in http.calls) and not any(k[1] == "US" and r["consulta_realizada"] for k, r in col.items())
    assert out["mercados"]["principal"] == "BR" and out["abas"]["marketplaces"]["mercado_principal"] == "BR"


def test_brazil_vs_us_comparison(db):                                                        # 2
    fn, http = sctx(db)
    _, out, _ = run(db, "carregador GaN 65W", fn, mercado="BR", comparacao=["US"], profundidade="completa")
    col = {(r["id"], r["mercado"]): r for r in out["coleta"]["resultados"]}
    assert col[("ebay", "US")]["papel"] == "comparativo" and col[("ebay", "US")]["estado"] == "com dados"
    assert col[("google_ads_kp", "US")]["papel"] == "comparativo"
    mk = out["abas"]["marketplaces"]
    assert mk["ultimos_30_dias"]["anuncios"] == 8 and mk["por_mercado"]["US"]["ultimos_30_dias"]["anuncios"] == 5   # US não vira BR
    com = out["coberturas"]["comercial"]["itens"]
    assert any(i.get("comparativo") and i["mercado"] == "US" for i in com)


def test_quick_comparison_is_not_queried(db):
    fn, http = sctx(db)
    _, out, _ = run(db, "carregador GaN 65W", fn, mercado="BR", comparacao=["US"], profundidade="rapida")
    assert not any(r["mercado"] == "US" and r["consulta_realizada"] for r in out["coleta"]["resultados"])
    assert "só na pesquisa completa" in out["mercados"]["cobertura"]["US"]["papel"]


def test_china_without_targeted_coverage(db):                                                # 3
    fn, http = sctx(db)
    _, out, j = run(db, "carregador GaN 65W", fn, mercado="CN")
    assert out["mercados"]["cobertura"]["CN"]["mensagem"] == TG.NO_COVERAGE
    st = next(s for s in j["steps"] if s["id"] == "coleta")
    assert st["estado"] == "indisponível" and TG.NO_COVERAGE in st["detalhe"] and not http.calls       # nada americano como substituto
    assert out["decisao"]["cor"] == "CINZA" and any(TG.NO_COVERAGE in x for x in out["resultado"]["limitacoes"])


def test_global_source_never_attributed_to_brazil(db):                                       # 4
    fn, _ = sctx(db)
    _, out, _ = run(db, "carregador GaN 65W", fn, mercado="BR", profundidade="completa")
    g = next(r for r in out["coleta"]["resultados"] if r["id"] == "gdelt")
    assert g["mercado"] == "GLOBAL" and g["papel"] == "global" and g["cobertura_geografica"].startswith("global")
    assert out["abas"]["demanda"]["noticias_gdelt"]["mercado"] == "GLOBAL"
    assert out["mercados"]["cobertura"]["GLOBAL"]["mensagem"].startswith("Fonte global")


# ================================================================================================ 2. erros HTTP
class FakeTransport:
    def __init__(self, seq):
        self.seq, self.n = list(seq), 0

    def send(self, method, url, headers, data, timeout, timing):
        self.n += 1
        x = self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
        if isinstance(x, BaseException):
            raise x
        return x


def client(tmp_path, seq, **cfg):
    sleeps = []
    c = HttpClient(tmp_path / "cache", HttpConfig(min_interval=0, **cfg), sleep=sleeps.append)
    c.transport = FakeTransport(seq)
    return c, sleeps


def test_gdelt_429_retry_after_bounded(tmp_path):                                           # 5
    c, sleeps = client(tmp_path, [(429, {"Retry-After": "7"}, b"Please limit requests to one every 5 seconds")], max_attempts=3)
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.gdeltproject.org/api/v2/doc/doc?query=x", ttl=0)
    d = DG.classify(e.value)
    assert e.value.cause == "limite" and d["estado"] == "Limite de requisições" and d["consulta"] == "limite de requisições"
    assert d["mensagem"].startswith("Limite de requisições atingido.")
    assert c.transport.n == 3 and all(6.9 <= s <= 9 for s in sleeps[:2])                  # Retry-After respeitado, tentativas limitadas


def test_proxy_tunnel_403_vs_server_403_vs_permission(tmp_path):                             # 6
    c, _ = client(tmp_path, [urllib.error.URLError("Tunnel connection failed: 403 Forbidden")])
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.gdeltproject.org/x", ttl=0)
    assert e.value.cause == "proxy" and e.value.kind == "bloqueada" and c.transport.n == 1   # não insiste, não contorna
    assert DG.classify(e.value)["estado"] == "Bloqueada pela rede"
    assert "Não foi possível estabelecer conexão com a fonte. Verifique as configurações de rede ou consulte a TI." in str(e.value)
    c, _ = client(tmp_path, [(403, {"X-Squid-Error": "ERR_ACCESS_DENIED 0"}, b"<html>squid</html>")])
    with pytest.raises(SourceError) as e:
        c.request_json("https://exemplo.org/x", ttl=0)
    assert e.value.cause == "proxy"
    c, _ = client(tmp_path, [(403, {}, b"forbidden")])
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.gdeltproject.org/x", ttl=0)
    assert e.value.cause == "recusado" and DG.classify(e.value)["estado"] == "Indisponível"
    c, _ = client(tmp_path, [(403, {}, b"forbidden")])
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.mercadolibre.com/sites/MLB/search?q=x", headers={"Authorization": "Bearer t"}, ttl=0)
    assert e.value.cause == "permissao" and DG.classify(e.value)["estado"] == "Permissão insuficiente"
    c, _ = client(tmp_path, [(401, {}, b"invalid token")])
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.mercadolibre.com/users/me", headers={"Authorization": "Bearer t"}, ttl=0)
    assert e.value.cause == "token" and DG.classify(e.value)["estado"] == "Token expirado"


def test_timeout_dns_and_server_errors(tmp_path):                                           # 7
    import socket
    c, _ = client(tmp_path, [TimeoutError("timed out")], max_attempts=2)
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.gdeltproject.org/x", ttl=0)
    assert e.value.cause == "timeout" and DG.classify(e.value)["mensagem"].startswith("Tempo de conexão esgotado")
    c, _ = client(tmp_path, [urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))])
    with pytest.raises(SourceError) as e:
        c.request_json("https://nao-existe.invalid/x", ttl=0)
    assert e.value.cause == "dns"
    c, _ = client(tmp_path, [(503, {}, b"down")], max_attempts=2)
    with pytest.raises(SourceError) as e:
        c.request_json("https://api.gdeltproject.org/x", ttl=0)
    assert e.value.cause == "servidor"


def test_gdelt_unavailable_does_not_block_full_research(db):
    http = FakeHttp(fail={"api.gdeltproject.org": SourceError("Limite de requisições atingido. HTTP 429", "limite", status=429, cause="limite")})
    fn, _ = sctx(db, http)
    _, out, j = run(db, "carregador GaN 65W", fn, profundidade="completa")
    g = next(r for r in out["coleta"]["resultados"] if r["id"] == "gdelt")
    assert g["estado"] == "limite de requisições" and g["motivo"].startswith("Limite de requisições atingido")
    assert out["coberturas"]["comercial"]["n"] >= 2 and out["decisao"]["cor"] == "VERDE"        # demais fontes seguem


# ================================================================================================ 5. Mercado Livre
def test_mercadolivre_without_oauth(db):                                                     # 8
    fn, http = sctx(db, creds={k: v for k, v in ALL.items() if k != "mercadolivre"})
    _, out, _ = run(db, "carregador GaN 65W", fn)
    ml = next(r for r in out["coleta"]["resultados"] if r["id"] == "mercadolivre_busca")
    assert ml["estado"] == "não autorizada" and ml["central"] == "#integracoes/mercadolivre"
    assert any(a["link"] == "#integracoes/mercadolivre" and "abrir Central de Integrações" in a["texto"] for a in out["resultado"]["proximas_acoes"])


def test_mercadolivre_expired_token_is_refreshed_once(db, monkeypatch):                     # 9
    import gpi.integrations.registry as reg
    calls = {"tok": 0}

    def tok(http, creds):
        calls["tok"] += 1
        return "novo" if creds.get("mercadolivre").get("expires_at") == "0" else "velho"
    monkeypatch.setattr(reg, "ml_token", tok)

    class H(FakeHttp):
        def request_json(self, url, method="GET", **kw):
            if "MLB/search" in url and kw.get("headers", {}).get("Authorization") == "Bearer velho":
                self.calls.append(url)
                raise SourceError("credencial recusada (HTTP 401)", "restrita", status=401, cause="token")
            return super().request_json(url, method, **kw)
    creds = {**ALL, "mercadolivre": {"access_token": "x", "refresh_token": "r"}}
    fn, http = sctx(db, H(), creds)
    _, out, _ = run(db, "carregador GaN 65W", fn)
    ml = next(r for r in out["coleta"]["resultados"] if r["id"] == "mercadolivre_busca")
    assert ml["estado"] == "com dados" and calls["tok"] == 2 and sum("MLB/search" in u for u in http.calls) == 2


def test_mercadolivre_403_and_429(db):
    fn, _ = sctx(db, FakeHttp(fail={"MLB/search": SourceError("permissão insuficiente (HTTP 403)", "restrita", status=403, cause="permissao")}))
    _, out, _ = run(db, "carregador GaN 65W", fn)
    ml = next(r for r in out["coleta"]["resultados"] if r["id"] == "mercadolivre_busca")
    assert ml["estado"] == "não autorizada" and "permissões" in ml["acao"]
    fn, _ = sctx(db, FakeHttp(fail={"MLB/search": SourceError("Limite de requisições atingido. HTTP 429", "limite", status=429, cause="limite")}))
    _, out, _ = run(db, "aspirador robô", fn)
    ml = next(r for r in out["coleta"]["resultados"] if r["id"] == "mercadolivre_busca")
    assert ml["estado"] == "limite de requisições"


class Store:
    def __init__(self, db):
        self.db, self.r = db, {}

    def load_result(self, n):
        return self.r.get(n)

    def save_result(self, n, p):
        self.r[n] = p


class Sync:
    def __init__(self, db, http, creds):
        self.store, self.http, self.creds = Store(db), http, creds


def test_mercadolivre_valid_preview_not_persisted(db):                                       # 10
    s = Sync(db, FakeHttp(), Creds(ALL))
    r = DG.ml_search_preview(s, "Fritadeira elétrica", 5)
    it = r["itens"][0]
    assert r["ok"] and not r["gravado"] and {"produto", "titulo", "preco_anunciado", "moeda", "marketplace", "id", "link", "coletado_em", "caracteristicas"} <= set(it)
    assert it["caracteristicas"].get("BRAND") or it["caracteristicas"].get("marca")
    assert not db.query("SELECT 1 FROM market_listings") and any("não é preço de venda" in a for a in r["avisos"])


def test_integration_diagnostics_two_step_mercadolivre(db):
    class H(FakeHttp):
        def request_json(self, url, method="GET", **kw):
            self.calls.append(url)
            if "users/me" in url:
                return {"id": 1, "site_id": "MLB"}
            if "MLB/search" in url:
                raise SourceError("permissão insuficiente (HTTP 403)", "restrita", status=403, cause="permissao")
            return super().request_json(url, method, **kw)
    s = Sync(db, H(), Creds(ALL))
    r = DG.test(db, s, {}, "mercadolivre")
    assert r["estado"] == "Autorizada" and r["permissoes"] == ["leitura da conta"]               # credencial ≠ permissão de busca
    assert "DevCenter" in r["acao"] and [e["ok"] for e in r["etapas"]] == [True, False]
    rows = {x["id"]: x for x in DG.rows(db, s, {})}
    assert rows["mercadolivre"]["estado"] == "Autorizada" and rows["youtube"]["configuracao"] == "configurada"
    assert DG.test(db, Sync(db, FakeHttp(), Creds({})), {}, "ebay")["estado"] == "Não configurada"
    assert set(DG.STATES) >= {"Não configurada", "Funcional sem resultados", "Token expirado", "Bloqueada pela rede", "Limite de requisições"}


# ================================================================================================ 1. coberturas
def test_commercial_vs_contextual_coverage(tmp_path, db):                                    # 11
    from test_v091_suite import img
    from gpi.suite import visual as V
    V.add_to_catalog(db, tmp_path, img(), "carregador", "charger+gan:65w", "charger+gan")
    fn, _ = sctx(db, creds={})
    _, out, _ = run(db, "carregador GaN 65W", fn)
    c = out["coberturas"]
    assert c["comercial"]["n"] == 0 and c["contextual"]["n"] >= 1 and c["confianca"]["nivel"] == "baixa"
    assert out["decisao"]["cor"] == "CINZA" and out["mensagem_final"] == RS.INSUFFICIENT and not out["conclusiva"]


def test_technical_coverage(db):                                                             # 12
    from test_v091_suite import SHIP_CSV
    from gpi.suite import suppliers as SP
    SP.import_shipments(db, SHIP_CSV.encode(), "e.csv")
    fn, _ = sctx(db, creds={})
    _, out, _ = run(db, "carregador GaN 65W", fn)
    t = {i["indicador"] for i in out["coberturas"]["tecnica"]["itens"]}
    assert {"identificação técnica confirmada", "família", "variante", "especificações explícitas", "fornecedores candidatos"} <= t
    assert out["decisao"]["cor"] == "CINZA"                                                   # fornecedores ≠ demanda


def test_cache_key_by_market_and_product(db):                                                # 13 14
    fn, http = sctx(db)
    run(db, "carregador GaN 65W", fn, mercado="BR")
    n = len(http.calls)
    _, out, _ = run(db, "carregador GaN 65W", fn, mercado="US")                               # outro mercado: não reaproveita BR
    us = next(r for r in out["coleta"]["resultados"] if r["id"] == "google_ads_kp")
    assert us["mercado"] == "US" and us["estado"] == "com dados" and len(http.calls) > n
    n = len(http.calls)
    _, out, _ = run(db, "aspirador robô", fn, mercado="BR")                                   # outro produto/termo
    assert next(r for r in out["coleta"]["resultados"] if r["id"] == "google_ads_kp")["estado"] != "cache válido" and len(http.calls) > n
    assert TG.cache_key("ebay", "US", "en", "x", "p1") != TG.cache_key("ebay", "US", "en", "x", "p2")
    assert TG.cache_key("google_ads_kp", "BR", "pt", "x", None) != TG.cache_key("google_ads_kp", "US", "pt", "x", None)
    keys = db.query("SELECT DISTINCT cache_key FROM research_source_runs WHERE cache_key IS NOT NULL")
    assert len(keys) >= 4


def test_forced_update_respects_permissions(db):                                             # 15
    fn, http = sctx(db, creds={"google_ads": {"refresh_token": "r", "customer_id": "1"}})
    run(db, "carregador GaN 65W", fn)
    db.execute("UPDATE research_source_runs SET at = ?", ((datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"),))
    _, out, _ = run(db, "carregador GaN 65W", fn, atualizar=True)
    col = {r["id"]: r for r in out["coleta"]["resultados"]}
    assert col["google_ads_kp"]["consulta_realizada"] and col["mercadolivre_busca"]["estado"] == "não autorizada"
    assert not any("MLB/search" in u for u in http.calls)


def test_schema_migration_adds_cache_columns(tmp_path):
    from gpi.db import Database
    d = Database(tmp_path / "o.sqlite")
    d.execute(TG.RUNS_SQL)
    d.execute("INSERT INTO research_source_runs (source, market, query_norm, at, status) VALUES ('ebay', 'US', 'x', '2026-01-01T00:00:00', 'com dados')")
    TG.ensure(d)
    cols = {r["name"] for r in d.query("PRAGMA table_info(research_source_runs)")}
    assert {"cache_key", "lang", "product_id", "params"} <= cols and d.query("SELECT COUNT(*) AS n FROM research_source_runs")[0]["n"] == 1


def test_quick_full_insufficient_monitoring_export(db):                                      # 16–20
    import io as _io
    from openpyxl import load_workbook
    from gpi.suite import export as EX
    fn, _ = sctx(db)
    rid, out, _ = run(db, "carregador GaN 65W", fn, profundidade="completa", mercado="BR", comparacao=["US"])
    assert out["resultado"]["classificacao"] == "VERDE" and out["resultado"]["confianca"]["nivel"] == "alta"
    wb = load_workbook(_io.BytesIO(EX.xlsx("pesquisa", out, "x")))
    assert {"Coberturas", "Fontes e cobertura"} <= set(wb.sheetnames)
    assert EX.pdf("pesquisa", out, "x")[:5] == b"%PDF-"
    m = MON.from_research(db, out, rid)
    assert m["parametros"]["mercado"] == "BR" and m["semanal"]


def test_dossier_and_research_regression_without_connectors(db):                            # 21 (resumo)
    _, out, j = run(db, "carregador GaN 65W", None)
    assert j["progresso"]["pct"] == 100 and out["abas"]["visao_geral"]["produto"] == "Carregador GaN 65W"
    assert out["coberturas"]["tecnica"]["n"] >= 3 and out["resultado"]["classificacao"] == "CINZA"

