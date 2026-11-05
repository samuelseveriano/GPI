"""
Relatório em Excel (.xlsx) gerado localmente com openpyxl — não exige Microsoft Excel.

* Uma aba por seção (Resumo Executivo primeiro; Fontes e Metodologia sempre presente).
* Tabelas estruturadas do Excel (filtro próprio), cabeçalho formatado, painéis congelados,
  larguras ajustadas, números/porcentagens/datas no padrão brasileiro, hiperlinks para fontes,
  formatação condicional nos scores e no crescimento e gráficos nativos do Excel.
* Proteção contra injeção de fórmulas: textos vindos de APIs que começam com = + - @ ou
  caracteres de controle são gravados como TEXTO com o prefixo de citação do Excel (quotePrefix);
  as únicas fórmulas do arquivo são as do próprio GPI, em células conhecidas.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

INK, ACCENT, SIDE = "1B2330", "0F766E", "121A26"
HEAD_FILL = PatternFill("solid", fgColor=SIDE)
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color=INK)
SUB_FONT = Font(italic=True, size=9, color="5D6878")
DEMO_FILL = PatternFill("solid", fgColor="B91C1C")
THIN = Side(style="thin", color="E2E5EA")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")
FMT = {"pct": "0.0%", "numero": "#,##0.00", "inteiro": "#,##0", "score": "0.0", "data": "DD/MM/YYYY"}
SAFE_URL = re.compile(r"^https?://[^\s\"'<>]+$", re.I)


def safe_text(v: str) -> tuple[str, bool]:
    """Texto limpo + indicação de que precisa do prefixo de citação (não é fórmula)."""
    v = ILLEGAL_CHARACTERS_RE.sub("", str(v))
    return v, v.startswith(FORMULA_START)


def to_date(v):
    if isinstance(v, (date, datetime)):
        return v if isinstance(v, date) and not isinstance(v, datetime) else v.date()
    if not isinstance(v, str) or not v:
        return None
    s = v.strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    return None


def put(ws, row, col, v, kind="texto"):
    c = ws.cell(row=row, column=col)
    if v is None or v == "":
        return c
    if kind == "data":
        d = to_date(v)
        if d:
            c.value = d
            c.number_format = FMT["data"]
            return c
    if kind in ("pct", "numero", "inteiro", "score") and isinstance(v, (int, float)) and not isinstance(v, bool):
        c.value = float(v) if kind != "inteiro" else int(round(v))
        c.number_format = FMT[kind]
        return c
    if isinstance(v, bool):
        v = "sim" if v else "não"
    if isinstance(v, (int, float)):
        c.value = v
        return c
    text, quoted = safe_text(v)
    c.value = text[:32000]
    c.data_type = "s"
    if quoted:
        c.quotePrefix = True
    if kind == "link" and SAFE_URL.match(text):
        c.hyperlink = text
        c.font = Font(color="2563EB", underline="single")
    return c


def sheet_name(name: str, used: set) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", name)[:31]
    n, i = base, 2
    while n.lower() in used:
        n = f"{base[:27]} ({i})"
        i += 1
    used.add(n.lower())
    return n


class Writer:
    def __init__(self, ds: dict):
        self.ds = ds
        self.wb = Workbook()
        self.used = set()
        self.tables = 0
        self.refs = {}                      # id da tabela → (aba, coluna→letra, primeira, última linha)

    # ---------------------------------------------------------------- cabeçalho de aba
    def banner(self, ws, row: int, ncols: int) -> int:
        if self.ds.get("demo"):
            ws.cell(row=row, column=1, value="DEMONSTRAÇÃO — dados sintéticos ou de teste; não usar como dado real. "
                                             f"Motivo: {self.ds.get('demo_motivo')}")
            for c in range(1, max(ncols, 6) + 1):
                ws.cell(row=row, column=c).fill = DEMO_FILL
            ws.cell(row=row, column=1).font = Font(bold=True, color="FFFFFF")
            row += 1
        return row

    def write_table(self, ws, t: dict, row: int) -> int:
        cols = t["colunas"]
        ws.cell(row=row, column=1, value=t["titulo"]).font = Font(bold=True, size=12, color=ACCENT)
        row += 1
        ws.cell(row=row, column=1, value=f"Natureza do dado: {t['natureza']}").font = SUB_FONT
        row += 1
        if t.get("descricao"):
            put(ws, row, 1, t["descricao"]).font = SUB_FONT
            row += 1
        if not t["linhas"]:
            put(ws, row, 1, t["vazio"]).font = Font(italic=True, color="8A5300")
            row += 2
            for n in t.get("notas", []):
                put(ws, row, 1, "Nota: " + n).font = SUB_FONT
                row += 1
            return row + 1
        head = row
        seen = set()
        for j, c in enumerate(cols, start=1):
            label = c["rotulo"]
            while label in seen:                 # cabeçalhos de tabela do Excel precisam ser únicos
                label += " "
            seen.add(label)
            cell = ws.cell(row=row, column=j, value=label)
            cell.fill, cell.font = HEAD_FILL, HEAD_FONT
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[row].height = 32
        for r in t["linhas"]:
            row += 1
            for j, c in enumerate(cols, start=1):
                put(ws, row, j, r.get(c["id"]), c["tipo"]).border = Border(bottom=THIN)
        last = row
        self.tables += 1
        ref = f"A{head}:{get_column_letter(len(cols))}{last}"
        tb = Table(displayName=f"T{self.tables}_{re.sub(r'[^A-Za-z0-9_]', '_', t['id'])}"[:250], ref=ref)
        tb.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(tb)
        letters = {c["id"]: get_column_letter(j) for j, c in enumerate(cols, start=1)}
        self.refs[t["id"]] = (ws.title, letters, head + 1, last)
        for c in cols:                            # formatação condicional (qualidade, scores e crescimento)
            L = letters[c["id"]]
            rng = f"{L}{head + 1}:{L}{last}"
            if c["tipo"] == "score":
                ws.conditional_formatting.add(rng, ColorScaleRule(start_type="num", start_value=0, start_color="F8D7DA",
                                                                  mid_type="num", mid_value=50, mid_color="FFF3CD",
                                                                  end_type="num", end_value=100, end_color="D1E7DD"))
            elif c["tipo"] == "pct" and c["id"] in ("crescimento", "search_growth", "social_growth", "ganho"):
                ws.conditional_formatting.add(rng, ColorScaleRule(start_type="num", start_value=-0.5, start_color="F8D7DA",
                                                                  mid_type="num", mid_value=0, mid_color="FFFFFF",
                                                                  end_type="num", end_value=0.5, end_color="D1E7DD"))
        row += 1
        for n in t.get("notas", []):
            put(ws, row, 1, "Nota: " + n).font = SUB_FONT
            row += 1
        return row + 1

    def fit(self, ws, widths: dict):
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = max(9, min(60, w + 2))

    def measure(self, tables) -> dict:
        w = {}
        for t in tables:
            for j, c in enumerate(t["colunas"], start=1):
                lens = [min(len(c["rotulo"]), 28)] + [len(str(r.get(c["id"]) if r.get(c["id"]) is not None else ""))
                                                      for r in t["linhas"][:300]]
                if c["tipo"] == "data":
                    lens.append(11)
                w[j] = max(w.get(j, 0), max(lens))
        return w

    # ---------------------------------------------------------------- abas
    def summary(self):
        ds, m = self.ds, self.ds["meta"]
        ws = self.wb.active
        ws.title = sheet_name("Resumo Executivo", self.used)
        row = self.banner(ws, 1, 4)
        ws.cell(row=row, column=1, value=ds["titulo"]).font = TITLE_FONT
        row += 1
        put(ws, row, 1, ds["subtitulo"]).font = SUB_FONT
        row += 2
        meta_rows = [("Gerado em", m["gerado_em"].replace("T", " ")), ("Identificador da execução", m["run_id"]),
                     ("Versão do GPI", m["versao_software"]), ("Versão dos dados", m["versao_dados"]),
                     ("Análise de consumo de", m.get("analise_consumo")), ("Filtros aplicados", m["filtros_texto"]),
                     ("Fontes no recorte", ", ".join(m["fontes"]) or "nenhuma"),
                     ("Modelos", "; ".join(f"{x['modelo']} ({x.get('treinado_em') or '—'})" for x in m["modelos"][:6]) or "nenhum treinado"),
                     ("Critério dos rankings", m["criterios_ranking"])]
        for k, v in meta_rows:
            ws.cell(row=row, column=1, value=k).font = Font(bold=True)
            put(ws, row, 2, v)
            row += 1
        row += 1
        row = self.write_table(ws, ds["resumo"], row)
        ex = ds["texto"].get("executivo")
        if ex:
            for titulo, key in (("1. Resumo executivo", "resumo"),):
                ws.cell(row=row, column=1, value=titulo).font = Font(bold=True, size=12, color=ACCENT)
                row += 1
                for p in ex[key]:
                    put(ws, row, 1, p).alignment = Alignment(wrap_text=True, vertical="top")
                    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
                    ws.row_dimensions[row].height = 15 * max(1, len(p) // 95 + 1)
                    row += 1
                row += 1
            from .data import table
            for t in (table("panorama", "2. Panorama de mercado", [("indicador", "Indicador"), ("valor", "Valor"), ("natureza", "Natureza")],
                            ex["panorama"], "obs"),
                      table("destaques", "3. Produtos em destaque", [("produto", "Produto")], [{"produto": p} for p in ex["destaques"]], "der"),
                      table("internacional", "4. Tendências internacionais", [("produto", "Produto"), ("forca", "Força do sinal (0–1)", "numero"),
                            ("detalhe", "Detalhe")], ex["internacional"], "der",
                            vazio="Nenhum sinal internacional (exige séries mensais longas em dois países)."),
                      table("mudancas", "5. Principais mudanças recentes", [("produto", "Produto"), ("mudanca", "Mudança"), ("data", "Data"),
                            ("fonte", "Fonte"), ("evidencia", "Evidência")], ex.get("mudancas") or [], "der",
                            vazio="Nenhuma mudança comercial recente com evidência suficiente."),
                      table("qualidade_ev", "6. QUALIDADE DAS EVIDÊNCIAS", [("item", "Item"), ("valor", "Detalhe")],
                            (ex.get("qualidade") or {}).get("linhas", []), "der"),
                      table("riscos", "7. Riscos mais frequentes", [("risco", "Risco"), ("produtos", "Produtos", "inteiro")], ex["riscos"], "der"),
                      table("limitacoes", "8. Limitações", [("limitacao", "Limitação")], [{"limitacao": x} for x in ex["limitacoes"]], "der"),
                      table("proximos", "9. Próximas investigações recomendadas", [("produto", "Produto"), ("investigacao", "Investigação")],
                            ex["proximos"], "der")):
                row = self.write_table(ws, t, row)
        ws["A{}".format(row)] = "Verificações (fórmulas do GPI, recalculadas pelo Excel ao abrir)"
        ws["A{}".format(row)].font = Font(bold=True, color=ACCENT)
        self.formula_row = row + 1
        ws.column_dimensions["A"].width = 34
        ws.column_dimensions["B"].width = 70
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 18
        ws.freeze_panes = "A4" if ds.get("demo") else "A3"
        ws.sheet_view.showGridLines = False
        return ws

    def formulas(self, ws):
        """Fórmulas próprias (contagem e média) sobre as tabelas — permitem conferir os números no Excel."""
        r = self.formula_row
        for tid, label, col, fn in (("ranking", "Linhas no ranking", "produto", "COUNTA"),
                                    ("ranking", "Média do Opportunity Score no ranking", "score", "AVERAGE"),
                                    ("oportunidades", "Média do índice de oportunidade", "indice", "AVERAGE"),
                                    ("historico", "Observações no histórico", "valor", "COUNT")):
            if tid not in self.refs or col not in self.refs[tid][1]:
                continue
            sheet, letters, a, b = self.refs[tid]
            L = letters[col]
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=f"=IFERROR({fn}('{sheet}'!{L}{a}:{L}{b}),\"—\")")
            ws.cell(row=r, column=2).number_format = "#,##0.0"
            r += 1

    def section(self, name, tables):
        ws = self.wb.create_sheet(sheet_name(name, self.used))
        row = self.banner(ws, 1, len(tables[0]["colunas"]) if tables else 4)
        ws.cell(row=row, column=1, value=name).font = TITLE_FONT
        put(ws, row + 1, 1, "Filtros: " + self.ds["meta"]["filtros_texto"]).font = SUB_FONT
        row += 3
        first_head = None
        for t in tables:
            if first_head is None and t["linhas"]:
                first_head = row + 2 + (1 if t.get("descricao") else 0)
            row = self.write_table(ws, t, row)
        self.fit(ws, self.measure(tables))
        if len(tables) == 1 and first_head:
            ws.freeze_panes = ws.cell(row=first_head + 1, column=2)
        else:
            ws.freeze_panes = ws.cell(row=row and 4, column=1)
        return ws

    def charts(self):
        gs = [g for g in self.ds.get("graficos", []) if g.get("series")]
        if not gs:
            return
        ws = self.wb.create_sheet(sheet_name("Gráficos", self.used))
        self.banner(ws, 1, 6)
        ws.cell(row=2, column=1, value="Gráficos (dados ao lado de cada gráfico; uma unidade por gráfico)").font = TITLE_FONT
        row = 4
        for g in gs[:6]:
            ws.cell(row=row, column=1, value=f"{g['titulo']} — {g.get('unidade', '')}").font = Font(bold=True, color=ACCENT)
            row += 1
            if g["tipo"] == "linha":
                xs = sorted({x for s in g["series"] for x in s["x"]})
                ws.cell(row=row, column=1, value="Período")
                for j, s in enumerate(g["series"], start=2):
                    put(ws, row, j, s["nome"])
                for i, x in enumerate(xs, start=1):
                    ws.cell(row=row + i, column=1, value=x)
                    for j, s in enumerate(g["series"], start=2):
                        d = dict(zip(s["x"], s["y"]))
                        if x in d:
                            ws.cell(row=row + i, column=j, value=d[x])
                ch = LineChart()
                ch.y_axis.title = g.get("unidade", "")[:40]
                data = Reference(ws, min_col=2, max_col=1 + len(g["series"]), min_row=row, max_row=row + len(xs))
                ch.add_data(data, titles_from_data=True)
                ch.set_categories(Reference(ws, min_col=1, min_row=row + 1, max_row=row + len(xs)))
                n = len(xs)
            else:
                ws.cell(row=row, column=1, value="Produto")
                ws.cell(row=row, column=2, value=g.get("unidade") or "valor")
                for i, s in enumerate(g["series"], start=1):
                    put(ws, row + i, 1, s["nome"])
                    ws.cell(row=row + i, column=2, value=s["y"][0])
                ch = BarChart()
                ch.type = "bar"
                ch.add_data(Reference(ws, min_col=2, min_row=row, max_row=row + len(g["series"])), titles_from_data=True)
                ch.set_categories(Reference(ws, min_col=1, min_row=row + 1, max_row=row + len(g["series"])))
                n = len(g["series"])
            ch.title = g["titulo"][:60]
            ch.height, ch.width = 7.5, 18
            ws.add_chart(ch, f"{get_column_letter(len(g['series']) + 3)}{row}")
            row += max(n, 15) + 3
        ws.column_dimensions["A"].width = 22

    def save(self, path):
        sm = self.summary()
        order = ["Ranking de Produtos", "Produtos Mais Pesquisados", "Ranking de Interesse Relativo", "Produto",
                 "Histórico de Indicadores", "Tendências por País", "Redes Sociais", "Search vs. Social", "Forecasting",
                 "Modelos e Desempenho", "Oportunidades", "Fontes e Metodologia", "Dados Brutos Permitidos"]
        secs = sorted(self.ds["secoes"], key=lambda s: order.index(s[0]) if s[0] in order else 99)
        for name, tables in secs:
            self.section(name, tables)
        self.charts()
        self.formulas(sm)
        props = self.wb.properties
        props.title = self.ds["titulo"][:250]
        props.creator = "GPI — Global Product Intelligence"
        props.subject = self.ds["meta"]["run_id"]
        props.keywords = ("DEMONSTRAÇÃO " if self.ds.get("demo") else "") + "GPI relatório"
        self.wb.calculation.fullCalcOnLoad = True
        self.wb.save(path)


def write(ds: dict, path) -> None:
    Writer(ds).save(path)
