"""Original, UNMASKED page image of an official VSB hall / seating PDF.

Hard rules (regression-tested in tests/test_v7_original_page_image.py):

* The image is the whole page exactly as PyMuPDF renders it from the stored official PDF. Nothing is covered, blurred,
  cropped, replaced or reconstructed. Every other student's register number, every row and every table cell stays visible.
* The searched register number can be highlighted. The highlight is a SEPARATE, non-destructive overlay applied to the
  finished raster: a translucent yellow layer blended with "multiply" (black text stays black, white becomes yellow) plus a
  thin outline drawn just outside the word. If the number cannot be located reliably (no text layer, OCR page, abbreviated
  in a table), the page is returned with NO highlight at all - never a guessed one.
* Cached images live under  <storage>/page_cache/<PREVIEW_CACHE_VERSION>/ . Changing the version (or the code that
  produced older images) makes every older cache directory obsolete; purge_obsolete_cache() deletes them, so a stale image
  from an earlier (masking) release can never be served again.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

log = logging.getLogger("exam_monitor.render")

MIN_DPI, MAX_DPI = 72, 220
_TRIM = ",;:.()[]"


class PageUnavailable(Exception):
    """The page cannot be rendered (missing file, bad page number, encrypted PDF). Never leaks a partial image."""


@dataclass
class Rendered:
    png: bytes
    highlights: int          # number of boxes drawn (0 = pristine page)
    page_count: int
    width: int
    height: int
    cached: bool = False


def cache_root() -> Path:
    from ..routers import docproc
    return docproc.storage_dir() / "page_cache"


def purge_obsolete_cache() -> int:
    """Delete every cache directory that does not belong to the current PREVIEW_CACHE_VERSION. Returns directories removed."""
    root, removed = cache_root(), 0
    if not root.exists():
        return 0
    keep = _safe_version(settings.preview_cache_version)
    for child in root.iterdir():
        if child.is_dir() and child.name != keep:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        elif child.is_file():
            child.unlink(missing_ok=True)
            removed += 1
    return removed


def _safe_version(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", v or "v2-unmasked")[:40]


def word_boxes_for(page, register_number: str) -> list[tuple[float, float, float, float]]:
    """Boxes (PDF points) of words that ARE the register number (full number, optionally followed by a comma)."""
    target = register_number.strip().upper()
    out = []
    for w in page.get_text("words"):
        if str(w[4]).strip(_TRIM).upper() == target:
            out.append((float(w[0]), float(w[1]), float(w[2]), float(w[3])))
    return out


def _inner_boxes(boxes, scale: float, inset: int = 2) -> list[tuple[int, int, int, int]]:
    """Pixel rectangles strictly INSIDE each word's own box. Word boxes of different words never overlap, so the overlay can
    never touch a neighbouring register number (comma-separated lists put them only a few pixels apart)."""
    out = []
    for x0, y0, x1, y1 in boxes:
        a, b, c, d = math.ceil(x0 * scale) + inset, math.ceil(y0 * scale) + inset, math.floor(x1 * scale) - inset, math.floor(y1 * scale) - inset
        if c > a and d > b:
            out.append((a, b, c, d))
    return out


def _overlay(png_pixels, boxes: list[tuple[float, float, float, float]], scale: float):
    """Return a new PIL image = original pixels x translucent-yellow layer (multiply) + 1px outline, drawn only inside the
    searched word's own box. The original pixel array is never modified."""
    from PIL import Image, ImageChops, ImageDraw
    base = png_pixels.convert("RGB")
    inner = _inner_boxes(boxes, scale)
    if not inner:
        return base
    layer = Image.new("RGB", base.size, (255, 255, 255))
    d = ImageDraw.Draw(layer)
    for r in inner:
        d.rectangle(r, fill=(255, 230, 0))
    out = ImageChops.multiply(base, layer)
    od = ImageDraw.Draw(out)
    for r in inner:
        od.rectangle(r, outline=(214, 120, 0), width=1)
    return out


def render_original_page(pdf_path: str | Path, page_index: int, register_number: str | None = None, *,
                         highlight: bool = True, dpi: int | None = None, cache_key: str | None = None) -> Rendered:
    """Render page `page_index` (0-based) of `pdf_path` in full. `cache_key` (the PDF's SHA-256) enables the disk cache."""
    import fitz
    dpi = max(MIN_DPI, min(MAX_DPI, int(dpi or settings.public_page_dpi)))
    reg = (register_number or "").strip().upper() if highlight else ""
    cache_dir: Path | None = None
    stem = ""
    if cache_key and re.fullmatch(r"[0-9a-f]{64}", cache_key):
        cache_dir = cache_root() / _safe_version(settings.preview_cache_version) / cache_key[:2]
        stem = f"{cache_key}_p{int(page_index)}_d{dpi}_{reg or 'plain'}"
        for hit in (cache_dir.glob(stem + "_h*.png") if cache_dir.is_dir() else []):
            try:
                data = hit.read_bytes()
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                n = int(hit.stem.rsplit("_h", 1)[1])
                return Rendered(data, n, -1, im.width, im.height, cached=True)
            except Exception:  # noqa: BLE001 - a damaged cache file is simply re-rendered
                hit.unlink(missing_ok=True)
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:  # noqa: BLE001
        raise PageUnavailable("The stored PDF could not be opened") from e
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise PageUnavailable("encrypted")
        if not 0 <= int(page_index) < len(doc):
            raise PageUnavailable("page out of range")
        page = doc[int(page_index)]
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)      # the page itself, untouched
        boxes = word_boxes_for(page, reg) if reg else []
        boxes = [b for b in boxes if _inner_boxes([b], scale)]        # unusable (tiny) boxes are not highlighted
        if boxes:
            from PIL import Image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out = _overlay(img, boxes, scale)
            buf = io.BytesIO()
            out.save(buf, format="PNG", optimize=False)
            png = buf.getvalue()
        else:
            png = pix.tobytes("png")
        result = Rendered(png, len(boxes), len(doc), pix.width, pix.height)
    finally:
        doc.close()
    if cache_dir is not None:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            target = cache_dir / f"{stem}_h{result.highlights}.png"
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(result.png)
            tmp.replace(target)
        except OSError:
            log.warning("could not write page cache file")
    return result


def sha256_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
