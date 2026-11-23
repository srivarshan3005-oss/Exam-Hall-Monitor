"""Regression tests for the official VSB verification rules (added in UPDATED_CANDIDATE_v2).

Rules covered: FULLY_VERIFIED / HALL_LIST_CONFIRMED / UNRESOLVED gating on individual approval, bulk approval and publishing;
acknowledgement never bypasses verification; critical-field edits invalidate verification; every decision is audited;
unpublished records stay private; the hall correction is preserved as provenance.
All register numbers are either the public sample rows used elsewhere in the suite or synthetic.
"""
import json

from sqlalchemy import select

from app import doc_models as dm, models
from app.vsb_alloc import original_import as oi
from conftest import make_student
from operator_data import correction_register, requires_allotments, requires_corrections, requires_provenance, requires_variant_review

HALL_PDF = "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-hall.pdf"
SEAT_PDF = "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-seat.pdf"
CHART = "d12cded03485_17.11.26-AN-seat_page_23.png"
IMPORT = "/api/vsb-allocation/import/original"
V = "/api/vsb-allocation"


def _row(reg, date, sess, hall="MB III A103", seat="23", code="23ECT307"):
    return {"register_number": reg, "exam_date": date, "session": sess, "hall_number": hall, "seat_number": seat,
            "subject_code": code, "subject_name": "DIGITAL ELECTRONICS", "page": 4, "source_url": SEAT_PDF,
            "seating_image": f"evidence/{CHART}"}


def _stage(client, admin, payload):
    raw = json.dumps(payload).encode()
    r = client.post(IMPORT + "?dry_run=false&confirm=true", files={"file": ("allotments.json", raw, "application/json")}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _records(client, admin, bid):
    return client.get(f"{V}/batches/{bid}/records", params={"limit": 1000}, headers=admin).json()["records"]


def _batch_id(body, date, sess):
    return next(b["id"] for b in body["batches"] if b["exam_date"] == date and b["session"] == sess)


def _approve(client, admin, rid, **extra):
    return client.post(f"{V}/records/{rid}/review", json={"decision": "approve", "note": "checked", **extra}, headers=admin)


def _audit_actions(db):
    return [a.action for a in db.scalars(select(models.AuditLog)).all()]


def test_import_assigns_status_by_session_exactly_as_specified(client, admin):
    """17 Nov AN -> FULLY_VERIFIED; 17 Nov FN and 18 Nov -> HALL_LIST_CONFIRMED; 16 Nov -> UNRESOLVED; unknown future date -> UNRESOLVED."""
    payload = {
        "993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")],
        "993684095302": [_row("993684095302", "2026-11-17", "FN", seat="2", hall="MB III 103")],
        "993684095303": [_row("993684095303", "2026-11-18", "FN", seat="3", hall="MB III 103")],
        "993684095304": [_row("993684095304", "2026-11-16", "FN", seat="4", hall="MB III 103")],
        "993684095305": [_row("993684095305", "2026-11-16", "AN", seat="5", hall="MB III 103")],
        "993684095306": [_row("993684095306", "2026-11-24", "FN", seat="6", hall="MB III 103")],
    }
    body = _stage(client, admin, payload)
    got = {(b["exam_date"], b["session"]): {r["register_number"]: r["verification_status"] for r in _records(client, admin, b["id"])}
           for b in body["batches"]}
    assert set(got[("2026-11-17", "AN")].values()) == {"FULLY_VERIFIED"}
    assert set(got[("2026-11-17", "FN")].values()) == {"HALL_LIST_CONFIRMED"}
    assert set(got[("2026-11-18", "FN")].values()) == {"HALL_LIST_CONFIRMED"}
    assert set(got[("2026-11-16", "FN")].values()) == {"UNRESOLVED"}
    assert set(got[("2026-11-16", "AN")].values()) == {"UNRESOLVED"}
    assert set(got[("2026-11-24", "FN")].values()) == {"UNRESOLVED"}


def test_hall_list_only_and_unresolved_cannot_be_approved_even_with_note_and_acknowledgement(client, admin, db):
    body = _stage(client, admin, {
        "993684095302": [_row("993684095302", "2026-11-17", "FN", seat="2", hall="MB III 103")],
        "993684095304": [_row("993684095304", "2026-11-16", "FN", seat="4", hall="MB III 103")]})
    for b in body["batches"]:
        for r in _records(client, admin, b["id"]):
            for extra in ({}, {"acknowledge": True}):
                resp = _approve(client, admin, r["id"], **extra)
                assert resp.status_code == 422, (r["verification_status"], extra, resp.text)
            assert _records(client, admin, b["id"])[0]["review_status"] == "pending"
    assert "vsb_alloc.record_approve" not in _audit_actions(db)       # a refused approval leaves no approval trace


