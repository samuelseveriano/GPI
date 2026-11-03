from .content import GoogleNews, Reddit, RssFeeds, YouTube
from .public import BcbPtax, ComexStat, IbgePmc, UnComtrade, WikimediaPageviews
from .restricted import (AlibabaInsights, AliExpress, Alibaba, AmazonBR, AmazonUS, BaiduIndex, Comparadores,
                         GoogleTrends, JdCom, MercadoLivre, OceanEngineIndex, ReclameAqui, Shopee,
                         Taobao, Trustpilot)
from .search import GoogleAdsKeywordPlanner, GoogleTrendsTrending
from .sources5 import (EbayBrowse, Gdelt, GoogleTrendsBigQuery, MercadoLivreTrends,
                       MicrosoftAdsKeywordPlanner)


def all_connectors():
    cs = [BcbPtax(), GoogleTrendsTrending(), GoogleAdsKeywordPlanner(), WikimediaPageviews(), ComexStat(), IbgePmc(),
          UnComtrade(), RssFeeds(), GoogleNews(), YouTube(), Reddit(), MercadoLivre(), AmazonBR(), AmazonUS(), Shopee(),
          AliExpress(), Alibaba(), Taobao(), GoogleTrends(), BaiduIndex(), OceanEngineIndex(), AlibabaInsights(),
          JdCom(), MercadoLivreTrends(), GoogleTrendsBigQuery(), EbayBrowse(), Gdelt(), MicrosoftAdsKeywordPlanner(), Trustpilot(), ReclameAqui(), Comparadores()]
    return sorted(cs, key=lambda c: c.order)
