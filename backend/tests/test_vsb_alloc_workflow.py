"""VSB allocation workflow: stage -> correct -> approve -> preview -> publish -> student view -> bridge.
Synthetic register numbers only (922595... with year digits rewritten, see tests/vsb/fixtures_hall.py)."""
import hashlib
from datetime import date

import pytest
from sqlalchemy import select

from app import doc_models as dm, models
from app.vsb_alloc import service as svc
from app.vsb_alloc.common import PageInput
from conftest import STRONG, login, make_exam, make_student, make_user
from vsb import fixtures_hall as FH, fixtures_seat as FS
from vsb.test_vsb_reconcile import _hall_text
from vsb.test_vsb_seat_parser import SUBS, _seats

R_CSE1, R_CSE13, R_EEE6 = "994177572001", "994177572013", "992829432006"


def _version(db, kind, title):
    d = dm.OfficialDocument(source_url=f"https://vsbec.edu.in/wp-content/uploads/2026/11/{title}.pdf", title=title, doc_kind=kind,
                            exam_date=date(2026, 11, 14), session="FN", origin="crawler")
    db.add(d)
    db.flush()
    v = dm.DocumentVersion(document_id=d.id, version_no=1, sha256=hashlib.sha256(title.encode()).hexdigest(), size_bytes=1,
                           storage_path="missing.pdf", processing_status="processed")
    db.add(v)
    db.commit()
    return v


@pytest.fixture()
def staged(db, client, admin, monkeypatch):
    hv, sv = _version(db, "hall_allotment", "14.11.26-FN-HALL"), _version(db, "seating_allotment", "14.11.26-FN-SEAT")
    ht = _hall_text()
    cut = FH.HEADER + "[23EET"
    pages = {hv.id: [PageInput(0, ht.split(cut)[0]), PageInput(1, cut + ht.split(cut)[1])],
             sv.id: [FS.build_page(0, "MB III 02", _seats(), SUBS)]}
    monkeypatch.setattr(svc, "load_pages", lambda _db, v: pages[v.id])
    for reg in (R_CSE1, R_CSE13, R_EEE6):
        make_student(db, reg, "Demo " + reg[-4:], "CSE" if "104" in reg else "EEE")
    r = client.post("/api/vsb-allocation/batches/build", json={"hall_version_id": hv.id, "seat_version_id": sv.id}, headers=admin)
    assert r.status_code == 201, r.text
    batch = r.json()[0]
    # Test fixture explicitly simulates an administrator checking both official PDFs.
    for record in _recs(client, admin, batch["id"]):
        verified = client.post(f"/api/vsb-allocation/records/{record['id']}/verification", json={
            "status": "FULLY_VERIFIED", "hall_pdf_reference": hv.document.source_url,
            "seat_pdf_reference": sv.document.source_url, "note": "Synthetic fixture: checked against both official PDF inputs."}, headers=admin)
        assert verified.status_code == 200, verified.text
    return batch, hv, sv


def _recs(client, admin, bid, **q):
    return client.get(f"/api/vsb-allocation/batches/{bid}/records", params={"limit": 1000, **q}, headers=admin).json()["records"]


def test_build_stages_a_draft_and_publishes_nothing(client, admin, staged):
    b, _, _ = staged
    assert b["status"] == "draft" and b["exam_date"] == "2026-11-14" and b["session"] == "FN"
    assert b["records"]["total"] == 25 and b["records"].get("pending") == 25
    recs = _recs(client, admin, b["id"])
    one = next(r for r in recs if r["register_number"] == R_CSE13)
    assert (one["hall"], one["seat"], one["department"], one["subject_code"]) == ("MB III 02", "28", "BE-CSE", "23CST302R")
    assert not any(r["published"] for r in recs)
    assert client.get(f"/api/lookup/{R_CSE13}").json()["vsb_allocations"] == []


def test_bulk_approve_only_clean_known_students(client, admin, staged):
    b, _, _ = staged
    r = client.post(f"/api/vsb-allocation/batches/{b['id']}/approve-confident", headers=admin)
    assert r.json()["approved"] == 3          # only the three students that exist in the student database are clean
    recs = _recs(client, admin, b["id"])
    assert sum(x["review_status"] == "approved" for x in recs) == 3
    unknown = next(x for x in recs if not x["student_known"])
    assert unknown["review_status"] == "pending" and "student_not_in_database" in unknown["flags"]


def test_flagged_record_needs_note_and_acknowledgement(client, admin, staged):
    b, _, _ = staged
    rid = next(r["id"] for r in _recs(client, admin, b["id"]) if not r["student_known"])
    url = f"/api/vsb-allocation/records/{rid}/review"
    assert client.post(url, json={"decision": "approve"}, headers=admin).status_code == 422
    assert client.post(url, json={"decision": "approve", "note": "checked against PDF"}, headers=admin).status_code == 200


