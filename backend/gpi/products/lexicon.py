"""
Léxico multilíngue (pt / en / zh) de conceitos de produto.

Cada conceito tem um id estável. Um termo de busca vira um CONJUNTO de conceitos — ex.:
  "carregador sem fio", "wireless charger" e "无线充电器" → {charger, wireless}
— e essa chave conceitual é o que identifica o produto em qualquer idioma (deduplicação
multilíngue determinística). Conceitos do tipo 'head' são o núcleo do produto (o que ele é);
'mod' são qualificadores que mudam o produto (sem fio, solar, robô, inteligente...).
Atributos numéricos (potência, capacidade...) NÃO fazem parte da chave: viram variantes.

Os termos em chinês são casados por máxima correspondência (o chinês não separa palavras).
"""
from __future__ import annotations

# id: (tipo, categoria (só para 'head'), [pt], [en], [zh])
CONCEPTS: dict[str, tuple] = {
    # ---- celulares, energia e acessórios
    "charger": ("head", "Celulares e acessórios", ["carregador", "carregadores", "fonte de celular"], ["charger", "chargers", "charging adapter", "power adapter"], ["充电器", "充电头"]),
    "cable": ("head", "Celulares e acessórios", ["cabo", "cabos"], ["cable", "cord"], ["数据线", "充电线"]),
    "power_bank": ("head", "Celulares e acessórios", ["power bank", "carregador portátil", "bateria externa", "bateria portátil"], ["power bank", "portable charger", "battery pack"], ["充电宝", "移动电源"]),
    "phone_case": ("head", "Celulares e acessórios", ["capinha", "capa de celular", "case de celular"], ["phone case"], ["手机壳"]),
    "screen_protector": ("head", "Celulares e acessórios", ["película", "pelicula"], ["screen protector", "tempered glass protector"], ["钢化膜", "手机膜"]),
    "phone_holder": ("head", "Celulares e acessórios", ["suporte de celular", "suporte para celular"], ["phone holder", "phone mount"], ["手机支架"]),
    "smartphone": ("head", "Celulares e acessórios", ["celular", "smartphone", "iphone", "galaxy"], ["smartphone", "cell phone", "iphone"], ["手机", "智能手机"]),
    "smartwatch": ("head", "Celulares e acessórios", ["smartwatch", "relógio inteligente", "relogio inteligente", "smartband", "pulseira inteligente"], ["smartwatch", "smart watch", "fitness tracker", "smart band"], ["智能手表", "智能手环"]),
    "stylus": ("head", "Informática", ["caneta touch", "caneta para tablet"], ["stylus", "stylus pen"], ["触控笔"]),
    # ---- áudio e vídeo
    "earbuds": ("head", "Áudio e vídeo", ["fone de ouvido", "fone bluetooth", "fones de ouvido", "fone", "headphone", "headset", "earbuds"], ["earbuds", "headphones", "earphones", "headset"], ["耳机", "蓝牙耳机"]),
    "speaker": ("head", "Áudio e vídeo", ["caixa de som", "caixinha de som", "alto-falante"], ["speaker", "bluetooth speaker"], ["音箱", "蓝牙音箱"]),
    "soundbar": ("head", "Áudio e vídeo", ["soundbar", "barra de som"], ["soundbar", "sound bar"], ["回音壁", "条形音箱"]),
    "microphone": ("head", "Áudio e vídeo", ["microfone"], ["microphone", "mic"], ["麦克风", "话筒"]),
    "projector": ("head", "Áudio e vídeo", ["projetor"], ["projector"], ["投影仪"]),
    "tv_box": ("head", "Áudio e vídeo", ["tv box", "receptor de tv"], ["tv box", "streaming box", "streaming stick"], ["电视盒子", "机顶盒"]),
    "action_camera": ("head", "Áudio e vídeo", ["câmera de ação", "camera de acao", "câmera esportiva"], ["action camera", "action cam"], ["运动相机"]),
    "ring_light": ("head", "Áudio e vídeo", ["ring light", "iluminador de anel"], ["ring light"], ["环形灯", "补光灯"]),
    "gimbal": ("head", "Áudio e vídeo", ["estabilizador de celular", "gimbal"], ["gimbal", "phone stabilizer"], ["稳定器"]),
    # ---- informática
    "mouse": ("head", "Informática", ["mouse"], ["mouse"], ["鼠标"]),
    "keyboard": ("head", "Informática", ["teclado"], ["keyboard"], ["键盘"]),
    "monitor": ("head", "Informática", ["monitor"], ["monitor"], ["显示器"]),
    "router": ("head", "Informática", ["roteador", "repetidor wi-fi", "repetidor wifi"], ["router", "wifi extender", "mesh wifi"], ["路由器"]),
    "webcam": ("head", "Informática", ["webcam"], ["webcam"], ["摄像头电脑", "网络摄像头"]),
    "usb_hub": ("head", "Informática", ["hub usb", "adaptador usb-c", "dock usb-c"], ["usb hub", "usb-c hub", "docking station"], ["扩展坞", "集线器"]),
    "ssd": ("head", "Informática", ["ssd"], ["ssd"], ["固态硬盘"]),
    "pendrive": ("head", "Informática", ["pendrive", "pen drive"], ["flash drive", "usb drive", "thumb drive"], ["u盘"]),
    "laptop_stand": ("head", "Informática", ["suporte para notebook"], ["laptop stand"], ["笔记本支架"]),
    "game_controller": ("head", "Informática", ["controle de videogame", "controle gamer", "joystick", "gamepad"], ["game controller", "gamepad", "controller"], ["游戏手柄", "手柄"]),
    # ---- casa inteligente e segurança
    "lock": ("head", "Casa inteligente e segurança", ["fechadura", "fechaduras"], ["lock", "door lock", "deadbolt"], ["门锁", "锁"]),
    "camera": ("head", "Casa inteligente e segurança", ["câmera", "camera", "câmeras", "cameras"], ["camera", "cameras", "cam"], ["摄像头", "监控摄像头", "摄像机"]),
    "doorbell": ("head", "Casa inteligente e segurança", ["campainha"], ["doorbell", "video doorbell"], ["门铃", "可视门铃"]),
    "motion_sensor": ("head", "Casa inteligente e segurança", ["sensor de presença", "sensor de presenca", "sensor de movimento"], ["motion sensor", "occupancy sensor", "pir sensor"], ["人体感应器", "人体传感器"]),
    "sensor": ("head", "Casa inteligente e segurança", ["sensor"], ["sensor"], ["传感器"]),
    "plug": ("head", "Casa inteligente e segurança", ["tomada", "tomadas", "plugue"], ["plug", "outlet", "socket"], ["插座", "插头"]),
    "switch": ("head", "Casa inteligente e segurança", ["interruptor"], ["light switch", "wall switch"], ["开关"]),
    "alarm": ("head", "Casa inteligente e segurança", ["alarme"], ["alarm", "alarm system"], ["报警器"]),
    "smart_speaker": ("head", "Casa inteligente e segurança", ["assistente virtual", "alexa", "echo dot", "google nest"], ["smart speaker", "echo dot", "alexa", "google nest"], ["智能音箱"]),
    "safe": ("head", "Casa inteligente e segurança", ["cofre"], ["safe", "safe box"], ["保险箱"]),
    # ---- iluminação
    "lamp": ("head", "Iluminação", ["luminária", "luminaria", "abajur", "luz", "refletor", "arandela", "spot"], ["lamp", "light", "floodlight", "fixture", "lights"], ["灯", "台灯", "灯具", "照明灯"]),
    "bulb": ("head", "Iluminação", ["lâmpada", "lampada", "lâmpadas", "lampadas"], ["bulb", "light bulb", "bulbs"], ["灯泡"]),
    "led_strip": ("head", "Iluminação", ["fita led", "fita de led", "mangueira led"], ["led strip", "led strip lights", "light strip"], ["灯带", "led灯带"]),
    "flashlight": ("head", "Iluminação", ["lanterna"], ["flashlight", "torch"], ["手电筒"]),
    "headlamp": ("head", "Iluminação", ["lanterna de cabeça", "lanterna de cabeca"], ["headlamp"], ["头灯"]),
    # ---- eletroportáteis e cozinha
    "air_fryer": ("head", "Eletroportáteis", ["air fryer", "fritadeira elétrica", "fritadeira eletrica", "fritadeira sem óleo", "fritadeira sem oleo", "airfryer"], ["air fryer", "airfryer"], ["空气炸锅"]),
    "blender": ("head", "Eletroportáteis", ["liquidificador", "mixer"], ["blender"], ["搅拌机", "破壁机", "料理机"]),
    "coffee_maker": ("head", "Eletroportáteis", ["cafeteira", "máquina de café", "maquina de cafe"], ["coffee maker", "espresso machine", "coffee machine"], ["咖啡机"]),
    "kettle": ("head", "Eletroportáteis", ["chaleira elétrica", "chaleira eletrica", "chaleira"], ["electric kettle", "kettle"], ["电水壶", "烧水壶"]),
    "rice_cooker": ("head", "Eletroportáteis", ["panela elétrica de arroz", "panela de arroz"], ["rice cooker"], ["电饭煲"]),
    "pressure_cooker": ("head", "Eletroportáteis", ["panela de pressão elétrica", "panela de pressao eletrica"], ["electric pressure cooker", "instant pot"], ["电压力锅"]),
    "sandwich_maker": ("head", "Eletroportáteis", ["sanduicheira", "grill elétrico", "grill eletrico"], ["sandwich maker", "electric grill"], ["三明治机", "电烤盘"]),
    "mixer": ("head", "Eletroportáteis", ["batedeira"], ["stand mixer", "hand mixer"], ["打蛋器", "厨师机"]),
    "juicer": ("head", "Eletroportáteis", ["espremedor", "centrífuga de suco", "extrator de suco"], ["juicer"], ["榨汁机"]),
    "water_purifier": ("head", "Eletroportáteis", ["purificador de água", "purificador de agua", "filtro de água"], ["water purifier", "water filter"], ["净水器"]),
    "food_scale": ("head", "Eletroportáteis", ["balança de cozinha", "balanca de cozinha"], ["kitchen scale"], ["厨房秤"]),
    "vacuum_sealer": ("head", "Eletroportáteis", ["seladora a vácuo", "seladora a vacuo"], ["vacuum sealer"], ["真空封口机"]),
    # ---- casa, limpeza e climatização
    "vacuum": ("head", "Casa e limpeza", ["aspirador", "aspirador de pó", "aspirador de po"], ["vacuum", "vacuum cleaner", "vacuums"], ["吸尘器", "扫地机"]),
    "mop": ("head", "Casa e limpeza", ["mop", "esfregão"], ["mop"], ["拖把"]),
    "fan": ("head", "Climatização", ["ventilador", "ventiladores", "circulador de ar"], ["fan", "fans"], ["风扇", "电风扇"]),
    "air_conditioner": ("head", "Climatização", ["ar-condicionado", "ar condicionado", "climatizador"], ["air conditioner", "air cooler"], ["空调", "冷风机"]),
    "humidifier": ("head", "Climatização", ["umidificador", "umidificador de ar"], ["humidifier"], ["加湿器"]),
    "dehumidifier": ("head", "Climatização", ["desumidificador"], ["dehumidifier"], ["除湿机"]),
    "air_purifier": ("head", "Climatização", ["purificador de ar"], ["air purifier"], ["空气净化器"]),
    "heater": ("head", "Climatização", ["aquecedor"], ["space heater", "heater"], ["取暖器", "暖风机"]),
    "diffuser": ("head", "Casa e limpeza", ["difusor de aromas", "difusor"], ["diffuser", "aroma diffuser"], ["香薰机"]),
    "organizer": ("head", "Casa e limpeza", ["organizador"], ["organizer"], ["收纳盒"]),
    # ---- ferramentas
    "drill": ("head", "Ferramentas", ["parafusadeira", "furadeira", "parafusadeiras"], ["drill", "cordless drill", "screwdriver drill", "impact driver"], ["电钻", "电动螺丝刀"]),
    "saw": ("head", "Ferramentas", ["serra", "serra circular", "serra tico-tico", "motosserra"], ["saw", "circular saw", "jigsaw", "chainsaw"], ["电锯", "锯"]),
    "grinder": ("head", "Ferramentas", ["esmerilhadeira", "lixadeira"], ["angle grinder", "sander"], ["角磨机", "砂光机"]),
    "pressure_washer": ("head", "Ferramentas", ["lavadora de alta pressão", "lavadora de alta pressao", "lavadora de pressão"], ["pressure washer"], ["高压清洗机", "洗车机"]),
    "multimeter": ("head", "Ferramentas", ["multímetro", "multimetro"], ["multimeter"], ["万用表"]),
    "soldering_iron": ("head", "Ferramentas", ["ferro de solda"], ["soldering iron"], ["电烙铁"]),
    "tool_kit": ("head", "Ferramentas", ["kit de ferramentas", "jogo de chaves"], ["tool kit", "tool set"], ["工具箱", "工具套装"]),
    "laser_level": ("head", "Ferramentas", ["nível a laser", "nivel a laser"], ["laser level"], ["激光水平仪"]),
    # ---- moto e automotivo
    "helmet": ("head", "Moto e automotivo", ["capacete", "capacetes"], ["helmet", "helmets"], ["头盔"]),
    "mirror": ("head", "Moto e automotivo", ["retrovisor", "retrovisores", "espelho retrovisor"], ["mirror", "rearview mirror", "side mirror", "mirrors"], ["后视镜"]),
    "intercom": ("head", "Moto e automotivo", ["intercomunicador"], ["intercom", "helmet intercom"], ["对讲机", "头盔对讲"]),
    "dash_cam": ("head", "Moto e automotivo", ["câmera veicular", "camera veicular", "dashcam"], ["dash cam", "dashcam"], ["行车记录仪"]),
    "tire_inflator": ("head", "Moto e automotivo", ["compressor de ar portátil", "calibrador de pneu", "enchedor de pneu"], ["tire inflator", "air compressor"], ["充气泵"]),
    "jump_starter": ("head", "Moto e automotivo", ["auxiliar de partida"], ["jump starter"], ["应急启动电源"]),
    "car_charger": ("head", "Moto e automotivo", ["carregador veicular", "carregador de carro"], ["car charger"], ["车载充电器"]),
    "gloves": ("head", "Moto e automotivo", ["luva", "luvas"], ["gloves"], ["手套"]),
    "motorcycle_jacket": ("head", "Moto e automotivo", ["jaqueta de moto", "jaqueta motociclista"], ["motorcycle jacket"], ["摩托车夹克", "骑行服"]),
    "gps": ("head", "Moto e automotivo", ["gps"], ["gps navigator"], ["导航仪"]),
    # ---- beleza e cuidados pessoais
    "hair_dryer": ("head", "Beleza e cuidados pessoais", ["secador de cabelo", "secador"], ["hair dryer"], ["吹风机"]),
    "hair_straightener": ("head", "Beleza e cuidados pessoais", ["chapinha", "prancha alisadora", "escova secadora", "modelador de cachos"], ["hair straightener", "flat iron", "curling iron", "hot air brush"], ["直发器", "卷发棒"]),
    "shaver": ("head", "Beleza e cuidados pessoais", ["barbeador", "aparador de pelos", "máquina de cortar cabelo", "maquina de cortar cabelo"], ["shaver", "trimmer", "hair clipper"], ["剃须刀", "理发器"]),
    "toothbrush": ("head", "Beleza e cuidados pessoais", ["escova de dentes elétrica", "escova de dentes eletrica", "escova elétrica"], ["electric toothbrush"], ["电动牙刷"]),
    "massager": ("head", "Saúde", ["massageador", "pistola de massagem"], ["massager", "massage gun"], ["按摩器", "筋膜枪"]),
    "scale": ("head", "Saúde", ["balança corporal", "balança digital", "balanca digital"], ["bathroom scale", "smart scale"], ["体重秤", "体脂秤"]),
    "thermometer": ("head", "Saúde", ["termômetro", "termometro"], ["thermometer"], ["温度计", "体温计"]),
    "oximeter": ("head", "Saúde", ["oxímetro", "oximetro"], ["pulse oximeter", "oximeter"], ["血氧仪"]),
    "blood_pressure": ("head", "Saúde", ["medidor de pressão", "medidor de pressao", "aparelho de pressão"], ["blood pressure monitor"], ["血压计"]),
    # ---- esporte, lazer, bebê, pet
    "drone": ("head", "Esporte e lazer", ["drone"], ["drone"], ["无人机"]),
    "scooter": ("head", "Esporte e lazer", ["patinete", "patinete elétrico", "patinete eletrico"], ["scooter", "electric scooter"], ["滑板车", "电动滑板车"]),
    "bike": ("head", "Esporte e lazer", ["bicicleta"], ["bike", "bicycle", "e-bike"], ["自行车"]),
    "water_bottle": ("head", "Esporte e lazer", ["garrafa térmica", "garrafa termica", "garrafa", "copo térmico", "copo termico"], ["water bottle", "insulated bottle", "tumbler"], ["保温杯", "水杯"]),
    "backpack": ("head", "Esporte e lazer", ["mochila"], ["backpack"], ["背包", "双肩包"]),
    "tent": ("head", "Esporte e lazer", ["barraca"], ["tent"], ["帐篷"]),
    "baby_monitor": ("head", "Bebês e brinquedos", ["babá eletrônica", "baba eletronica"], ["baby monitor"], ["婴儿监视器"]),
    "toy": ("head", "Bebês e brinquedos", ["brinquedo"], ["toy"], ["玩具"]),
    "pet_feeder": ("head", "Pet", ["comedouro automático", "comedouro automatico", "alimentador automático"], ["automatic pet feeder", "pet feeder"], ["自动喂食器", "喂食器"]),
    "pet_fountain": ("head", "Pet", ["bebedouro para gato", "fonte para gatos", "bebedouro pet"], ["pet fountain", "cat water fountain"], ["宠物饮水机"]),
    "solar_panel": ("head", "Energia", ["painel solar", "placa solar"], ["solar panel"], ["太阳能板", "太阳能电池板"]),
    "inverter": ("head", "Energia", ["inversor"], ["inverter", "power inverter"], ["逆变器"]),
    "power_station": ("head", "Energia", ["estação de energia", "gerador portátil", "gerador portatil"], ["portable power station", "power station"], ["户外电源", "便携式电源站"]),
    # ---- qualificadores (mudam o produto)
    "wireless": ("mod", None, ["sem fio", "wireless", "bluetooth"], ["wireless", "cordless", "bluetooth"], ["无线", "蓝牙"]),
    "smart": ("mod", None, ["inteligente", "smart", "Wi-Fi", "wifi"], ["smart", "Wi-Fi", "wifi"], ["智能"]),
    "solar": ("mod", None, ["solar"], ["solar"], ["太阳能"]),
    "robot": ("mod", None, ["robô", "robo", "robótico", "robotico"], ["robot", "robotic", "robo"], ["机器人", "扫地机器人"]),
    "portable": ("mod", None, ["portátil", "portatil", "mini"], ["portable", "mini"], ["便携", "便携式", "迷你"]),
    "led": ("mod", None, ["LED"], ["LED"], ["LED"]),
    "fast": ("mod", None, ["rápido", "rapido", "turbo"], ["fast", "quick", "rapid"], ["快充", "快速"]),
    "usb_c": ("mod", None, ["USB-C", "usb c", "tipo c", "tipo-c", "type-c"], ["USB-C", "usb c", "type-c", "type c"], ["type-c"]),
    "magsafe": ("mod", None, ["MagSafe", "magnético", "magnetico"], ["MagSafe", "magnetic"], ["磁吸"]),
    "gan": ("mod", None, ["GaN"], ["GaN"], ["氮化镓"]),
    "motorcycle": ("mod", None, ["de moto", "moto", "motocicleta", "motociclista"], ["motorcycle", "motorbike", "moto"], ["摩托车", "摩托"]),
    "car": ("mod", None, ["automotivo", "carro", "veicular"], ["car", "vehicle", "automotive"], ["汽车", "车载"]),
    "electronic": ("mod", None, ["eletrônica", "eletronica", "eletrônico", "eletronico", "biométrica", "biometrica", "digital"], ["electronic", "biometric", "keyless", "fingerprint"], ["电子", "指纹"]),
    "outdoor": ("mod", None, ["externa", "externo", "área externa", "jardim"], ["outdoor", "garden"], ["户外", "室外"]),
    "noise_cancel": ("mod", None, ["cancelamento de ruído", "cancelamento de ruido", "anc"], ["noise cancelling", "noise canceling", "anc"], ["降噪"]),
    "gamer": ("mod", None, ["gamer"], ["gaming"], ["电竞", "游戏"]),
    "rechargeable": ("mod", None, ["recarregável", "recarregavel"], ["rechargeable"], ["充电式"]),
    "presence": ("mod", None, ["presença", "presenca", "movimento"], ["motion", "occupancy"], ["人体感应"]),
    "iphone_compat": ("mod", None, ["de iphone", "para iphone", "iphone"], ["for iphone", "iphone"], ["苹果"]),
}

