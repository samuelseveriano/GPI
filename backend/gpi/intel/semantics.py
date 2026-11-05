"""Catálogo semântico de fontes e métricas (v0.8, Etapa 1 e Gate 3).

Cada métrica tem UM tipo de evidência. Tipos nunca são convertidos entre si:

* SEARCH_INTEREST            — interesse de pesquisa (volume aproximado, faixa de tráfego, índice relativo).
* COMMERCIAL_SEARCH_INTENT   — sinais de pesquisa comercial (ranking de mais buscados de marketplace, termos com intenção
                               de compra). Posição em ranking NÃO é volume.
* SOCIAL_ATTENTION           — atenção em redes sociais (visualizações, publicações). Não são vendas.
* PUBLIC_ATTENTION           — notícias, enciclopédia, menções. Leitura de artigo NÃO é intenção de compra.
* FOREIGN_TRADE              — importação/exportação (por NCM/SH, não por produto). Não é demanda de consumidores.
* ACTUAL_DEMAND              — demanda efetiva: só dados transacionais do próprio usuário (vendas importadas).
* MARKET_OFFER               — oferta/preços anunciados (não é demanda).
* MACRO_CONTEXT              — câmbio, varejo agregado: contexto, nunca evidência de produto.

`INDICATORS` define quais tipos alimentam cada índice consolidado; `eligible(metric, indicator)` é a regra usada pelo
motor de fusão, pelo dashboard e pelos relatórios — uma única fonte de verdade (Gate 8).
"""
from __future__ import annotations

SEARCH, COMMERCIAL, SOCIAL, PUBLIC, TRADE, DEMAND, OFFER, MACRO = (
    "SEARCH_INTEREST", "COMMERCIAL_SEARCH_INTENT", "SOCIAL_ATTENTION", "PUBLIC_ATTENTION", "FOREIGN_TRADE", "ACTUAL_DEMAND",
    "MARKET_OFFER", "MACRO_CONTEXT")

TYPE_LABEL = {SEARCH: "Interesse de pesquisa", COMMERCIAL: "Sinal de pesquisa comercial", SOCIAL: "Atenção em redes sociais",
              PUBLIC: "Atenção pública (notícias e enciclopédia)", TRADE: "Comércio exterior", DEMAND: "Demanda efetiva (vendas)",
              OFFER: "Oferta e preços anunciados", MACRO: "Contexto macroeconômico"}
TYPE_NOT = {SEARCH: "não é volume de vendas", COMMERCIAL: "posição em ranking não é volume de buscas",
            SOCIAL: "visualizações não são vendas", PUBLIC: "leitura de artigos e notícias não é intenção de compra",
            TRADE: "volume importado não equivale à demanda de consumidores", DEMAND: "vale apenas para o histórico informado",
            OFFER: "anúncios não são vendas", MACRO: "não descreve nenhum produto específico"}

