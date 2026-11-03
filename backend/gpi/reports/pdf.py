"""
Relatório em PDF gerado localmente com ReportLab (BSD) — sem Word, LibreOffice nem serviço externo.

* Fonte DejaVu Sans embutida no pacote (licença livre, redistribuível): acentuação completa do
  português. Caracteres chineses usam uma fonte CJK já instalada no Windows (Microsoft YaHei,
  SimSun, SimHei, DengXian) — embutida por subconjunto no PDF, como o Windows permite — ou, se não
  houver nenhuma, a fonte CID padrão "STSong-Light" do ReportLab (não embutida; o leitor de PDF
  fornece os glifos). Nenhuma fonte é baixada da internet.
* A4 vertical para o texto; páginas A4 horizontais para tabelas largas. Capa, sumário (quando há
  várias seções), cabeçalho, rodapé com "Página X de Y", tabelas com quebra de linha dentro das
  células (sem texto cortado ou sobreposto) e gráficos simples.
* Relatórios com dados demonstrativos recebem faixa e marca d'água "DEMONSTRAÇÃO".
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

FONT_DIR = Path(__file__).with_name("fonts")
INK, MUTED, ACCENT, SIDE = colors.HexColor("#1b2330"), colors.HexColor("#5d6878"), colors.HexColor("#0f766e"), colors.HexColor("#121a26")
LINE, WARN = colors.HexColor("#e2e5ea"), colors.HexColor("#b91c1c")
PALETTE = [colors.HexColor(c) for c in ("#2563eb", "#d97706", "#0f766e", "#9333ea", "#dc2626", "#64748b")]
ISO_DT = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:T[\d:.+-]+)?\b")
CJK_RE = re.compile(r"([\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]+)")
_FONTS: dict = {}


def _register() -> dict:
    if _FONTS:
        return _FONTS
    pdfmetrics.registerFont(TTFont("GPI", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("GPI-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    from reportlab.lib.fonts import addMapping
    addMapping("GPI", 0, 0, "GPI")
    addMapping("GPI", 1, 0, "GPI-Bold")
    addMapping("GPI", 0, 1, "GPI")
    addMapping("GPI", 1, 1, "GPI-Bold")
    _FONTS["glyphs"] = set(pdfmetrics.getFont("GPI").face.charToGlyph.keys())
    windir = os.environ.get("WINDIR", r"C:\Windows")
    cands = [(Path(windir) / "Fonts" / n, i) for n, i in (("msyh.ttc", 0), ("simsun.ttc", 0), ("simhei.ttf", 0), ("Deng.ttf", 0))]
    cands += [(Path(p), 0) for p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                                     "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
                                     "/System/Library/Fonts/PingFang.ttc")]
    _FONTS["cjk"], _FONTS["cjk_origem"] = None, None
    for p, idx in cands:
        if p.exists():
            try:
                pdfmetrics.registerFont(TTFont("GPI-CJK", str(p), subfontIndex=idx))
                _FONTS["cjk"], _FONTS["cjk_origem"] = "GPI-CJK", f"{p.name} (fonte do sistema, embutida por subconjunto)"
                break
            except Exception:  # noqa: BLE001 — fonte com contornos CFF ou corrompida: tenta a próxima
                continue
    if not _FONTS["cjk"]:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _FONTS["cjk"], _FONTS["cjk_origem"] = "STSong-Light", "STSong-Light (CID padrão, fornecida pelo leitor de PDF)"
    return _FONTS


def rich(text) -> str:
    """Texto seguro para Paragraph: escapa XML, troca caracteres sem glifo e marca trechos chineses."""
    f = _register()
    if text is None:
        return ""
    s = str(text)
    out = []
    for part in CJK_RE.split(s):
        if not part:
            continue
        if CJK_RE.fullmatch(part):
            out.append(f'<font name="{f["cjk"]}">{escape(part)}</font>')
        else:
            out.append(escape("".join(ch if (ord(ch) in f["glyphs"] or ch in "\n\t") else "□" if ord(ch) > 0x2fff else "?"
                                      for ch in part)))
    return "".join(out)


# ---------------------------------------------------------------- formatação brasileira
def br_num(v, dec=1) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt(v, kind: str) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if kind == "pct" and isinstance(v, (int, float)):
        return br_num(v * 100, 1) + "%"
    if kind == "inteiro" and isinstance(v, (int, float)):
        return br_num(v, 0)
    if kind in ("numero",) and isinstance(v, (int, float)):
        return br_num(v, 2 if abs(v) < 100 else 0)
    if kind == "score" and isinstance(v, (int, float)):
        return br_num(v, 1)
    if kind == "data" and isinstance(v, str):
        m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", v)
        if m:
            return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m.group(3) else f"{m.group(2)}/{m.group(1)}"
    if isinstance(v, float):
        return br_num(v, 2)
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return ISO_DT.sub(lambda m: f"{m.group(3)}/{m.group(2)}/{m.group(1)}", str(v))


STYLES = {}


def styles():
    if STYLES:
        return STYLES
    _register()
    base = dict(fontName="GPI", textColor=INK, alignment=TA_LEFT)
    STYLES.update({
        "title": ParagraphStyle("t", fontSize=22, leading=27, fontName="GPI-Bold", textColor=INK),
        "subtitle": ParagraphStyle("st", fontSize=11, leading=15, **{**base, "textColor": MUTED}),
        "h1": ParagraphStyle("h1", fontSize=15, leading=19, fontName="GPI-Bold", textColor=ACCENT, spaceBefore=6, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontSize=11.5, leading=14.5, fontName="GPI-Bold", textColor=INK, spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("b", fontSize=9.5, leading=13.5, spaceAfter=4, **base),
        "small": ParagraphStyle("s", fontSize=7.8, leading=10, **{**base, "textColor": MUTED}),
        "cell": ParagraphStyle("c", fontSize=7.2, leading=9, **base),
        "head": ParagraphStyle("hd", fontSize=7.2, leading=9, fontName="GPI-Bold", textColor=colors.white),
        "demo": ParagraphStyle("d", fontSize=10, leading=13, fontName="GPI-Bold", textColor=colors.white, backColor=WARN,
                               borderPadding=(5, 6, 5, 6)),
        "toc1": ParagraphStyle("toc1", fontSize=10, leading=15, **base),
    })
    return STYLES


class NumberedCanvas(rl_canvas.Canvas):
    """Segunda passagem: escreve 'Página X de Y' e a marca d'água em todas as páginas."""
    demo = False
    head = ""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            self._decorate(n)
            super().showPage()
        super().save()

    def _decorate(self, total):
        w, h = self._pagesize
        self.saveState()
        if self._pageNumber > 1:
            self.setFont("GPI", 7.5)
            self.setFillColor(MUTED)
            self.drawString(15 * mm, h - 10 * mm, self.head[:140])
            self.setStrokeColor(LINE)
            self.line(15 * mm, h - 11.5 * mm, w - 15 * mm, h - 11.5 * mm)
        self.setFont("GPI", 7.5)
        self.setFillColor(MUTED)
        self.drawString(15 * mm, 8 * mm, "GPI — Global Product Intelligence · relatório gerado localmente")
        self.drawRightString(w - 15 * mm, 8 * mm, f"Página {self._pageNumber} de {total}")
        if self.demo:
            self.setFillColor(colors.Color(0.73, 0.11, 0.11, alpha=0.10))
            self.setFont("GPI-Bold", 64)
            self.translate(w / 2, h / 2)
            self.rotate(35)
            self.drawCentredString(0, 0, "DEMONSTRAÇÃO")
        self.restoreState()


