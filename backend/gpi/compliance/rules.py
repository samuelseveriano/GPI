"""Camada 1b — regras determinísticas e rastreáveis (cada resultado cita a regra, as características e os documentos).

Estados (seção 12 da especificação):
1 EXIGÊNCIA IDENTIFICADA · 2 POTENCIAL EXIGÊNCIA · 3 NÃO IDENTIFICADA NAS FONTES CONSULTADAS (não é dispensa) ·
4 INFORMAÇÕES INSUFICIENTES · 5 REVISÃO ESPECIALIZADA NECESSÁRIA.
Não existe estado de liberação de importação: a triagem nunca autoriza a operação.
"""
from __future__ import annotations

from .features import LABEL

STATE_LABEL = {1: "EXIGÊNCIA IDENTIFICADA", 2: "POTENCIAL EXIGÊNCIA", 3: "NÃO IDENTIFICADA NAS FONTES CONSULTADAS",
               4: "INFORMAÇÕES INSUFICIENTES", 5: "REVISÃO ESPECIALIZADA NECESSÁRIA"}
NOT_DISPENSA = ("Este resultado NÃO representa dispensa oficial: a ausência de regra na base consultada não equivale à "
                "inexistência de obrigação legal.")


def _v(f, k):
    return f["caracteristicas"].get(k, {}).get("valor")


def _ev(f, keys):
    return [f"{LABEL.get(k, k)} — {f['caracteristicas'][k]['origem']}: “{f['caracteristicas'][k]['evidencia'][:120]}”"
            for k in keys if k in f["caracteristicas"] and f["caracteristicas"][k]["valor"]]


def finding(orgao, estado, titulo, regra, motivo, docs, evidencias=None, perguntas=None, documentos_solicitar=None,
            proxima_acao=None, tipo="exigência"):
    return {"orgao": orgao, "estado": estado, "estado_rotulo": STATE_LABEL[estado], "titulo": titulo, "regra": regra,
            "tipo": tipo, "motivo": motivo, "evidencias": evidencias or [], "documentos": docs, "perguntas": perguntas or [],
            "documentos_solicitar": documentos_solicitar or [], "proxima_acao": proxima_acao,
            "observacao": NOT_DISPENSA if estado == 3 else None}


ANATEL_DOCS = ["anatel-res-715-2019", "anatel-res-780-2025", "anatel-servico-homologacao", "anatel-lgt-9472-1997"]


def anatel(f: dict) -> list[dict]:
    op = f["operacao"]
    radios = [k for k in ("wifi", "bluetooth", "rf", "celular") if _v(f, k)]
    unknown = [k for k in ("wifi", "bluetooth", "rf", "celular") if k in f["caracteristicas"] and _v(f, k) is None]
    declared_no = all(_v(f, k) is False for k in ("wifi", "bluetooth", "rf", "celular"))
    docs = list(ANATEL_DOCS)
    if any(k in radios for k in ("wifi", "bluetooth", "rf")):
        docs.insert(2, "anatel-res-680-2017")
    pedir = ["Nome do fabricante e modelo técnico exatos (como na etiqueta)", "Frequências de operação e potência de transmissão",
             "Fabricante/modelo do módulo de rádio e certificações existentes", "Relatórios de ensaio de radiofrequência existentes"]
    acao = ("Verificar se o modelo exato já possui homologação Anatel (consulta pública/dados abertos). Se não houver, a "
            "homologação é solicitada pelo procedimento oficial (Organismo de Certificação Designado e Anatel) antes da "
            "comercialização.")
    if radios:
        if op["amostra_ensaio"] or op["uso_proprio"]:
            return [finding("Anatel", 5, "Produto com radiocomunicação para uso próprio ou amostra", "ANATEL-RF-02",
                            "O produto possui transmissor de radiofrequência, mas a operação informada não é de "
                            "comercialização. As condições para uso próprio e para amostras de ensaio diferem das de "
                            "comercialização e precisam ser confirmadas no procedimento oficial.",
                            docs, _ev(f, radios), ["Quantidade de unidades e finalidade exata da importação"], pedir,
                            "Confirmar com a Anatel/OCD o procedimento aplicável à operação informada.")]
        if op["componente"]:
            return [finding("Anatel", 2, "Componente/módulo de radiocomunicação", "ANATEL-RF-03",
                            "Componentes com transmissor de RF podem ter homologação própria (módulo) e o produto final "
                            "que os integra pode precisar de homologação específica. Depende do enquadramento técnico.",
                            docs, _ev(f, radios), ["O módulo será vendido separadamente ou integrado a outro produto?"],
                            pedir, acao)]
        estado = 1 if op["comercializacao"] else 2
        perguntas = [] if op["comercializacao"] else ["A importação é para comercialização, uso próprio ou amostra?"]
        return [finding("Anatel", estado, "Homologação de produto para telecomunicações", "ANATEL-RF-01",
                        "Produto informado/descrito com transmissor de radiofrequência (" + ", ".join(LABEL[k] for k in radios) +
                        "). Produtos para telecomunicações, inclusive equipamentos de radiocomunicação, dependem de "
                        "avaliação da conformidade e homologação da Anatel; marketplaces respondem solidariamente pela "
                        "oferta de produtos não homologados.", docs, _ev(f, radios), perguntas, pedir, acao)]
    if unknown or not declared_no:
        return [finding("Anatel", 4, "Comunicação sem fio não confirmada", "ANATEL-RF-00",
                        "Não há informação suficiente sobre Wi-Fi, Bluetooth, celular ou outro transmissor de RF.",
                        ["anatel-res-715-2019"], [],
                        ["O produto possui Wi-Fi, Bluetooth, comunicação celular, NFC/RFID ou controle remoto por rádio?",
                         "Se sim: quais frequências e qual módulo de rádio?"],
                        ["Especificação técnica com a lista de interfaces de comunicação"])]
    return [finding("Anatel", 3, "Nenhuma exigência Anatel identificada", "ANATEL-RF-NA",
                    "Informado sem Wi-Fi, Bluetooth, celular ou outro transmissor de RF; a base não contém regra Anatel "
                    "correspondente para as demais características.", ["anatel-res-715-2019"], [])]


