"""CSV / Excel / PDF export helpers. Excel and PDF need the optional `openpyxl` / `reportlab`
packages (listed in requirements.txt); when missing the endpoint answers 501 and CSV still works."""
import csv
import io
import re
from fastapi import HTTPException, Response

FORMATS = ("json", "csv", "xlsx", "pdf")
_MEDIA = {"csv": "text/csv; charset=utf-8",
          "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "pdf": "application/pdf"}


def safe_cell(v):
    """Neutralise spreadsheet-formula injection (cells starting with = + - @ are prefixed)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def filename(base: str, ext: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")[:80] + "." + ext


def _attach(content: bytes, fmt: str, name: str) -> Response:
    return Response(content=content, media_type=_MEDIA[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{filename(name, fmt)}"',
                             "Cache-Control": "no-store"})


def _missing(pkg: str):
    return HTTPException(status_code=501, detail=f"{pkg} is not installed on the server; install it "
                                                 "(pip install -r requirements.txt) or use CSV")


def tabular(fmt: str, name: str, title: str, columns: list[str], rows: list[list], meta: list[str] = ()) -> Response:
    rows = [[safe_cell(c) for c in r] for r in rows]
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        w.writerows(rows)
        return _attach(("\ufeff" + buf.getvalue()).encode("utf-8"), fmt, name)
    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ImportError:
            raise _missing("openpyxl")
        wb = Workbook()
        ws = wb.active
        ws.title = re.sub(r"[\[\]:*?/\\]", " ", title)[:31] or "Report"
        for line in meta:
            ws.append([safe_cell(line)])
        if meta:
            ws.append([])
        ws.append(columns)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append(r)
        for i, col in enumerate(columns, 1):
            width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:500]]) + 2
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 50)
        out = io.BytesIO()
        wb.save(out)
        return _attach(out.getvalue(), fmt, name)
    if fmt == "pdf":
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
            from xml.sax.saxutils import escape
        except ImportError:
            raise _missing("reportlab")
        st = getSampleStyleSheet()
        small = st["BodyText"].clone("small", fontSize=8, leading=10)
        out = io.BytesIO()
        doc = SimpleDocTemplate(out, pagesize=landscape(A4) if len(columns) > 5 else A4, title=title,
                                leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28)
        story = [Paragraph(escape(title), st["Title"])] + [Paragraph(escape(m), st["Normal"]) for m in meta] + [Spacer(1, 8)]
        data = [[Paragraph("<b>%s</b>" % escape(str(c)), small) for c in columns]] + \
               [[Paragraph(escape(str(c)), small) for c in r] for r in rows]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
        doc.build(story)
        return _attach(out.getvalue(), fmt, name)
    raise HTTPException(status_code=422, detail="format must be one of json, csv, xlsx, pdf")


def seating_pdf(name: str, title: str, meta: list[str], charts: list[dict], columns: int = 5) -> Response:
    """One printable page per hall: a grid of seat boxes (label, register number, department)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
        from xml.sax.saxutils import escape
    except ImportError:
        raise _missing("reportlab")
    st = getSampleStyleSheet()
    cell = st["BodyText"].clone("cell", fontSize=7.5, leading=9, alignment=1)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), title=title, leftMargin=24, rightMargin=24,
                            topMargin=26, bottomMargin=26)
    story = []
    for n, c in enumerate(charts):
        if n:
            story.append(PageBreak())
        story += [Paragraph(escape(title), st["Heading2"]),
                  Paragraph(escape(f"Hall {c['hall']} - capacity {c['capacity']} - allocated {c['allocated']} - "
                                   f"free {c['free']}"), st["Normal"])] + [Paragraph(escape(m), st["Normal"]) for m in meta]
        story.append(Spacer(1, 8))
        boxes, bg = [], []
        for s in c["seats"]:
            if s["state"] == "allocated":
                txt = f"<b>{escape(s['seat'])}</b><br/>{escape(s['register_number'])}<br/>{escape(s['department'] or '')[:22]}"
                bg.append(colors.HexColor("#e8f3ff"))
            elif s["state"] == "other_exam":
                txt, _ = f"<b>{escape(s['seat'])}</b><br/>(other exam)", bg.append(colors.HexColor("#fff4d6"))
            elif s["state"] == "unavailable":
                txt, _ = f"<b>{escape(s['seat'])}</b><br/>unavailable", bg.append(colors.HexColor("#dddddd"))
            else:
                txt, _ = f"<b>{escape(s['seat'])}</b><br/>-", bg.append(colors.white)
            boxes.append(Paragraph(txt, cell))
        rows = [boxes[i:i + columns] for i in range(0, len(boxes), columns)]
        if rows:
            rows[-1] += [""] * (columns - len(rows[-1]))
            style = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
            for i, b in enumerate(bg):
                style.append(("BACKGROUND", (i % columns, i // columns), (i % columns, i // columns), b))
            story.append(Table(rows, colWidths=[(doc.width / columns)] * columns, style=TableStyle(style), repeatRows=0))
        else:
            story.append(Paragraph("No seats configured for this hall.", st["Normal"]))
    doc.build(story)
    return _attach(out.getvalue(), "pdf", name)
