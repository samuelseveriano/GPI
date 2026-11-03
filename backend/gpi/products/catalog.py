"""
Catálogo canônico de produtos (Categoria → Família → Produto → Variante), separado dos códigos
de comércio exterior.

* Sementes: produtos de referência (lista abaixo), passados pelo mesmo NLP que os termos reais —
  assim a chave conceitual da semente é idêntica à de um termo de busca equivalente.
* Descoberta: termos observados (Trends, notícias, reviews, títulos de vídeos, palavras-chave) que
  formam um produto ainda não catalogado entram como CANDIDATOS; são promovidos a produto quando
  aparecem com evidência suficiente (≥ 2 ocorrências, ou 1 ocorrência em fonte de busca).
* Deduplicação: mesma chave conceitual = mesmo produto, em qualquer idioma. Variantes técnicas
  (20W, 65W, 140W) ficam separadas, ligadas à mesma família.
* NCM/SH: somente a posição SH4 tecnicamente fundamentada para o núcleo do produto (lista curta);
  sem fundamento, fica vazio.
* Limites de memória: `catalog_max_products` (padrão 5.000) e `catalog_max_candidates` (20.000).
"""
from __future__ import annotations

import json
from collections import Counter

from ..market.store import now_iso
from ..market.taxonomy import CONCEPTS as WIKI_CONCEPTS
from . import nlp
from .lexicon import CONCEPTS

# Produtos de referência (termos em português; o NLP gera chave, nomes pt/en/zh e variante)
SEEDS = [
    "Carregador USB-C", "Carregador USB-C 20W", "Carregador USB-C 65W", "Carregador USB-C 140W", "Carregador GaN",
    "Carregador de iPhone", "Carregador sem fio", "Carregador veicular", "Cabo USB-C", "Power bank", "Power bank 20000mAh",
    "Capinha de celular", "Película", "Suporte de celular", "Smartwatch", "Fone Bluetooth", "Fone de ouvido com cancelamento de ruído",
    "Caixa de som Bluetooth", "Soundbar", "Microfone sem fio", "Mini projetor", "Projetor 4K", "TV box", "Câmera de ação",
    "Ring light", "Estabilizador de celular", "Mouse sem fio", "Teclado gamer", "Monitor gamer", "Roteador Wi-Fi", "Hub USB-C",
    "SSD", "Controle gamer", "Fechadura eletrônica", "Fechadura inteligente", "Câmera Wi-Fi", "Câmera Wi-Fi externa",
    "Campainha inteligente", "Sensor de presença", "Tomada inteligente", "Interruptor inteligente", "Alarme residencial",
    "Assistente virtual Alexa", "Luminária LED", "Luminária solar", "Lâmpada LED", "Lâmpada inteligente", "Fita LED",
    "Lanterna recarregável", "Refletor LED solar", "Air fryer", "Liquidificador portátil", "Cafeteira elétrica",
    "Chaleira elétrica", "Panela elétrica de arroz", "Sanduicheira", "Purificador de água", "Seladora a vácuo",
    "Aspirador robô", "Aspirador de pó sem fio", "Ventilador portátil", "Ventilador de teto", "Ar-condicionado portátil",
    "Umidificador de ar", "Desumidificador", "Purificador de ar", "Aquecedor elétrico", "Difusor de aromas",
    "Parafusadeira sem fio", "Furadeira de impacto", "Serra circular", "Esmerilhadeira", "Lavadora de alta pressão",
    "Multímetro", "Nível a laser", "Kit de ferramentas", "Capacete de moto", "Retrovisor de moto", "Intercomunicador para capacete",
    "Câmera veicular", "Compressor de ar portátil", "Luva de moto", "Jaqueta de moto", "Suporte de celular para moto",
    "Secador de cabelo", "Chapinha", "Barbeador elétrico", "Escova de dentes elétrica", "Pistola de massagem", "Balança digital",
    "Oxímetro", "Medidor de pressão", "Drone", "Patinete elétrico", "Garrafa térmica", "Mochila", "Barraca",
    "Babá eletrônica", "Comedouro automático", "Bebedouro para gato", "Painel solar", "Inversor", "Gerador portátil",
]