class Doc(BaseDocTemplate):
    def __init__(self, path, **kw):
        super().__init__(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm,
                         bottomMargin=14 * mm, **kw)
        pw, ph = A4
        lw, lh = landscape(A4)
        self.addPageTemplates([
            PageTemplate("retrato", [Frame(15 * mm, 14 * mm, pw - 30 * mm, ph - 30 * mm, id="f1")], pagesize=A4),
            PageTemplate("paisagem", [Frame(15 * mm, 14 * mm, lw - 30 * mm, lh - 30 * mm, id="f2")], pagesize=landscape(A4)),
        ])

    def afterFlowable(self, fl):
        if isinstance(fl, Paragraph) and getattr(fl, "_toc", None):
            self.notify("TOCEntry", (0, fl.getPlainText(), self.page))


def heading(text, style="h1", toc=True):
    p = Paragraph(rich(text), styles()[style])
    p._toc = toc and style == "h1"
    return p


def col_widths(cols, rows, width: float, char_w: float = 4.1, pad: float = 7.0) -> list[float]:
    """Largura mínima = a maior palavra (cabeçalho em negrito ou conteúdo), para nunca quebrar palavras;
    o espaço restante é distribuído conforme o tamanho típico do conteúdo."""
    mins, want = [], []
    for c in cols:
        vals = [fmt(r.get(c["id"]), c["tipo"]) for r in rows[:120]]
        head_word = max((len(w) for w in c["rotulo"].split()), default=4) * 1.3
        body_word = max((len(w) for v in vals for w in v.split()), default=3)
        body_word = min(body_word, 22)
        mins.append(max(head_word, body_word, 4) * char_w + pad)
        typical = sorted(len(v) for v in vals)[int(len(vals) * 0.9)] if vals else 4
        want.append(max(min(typical, 60), len(c["rotulo"]) * 0.5) * char_w + pad)
    tot_min = sum(mins)
    if tot_min >= width:
        return [width * m / tot_min for m in mins]
    extra = width - tot_min
    gap = [max(0.0, w - m) for w, m in zip(want, mins)]
    g = sum(gap)
    if g <= 0:
        return [m + extra / len(mins) for m in mins]
    add = [extra * x / g for x in gap] if g > extra else [x + (extra - g) / len(mins) for x in gap]
    return [m + a for m, a in zip(mins, add)]


