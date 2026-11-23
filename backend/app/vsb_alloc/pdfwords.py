"""PDF -> PageInput (text + word boxes) using PyMuPDF, the project's PDF library. Imported lazily so the pure parsers
and their tests do not need it."""
from __future__ import annotations

from .common import PageInput, Word

MAX_PAGES = 300


def read_pages(path: str) -> list[PageInput]:
    import fitz
    doc = fitz.open(path)
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        if not 0 < len(doc) <= MAX_PAGES:
            raise ValueError(f"PDF must have 1-{MAX_PAGES} pages")
        out: list[PageInput] = []
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            words = [Word(str(w[4]), float(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in page.get_text("words")]
            out.append(PageInput(i, text, words, "text_layer" if text.strip() else "empty"))
        return out
    finally:
        doc.close()