# SH4 apenas quando a classificação do núcleo é inequívoca (Sistema Harmonizado)
NCM_HINT = {"charger": "8504", "car_charger": "8504", "power_bank": "8507", "cable": "8544", "earbuds": "8518",
            "speaker": "8518", "soundbar": "8518", "microphone": "8518", "helmet": "6506", "lock": "8301",
            "bulb": "8539", "lamp": "9405", "led_strip": "9405", "flashlight": "8513", "headlamp": "8513",
            "camera": "8525", "action_camera": "8525", "dash_cam": "8525", "webcam": "8525", "vacuum": "8508",
            "drill": "8467", "saw": "8467", "grinder": "8467", "air_fryer": "8516", "kettle": "8516",
            "coffee_maker": "8516", "hair_dryer": "8516", "hair_straightener": "8516", "projector": "8528",
            "monitor": "8528", "fan": "8414", "shaver": "8510", "smartphone": "8517", "smartwatch": "8517",
            "router": "8517", "drone": "8806", "mouse": "8471", "keyboard": "8471", "ssd": "8471",
            "blender": "8509", "juicer": "8509", "toothbrush": "8509", "multimeter": "9030", "solar_panel": "8541",
            "inverter": "8504", "thermometer": "9025", "scale": "8423", "food_scale": "8423", "plug": "8536",
            "switch": "8536", "air_conditioner": "8415"}
NCM_EXCEPT = {("mirror", "motorcycle"): "7009", ("mirror", "car"): "7009"}