def test_missing_seat_cannot_be_approved_until_corrected(client, admin, staged, db, monkeypatch):
    b, hv, sv = staged
    seats = _seats()
    gone = seats.pop(28)
    pages = {sv.id: [FS.build_page(0, "MB III 02", seats, SUBS)]}
    ht = _hall_text(); cut = FH.HEADER + "[23EET"
    pages[hv.id] = [PageInput(0, ht.split(cut)[0]), PageInput(1, cut + ht.split(cut)[1])]
    monkeypatch.setattr(svc, "load_pages", lambda _db, v: pages[v.id])
    nb = client.post("/api/vsb-allocation/batches/build", json={"hall_version_id": hv.id, "seat_version_id": sv.id}, headers=admin).json()[0]
    # The earlier draft was replaced. Do not compare ids: SQLite may reuse the freed rowid, PostgreSQL never does.
    listed = client.get("/api/vsb-allocation/batches", headers=admin).json()
    drafts = [x for x in listed if x["status"] == "draft" and x["exam_date"] == nb["exam_date"] and x["session"] == nb["session"]]
    assert [x["id"] for x in drafts] == [nb["id"]], "exactly one draft per (date, session) must remain"
    if nb["id"] == b["id"]:
        assert not any(r["register_number"] == gone and r["seat"] for r in _recs(client, admin, b["id"])), "old rows must not survive"
    rec = next(r for r in _recs(client, admin, nb["id"]) if r["register_number"] == gone)
    assert "missing_in_seating_pdf" in rec["flags"] and rec["seat"] is None
    assert client.post(f"/api/vsb-allocation/records/{rec['id']}/review", json={"decision": "approve", "note": "x y z", "acknowledge": True},
                       headers=admin).status_code == 422
    e = client.patch(f"/api/vsb-allocation/records/{rec['id']}", json={"seat": "28", "reason": "read from PDF page 1"}, headers=admin)
    assert e.status_code == 200 and e.json()["seat"] == "28" and e.json()["edited"]
    assert e.json()["verification_status"] == "UNRESOLVED"
    blocked = client.post(f"/api/vsb-allocation/records/{rec['id']}/review", json={"decision": "approve", "note": "corrected"}, headers=admin)
    assert blocked.status_code == 422
    verified = client.post(f"/api/vsb-allocation/records/{rec['id']}/verification", json={
        "status": "FULLY_VERIFIED", "hall_pdf_reference": hv.document.source_url, "seat_pdf_reference": sv.document.source_url,
        "note": "Seat corrected after checking official seat-sheet PDF."}, headers=admin)
    assert verified.status_code == 200
    assert client.post(f"/api/vsb-allocation/records/{rec['id']}/review", json={"decision": "approve", "note": "corrected"}, headers=admin).status_code == 200


def _approve_known(client, admin, bid):
    client.post(f"/api/vsb-allocation/batches/{bid}/approve-confident", headers=admin)


def test_publish_requires_preview_signature_and_confirmation(client, admin, staged):
    b, _, _ = staged
    _approve_known(client, admin, b["id"])
    pv = client.post(f"/api/vsb-allocation/batches/{b['id']}/publish/preview", headers=admin).json()
    assert pv["will_publish"] == 3 and pv["pending"] == 22
    url = f"/api/vsb-allocation/batches/{b['id']}/publish"
    assert client.post(url, json={"signature": pv["signature"], "confirm": False}, headers=admin).status_code == 422
    assert client.post(url, json={"signature": "0" * 64, "confirm": True}, headers=admin).status_code == 409
    r = client.post(url, json={"signature": pv["signature"], "confirm": True, "acknowledge_open_issues": True}, headers=admin)
    assert r.status_code == 200 and r.json()["published"] == 3