def inmetro(f: dict) -> list[dict]:
    out = []
    op = f["operacao"]
    if _v(f, "brinquedo"):
        out.append(finding("Inmetro", 1 if op["comercializacao"] else 2, "Brinquedos — certificação compulsória",
                           "INMETRO-BRINQ-01",
                           "Produto informado como brinquedo. O regulamento consolidado de brinquedos exige avaliação da "
                           "conformidade (certificação), registro no Inmetro e selo de identificação; os anexos definem o "
                           "que é e o que não é considerado brinquedo.",
                           ["inmetro-port-302-2021", "inmetro-registro-consulta", "inmetro-lei-9933-1999"],
                           _ev(f, ["brinquedo", "infantil"]),
                           [] if op["comercializacao"] else ["A importação é para comercialização?"],
                           ["Faixa etária indicada", "Relatórios de ensaio de segurança de brinquedos", "Lista de materiais",
                            "Projeto de marcação/etiquetagem e advertências"],
                           "Confirmar o enquadramento nos anexos da Portaria e verificar certificado/registro do modelo exato."))
    elif _v(f, "infantil"):
        out.append(finding("Inmetro", 2, "Produto destinado a crianças", "INMETRO-INF-01",
                           "Produto destinado a crianças pode ser enquadrado como brinquedo ou em outro regulamento "
                           "infantil, conforme a função e os anexos de exclusão.",
                           ["inmetro-port-302-2021", "inmetro-lei-9933-1999"], _ev(f, ["infantil"]),
                           ["O produto é usado para brincar por menores de 14 anos?", "Qual a faixa etária?"]))
    if _v(f, "alimentacao_rede") and not _v(f, "carregador_fonte") and not _v(f, "led_iluminacao"):
        out.append(finding("Inmetro", 2, "Aparelho elétrico ligado à rede — verificar escopo de eletrodomésticos",
                           "INMETRO-ELETRO-01",
                           "Produto com alimentação pela rede elétrica pode estar no escopo da Portaria de aparelhos "
                           "eletrodomésticos e similares; a Tabela 2 do Anexo III lista exclusões (ex.: classe III, "
                           "produtos com regulamento próprio, uso exclusivamente industrial, equipamentos médicos).",
                           ["inmetro-port-148-2022", "inmetro-registro-consulta", "inmetro-lei-9933-1999"],
                           _ev(f, ["alimentacao_rede"]),
                           ["Qual a função principal do aparelho e o ambiente de uso (doméstico, comercial, industrial)?",
                            "Classe de isolação (I, II ou III)?", "Possui regulamento Inmetro próprio (ex.: iluminação, carregadores)?"],
                           ["Especificações elétricas (tensão, potência, classe de isolação)", "Manual do usuário",
                            "Relatórios de ensaio de segurança elétrica existentes"],
                           "Conferir o escopo e as exclusões da Portaria e o Banco de Registro do Inmetro para o modelo exato."))
    if _v(f, "carregador_fonte") or _v(f, "bateria_litio"):
        out.append(finding("Inmetro", 5, "Carregadores, fontes ou baterias de lítio", "INMETRO-ENERGIA-01",
                           "Carregadores, fontes de alimentação e produtos com baterias de lítio podem ter regulamentos "
                           "técnicos específicos do Inmetro. A base local do GPI não contém, nesta versão, a portaria "
                           "aplicável a cada um desses produtos.",
                           ["inmetro-lei-9933-1999", "inmetro-registro-consulta"],
                           _ev(f, ["carregador_fonte", "bateria_litio"]),
                           ["Tipo exato (carregador de parede, fonte, power bank, bateria avulsa ou integrada)?",
                            "Tensão/corrente de saída e capacidade da bateria (mAh e Wh)?"],
                           ["Especificação elétrica de entrada/saída", "Especificação da célula/bateria (química, mAh, Wh)",
                            "Relatórios de ensaio de segurança existentes"],
                           "Consultar a regulamentação do Inmetro para o tipo exato e o Banco de Registro."))
    if _v(f, "led_iluminacao") and _v(f, "alimentacao_rede"):
        out.append(finding("Inmetro", 5, "Iluminação/LED ligada à rede", "INMETRO-LUZ-01",
                           "Produtos de iluminação podem ter regulamento próprio do Inmetro, fora do escopo de "
                           "eletrodomésticos. A base local do GPI não contém a portaria específica nesta versão.",
                           ["inmetro-port-148-2022", "inmetro-lei-9933-1999", "inmetro-registro-consulta"],
                           _ev(f, ["led_iluminacao", "alimentacao_rede"]),
                           ["É lâmpada, luminária, fita LED ou outro? Possui driver/fonte integrada?"]))
    if _v(f, "instrumento_medicao"):
        out.append(finding("Inmetro", 5, "Instrumento de medição", "INMETRO-METRO-01",
                           "Instrumentos de medição podem estar sujeitos ao controle metrológico legal do Inmetro "
                           "(aprovação de modelo e verificações), conforme o tipo e o uso (comercial, saúde, segurança).",
                           ["inmetro-lei-9933-1999"], _ev(f, ["instrumento_medicao"]),
                           ["O instrumento será usado em transações comerciais, saúde ou segurança?", "Qual grandeza mede?"]))
    if not out:
        relevant = [k for k in ("alimentacao_rede", "brinquedo", "infantil", "instrumento_medicao", "carregador_fonte")
                    if k in f["caracteristicas"]]
        if not relevant:
            out.append(finding("Inmetro", 4, "Características para o Inmetro não informadas", "INMETRO-00",
                               "Faltam informações sobre alimentação elétrica, público infantil, função de medição e tipo "
                               "de produto para verificar programas de avaliação da conformidade compulsória.",
                               ["inmetro-lei-9933-1999"], [],
                               ["O produto é ligado à rede elétrica? Usa bateria? É destinado a crianças? Mede alguma grandeza?"]))
        else:
            out.append(finding("Inmetro", 3, "Nenhuma exigência Inmetro identificada na base", "INMETRO-NA",
                               "As características informadas não correspondem às regras do Inmetro presentes na base local.",
                               ["inmetro-lei-9933-1999", "inmetro-registro-consulta"]))
    return out


