from .content import GoogleNews, Reddit, RssFeeds, YouTube
from .public import BcbPtax, ComexStat, IbgePmc, UnComtrade, WikimediaPageviews
from .restricted import (AlibabaInsights, AliExpress, Alibaba, AmazonBR, AmazonUS, BaiduIndex, Comparadores,
                         GoogleTrends, MercadoLivre, MicrosoftAdsKeywords, OceanEngineIndex, ReclameAqui, Shopee,
                         Taobao, Trustpilot)
from .search import GoogleAdsKeywordPlanner, GoogleTrendsTrending


def all_connectors():
    cs = [BcbPtax(), GoogleTrendsTrending(), GoogleAdsKeywordPlanner(), WikimediaPageviews(), ComexStat(), IbgePmc(),
          UnComtrade(), RssFeeds(), GoogleNews(), YouTube(), Reddit(), MercadoLivre(), AmazonBR(), AmazonUS(), Shopee(),
          AliExpress(), Alibaba(), Taobao(), GoogleTrends(), BaiduIndex(), OceanEngineIndex(), AlibabaInsights(),
          MicrosoftAdsKeywords(), Trustpilot(), ReclameAqui(), Comparadores()]
    return sorted(cs, key=lambda c: c.order)