# --------------------------------------------------------------------------------------------- fontes (Etapa 1)
SOURCES = {
    "google_ads_kp": {"nome": "Google Ads — Planejador de palavras-chave", "mede": "Pesquisas no Google por palavra-chave",
                      "unidade": "buscas/mês, arredondadas em faixas pelo Google", "frequencia": "mensal",
                      "cobertura": "país (BR, US)", "data_referencia": "mês da pesquisa", "limitacoes":
                      "Valores aproximados e arredondados; sem a conta do anunciante os valores podem vir em faixas largas.",
                      "uso": "API oficial com conta do usuário; termos do Google Ads API.", "relevancia": "alta"},
    "msads_kp": {"nome": "Microsoft Advertising — Ad Insight", "mede": "Pesquisas no Bing por palavra-chave", "unidade": "buscas/mês",
                 "frequencia": "mensal", "cobertura": "país", "data_referencia": "mês", "limitacoes": "Bing tem participação pequena no Brasil.",
                 "uso": "API oficial com conta do usuário.", "relevancia": "média"},
    "google_trends_rss": {"nome": "Google Trends — Trending Now (RSS)", "mede": "Buscas que entraram na lista de alta do dia",
                          "unidade": "buscas/dia — limite inferior da faixa", "frequencia": "diária (lista do momento)",
                          "cobertura": "país (BR, US)", "data_referencia": "dia da lista", "limitacoes":
                          "Lista curta, dominada por notícias e esportes; sem histórico retroativo.",
                          "uso": "Feed público oficial.", "relevancia": "baixa a média (só termos comerciais)"},
    "google_trends_bq": {"nome": "Google Trends — BigQuery (top 25 e em alta)", "mede": "Interesse relativo dos termos do top 25",
                         "unidade": "índice 0–100, relativo à região e semana", "frequencia": "semanal",
                         "cobertura": "regiões (DMA/estado)", "data_referencia": "semana", "limitacoes":
                         "Índice relativo — não é volume absoluto nem comparável entre regiões.",
                         "uso": "Conjunto público do Google Cloud, com projeto do usuário.", "relevancia": "média"},
    "ml_trends": {"nome": "Mercado Livre — tendências de busca (API oficial)", "mede": "Termos mais buscados no Mercado Livre",
                  "unidade": "posição no ranking (1 = mais buscado), até 50", "frequencia": "semanal (acúmulo pelo GPI)",
                  "cobertura": "Brasil (MLB)", "data_referencia": "data da coleta", "limitacoes":
                  "Ranking sem volume: posição não é quantidade de buscas; o histórico começa na 1ª coleta do GPI.",
                  "uso": "API oficial com OAuth do usuário; limites e periodicidade do Mercado Livre.", "relevancia": "alta (sinal comercial)"},
    "mercadolivre": {"nome": "Mercado Livre Brasil — tendências", "mede": "Mesma resposta de ml_trends (compartilhada)",
                     "unidade": "posição", "frequencia": "semanal", "cobertura": "Brasil", "data_referencia": "data da coleta",
                     "limitacoes": "Ver ml_trends.", "uso": "API oficial com OAuth do usuário.", "relevancia": "alta"},
    "wikimedia": {"nome": "Wikimedia — visualizações de artigos", "mede": "Leituras de artigos da Wikipédia por idioma",
                  "unidade": "visualizações/mês", "frequencia": "mensal", "cobertura": "idioma (pt/en/zh) — NÃO é país",
                  "data_referencia": "mês", "limitacoes":
                  "Atenção enciclopédica, não pesquisa nem intenção de compra; o tráfego total da Wikipédia muda ao longo dos "
                  "anos (respostas em buscadores e assistentes), o que desloca todos os artigos ao mesmo tempo.",
                  "uso": "API pública Wikimedia REST (CC0 para métricas).", "relevancia": "baixa (contexto de atenção)"},
    "gdelt": {"nome": "GDELT — notícias globais", "mede": "Artigos de imprensa que citam o produto", "unidade": "artigos/mês",
              "frequencia": "mensal", "cobertura": "imprensa mundial", "data_referencia": "data de publicação",
              "limitacoes": "Repercussão, não consumo; limite de 1 consulta a cada 5 s.", "uso": "API pública DOC 2.0.",
              "relevancia": "baixa"},
    "rss": {"nome": "Feeds RSS especializados", "mede": "Manchetes que citam o produto", "unidade": "itens/mês", "frequencia": "diária",
            "cobertura": "sites configurados (pt/en)", "data_referencia": "publicação", "limitacoes": "Cobertura editorial, não demanda.",
            "uso": "Feeds públicos; somente manchete, resumo e link.", "relevancia": "baixa"},
    "google_news": {"nome": "Google Notícias (RSS)", "mede": "Manchetes", "unidade": "itens/mês", "frequencia": "diária",
                    "cobertura": "país/idioma do feed", "data_referencia": "publicação", "limitacoes": "Opt-in; repercussão.",
                    "uso": "Feed público, habilitado pelo usuário.", "relevancia": "baixa"},
    "reddit": {"nome": "Reddit", "mede": "Discussões de consumidores", "unidade": "itens/mês", "frequencia": "diária",
               "cobertura": "global, majoritariamente EUA", "data_referencia": "publicação", "limitacoes":
               "Nível gratuito para uso não comercial.", "uso": "API oficial; uso autorizado confirmado pelo usuário.", "relevancia": "baixa"},
    "youtube": {"nome": "YouTube Data API v3", "mede": "Vídeos de review/unboxing encontrados por busca e suas estatísticas",
                "unidade": "vídeos; visualizações acumuladas", "frequencia": "semanal", "cobertura":
                "consulta com regionCode=BR; o idioma do vídeo pode ser outro", "data_referencia": "publicação do vídeo",
                "limitacoes": "Visualizações não são vendas; busca por relevância não é amostra representativa.",
                "uso": "Políticas do YouTube API Services: dados exibidos separadamente, não combinados em índices de outras "
                       "fontes; retenção máxima de 30 dias sem atualização.", "relevancia": "baixa (contexto)",
                "combinavel": False},
    "tiktok": {"nome": "TikTok API for Business", "mede": "Popularidade de hashtags", "unidade": "posição/visualizações",
               "frequencia": "diária", "cobertura": "país", "data_referencia": "dia", "limitacoes": "Atenção social.",
               "uso": "API oficial; separação exigida pelas políticas.", "relevancia": "baixa", "combinavel": False},
    "instagram": {"nome": "Instagram Graph API", "mede": "Publicações por hashtag", "unidade": "publicações",
                  "frequencia": "diária", "cobertura": "conta", "data_referencia": "dia", "limitacoes": "Atenção social.",
                  "uso": "API oficial; separação exigida pelas políticas.", "relevancia": "baixa", "combinavel": False},
    "facebook": {"nome": "Facebook Graph API", "mede": "Páginas comerciais", "unidade": "seguidores/publicações",
                 "frequencia": "diária", "cobertura": "conta", "data_referencia": "dia", "limitacoes": "Atenção social.",
                 "uso": "API oficial.", "relevancia": "baixa", "combinavel": False},
    "meta_ads": {"nome": "Biblioteca de Anúncios da Meta", "mede": "Anúncios ativos por termo", "unidade": "anúncios",
                 "frequencia": "diária", "cobertura": "país", "data_referencia": "dia", "limitacoes": "Oferta/publicidade, não demanda.",
                 "uso": "API oficial.", "relevancia": "baixa", "combinavel": False},
    "ebay": {"nome": "eBay Browse API", "mede": "Anúncios e preços", "unidade": "preço (moeda local)", "frequencia": "sob demanda",
             "cobertura": "EUA", "data_referencia": "data da coleta", "limitacoes": "Oferta, não vendas.", "uso": "API oficial.",
             "relevancia": "média (preço de referência)"},
    "comexstat": {"nome": "Comex Stat (MDIC)", "mede": "Importações brasileiras por NCM", "unidade": "US$ FOB e kg/mês",
                  "frequencia": "mensal", "cobertura": "Brasil, por país de origem", "data_referencia": "mês de registro",
                  "limitacoes": "NCM agrega produtos diferentes; não é demanda do consumidor.", "uso": "API pública oficial.",
                  "relevancia": "média (contexto de mercado)"},
    "comtrade": {"nome": "UN Comtrade", "mede": "Importações de outros países vindas da China por SH", "unidade": "US$/ano ou mês",
                 "frequencia": "anual/mensal", "cobertura": "países declarantes", "data_referencia": "período declarado",
                 "limitacoes": "SH6 agrega produtos; defasagem de meses.", "uso": "API pública (chave opcional).", "relevancia": "média"},
    "bcb_ptax": {"nome": "Banco Central — PTAX", "mede": "Taxa de câmbio", "unidade": "R$/US$", "frequencia": "diária",
                 "cobertura": "Brasil", "data_referencia": "dia útil", "limitacoes": "Contexto de custo de importação.",
                 "uso": "API pública oficial.", "relevancia": "contexto"},
    "ibge_pmc": {"nome": "IBGE — Pesquisa Mensal de Comércio", "mede": "Volume de vendas do varejo por atividade",
                 "unidade": "índice (base fixa)", "frequencia": "mensal", "cobertura": "Brasil", "data_referencia": "mês",
                 "limitacoes": "Atividade agregada; não identifica produtos.", "uso": "API pública oficial.", "relevancia": "contexto"},
    "vendas": {"nome": "Vendas importadas pelo usuário", "mede": "Unidades vendidas por SKU", "unidade": "unidades/mês",
               "frequencia": "mensal", "cobertura": "empresa do usuário", "data_referencia": "mês", "limitacoes":
               "Vale para o histórico informado.", "uso": "Dado privado local; nunca sai do computador.", "relevancia": "alta"},
}

