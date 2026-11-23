"""Phase 4: seating-allotment PDF import (parser + review + conflict detection + confirmed import)."""
import hashlib
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from app import models, doc_models
from app.seating_parse import parse_pages, find_internal_conflicts
from conftest import make_student, make_exam, REG1, REG2, REG3

TEXT = """SEATING ARRANGEMENT
Hall: HALL-A
990025106001   Seat 1
990025106002   Seat 2
Hall: HALL-B
990025205001   7
990025106009
"""


def hall(db, code="HALL-A", n=5, verified=True):
    h = doc_models.Hall(code=code, display_name=code, capacity=n, verified=verified)
    db.add(h)
    db.flush()
    db.add_all([models.HallSeat(hall_id=h.id, seat_label=str(i), active=True) for i in range(1, n + 1)])
    db.commit()


def make_version(db, text=TEXT, method="text_layer"):
    d = doc_models.OfficialDocument(source_url="upload://t/1", title="Seating", doc_kind="hall_allotment")
    db.add(d)
    db.flush()
    v = doc_models.DocumentVersion(document_id=d.id, version_no=1, sha256=hashlib.sha256(text.encode()).hexdigest(),
                                   size_bytes=10, storage_path="x", processing_status="processed")
    db.add(v)
    db.flush()
    db.add(doc_models.PdfPage(version_id=v.id, page_index=0, text_content=text, extraction_method=method, text_chars=len(text)))
    db.commit()
    return v


def test_parser_never_guesses():
    rows = parse_pages([{"index": 0, "text": TEXT, "method": "text_layer"}])
    by = {r.register_number: r for r in rows}
    a, b, c, d = (by[x] for x in ("990025106001", "990025106002", "990025205001", "990025106009"))
    assert (a.hall, a.seat, a.flags) == ("HALL-A", "1", [])
    assert (c.hall, c.seat) == ("HALL-B", "7") and "seat_taken_from_unlabelled_number" in c.flags and c.confidence < a.confidence
    assert d.seat is None and "seat_not_found" in d.flags and d.confidence <= 0.3
    # no hall label anywhere -> hall stays empty
    r = parse_pages([{"index": 0, "text": "990025106001 Seat 4", "method": "text_layer"}])[0]
    assert r.hall is None and "hall_not_found" in r.flags
    # OCR rows are always flagged; several students on one line get no seat
    o = parse_pages([{"index": 0, "text": "Hall: H1\n990025106001 Seat 4", "method": "ocr", "confidence": 50}])[0]
    assert "ocr_text" in o.flags and o.confidence < 0.6
    m = parse_pages([{"index": 0, "text": "Hall: H1\n990025106001 990025106002 3", "method": "text_layer"}])
    assert all(x.seat is None and "several_register_numbers_on_one_line" in x.flags for x in m)


def test_internal_conflicts():
    rows = [dict(id=1, register_number="1", hall="A", seat="1"), dict(id=2, register_number="2", hall="a", seat="1"),
            dict(id=3, register_number="3", hall="A", seat="2"), dict(id=4, register_number="3", hall="A", seat="3"),
            dict(id=5, register_number="4", hall="A", seat="9"), dict(id=6, register_number="4", hall="A", seat="9")]
    c = find_internal_conflicts(rows)
    assert 1 in c and 2 in c and 3 in c and 4 in c and 5 in c and 6 in c
    assert "conflicting" in c[3][0] and "same place" in c[5][0]


