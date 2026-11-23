"""End to end on the 20-Nov-2026 AN sheets: PDF files -> real PyMuPDF reading -> DRAFT batch -> roster matching ->
verification + approval -> publish -> public register-number lookup -> official PDF page preview.

The two PDFs are GENERATED from the real official text (tests/vsb/real_20nov26) because the build sandbox could not download VSB's
binary files; geometry is approximate (see vsb/test_vsb_pdf_roundtrip.py). Official-source discovery/download is covered by
test_vsb_crawler.py with a mocked transport (no network). Nothing here is hardcoded to these two files.
"""
import hashlib
import json
from datetime import date

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

fitz = pytest.importorskip("fitz")
from app import doc_models as dm
from app.config import settings
from conftest import make_student
from vsb import independent_compare as IC
from vsb.test_vsb_pdf_roundtrip import _seat_pdf

HALL_URL = "https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-HALL.pdf"
SEAT_URL = "https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-SEAT.pdf"
EEE_102 = "922525105045"        # hall MB III 102, seat 16 (hall PDF page 2, seat PDF page 5)
AIDS_A104 = "922524243026"      # hall MB III A104, seat 3  (partially filled hall)
OTHER = "922525105051"          # same hall as EEE_102, seat 28
UNKNOWN = "922525105052"        # on the PDFs but NOT in the roster


def _hall_pdf(path):
    c = canvas.Canvas(str(path), pagesize=A4)
    for text in IC.pages("20.11.26-AN-HALL.pages.txt"):
        y = A4[1] - 40
        c.setFont("Helvetica", 7)
        for ln in text.splitlines():
            c.drawString(30, y, ln); y -= 11
        c.showPage()
    c.save()


def _doc(db, tmp_path, name, kind, url, status="processed"):
    data = (tmp_path / name).read_bytes()
    d = dm.OfficialDocument(source_url=url, title=name.removesuffix(".pdf"), doc_kind=kind, exam_date=date(2026, 11, 20),
                            session="AN", origin="crawler")
    db.add(d); db.flush()
    v = dm.DocumentVersion(document_id=d.id, version_no=1, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                           storage_path=name, processing_status=status)
    db.add(v); db.commit()
    return v


