from .content import GoogleNews, Reddit, RssFeeds, YouTube
from .public import BcbPtax, ComexStat, IbgePmc, UnComtrade, WikimediaPageviews
from .restricted import (AliExpress, Alibaba, AmazonBR, AmazonUS, Comparadores, GoogleTrends, MercadoLivre,
                         ReclameAqui, Shopee, Taobao, Trustpilot)


def all_connectors():
    cs = [BcbPtax(), WikimediaPageviews(), ComexStat(), IbgePmc(), UnComtrade(), RssFeeds(), GoogleNews(),
          YouTube(), Reddit(), MercadoLivre(), AmazonBR(), AmazonUS(), Shopee(), AliExpress(), Alibaba(),
          Taobao(), GoogleTrends(), Trustpilot(), ReclameAqui(), Comparadores()]
    return sorted(cs, key=lambda c: c.order)