def test_full_flow_requires_review_and_confirmation(client, db, admin, staff):
    for r, n in ((REG1, "One"), (REG2, "Two"), (REG3, "Three")):
        make_student(db, r, n)
    e = make_exam(db)
    hall(db, "HALL-A")
    hall(db, "HALL-B", n=10)
    v = make_version(db)
    base = f"/api/admin/seating-import/{v.id}"
    ex = client.post(base + "/extract", headers=staff)
    assert ex.status_code == 200 and ex.json()["rows"] == 4 and ex.json()["needing_attention"] == 2
    rev = client.get(base + "?only_uncertain=true", headers=staff).json()
    assert rev["total"] == 4 and {i["register_number"] for i in rev["entries"]} == {REG3, "990025106009"}
    # staff cannot approve/edit/import
    first = client.get(base, headers=staff).json()["entries"]
    assert client.post(f"/api/admin/seating-import/entries/{first[0]['id']}/review", headers=staff, json={"decision": "approve"}).status_code == 403
    assert client.post(base + "/import", headers=staff, json={"exam_id": e.id, "signature": "0" * 64, "confirm": True}).status_code == 403
    # nothing imported without approval
    pv = client.post(base + "/preview", headers=admin, json={"exam_id": e.id}).json()
    assert pv["summary"]["ready"] == 0 and pv["summary"]["not_approved"] == 4
    assert client.post(base + "/import", headers=admin, json={"exam_id": e.id, "signature": pv["signature"], "confirm": True}).status_code == 409
    # bulk approval only takes confident rows; the incomplete row cannot be approved at all
    assert client.post(base + "/approve-confident", headers=admin).json() == {"approved": 2}
    bad = next(i for i in first if i["register_number"] == "990025106009")
    assert client.post(f"/api/admin/seating-import/entries/{bad['id']}/review", headers=admin, json={"decision": "approve"}).status_code == 422
    # human correction of the uncertain row, then approval
    low = next(i for i in first if i["register_number"] == REG3)
    assert client.patch(f"/api/admin/seating-import/entries/{low['id']}", headers=admin, json={"seat": "7", "reason": "checked on page 1"}).status_code == 200
    assert client.post(f"/api/admin/seating-import/entries/{low['id']}/review", headers=admin, json={"decision": "approve"}).status_code == 200
    client.post(f"/api/admin/seating-import/entries/{bad['id']}/review", headers=admin, json={"decision": "reject"})
    pv = client.post(base + "/preview", headers=admin, json={"exam_id": e.id}).json()
    assert pv["summary"] == {"ready": 3, "blocked": 0, "not_approved": 0, "rejected": 1}
    assert client.post(base + "/import", headers=admin, json={"exam_id": e.id, "signature": "f" * 64, "confirm": True}).status_code == 409   # stale
    assert client.post(base + "/import", headers=admin, json={"exam_id": e.id, "signature": pv["signature"], "confirm": False}).status_code == 422
    ok = client.post(base + "/import", headers=admin, json={"exam_id": e.id, "signature": pv["signature"], "confirm": True})
    assert ok.status_code == 201 and ok.json()["created"] == 3
    db.expire_all()
    got = {(a.student.register_number, a.hall, a.seat, a.source) for a in db.scalars(select(models.Allotment)).all()}
    assert (REG1, "HALL-A", "1", "pdf") in got and (REG3, "HALL-B", "7", "pdf") in got and len(got) == 3
    assert db.scalars(select(models.AllotmentHistory)).all()
    assert client.post(base + "/extract", headers=admin).status_code == 409          # locked after import
    assert any(a.action == "seating_import.imported" for a in db.scalars(select(models.AuditLog)).all())


def test_conflicts_with_existing_data_block_rows(client, db, admin):
    make_student(db, REG1, "One")
    make_student(db, REG2, "Two")
    make_student(db, REG3, "Three")
    e = make_exam(db)
    hall(db, "HALL-A")
    other = db.scalar(select(models.Student).where(models.Student.register_number == REG3))
    db.add(models.Allotment(student_id=other.id, exam_id=e.id, hall="HALL-A", seat="1"))         # seat taken
    s2 = db.scalar(select(models.Student).where(models.Student.register_number == REG2))
    db.add(models.Allotment(student_id=s2.id, exam_id=e.id, hall="HALL-A", seat="5"))            # different seat already
    db.commit()
    text = "Hall: HALL-A\n990025106001 Seat 1\n990025106002 Seat 2\n999999999999 Seat 3\n"
    v = make_version(db, text)
    base = f"/api/admin/seating-import/{v.id}"
    client.post(base + "/extract", headers=admin)
    assert client.post(base + "/approve-confident", headers=admin).json() == {"approved": 3}
    pv = client.post(base + "/preview", headers=admin, json={"exam_id": e.id}).json()
    reasons = {i["register_number"]: " ".join(i["reasons"]) for i in pv["items"]}
    assert pv["summary"]["blocked"] == 3 and pv["summary"]["ready"] == 0
    assert "existing allotment HALL-A/5" in reasons[REG2] and "no student" in reasons["999999999999"]
    assert reasons[REG1]            # seat 1 already belongs to another student
    assert client.post(base + "/import", headers=admin, json={"exam_id": e.id, "signature": pv["signature"], "confirm": True}).status_code == 409
    assert client.post(base + "/import", headers=admin, json={"exam_id": e.id, "signature": pv["signature"], "confirm": True, "skip_blocked": True}).status_code == 409   # nothing ready


def test_duplicate_students_in_document_are_flagged(client, db, admin):
    make_student(db, REG1, "One")
    hall(db, "HALL-A")
    v = make_version(db, "Hall: HALL-A\n990025106001 Seat 1\n990025106001 Seat 2\n")
    base = f"/api/admin/seating-import/{v.id}"
    client.post(base + "/extract", headers=admin)
    rev = client.get(base, headers=admin).json()
    assert all("conflicting allocations" in c for i in rev["entries"] for c in i["conflicts"]) and rev["uncertain"] == 2
    assert client.post(base + "/approve-confident", headers=admin).json() == {"approved": 0}


def test_extract_needs_processed_text_and_logins(client, db, admin, student_auth):
    d = doc_models.OfficialDocument(source_url="upload://t/2", title="Empty", doc_kind="hall_allotment")
    db.add(d)
    db.flush()
    v = doc_models.DocumentVersion(document_id=d.id, version_no=1, sha256="a" * 64, size_bytes=1, storage_path="x")
    db.add(v)
    db.commit()
    assert client.post(f"/api/admin/seating-import/{v.id}/extract", headers=admin).status_code == 409
    assert client.post(f"/api/admin/seating-import/{v.id}/extract", headers=student_auth).status_code == 403
    assert client.get("/api/admin/seating-import/999", headers=admin).status_code == 404
