"""Exemplos rotulados de intenção (redigidos manualmente, pt/en/zh) usados para treinar o modelo
supervisionado local. Não são dados de mercado — servem para ensinar o padrão linguístico de cada
intenção. O usuário pode ampliar este conjunto; o modelo só é usado com ≥ 40 exemplos."""
LABELED = [
    # compra
    ("comprar air fryer barata", "compra"), ("preço parafusadeira bosch", "compra"), ("onde comprar capacete ls2", "compra"),
    ("fone bluetooth promoção", "compra"), ("carregador usb-c 65w oferta", "compra"), ("cupom desconto aspirador robô", "compra"),
    ("buy robot vacuum", "compra"), ("cheap wireless earbuds deal", "compra"), ("smart lock price", "compra"),
    ("best air fryer under 100", "compra"), ("购买空气炸锅", "compra"), ("充电宝价格", "compra"), ("智能门锁多少钱", "compra"),
    ("luminária solar mercado livre", "compra"), ("câmera wi-fi frete grátis", "compra"),
    # comparação
    ("air fryer mondial ou britânia", "comparacao"), ("iphone vs galaxy carregador", "comparacao"),
    ("qual melhor fone jbl ou qcy", "comparacao"), ("diferença entre parafusadeira e furadeira", "comparacao"),
    ("roomba vs roborock", "comparacao"), ("gan charger comparison", "comparacao"), ("ring vs eufy doorbell", "comparacao"),
    ("扫地机器人哪个好", "comparacao"), ("小米和华为手环对比", "comparacao"), ("projetor comparativo 2026", "comparacao"),
    ("capacete fechado ou articulado", "comparacao"), ("difference between humidifier and diffuser", "comparacao"),
    # review
    ("review aspirador robô xiaomi", "review"), ("air fryer philips vale a pena", "review"), ("fone qcy é bom", "review"),
    ("unboxing mini projetor", "review"), ("avaliação fechadura eletrônica", "review"), ("anker power bank review", "review"),
    ("is the dji mini worth it", "review"), ("tested: best smart plugs", "review"), ("空气炸锅评测", "review"),
    ("蓝牙耳机开箱", "review"), ("opinião sobre câmera intelbras", "review"), ("hands-on usb-c hub", "review"),
    # problema técnico
    ("air fryer não liga", "problema_tecnico"), ("fone bluetooth não conecta", "problema_tecnico"),
    ("carregador esquentando muito", "problema_tecnico"), ("aspirador robô parou de funcionar", "problema_tecnico"),
    ("smart plug not working", "problema_tecnico"), ("power bank won't charge", "problema_tecnico"),
    ("ring doorbell problem", "problema_tecnico"), ("充电宝不充电", "problema_tecnico"), ("门锁故障", "problema_tecnico"),
    ("câmera wi-fi piscando luz vermelha", "problema_tecnico"), ("projetor com defeito na imagem", "problema_tecnico"),
    # manutenção
    ("como limpar air fryer", "manutencao"), ("como trocar bateria da fechadura", "manutencao"),
    ("refil purificador de água", "manutencao"), ("peças para parafusadeira", "manutencao"),
    ("how to clean humidifier", "manutencao"), ("robot vacuum replacement brush", "manutencao"),
    ("how to reset smart plug", "manutencao"), ("空调清洗", "manutencao"), ("扫地机器人更换滤网", "manutencao"),
    ("como pintar capacete", "manutencao"), ("manual do umidificador", "manutencao"), ("helmet visor replacement", "manutencao"),
    # informação
    ("o que é carregador gan", "informacao"), ("como funciona sensor de presença", "informacao"),
    ("quanto consome um ventilador", "informacao"), ("what is a power station", "informacao"),
    ("how does a smart lock work", "informacao"), ("氮化镓是什么", "informacao"), ("para que serve umidificador", "informacao"),
    ("air fryer consumo de energia", "informacao"), ("what does anc mean", "informacao"), ("太阳能灯原理", "informacao"),
    # entretenimento
    ("capacete de personagem de anime", "entretenimento"), ("fantasia de capacete star wars", "entretenimento"),
    ("drone em filme", "entretenimento"), ("lego robot toy", "entretenimento"), ("minecraft lamp meme", "entretenimento"),
    ("cosplay helmet naruto", "entretenimento"), ("动漫头盔", "entretenimento"), ("desenho de robô aspirador", "entretenimento"),
    ("movie projector scene", "entretenimento"), ("pokemon lamp", "entretenimento"),
    # notícia
    ("samsung lança novo carregador 45w", "noticia"), ("recall de air fryer", "noticia"),
    ("xiaomi anuncia aspirador robô", "noticia"), ("apple unveils new magsafe charger", "noticia"),
    ("dji launches new drone", "noticia"), ("新款手机发布", "noticia"), ("空气炸锅召回", "noticia"),
    ("lançamento fechadura intelbras", "noticia"), ("anker recall power bank news", "noticia"), ("chega ao brasil novo projetor", "noticia"),
]
