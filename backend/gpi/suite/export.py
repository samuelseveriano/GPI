"""Exportação XLSX e PDF dos resultados da suíte (dossiê de pesquisa, nichos, palavras-chave, fornecedores, cenários).

Reutiliza a proteção contra injeção de fórmulas e as fontes do Centro de Relatórios. Cada exportação traz a natureza dos
dados e as limitações; nada é acrescentado que não esteja no resultado exibido na tela."""
from __future__ import annotations

import io
import json
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from ..reports.xlsx import safe_text

HEAD = PatternFill("solid", fgColor="1F3A5F")


def _cell(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (dict, list, tuple)):
        v = json.dumps(v, ensure_ascii=False, default=str)
    t, _ = safe_text(v)
    return ("'" + t if t[:1] in "=+-@" else t)[:32000]


def tables_from(kind: str, data: dict) -> list[tuple[str, list[dict], list[str]]]:
    """(nome da aba, linhas, notas)."""
    if kind == "pesquisa":
        ab = data.get("abas") or {}
        ov = ab.get("visao_geral") or {}
        dec = data.get("decisao") or {}
        t = [("Visão geral", [{"campo": k, "valor": v} for k, v in {
            "consulta": data.get("consulta"), "produto": ov.get("produto"), "produto_id": ov.get("produto_id"), "estágio": ov.get("nome_estagio"),
            "situação": ov.get("situacao"), "decisão": dec.get("cor"), "significado": dec.get("significado"),
            "motivos": "; ".join(dec.get("motivos") or []),
            **{f"indicador: {k}": (v or {}).get("valor") for k, v in (ov.get("indicadores") or {}).items()}}.items()],
              ["Score não é probabilidade. Ausência de dado não é evidência negativa."])]
        dm = ab.get("demanda") or {}
        t.append(("Demanda", [x for m in dm.get("mercados", []) for x in m.get("exemplos", [])], [dm.get("aviso") or ""]))
        mk = ab.get("marketplaces") or {}
        t.append(("Marketplaces", mk.get("anuncios") or [], [mk.get("aviso") or "", "Vendas e receita não disponíveis."]))
        t.append(("Semelhantes", (ab.get("semelhantes") or {}).get("itens") or [], [(ab.get("semelhantes") or {}).get("nota") or ""]))
        fo = ab.get("fornecedores") or {}
        t.append(("Fornecedores", [{**c, "fontes": ", ".join(c.get("fontes") or []), "motivos": "; ".join(c.get("motivos") or [])}
                                   for c in fo.get("candidatos") or []], [fo.get("aviso") or ""]))
        im = ab.get("importacao") or {}
        t.append(("Importação NCM", [{k: c.get(k) for k in ("codigo", "descricao", "pontuacao")} for c in (im.get("ncm") or {}).get("candidatas", [])],
                  (im.get("ncm") or {}).get("avisos") or []))
        t.append(("Riscos", im.get("riscos") or [], ["Riscos identificados a partir dos dados; não é lista exaustiva."]))
        t.append(("Qualidade", [{"campo": k, "valor": v} for k, v in (ab.get("qualidade") or {}).items() if k != "regras"],
                  (ab.get("qualidade") or {}).get("regras") or []))
        pv = ab.get("previsoes") or {}
        t.append(("Previsões", [{"serie": s["rotulo"], "n": s["n"], "tendencia": (s.get("tendencia") or {}).get("direcao"),
                                 "p_valor": (s.get("tendencia") or {}).get("p_valor"), "modelo": (s.get("previsao") or {}).get("modelo"),
                                 "wape_validacao": (s.get("previsao") or {}).get("backtest_wape"),
                                 "melhor_que_ingenuo": (s.get("previsao") or {}).get("melhor_que_ingenuo")} for s in pv.get("series", [])],
                  [pv.get("nota") or ""]))
        t.append(("Evidências", (ab.get("evidencias") or {}).get("itens") or [], [(ab.get("evidencias") or {}).get("regra") or ""]))
        return t
    if kind == "nichos":
        return [("Nichos", [{k: v for k, v in r.items() if k != "atributos"} for r in data.get("itens", [])],
                 ["Anúncios observados não são vendas.", "Score não é probabilidade."])]
    if kind == "palavras":
        return [("Observadas", data.get("observadas") or [], [data.get("aviso") or ""]),
                ("Geradas", data.get("geradas") or [], ["Sugestões do léxico do GPI — nunca observadas em fonte."])]
    if kind == "fornecedor":
        e = data.get("empresa") or {}
        return [("Empresa", [{"campo": k, "valor": v} for k, v in e.items()], data.get("regras") or []),
                ("Embarques", data.get("embarques") or [], (data.get("cobertura_embarques") or {}).get("limitacoes") or []),
                ("Relações", (data.get("rede") or {}).get("arestas") or [], (data.get("rede") or {}).get("avisos") or []),
                ("Avaliação", [{"dimensao": d, "tipo": t, **x} for d, m in (data.get("avaliacao") or {}).items() for t, lst in m.items() for x in lst], [])]
    if kind == "cenario":
        sc = data.get("cenarios") or {}
        rows = []
        for name, v in sc.items():
            rows.append({"cenário": name, **{k: v2 for k, v2 in v.items() if k != "custos_adicionais"}})
        return [("Cenários", rows, data.get("avisos") or []), ("Parâmetros", [{"campo": k, "valor": v} for k, v in (data.get("parametros") or {}).items()],
                                                               ["Pendentes: " + ", ".join(data.get("pendentes") or []) if data.get("pendentes") else ""])]
    return [("Dados", data if isinstance(data, list) else [data], [])]


