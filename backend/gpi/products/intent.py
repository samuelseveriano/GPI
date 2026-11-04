"""
Classificação de intenção de termos de busca / manchetes.

Classes: compra · comparacao · review · problema_tecnico · manutencao · informacao · entretenimento · noticia

1. Regras (léxicos pt/en/zh, com prioridade): sinais explícitos ("comprar", "vs", "não liga",
   "como trocar", "anime", "lançamento"...).
2. Modelo supervisionado local (TF-IDF de caracteres + regressão logística, scikit-learn) usado
   SOMENTE quando há exemplos rotulados suficientes (mínimo de 40, ao menos 3 classes) E a acurácia em
   validação cruzada é ≥ 0,60. Os nomes de produto são mascarados antes do treino. Treinado
   com os rótulos fornecidos (arquivo de rótulos do GPI e/ou rótulos do usuário). Sem dados
   suficientes, apenas as regras são usadas e termos sem sinal ficam como 'informacao' com
   confiança baixa — nunca são tratados automaticamente como demanda de compra.

`commercial` = intenção ligada a aquisição (compra, comparação, review). Problemas técnicos e
manutenção indicam base instalada (sinal de mercado, não de compra); notícia e entretenimento
não são demanda.
"""
from __future__ import annotations

import re

from . import nlp
from .nlp import clean, detect_lang, strip_accents

INTENTS = ("compra", "comparacao", "review", "problema_tecnico", "manutencao", "informacao", "entretenimento", "noticia")
COMMERCIAL = {"compra", "comparacao", "review"}

RULES = [  # (intenção, regex sobre texto normalizado sem acentos) — ordem = prioridade
    ("entretenimento", r"\b(anime|personagem|desenho|filme|serie|jogo do|game of|cosplay|meme|lego|fantasia|"
                       r"star wars|marvel|minecraft|fortnite|pokemon|naruto|brinquedo de|movie|cartoon|character|"
                       r"costume|toy of)\b|动漫|动画|电影|游戏角色"),
    ("problema_tecnico", r"\b(nao liga|nao carrega|nao funciona|parou de funcionar|defeito|problema|erro|esquentando|"
                         r"queimou|travando|piscando|nao conecta|not working|won'?t (turn on|charge)|stopped working|"
                         r"problem|issue|error|overheat\w*|broken|fix)\b|故障|不充电|坏了|不能用|没反应"),
    ("manutencao", r"\b(como (limpar|trocar|consertar|desmontar|pintar|instalar|configurar|resetar|calibrar)|limpeza|"
                   r"peca|pecas|refil|filtro de reposicao|reparo|conserto|manual|reset|how to (clean|replace|repair|"
                   r"install|reset|paint|fix)|replacement|spare parts?|repair|cleaning)\b|维修|清洗|更换|安装|说明书"),
    ("noticia", r"\b(lancamento|lanca|lancou|anuncia|anunciou|recall|chega ao brasil|novidade|apresenta|"
                r"launch(es|ed)?|announce[sd]?|unveil\w*|released?|news|leak\w*)\b|发布|上市|新闻|召回"),
    ("comparacao", r"\b(vs|versus|ou|comparativo|comparacao|qual (o )?melhor|diferenca entre|melhor .* ou|"
                   r"compare|comparison|difference between|alternatives?)\b|对比|区别|哪个好|还是"),
    ("review", r"\b(review|reviews|resenha|analise|avaliacao|avaliacoes|vale a pena|e bom|e boa|opiniao|opinioes|"
               r"reclamacao|unboxing|teste|testamos|worth it|is it good|rating|ratings|hands-on|tested)\b|评测|测评|开箱|怎么样|好用吗"),
    ("compra", r"\b(comprar|compra|preco|precos|barato|barata|baratos|promocao|oferta|desconto|cupom|onde comprar|"
               r"loja|frete|mercado livre|shopee|amazon|aliexpress|black friday|parcelado|buy|price|prices|cheap|"
               r"cheapest|deal|deals|discount|coupon|sale|for sale|where to buy|best|melhor|melhores|top \d+|"
               r"under \$?\d+|ate r?\$?\d+)\b|购买|价格|多少钱|便宜|优惠|推荐|哪里买|淘宝|京东|拼多多"),
    ("informacao", r"\b(o que e|como funciona|para que serve|quanto consome|consumo|significado|what is|how does|"
                   r"how do|meaning|what does)\b|是什么|原理|怎么用"),
]
_RX = [(i, re.compile(rx)) for i, rx in RULES]
_PRODUCT_WORDS = sorted({w for lang in ("pt", "en") for w, _ in nlp._INDEX[lang]} |
                        {strip_accents(b) for b in nlp.BRANDS}, key=len, reverse=True)