class Catalog:
    def __init__(self, db, cfg: dict | None = None):
        self.db = db
        cfg = cfg or {}
        self.max_products = int(cfg.get("catalog_max_products", 5000))
        self.max_candidates = int(cfg.get("catalog_max_candidates", 20000))

    # -------------------------------------------------------------------- sementes
    def ensure_seeded(self) -> int:
        import hashlib
        sig = hashlib.sha256(json.dumps([SEEDS, sorted(WIKI_CONCEPTS), sorted(NCM_HINT.items())], ensure_ascii=False)
                             .encode()).hexdigest()[:16]
        done = self.db.query("SELECT payload FROM analysis_results WHERE name = 'catalog_seed'")
        if done and json.loads(done[0]["payload"]).get("sig") == sig:
            return 0                                   # sementes já aplicadas nesta versão
        with self.db.transaction():
            n = self._seed()
            self.db.execute("INSERT OR REPLACE INTO analysis_results (name, created_at, payload) VALUES ('catalog_seed', ?, ?)",
                            (now_iso(), json.dumps({"sig": sig, "novos": n})))
        return n

    def _seed(self) -> int:
        have = {r["product_id"] for r in self.db.query("SELECT product_id FROM catalog_products")}
        n = 0
        for term in SEEDS:
            a = nlp.analyze(term, "pt")
            if not a["produto"]:
                continue
            pid = self._upsert_from_analysis(a, origin="semente", evidence=0, alias_lang="pt")
            n += pid not in have
        # artigos da Wikipédia monitorados → produto do catálogo (para ligar as visualizações)
        for title in WIKI_CONCEPTS:
            a = nlp.analyze(title, "en")
            if a["produto"]:
                fam = self._upsert_from_analysis(a, origin="semente", evidence=0, alias_lang="en", variant=False)
                self.db.execute("UPDATE catalog_products SET wiki_en = COALESCE(wiki_en, ?) WHERE product_id = ?",
                                (title, fam))
        return n

    def _upsert_from_analysis(self, a: dict, origin: str, evidence: int = 1, alias_lang: str | None = None,
                              variant: bool = True) -> str:
        p, ts = a["produto"], now_iso()
        fam = p["chave"]
        head = p["nucleo"]
        ncm = NCM_EXCEPT.get((head, next((m for m in p["qualificadores"] if (head, m) in NCM_EXCEPT), None)),
                             NCM_HINT.get(head))
        with self.db.lock:
            cur = self.db.query("SELECT product_id FROM catalog_products WHERE product_id = ?", (fam,))
            if cur:
                self.db.execute("UPDATE catalog_products SET last_seen = ?, evidence = evidence + ? WHERE product_id = ?",
                                (ts, evidence, fam))
            else:
                self.db.execute(
                    "INSERT INTO catalog_products (product_id, canonical, name_pt, name_en, name_zh, category, family,"
                    " level, parent_id, attributes, ncm_hint, origin, first_seen, last_seen, evidence)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 'produto', NULL, ?, ?, ?, ?, ?, ?)",
                    (fam, p["nome_pt"], p["nome_pt"], p["nome_en"], p["nome_zh"], p["categoria"], head,
                     json.dumps({"qualificadores": p["qualificadores"]}, ensure_ascii=False), ncm, origin, ts, ts, evidence))
            out = fam
            if variant and p["variante"]:
                vid = f"{fam}:{p['variante']}"
                if self.db.query("SELECT 1 FROM catalog_products WHERE product_id = ?", (vid,)):
                    self.db.execute("UPDATE catalog_products SET last_seen = ?, evidence = evidence + ? WHERE product_id = ?",
                                    (ts, evidence, vid))
                else:
                    attrs = {k: v for k, v in a["atributos"].items() if k in nlp.VARIANT_ATTRS or k in ("conector", "tecnologia")}
                    self.db.execute(
                        "INSERT INTO catalog_products (product_id, canonical, name_pt, name_en, name_zh, category, family,"
                        " level, parent_id, attributes, ncm_hint, origin, first_seen, last_seen, evidence)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, 'variante', ?, ?, ?, ?, ?, ?, ?)",
                        (vid, f"{p['nome_pt']} {p['variante'].upper()}", f"{p['nome_pt']} {p['variante'].upper()}",
                         f"{p['nome_en']} {p['variante'].upper()}", f"{p['variante'].upper()}{p['nome_zh']}",
                         p["categoria"], head, fam, json.dumps(attrs, ensure_ascii=False), ncm, origin, ts, ts, evidence))
                out = vid
            if alias_lang:
                self.add_alias(fam, a["texto"], alias_lang)
        return out

    def add_alias(self, pid: str, alias: str, lang: str):
        norm = nlp._norm(alias) if lang != "zh" else alias.strip().lower()
        if norm:
            self.db.execute("INSERT OR IGNORE INTO product_aliases (alias_norm, product_id, alias, lang) VALUES (?, ?, ?, ?)",
                            (norm[:200], pid, alias[:200], lang))

    # -------------------------------------------------------------------- correspondência e descoberta
    def match(self, text: str, lang: str | None = None) -> dict | None:
        """Produto do catálogo para um texto (família e, se houver, variante). None = sem produto
        ou produto ainda não catalogado."""
        a = nlp.analyze(text, lang)
        if not a["produto"]:
            return None
        fam = a["produto"]["chave"]
        if not self.db.query("SELECT 1 FROM catalog_products WHERE product_id = ?", (fam,)):
            return None
        var = f"{fam}:{a['produto']['variante']}" if a["produto"]["variante"] else None
        return {"familia": fam, "variante": var, "analise": a}

    def observe(self, term: str, source: str, country: str | None = None, intent: str | None = None,
                strong: bool = False, lang: str | None = None) -> str | None:
        """Registra um termo observado numa fonte. Devolve o product_id (família ou variante) se o
        termo corresponde a um produto catalogado ou recém-promovido; None caso contrário."""
        from . import discovery
        a = nlp.analyze(term, lang)
        if not a["produto"]:
            a = discovery.analyze(term, lang, self._aliases())
            if not a["produto"]:
                return None
        p, ts = a["produto"], now_iso()
        norm = nlp._norm(a["texto"]) if a["idioma"] != "zh" else a["texto"].lower()
        fam = p["chave"]
        exists = bool(self.db.query("SELECT 1 FROM catalog_products WHERE product_id = ?", (fam,)))
        with self.db.lock:
            row = self.db.query("SELECT * FROM discovery_candidates WHERE term_norm = ?", (norm[:200],))
            if row:
                r = row[0]
                srcs, ctys, ints = (Counter(json.loads(r[k] or "{}")) for k in ("sources", "countries", "intents"))
                occ = r["occurrences"] + 1
            else:
                if self._count("discovery_candidates") >= self.max_candidates:
                    return self._upsert_from_analysis(a, "descoberto", 1, a["idioma"]) if exists else None
                srcs, ctys, ints, occ = Counter(), Counter(), Counter(), 1
            srcs[source] += 1
            if country:
                ctys[country] += 1
            if intent:
                ints[intent] += 1
            promote = exists or strong or occ >= 2 or len(srcs) >= 2
            status = "promovido" if promote else "candidato"
            if promote and not exists and self._count("catalog_products") >= self.max_products:
                promote, status = False, "candidato"
            self.db.execute(
                "INSERT INTO discovery_candidates (term_norm, term, lang, head, family_hint, first_seen, last_seen,"
                " occurrences, sources, countries, intents, product_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(term_norm) DO UPDATE SET last_seen=excluded.last_seen, occurrences=excluded.occurrences,"
                " sources=excluded.sources, countries=excluded.countries, intents=excluded.intents,"
                " product_id=excluded.product_id, status=excluded.status",
                (norm[:200], a["texto"][:200], a["idioma"], p["nucleo"], fam, ts, ts, occ,
                 json.dumps(srcs), json.dumps(ctys), json.dumps(ints), fam if promote else None, status))
            if not promote:
                return None
            return self._upsert_from_analysis(a, "semente" if exists else "descoberto", 1, a["idioma"])

    def _aliases(self) -> list[tuple[str, str]]:
        if not hasattr(self, "_alias_cache"):
            self._alias_cache = [(r["alias"], r["product_id"]) for r in self.db.query(
                "SELECT alias, product_id FROM product_aliases WHERE lang <> 'zh' LIMIT 20000")]
        return self._alias_cache

    def _count(self, table: str) -> int:
        return int(self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])

    # -------------------------------------------------------------------- consultas
    def products(self, level: str | None = None) -> list[dict]:
        sql = "SELECT * FROM catalog_products" + (" WHERE level = ?" if level else "") + " ORDER BY category, canonical"
        rows = self.db.query(sql, (level,) if level else ())
        for r in rows:
            r["attributes"] = json.loads(r["attributes"] or "{}")
        return rows

    def get(self, pid: str) -> dict | None:
        r = self.db.query("SELECT * FROM catalog_products WHERE product_id = ?", (pid,))
        if not r:
            return None
        p = r[0]
        p["attributes"] = json.loads(p["attributes"] or "{}")
        fam = p["parent_id"] or p["product_id"]
        p["variantes"] = [v for v in self.db.query("SELECT product_id, canonical FROM catalog_products WHERE parent_id = ?"
                                                   " ORDER BY canonical", (fam,))]
        p["aliases"] = self.db.query("SELECT alias, lang FROM product_aliases WHERE product_id = ? ORDER BY lang, alias"
                                     " LIMIT 40", (fam,))
        p["relacionados"] = self.db.query(
            "SELECT product_id, canonical, CASE WHEN family = ? THEN 'mesma família' ELSE 'mesma categoria' END AS relacao"
            " FROM catalog_products WHERE level = 'produto' AND product_id <> ? AND (family = ? OR category = ?)"
            " ORDER BY (family = ?) DESC, evidence DESC LIMIT 12", (p["family"], fam, p["family"], p["category"], p["family"]))
        return p

    def candidates(self, status: str | None = None, limit: int = 200) -> list[dict]:
        rows = self.db.query("SELECT * FROM discovery_candidates" + (" WHERE status = ?" if status else "") +
                             " ORDER BY last_seen DESC, occurrences DESC LIMIT ?", ((status, limit) if status else (limit,)))
        for r in rows:
            for k in ("sources", "countries", "intents"):
                r[k] = json.loads(r[k] or "{}")
        return rows


def concept_of(pid: str) -> tuple[str, list[str]]:
    base = pid.split(":")[0]
    head, *mods = base.split("+")
    return head, mods


def label(pid: str) -> str:
    head, mods = concept_of(pid)
    if head not in CONCEPTS:
        return pid
    n = nlp.names_for(head, [m for m in mods if m in CONCEPTS])["nome_pt"]
    return n + (f" {pid.split(':')[1].upper()}" if ":" in pid else "")