def xlsx(kind: str, data: dict, title: str) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    for name, rows, notes in tables_from(kind, data):
        n = name[:31]
        while n in used:
            n = n[:28] + str(len(used))
        used.add(n)
        ws = wb.create_sheet(n)
        ws.append([_cell(f"GPI — {title} · {name}")])
        ws["A1"].font = Font(bold=True, size=12)
        ws.append([_cell(f"Gerado em {datetime.now():%Y-%m-%d %H:%M} · dados locais do GPI")])
        for nt in notes:
            if nt:
                ws.append([_cell("Nota: " + nt)])
        ws.append([])
        if not rows:
            ws.append(["Sem dados para esta seção."])
            continue
        cols = []
        for r in rows:
            for k in (r if isinstance(r, dict) else {}):
                if k not in cols:
                    cols.append(k)
        ws.append([_cell(c) for c in cols])
        hr = ws.max_row
        for c in ws[hr]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), HEAD
        for r in rows[:20000]:
            ws.append([_cell(r.get(c)) if isinstance(r, dict) else _cell(r) for c in cols])
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(row=hr, column=i).column_letter].width = min(60, max(10, len(str(c)) + 4))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def pdf(kind: str, data: dict, title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from ..reports.pdf import styles
    st = styles()
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"GPI — {title}", author="GPI — Global Product Intelligence")
    W = landscape(A4)[0] - 24 * mm
    story = [Paragraph(escape(f"GPI — {title}"), st["title"]),
             Paragraph(escape(f"Gerado em {datetime.now():%Y-%m-%d %H:%M} · dados locais do GPI"), st["subtitle"]), Spacer(1, 6)]
    for name, rows, notes in tables_from(kind, data):
        story.append(Paragraph(escape(name), st["h1"]))
        for nt in notes:
            if nt:
                story.append(Paragraph(escape("Nota: " + nt), st["small"]))
        if not rows:
            story.append(Paragraph("Sem dados para esta seção.", st["body"]))
            continue
        cols = []
        for r in rows:
            for k in (r if isinstance(r, dict) else {}):
                if k not in cols and len(cols) < 9:
                    cols.append(k)

        def cell(v):
            v = _cell(v)
            return Paragraph(escape(str("" if v is None else v))[:400], st["cell"])
        tbl = [[Paragraph(escape(str(c)), st["head"]) for c in cols]] + [[cell(r.get(c)) for c in cols] for r in rows[:150] if isinstance(r, dict)]
        t = Table(tbl, colWidths=[W / max(1, len(cols))] * len(cols), repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D2DE")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
        if len(rows) > 150:
            story.append(Paragraph(f"… {len(rows) - 150} linha(s) adicionais no XLSX.", st["small"]))
        story.append(Spacer(1, 6))
    doc.build(story)
    return bio.getvalue()