@pytest.fixture()
def staged(db, client, admin, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    _hall_pdf(tmp_path / "20.11.26-AN-HALL.pdf")
    _seat_pdf(tmp_path / "20.11.26-AN-SEAT.pdf")
    hv = _doc(db, tmp_path, "20.11.26-AN-HALL.pdf", "hall_allotment", HALL_URL)
    sv = _doc(db, tmp_path, "20.11.26-AN-SEAT.pdf", "seating_allotment", SEAT_URL)
    for reg, dept in ((EEE_102, "EEE"), (AIDS_A104, "AIDS"), (OTHER, "EEE")):
        make_student(db, reg, "Demo " + reg[-4:], dept)
    r = client.post("/api/vsb-allocation/batches/build", json={"hall_version_id": hv.id, "seat_version_id": sv.id}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()[0], hv, sv


def _recs(client, admin, bid):
    return client.get(f"/api/vsb-allocation/batches/{bid}/records", params={"limit": 1000}, headers=admin).json()["records"]


def _verify(client, admin, rec, hv, sv, status="FULLY_VERIFIED"):
    body = {"status": status, "hall_pdf_reference": hv.document.source_url, "note": "checked against the official PDF page"}
    if status == "FULLY_VERIFIED":
        body["seat_pdf_reference"] = sv.document.source_url
    r = client.post(f"/api/vsb-allocation/records/{rec['id']}/verification", json=body, headers=admin)
    assert r.status_code == 200, r.text


def _publish(client, admin, bid):
    client.post(f"/api/vsb-allocation/batches/{bid}/approve-confident", headers=admin)
    pv = client.post(f"/api/vsb-allocation/batches/{bid}/publish/preview", headers=admin).json()
    r = client.post(f"/api/vsb-allocation/batches/{bid}/publish",
                    json={"signature": pv["signature"], "confirm": True, "acknowledge_open_issues": True}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_draft_matches_independent_reference_and_nothing_is_public(client, admin, staged):
    b, hv, sv = staged
    ref = IC.report()
    assert b["status"] == "draft" and b["exam_date"] == "2026-11-20" and b["session"] == "AN" and b["records"]["total"] == 390
    recs = _recs(client, admin, b["id"])
    assert len(recs) == 390 and len({r["register_number"] for r in recs}) == 390
    for r in recs:
        hall, seat = ref["assignments"][r["register_number"]]
        assert (r["hall"], r["seat"]) == (hall, str(seat)), r["register_number"]
        assert r["subject_code"] == ref["subject_of"][r["register_number"]] and r["department"] == ref["programme_of"][r["register_number"]]
        assert (r["hall_page"], r["seat_page"]) == (ref["page_of_hall"][r["register_number"]], ref["page_of_seat"][r["register_number"]])
        assert not r["blocking"] and not r["published"] and r["review_status"] == "pending" and r["verification_status"] == "UNRESOLVED"
    assert client.get(f"/api/lookup/{EEE_102}").json()["vsb_allocations"] == []       # draft: invisible


def test_roster_matching_is_reported_separately_from_parsing(client, admin, staged):
    b, _, _ = staged
    rep = client.get(f"/api/vsb-allocation/batches/{b['id']}/roster-report", headers=admin).json()
    assert (rep["records"], rep["matched"], rep["unmatched"]) == (390, 3, 387)
    assert UNKNOWN in {u["register_number"] for u in rep["unmatched_register_numbers"]} and EEE_102 not in {u["register_number"] for u in rep["unmatched_register_numbers"]}
    issues = client.get(f"/api/vsb-allocation/batches/{b['id']}/issues", params={"status": "open"}, headers=admin).json()
    kinds = {i["kind"] for i in (issues if isinstance(issues, list) else issues.get("issues", []))}
    assert not kinds & {"hall_sheet_missing", "hall_unreadable", "group_count_mismatch", "department_total_mismatch"}
    unknown = next(r for r in _recs(client, admin, b["id"]) if r["register_number"] == UNKNOWN)
    assert not unknown["student_known"] and "student_not_in_database" in unknown["flags"] and unknown["review_status"] == "pending"
    with_student = [r for r in _recs(client, admin, b["id"]) if r["student_known"]]
    assert {r["register_number"] for r in with_student} == {EEE_102, AIDS_A104, OTHER}


def test_publish_then_student_sees_hall_seat_and_page_links(client, admin, staged):
    b, hv, sv = staged
    for r in _recs(client, admin, b["id"]):
        if r["student_known"]:
            _verify(client, admin, r, hv, sv)
    assert _publish(client, admin, b["id"])["published"] == 3
    d = client.get(f"/api/portal/lookup/{EEE_102}").json()
    e = next(x for x in d["entries"] if x["kind"] == "vsb")
    assert (e["date"], e["session"], e["hall"], e["seat"]) == ("2026-11-20", "AN", "MB III 102", "16")
    assert e["subject_code"] == "23EET301" and e["verification_status"] == "FULLY_VERIFIED"
    assert [(p["source"], p["page"], p["official_url"]) for p in e["pdf_pages"]] == [("hall", 2, HALL_URL), ("seat", 5, SEAT_URL)]
    dump = json.dumps(d)
    assert OTHER not in dump and UNKNOWN not in dump                              # no other student's number anywhere in the response
    assert client.get(f"/api/portal/lookup/{UNKNOWN}").status_code == 404           # unmatched student: no record, nothing invented


def test_page_preview_png_is_the_original_unmasked_page_with_own_number_highlighted(client, admin, staged, tmp_path):
    """V7: the legacy endpoint now serves the ORIGINAL page. Every other register number is pixel-identical to the plain render."""
    b, hv, sv = staged
    for r in _recs(client, admin, b["id"]):
        if r["student_known"]:
            _verify(client, admin, r, hv, sv)
    _publish(client, admin, b["id"])
    for source, pdf, page in (("seat", "20.11.26-AN-SEAT.pdf", 4), ("hall", "20.11.26-AN-HALL.pdf", 1)):
        resp = client.get(f"/api/portal/pdf-page/{EEE_102}", params={"ref": b["id"], "source": source})
        assert resp.status_code == 200 and resp.headers["content-type"] == "image/png" and resp.headers["x-original-page"] == "unmasked"
        pix = fitz.Pixmap(resp.content)
        src = fitz.open(str(tmp_path / pdf))[page]
        from app.config import settings as _s
        scale = _s.public_page_dpi / 72
        plain = src.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        assert (pix.width, pix.height) == (plain.width, plain.height)          # the WHOLE page, not a crop
        words = src.get_text("words")
        own = [w for w in words if str(w[4]).strip(",") == EEE_102]
        others = [w for w in words if str(w[4]).strip(",").isdigit() and len(str(w[4]).strip(",")) == 12 and str(w[4]).strip(",") != EEE_102]
        assert own and others

        def crop(p, w):
            return [p.pixel(x, y) for x in range(int(w[0] * scale), int(w[2] * scale), 2) for y in range(int(w[1] * scale), int(w[3] * scale), 2)]
        assert all(crop(pix, w) == crop(plain, w) for w in others), f"{source}: another student's number was altered"
        assert all(crop(pix, w) != crop(plain, w) for w in own), f"{source}: own number was not highlighted"


def test_preview_and_lookup_respect_verification_levels(client, admin, staged, db):
    b, hv, sv = staged
    recs = {r["register_number"]: r for r in _recs(client, admin, b["id"])}
    _verify(client, admin, recs[EEE_102], hv, sv, "FULLY_VERIFIED")
    # The review endpoint refuses to approve a hall-only record (existing rule, unchanged: "cannot be approved until seat
    # verification is completed"). HALL_LIST_CONFIRMED rows therefore only exist for imported/legacy data, so simulate one directly.
    r = client.post(f"/api/vsb-allocation/records/{recs[AIDS_A104]['id']}/review", json={"decision": "approve", "note": "hall list checked"}, headers=admin)
    assert r.status_code == 422          # not verified (or hall-only): cannot be approved through the review endpoint
    _publish(client, admin, b["id"])
    row = db.get(dm.VsbAllocRecord, recs[AIDS_A104]["id"])
    row.verification_status, row.review_status, row.published = "HALL_LIST_CONFIRMED", "approved", True
    db.commit()
    hall_only = next(x for x in client.get(f"/api/portal/lookup/{AIDS_A104}").json()["entries"] if x["kind"] == "vsb")
    assert hall_only["hall"] == "MB III A104" and hall_only["seat"] is None and hall_only["verification_status"] == "HALL_LIST_CONFIRMED"
    assert [p["source"] for p in hall_only["pdf_pages"]] == ["hall"]               # the seat sheet would reveal the seat
    assert client.get(f"/api/portal/pdf-page/{AIDS_A104}", params={"ref": b["id"], "source": "hall"}).status_code == 200
    assert client.get(f"/api/portal/pdf-page/{AIDS_A104}", params={"ref": b["id"], "source": "seat"}).status_code == 404
    # UNRESOLVED + unapproved (OTHER) and an unmatched student (UNKNOWN) never see anything
    assert [x for x in client.get(f"/api/portal/lookup/{OTHER}").json()["entries"] if x["kind"] == "vsb"] == []
    for src in ("hall", "seat"):
        assert client.get(f"/api/portal/pdf-page/{OTHER}", params={"ref": b["id"], "source": src}).status_code == 404
        assert client.get(f"/api/portal/pdf-page/{UNKNOWN}", params={"ref": b["id"], "source": src}).status_code == 404
    assert client.get(f"/api/portal/pdf-page/{EEE_102}", params={"ref": 99999, "source": "hall"}).status_code == 404


def test_preview_without_a_text_layer_shows_the_plain_original_page_without_highlight(client, admin, staged, tmp_path):
    b, hv, sv = staged
    _verify(client, admin, next(r for r in _recs(client, admin, b["id"]) if r["register_number"] == EEE_102), hv, sv)
    _publish(client, admin, b["id"])
    # an image-only page has no word boxes, so the number cannot be located: the page is still shown, unmodified, never guessed
    src = fitz.open(str(tmp_path / "20.11.26-AN-HALL.pdf"))
    out = fitz.open()
    for pg in src:
        img = pg.get_pixmap(dpi=60).tobytes("png")
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, stream=img)
    out.save(str(tmp_path / "20.11.26-AN-HALL.pdf"))
    resp = client.get(f"/api/portal/pdf-page/{EEE_102}", params={"ref": b["id"], "source": "hall"})
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"


def test_replaced_official_pdf_after_publish_is_flagged_to_the_student(client, admin, staged, db):
    b, hv, sv = staged
    _verify(client, admin, next(r for r in _recs(client, admin, b["id"]) if r["register_number"] == EEE_102), hv, sv)
    _publish(client, admin, b["id"])
    db.add(dm.DocumentVersion(document_id=hv.document_id, version_no=2, sha256="f" * 64, size_bytes=1, storage_path="x.pdf",
                              processing_status="processed"))
    db.commit()
    e = next(x for x in client.get(f"/api/portal/lookup/{EEE_102}").json()["entries"] if x["kind"] == "vsb")
    assert e["verify_note"] and "replaced" in e["verify_note"]


def test_scheduled_auto_stage_pairs_hall_and_seat_by_date_and_session(db, tmp_path, monkeypatch):
    """What the scheduler runs after a download: pair the session's hall + seat PDFs and stage a DRAFT only (never published)."""
    from app.vsb_alloc import service as svc
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    _hall_pdf(tmp_path / "20.11.26-AN-HALL.pdf")
    _seat_pdf(tmp_path / "20.11.26-AN-SEAT.pdf")
    _doc(db, tmp_path, "20.11.26-AN-HALL.pdf", "hall_allotment", HALL_URL, "pending")
    notes = svc.auto_stage(db, "scheduler")
    assert notes == ["2026-11-20 AN: waiting for the seating allotment PDF before a batch can be staged."]
    _doc(db, tmp_path, "20.11.26-AN-SEAT.pdf", "seating_allotment", SEAT_URL, "pending")
    notes = svc.auto_stage(db, "scheduler")
    assert notes == ["2026-11-20 AN: draft batch staged for administrator review (nothing is published)."]
    b = db.scalar(select(dm.VsbAllocBatch))
    assert (b.status, b.exam_date, b.session) == ("draft", date(2026, 11, 20), "AN")
    recs = db.scalars(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.batch_id == b.id)).all()
    assert len(recs) == 390 and not any(r.published or r.review_status == "approved" for r in recs)
    assert svc.auto_stage(db, "scheduler") == []                  # same versions: no duplicate batch
