"""Fixture PDF builders for the V7 tests.

The PDFs are GENERATED from the real 20-Nov-2026 AN page text captured in tests/vsb/real_20nov26 (hall list + seating
sheets). They are NOT VSB's binary files (the build environment cannot reach vsbec.edu.in), so geometry approximates TCPDF's.
They exercise the same parsers, word boxes and page rendering the real PDFs go through. Any test using them is a FIXTURE test.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from vsb import independent_compare as IC

COLX = [40, 170, 300, 430]


def hall_pages() -> list[str]:
    return IC.pages("20.11.26-AN-HALL.pages.txt")


def seat_pages() -> list[str]:
    return IC.pages("20.11.26-AN-SEAT.pages.txt")


def write_hall_pdf(path: Path, texts: list[str] | None = None) -> Path:
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    for text in texts or hall_pages():
        y = H - 40
        c.setFont("Helvetica", 8)
        for line in [l for l in text.splitlines() if l.strip()]:
            c.drawString(40, y, line[:160])
            y -= 12
        c.showPage()
    c.save()
    return path


def write_seat_pdf(path: Path, texts: list[str] | None = None) -> Path:
    """Seating sheets as a 4-column serpentine grid with real coordinates (so seat mapping uses word boxes)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    for text in texts or seat_pages():
        lines = [l for l in text.splitlines() if l.strip()]
        h_i = next(i for i, l in enumerate(lines) if l.startswith("EXAM HALL"))
        t_i = next(i for i, l in enumerate(lines) if l.startswith("CODE TITLE"))
        y = H - 40
        c.setFont("Helvetica", 8)
        for l in lines[:h_i + 1]:
            c.drawString(40, y, l)
            y -= 12
        grid = []
        for ln in lines[h_i + 1:t_i]:
            toks = ln.split()
            cells, k = [], 0
            while k < len(toks):
                reg = toks[k + 1] if k + 1 < len(toks) and len(toks[k + 1]) == 12 else None
                cells.append((toks[k], reg))
                k += 2 if reg else 1
            grid.append(cells)
        y -= 6
        for r, row in enumerate(grid):
            for ci, (seat, reg) in enumerate(row):
                yy = y - r * 14
                c.drawString(COLX[ci], yy, seat)
                if reg:
                    c.drawString(COLX[ci] + 22, yy, reg)
        y -= 7 * 14 + 10
        for l in lines[t_i:]:
            c.drawString(40, y, l[:150])
            y -= 12
        c.showPage()
    c.save()
    return path


def sample_register() -> str:
    """A register number that is on both the hall list and a seat sheet in the fixture (first one of MB III 02)."""
    return "922523105015"
