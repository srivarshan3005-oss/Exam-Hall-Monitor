"""Regression tests for the two confirmed critical defects in UPDATED_CANDIDATE_v2.

DEFECT A  An unrelated edit (department, note) set edited=True, which used to switch off the hard-conflict check, so a
          record with hall_mismatch could be approved after a department-only edit.
DEFECT B  Migration 0014 gave legacy rows UNRESOLVED, but public lookups only checked approved+published, so legacy rows
          stayed visible as if confirmed.
All register numbers are synthetic or the public sample rows used elsewhere in the suite.
"""
import json
import sqlite3

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text

from app import doc_models as dm, models
from app.dbcheck import alembic_config
from conftest import make_student, make_user, login
from test_vsb_verification_enforcement import (HALL_PDF, SEAT_PDF, V, _approve, _audit_actions, _batch_id, _records, _row, _stage)

REG_A, REG_B, REG_C = "993684095311", "993684095312", "993684095313"


def _mismatched(client, admin, db, reg=REG_A, seat="5"):
    """A FULLY_VERIFIED record (17 Nov AN) whose hall list and seat sheet name different halls."""
    make_student(db, reg, "Conflict Student", "ECE", 2)
    body = _stage(client, admin, {reg: [_row(reg, "2026-11-17", "AN", seat=seat, hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    rid = _records(client, admin, bid)[0]["id"]
    rec = db.get(dm.VsbAllocRecord, rid)
    det = json.loads(rec.detail or "{}")
    det["hall_pdf_hall"], det["seat_pdf_hall"] = "MB III 103", "MB III A103"
    rec.detail, rec.flags = json.dumps(det), json.dumps(["hall_mismatch"])
    db.commit()
    return bid, rid


def _status(client, admin, bid, rid):
    return next(r for r in _records(client, admin, bid) if r["id"] == rid)


# ------------------------------------------------------------------------------------------------- DEFECT A
def test_defect_a_unrelated_edits_never_clear_a_hall_mismatch(client, admin, db):
    bid, rid = _mismatched(client, admin, db)
    assert _approve(client, admin, rid).status_code == 422
    for body in ({"department": "Mechanical", "reason": "department typo"},
                 {"note": "checked the noticeboard", "reason": "note only"}):
        r = client.patch(f"{V}/records/{rid}", json=body, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "FULLY_VERIFIED"       # unrelated edits never alter verification
        assert r.json()["edited"] is True
        for extra in ({}, {"acknowledge": True}):                        # nor does acknowledgement help
            blocked = _approve(client, admin, rid, **extra)
            assert blocked.status_code == 422, (body, extra)
            assert "different halls" in blocked.json()["detail"]
    assert _status(client, admin, bid, rid)["review_status"] == "pending"
    edits = [a for a in db.scalars(select(models.AuditLog).where(models.AuditLog.action == "vsb_alloc.record_edited")).all()]
    assert len(edits) == 2 and "department" in edits[0].details


def test_defect_a_bulk_and_publish_paths_also_refuse_the_conflict(client, admin, db):
    bid, rid = _mismatched(client, admin, db)
    client.patch(f"{V}/records/{rid}", json={"department": "ECE", "reason": "department corrected"}, headers=admin)
    db.expire_all()
    rec = db.get(dm.VsbAllocRecord, rid)
    rec.flags = "[]"                                        # even with the stored flag absent, the live PDF evidence still conflicts
    db.commit()
    assert client.post(f"{V}/batches/{bid}/approve-confident", headers=admin).json()["approved"] == 0
    # a row forced to 'approved' by manual SQL must not publish either
    rec = db.get(dm.VsbAllocRecord, rid)
    rec.review_status = "approved"
    db.commit()
    pv = client.post(f"{V}/batches/{bid}/publish/preview", headers=admin).json()
    assert pv["will_publish"] == 0
    r = client.post(f"{V}/batches/{bid}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin)
    assert r.status_code == 409
    db.expire_all()
    assert db.get(dm.VsbAllocRecord, rid).published is False


def test_defect_a_legitimate_resolution_unblocks_and_is_voided_by_a_later_change(client, admin, staff, db):
    bid, rid = _mismatched(client, admin, db)
    url = f"{V}/records/{rid}/resolve-conflict"
    ok = {"flag": "hall_mismatch", "pdf_reference": SEAT_PDF, "note": "MB III 103 is the printed hall on page 4"}
    assert client.post(url, json=ok, headers=staff).status_code in (401, 403)                 # admins only
    for bad in ({"pdf_reference": "https://evil.example/a.pdf"}, {"pdf_reference": "http://vsbec.edu.in/a.pdf"}, {"note": "short"}):
        assert client.post(url, json={**ok, **bad}, headers=admin).status_code == 422, bad
    r = client.post(url, json=ok, headers=admin)
    assert r.status_code == 200, r.text
    assert "vsb_alloc.conflict_resolved" in _audit_actions(db)
    assert _approve(client, admin, rid).status_code == 200                                     # now legitimately approvable
    # a later change to a critical field voids the resolution and the verification
    client.post(f"{V}/records/{rid}/review", json={"decision": "reset", "note": "redo"}, headers=admin)
    client.patch(f"{V}/records/{rid}", json={"seat": "6", "reason": "seat corrected in test"}, headers=admin)
    client.post(f"{V}/records/{rid}/verification", json={"status": "FULLY_VERIFIED", "hall_pdf_reference": HALL_PDF,
                                                         "seat_pdf_reference": SEAT_PDF, "note": "re-checked both PDFs"}, headers=admin)
    assert _approve(client, admin, rid).status_code == 422


def test_defect_a_resolution_requires_a_hall_the_pdfs_actually_print(client, admin, db):
    bid, rid = _mismatched(client, admin, db)
    client.patch(f"{V}/records/{rid}", json={"hall": "MB III 999", "reason": "wrong hall typed"}, headers=admin)
    # critical edit reset verification, so resolution is refused until the record is verified again
    ok = {"flag": "hall_mismatch", "pdf_reference": SEAT_PDF, "note": "attempted resolution"}
    assert client.post(f"{V}/records/{rid}/resolve-conflict", json=ok, headers=admin).status_code == 409
    client.post(f"{V}/records/{rid}/verification", json={"status": "FULLY_VERIFIED", "hall_pdf_reference": HALL_PDF,
                                                         "seat_pdf_reference": SEAT_PDF, "note": "re-checked"}, headers=admin)
    assert client.post(f"{V}/records/{rid}/resolve-conflict", json=ok, headers=admin).status_code == 422


def test_defect_a_duplicate_seat_is_checked_live_not_from_stored_flags(client, admin, db):
    make_student(db, REG_A, "A", "ECE", 2)
    make_student(db, REG_B, "B", "ECE", 2)
    body = _stage(client, admin, {REG_A: [_row(REG_A, "2026-11-17", "AN", seat="7", hall="MB III 103")],
                                  REG_B: [_row(REG_B, "2026-11-17", "AN", seat="7", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    recs = _records(client, admin, bid)
    for r in recs:
        client.patch(f"{V}/records/{r['id']}", json={"department": "ECE", "reason": "unrelated edit"}, headers=admin)
    for r in recs:
        row = db.get(dm.VsbAllocRecord, r["id"]); row.flags = "[]"
    db.commit()
    assert all(_approve(client, admin, r["id"], acknowledge=True).status_code == 422 for r in recs)


# ------------------------------------------------------------------------------------------------- DEFECT B
def _published_trio(client, admin, db):
    """Three students in one published batch carrying FULLY_VERIFIED / HALL_LIST_CONFIRMED / UNRESOLVED."""
    for reg in (REG_A, REG_B, REG_C):
        make_student(db, reg, f"Student {reg[-2:]}", "ECE", 2)
    body = _stage(client, admin, {reg: [_row(reg, "2026-11-17", "AN", seat=str(i + 1), hall="MB III 103")]
                                  for i, reg in enumerate((REG_A, REG_B, REG_C))})
    bid = _batch_id(body, "2026-11-17", "AN")
    states = {REG_A: "FULLY_VERIFIED", REG_B: "HALL_LIST_CONFIRMED", REG_C: "UNRESOLVED"}
    for r in db.scalars(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.batch_id == bid)).all():
        r.verification_status, r.review_status, r.published = states[r.register_number], "approved", True
    db.get(dm.VsbAllocBatch, bid).status = "published"           # exactly what a database upgrade leaves behind
    db.commit()
    return bid


def test_defect_b_public_lookup_applies_one_verification_policy(client, admin, db):
    _published_trio(client, admin, db)
    full = client.get(f"/api/portal/lookup/{REG_A}").json()
    hall = client.get(f"/api/portal/lookup/{REG_B}").json()
    legacy = client.get(f"/api/portal/lookup/{REG_C}").json()
    e = full["entries"][0]
    assert (e["hall"], e["seat"], e["verification_status"]) == ("MB III 103", "1", "FULLY_VERIFIED") and e["seat_map"]
    h = hall["entries"][0]
    assert (h["hall"], h["seat"], h["verification_status"]) == ("MB III 103", None, "HALL_LIST_CONFIRMED") and not h["seat_map"]
    assert "not yet been checked" in h["verification_label"]
    assert legacy["entries"] == []                                   # UNRESOLVED is never presented as an allocation
    assert "MB III 103" not in json.dumps(legacy) and "UNRESOLVED" not in json.dumps(legacy)
    assert legacy["verification_note"] == full["verification_note"]  # response shape does not reveal which students have hidden rows
    strip = lambda d: {k: v for k, v in d.items() if k not in ("student",)}
    nobody = make_student(db, "993684095399", "Nobody", "ECE", 2)
    assert strip(legacy) == strip(client.get("/api/portal/lookup/993684095399").json())


def test_defect_b_seat_map_and_counts_follow_the_same_policy(client, admin, db):
    bid = _published_trio(client, admin, db)
    make_user(db, "s_full", "student", student=db.scalar(select(models.Student).where(models.Student.register_number == REG_A)))
    make_user(db, "s_hall", "student", student=db.scalar(select(models.Student).where(models.Student.register_number == REG_B)))
    make_user(db, "s_legacy", "student", student=db.scalar(select(models.Student).where(models.Student.register_number == REG_C)))
    me = lambda u: client.get("/api/vsb-allocation/my", headers=login(client, u))
    full, hall, legacy = me("s_full").json(), me("s_hall").json(), me("s_legacy").json()
    assert len(full["allocations"]) == 1 and full["withheld_unverified"] == 0
    assert hall["allocations"][0]["seat"] is None and hall["allocations"][0]["verification_status"] == "HALL_LIST_CONFIRMED"
    assert legacy["allocations"] == [] and legacy["withheld_unverified"] == 1 and legacy["verification_note"]
    seatmap = lambda reg: client.get(f"/api/portal/seatmap/{reg}", params={"kind": "vsb", "ref": bid})
    assert seatmap(REG_A).status_code == 200
    for reg in (REG_B, REG_C):                                          # hall-only and unresolved rows never reveal seats
        assert seatmap(reg).status_code == 404, reg
    taken = json.dumps(seatmap(REG_A).json())
    assert '"2"' not in taken and '"3"' not in taken                    # other students' seats are not leaked
    from datetime import date
    db.get(dm.VsbAllocBatch, bid).exam_date = date(2099, 1, 15)         # notices list only upcoming dates
    db.commit()
    pub = client.get("/api/portal/notices").json()
    dates = [s for d in pub.get("dates", []) for s in d.get("sessions", [])]
    assert sum(s["allotments"] for s in dates) == 2                  # unresolved legacy row is not counted


def test_defect_b_admin_can_inspect_and_resolve_legacy_records(client, admin, staff, db):
    bid = _published_trio(client, admin, db)
    rows = {r["register_number"]: r for r in _records(client, admin, bid)}
    assert rows[REG_C]["verification_status"] == "UNRESOLVED" and rows[REG_C]["published"] is True   # history preserved
    assert client.get(f"{V}/batches/{bid}/records", headers=staff).status_code == 200
    # withdraw, verify through the authorised workflow, then the record is no longer unresolved
    assert client.post(f"{V}/batches/{bid}/withdraw", json={"reason": "legacy review in test"}, headers=admin).status_code == 200
    ok = client.post(f"{V}/records/{rows[REG_C]['id']}/verification", json={
        "status": "FULLY_VERIFIED", "hall_pdf_reference": HALL_PDF, "seat_pdf_reference": SEAT_PDF, "note": "checked both PDFs"}, headers=admin)
    assert ok.status_code == 200 and ok.json()["verification_status"] == "FULLY_VERIFIED"
    assert "vsb_alloc.record_verified" in _audit_actions(db)


def test_defect_b_unresolved_records_cannot_be_approved_or_published(client, admin, db):
    make_student(db, REG_C, "C", "ECE", 2)
    body = _stage(client, admin, {REG_C: [_row(REG_C, "2026-11-16", "FN", seat="3", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-16", "FN")
    rid = _records(client, admin, bid)[0]["id"]
    assert _status(client, admin, bid, rid)["verification_status"] == "UNRESOLVED"
    assert _approve(client, admin, rid, acknowledge=True).status_code == 422
    assert client.post(f"{V}/batches/{bid}/approve-confident", headers=admin).json()["approved"] == 0
    db.get(dm.VsbAllocRecord, rid).review_status = "approved"; db.commit()
    pv = client.post(f"{V}/batches/{bid}/publish/preview", headers=admin).json()
    assert pv["will_publish"] == 0
    assert client.post(f"{V}/batches/{bid}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin).status_code == 409
    assert client.get(f"/api/portal/lookup/{REG_C}").json()["entries"] == []


def _insert(conn, table, values):
    cols = inspect(conn).get_columns(table)
    row = dict(values)
    for c in cols:
        if c["name"] in row or c.get("nullable", True) or c.get("default") is not None:
            continue
        t = str(c["type"]).upper()
        row[c["name"]] = 0 if any(x in t for x in ("INT", "BOOL", "FLOAT")) else "2026-11-17 00:00:00" if any(x in t for x in ("DATE", "TIME")) else "x"
    conn.execute(text(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join(':' + k for k in row)})"), row)


def test_defect_b_database_upgrade_preserves_legacy_rows_and_renames_status(tmp_path):
    """Published + UNRESOLVED after a real 0014 -> head upgrade: nothing deleted or upgraded, history kept, audit row written."""
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    cfg = alembic_config(url)
    command.upgrade(cfg, "0014")
    eng = create_engine(url)
    with eng.begin() as c:
        _insert(c, "vsb_alloc_batches", {"id": 1, "exam_date": "2026-11-17", "session": "AN", "status": "published", "exam_name": "X"})
        for i, st in enumerate(("FULLY_VERIFIED", "HALL_LIST_ONLY", "UNRESOLVED"), start=1):
            _insert(c, "vsb_alloc_records", {"id": i, "batch_id": 1, "register_number": f"92259910640{i}", "hall": "MB III 103", "seat": str(i),
                                             "subject_code": "23ECT307", "review_status": "approved", "published": 1,
                                             "verification_status": st})
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")                                      # idempotent
    with eng.connect() as c:
        got = dict(c.execute(text("SELECT id, verification_status FROM vsb_alloc_records ORDER BY id")).fetchall())
        assert got == {1: "FULLY_VERIFIED", 2: "HALL_LIST_CONFIRMED", 3: "UNRESOLVED"}
        assert c.execute(text("SELECT count(*) FROM vsb_alloc_records WHERE published=1 AND review_status='approved'")).scalar() == 3
        assert c.execute(text("SELECT count(*) FROM audit_logs WHERE action='vsb_alloc.legacy_unresolved_hidden'")).scalar() == 1
    with pytest.raises(Exception):
        with eng.begin() as c:
            c.execute(text("UPDATE vsb_alloc_records SET verification_status='MADE_UP' WHERE id=1"))
    command.downgrade(cfg, "0014")
    with eng.connect() as c:
        assert c.execute(text("SELECT verification_status FROM vsb_alloc_records WHERE id=2")).scalar() == "HALL_LIST_ONLY"
