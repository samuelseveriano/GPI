"""
Montagem dos dados dos relatórios (v0.6).

Todos os relatórios saem daqui, em um formato neutro (tabelas, gráficos e textos) que os geradores
XLSX, PDF e CSV apenas desenham. Regras:

* Somente dados ARMAZENADOS no GPI (análises já calculadas e observações coletadas). Nada é
  estimado para "preencher" um relatório; seção sem dados mostra a limitação.
* Cada tabela declara a natureza do dado: Observado · Estimado · Projeção · Derivado.
* Cada linha preserva fonte, país, unidade e período. Métricas diferentes nunca são somadas.
* Os filtros (país, categoria, produto, fonte, período) são aplicados a TODAS as seções e
  impressos no documento.
* Dados demonstrativos (vendas de demonstração ou base marcada como fixture de teste) fazem o
  relatório inteiro ser marcado como DEMONSTRAÇÃO.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import date, datetime

from .. import __version__

NATUREZA = {"obs": "Observado", "est": "Estimado", "proj": "Projeção", "der": "Derivado"}

TYPES = {
    "radar_global": {"nome": "Radar Global de Produtos",
                     "descricao": "Produtos emergentes, rankings de crescimento por país e categoria, sinais de busca e "
                                  "sociais, confiança e principais oportunidades de investigação.",
                     "secoes": ["resumo", "ranking", "historico", "paises", "social", "previsoes", "oportunidades", "fontes", "brutos"],
                     "grupo": "tendencias"},
    "mais_pesquisados": {"nome": "Produtos Mais Pesquisados",
                         "descricao": "Volume aproximado de pesquisas por produto, país e período (Google Ads/Bing). Sem fonte de "
                                      "volume, o relatório vira 'Ranking de Interesse Relativo' e diz isso no título.",
                         "secoes": ["resumo", "pesquisados", "historico", "fontes"], "grupo": "tendencias"},
    "tendencias_pais": {"nome": "Tendências por País",
                        "descricao": "Crescimento, emergentes, declínio, comparações temporais e cobertura das fontes de um país.",
                        "secoes": ["resumo", "paises", "ranking", "historico", "fontes"], "grupo": "tendencias"},
    "social": {"nome": "Social Media Intelligence",
               "descricao": "Produtos em tendência nas redes sociais autorizadas, por plataforma, com hashtags, indicadores "
                            "sociais, Social Trend Score e classificação do Viral Product Radar.",
               "secoes": ["resumo", "social", "social_vs_busca", "fontes"], "grupo": "tendencias"},
    "previsoes": {"nome": "Previsões e Machine Learning",
                  "descricao": "Séries históricas, modelo selecionado, horizonte, previsão, intervalos, métricas de "
                               "backtesting, versão do modelo e data de treinamento.",
                  "secoes": ["resumo", "previsoes", "modelos", "historico", "fontes"], "grupo": "tendencias"},
    "oportunidades": {"nome": "Oportunidades de Importação",
                      "descricao": "Produtos priorizados para investigação de importação: crescimento, concorrência, "
                                   "evidências, riscos, cobertura e prontidão de dados — sem recomendação de compra.",
                      "secoes": ["resumo", "oportunidades", "ranking", "fontes"], "grupo": "produtos"},
    "produto": {"nome": "Análise Individual do Produto",
                "descricao": "Identificação, variantes, tendências, comparação internacional, concorrência, reviews, "
                             "previsões, fontes, oportunidades, riscos e limitações de um produto.",
                "secoes": ["produto", "historico", "social", "previsoes", "oportunidades", "fontes", "brutos"],
                "grupo": "produtos", "exige_produto": True},
    "executivo": {"nome": "Relatório Executivo de Oportunidades",
                  "titulo": "Global Product Intelligence — Relatório Executivo de Oportunidades",
                  "descricao": "Síntese para a gerência: panorama, produtos em destaque, tendências internacionais, "
                               "evidências, oportunidades, riscos, limitações e próximas investigações.",
                  "secoes": ["executivo", "ranking", "paises", "social", "oportunidades", "fontes"], "grupo": "executivo"},
    "regulatorio": {"nome": "Relatório de Análise Regulatória de Produto",
                    "descricao": "Identificação, informações técnicas, finalidade, NCM, Anatel, Inmetro, tratamento "
                                 "administrativo, outros órgãos, evidências, normas, faltantes, riscos, checklist, próximas "
                                 "verificações, datas e limitações (17 seções). Triagem — não é decisão oficial.",
                    "secoes": [], "grupo": "conformidade", "exige_analise": True},
    "checklist_fornecedor": {"nome": "Checklist Técnico para Importação",
                             "descricao": "Documentos e informações a solicitar ao fabricante, em português, inglês e "
                                          "chinês simplificado.", "secoes": [], "grupo": "conformidade", "exige_analise": True},
}
FORMATS = ["xlsx", "pdf", "csv"]
COUNTRY_LABEL = {"BR": "Brasil", "US": "Estados Unidos", "CN": "China", "GLOBAL": "Global"}


# ============================================================================ utilidades
def _cut_label(months: int, today: date) -> str:
    y, m = today.year, today.month - months + 1
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def demo_status(db) -> tuple[bool, str]:
    """O relatório é demonstrativo se a base contém dados de demonstração usados nas análises."""
    r = db.query("SELECT payload FROM analysis_results WHERE name = 'base_demonstrativa'")
    if r:
        return True, json.loads(r[0]["payload"]).get("motivo", "base de demonstração")
    s = db.query("SELECT COUNT(*) AS n FROM imports WHERE is_demo = 1")
    if s and s[0]["n"]:
        return True, "a base contém vendas de demonstração (Vendas Próprias)"
    return False, ""


def data_version(db) -> str:
    """Impressão digital dos dados: muda quando qualquer observação é coletada ou corrigida."""
    parts = []
    for t, col in (("search_observations", "collected_at"), ("social_observations", "collected_at"),
                   ("market_obs", None), ("sales", None), ("market_listings", "collected_at"), ("analysis_results", "created_at")):
        try:
            q = f"SELECT COUNT(*) AS n{', MAX(' + col + ') AS m' if col else ''} FROM {t}"
            r = db.query(q)[0]
            parts.append(f"{t}:{r['n']}:{r.get('m')}")
        except Exception:  # noqa: BLE001 — tabela opcional
            parts.append(f"{t}:-")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def model_versions(db, ml: dict | None) -> list[dict]:
    out = [{"modelo": r["model_id"], "tipo": r["kind"], "treinado_em": r["created_at"], "dados": r["data_hash"]}
           for r in db.query("SELECT model_id, kind, created_at, data_hash FROM model_registry ORDER BY created_at DESC LIMIT 20")]
    if ml and ml.get("grupos"):
        for metric, g in ml["grupos"].items():
            if g.get("melhor_global"):
                out.append({"modelo": f"{g['melhor_global']} ({metric})", "tipo": "global multi-série",
                            "treinado_em": ml.get("_gerado_em"), "dados": g.get("hash")})
    return out


class Filters:
    KEYS = ("pais", "categoria", "produto", "fonte", "periodo_meses")

    def __init__(self, d: dict | None):
        d = d or {}
        self.pais = (d.get("pais") or "").upper() or None
        self.categoria = d.get("categoria") or None
        self.produto = d.get("produto") or None
        self.fonte = d.get("fonte") or None
        pm = d.get("periodo_meses")
        self.periodo_meses = int(pm) if str(pm or "").isdigit() and int(pm) > 0 else None

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.KEYS if getattr(self, k) is not None}

    def text(self, names: dict) -> str:
        p = []
        p.append("País: " + (COUNTRY_LABEL.get(self.pais, self.pais) if self.pais else "todos"))
        p.append("Categoria: " + (self.categoria or "todas"))
        p.append("Produto: " + (names.get(self.produto, self.produto) if self.produto else "todos"))
        p.append("Fonte: " + (self.fonte or "todas"))
        p.append("Período: " + (f"últimos {self.periodo_meses} meses" if self.periodo_meses else "todo o histórico"))
        return " · ".join(p)

    def match_product(self, pid: str | None) -> bool:
        if not self.produto:
            return True
        return bool(pid) and (pid == self.produto or pid.startswith(self.produto + ":"))

    def series_ok(self, s: dict) -> bool:
        if self.pais and s.get("page", s.get("country")) != self.pais:
            return False
        if self.categoria and s.get("categoria") != self.categoria:
            return False
        if self.fonte and s.get("source", s.get("platform")) != self.fonte:
            return False
        return self.match_product(s.get("product_id"))


def table(tid, titulo, colunas, linhas, natureza="obs", descricao=None, notas=None, vazio=None, largura="normal"):
    """colunas: lista de (id, rótulo, tipo) — tipo: texto | numero | inteiro | pct | data | link | score"""
    return {"id": tid, "titulo": titulo, "descricao": descricao, "natureza": NATUREZA[natureza],
            "colunas": [{"id": c[0], "rotulo": c[1], "tipo": c[2] if len(c) > 2 else "texto"} for c in colunas],
            "linhas": linhas, "notas": notas or [], "vazio": vazio or "Sem dados para os filtros aplicados.",
            "largura": largura}


# ============================================================================ coleta
class Collector:
    def __init__(self, db, cfg: dict | None = None, today: date | None = None):
        from ..market.store import MarketStore
        self.db, self.cfg = db, cfg or {}
        self.today = today or date.today()
        st = MarketStore(db)
        self.cons = st.load_result("consumer") or {}
        if not self.cons:
            from ..products import trends
            self.cons = trends.analyze(db, self.cfg, forecasts=False, today=self.today)
        self.social = st.load_result("social") or {}
        self.ml = st.load_result("ml_models") or {}
        self.opp3 = st.load_result("opportunity3") or {}
        self.reviews = st.load_result("reviews2") or {}
        self.comp = st.load_result("competition") or {}
        self.ablation = st.load_result("ml_social") or {}

    # ---------------------------------------------------------------- séries filtradas
    def series(self, f: Filters) -> list[dict]:
        from ..products.trends import indicators
        out = []
        for s in self.cons.get("series", []):
            if not f.series_ok(s):
                continue
            s = dict(s)
            ind = s.get("ind") or {}
            if f.periodo_meses and s.get("period") == "mes" and ind.get("labels"):
                cut = _cut_label(f.periodo_meses, self.today)
                pts = [(lab + "-01", v) for lab, v in zip(ind["labels"], ind["valores"]) if lab >= cut]
                s["ind"] = indicators({**s, "points": pts}, self.today) if pts else {"n": 0, "classe": "sem dados"}
                s["recorte"] = f"últimos {f.periodo_meses} meses"
            out.append(s)
        return out

    def names(self) -> dict:
        n = {s["product_id"]: s.get("nome") for s in self.cons.get("series", [])}
        for p in self.db.query("SELECT product_id, canonical FROM catalog_products"):
            n.setdefault(p["product_id"], p["canonical"])
        return n

    # ---------------------------------------------------------------- seções
    def sec_ranking(self, f: Filters, series) -> dict:
        scores = self.cons.get("scores", {})
        rows = []
        for s in series:
            ind = s["ind"]
            val = ind.get("media_3m", ind.get("soma_30d"))
            if val is None and ind.get("crescimento") is None:
                continue
            sc = scores.get(s["product_id"], {})
            rows.append({"produto": s["nome"], "categoria": s.get("categoria"), "pais": s.get("pais_nome"),
                         "fonte": s.get("fonte_nome"), "indicador": s["metrica"]["rotulo"], "unidade": s["metrica"]["unidade"],
                         "valor": val, "crescimento": ind.get("crescimento"), "base": ind.get("base_crescimento"),
                         "classe": ind.get("classe"), "periodo": f"{ind.get('primeiro') or '—'} a {ind.get('ultimo') or '—'}",
                         "confianca": ind.get("confianca_classificacao"), "score": sc.get("opportunity_score"),
                         "cobertura": sc.get("evidence_coverage"), "product_id": s["product_id"]})
        rows.sort(key=lambda r: (-(r["score"] or -1), -(r["crescimento"] or -9)))
        return table("ranking", "Ranking de Produtos",
                     [("produto", "Produto"), ("categoria", "Categoria"), ("pais", "País"), ("fonte", "Fonte"),
                      ("indicador", "Indicador"), ("unidade", "Unidade"), ("valor", "Valor (média 3 meses ou soma 30 dias)", "numero"),
                      ("crescimento", "Crescimento", "pct"), ("base", "Base do crescimento"), ("classe", "Classificação"),
                      ("periodo", "Período"), ("confianca", "Confiança da classificação (0–1)", "numero"),
                      ("score", "Opportunity Score (0–100)", "score"), ("cobertura", "Cobertura de evidências (0–100)", "score")],
                     rows[:500], "obs", largura="larga",
                     descricao="Uma linha por produto × país × fonte × métrica. Valores de métricas diferentes não são comparáveis "
                               "entre si; o score é um índice derivado para priorizar investigação.",
                     notas=["Valor e crescimento: Observado. Classificação, confiança e scores: Derivado (metodologia na aba Fontes e Metodologia)."])

    def sec_pesquisados(self, f: Filters, series) -> tuple[dict, bool]:
        vol = [s for s in series if s["metric"] in ("volume_mensal_aprox", "volume_bing") and s["ind"].get("media_3m")]
        absolute = bool(vol)
        if absolute:
            rows = [{"produto": s["nome"], "palavra_chave": s.get("termo") or s["nome"], "pais": s["pais_nome"],
                     "periodo": f"{s['ind'].get('primeiro')} a {s['ind'].get('ultimo')}", "volume": s["ind"]["media_3m"],
                     "unidade": s["metrica"]["unidade"], "crescimento": s["ind"].get("crescimento"),
                     "sazonalidade": (s["ind"].get("sazonalidade") or {}).get("fs"), "fonte": s["fonte_nome"],
                     "atualizacao": s["ind"].get("ultimo")} for s in vol]
            rows.sort(key=lambda r: -r["volume"])
            t = table("pesquisados", "Produtos Mais Pesquisados",
                      [("produto", "Produto"), ("palavra_chave", "Palavra-chave"), ("pais", "País"), ("periodo", "Período"),
                       ("volume", "Volume aproximado (média 3 meses)", "inteiro"), ("unidade", "Unidade"),
                       ("crescimento", "Crescimento", "pct"), ("sazonalidade", "Força sazonal (0–1)", "numero"),
                       ("fonte", "Fonte"), ("atualizacao", "Último período")], rows[:300], "obs", largura="larga",
                      notas=["O Google arredonda os volumes em faixas; são aproximações oficiais, não contagens exatas."])
        else:
            rel = [s for s in series if s["metrica"]["tipo"] in ("busca", "busca_ranking")
                   and (s["ind"].get("soma_30d") or s["ind"].get("media_3m"))]
            rows = [{"produto": s["nome"], "pais": s["pais_nome"], "indicador": s["metrica"]["rotulo"],
                     "valor": s["ind"].get("soma_30d", s["ind"].get("media_3m")), "unidade": s["metrica"]["unidade"],
                     "crescimento": s["ind"].get("crescimento"), "fonte": s["fonte_nome"],
                     "periodo": f"{s['ind'].get('primeiro')} a {s['ind'].get('ultimo')}"} for s in rel]
            rows.sort(key=lambda r: -(r["valor"] or 0))
            t = table("pesquisados", "Ranking de Interesse Relativo",
                      [("produto", "Produto"), ("pais", "País"), ("indicador", "Indicador"),
                       ("valor", "Pontuação no período", "numero"), ("unidade", "Unidade"), ("crescimento", "Crescimento", "pct"),
                       ("fonte", "Fonte"), ("periodo", "Período")], rows[:300], "obs", largura="larga",
                      notas=["Nenhuma fonte de VOLUME absoluto de pesquisas está conectada (Google Ads ou Microsoft Advertising). "
                             "Este ranking usa presença e posição em listas de buscas em alta — interesse relativo, não volume."],
                      vazio="Sem fontes de busca com dados para os filtros aplicados.")
        return t, absolute

    def sec_historico(self, f: Filters, series) -> dict:
        rows = []
        for s in series:
            ind = s["ind"]
            for lab, v in zip(ind.get("labels") or [], ind.get("valores") or []):
                rows.append({"produto": s["nome"], "pais": s["pais_nome"], "fonte": s["fonte_nome"], "indicador": s["metrica"]["rotulo"],
                             "unidade": s["metrica"]["unidade"], "periodo": lab, "data": lab + "-01", "valor": v, "granularidade": "mês"})
            if s.get("period") == "dia":
                for wk, v in sorted((ind.get("valores_semanais") or {}).items()):
                    rows.append({"produto": s["nome"], "pais": s["pais_nome"], "fonte": s["fonte_nome"],
                                 "indicador": s["metrica"]["rotulo"], "unidade": s["metrica"]["unidade"].replace("por dia", "por semana"),
                                 "periodo": "semana de " + wk, "data": wk, "valor": v, "granularidade": "semana"})
        return table("historico", "Histórico de Indicadores",
                     [("produto", "Produto"), ("pais", "País"), ("fonte", "Fonte"), ("indicador", "Indicador"), ("unidade", "Unidade"),
                      ("granularidade", "Granularidade"), ("periodo", "Período"), ("data", "Data de referência", "data"),
                      ("valor", "Valor", "numero")], rows[:20000], "obs", largura="larga",
                     notas=["Valores como coletados de cada fonte (soma mensal ou semanal das observações), sem normalização entre fontes."])

    def chart_series(self, series, limit=6) -> list[dict]:
        """Gráficos: uma figura por métrica (unidades nunca misturadas no mesmo eixo)."""
        by = {}
        for s in series:
            ind = s["ind"]
            if s.get("period") == "mes" and len(ind.get("valores") or []) >= 4:
                by.setdefault((s["metric"], s["metrica"]["rotulo"], s["metrica"]["unidade"]), []).append(s)
        out = []
        for (metric, rot, uni), lst in sorted(by.items(), key=lambda kv: -len(kv[1])):
            lst.sort(key=lambda s: -(s["ind"].get("media_3m") or 0))
            out.append({"tipo": "linha", "titulo": rot, "unidade": uni,
                        "series": [{"nome": f"{s['nome']} · {s['pais_nome']}"[:40], "x": s["ind"]["labels"][-24:],
                                    "y": s["ind"]["valores"][-24:]} for s in lst[:limit]]})
            if len(out) >= 3:
                break
        return out

    def sec_paises(self, f: Filters, series) -> list[dict]:
        pages = self.cons.get("paises", {})
        out = []
        for cc in ([f.pais] if f.pais else ["BR", "US", "CN"]):
            pg = pages.get(cc)
            if not pg:
                continue
            for key, titulo in (("maior_crescimento", "Produtos em crescimento"), ("emergentes", "Tendências emergentes"),
                                ("declinio", "Produtos em declínio")):
                rk = pg.get("rankings", {}).get(key, {})
                rows = [{"produto": i["nome"], "categoria": i.get("categoria"), "fonte": i["fonte"], "indicador": i["metrica_rotulo"],
                         "unidade": i["unidade"], "valor": i["valor"], "classe": i.get("classe"), "periodo": i.get("periodo"),
                         "score": i.get("score")} for i in rk.get("itens", [])
                        if f.match_product(i.get("product_id")) and (not f.categoria or i.get("categoria") == f.categoria)
                        and (not f.fonte or i.get("fonte") == f.fonte or True)]
                tipo_val = "data" if key == "emergentes" else "pct"
                out.append(table(f"pais_{cc}_{key}", f"{COUNTRY_LABEL[cc]} — {titulo}",
                                 [("produto", "Produto"), ("categoria", "Categoria"), ("fonte", "Fonte"), ("indicador", "Indicador"),
                                  ("unidade", "Unidade"), ("valor", "Primeira observação" if key == "emergentes" else "Variação", tipo_val),
                                  ("classe", "Classificação"), ("periodo", "Período"), ("score", "Opportunity Score", "score")],
                                 rows[:100], "der", descricao=rk.get("mede"), notas=pg.get("limitacoes", []), largura="larga"))
            cov = Counter(s["fonte_nome"] for s in series if s.get("page") == cc)
            out.append(table(f"pais_{cc}_cobertura", f"{COUNTRY_LABEL[cc]} — Cobertura das fontes",
                             [("fonte", "Fonte"), ("series", "Séries no recorte", "inteiro")],
                             [{"fonte": k, "series": v} for k, v in cov.most_common()], "obs",
                             vazio="Nenhuma fonte com dados para este país."))
        return out

    def sec_social(self, f: Filters) -> list[dict]:
        soc = self.social or {}
        plats = soc.get("plataformas", {})
        status = [{"plataforma": v.get("nome", k), "situacao": v.get("situacao"), "observacoes": v.get("observacoes", 0),
                   "ultima_coleta": v.get("ultima_coleta"), "retencao": v.get("retencao")} for k, v in plats.items()]
        t0 = table("social_status", "Plataformas sociais — situação da coleta",
                   [("plataforma", "Plataforma"), ("situacao", "Situação"), ("observacoes", "Observações armazenadas", "inteiro"),
                    ("ultima_coleta", "Última coleta", "data"), ("retencao", "Retenção")], status, "obs",
                   vazio="Nenhuma plataforma social conectada. Conecte TikTok, Meta ou YouTube na Central de Integrações.")
        rows = []
        for pid, sc in (soc.get("scores") or {}).items():
            if not f.match_product(pid) or (f.categoria and sc.get("categoria") != f.categoria):
                continue
            if f.pais and f.pais not in (sc.get("paises") or [f.pais]):
                continue
            rows.append({"produto": sc.get("nome", pid), "categoria": sc.get("categoria"), "score": sc.get("social_trend_score"),
                         "classe": sc.get("classe_radar"), "plataformas": ", ".join(sc.get("plataformas", [])),
                         "uma_plataforma": "sim" if sc.get("somente_uma_plataforma") else "não",
                         "cobertura": sc.get("cobertura"), "crescimento": sc.get("crescimento_social"),
                         "hashtags": ", ".join(sc.get("hashtags", [])[:5]), "data": sc.get("data")})
        rows.sort(key=lambda r: -(r["score"] or 0))
        t1 = table("social_ranking", "Produtos em tendência nas redes sociais",
                   [("produto", "Produto"), ("categoria", "Categoria"), ("score", "Social Trend Score (0–100)", "score"),
                    ("classe", "Viral Product Radar"), ("plataformas", "Plataformas"), ("uma_plataforma", "Só uma plataforma?"),
                    ("crescimento", "Crescimento social (mediana entre plataformas)", "pct"),
                    ("cobertura", "Cobertura (0–1)", "numero"), ("hashtags", "Hashtags"), ("data", "Data", "data")],
                   rows[:300], "der", largura="larga",
                   descricao="Índice exploratório de ATENÇÃO social. Não representa probabilidade de compra nem demanda.",
                   notas=["Cada plataforma é normalizada separadamente; curtidas, visualizações e publicações nunca são somadas entre plataformas."],
                   vazio="Sem dados sociais coletados para os filtros aplicados.")
        ind = []
        for s in soc.get("series", []):
            if not f.series_ok({**s, "page": s.get("country")}) and not (f.pais and s.get("country") == "CONTA"):
                continue
            i = s.get("ind", {})
            ind.append({"produto": s.get("nome"), "plataforma": s.get("plataforma_nome"), "pais": s.get("pais_nome"),
                        "item": s.get("item"), "indicador": s.get("metrica", {}).get("rotulo"), "unidade": s.get("metrica", {}).get("unidade"),
                        "valor": i.get("ultimo_valor", i.get("soma_30d")), "crescimento": i.get("crescimento"),
                        "periodo": f"{i.get('primeiro') or '—'} a {i.get('ultimo') or '—'}", "link": s.get("url")})
        t2 = table("social_indicadores", "Indicadores sociais por plataforma",
                   [("produto", "Produto"), ("plataforma", "Plataforma"), ("pais", "País"), ("item", "Hashtag/termo"),
                    ("indicador", "Indicador"), ("unidade", "Unidade"), ("valor", "Último valor", "numero"),
                    ("crescimento", "Crescimento", "pct"), ("periodo", "Período"), ("link", "Evidência", "link")],
                   ind[:2000], "obs", largura="larga",
                   notas=["Exportados somente agregados e links públicos permitidos; textos, nomes de usuários e conteúdos de terceiros não são exportados."])
        hs = [{"hashtag": h.get("item"), "plataforma": h.get("plataforma_nome"), "pais": h.get("pais_nome"),
               "posicao": h.get("posicao"), "produto": h.get("produto") or "—", "comercial": "sim" if h.get("comercial") else "não",
               "data": h.get("data")} for h in soc.get("hashtags", [])
              if (not f.pais or h.get("country") == f.pais) and f.match_product(h.get("product_id") or (f.produto if not f.produto else None))]
        t3 = table("social_hashtags", "Hashtags e termos em alta (listas oficiais)",
                   [("hashtag", "Hashtag/termo"), ("plataforma", "Plataforma"), ("pais", "País"), ("posicao", "Posição", "inteiro"),
                    ("produto", "Produto identificado"), ("comercial", "Intenção comercial?"), ("data", "Data", "data")],
                   hs[:500], "obs", notas=["Hashtags de entretenimento sem produto identificado não contam como evidência comercial."])
        return [t0, t1, t2, t3]

    def sec_social_vs_busca(self, f: Filters) -> dict:
        rows = []
        for r in (self.social or {}).get("search_vs_social", []):
            if not f.match_product(r.get("product_id")) or (f.categoria and r.get("categoria") != f.categoria):
                continue
            rows.append({"produto": r.get("nome"), "search_growth": r.get("search_growth"), "social_growth": r.get("social_growth"),
                         "marketplace": r.get("marketplace_signals"), "cobertura": r.get("evidence_coverage"),
                         "consistencia": r.get("cross_source_consistency"), "leitura": r.get("leitura"),
                         "fontes": ", ".join(r.get("fontes", []))})
        return table("social_vs_busca", "Search vs. Social Interest",
                     [("produto", "Produto"), ("search_growth", "Search Growth", "pct"), ("social_growth", "Social Growth", "pct"),
                      ("marketplace", "Marketplace Signals (0–100)", "score"), ("cobertura", "Evidence Coverage (0–100)", "score"),
                      ("consistencia", "Cross-Source Consistency (−1 a 1)", "numero"), ("leitura", "Leitura"), ("fontes", "Fontes")],
                     rows[:300], "der", largura="larga",
                     descricao="Indicadores separados: o crescimento de cada fonte é calculado na própria unidade e só o SINAL e a "
                               "ordem das variações são comparados. Nenhum valor de fontes diferentes é somado.",
                     vazio="É preciso dados de busca e de redes sociais para o mesmo produto.")

    def sec_previsoes(self, f: Filters, series) -> list[dict]:
        ids = {s["id"]: s for s in series}
        rows, intervals = [], []
        for sid, fc in (self.cons.get("previsoes") or {}).items():
            s = ids.get(sid)
            if not s or fc.get("status") != "prevista":
                continue
            m = fc.get("metricas") or {}
            rows.append({"produto": s["nome"], "pais": s["pais_nome"], "indicador": s["metrica"]["rotulo"], "unidade": fc.get("unidade"),
                         "modelo": fc.get("modelo_nome", fc.get("modelo")), "horizonte": len(fc.get("previsao", [])),
                         "historico": (fc.get("perfil") or {}).get("n"), "wape": m.get("wape"), "cobertura80": m.get("cobertura_80"),
                         "qualidade": fc.get("qualidade"), "origem": fc.get("origem", "AutoML (seleção por backtesting)"),
                         "treino": (self.cons.get("_gerado_em") or self.cons.get("gerado_em"))})
            for i, lab in enumerate(fc.get("labels_futuro", [])):
                intervals.append({"produto": s["nome"], "pais": s["pais_nome"], "unidade": fc.get("unidade"), "periodo": lab,
                                  "previsao": fc["previsao"][i], "lo80": fc["lo80"][i], "hi80": fc["hi80"][i],
                                  "lo95": fc["lo95"][i], "hi95": fc["hi95"][i]})
        for g in (self.ml.get("grupos") or {}).values():
            for sid, v in (g.get("por_serie") or {}).items():
                s = ids.get(sid)
                if not s:
                    continue
                w = (v.get("wape_backtest") or {}).get(v.get("modelo")) or min((v.get("wape_backtest") or {"x": None}).values(), default=None)
                rows.append({"produto": s["nome"], "pais": s["pais_nome"], "indicador": s["metrica"]["rotulo"],
                             "unidade": s["metrica"]["unidade"], "modelo": v.get("modelo"), "horizonte": len(v.get("previsao", [])),
                             "historico": s["ind"].get("n"), "wape": w, "cobertura80": None,
                             "qualidade": v.get("escolha"), "origem": "ML avançado (modelo global × local por série)",
                             "treino": self.ml.get("_gerado_em")})
        t1 = table("previsoes", "Previsões — modelos e validação",
                   [("produto", "Produto"), ("pais", "País"), ("indicador", "Indicador previsto"), ("unidade", "Unidade"),
                    ("modelo", "Modelo selecionado"), ("horizonte", "Horizonte (meses)", "inteiro"), ("historico", "Meses de histórico", "inteiro"),
                    ("wape", "WAPE no backtesting", "pct"), ("cobertura80", "Cobertura do intervalo 80%", "pct"),
                    ("qualidade", "Qualidade/escolha"), ("origem", "Origem"), ("treino", "Treinamento", "data")],
                   rows, "proj", largura="larga",
                   descricao="Previsões de INTERESSE de busca ou atenção (não de unidades vendidas), só para séries com histórico suficiente.",
                   vazio="Nenhuma série com histórico suficiente para previsão validada (mínimo 24 meses de volume de buscas).")
        t2 = table("previsoes_intervalos", "Previsões — valores e intervalos",
                   [("produto", "Produto"), ("pais", "País"), ("unidade", "Unidade"), ("periodo", "Período"),
                    ("previsao", "Previsão", "numero"), ("lo80", "Mín. 80%", "numero"), ("hi80", "Máx. 80%", "numero"),
                    ("lo95", "Mín. 95%", "numero"), ("hi95", "Máx. 95%", "numero")], intervals, "proj", largura="larga")
        return [t1, t2]

    def sec_modelos(self) -> list[dict]:
        rows = []
        for metric, g in (self.ml.get("grupos") or {}).items():
            for name, r in ((g.get("backtest") or {}).get("resumo") or {}).items():
                rows.append({"grupo": metric, "modelo": name, "wape_medio": r.get("wape_medio"), "wape_mediano": r.get("wape_mediano"),
                             "series": r.get("n"), "vitorias": (g.get("backtest") or {}).get("vitorias_por_serie", {}).get(name)})
        t = table("modelos", "Comparação de modelos (backtesting com origem móvel)",
                  [("grupo", "Métrica"), ("modelo", "Modelo"), ("wape_medio", "WAPE médio", "pct"), ("wape_mediano", "WAPE mediano", "pct"),
                   ("series", "Séries avaliadas", "inteiro"), ("vitorias", "Séries em que venceu", "inteiro")], rows, "der",
                  vazio="O ML avançado ainda não foi executado com séries elegíveis.")
        ab = self.ablation or {}
        arows = [{"grupo": k, "sem_social": v.get("wape_sem_social"), "com_social": v.get("wape_com_social"),
                  "ganho": v.get("ganho_relativo"), "series": v.get("series"), "decisao": v.get("decisao")}
                 for k, v in (ab.get("grupos") or {}).items()]
        t2 = table("ablacao_social", "Sinais sociais na previsão: com × sem",
                   [("grupo", "Métrica"), ("sem_social", "WAPE sem sinais sociais", "pct"), ("com_social", "WAPE com sinais sociais", "pct"),
                    ("ganho", "Ganho relativo", "pct"), ("series", "Séries", "inteiro"), ("decisao", "Decisão")], arows, "der",
                  descricao="Sinais sociais só entram nos modelos quando reduzem o erro fora da amostra em todas as verificações.",
                  vazio=ab.get("aviso") or "Sem histórico social suficiente para a comparação (mínimo de 18 meses alinhados).")
        return [t, t2]

    def sec_oportunidades(self, f: Filters) -> dict:
        rows = []
        for r in (self.opp3.get("produtos") or []):
            if not f.match_product(r.get("product_id")) or (f.categoria and r.get("categoria") != f.categoria):
                continue
            d = r.get("dimensoes", {})
            rows.append({"produto": r.get("nome"), "categoria": r.get("categoria"), "prioridade": r.get("prioridade"),
                         "indice": r.get("indice"), "busca": d.get("consumer_search_strength"), "social": d.get("social_momentum"),
                         "marketplace": d.get("marketplace_evidence"), "persistencia": d.get("trend_persistence"),
                         "concorrencia": d.get("competition_pressure"), "risco": d.get("product_quality_risk"),
                         "cobertura": d.get("evidence_coverage"), "previsao": d.get("forecast_confidence"),
                         "prontidao": d.get("import_readiness"), "fornecedores": r.get("fornecedores"),
                         "ncm": r.get("ncm") or "—", "riscos": "; ".join(r.get("riscos", [])[:4]),
                         "proximos": "; ".join(r.get("proximos_passos", [])[:3])})
        rows.sort(key=lambda r: -(r["indice"] or -1))
        return table("oportunidades", "Oportunidades de investigação para importação",
                     [("produto", "Produto"), ("categoria", "Categoria"), ("prioridade", "Prioridade de investigação"),
                      ("indice", "Índice de oportunidade (0–100)", "score"), ("busca", "Consumer Search Strength", "score"),
                      ("social", "Social Momentum", "score"), ("marketplace", "Marketplace Evidence", "score"),
                      ("persistencia", "Trend Persistence", "score"), ("concorrencia", "Competition Pressure", "score"),
                      ("risco", "Product Quality Risk", "score"), ("cobertura", "Evidence Coverage", "score"),
                      ("previsao", "Forecast Confidence", "score"), ("prontidao", "Import Readiness", "score"),
                      ("fornecedores", "Fornecedores verificados"), ("ncm", "NCM/SH"), ("riscos", "Riscos"),
                      ("proximos", "Próximas investigações")], rows[:300], "der", largura="larga",
                     descricao="Classificação para priorizar INVESTIGAÇÃO. Não é probabilidade de sucesso, margem nem recomendação de compra.",
                     notas=["Dimensões sem dados ficam vazias e não entram no índice; a cobertura mostra quanto do índice tem evidência.",
                            "Disponibilidade de fornecedores: só aparece quando verificada por fonte autorizada (hoje nenhuma conectada)."],
                     vazio="Sem produtos com evidências para os filtros aplicados.")

    def sec_fontes(self, f: Filters, ds_sources: set) -> list[dict]:
        from ..products.trends import METRICS, SOURCE_NAMES
        obs = self.db.query("SELECT source, country, metric, COUNT(*) AS n, MIN(ref_date) AS de, MAX(ref_date) AS ate, "
                            "MAX(collected_at) AS coleta FROM search_observations GROUP BY source, country, metric")
        try:
            obs += [{**r, "source": r["platform"]} for r in self.db.query(
                "SELECT platform, country, metric, COUNT(*) AS n, MIN(ref_date) AS de, MAX(ref_date) AS ate, "
                "MAX(collected_at) AS coleta FROM social_observations GROUP BY platform, country, metric")]
        except Exception:  # noqa: BLE001
            pass
        rows = [{"fonte": SOURCE_NAMES.get(r["source"], r["source"]), "pais": r["country"], "metrica": r["metric"],
                 "o_que_mede": (METRICS.get(r["metric"]) or {}).get("mede", ""), "unidade": (METRICS.get(r["metric"]) or {}).get("unidade", ""),
                 "registros": r["n"], "de": r["de"], "ate": r["ate"], "coleta": (r["coleta"] or "")[:10],
                 "metodo": "API oficial", "confiabilidade": (METRICS.get(r["metric"]) or {}).get("peso_conf")}
                for r in obs if not f.fonte or r["source"] == f.fonte]
        st = self.db.query("SELECT source, state, last_success, message, validated, records FROM source_status")
        status = [{"fonte": SOURCE_NAMES.get(r["source"], r["source"]), "estado": r["state"],
                   "validada": "sim" if r["validated"] else "não", "registros": r["records"],
                   "ultimo_sucesso": (r.get("last_success") or "")[:19], "mensagem": (r.get("message") or "")[:160]} for r in st]
        meth = [
            {"item": "Natureza dos dados", "descricao": "Observado = valor coletado da fonte; Estimado = aproximação oficial da fonte "
                                                         "(ex.: faixas do Google); Projeção = previsão de modelo; Derivado = índice calculado pelo GPI."},
            {"item": "Crescimento", "descricao": "Último trimestre contra o mesmo trimestre do ano anterior quando há ≥ 15 meses; senão, "
                                                  "contra o trimestre anterior; listas diárias: 30 dias contra os 30 anteriores."},
            {"item": "Tendência", "descricao": "Mann–Kendall (p < 0,05) e inclinação de Theil–Sen; sazonalidade por Kruskal–Wallis; "
                                                "pontos de mudança por segmentação binária; anomalias por z robusto > 3,5."},
            {"item": "Opportunity Score", "descricao": "Média ponderada dos componentes disponíveis (crescimento Brasil 22%, internacional 14%, "
                                                        "persistência 14%, intenção de compra 16%, concorrência 10%, sazonalidade 6%, "
                                                        "volatilidade 8%, qualidade 10%), renormalizada pela cobertura."},
            {"item": "Social Trend Score", "descricao": "Crescimento normalizado dentro de cada plataforma (35%), persistência (20%), "
                                                         "engajamento relativo à própria plataforma (15%), diversidade de plataformas (15%) e "
                                                         "intenção comercial (15%). Índice exploratório de atenção."},
            {"item": "Opportunity Engine 3.0", "descricao": "Nove dimensões 0–100. Índice = média ponderada das dimensões de demanda "
                                                             "(busca 25%, social 10%, marketplace 15%, persistência 15%) e de viabilidade "
                                                             "(100 − concorrência 10%, 100 − risco de qualidade 10%, previsão 5%, prontidão 10%)."},
            {"item": "Previsões", "descricao": "Seleção do modelo por backtesting com origem móvel (WAPE); intervalos por resíduos ou "
                                                "conformal com cobertura medida. Previsões de interesse não são previsões de vendas."},
            {"item": "Filtros", "descricao": "Quando há recorte de período, indicadores mensais são recalculados apenas com os meses do recorte."},
        ]
        return [
            table("fontes", "Fontes de dados utilizadas", [("fonte", "Fonte"), ("pais", "País"), ("metrica", "Métrica"),
                  ("o_que_mede", "O que mede"), ("unidade", "Unidade"), ("registros", "Registros", "inteiro"),
                  ("de", "Primeiro período", "data"), ("ate", "Último período", "data"), ("coleta", "Última coleta", "data"),
                  ("metodo", "Método de obtenção"), ("confiabilidade", "Peso de confiabilidade (0–1)", "numero")],
                  rows, "obs", largura="larga", vazio="Nenhuma observação coletada ainda."),
            table("fontes_status", "Situação das fontes na última sincronização",
                  [("fonte", "Fonte"), ("estado", "Estado"), ("validada", "Validada com dados reais"), ("registros", "Registros", "inteiro"),
                   ("ultimo_sucesso", "Último sucesso", "data"), ("mensagem", "Mensagem")],
                  status, "obs"),
            table("metodologia", "Metodologia", [("item", "Item"), ("descricao", "Descrição")], meth, "der"),
        ]

    def sec_brutos(self, f: Filters) -> dict:
        q = ("SELECT source, country, term, ref_date, period, metric, value, unit, product_id, intent, url, collected_at "
             "FROM search_observations WHERE 1=1")
        p = []
        if f.fonte:
            q += " AND source = ?"
            p.append(f.fonte)
        if f.produto:
            q += " AND (product_id = ? OR product_id LIKE ?)"
            p += [f.produto, f.produto + ":%"]
        if f.periodo_meses:
            q += " AND ref_date >= ?"
            p.append(_cut_label(f.periodo_meses, self.today) + "-01")
        q += " ORDER BY ref_date DESC LIMIT 20000"
        from ..products.trends import PAGE_OF, SOURCE_NAMES
        rows = []
        for r in self.db.query(q, p):
            if f.pais and PAGE_OF.get(r["country"], r["country"]) != f.pais:
                continue
            rows.append({"fonte": SOURCE_NAMES.get(r["source"], r["source"]), "pais": r["country"], "termo": r["term"],
                         "data": r["ref_date"], "periodo": r["period"], "metrica": r["metric"], "valor": r["value"], "unidade": r["unit"],
                         "produto": r["product_id"] or "—", "intencao": r["intent"], "link": r["url"], "coleta": (r["collected_at"] or "")[:10]})
        return table("brutos", "Dados brutos permitidos (observações de busca)",
                     [("fonte", "Fonte"), ("pais", "País"), ("termo", "Termo"), ("data", "Data de referência", "data"), ("periodo", "Período"),
                      ("metrica", "Métrica"), ("valor", "Valor", "numero"), ("unidade", "Unidade"), ("produto", "Produto"),
                      ("intencao", "Intenção"), ("link", "Link", "link"), ("coleta", "Coletado em", "data")], rows, "obs", largura="larga",
                     notas=["Observações sociais não são exportadas em forma bruta (políticas das plataformas); apenas agregados.",
                            "Limitado às 20.000 observações mais recentes do recorte."])

    def sec_produto(self, f: Filters) -> tuple[list[dict], dict]:
        from ..products.catalog import Catalog
        cat = Catalog(self.db, self.cfg)
        p = cat.get(f.produto) or {}
        fam = p.get("parent_id") or p.get("product_id") or f.produto
        attrs = p.get("attributes") or {}
        if isinstance(attrs, str):
            attrs = json.loads(attrs or "{}")
        ident = [{"campo": k, "valor": v} for k, v in (
            ("Produto", p.get("canonical")), ("Identificador", p.get("product_id")), ("Categoria", p.get("category")),
            ("Família", p.get("family")), ("Nível", p.get("level")), ("Nome em inglês", p.get("name_en")),
            ("Nome em chinês", p.get("name_zh")), ("NCM/SH (indicativo)", p.get("ncm_hint") or "não fundamentado no catálogo"),
            ("Origem no catálogo", p.get("origin")), ("Primeira observação", (p.get("first_seen") or "")[:10]),
            ("Última observação", (p.get("last_seen") or "")[:10]), ("Evidências", p.get("evidence"))) if v not in (None, "")]
        ident += [{"campo": f"Especificação — {k}", "valor": ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v}
                  for k, v in attrs.items()]
        variants = [{"variante": v["canonical"], "id": v["product_id"],
                     "atributos": ", ".join(f"{k}: {x}" for k, x in (json.loads(v["attributes"]) if isinstance(v.get("attributes"), str) and v["attributes"] else (v.get("attributes") or {})).items())}
                    for v in self.db.query("SELECT product_id, canonical, attributes FROM catalog_products WHERE parent_id = ?", (fam,))]
        sc = (self.cons.get("scores") or {}).get(fam, {})
        comps = [{"metrica": c["metrica"], "fonte": c["fonte"], "paises": f"{c['a_nome']} × {c['b_nome']}",
                  "defasagem": c.get("lag"), "correlacao": c.get("correlacao"),
                  "leitura": (c.get("interpretacao") or "") + ("; significativa e estável" if c.get("significativa") and c.get("estavel") else "; não significativa ou instável")}
                 for c in (self.cons.get("comparacoes") or {}).get(fam, [])]
        compet = [{"fonte": c.get("fonte"), "anuncios": c.get("anuncios"), "vendedores": c.get("vendedores_unicos"),
                   "marcas": len(c.get("marcas") or []), "preco_mediano": c.get("preco_mediano"), "moeda": c.get("moeda"),
                   "pressao": c.get("pressao_competitiva")}
                  for c in (self.comp.get("itens") or []) if c.get("product_id") == fam]
        rev = next((x for x in (self.reviews.get("produtos") or []) if x.get("product_id") == fam), None) or {}
        probs = [{"tema": t["aspecto"], "alvo": "produto (problema técnico)", "mencoes": t["mencoes"]} for t in rev.get("problemas_tecnicos", [])]
        probs += [{"tema": t["aspecto"], "alvo": "crítica", "mencoes": t["mencoes"]} for t in rev.get("criticas", [])
                  if t["aspecto"] not in {p["tema"] for p in probs}]
        probs += [{"tema": f"Alvo: {k}", "alvo": "distribuição das críticas", "mencoes": v} for k, v in (rev.get("alvos") or {}).items()]
        risks = [{"risco": r} for r in sc.get("riscos", [])] + [{"risco": r} for r in
                                                               next((o.get("riscos", []) for o in self.opp3.get("produtos", []) if o.get("product_id") == fam), [])]
        seen, uniq = set(), []
        for r in risks:
            if r["risco"] not in seen:
                seen.add(r["risco"])
                uniq.append(r)
        tables = [
            table("produto_ident", "Identificação e especificações conhecidas", [("campo", "Campo"), ("valor", "Valor")], ident, "obs",
                  vazio="Produto não encontrado no catálogo."),
            table("produto_variantes", "Variantes", [("variante", "Variante"), ("id", "Identificador"), ("atributos", "Atributos")],
                  variants, "obs", vazio="Nenhuma variante técnica registrada."),
            table("produto_intl", "Comparação internacional (exploratória)",
                  [("metrica", "Métrica"), ("fonte", "Fonte"), ("paises", "Países"), ("defasagem", "Defasagem (meses)", "inteiro"),
                   ("correlacao", "Correlação", "numero"), ("leitura", "Leitura")], comps, "der",
                  descricao="Correlação com defasagem entre países na mesma métrica e fonte. Não indica causalidade.",
                  vazio="Sem séries comparáveis em dois ou mais países."),
            table("produto_concorrencia", "Concorrência observada", [("fonte", "Fonte"), ("anuncios", "Anúncios", "inteiro"),
                  ("vendedores", "Vendedores únicos", "inteiro"), ("marcas", "Marcas", "inteiro"),
                  ("preco_mediano", "Preço mediano", "numero"), ("moeda", "Moeda"), ("pressao", "Pressão competitiva (0–100)", "score")],
                  compet, "obs", vazio="Sem anúncios de marketplaces coletados (conecte eBay ou Mercado Livre)."),
            table("produto_reviews", "Reviews — problemas técnicos e temas de reclamação",
                  [("tema", "Tema"), ("alvo", "Tipo"), ("mencoes", "Menções", "inteiro")],
                  probs, "der", vazio="Sem avaliações coletadas para o produto.",
                  notas=["Contagens de opiniões publicadas nas fontes coletadas; não são taxa de defeito."]),
            table("produto_riscos", "Riscos e limitações", [("risco", "Risco ou limitação")], uniq, "der"),
        ]
        return tables, {"produto": p, "familia": fam, "score": sc}

    # ---------------------------------------------------------------- relatório executivo (texto)
    def executive_text(self, f: Filters, series, ranking_rows, opp_rows, social_rows) -> dict:
        k = self.cons.get("kpis", {})
        paises = {COUNTRY_LABEL.get(c, c) for c in k.get("paises_com_buscas", [])}
        growing = [r for r in ranking_rows if (r.get("crescimento") or 0) > 0.15]
        emerg = sorted({s["nome"] for s in series if s["ind"].get("classe") == "emergente"})
        top = [r["produto"] for r in opp_rows[:5]] if opp_rows else [r["produto"] for r in ranking_rows[:5]]
        has_vol = any(s["metric"] in ("volume_mensal_aprox", "volume_bing") for s in series)
        resumo = []
        if not series:
            resumo.append("Não há séries de interesse coletadas para o recorte selecionado. O relatório registra a situação das fontes "
                          "e as integrações necessárias; nenhuma conclusão sobre produtos é apresentada.")
        else:
            resumo.append(f"O GPI acompanha {k.get('produtos_monitorados', 0)} produtos do catálogo; {len({s['product_id'] for s in series})} "
                          f"têm sinais coletados no recorte, em {len({s['source'] for s in series})} fonte(s) e "
                          f"{len({s.get('page') for s in series})} mercado(s).")
            if growing:
                resumo.append(f"{len({r['produto'] for r in growing})} produto(s) mostram crescimento acima de 15% em pelo menos um indicador. "
                              "Esses sinais indicam produtos a investigar, não demanda garantida.")
            if emerg:
                resumo.append(f"Produtos que passaram a aparecer recentemente: {', '.join(emerg[:6])}.")
            if not has_vol:
                resumo.append("Nenhuma fonte de VOLUME absoluto de buscas está conectada: os rankings usam interesse relativo e "
                              "listas de buscas em alta. Conectar o Google Ads ou o Microsoft Advertising permitiria medir volume.")
        panorama = [{"indicador": "Produtos monitorados no catálogo", "valor": k.get("produtos_monitorados"), "natureza": "Observado"},
                    {"indicador": "Produtos com sinais no recorte", "valor": len({s["product_id"] for s in series}), "natureza": "Observado"},
                    {"indicador": "Séries de indicadores no recorte", "valor": len(series), "natureza": "Observado"},
                    {"indicador": "Tendências emergentes", "valor": len(emerg), "natureza": "Derivado"},
                    {"indicador": "Mercados com dados de busca", "valor": ", ".join(sorted(paises)) or "nenhum", "natureza": "Observado"},
                    {"indicador": "Fontes com dados", "valor": len(k.get("fontes_com_dados", [])), "natureza": "Observado"},
                    {"indicador": "Produtos com sinais sociais", "valor": len(social_rows), "natureza": "Observado"}]
        intl = []
        for pid, sc in (self.cons.get("scores") or {}).items():
            if sc.get("sinal_internacional") and f.match_product(pid):
                v = sc["sinal_internacional"]
                intl.append({"produto": next((s["nome"] for s in series if s["product_id"] == pid), pid),
                             "forca": v.get("forca"), "detalhe": f"{v.get('mercado_antecedente')}: {v.get('metrica')} — " + v.get("rotulo", "")})
        riscos = Counter(r for sc in (self.cons.get("scores") or {}).values() for r in sc.get("riscos", []))
        prox = []
        for r in opp_rows[:5]:
            if r.get("proximos"):
                prox.append({"produto": r["produto"], "investigacao": r["proximos"]})
        if not has_vol:
            prox.append({"produto": "Todos", "investigacao": "Conectar uma fonte de volume de buscas (Google Ads — acesso Básico ou superior)."})
        if not (self.social or {}).get("series"):
            prox.append({"produto": "Todos", "investigacao": "Conectar redes sociais autorizadas (TikTok Business, Meta, YouTube) para medir atenção social."})
        prox.append({"produto": "Itens priorizados", "investigacao": "Validar preços, custos de importação, certificações e fornecedores antes de qualquer decisão de compra."})
        lim = ["Resultados exploratórios: indicadores de interesse e atenção não equivalem a vendas.",
               "Dados sociais e de busca têm unidades diferentes e não são somados.",
               "Não há fonte autorizada de buscas de consumidores na China continental."]
        if not has_vol:
            lim.append("Sem volume absoluto de buscas conectado.")
        return {"resumo": resumo, "panorama": panorama, "destaques": top, "internacional": intl[:15],
                "riscos": [{"risco": r, "produtos": n} for r, n in riscos.most_common(8)], "proximos": prox, "limitacoes": lim}


# ============================================================================ montagem
def build(db, tipo: str, filtros: dict | None = None, cfg: dict | None = None, today: date | None = None,
          run_id: str | None = None) -> dict:
    if tipo not in TYPES:
        raise ValueError(f"tipo de relatório desconhecido: {tipo}")
    spec = TYPES[tipo]
    if spec.get("exige_analise"):
        from . import regulatory as RG
        a = RG.load_analysis(db, filtros or {})
        return RG.build(a, run_id) if tipo == "regulatorio" else RG.build_checklist(a, run_id)
    f = Filters(filtros)
    if spec.get("exige_produto") and not f.produto:
        raise ValueError("selecione um produto para o relatório individual")
    c = Collector(db, cfg, today)
    names = c.names()
    series = c.series(f)
    demo, demo_motivo = demo_status(db)
    ds = {"tipo": tipo, "titulo": spec.get("titulo", "Global Product Intelligence — " + spec["nome"]),
          "subtitulo": spec["descricao"], "secoes": [], "graficos": [], "texto": {}, "demo": demo, "demo_motivo": demo_motivo}
    sources = {s.get("fonte_nome") for s in series}
    ranking = c.sec_ranking(f, series)
    for sec in spec["secoes"]:
        if sec == "resumo":
            continue                                   # montado ao fim
        if sec == "ranking":
            ds["secoes"].append(("Ranking de Produtos", [ranking]))
            ds["graficos"] += c.chart_series(series)
        elif sec == "pesquisados":
            t, absolute = c.sec_pesquisados(f, series)
            if not absolute:
                ds["titulo"] = "Global Product Intelligence — Ranking de Interesse Relativo"
            ds["secoes"].append((t["titulo"], [t]))
            ds["graficos"] += [{"tipo": "barra", "titulo": t["titulo"] + " — top 10", "unidade": (t["linhas"][0].get("unidade") if t["linhas"] else ""),
                                "series": [{"nome": r["produto"][:32], "y": [r.get("volume", r.get("valor")) or 0]} for r in t["linhas"][:10]
                                           if t["linhas"] and r.get("unidade") == t["linhas"][0].get("unidade")]}] if t["linhas"] else []
        elif sec == "historico":
            ds["secoes"].append(("Histórico de Indicadores", [c.sec_historico(f, series)]))
        elif sec == "paises":
            ds["secoes"].append(("Tendências por País", c.sec_paises(f, series)))
        elif sec == "social":
            ds["secoes"].append(("Redes Sociais", c.sec_social(f)))
        elif sec == "social_vs_busca":
            ds["secoes"].append(("Search vs. Social", [c.sec_social_vs_busca(f)]))
        elif sec == "previsoes":
            ds["secoes"].append(("Forecasting", c.sec_previsoes(f, series)))
        elif sec == "modelos":
            ds["secoes"].append(("Modelos e Desempenho", c.sec_modelos()))
        elif sec == "oportunidades":
            ds["secoes"].append(("Oportunidades", [c.sec_oportunidades(f)]))
        elif sec == "fontes":
            ds["secoes"].append(("Fontes e Metodologia", c.sec_fontes(f, sources)))
        elif sec == "brutos":
            ds["secoes"].append(("Dados Brutos Permitidos", [c.sec_brutos(f)]))
        elif sec == "produto":
            t, info = c.sec_produto(f)
            pname = (info["produto"] or {}).get("canonical") or names.get(f.produto, f.produto)
            ds["titulo"] = f"Global Product Intelligence — Análise do Produto: {pname}"
            ds["secoes"].append(("Produto", t))
            ds["graficos"] += c.chart_series(series)
            ds["texto"]["produto"] = info
        elif sec == "executivo":
            opp = c.sec_oportunidades(f)
            soc = c.sec_social(f)[1]
            ds["texto"]["executivo"] = c.executive_text(f, series, ranking["linhas"], opp["linhas"], soc["linhas"])
            ds["graficos"] += c.chart_series(series, 5)
    # resumo (sempre a primeira aba/seção)
    rid = run_id or uuid.uuid4().hex
    mv = model_versions(db, c.ml)
    kpis = [{"indicador": "Séries no recorte", "valor": len(series), "natureza": "Observado"},
            {"indicador": "Produtos no recorte", "valor": len({s["product_id"] for s in series}), "natureza": "Observado"},
            {"indicador": "Fontes no recorte", "valor": len(sources), "natureza": "Observado"},
            {"indicador": "Emergentes", "valor": sum(1 for s in series if s["ind"].get("classe") == "emergente"), "natureza": "Derivado"},
            {"indicador": "Em crescimento (> 15%)", "valor": sum(1 for s in series if (s["ind"].get("crescimento") or 0) > 0.15), "natureza": "Derivado"},
            {"indicador": "Em declínio", "valor": sum(1 for s in series if s["ind"].get("classe") == "declínio"), "natureza": "Derivado"}]
    ds["resumo"] = table("resumo", "Resumo", [("indicador", "Indicador"), ("valor", "Valor"), ("natureza", "Natureza do dado")], kpis, "obs")
    ds["meta"] = {"run_id": rid, "gerado_em": datetime.now().isoformat(timespec="seconds"), "versao_software": __version__,
                  "versao_dados": data_version(db), "analise_consumo": c.cons.get("_gerado_em") or c.cons.get("gerado_em"),
                  "analise_social": (c.social or {}).get("_gerado_em"), "modelos": mv,
                  "filtros": f.as_dict(), "filtros_texto": f.text(names), "fontes": sorted(x for x in sources if x),
                  "criterios_ranking": "Opportunity Score (desc.), depois crescimento (desc.)",
                  "parametros": {k: c.cfg.get(k) for k in ("trend_forecast_max", "ml_global_enabled", "ml_tuning_trials") if k in c.cfg},
                  "tipo_nome": spec["nome"]}
    return ds


def main_table(ds: dict) -> dict:
    """Tabela principal (para CSV e exportações simples)."""
    pref = {"radar_global": "ranking", "mais_pesquisados": "pesquisados", "tendencias_pais": "ranking", "social": "social_ranking",
            "previsoes": "previsoes", "oportunidades": "oportunidades", "produto": "historico", "executivo": "ranking",
            "regulatorio": "anatel", "checklist_fornecedor": "checklist"}.get(ds["tipo"], "resumo")
    for _, tables in ds["secoes"]:
        for t in tables:
            if t["id"] == pref:
                return t
    return ds["resumo"]
