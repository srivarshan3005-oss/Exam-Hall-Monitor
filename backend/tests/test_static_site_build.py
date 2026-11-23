"""The GitHub Pages export: one plain image per used page, per-register JSON identical to the API, highlight boxes on the numbers."""
import json
import sys
from pathlib import Path

import pytest

from app.vsb_live import cycle, pipeline
from v7_fakesite import standard_site
from v7_pdfs import write_hall_pdf, write_seat_pdf

REG = "922523105015"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _fresh():
    pipeline.forget()
    yield


def test_static_export(tmp_path, monkeypatch, client, db):
    standard_site(write_hall_pdf(tmp_path / "h.pdf"), write_seat_pdf(tmp_path / "s.pdf"), monkeypatch)
    cycle.run_cycle(trigger="manual", actor="t")
    api = client.get(f"/api/public/lookup/{REG}").json()
    assert api["records"], "fixture produced no record"
    import build_static_site
    out = tmp_path / "site"
    (out / ".git").mkdir(parents=True)
    (out / "stale.txt").write_text("old", encoding="utf-8")
    info = build_static_site.main(str(out))
    assert info["regs"] >= 1 and info["missing"] == 0 and info["images"] >= 1
    assert (out / ".git").is_dir() and not (out / "stale.txt").exists(), "rebuild must keep .git and drop stale files"
    for f in ("index.html", "portal.js", "portal.css", ".nojekyll", "data/published.json", "data/status.json"):
        assert (out / f).exists(), f
    assert "window.STATIC_SITE = true" in (out / "index.html").read_text(encoding="utf-8")
    st = json.loads((out / "data" / "lookup" / f"{REG}.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in st["records"]] == [r["id"] for r in api["records"]]
    assert [(r["hall"], r["seat"], r["status"]) for r in st["records"]] == [(r["hall"], r["seat"], r["status"]) for r in api["records"]]
    for r in st["records"]:
        for s in r["sources"]:
            assert s["image_url"].startswith("img/") and (out / s["image_url"]).stat().st_size > 1000
            from PIL import Image
            assert Image.open(out / s["image_url"]).width <= build_static_site.MAX_WIDTH
            assert s["highlights"] and all(0 <= v <= 1 for b in s["highlights"] for v in b)
    assert "college_name" not in st
