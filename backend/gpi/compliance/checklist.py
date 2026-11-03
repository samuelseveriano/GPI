"""Checklist Técnico para Importação (seção 15): perguntas e documentos a solicitar ao fabricante.

Português, inglês e chinês simplificado. O chinês usa terminologia técnica padrão preparada pelo GPI e é marcado como
"revisar antes de enviar" (não houve validação por tradutor humano). Certificados internacionais (CE, FCC, CCC…)
NÃO substituem automaticamente as certificações/homologações brasileiras.
"""
from __future__ import annotations

ZH_NOTE = "Tradução para chinês preparada pelo GPI com terminologia técnica padrão — revisar com o fornecedor ou tradutor antes de enviar."
INTL_NOTE = ("Certificados internacionais (ex.: CE, FCC, CCC, UKCA) e relatórios de ensaio estrangeiros podem ajudar, mas NÃO "
             "substituem automaticamente certificações, registros ou homologações exigidos no Brasil.")

BASE = [
    ("ident", "Technical Datasheet", "Ficha técnica completa do produto", "Complete technical datasheet of the product", "产品完整技术规格书"),
    ("ident", "Product Specification", "Especificação do produto (funções, dimensões, peso, materiais)",
     "Product specification (functions, dimensions, weight, materials)", "产品规格说明（功能、尺寸、重量、材料）"),
    ("ident", "User Manual", "Manual do usuário (preferencialmente com versão em português)", "User manual (Portuguese version preferred)",
     "用户手册（最好提供葡萄牙语版本）"),
    ("ident", "Manufacturer Information", "Razão social, endereço da fábrica e contato do fabricante (não do revendedor)",
     "Legal name, factory address and contact of the manufacturer (not the trader)", "制造商（非贸易商）的公司全称、工厂地址和联系方式"),
    ("ident", "Product Identification", "Marca, modelo técnico exato e variações de modelo", "Brand, exact technical model number and model variants",
     "品牌、确切的技术型号及型号变体"),
    ("ident", "Labeling Specifications", "Projeto da etiqueta/marcação do produto e da embalagem", "Product and packaging labeling/marking artwork",
     "产品及包装的标签/标识设计稿"),
    ("ident", "Component List", "Lista de componentes principais (BOM resumida)", "List of main components (summary BOM)", "主要元器件清单（简要BOM）"),
    ("ident", "Existing Certifications", "Certificados e relatórios de ensaio já existentes (qualquer país), com o modelo exato",
     "Existing certificates and test reports (any country) covering the exact model", "现有的证书和测试报告（任何国家），须涵盖确切型号"),
    ("ident", "HS Code", "Código HS usado na exportação (apenas referência para a NCM)", "HS code used for export (reference only)",
     "出口使用的HS编码（仅供参考）"),
]
COND = {
    "radio": [
        ("radio", "Wireless Module Information", "Fabricante e modelo do módulo de rádio (Wi-Fi/Bluetooth/celular) e certificações do módulo",
         "Manufacturer and model of the wireless module (Wi-Fi/Bluetooth/cellular) and module certifications",
         "无线模块（Wi-Fi/蓝牙/蜂窝）的制造商、型号及模块认证"),
        ("radio", "Radio Parameters", "Frequências de operação, potência de transmissão e tipo de antena",
         "Operating frequencies, transmit power and antenna type", "工作频率、发射功率和天线类型"),
        ("radio", "RF Test Reports", "Relatórios de ensaio de radiofrequência e compatibilidade eletromagnética existentes",
         "Existing radio frequency and EMC test reports", "现有的射频和电磁兼容测试报告"),
        ("radio", "Samples for Testing", "Disponibilidade de amostras para ensaios em laboratório no Brasil",
         "Availability of samples for laboratory testing in Brazil", "可否提供用于巴西实验室测试的样品"),
    ],
    "eletrico": [
        ("eletrico", "Electrical Specifications", "Tensão, frequência e potência nominais; classe de isolação; tipo de plugue",
         "Rated voltage, frequency and power; insulation class; plug type", "额定电压、频率和功率；绝缘等级；插头类型"),
        ("eletrico", "Safety Test Reports", "Relatórios de ensaio de segurança elétrica existentes (ex.: série IEC 60335 ou IEC 62368)",
         "Existing electrical safety test reports (e.g., IEC 60335 or IEC 62368 series)", "现有的电气安全测试报告（如IEC 60335或IEC 62368系列）"),
    ],
    "bateria": [
        ("bateria", "Battery Specifications", "Química da bateria, capacidade (mAh e Wh), tensão e fabricante da célula",
         "Battery chemistry, capacity (mAh and Wh), voltage and cell manufacturer", "电池化学类型、容量（mAh和Wh）、电压及电芯制造商"),
        ("bateria", "Battery Safety Documents", "Relatórios de ensaio de segurança da bateria e documentação de transporte (ex.: UN 38.3, ficha de segurança)",
         "Battery safety test reports and transport documents (e.g., UN 38.3, safety data sheet)", "电池安全测试报告及运输文件（如UN 38.3、安全数据表）"),
    ],
    "brinquedo": [
        ("brinquedo", "Age Grading", "Faixa etária indicada e advertências", "Intended age range and warnings", "适用年龄范围和警示语"),
        ("brinquedo", "Toy Safety Reports", "Relatórios de ensaio de segurança de brinquedos e lista de materiais/tintas",
         "Toy safety test reports and list of materials/paints", "玩具安全测试报告及材料/涂料清单"),
    ],
    "medicao": [
        ("medicao", "Metrological Specifications", "Grandeza medida, faixa, resolução e exatidão", "Measured quantity, range, resolution and accuracy",
         "测量的量、量程、分辨率和准确度"),
    ],
    "saude": [
        ("saude", "Health Product Status", "Finalidade de uso declarada e registros sanitários existentes", "Declared intended use and existing health registrations",
         "声明的预期用途及现有的卫生注册"),
    ],
}


def build(analysis: dict) -> dict:
    f = analysis.get("caracteristicas", {})

    def on(k):
        return bool(f.get(k, {}).get("valor"))
    groups = ["ident"]
    if any(on(k) for k in ("wifi", "bluetooth", "rf", "celular")):
        groups.append("radio")
    if on("alimentacao_rede") or on("carregador_fonte"):
        groups.append("eletrico")
    if on("bateria") or on("bateria_litio"):
        groups.append("bateria")
    if on("brinquedo") or on("infantil"):
        groups.append("brinquedo")
    if on("instrumento_medicao"):
        groups.append("medicao")
    if on("medico") or on("contato_alimentos") or on("cosmetico"):
        groups.append("saude")
    items = list(BASE)
    for g in groups[1:]:
        items += COND[g]
    extra = []
    for a in analysis.get("achados", []):
        for d in a.get("documentos_solicitar", []):
            dup = any(d == it[2] for it in items) or "HS" in d or d.startswith(("Especificação técnica completa", "Especificações elétricas"))
            if d not in extra and not dup:
                extra.append(d)
    rows = [{"grupo": g, "item": code, "pt": pt, "en": en, "zh": zh} for g, code, pt, en, zh in items]
    rows += [{"grupo": "achados", "item": "—", "pt": d, "en": None, "zh": None} for d in extra]
    return {"itens": rows, "grupos": groups, "aviso_internacional": INTL_NOTE, "aviso_traducao": ZH_NOTE,
            "produto": analysis.get("produto")}
