"""V7 live system: official-source discovery -> download -> validation -> extraction -> hall/seat matching -> database ->
register-number-only lookup -> original UNMASKED page image -> printable slip.

FIXTURE tests: the official website is replaced by tests/v7_fakesite.py and the PDFs are generated from the real 20-Nov-2026
page text (tests/v7_pdfs.py). Nothing here touches the live college site (see tests/test_live_vsb.py for that, opt-in).
"""
import io
import json
from datetime import date

import fitz
import pytest
from PIL import Image
from sqlalchemy import select

from app import doc_models as dm, vsb_sources as vs
from app.config import settings
from app.vsb_live import cycle, pipeline, render
from v7_fakesite import COE, HALL_URL, SEAT_URL, FakeSite, standard_site
from v7_pdfs import hall_pages, seat_pages, write_hall_pdf, write_seat_pdf

REG = "922523105015"          # on hall page 2 (MB III 02) and seat sheet page 1, seat 2, subject 23EET301, BE-EEE
OTHER = "922524105045"        # another student on the same pages
UNKNOWN = "999999999999"


@pytest.fixture(autouse=True)
def _fresh_parse_cache():
    pipeline.forget()
    yield
    pipeline.forget()


@pytest.fixture()
def pdfs(tmp_path):
    return write_hall_pdf(tmp_path / "hall.pdf"), write_seat_pdf(tmp_path / "seat.pdf")


@pytest.fixture()
def site(pdfs, monkeypatch):
    return standard_site(*pdfs, monkeypatch)


def scan(**kw):
    return cycle.run_cycle(trigger="manual", actor="test", **kw)


def lookup(client, reg=REG):
    return client.get(f"/api/public/lookup/{reg}")


# ----------------------------------------------------------------------------- discovery
def test_discovery_uses_html_embedded_wordpress_and_sitemap_and_records_health(site, db):
    r = scan()
    assert r["discovery"]["status"] in ("ok", "partial") and r["discovery"]["downloaded"] == 2
    methods = {h.method: h for h in db.scalars(select(dm.VsbSourceHealth)).all() if h.last_status == "ok"}
    assert {"html", "wp_media", "sitemap"} <= set(methods)
    urls = {l.url for l in db.scalars(select(dm.VsbSourceLink)).all()}
    assert {HALL_URL, SEAT_URL} <= urls
    assert any(u.startswith("https://coe.vsbec.edu.in/") for u in site.calls)         # second official host is read too
    links = {l.url: l for l in db.scalars(select(dm.VsbSourceLink)).all()}
    assert links[HALL_URL].exam_date == date(2026, 11, 20) and links[HALL_URL].session == "AN"


def test_pdf_found_only_by_sitemap_or_media_is_still_discovered(pdfs, monkeypatch, db):
    s = standard_site(*pdfs, monkeypatch)
    s.listing([])                                          # the listing page carries NO links at all
    s.add(vs.COE_PAGE if hasattr(vs, "COE_PAGE") else "https://coe.vsbec.edu.in/", "<html></html>")
    r = scan()
    assert r["discovery"]["downloaded"] == 2               # one via WordPress media, the other via the sitemap


def test_failed_methods_do_not_fail_the_scan_but_are_reported(pdfs, monkeypatch, db):
    s = standard_site(*pdfs, monkeypatch, wp=False, sitemap=False)
    r = scan()
    assert r["discovery"]["downloaded"] == 2
    bad = {h.method for h in db.scalars(select(dm.VsbSourceHealth)).all() if h.last_status == "failed"}
    assert {"wp_media", "sitemap"} <= bad


