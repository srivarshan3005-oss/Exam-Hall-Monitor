"""Build a STATIC copy of the student portal for GitHub Pages (no server needed).

Run from the backend folder:   .venv\\Scripts\\python.exe build_static_site.py [output_folder]

It reads the same database and stored PDFs as the live server and writes:
  index.html, portal.css, portal.js       the same portal, switched to static mode
  data/lookup/<REGISTER>.json             exactly what /api/public/lookup returns for that number
  data/published.json, data/status.json   the "published allotments" boxes and the sync bar
  img/<hash>_p<page>.jpg                  ONE plain image per used PDF page (the highlight is drawn in the browser)
Page images are the original, complete, unmasked pages (same as the live server).
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy import select

from app import doc_models as dm
from app.database import SessionLocal
from app.routers import docproc, public_live as pl
from app.vsb_live import render
from app.config import settings

HERE = Path(__file__).resolve().parent
STATIC_SRC = HERE / "app" / "static" / "portal"
JPEG_QUALITY = 62
MAX_WIDTH = 1100          # px; highlights are stored as fractions of the page, so resizing is safe


def main(out_dir: str | None = None) -> dict:
    out = Path(out_dir or (HERE.parent / "site")).resolve()
    if out.exists():                       # start clean but KEEP .git, so later publishes upload only what changed
        for child in out.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    for sub in ("data/lookup", "img"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")

    html = (STATIC_SRC / "index.html").read_text(encoding="utf-8").replace(
        '<script src="portal.js"></script>', '<script>window.STATIC_SITE = true;</script>\n<script src="portal.js"></script>')
    (out / "index.html").write_text(html, encoding="utf-8")
    for name in ("portal.css", "portal.js"):
        shutil.copy2(STATIC_SRC / name, out / name)

    db = SessionLocal()
    try:
        q = select(dm.LiveAllotment).where(dm.LiveAllotment.is_current == True)  # noqa: E712
        cutoff = pl.portal_cutoff()
        if cutoff is not None:
            q = q.where(dm.LiveAllotment.exam_date >= cutoff)
        rows = db.scalars(q).all()
        by_id = {a.id: a for a in rows}
        regs = sorted({a.register_number for a in rows})

        docs: dict[int, fitz.Document] = {}
        done_img: set[str] = set()
        paths: dict[int, Path] = {}

        def image_for(vid: int, page: int) -> tuple[str, fitz.Page] | None:
            v = db.get(dm.DocumentVersion, vid)
            if v is None:
                return None
            key = f"{v.sha256[:12]}_p{page}"
            if vid not in docs:
                try:
                    paths[vid] = docproc.stored_path(v)
                    docs[vid] = fitz.open(str(paths[vid]))
                except Exception:  # noqa: BLE001 - PDF file missing on this computer
                    return None
            if page >= len(docs[vid]):
                return None
            if key not in done_img:
                r = render.render_original_page(paths[vid], page, None, highlight=False, cache_key=v.sha256)
                im = Image.open(io.BytesIO(r.png)).convert("RGB")
                if im.width > MAX_WIDTH:
                    im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
                im.save(out / "img" / f"{key}.jpg", "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
                done_img.add(key)
            return key, docs[vid][page]

        missing_pages = 0
        for n, reg in enumerate(regs, 1):
            res = pl.lookup(db, reg)
            res.pop("college_name", None)
            for rec in res["records"]:
                a = by_id.get(rec["id"])
                for s in rec["sources"]:
                    vid, page = (a.hall_version_id, a.hall_page) if s["kind"] == "hall" else (a.seat_version_id, a.seat_page)
                    got = image_for(vid, page) if (a and vid and page is not None) else None
                    if not got:
                        missing_pages += 1
                        s["image_url"] = s["plain_image_url"] = None
                        s["highlights"] = []
                        continue
                    key, pg = got
                    w, h = pg.rect.width, pg.rect.height
                    boxes = [b for b in render.word_boxes_for(pg, reg) if render._inner_boxes([b], 1.0)] if hasattr(render, "_inner_boxes") else []
                    s["image_url"] = s["plain_image_url"] = f"img/{key}.jpg"
                    s["highlights"] = [[round(b[0] / w, 5), round(b[1] / h, 5), round((b[2] - b[0]) / w, 5), round((b[3] - b[1]) / h, 5)] for b in boxes]
            (out / "data" / "lookup" / f"{reg}.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            if n % 500 == 0:
                print(f"  {n}/{len(regs)} register numbers...")

        (out / "data" / "published.json").write_text(json.dumps(pl.published(db), ensure_ascii=False), encoding="utf-8")
        (out / "data" / "status.json").write_text(json.dumps(pl.public_status(db), ensure_ascii=False, default=str), encoding="utf-8")
        for d in docs.values():
            d.close()
    finally:
        db.close()

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"Static site written to {out}: {len(regs)} register numbers, {len(done_img)} page images, {size:.1f} MB"
          + (f"; {missing_pages} page image(s) could not be made (PDF missing on this computer)" if missing_pages else ""))
    if size > 900:
        print("WARNING: the site is close to GitHub Pages' 1 GB limit.")
    return {"regs": len(regs), "images": len(done_img), "mb": size, "missing": missing_pages, "out": str(out)}


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