# --------------------------------------------------------------------------------------------- métricas (Gate 3)
_M = lambda **k: k   # noqa: E731
METRICS = {
    "volume_mensal_aprox": _M(tipo=SEARCH, nome_comercial="Volume de buscas no Google (aproximado)", unidade="buscas/mês",
                              definicao="Média mensal de pesquisas da palavra-chave, arredondada pelo Google",
                              metodo="valor informado pela API; soma dos termos do mesmo produto", frequencia="mensal",
                              comparavel="entre meses e países da mesma fonte", modelagem=True, crescimento_pct=True),
    "volume_bing": _M(tipo=SEARCH, nome_comercial="Volume de buscas no Bing", unidade="buscas/mês", frequencia="mensal",
                      definicao="Pesquisas mensais no Bing", metodo="valor informado pela API", comparavel="entre meses",
                      modelagem=True, crescimento_pct=True),
    "trafego_faixa": _M(tipo=SEARCH, nome_comercial="Buscas em alta no Google (Trending Now)", unidade="buscas/dia (limite inferior)",
                        definicao="Limite inferior da faixa de tráfego de um termo na lista de alta do dia",
                        metodo="presença diária; somas por janela", frequencia="diária", comparavel="só presença/ausência entre dias",
                        modelagem=False, crescimento_pct=False),
    "score_trends": _M(tipo=SEARCH, nome_comercial="Índice do top 25 do Google (BigQuery)", unidade="índice 0–100",
                       definicao="Interesse relativo à região e semana", metodo="máximo entre regiões por semana", frequencia="semanal",
                       comparavel="NÃO entre regiões; não é volume", modelagem=False, crescimento_pct=False),
    "score_trends_rising": _M(tipo=SEARCH, nome_comercial="Em alta no Google (BigQuery)", unidade="índice 0–100",
                              definicao="Termos com maior crescimento relativo", metodo="máximo entre regiões", frequencia="semanal",
                              comparavel="NÃO entre regiões; não é volume", modelagem=False, crescimento_pct=False),
    "posicao_tendencia": _M(tipo=COMMERCIAL, nome_comercial="Ranking de mais buscados do Mercado Livre", unidade="posição (1–50)",
                            definicao="Posição do termo na lista de mais buscados no momento da coleta",
                            metodo="persistência, melhor/média posição, entradas e saídas (sem % de volume)", frequencia="semanal",
                            comparavel="posições entre coletas", modelagem=False, crescimento_pct=False),
    "visualizacoes": _M(tipo=PUBLIC, nome_comercial="Leitura de artigos da Wikipédia", unidade="visualizações/mês",
                        definicao="Visualizações do artigo correspondente ao produto, por idioma",
                        metodo="valor da API; variação também comparada à mediana dos artigos do mesmo idioma",
                        frequencia="mensal", comparavel="entre meses do mesmo idioma", modelagem=True, crescimento_pct=True),
    "mencoes": _M(tipo=PUBLIC, nome_comercial="Menções em notícias e discussões", unidade="itens/mês",
                  definicao="Manchetes e discussões que citam o produto", metodo="contagem mensal de itens associados",
                  frequencia="mensal", comparavel="entre meses (cobertura dos feeds muda)", modelagem=False, crescimento_pct=False),
    "noticias_gdelt": _M(tipo=PUBLIC, nome_comercial="Repercussão na imprensa (GDELT)", unidade="artigos/mês",
                         definicao="Artigos na imprensa mundial que citam o produto", metodo="contagem mensal",
                         frequencia="mensal", comparavel="entre meses", modelagem=False, crescimento_pct=True),
    "videos_youtube": _M(tipo=SOCIAL, nome_comercial="Vídeos no YouTube", unidade="vídeos e visualizações acumuladas",
                         definicao="Vídeos de review/unboxing encontrados por busca", metodo="contagem; exibido à parte",
                         frequencia="semanal", comparavel="não (amostra de busca)", modelagem=False, crescimento_pct=False),
    "social": _M(tipo=SOCIAL, nome_comercial="Atenção em redes sociais", unidade="conforme a plataforma", definicao="Métricas das APIs sociais",
                 metodo="exibido por plataforma", frequencia="diária", comparavel="só dentro da plataforma", modelagem=False,
                 crescimento_pct=False),
    "importacao_fob": _M(tipo=TRADE, nome_comercial="Importações (US$ FOB)", unidade="US$/mês", definicao="Valor importado por NCM",
                         metodo="valor oficial", frequencia="mensal", comparavel="entre meses da mesma NCM", modelagem=True,
                         crescimento_pct=True),
    "preco_anuncio": _M(tipo=OFFER, nome_comercial="Preço anunciado", unidade="moeda local", definicao="Preços de anúncios",
                        metodo="mediana por coleta", frequencia="sob demanda", comparavel="mesma moeda", modelagem=False,
                        crescimento_pct=False),
    "cambio": _M(tipo=MACRO, nome_comercial="Câmbio PTAX", unidade="R$/US$", definicao="Taxa de câmbio oficial", metodo="valor oficial",
                 frequencia="diária", comparavel="sim", modelagem=True, crescimento_pct=True),
    "varejo_indice": _M(tipo=MACRO, nome_comercial="Volume do varejo (IBGE)", unidade="índice", definicao="Volume de vendas do varejo",
                        metodo="valor oficial", frequencia="mensal", comparavel="sim", modelagem=True, crescimento_pct=True),
    "vendas_unidades": _M(tipo=DEMAND, nome_comercial="Vendas (unidades)", unidade="unidades/mês", definicao="Vendas do usuário",
                          metodo="importação de planilha", frequencia="mensal", comparavel="sim", modelagem=True, crescimento_pct=True),
}
METRIC_SOURCES = {"volume_mensal_aprox": ["google_ads_kp"], "volume_bing": ["msads_kp"], "trafego_faixa": ["google_trends_rss"],
                  "score_trends": ["google_trends_bq"], "score_trends_rising": ["google_trends_bq"],
                  "posicao_tendencia": ["ml_trends", "mercadolivre"], "visualizacoes": ["wikimedia"],
                  "mencoes": ["rss", "google_news", "reddit"], "noticias_gdelt": ["gdelt"], "videos_youtube": ["youtube"],
                  "social": ["tiktok", "instagram", "facebook", "meta_ads"], "importacao_fob": ["comexstat", "comtrade"],
                  "preco_anuncio": ["ebay"], "cambio": ["bcb_ptax"], "varejo_indice": ["ibge_pmc"], "vendas_unidades": ["vendas"]}