def test_scan_reports_failure_honestly_when_every_source_is_down(pdfs, monkeypatch, db, client):
    s = standard_site(*pdfs, monkeypatch)
    assert scan()["discovery"]["status"] in ("ok", "partial")
    s.routes.clear()
    s.add(COE, exc=TimeoutError("timed out"))
    s.routes[COE]["exc"] = TimeoutError("timed out")
    r = scan()
    assert r["discovery"]["status"] == "failed" and r["status"] == "failed"
    # nothing was erased and the student still gets the previously verified answer, with an honest warning
    d = lookup(client).json()
    assert d["status"] == "found" and d["records"] and d["warnings"] and d["last_scan_status"] == "failed"
    assert d["last_synchronised_at"]                       # the last SUCCESSFUL scan time is shown, not the failed one


def test_empty_non_pdf_corrupt_oversized_and_wrong_type_downloads_are_rejected(pdfs, monkeypatch, db):
    s = standard_site(*pdfs, monkeypatch)
    s.add_pdf(HALL_URL, b"")                                                   # empty body
    s.add_pdf(SEAT_URL, b"<html>not a pdf</html>")                             # a web page where a PDF should be
    r = scan()
    assert r["discovery"]["downloaded"] == 0 and r["discovery"]["failed"] >= 2
    assert db.scalar(select(dm.OfficialDocument.id)) is None
    s.add_pdf(HALL_URL, b"%PDF-1.4\n garbage that is not a real pdf")          # right signature, corrupt body
    scan()
    assert db.scalar(select(dm.OfficialDocument.id)) is None
    s.add(HALL_URL, b"%PDF-1.4", ctype="text/html")                           # wrong content type
    scan()
    link = db.scalar(select(dm.VsbSourceLink).where(dm.VsbSourceLink.url == HALL_URL))
    assert link.download_status in ("blocked", "failed") and link.last_error


def test_off_site_and_lookalike_hosts_are_never_requested(pdfs, monkeypatch):
    s = standard_site(*pdfs, monkeypatch)
    s.listing([("http://evil.example/a.pdf", "HALL ALLOTMENT"), ("https://vsbec.edu.in.evil.example/b.pdf", "HALL ALLOTMENT"),
               (HALL_URL, "HALL ALLOTMENT - AN"), (SEAT_URL, "SEATING ALLOTMENT - AN")])
    scan()
    assert not any("evil" in c for c in s.calls)


# ----------------------------------------------------------------------------- end to end
def test_end_to_end_register_number_only_lookup(site, client, db, monkeypatch):
    r = scan()
    assert r["ingest"]["parsed"] == 2 and r["index"]["records"] == 390 and r["index"]["new"] == 390
    d = lookup(client).json()
    assert d["status"] == "found" and len(d["records"]) == 1
    rec = d["records"][0]
    assert (rec["date"], rec["weekday"], rec["session"]) == ("2026-11-20", "Friday", "AN")
    assert (rec["subject_code"], rec["subject_name"]) == ("23EET301", "ELECTROMAGNETIC FIELDS")
    assert (rec["programme"], rec["department"]) == ("BE", "EEE")
    assert (rec["hall"], rec["seat"], rec["status"]) == ("MB III 02", "2", "CONFIRMED")
    assert rec["session_time"] is None and rec["revised"] is False            # no time is invented when none is configured
    monkeypatch.setattr(settings, "session_times", "FN=09:30-12:30,AN=13:30-16:30")
    assert lookup(client).json()["records"][0]["session_time"] == "13:30-16:30"
    src = {s["kind"]: s for s in rec["sources"]}
    assert src["hall"]["filename"] == "20.11.26-AN-HALL.pdf" and src["hall"]["page"] == 2 and src["hall"]["official_url"] == HALL_URL
    assert src["seat"]["filename"] == "20.11.26-AN-SEAT.pdf" and src["seat"]["page"] == 1 and src["seat"]["official_url"] == SEAT_URL
    assert rec["location_message"] == "Building/floor location has not yet been verified."     # nothing verified: no map, no invention
    assert rec["location"] is None
    assert d["last_synchronised_at"]