HEADS = {k for k, v in CONCEPTS.items() if v[0] == "head"}
MODS = {k for k, v in CONCEPTS.items() if v[0] == "mod"}

# Qualificadores de busca que NÃO fazem parte do produto (removidos na normalização)
QUALIFIERS = {
    "pt": {"melhor", "melhores", "barato", "barata", "baratos", "comprar", "compra", "preço", "preco", "promoção",
           "promocao", "oferta", "review", "resenha", "avaliação", "avaliacao", "vale", "pena", "qual", "quais",
           "novo", "nova", "original", "custo", "benefício", "beneficio", "top", "ranking", "como", "usar", "onde",
           "para", "pra", "de", "do", "da", "dos", "das", "com", "e", "o", "a", "os", "as", "um", "uma", "no", "na",
           "em", "por", "mais", "kit", "lançamento", "lancamento", "ou", "vs", "x", "é", "bom", "boa"},
    "en": {"best", "cheap", "cheapest", "buy", "price", "deal", "deals", "sale", "review", "reviews", "top", "new",
           "vs", "versus", "the", "a", "an", "for", "with", "and", "or", "of", "to", "how", "what", "which", "is",
           "near", "me", "good", "budget", "rated", "amazon", "walmart", "in", "on", "under", "worth", "it"},
}
STOP_ZH = {"最好", "推荐", "哪个", "好", "便宜", "价格", "多少钱", "评测", "怎么", "的", "什么", "排行", "排行榜"}

# Marcas frequentes (atributo 'marca'; não definem o produto)
BRANDS = {"apple", "samsung", "xiaomi", "redmi", "motorola", "lg", "sony", "jbl", "philips", "mondial", "britania",
          "britânia", "arno", "electrolux", "midea", "intelbras", "positivo", "multilaser", "anker", "baseus", "ugreen",
          "dji", "gopro", "bosch", "makita", "dewalt", "black+decker", "black decker", "wap", "karcher", "kärcher",
          "ls2", "shoei", "agv", "norisk", "pro tork", "protork", "ebf", "x11", "givi", "tp-link", "tplink", "huawei",
          "honor", "realme", "oppo", "vivo", "oneplus", "lenovo", "dell", "hp", "asus", "acer", "logitech", "razer",
          "redragon", "edifier", "qcy", "haylou", "amazfit", "garmin", "positivo casa inteligente", "tuya", "sonoff",
          "eufy", "roborock", "ecovacs", "irobot", "roomba", "dreame", "wyze", "ring", "arlo", "yale", "papaiz",
          "ninja", "cuisinart", "oster", "walita", "cadence", "elgin", "kabum", "tramontina", "stanley", "mi"}