def receita(f: dict, ncm_info: dict | None) -> list[dict]:
    docs = ["rfb-classificacao-fiscal", "siscomex-classif", "siscomex-tabela-ncm"]
    if not ncm_info or not ncm_info.get("codigo"):
        return [finding("Receita Federal", 4, "NCM não informada", "RFB-NCM-00",
                        "A classificação fiscal (NCM) é necessária para a declaração de importação, tributos e para "
                        "consultar o tratamento administrativo. Sem a NCM e as especificações técnicas, não é possível "
                        "concluir a classificação.", docs, [],
                        ["Função principal, materiais, forma de alimentação e componentes do produto",
                         "O fornecedor indica algum código HS? (é apenas referência — os 6 primeiros dígitos do SH)"],
                        ["Especificação técnica completa", "Código HS usado pelo exportador (referência)"],
                        "Usar o Sistema Classif e, havendo dúvida, a consulta formal de classificação da Receita Federal.",
                        tipo="classificação fiscal")]
    st = ncm_info.get("estado")
    if st == "valida":
        estado, motivo = 2, ("NCM em formato válido e encontrada na tabela local vigente. A correção da classificação não é "
                             "confirmada pelo GPI: depende das especificações, das notas legais e das notas explicativas.")
    elif st in ("inexistente", "expirada"):
        estado, motivo = 5, f"NCM informada {('não consta' if st == 'inexistente' else 'está fora de vigência')} na tabela oficial carregada."
    elif st == "formato_invalido":
        estado, motivo = 4, "Código NCM em formato inválido (são 8 dígitos, ex.: 8517.62.77)."
    else:
        estado, motivo = 2, "Tabela NCM oficial não carregada no GPI: formato conferido, existência e vigência não verificadas."
    if ncm_info.get("alertas"):           # heurística grosseira: vira pergunta, não muda o estado
        motivo += " Pontos a conferir na classificação: " + "; ".join(ncm_info["alertas"]) + "."
        ncm_info.setdefault("perguntas", []).append("A NCM informada considera todas as funções do produto (ex.: comunicação sem fio)?")
    return [finding("Receita Federal", estado, f"Classificação fiscal — NCM {ncm_info.get('codigo_formatado') or ncm_info.get('codigo')}",
                    "RFB-NCM-01", motivo, docs, [], ncm_info.get("perguntas", []), [],
                    "Validar a NCM no Sistema Classif e, se persistir dúvida, por consulta formal à Receita Federal.",
                    tipo="classificação fiscal")]