_PRODUCT_RX = re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in _PRODUCT_WORDS if len(w) > 1) + r")(?![\w])")
_ZH_PRODUCT = sorted({w for w, _ in nlp._INDEX["zh"]}, key=len, reverse=True)


def mask_products(text: str) -> str:
    """Troca nomes de produto, marcas e números por marcadores: o modelo aprende as palavras de
    intenção ("comprar", "não liga", "como limpar"), não os produtos que aparecem nos exemplos."""
    t = nlp._norm(clean(text))
    for w in _ZH_PRODUCT:
        t = t.replace(w, " 〔p〕 ")
    t = _PRODUCT_RX.sub(" 〔p〕 ", t)
    t = re.sub(r"\d+\w*", " 〔n〕 ", t)
    return re.sub(r"\s+", " ", t).strip()


def rule_intent(text: str) -> tuple[str | None, str | None]:
    t = strip_accents(clean(text).lower())
    for intent, rx in _RX:
        m = rx.search(t)
        if m:
            return intent, m.group(0)
    return None, None


class IntentModel:
    """Regras + (opcional) modelo supervisionado treinado com exemplos rotulados."""
    MIN_LABELS, MIN_CLASSES, MIN_CV_ACC = 40, 3, 0.60

    def __init__(self, labeled: list[tuple[str, str]] | None = None):
        self.model = None
        self.info = {"supervisionado": False, "exemplos": len(labeled or [])}
        if labeled:
            self.fit(labeled)

    def fit(self, labeled: list[tuple[str, str]]):
        labeled = [(t, y) for t, y in labeled if y in INTENTS and t]
        classes = {y for _, y in labeled}
        self.info = {"supervisionado": False, "exemplos": len(labeled), "classes": len(classes)}
        if len(labeled) < self.MIN_LABELS or len(classes) < self.MIN_CLASSES:
            self.info["motivo"] = (f"exemplos rotulados insuficientes ({len(labeled)} de {self.MIN_LABELS}, "
                                   f"{len(classes)} de {self.MIN_CLASSES} classes): somente regras")
            return self
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import cross_val_score
            from sklearn.pipeline import make_pipeline
        except ImportError:
            self.info["motivo"] = "scikit-learn indisponível: somente regras"
            return self
        X = [mask_products(t) for t, _ in labeled]
        y = [lab for _, lab in labeled]
        pipe = make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1, sublinear_tf=True),
                             LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"))
        n_cv = min(5, min(y.count(c) for c in set(y)))
        if n_cv >= 2:
            self.info["acuracia_validacao_cruzada"] = round(float(cross_val_score(pipe, X, y, cv=n_cv).mean()), 3)
        acc = self.info.get("acuracia_validacao_cruzada")
        if acc is None or acc < self.MIN_CV_ACC:
            self.info["motivo"] = (f"acurácia em validação cruzada {acc} < {self.MIN_CV_ACC}: o modelo supervisionado "
                                   "não é confiável com estes rótulos; somente regras")
            return self
        pipe.fit(X, y)
        self.model = pipe
        self.info["supervisionado"] = True
        return self

    def classify(self, text: str) -> dict:
        intent, ev = rule_intent(text)
        if intent:
            return {"intencao": intent, "confianca": 0.9, "metodo": "regra", "evidencia": ev,
                    "comercial": intent in COMMERCIAL, "idioma": detect_lang(text)}
        if self.model is not None:
            p = self.model.predict_proba([mask_products(text)])[0]
            k = int(p.argmax())
            lab, conf = self.model.classes_[k], float(p[k])
            if conf >= 0.5:
                return {"intencao": lab, "confianca": round(conf, 2), "metodo": "modelo", "evidencia": None,
                        "comercial": lab in COMMERCIAL, "idioma": detect_lang(text)}
        # sem sinal: termo de produto puro (ex.: "air fryer") → informação genérica, confiança baixa
        return {"intencao": "informacao", "confianca": 0.4, "metodo": "padrao", "evidencia": None,
                "comercial": False, "idioma": detect_lang(text)}


_DEFAULT: IntentModel | None = None


def default_model() -> IntentModel:
    """Modelo padrão: regras + supervisionado treinado com o arquivo de rótulos do GPI."""
    global _DEFAULT
    if _DEFAULT is None:
        from .labels import LABELED
        _DEFAULT = IntentModel(LABELED)
    return _DEFAULT


def classify(text: str) -> dict:
    return default_model().classify(text)
