"""Builds synthetic timetable PDFs for tests (digital table, digital text, scanned image-only)."""
import io
import fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SS = getSampleStyleSheet()


def table_pdf(rows=None, dept="Electronics and Communication Engineering") -> bytes:
    rows = rows or [["Date", "Session", "Subject Code", "Subject Name"],
                    ["15/01/2027", "FN 09:30 AM - 12:30 PM", "CS3251", "Programming in C"],
                    ["", "AN 01:30 PM - 04:30 PM", "MA3151", "Matrices and Calculus"],
                    ["18/01/2027", "FN 09:30 AM - 12:30 PM", "EC3452", "Electromagnetic Fields"]]
    buf = io.BytesIO()
    from reportlab.lib.styles import ParagraphStyle
    small = ParagraphStyle("c", parent=SS["Normal"], fontSize=(11 if len(rows[0]) <= 4 else 8), leading=13)
    n = len(rows[0])
    wide = [[Paragraph(c, small) for c in r] for r in rows]       # wrap cells so wide tables fit the page
    t = Table(wide, colWidths=[75, 170, 80, 160] if n == 4 else [480 / n] * n)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4).build([
        Paragraph("DEMO COLLEGE", SS["Title"]), Paragraph("End Semester Examinations Nov/Dec 2026", SS["Heading2"]),
        Paragraph(f"Department of {dept}", SS["Normal"]), Paragraph("Academic Year: 2026-27  Semester III", SS["Normal"]),
        Spacer(1, 12), t, Spacer(1, 12), Paragraph("Instructions:", SS["Normal"]),
        Paragraph("1. Candidates must carry the hall ticket.", SS["Normal"]),
        Paragraph("2. Mobile phones are prohibited in the hall.", SS["Normal"]),
        Paragraph("Sample register 990025106001 listed.", SS["Normal"])])
    return buf.getvalue()


def text_pdf(lines=None) -> bytes:
    lines = lines or ["End Semester Examinations Nov/Dec 2026", "Academic Year 2026-27", "Department of Computer Science",
                      "15 Jan 2027", "FN 9.30 am - 12.30 pm CS3251 Programming in C",
                      "AN 1.30 pm - 4.30 pm MA3151 Matrices and Calculus",
                      "18-01-2027 FN 09:30-12:30 EC3452 Electromagnetic Fields",
                      "19/01/2027 AN XX99 Mystery paper"]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build([Paragraph(x, SS["Normal"]) for x in lines])
    return buf.getvalue()


def scanned(pdf_bytes: bytes, dpi: int = 200, noise: bool = False) -> bytes:
    """Rasterise every page into an image-only PDF (no text layer)."""
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    for pg in src:
        pix = pg.get_pixmap(dpi=dpi)
        data = pix.tobytes("png")
        if noise:
            from PIL import Image, ImageFilter
            im = Image.open(io.BytesIO(data)).convert("L").filter(ImageFilter.GaussianBlur(1.6))
            b = io.BytesIO(); im.save(b, "PNG"); data = b.getvalue()
        p = out.new_page(width=pg.rect.width, height=pg.rect.height)
        p.insert_image(p.rect, stream=data)
    return out.tobytes()


def blank_pdf() -> bytes:
    d = fitz.open(); d.new_page(); return d.tobytes()