def test_every_hall_and_seat_matches_the_independent_reference(site, client, db):
    """All 390 students: hall AND seat equal the independent re-derivation of the page text (tests/vsb/independent_compare)."""
    from vsb import independent_compare as IC
    scan()
    ref = IC.report()["assignments"]
    rows = db.scalars(select(dm.LiveAllotment).where(dm.LiveAllotment.is_current == True)).all()  # noqa: E712
    assert len(rows) == len(ref) == 390
    assert {r.register_number: (r.hall, int(r.seat)) for r in rows} == ref
    assert {r.status for r in rows} == {"CONFIRMED"}


def test_register_input_is_normalised_validated_and_unknown_numbers_say_so(site, client):
    scan()
    for raw in ("9225%2023105015", "9225-2310-5015", "922523105015"):
        r = client.get(f"/api/public/lookup/{raw}")
        assert r.status_code == 200 and r.json()["records"][0]["register_number"] == REG, raw
    assert client.get("/api/public/lookup/12").status_code == 422
    assert client.get("/api/public/lookup/ab%24cd%25ef12").status_code == 422
    u = lookup(client, UNKNOWN).json()
    assert u["status"] == "no_match" and u["records"] == []
    assert "No allotment was found" in u["message"]
    assert UNKNOWN not in json.dumps({k: v for k, v in u.items() if k not in ("register_number", "message")})   # nobody else's data
    # a mismatched search never returns another student's record
    assert all(r["register_number"] == REG for r in lookup(client).json()["records"])


def test_status_before_anything_is_published_and_while_a_document_is_processing(site, client, db):
    assert lookup(client).json()["status"] == "not_yet_published"
    scan()
    v = db.scalar(select(dm.DocumentVersion))
    db.add(dm.LiveIngest(version_id=v.id, status="pending")) if not db.scalar(select(dm.LiveIngest).where(dm.LiveIngest.version_id == v.id)) else None
    db.commit()
    for ing in db.scalars(select(dm.LiveIngest)).all():
        ing.status = "ok"
    # a number that matches nothing while a NEW document is still being processed must say "processing", not "no match"
    first = db.scalars(select(dm.LiveIngest)).first()
    first.status = "processing"
    db.commit()
    assert lookup(client, UNKNOWN).json()["status"] == "processing"
    first.status = "ok"
    db.commit()
    assert lookup(client, UNKNOWN).json()["status"] == "no_match"


def test_hall_only_when_the_seating_chart_is_not_published(pdfs, monkeypatch, client, db):
    standard_site(*pdfs, monkeypatch, with_seat=False, sitemap=False)
    scan()
    rec = lookup(client).json()["records"][0]
    assert (rec["status"], rec["hall"], rec["seat"]) == ("HALL_ONLY", "MB III 02", None)
    assert "not published" in rec["seat_note"].lower() and [s["kind"] for s in rec["sources"]] == ["hall"]


def test_seat_sheet_only_is_labelled_as_such(pdfs, monkeypatch, client):
    s = standard_site(*pdfs, monkeypatch, sitemap=False)
    s.listing([(SEAT_URL, "SEATING ALLOTMENT - AN (20.11.2026)")])
    s.routes.pop(HALL_URL)
    s.routes.pop(f"https://vsbec.edu.in/wp-json/wp/v2/media?mime_type=application/pdf&per_page=100&orderby=date&order=desc&page=1")
    s.add("https://coe.vsbec.edu.in/", "<html></html>")
    scan()
    rec = lookup(client).json()["records"][0]
    assert rec["status"] == "SEAT_ONLY" and rec["seat"] == "2"