def pdf_table(t: dict, width: float, max_rows: int = 150) -> list:
    st = styles()
    out = [Paragraph(rich(t["titulo"]), st["h2"]),
           Paragraph(rich(f"Natureza do dado: {t['natureza']}" + (f" — {t['descricao']}" if t.get("descricao") else "")), st["small"]),
           Spacer(1, 3)]
    if not t["linhas"]:
        out.append(Paragraph(rich(t["vazio"]), st["body"]))
        for n in t.get("notas", []):
            out.append(Paragraph(rich("Nota: " + n), st["small"]))
        return [KeepTogether(out)]
    cols = t["colunas"]
    rows = t["linhas"][:max_rows]
    # larguras proporcionais ao conteúdo (com mínimo e máximo), somando exatamente a largura útil
    widths = col_widths(cols, rows, width)
    data = [[Paragraph(rich(c["rotulo"]), st["head"]) for c in cols]]
    for r in rows:
        line = []
        for c in cols:
            v = r.get(c["id"])
            txt = fmt(v, c["tipo"])
            if c["tipo"] == "link" and isinstance(v, str) and v.startswith(("http://", "https://")):
                short = re.sub(r"^https?://(www\.)?", "", v)[:38]
                line.append(Paragraph(f'<link href="{escape(v)}" color="#2563eb">{rich(short)}</link>', st["cell"]))
            else:
                line.append(Paragraph(rich(txt), st["cell"]))
        data.append(line)
    tb = Table(data, colWidths=widths, repeatRows=1)
    ts = [("BACKGROUND", (0, 0), (-1, 0), SIDE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
          ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6f7f9")))
    for j, c in enumerate(cols):                     # cor discreta nos scores (qualidade)
        if c["tipo"] == "score":
            for i, r in enumerate(rows, start=1):
                v = r.get(c["id"])
                if isinstance(v, (int, float)):
                    col = "#d1e7dd" if v >= 66 else "#fff3cd" if v >= 33 else "#f8d7da"
                    ts.append(("BACKGROUND", (j, i), (j, i), colors.HexColor(col)))
    tb.setStyle(TableStyle(ts))
    out = out[:2] + [Spacer(1, 3), tb]
    if len(t["linhas"]) > max_rows:
        out.append(Paragraph(rich(f"Mostrando {max_rows} de {len(t['linhas'])} linhas — a lista completa está no relatório Excel."), st["small"]))
    for n in t.get("notas", []):
        out.append(Paragraph(rich("Nota: " + n), st["small"]))
    out.append(Spacer(1, 8))
    return out


def chart(g: dict, width: float) -> Drawing | None:
    if not g.get("series"):
        return None
    st = styles()
    if g["tipo"] == "linha":
        xs = sorted({x for s in g["series"] for x in s["x"]})
        if len(xs) < 2:
            return None
        h = 190
        d = Drawing(width, h)
        lc = HorizontalLineChart()
        lc.x, lc.y, lc.width, lc.height = 46, 48, width - 60, h - 78
        data = []
        for s in g["series"]:
            m = dict(zip(s["x"], s["y"]))
            data.append([m.get(x) for x in xs])
        lc.data = data
        lc.categoryAxis.categoryNames = [x[2:] if len(x) == 7 else x for x in xs]
        step = max(1, len(xs) // 8)
        lc.categoryAxis.labels.fontName, lc.categoryAxis.labels.fontSize = "GPI", 6.5
        lc.categoryAxis.labels.angle = 0
        lc.categoryAxis.categoryNames = [n if i % step == 0 else "" for i, n in enumerate(lc.categoryAxis.categoryNames)]
        lc.valueAxis.labels.fontName, lc.valueAxis.labels.fontSize = "GPI", 6.5
        lc.valueAxis.labelTextFormat = lambda v: br_num(v, 0)
        vals = [v for row in data for v in row if v is not None]
        lc.valueAxis.valueMin = 0
        lc.valueAxis.valueMax = (max(vals) * 1.1) if vals and max(vals) > 0 else 1
        for i in range(len(data)):
            lc.lines[i].strokeColor = PALETTE[i % len(PALETTE)]
            lc.lines[i].strokeWidth = 1.4
        d.add(lc)
        lg = Legend()
        lg.x, lg.y = 46, 16
        lg.fontName, lg.fontSize = "GPI", 6.5
        lg.columnMaximum, lg.dx, lg.dy = 2, 6, 6
        lg.deltax = (width - 60) / 3
        lg.alignment = "right"
        lg.colorNamePairs = [(PALETTE[i % len(PALETTE)], s["nome"][:34]) for i, s in enumerate(g["series"][:6])]
        d.add(lg)
    else:
        n = len(g["series"])
        h = 40 + 16 * n
        d = Drawing(width, h)
        bc = HorizontalBarChart()
        bc.x, bc.y, bc.width, bc.height = 150, 18, width - 175, h - 30
        bc.data = [[s["y"][0] for s in g["series"]][::-1]]
        bc.categoryAxis.categoryNames = [s["nome"][:30] for s in g["series"]][::-1]
        bc.categoryAxis.labels.fontName, bc.categoryAxis.labels.fontSize = "GPI", 6.8
        bc.valueAxis.labels.fontName, bc.valueAxis.labels.fontSize = "GPI", 6.5
        bc.valueAxis.valueMin = 0
        bc.valueAxis.labelTextFormat = lambda v: br_num(v, 0)
        bc.bars[0].fillColor = ACCENT
        bc.bars.strokeColor = None
        d.add(bc)
    d.add(String(0, h - 12, f"{g['titulo']} — {g.get('unidade', '')}"[:110], fontName="GPI-Bold", fontSize=8.5, fillColor=INK))
    return d


def write(ds: dict, path) -> dict:
    st = styles()
    f = _register()
    doc = Doc(path, title=ds["titulo"], author="GPI — Global Product Intelligence", subject=ds["meta"]["run_id"])
    pw = A4[0] - 30 * mm
    lw = landscape(A4)[0] - 30 * mm
    m = ds["meta"]
    story = []
    # ---- capa
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("GPI · Global Product Intelligence", ParagraphStyle("brand", fontName="GPI-Bold", fontSize=10,
                                                                              textColor=ACCENT, leading=14)))
    story.append(Spacer(1, 6))
    story.append(Paragraph(rich(ds["titulo"].replace("Global Product Intelligence — ", "")), st["title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(rich(ds["subtitulo"]), st["subtitle"]))
    story.append(Spacer(1, 14))
    if ds.get("demo"):
        story.append(Paragraph(rich("DEMONSTRAÇÃO — este relatório usa dados sintéticos ou de teste e não deve ser usado como "
                                    f"dado real. Motivo: {ds.get('demo_motivo')}"), st["demo"]))
        story.append(Spacer(1, 12))
    gen = datetime.fromisoformat(m["gerado_em"])
    info = [("Data de referência", gen.strftime("%d/%m/%Y %H:%M")), ("Filtros aplicados", m["filtros_texto"]),
            ("Identificador da execução", m["run_id"]), ("Versão do GPI", m["versao_software"]),
            ("Versão dos dados", m["versao_dados"]), ("Fontes no recorte", ", ".join(m["fontes"]) or "nenhuma"),
            ("Modelos", "; ".join(x["modelo"] for x in m["modelos"][:5]) or "nenhum treinado")]
    tb = Table([[Paragraph(rich(k), ParagraphStyle("k", parent=st["cell"], fontName="GPI-Bold", fontSize=8.5, leading=11)),
                 Paragraph(rich(v), ParagraphStyle("v", parent=st["cell"], fontSize=8.5, leading=11))] for k, v in info],
               colWidths=[45 * mm, pw - 45 * mm])
    tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(tb)
    story.append(Spacer(1, 10))
    story.append(Paragraph(rich("Resultados exploratórios para priorizar investigação. Indicadores de busca, atenção e redes "
                                "sociais não são vendas; nenhuma recomendação de compra é feita por este relatório."), st["small"]))
    sections = [(n, t) for n, t in ds["secoes"]]
    if len(sections) >= 3 or ds["texto"].get("executivo"):
        story.append(PageBreak())
        toc = TableOfContents()
        toc.levelStyles = [st["toc1"]]
        story.append(Paragraph(rich("Sumário"), st["h1"]))
        story.append(toc)
    story.append(PageBreak())
    # ---- resumo / texto executivo
    ex = ds["texto"].get("executivo")
    story.append(heading("Resumo executivo" if ex else "Resumo"))
    if ex:
        for p in ex["resumo"]:
            story.append(Paragraph(rich(p), st["body"]))
        from .data import table
        blocks = [
            ("Panorama de mercado", table("panorama", "Indicadores do recorte", [("indicador", "Indicador"), ("valor", "Valor"),
                                          ("natureza", "Natureza do dado")], ex["panorama"], "obs")),
            ("Produtos em destaque", table("dest", "Produtos com maior índice de oportunidade de investigação", [("produto", "Produto")],
                                           [{"produto": x} for x in ex["destaques"]], "der", vazio="Sem produtos com evidências suficientes.")),
            ("Tendências internacionais", table("intl", "International Trend Signal", [("produto", "Produto"),
                                                ("forca", "Força (0–1)", "numero"), ("detalhe", "Detalhe")], ex["internacional"], "der",
                                                vazio="Nenhum sinal internacional: exige séries mensais longas na mesma métrica em dois países.")),
        ]
        for h, t in blocks:
            story.append(heading(h))
            story += pdf_table(t, pw)
        first = True
        for g in ds.get("graficos", [])[:2]:
            d = chart(g, pw)
            if d:
                story.append(KeepTogether([heading("Evidências de demanda") if first else Spacer(1, 4), d, Spacer(1, 8)]))
                first = False
    else:
        story += pdf_table(ds["resumo"], pw)
        for g in ds.get("graficos", [])[:3]:
            d = chart(g, pw)
            if d:
                story += [CondPageBreak(70 * mm), d, Spacer(1, 8)]
    # ---- seções
    for name, tables in sections:
        wide = any(t.get("largura") == "larga" for t in tables)
        story.append(NextPageTemplate("paisagem" if wide else "retrato"))
        story.append(PageBreak())
        story.append(heading({"Oportunidades": "Principais oportunidades" if ex else "Oportunidades"}.get(name, name)))
        for t in tables:
            limit = 60 if t["id"] in ("historico", "brutos", "social_indicadores") else 150
            story += pdf_table(t, lw if wide else pw, limit)
    if ex:
        story.append(NextPageTemplate("retrato"))
        story.append(PageBreak())
        from .data import table
        story.append(heading("Riscos"))
        story += pdf_table(table("riscos", "Riscos mais frequentes", [("risco", "Risco"), ("produtos", "Produtos afetados", "inteiro")],
                                 ex["riscos"], "der"), pw)
        story.append(heading("Limitações"))
        for x in ex["limitacoes"]:
            story.append(Paragraph(rich("• " + x), st["body"]))
        story.append(heading("Próximas investigações recomendadas"))
        story += pdf_table(table("prox", "Investigações sugeridas (não são recomendações de compra)",
                                 [("produto", "Produto"), ("investigacao", "Investigação")], ex["proximos"], "der"), pw)
    story.append(Spacer(1, 6))
    story.append(Paragraph(rich(f"Fonte CJK: {f['cjk_origem']}. Relatório reproduzível pelo identificador {m['run_id']} "
                                "(snapshot dos dados guardado junto ao arquivo no Histórico de Relatórios)."), st["small"]))
    NumberedCanvas.demo = bool(ds.get("demo"))
    NumberedCanvas.head = ("DEMONSTRAÇÃO · " if ds.get("demo") else "") + ds["titulo"] + " · " + gen.strftime("%d/%m/%Y")
    doc.multiBuild(story, canvasmaker=NumberedCanvas)
    return {"fonte_cjk": f["cjk_origem"]}