# --------------------------------------------------------------------------------------------- índices (seção 8)
INDICATORS = {
    "search_interest_index": {"nome": "Search Interest Index", "rotulo": "Interesse de pesquisa", "tipos": [SEARCH],
                              "descricao": "Interesse em pesquisas (Google Ads, Bing, Trending Now, BigQuery)."},
    "commercial_intent_index": {"nome": "Commercial Intent Index", "rotulo": "Sinais comerciais", "tipos": [COMMERCIAL],
                                "descricao": "Presença e persistência em rankings de mais buscados de marketplaces e termos com intenção de compra."},
    "public_attention_index": {"nome": "Public Attention Index", "rotulo": "Atenção pública", "tipos": [PUBLIC],
                               "descricao": "Notícias, enciclopédia e menções. NÃO é demanda."},
    "evidence_coverage": {"nome": "Evidence Coverage", "rotulo": "Cobertura de evidências", "tipos": [SEARCH, COMMERCIAL, PUBLIC, TRADE, DEMAND],
                          "descricao": "Quantidade, diversidade e qualidade das evidências elegíveis."},
    "forecast_confidence": {"nome": "Forecast Confidence", "rotulo": "Confiança da previsão", "tipos": [SEARCH, PUBLIC, DEMAND],
                            "descricao": "Qualidade validada por backtesting das previsões elegíveis."},
    "opportunity_score": {"nome": "Opportunity Score", "rotulo": "Prioridade de investigação", "tipos": [SEARCH, COMMERCIAL, PUBLIC],
                          "descricao": "Prioriza produtos para investigação. NÃO é probabilidade de sucesso."},
    "import_readiness": {"nome": "Import Readiness", "rotulo": "Prontidão para importação", "tipos": [],
                         "descricao": "Disponibilidade documental, preparação comercial e situação regulatória (análises de conformidade)."},
}