def test_conflicting_hall_and_seat_documents_are_flagged_not_silently_resolved(tmp_path, monkeypatch, client, db):
    texts = [t.replace("MB III 03 13", "MB III 05 13") for t in hall_pages()]        # hall list moves the MB III 03 block to 05
    standard_site(write_hall_pdf(tmp_path / "h.pdf", texts), write_seat_pdf(tmp_path / "s.pdf"), monkeypatch)
    scan()
    moved = "922525105001"                                                          # seated in MB III 03 on the seat sheet
    d = lookup(client, moved).json()
    rec = d["records"][0]
    assert d["status"] == "conflict" and rec["status"] == "CONFLICT"
    assert rec["hall"] is None and rec["seat"] is None                              # nothing picked silently
    assert any("MB III 05" in n and "MB III 03" in n for n in rec["notes"])         # both source claims preserved
    assert {s["kind"] for s in rec["sources"]} == {"hall", "seat"}                  # both source pages available as evidence
    assert lookup(client).json()["records"][0]["status"] == "CONFIRMED"             # unaffected students stay confirmed


def test_modified_pdf_at_the_same_url_is_detected_revised_and_history_is_kept(pdfs, tmp_path, monkeypatch, client, db):
    s = standard_site(*pdfs, monkeypatch)
    scan()
    first = lookup(client).json()["records"][0]
    assert first["revision"] == 1
    # the college re-publishes both documents under the SAME URLs with the MB III 02 hall moved to MB III 09
    new_hall = write_hall_pdf(tmp_path / "h2.pdf", [t.replace("MB III 02", "MB III 09") for t in hall_pages()])
    new_seat = write_seat_pdf(tmp_path / "s2.pdf", [t.replace("MB III 02", "MB III 09") for t in seat_pages()])
    s.add_pdf(HALL_URL, new_hall, etag='"h2"')
    s.add_pdf(SEAT_URL, new_seat, etag='"s2"')
    r = scan()
    assert r["discovery"]["downloaded"] == 2 and r["index"]["revised"] > 0
    versions = db.scalars(select(dm.DocumentVersion).order_by(dm.DocumentVersion.id)).all()
    assert len(versions) == 4 and sum(v.is_current for v in versions) == 2
    rows = db.scalars(select(dm.LiveAllotment).where(dm.LiveAllotment.register_number == REG).order_by(dm.LiveAllotment.revision)).all()
    assert [x.is_current for x in rows] == [False, True] and rows[1].revised_from_id == rows[0].id
    cur = lookup(client).json()["records"][0]
    assert cur["revised"] is True and cur["revision"] == 2 and cur["hall"] == "MB III 09" and cur["status"] == "CONFIRMED"


def test_duplicate_pdf_is_not_stored_twice_and_unchanged_polls_change_nothing(site, db):
    scan()
    n = db.scalar(select(dm.DocumentVersion.id).order_by(dm.DocumentVersion.id.desc()))
    r = scan()
    assert r["discovery"]["downloaded"] == 0 and r["ingest"]["parsed"] == 0
    assert db.scalar(select(dm.DocumentVersion.id).order_by(dm.DocumentVersion.id.desc())) == n
    r = scan(rebuild=True)                                                           # a forced rebuild is idempotent
    assert r["index"]["new"] == 0 and r["index"]["revised"] == 0 and r["index"]["unchanged"] == 390


def test_same_bytes_under_a_new_url_is_a_duplicate(pdfs, site, db):
    scan()
    other = "https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-HALL-copy.pdf"
    site.add_pdf(other, pdfs[0])
    site.listing([(HALL_URL, "HALL ALLOTMENT - AN"), (SEAT_URL, "SEATING ALLOTMENT - AN"), (other, "HALL ALLOTMENT - AN (copy)")])
    r = scan()
    assert r["discovery"]["duplicates"] == 1


def test_ocr_required_pdf_is_read_through_ocr(tmp_path, monkeypatch, client, db):
    from app import doc_extract as dx
    if not dx.ocr_available():
        pytest.skip("Tesseract is not installed")
    hp = write_hall_pdf(tmp_path / "h.pdf", hall_pages()[:1])
    src = fitz.open(str(hp))
    out = fitz.open()
    for pg in src:
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, stream=pg.get_pixmap(dpi=200).tobytes("png"))
    scanned = out.tobytes()
    pages, n = pipeline.read_pages_with_ocr(str(_save(tmp_path, scanned)))
    assert n == 1 and pages[0].method == "ocr" and not pages[0].words
    doc = pipeline.parse_hall_pdf(pages)
    assert doc.groups and doc.groups[0].subject_code == "23CET305"


