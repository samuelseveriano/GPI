from .content import GoogleNews, Reddit, RssFeeds, YouTube
from .public import BcbPtax, ComexStat, IbgePmc, UnComtrade, WikimediaPageviews
from .restricted import (AliExpress, AmazonBR, AmazonUS, Comparadores, GoogleTrends, MercadoLivre, Shopee,
                         Taobao, Trustpilot)
from .search import GoogleAdsKeywordPlanner, GoogleTrendsTrending
from ..social.connectors import social_connectors
from .sources5 import (EbayBrowse, Gdelt, GoogleTrendsBigQuery, MercadoLivreTrends,
                       MicrosoftAdsKeywordPlanner)


def all_connectors():
    cs = [BcbPtax(), GoogleTrendsTrending(), GoogleAdsKeywordPlanner(), WikimediaPageviews(), ComexStat(), IbgePmc(),
          UnComtrade(), RssFeeds(), GoogleNews(), YouTube(), Reddit(), MercadoLivre(), AmazonBR(), AmazonUS(), Shopee(),
          AliExpress(), Taobao(), GoogleTrends(), MercadoLivreTrends(), GoogleTrendsBigQuery(), EbayBrowse(), Gdelt(),
          MicrosoftAdsKeywordPlanner(), Trustpilot(), Comparadores(),
          *social_connectors()]
    return sorted(cs, key=lambda c: c.order)


# v0.7 — fontes retiradas das integrações ativas (sem API aberta a terceiros, ou acesso só por contrato/login
# chinês). Não há conector, formulário, job, sincronização nem aviso recorrente para elas. Dados históricos já
# gravados (se houver) são preservados e aparecem identificados como "fonte descontinuada".
REMOVED_SOURCES = {
    "reclame_aqui": ("Reclame Aqui", "sem API pública; acesso apenas por parceria comercial"),
    "baidu_index": ("Baidu Index (百度指数)", "sem API pública; exige login de usuário chinês"),
    "ocean_engine": ("巨量算数 Ocean Engine / Douyin", "sem API aberta a terceiros fora da China"),
    "alibaba": ("Alibaba.com", "exige cadastro empresarial e app key aprovada"),
    "alibaba_insights": ("Alibaba / 1688 — dados de busca", "ferramentas pagas para vendedores cadastrados"),
    "jd_com": ("JD.com (京东)", "exige empresa registrada na China"),
}
REMOVED_IN = "0.7"


def removed_label(source: str) -> str | None:
    r = REMOVED_SOURCES.get(source)
    return f"{r[0]} — fonte descontinuada no GPI v{REMOVED_IN} (dados históricos preservados)" if r else None