def test_bulk_approval_applies_the_same_restrictions_as_individual_approval(client, admin, db):
    make_student(db, "993684095301", "Fully Verified", "ECE", 2)
    make_student(db, "993684095302", "Hall List Only", "ECE", 2)
    make_student(db, "993684095304", "Unresolved", "ECE", 2)
    body = _stage(client, admin, {
        "993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")],
        "993684095302": [_row("993684095302", "2026-11-17", "FN", seat="2", hall="MB III 103")],
        "993684095304": [_row("993684095304", "2026-11-16", "FN", seat="4", hall="MB III 103")]})
    approved = {}
    for b in body["batches"]:
        n = client.post(f"{V}/batches/{b['id']}/approve-confident", headers=admin).json()["approved"]
        approved[(b["exam_date"], b["session"])] = n
        statuses = {r["review_status"] for r in _records(client, admin, b["id"])}
        assert statuses == ({"approved"} if n else {"pending"})
    assert approved == {("2026-11-17", "AN"): 1, ("2026-11-17", "FN"): 0, ("2026-11-16", "FN"): 0}


def test_bulk_approval_writes_one_audit_row_per_record(client, admin, db):
    make_student(db, "993684095301", "Fully Verified", "ECE", 2)
    body = _stage(client, admin, {"993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    assert client.post(f"{V}/batches/{bid}/approve-confident", headers=admin).json()["approved"] == 1
    rid = _records(client, admin, bid)[0]["id"]
    rows = db.scalars(select(models.AuditLog).where(models.AuditLog.action == "vsb_alloc.record_approve")).all()
    assert [a.target for a in rows] == [str(rid)] and json.loads(rows[0].details)["via"] == "bulk"
    assert "vsb_alloc.bulk_approved" in _audit_actions(db)


def test_critical_field_edit_invalidates_verification_but_department_edit_does_not(client, admin):
    body = _stage(client, admin, {"993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    rid = _records(client, admin, bid)[0]["id"]
    dept = client.patch(f"{V}/records/{rid}", json={"department": "ECE", "reason": "department corrected"}, headers=admin)
    assert dept.status_code == 200 and dept.json()["verification_status"] == "FULLY_VERIFIED"
    for field, value in (("hall", "MB III 104"), ("seat", "9"), ("subject_code", "23ECT999")):
        # restore a verified state, then change exactly one critical field
        ok = client.post(f"{V}/records/{rid}/verification", json={
            "status": "FULLY_VERIFIED", "hall_pdf_reference": HALL_PDF, "seat_pdf_reference": SEAT_PDF,
            "note": "re-verified against the official PDFs"}, headers=admin)
        assert ok.status_code == 200 and ok.json()["verification_status"] == "FULLY_VERIFIED"
        edit = client.patch(f"{V}/records/{rid}", json={field: value, "reason": f"{field} corrected in test"}, headers=admin)
        assert edit.status_code == 200, edit.text
        assert edit.json()["verification_status"] == "UNRESOLVED", field
        assert edit.json()["review_status"] == "pending"
        assert _approve(client, admin, rid, acknowledge=True).status_code == 422


def test_verification_requires_official_https_pdf_references_and_is_audited(client, admin, db):
    body = _stage(client, admin, {"993684095302": [_row("993684095302", "2026-11-17", "FN", seat="2", hall="MB III 103")]})
    rid = _records(client, admin, _batch_id(body, "2026-11-17", "FN"))[0]["id"]
    url = f"{V}/records/{rid}/verification"
    base = {"status": "FULLY_VERIFIED", "hall_pdf_reference": HALL_PDF, "seat_pdf_reference": SEAT_PDF, "note": "both PDFs checked"}
    for bad in ({"hall_pdf_reference": "http://vsbec.edu.in/x.pdf"}, {"hall_pdf_reference": "https://evil.example/x.pdf"},
                {"seat_pdf_reference": "https://vsbec.edu.in.evil.example/x.pdf"}, {"seat_pdf_reference": None},
                {"seat_pdf_reference": "https://vsbec.edu.in/page.html"}):
        assert client.post(url, json={**base, **bad}, headers=admin).status_code == 422, bad
    assert _records(client, admin, _batch_id(body, "2026-11-17", "FN"))[0]["verification_status"] == "HALL_LIST_CONFIRMED"
    assert client.post(url, json=base, headers=admin).status_code == 200
    assert "vsb_alloc.record_verified" in _audit_actions(db)


def test_only_administrators_can_verify_or_approve(client, admin, staff, student_auth):
    body = _stage(client, admin, {"993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    rid = _records(client, admin, bid)[0]["id"]
    ver = {"status": "FULLY_VERIFIED", "hall_pdf_reference": HALL_PDF, "seat_pdf_reference": SEAT_PDF, "note": "attempt"}
    for who in (staff, student_auth, {}):
        assert client.post(f"{V}/records/{rid}/verification", json=ver, headers=who).status_code in (401, 403)
        assert client.post(f"{V}/records/{rid}/review", json={"decision": "approve", "note": "x y z"}, headers=who).status_code in (401, 403)
        assert client.post(f"{V}/batches/{bid}/approve-confident", headers=who).status_code in (401, 403)


def test_publish_never_exposes_unverified_or_unapproved_records_and_students_see_only_their_own(client, admin, db):
    make_student(db, "993684095301", "Verified Student", "ECE", 2)
    make_student(db, "993684095302", "Hall List Student", "ECE", 2)
    body = _stage(client, admin, {
        "993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")],
        "993684095302": [_row("993684095302", "2026-11-17", "FN", seat="2", hall="MB III 103")]})
    an, fn = _batch_id(body, "2026-11-17", "AN"), _batch_id(body, "2026-11-17", "FN")
    # the hall-list-only batch has nothing approvable: publishing it is refused
    pv = client.post(f"{V}/batches/{fn}/publish/preview", headers=admin).json()
    assert pv["will_publish"] == 0
    assert client.post(f"{V}/batches/{fn}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin).status_code == 409
    # the fully verified batch publishes only after approval
    assert client.post(f"{V}/batches/{an}/approve-confident", headers=admin).json()["approved"] == 1
    pv = client.post(f"{V}/batches/{an}/publish/preview", headers=admin).json()
    assert pv["will_publish"] == 1
    assert client.post(f"{V}/batches/{an}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin).status_code == 200
    mine = client.get("/api/portal/lookup/993684095301").json()
    other = client.get("/api/portal/lookup/993684095302").json()
    assert any(e["kind"] == "vsb" for e in mine["entries"])
    assert all(e["kind"] != "vsb" for e in other["entries"])
    assert "993684095302" not in json.dumps(mine)                          # no other student's register number
    assert "vsb_alloc.published" in _audit_actions(db)


def test_publish_refuses_a_legacy_approved_row_that_is_not_fully_verified(client, admin, db):
    """Defence in depth: even if an approved row is somehow not FULLY_VERIFIED (legacy data, manual SQL), publication stops."""
    make_student(db, "993684095301", "Verified Student", "ECE", 2)
    body = _stage(client, admin, {"993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    assert client.post(f"{V}/batches/{bid}/approve-confident", headers=admin).json()["approved"] == 1
    rec = db.scalar(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.batch_id == bid))
    rec.verification_status = "HALL_LIST_CONFIRMED"
    db.commit()
    pv = client.post(f"{V}/batches/{bid}/publish/preview", headers=admin).json()
    assert pv["will_publish"] == 0
    r = client.post(f"{V}/batches/{bid}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin)
    assert r.status_code == 409
    db.refresh(rec)
    assert rec.published is False


def test_published_batch_cannot_be_edited_reverified_or_re_decided(client, admin, db):
    make_student(db, "993684095301", "Verified Student", "ECE", 2)
    body = _stage(client, admin, {"993684095301": [_row("993684095301", "2026-11-17", "AN", seat="1", hall="MB III 103")]})
    bid = _batch_id(body, "2026-11-17", "AN")
    client.post(f"{V}/batches/{bid}/approve-confident", headers=admin)
    pv = client.post(f"{V}/batches/{bid}/publish/preview", headers=admin).json()
    assert client.post(f"{V}/batches/{bid}/publish", json={"signature": pv["signature"], "confirm": True}, headers=admin).status_code == 200
    rid = _records(client, admin, bid)[0]["id"]
    assert client.patch(f"{V}/records/{rid}", json={"seat": "9", "reason": "attempt on published"}, headers=admin).status_code == 409
    assert client.post(f"{V}/records/{rid}/verification", json={"status": "HALL_LIST_CONFIRMED", "hall_pdf_reference": HALL_PDF,
                       "note": "attempt on published"}, headers=admin).status_code == 409
    assert client.post(f"{V}/records/{rid}/review", json={"decision": "reject", "note": "attempt"}, headers=admin).status_code == 409


@requires_allotments
def test_counts_in_the_importer_rules_match_the_official_dataset():
    """The hard-coded rules must reproduce 627 / 1,159 / 1,520 from the real source file, and nothing else."""
    from collections import Counter
    from datetime import date
    src = oi.DATA_DIR / "source" / "allotments.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    c = Counter()
    for rows in data.values():
        for r in rows:
            y, m, d = map(int, r["exam_date"].split("-"))
            c[oi._verif_status(date(y, m, d), r["session"])] += 1
    assert c == {"FULLY_VERIFIED": 627, "HALL_LIST_CONFIRMED": 1159, "UNRESOLVED": 1520} and sum(c.values()) == 3306


@requires_variant_review
def test_hall_variant_review_counts_are_a_separate_dataset():
    """2,099 hall-label variant records (377 / 772 / 950) are a subset review and must not be confused with the 3,306 total."""
    import csv
    from collections import Counter
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "docs" / "hall_label_variant_review.csv"
    rows = list(csv.DictReader(p.open(encoding="utf-8", newline="")))
    col = "verification_status"
    c = Counter(r[col] for r in rows)
    assert len(rows) == 2099 and c == {"FULLY_VERIFIED": 377, "HALL_LIST_CONFIRMED": 772, "UNRESOLVED": 950}


@requires_corrections
@requires_provenance
def test_hall_correction_is_preserved_as_provenance_and_not_an_official_contradiction(client, admin):
    reg = correction_register("hall")
    prov = oi.load_provenance()
    key = f"{reg}|2026-11-17|AN"
    # the original mirror provenance is untouched ...
    assert prov["records"][key]["hall_pdf_label"] == "MB III 206" and prov["records"][key]["seat_pdf_label"] == "MB III A04"
    # ... and the correction is appended separately, with evidence
    corr = prov["corrections"][key]
    assert (corr["mirror_value"], corr["corrected_value"], corr["corrected_seat"]) == ("MB III 206", "MB III A04", "28")
    assert corr["is_official_contradiction"] is False and corr["correction_type"] == "mirror_transcription_error"
    assert {e["page"] for e in corr["evidence"]} == {4, 20}
    # the staged record carries both, stays FULLY_VERIFIED (17 Nov AN) and is still not approvable until the hall is confirmed
    body = _stage(client, admin, {reg: [_row(reg, "2026-11-17", "AN", hall="MB III A04", seat="28")]})
    rec = _records(client, admin, _batch_id(body, "2026-11-17", "AN"))[0]
    assert rec["provenance_correction"]["corrected_value"] == "MB III A04"
    assert rec["hall_pdf_hall"] == "MB III 206"                                  # original provenance preserved
    assert (rec["hall"], rec["seat"], rec["verification_status"]) == ("MB III A04", "28", "FULLY_VERIFIED")
    assert any("corrects the mirror" in n for n in rec["notes"])


def test_malformed_corrections_file_is_refused(tmp_path):
    import pytest
    main = tmp_path / "allocation_provenance.json"
    main.write_text(json.dumps({"records": {}, "documents": {}}), encoding="utf-8")
    assert "corrections" not in oi.load_provenance(main)
    (tmp_path / "provenance_corrections.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(oi.ImportRefused):
        oi.load_provenance(main)
    (tmp_path / "provenance_corrections.json").write_text(json.dumps({"corrections": []}), encoding="utf-8")
    with pytest.raises(oi.ImportRefused):
        oi.load_provenance(main)


def test_windows_scripts_ship_with_crlf_line_endings():
    """Regression: .bat/.cmd/.ps1 files were LF-only in the release ZIP (.gitattributes only applies to git checkouts).
    cmd.exe can mis-parse goto/call labels in LF-only batch files, so the shipped files must be CRLF."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    bad = []
    for pattern in ("*.bat", "*.cmd", "*.ps1"):
        for p in root.rglob(pattern):
            if any(part in {".venv", "node_modules", "build", ".gradle"} for part in p.parts):
                continue
            data = p.read_bytes()
            if b"\n" in data and data.count(b"\n") != data.count(b"\r\n"):
                bad.append(str(p.relative_to(root)))
    assert not bad, f"LF-only Windows scripts: {bad}"