def metric_type(metric: str) -> str | None:
    m = METRICS.get(metric)
    return m["tipo"] if m else None


def eligible(metric: str, indicator: str, source: str | None = None) -> bool:
    """Regra única de elegibilidade de uma métrica para um índice. Fontes não combináveis (políticas) nunca entram."""
    if source and SOURCES.get(source, {}).get("combinavel") is False:
        return False
    t = metric_type(metric)
    return bool(t) and t in INDICATORS[indicator]["tipos"]


def describe(metric: str) -> dict:
    m = METRICS[metric]
    return {"metrica": metric, **m, "tipo_rotulo": TYPE_LABEL[m["tipo"]], "nao_e": TYPE_NOT[m["tipo"]],
            "fontes": [{"id": s, **{k: SOURCES[s][k] for k in ("nome", "cobertura", "limitacoes", "uso")}}
                       for s in METRIC_SOURCES.get(metric, []) if s in SOURCES],
            "indices": [k for k in INDICATORS if eligible(metric, k)]}


def catalog() -> dict:
    """Catálogo completo para a interface e a documentação."""
    return {"tipos": [{"id": t, "rotulo": TYPE_LABEL[t], "nao_e": TYPE_NOT[t]} for t in TYPE_LABEL],
            "metricas": [describe(m) for m in METRICS],
            "fontes": [{"id": k, **v} for k, v in SOURCES.items()],
            "indices": [{"id": k, **v, "metricas_elegiveis": [m for m in METRICS if eligible(m, k)]} for k, v in INDICATORS.items()],
            "regra": "Um tipo de evidência nunca é convertido em outro. Ausência de dados não é ausência de demanda."}