def _save(tmp_path, data):
    p = tmp_path / "scan.pdf"
    p.write_bytes(data)
    return p


def test_corrupt_stored_pdf_marks_ingest_failed_without_losing_other_data(site, client, db):
    scan()
    v = db.scalar(select(dm.DocumentVersion).join(dm.OfficialDocument).where(dm.OfficialDocument.doc_kind == "seating_allotment"))
    from app.routers import docproc
    docproc.stored_path(v).write_bytes(b"%PDF-1.4 broken")
    pipeline.forget()
    ing = db.scalar(select(dm.LiveIngest).where(dm.LiveIngest.version_id == v.id))
    ing.status = "pending"
    db.commit()
    r = pipeline.ingest_pending(db)
    assert r["failed"] == 1
    db.refresh(ing)
    assert ing.status == "failed" and ing.error
    assert lookup_rows(db) == 390                                                    # previously indexed rows untouched


def lookup_rows(db):
    return len(db.scalars(select(dm.LiveAllotment).where(dm.LiveAllotment.is_current == True)).all())  # noqa: E712


def test_adding_the_seat_to_a_hall_only_record_is_new_detail_not_a_revision(pdfs, monkeypatch, client, db):
    s = standard_site(*pdfs, monkeypatch, with_seat=False, sitemap=False)
    scan()
    assert lookup(client).json()["records"][0]["status"] == "HALL_ONLY"
    standard_site(*pdfs, monkeypatch, sitemap=False)              # the seating chart is published later
    scan()
    rec = lookup(client).json()["records"][0]
    assert rec["status"] == "CONFIRMED" and rec["seat"] == "2" and rec["revised"] is False


def test_student_portal_hides_exams_older_than_the_window(site, client, db, monkeypatch):
    """Old exams stay stored but the student page only shows current ones (today - PORTAL_PAST_DAYS onward)."""
    from datetime import date as _d, timedelta
    scan()
    monkeypatch.setattr(settings, "portal_past_days", -1)
    assert len(lookup(client).json()["records"]) == 1                       # unlimited: 20-Nov record shown
    row = db.get(dm.LiveAllotment, lookup(client).json()["records"][0]["id"])
    row.exam_date = _d.today() - timedelta(days=10); db.commit()
    monkeypatch.setattr(settings, "portal_past_days", 2)
    d = lookup(client).json()
    assert d["records"] == []
    assert db.scalar(select(dm.LiveAllotment).where(dm.LiveAllotment.id == row.id)) is not None   # not deleted
    row.exam_date = _d.today(); db.commit()
    assert any(r["id"] == row.id for r in lookup(client).json()["records"])


def test_version_token_endpoint_and_poll_seconds(site, client, db, monkeypatch):
    scan()
    v1 = client.get("/api/public/version/" + lookup(client).json()["register_number"]).json()["version"]
    d = lookup(client).json()
    assert d["version"] == v1                                         # same token as the full lookup
    row = db.get(dm.LiveAllotment, d["records"][0]["id"]); row.revision += 1; db.commit()
    assert client.get("/api/public/version/" + d["register_number"]).json()["version"] != v1   # a revision changes it
    assert client.get("/api/public/version/12").status_code == 422
    for given, want in ((60, 60), (1, 15), (9999, 300)):
        monkeypatch.setattr(settings, "vsb_poll_seconds", given); assert settings.poll_seconds == want
    monkeypatch.setattr(settings, "vsb_poll_seconds", 0); assert settings.poll_seconds == settings.poll_minutes * 60
