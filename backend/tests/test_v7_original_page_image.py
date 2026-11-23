"""Regression tests for the most important V7 requirement: the page image is the ORIGINAL page, complete and UNMASKED.

Every other register number, every row and every table cell must stay visible; the searched number may only be highlighted by a
separate overlay; stale (older, masked) cache images must never be served.
"""
import io

import fitz
import pytest
from PIL import Image, ImageChops
from sqlalchemy import select

from app import doc_models as dm
from app.config import settings
from app.vsb_live import pipeline, render
from v7_fakesite import standard_site
from v7_pdfs import write_hall_pdf, write_seat_pdf

REG = "922523105015"


@pytest.fixture(autouse=True)
def _fresh():
    pipeline.forget()
    yield


@pytest.fixture()
def built(tmp_path, monkeypatch, client, db):
    from app.vsb_live import cycle
    hp, sp = write_hall_pdf(tmp_path / "h.pdf"), write_seat_pdf(tmp_path / "s.pdf")
    standard_site(hp, sp, monkeypatch)
    cycle.run_cycle(trigger="manual", actor="t")
    rec = client.get(f"/api/public/lookup/{REG}").json()["records"][0]
    return {"client": client, "rec": rec, "hall": hp, "seat": sp, "db": db}


def _words(pdf, page):
    return fitz.open(str(pdf))[page].get_text("words")


def _regs(words):
    return [w for w in words if str(w[4]).strip(",").isdigit() and len(str(w[4]).strip(",")) == 12]


def _crop_pixels(pix, w, scale):
    return [pix.pixel(x, y) for x in range(int(w[0] * scale), int(w[2] * scale) + 1) for y in range(int(w[1] * scale), int(w[3] * scale) + 1)]


@pytest.mark.parametrize("source,pdfkey", [("hall", "hall"), ("seat", "seat")])
def test_whole_page_is_returned_and_every_other_register_number_is_pixel_identical(built, source, pdfkey):
    c, rec = built["client"], built["rec"]
    src = next(s for s in rec["sources"] if s["kind"] == source)
    resp = c.get(src["image_url"])
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png" and resp.headers["x-original-page"] == "unmasked"
    page_no = src["page"] - 1
    pdf_page = fitz.open(str(built[pdfkey]))[page_no]
    pix = fitz.Pixmap(resp.content)
    scale = settings.public_page_dpi / 72
    plain = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    assert (pix.width, pix.height) == (plain.width, plain.height), "image was cropped or resized"
    words = pdf_page.get_text("words")
    own = [w for w in words if str(w[4]).strip(",") == REG]
    others = [w for w in _regs(words) if str(w[4]).strip(",") != REG]
    assert own and len(others) >= 10
    for w in others:
        assert _crop_pixels(pix, w, scale) == _crop_pixels(plain, w, scale), f"{w[4]} was altered"
    # and outside the highlight boxes the WHOLE page is identical to PyMuPDF's own render
    diff = ImageChops.difference(Image.open(io.BytesIO(resp.content)).convert("RGB"), Image.open(io.BytesIO(plain.tobytes("png"))).convert("RGB"))
    bbox = diff.getbbox()
    assert bbox is not None, "the searched number should be highlighted"
    pad = 2
    boxes = [(int(w[0] * scale) - pad, int(w[1] * scale) - pad, int(w[2] * scale) + pad, int(w[3] * scale) + pad) for w in own]
    mask = Image.new("L", diff.size, 0)
    for b in boxes:
        mask.paste(255, b)
    outside = ImageChops.multiply(diff.convert("L"), ImageChops.invert(mask))
    assert outside.getbbox() is None, "pixels changed outside the highlight overlay"


def test_text_stays_legible_to_ocr_and_pixels_are_not_blank_boxes(built):
    from app import doc_extract as dx
    if not dx.ocr_available():
        pytest.skip("Tesseract is not installed")
    import pytesseract
    src = next(s for s in built["rec"]["sources"] if s["kind"] == "seat")
    png = built["client"].get(src["plain_image_url"]).content
    text = pytesseract.image_to_string(Image.open(io.BytesIO(png)).resize((1500, 2100)), config="--psm 6")
    digits = "".join(text.split())
    found = [n for n in ("922523105015", "922524114053", "922524105015", "922525114005", "922523114056") if n in digits]
    assert len(found) >= 3, f"OCR of the delivered image should still read other students' numbers; got {found}"