def test_open_error_issues_block_publishing_until_acknowledged(client, admin, staged, db):
    b, _, _ = staged
    db.add(dm.VsbAllocIssue(batch_id=b["id"], kind="hall_total_mismatch", severity="error", message="test", status="open"))
    db.commit()
    _approve_known(client, admin, b["id"])
    pv = client.post(f"/api/vsb-allocation/batches/{b['id']}/publish/preview", headers=admin).json()
    r = client.post(f"/api/vsb-allocation/batches/{b['id']}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin)
    assert r.status_code == 409 and "error issue" in r.json()["detail"]


def _publish(client, admin, bid):
    pv = client.post(f"/api/vsb-allocation/batches/{bid}/publish/preview", headers=admin).json()
    r = client.post(f"/api/vsb-allocation/batches/{bid}/publish", json={"signature": pv["signature"], "confirm": True,
                                                                     "acknowledge_open_issues": True}, headers=admin)
    assert r.status_code == 200, r.text


def test_students_see_only_approved_published_records(client, admin, staged, db):
    b, _, _ = staged
    _approve_known(client, admin, b["id"])
    s = db.scalar(select(models.Student).where(models.Student.register_number == R_CSE13))
    make_user(db, "stud13", "student", student=s)
    own = login(client, "stud13")
    assert client.get("/api/vsb-allocation/my", headers=own).json()["allocations"] == []      # approved but NOT published yet
    _publish(client, admin, b["id"])
    mine = client.get("/api/vsb-allocation/my", headers=own).json()["allocations"]
    assert len(mine) == 1
    m = mine[0]
    assert (m["register_number"], m["hall"], m["seat"], m["subject_code"], m["date"], m["session"], m["department"]) == \
        (R_CSE13, "MB III 02", "28", "23CST302R", "2026-11-14", "FN", "BE-CSE")
    assert m["source"]["url"].startswith("https://vsbec.edu.in/")
    pub = client.get(f"/api/lookup/{R_CSE13}").json()["vsb_allocations"]
    assert [x["seat"] for x in pub] == ["28"]


def test_unapproved_and_unknown_students_are_never_exposed(client, admin, staged, db):
    b, _, _ = staged
    _approve_known(client, admin, b["id"])
    _publish(client, admin, b["id"])
    s = make_student(db, "994177572002", "Pending One", "CSE")          # exists but its record was never approved
    rec = db.scalar(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.register_number == "994177572002"))
    rec.student_id = s.id
    db.commit()
    assert client.get("/api/lookup/994177572002").json()["vsb_allocations"] == []


def test_withdraw_hides_records_and_blocks_edits_while_published(client, admin, staged, db):
    b, _, _ = staged
    _approve_known(client, admin, b["id"])
    _publish(client, admin, b["id"])
    rid = next(r["id"] for r in _recs(client, admin, b["id"]) if r["published"])
    assert client.patch(f"/api/vsb-allocation/records/{rid}", json={"seat": "5", "reason": "try"}, headers=admin).status_code == 409
    assert client.post(f"/api/vsb-allocation/batches/{b['id']}/withdraw", json={"reason": "wrong PDF used"}, headers=admin).status_code == 200
    assert client.get(f"/api/lookup/{R_CSE13}").json()["vsb_allocations"] == []


def test_permissions(client, admin, staff, student_auth, staged):
    b, _, _ = staged
    base = f"/api/vsb-allocation/batches/{b['id']}"
    assert client.get("/api/vsb-allocation/batches").status_code == 401
    assert client.get("/api/vsb-allocation/batches", headers=student_auth).status_code == 403
    assert client.get("/api/vsb-allocation/batches", headers=staff).status_code == 200
    assert client.post(base + "/approve-confident", headers=staff).status_code == 403
    assert client.post(base + "/publish", json={"signature": "0" * 64, "confirm": True}, headers=staff).status_code == 403
    assert client.get("/api/vsb-allocation/my", headers=admin).status_code == 403


def test_bridge_into_allotments_uses_normal_rules(client, admin, staged, db):
    b, _, _ = staged
    _approve_known(client, admin, b["id"])
    _publish(client, admin, b["id"])
    pv = client.post(f"/api/vsb-allocation/batches/{b['id']}/bridge/preview", headers=admin).json()
    assert pv["summary"]["ready"] == 0 and pv["summary"]["blocked"] == 3        # no matching examination yet: nothing invented
    e = make_exam(db, code="23CST302R", date="2026-11-14")
    pv = client.post(f"/api/vsb-allocation/batches/{b['id']}/bridge/preview", headers=admin).json()
    ready = [i for i in pv["items"] if i["state"] == "ready"]
    assert {i["register_number"] for i in ready} == {R_CSE1, R_CSE13}            # the EEE student's subject has no exam
    r = client.post(f"/api/vsb-allocation/batches/{b['id']}/bridge", json={"signature": pv["signature"], "confirm": True, "skip_blocked": True},
                    headers=admin)
    assert r.status_code == 201 and r.json()["created"] == 2
    a = db.scalar(select(models.Allotment).where(models.Allotment.exam_id == e.id).join(models.Student).where(
        models.Student.register_number == R_CSE13))
    assert (a.hall, a.seat, a.source) == ("MB III 02", "28", "vsb")


def test_auto_stage_only_creates_drafts(db, client, admin, staged):
    b, hv, sv = staged
    assert svc.auto_stage(db, "scheduler") == []          # same source versions are already staged: nothing to do
    assert db.scalar(select(dm.VsbAllocBatch.status).where(dm.VsbAllocBatch.id == b["id"])) == "draft"
