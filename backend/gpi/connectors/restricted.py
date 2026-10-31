"""
Fontes que exigem credenciais, aprovação ou contrato — o GPI NÃO faz scraping,
não contorna login, CAPTCHA, limites ou termos de uso. Ficam marcadas como
restritas, com o motivo e o que seria necessário para ativá-las.
"""
from __future__ import annotations

from datetime import date

from .base import Batch, Connector, Job, require


class Restricted(Connector):
    reliability = "B"

    def plan(self, ctx):
        return []


class AmazonBR(Restricted):
    id, name, order = "amazon_br", "Amazon Brasil", 90
    docs_url = "https://webservices.amazon.com.br/paapi5/documentation/"
    restricted_reason = ("Product Advertising API exige conta aprovada no Programa de Associados (com vendas "
                         "qualificadas) e chaves de acesso. Páginas de 'mais vendidos' não podem ser raspadas.")


class AmazonUS(AmazonBR):
    id, name = "amazon_us", "Amazon Estados Unidos"
    docs_url = "https://webservices.amazon.com/paapi5/documentation/"


class Shopee(Restricted):
    id, name, order = "shopee", "Shopee Brasil", 91
    docs_url = "https://open.shopee.com/"
    restricted_reason = "Open Platform/Afiliados exige cadastro aprovado, chave de parceiro e assinatura das chamadas."


class AliExpress(Restricted):
    id, name, order = "aliexpress", "AliExpress", 92
    docs_url = "https://openservice.aliexpress.com/"
    restricted_reason = "Open Platform exige app key aprovada (programa de afiliados ou dropshipping)."


class Alibaba(Restricted):
    id, name, order = "alibaba", "Alibaba.com (fornecedores)", 93
    docs_url = "https://openapi.alibaba.com/"
    restricted_reason = ("Dados de fornecedores via Alibaba Open Platform exigem cadastro empresarial e app "
                         "key aprovada; não há API pública gratuita de busca.")


class Taobao(Restricted):
    id, name, order = "taobao", "Taobao", 94
    docs_url = "https://open.taobao.com/"
    restricted_reason = "Taobao Open Platform exige conta de desenvolvedor chinesa e aprovação de aplicativo."


class GoogleTrends(Restricted):
    id, name, order = "google_trends", "Google Trends", 95
    docs_url = "https://developers.google.com/search/apis/trends"
    restricted_reason = ("Não há API pública gratuita aberta: a API oficial está em acesso restrito (alfa, "
                         "mediante inscrição). Bibliotecas não oficiais raspam o site e não são usadas. "
                         "O interesse público é medido pela Wikimedia.")


class Trustpilot(Restricted):
    id, name, order = "trustpilot", "Trustpilot (avaliações)", 96
    docs_url = "https://developers.trustpilot.com/"
    restricted_reason = ("API disponível para empresas clientes do Trustpilot (planos pagos); não há acesso público "
                         "gratuito às avaliações de terceiros. O site não é raspado.")


class ReclameAqui(Restricted):
    id, name, order = "reclame_aqui", "Reclame Aqui", 97
    docs_url = "https://www.reclameaqui.com.br/"
    restricted_reason = "Não há API pública; dados apenas por parceria comercial. O site não é raspado."


class Comparadores(Restricted):
    id, name, order = "comparadores", "Comparadores de preço (Buscapé, Zoom, Google Shopping)", 98
    docs_url = "https://www.buscape.com.br/"
    restricted_reason = ("Sem API pública para consulta de preços de terceiros; exige licença ou parceria. "
                         "Preços indicativos de importação vêm do Comex Stat.")


class MercadoLivre(Connector):
    stage = 2
    """Ativado somente se a empresa configurar um access token oficial (OAuth)."""
    id, name, order = "mercadolivre", "Mercado Livre Brasil — tendências de busca", 80
    reliability = "B"
    docs_url = "https://developers.mercadolivre.com.br/pt_br/tendencias"
    description = "Palavras mais buscadas no Mercado Livre Brasil (recurso /trends), registradas a cada coleta."
    limitations = ("Fornece ranking atual, sem histórico: o histórico é construído pelo GPI a cada semana. "
                   "Não informa volume de buscas nem vendas.")

    def available(self, ctx):
        c = ctx.creds.get("mercadolivre") if getattr(ctx, "creds", None) else {}
        return bool(ctx.cfg.get("mercadolivre_access_token") or c.get("access_token"))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return ("A API exige login OAuth de um aplicativo registrado no DevCenter do Mercado Livre. "
                "Use 'Conectar' na Central de Integrações.")

    def info(self):
        d = super().info()
        return d

    def plan(self, ctx):
        if not self.available(ctx):
            return []
        wk = date.fromisoformat(str(ctx.today)).isocalendar()
        return [Job(f"{self.id}:trends:{wk[0]}-W{wk[1]:02d}", {}, refresh_days=None, priority=2)]

    @staticmethod
    def parse(payload):
        require(isinstance(payload, list), "Mercado Livre: lista de tendências esperada")
        return [str(x.get("keyword", "")).strip() for x in payload if x.get("keyword")]

    def run(self, job, ctx):
        tok = ctx.cfg.get("mercadolivre_access_token")
        if not tok:
            from ..integrations.registry import ml_token
            tok = ml_token(ctx.http, ctx.creds)
        url = "https://api.mercadolibre.com/trends/MLB"
        kws = self.parse(ctx.http.request_json(url, headers={"Authorization": f"Bearer {tok}"}, ttl=0))
        d = ctx.today.isoformat()
        from ..market import taxonomy as tx
        batches = []
        for pos, kw in enumerate(kws, start=1):
            meta = dict(source=self.id, indicator="Posição nas tendências de busca", kind="observado",
                        product_key="ml:" + tx.normalize_name(kw).replace(" ", "-"), product_name=kw,
                        category=None, country="Brasil", unit="posição (1 = mais buscado)", currency=None,
                        freq="W", origin_url=url, method="API oficial Mercado Livre /trends/MLB (OAuth)",
                        reliability="B")
            batches.append(Batch(f"ml:trend:{tx.normalize_name(kw)}", meta, [(d, float(pos))]))
        return batches, []