def test_plain_image_has_no_highlight_and_equals_the_direct_render(built):
    src = next(s for s in built["rec"]["sources"] if s["kind"] == "hall")
    resp = built["client"].get(src["plain_image_url"])
    assert resp.headers["x-highlight-count"] == "0"
    page = fitz.open(str(built["hall"]))[src["page"] - 1]
    pix = fitz.Pixmap(resp.content)
    scale = settings.public_page_dpi / 72
    assert resp.content == page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")


def test_the_selected_page_is_the_page_that_contains_the_number(built):
    for s in built["rec"]["sources"]:
        pdf = built["hall"] if s["kind"] == "hall" else built["seat"]
        assert any(str(w[4]).strip(",") == REG for w in _words(pdf, s["page"] - 1))


def test_no_highlight_when_the_number_is_not_reliably_locatable(tmp_path):
    """Image-only page: no word boxes -> the page is returned unmodified, never a guessed highlight."""
    src = fitz.open(str(write_hall_pdf(tmp_path / "h.pdf")))
    out = fitz.open()
    pg = src[1]
    np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
    np_.insert_image(np_.rect, stream=pg.get_pixmap(dpi=100).tobytes("png"))
    p = tmp_path / "img.pdf"
    out.save(str(p))
    r = render.render_original_page(p, 0, REG, highlight=True, dpi=100)
    assert r.highlights == 0
    assert r.png == fitz.open(str(p))[0].get_pixmap(matrix=fitz.Matrix(100 / 72, 100 / 72), alpha=False).tobytes("png")


def test_out_of_range_page_and_other_students_records_are_404(built):
    c, rec = built["client"], built["rec"]
    assert c.get(f"/api/public/page/922524105045/{rec['id']}/hall").status_code == 404      # another student's number with my record id
    assert c.get(f"/api/public/page/{REG}/999999/hall").status_code == 404
    assert c.get(f"/api/public/page/{REG}/{rec['id']}/other").status_code == 422
    assert c.get("/api/public/page/zz/1/hall").status_code == 422


def test_obsolete_masked_cache_is_purged_and_never_served(built, monkeypatch, tmp_path):
    root = render.cache_root()
    stale = root / "v1-masked" / "ab"
    stale.mkdir(parents=True)
    (stale / "old.png").write_bytes(b"\x89PNG-OLD-MASKED")
    (root / "loose.png").write_bytes(b"x")
    assert render.purge_obsolete_cache() == 2
    assert not (root / "v1-masked").exists() and not (root / "loose.png").exists()
    # an image cached under the CURRENT version is reused; a version bump makes it obsolete
    src = next(s for s in built["rec"]["sources"] if s["kind"] == "hall")
    built["client"].get(src["image_url"])
    cur = root / settings.preview_cache_version
    assert any(cur.rglob("*.png"))
    monkeypatch.setattr(settings, "preview_cache_version", "v3-test")
    assert render.purge_obsolete_cache() == 1 and not cur.exists()


def test_a_poisoned_cache_file_is_ignored_when_it_is_not_a_png(built):
    src = next(s for s in built["rec"]["sources"] if s["kind"] == "seat")
    built["client"].get(src["image_url"])
    f = next(render.cache_root().rglob("*.png"))
    f.write_bytes(b"not an image")
    r = built["client"].get(src["image_url"])
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


def test_legacy_masking_module_is_gone():
    with pytest.raises(ImportError):
        import app.vsb_alloc.pagepreview  # noqa: F401
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    bad = [str(p) for p in root.rglob("*.py") if "draw_rect" in p.read_text(encoding="utf-8", errors="ignore") and "fill=(0.1" in p.read_text(encoding="utf-8", errors="ignore")]
    assert bad == []