def siscomex(f: dict, ncm_info: dict | None, achados: list[dict]) -> list[dict]:
    docs = ["siscomex-tratamento-administrativo", "secex-port-249-2023", "siscomex-manual-lpco"]
    anuentes = sorted({a["orgao"] for a in achados if a["estado"] in (1, 2, 5) and a["orgao"] in ("Anatel", "Inmetro", "Anvisa", "MAPA", "Ibama", "Exército")})
    motivo = ("O tratamento administrativo (licenças, permissões e LPCO de órgãos anuentes) depende da NCM, do destaque, do "
              "país de origem e das condições da operação, e só pode ser confirmado no Simulador de Tratamento "
              "Administrativo do Portal Único. O GPI não presume que essas informações estejam disponíveis por API pública.")
    if anuentes:
        motivo += " Órgãos com exigência identificada ou potencial nesta análise: " + ", ".join(anuentes) + \
                  " — verificar se há anuência/LPCO para a NCM."
    valid = bool(ncm_info and ncm_info.get("estado") == "valida")
    return [finding("Siscomex", 5 if valid else 4, "Tratamento administrativo e LPCO — consulta oficial necessária",
                    "SISCOMEX-TA-01", motivo, docs, [],
                    [] if valid else ["NCM validada (8 dígitos) e condições da operação (país de origem, quantidade, finalidade)"],
                    [], "Consultar o Simulador de Tratamento Administrativo do Portal Único com a NCM validada.",
                    tipo="tratamento administrativo")]


def outros(f: dict) -> list[dict]:
    out = []
    if _v(f, "medico"):
        out.append(finding("Anvisa", 5, "Possível produto para saúde", "ANVISA-01",
                           "Produto descrito com finalidade médica/saúde: pode depender de regularização sanitária e de "
                           "anuência na importação. A base do GPI não contém regras detalhadas da Anvisa nesta versão.",
                           ["anvisa-portal", "siscomex-tratamento-administrativo"], _ev(f, ["medico"])))
    if _v(f, "contato_alimentos") or _v(f, "cosmetico"):
        out.append(finding("Anvisa", 5, "Contato com alimentos ou cosmético", "ANVISA-02",
                           "Materiais em contato com alimentos e cosméticos podem ter exigências sanitárias.",
                           ["anvisa-portal"], _ev(f, ["contato_alimentos", "cosmetico"])))
    if _v(f, "quimico"):
        out.append(finding("Ibama", 5, "Substância química", "IBAMA-01",
                           "Substâncias químicas podem ter controle ambiental ou de outros órgãos na importação.",
                           ["ibama-portal", "siscomex-tratamento-administrativo"], _ev(f, ["quimico"])))
    if _v(f, "controlado"):
        out.append(finding("Exército", 5, "Possível produto controlado", "EB-01",
                           "Informado como potencialmente controlado: exige análise especializada antes de qualquer importação.",
                           ["exercito-dfpc"], []))
    return out


def run(f: dict, ncm_info: dict | None) -> list[dict]:
    out = anatel(f) + inmetro(f) + outros(f)
    out += receita(f, ncm_info)
    out += siscomex(f, ncm_info, out)
    for i in f.get("indicios_nome", []):
        k = i["caracteristica"]
        q = f"O nome/categoria sugere “{i['rotulo']}” — o produto realmente possui essa característica?"
        org = "Anatel" if k in ("wifi", "bluetooth", "rf", "celular") else "Inmetro"
        tgt = next((a for a in out if a["orgao"] == org), None) or (out[0] if out else None)
        if tgt is not None and q not in tgt["perguntas"]:
            tgt["perguntas"].append(q)
    return out
