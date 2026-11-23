"""Original sabareesh2008 portal data -> VSB review workflow.

Uses a synthetic sample row (register 992696352326, 17 Nov 2026, AN, MB III A103, seat 23) plus synthetic rows that
exercise each safeguard. Nothing here is published unless the test explicitly approves and publishes it.
"""
import hashlib
import json

import pytest
from sqlalchemy import func, select

from app import doc_models as dm, models
from app.vsb_alloc import original_import as oi
from conftest import make_student
from operator_data import correction_register, requires_chart, requires_provenance, source_register

SAMPLE_REG = "992696352326"
SRC_URL = "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-seat.pdf"
CHART = "d12cded03485_17.11.26-AN-seat_page_23.png"
IMPORT = "/api/vsb-allocation/import/original"


def row(reg, hall="MB III A103", seat="23", date="2026-11-17", sess="AN", code="23ECT307",
        name="DIGITAL ELECTRONICS", page=4, img=f"evidence/{CHART}", url=SRC_URL):
    return {"register_number": reg, "exam_date": date, "session": sess, "hall_number": hall, "seat_number": seat,
            "subject_code": code, "subject_name": name, "page": page, "source_url": url, "seating_image": img}


def upload(client, headers, payload, dry_run=True, confirm=False):
    raw = json.dumps(payload).encode()
    q = f"?dry_run={'true' if dry_run else 'false'}&confirm={'true' if confirm else 'false'}"
    r = client.post(IMPORT + q, files={"file": ("allotments.json", raw, "application/json")}, headers=headers)
    return r, hashlib.sha256(raw).hexdigest()


def write(client, headers, payload):
    r, sha = upload(client, headers, payload, dry_run=False, confirm=True)
    assert r.status_code == 200, r.text
    return r.json(), sha


def recs(client, headers, bid):
    return client.get(f"/api/vsb-allocation/batches/{bid}/records", params={"limit": 1000}, headers=headers).json()["records"]


def sample_payload(reg=SAMPLE_REG):
    return {reg: [row(reg)], "992696352301": [row("992696352301", hall="MB III 103", seat="1")]}


def test_dry_run_is_the_default_and_writes_nothing(client, admin, db):
    r, _ = upload(client, admin, sample_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True and body["records_to_stage"] == 2
    assert db.scalar(select(dm.VsbAllocBatch.id).limit(1)) is None


def test_writing_requires_explicit_confirmation(client, admin):
    r, _ = upload(client, admin, sample_payload(), dry_run=False, confirm=False)
    assert r.status_code == 422


def test_only_administrators_can_import(client, staff, student_auth):
    for h in (staff, student_auth):
        r, _ = upload(client, h, sample_payload())
        assert r.status_code in (401, 403)


def test_rejects_malformed_file_and_rows(client, admin):
    r = client.post(IMPORT, files={"file": ("x.json", b"[1,2]", "application/json")}, headers=admin)
    assert r.status_code == 422
    bad = {
        "9225251063": [row("9225251063")],                                       # not 12 digits
        SAMPLE_REG: [row(SAMPLE_REG, sess="XX")],                                # bad session
        "992696352302": [row("992696352302", date="2026-13-40")],               # bad date
        "992696352303": [row("992696352303", url="http://vsbec.edu.in/x.pdf")], # not https
        "992696352304": [row("992696352305")],                                   # key mismatch
    }
    body, _ = write(client, admin, bad)
    reasons = {x["reason"] for x in body["rejected"]}
    assert {"register_not_12_digits", "session_invalid", "date_invalid", "source_url_invalid", "register_key_mismatch"} <= reasons
    assert body["records_to_stage"] == 0 and body["batches"] == []


def test_identical_repeats_merge_and_conflicts_are_not_staged(client, admin):
    conflicting = row("992696352310", hall="MB III A104", seat="5")
    payload = {SAMPLE_REG: [row(SAMPLE_REG), row(SAMPLE_REG)],
               "992696352310": [row("992696352310"), conflicting]}
    body, _ = write(client, admin, payload)
    assert body["identical_duplicates_merged"] == 1
    assert body["conflicts_total"] == 1 and body["conflicts"][0]["register_number"] == "992696352310"
    staged = {x["register_number"] for x in recs(client, admin, body["batches"][0]["id"])}
    assert staged == {SAMPLE_REG}  # the conflicting register is not staged at all


@requires_provenance
def test_provenance_and_flags_for_the_sample_record(client, admin, db):
    reg = source_register(exam_date="2026-11-17", session="AN", hall_number="MB III A103", seat_number="23", subject_code="23ECT307")
    body, sha = write(client, admin, sample_payload(reg))
    bid = next(b["id"] for b in body["batches"] if b["session"] == "AN")
    rec = next(r for r in recs(client, admin, bid) if r["register_number"] == reg)
    assert (rec["hall"], rec["seat"], rec["subject_code"], rec["subject_title"]) == ("MB III A103", "23", "23ECT307", "DIGITAL ELECTRONICS")
    assert rec["review_status"] == "pending" and rec["published"] is False and rec["seat_page"] == 23
    assert rec["seating_chart"] == CHART
    # the hall list and the seat sheet both place the sample in MB III A103 (from the mirror's database)
    assert rec["hall_pdf_hall"] == "MB III A103" and rec["seat_pdf_hall"] == "MB III A103"
    assert rec["hall_page"] == 4 and rec["seat_page"] == 23
    assert "hall_label_variant" in rec["flags"] and "student_not_in_database" in rec["flags"]
    assert "hall_mismatch" not in rec["flags"] and "provenance_mismatch" not in rec["flags"]
    assert rec["blocking"] is True
    stored = db.scalar(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.register_number == reg))
    d = json.loads(stored.detail)
    assert d["source_url"] == SRC_URL and d["json_page"] == 4 and d["file_sha256"] == sha
    assert d["hall_pdf_page"] == 4 and d["seat_pdf_page"] == 23
    assert d["hall_pdf_url"].endswith("/17.11.26-AN-hall.pdf") and d["seat_pdf_url"] == SRC_URL
    assert len(d["hall_pdf_sha256"]) == 64 and len(d["seat_pdf_sha256"]) == 64
    assert any("hall-list page" in n and "seat-sheet page is 23" in n for n in d["notes"])
    batch = db.get(dm.VsbAllocBatch, bid)
    assert batch.status == "draft" and batch.parser_version == oi.PARSER_VERSION
    assert json.loads(batch.summary)["primary_source"]["url"] == SRC_URL


def test_duplicate_seat_is_flagged_and_blocks_approval(client, admin):
    payload = {SAMPLE_REG: [row(SAMPLE_REG, seat="23")], "992696352320": [row("992696352320", seat="23")]}
    body, _ = write(client, admin, payload)
    bid = body["batches"][0]["id"]
    rid = next(r["id"] for r in recs(client, admin, bid) if r["register_number"] == SAMPLE_REG)
    assert "duplicate_seat" in next(r for r in recs(client, admin, bid) if r["id"] == rid)["flags"]
    url = f"/api/vsb-allocation/records/{rid}/review"
    assert client.post(url, json={"decision": "approve", "note": "checked PDF"}, headers=admin).status_code == 422
    assert client.post(url, json={"decision": "approve", "note": "checked PDF", "acknowledge": True}, headers=admin).status_code == 422
    # correcting the seat unlocks approval (the admin records the correction and the reason)
    fix = client.patch(f"/api/vsb-allocation/records/{rid}", json={"seat": "24", "reason": "seat confirmed on chart p.23"}, headers=admin)
    assert fix.status_code == 200, fix.text
    verify = client.post(f"/api/vsb-allocation/records/{rid}/verification", json={
        "status": "FULLY_VERIFIED",
        "hall_pdf_reference": "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-hall.pdf",
        "seat_pdf_reference": "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-seat.pdf",
        "note": "Corrected seat checked against official hall list and seat sheet."}, headers=admin)
    assert verify.status_code == 200, verify.text
    assert client.post(url, json={"decision": "approve", "note": "seat corrected and checked"}, headers=admin).status_code == 200


def test_reimport_replaces_unreviewed_draft_but_never_reviewed_decisions(client, admin, db):
    body, _ = write(client, admin, sample_payload())
    bid = next(b["id"] for b in body["batches"] if b["session"] == "AN")
    body2, _ = write(client, admin, sample_payload())
    assert any(s["session"] == "AN" and s["skipped_reason"] is None for s in body2["sessions"])
    rid = next(r["id"] for r in recs(client, admin, bid) if r["register_number"] == SAMPLE_REG)
    assert client.post(f"/api/vsb-allocation/records/{rid}/review", json={"decision": "approve", "note": "PDF checked", "acknowledge": True}, headers=admin).status_code == 200
    body3, _ = write(client, admin, sample_payload())
    an = next(s for s in body3["sessions"] if s["session"] == "AN")
    assert an["skipped_reason"] and "reviewed" in an["skipped_reason"]
    kept = db.scalar(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.register_number == SAMPLE_REG, dm.VsbAllocRecord.batch_id == bid))
    assert kept is not None and kept.review_status == "approved"


def test_import_never_touches_a_published_batch(client, admin, db):
    write(client, admin, sample_payload())
    make_student(db, SAMPLE_REG, "Sample Student", "ECE", 2)
    body2, _ = write(client, admin, sample_payload())  # re-link student on the new draft
    bid2 = next(b["id"] for b in body2["batches"] if b["session"] == "AN")
    rid = next(r["id"] for r in recs(client, admin, bid2) if r["register_number"] == SAMPLE_REG)
    assert client.post(f"/api/vsb-allocation/records/{rid}/review", json={"decision": "approve", "note": "PDF checked", "acknowledge": True}, headers=admin).status_code == 200
    _publish(client, admin, bid2)
    body3, _ = write(client, admin, sample_payload())
    assert db.get(dm.VsbAllocBatch, bid2).status == "published"
    assert any(s["session"] == "AN" and s["skipped_reason"] is None for s in body3["sessions"])


def _publish(client, headers, bid):
    p = client.post(f"/api/vsb-allocation/batches/{bid}/publish/preview", headers=headers).json()
    r = client.post(f"/api/vsb-allocation/batches/{bid}/publish", json={"signature": p["signature"], "confirm": True,
                    "acknowledge_open_issues": p["open_error_issues"] > 0}, headers=headers)
    assert r.status_code == 200, r.text


def test_student_sees_the_sample_seat_only_after_approval_and_publication(client, admin, db):
    make_student(db, SAMPLE_REG, "Sample Student", "ECE", 2)
    body, _ = write(client, admin, sample_payload())
    bid = next(b["id"] for b in body["batches"] if b["session"] == "AN")
    url = f"/api/portal/lookup/{SAMPLE_REG}"
    before = client.get(url).json()
    assert all(e["kind"] != "vsb" for e in before["entries"])
    rid = next(r["id"] for r in recs(client, admin, bid) if r["register_number"] == SAMPLE_REG)
    assert client.post(f"/api/vsb-allocation/records/{rid}/review", json={"decision": "approve", "note": "Checked against seat chart p.23", "acknowledge": True}, headers=admin).status_code == 200
    _publish(client, admin, bid)
    after = client.get(url).json()
    entry = next(e for e in after["entries"] if e["kind"] == "vsb")
    assert (entry["date"], entry["session"], entry["hall"], entry["seat"], entry["subject_code"]) == \
        ("2026-11-17", "AN", "MB III A103", "23", "23ECT307")
    assert entry["source"]["url"] == SRC_URL
    assert "992696352301" not in json.dumps(after)  # other students' rows never leak


@requires_chart(CHART)
def test_seating_chart_is_administrator_only(client, admin, staff, student_auth):
    ok = client.get(f"/api/vsb-allocation/charts/{CHART}", headers=admin)
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert ok.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/vsb-allocation/charts/{CHART}", headers=staff).status_code == 403
    assert client.get(f"/api/vsb-allocation/charts/{CHART}", headers=student_auth).status_code == 403
    for bad in ("..%2Fconftest.py", "d12cded03485_17.11.26-AN-seat_page_999.png", "nope.png"):
        assert client.get(f"/api/vsb-allocation/charts/{bad}", headers=admin).status_code == 404




@requires_provenance
def test_hall_conflict_between_the_two_pdfs_blocks_approval(client, admin):
    reg = correction_register("hall")
    # the uploaded row matches the mirror's seat sheet; the hall list disagrees, so the record must be blocked
    body, _ = write(client, admin, {reg: [row(reg, hall="MB III A04", seat="28", date="2026-11-17",
                                                             sess="AN", page=4, img="evidence/d12cded03485_17.11.26-AN-seat_page_20.png")]})
    bid = body["batches"][0]["id"]
    rec = recs(client, admin, bid)[0]
    assert "hall_mismatch" in rec["flags"] and rec["blocking"] is True
    assert rec["hall_pdf_hall"] == "MB III 206" and rec["seat_pdf_hall"] == "MB III A04"
    url = f"/api/vsb-allocation/records/{rec['id']}/review"
    assert client.post(url, json={"decision": "approve", "note": "checked", "acknowledge": True}, headers=admin).status_code == 422
    assert any(i["kind"] == "hall_mismatch" for i in client.get(f"/api/vsb-allocation/batches/{bid}/issues", params={"status": "open"}, headers=admin).json())
    # after the administrator corrects the hall (recorded with a reason) the record can be approved with a note
    fix = client.patch(f"/api/vsb-allocation/records/{rec['id']}", json={"hall": "MB III A04", "reason": "hall confirmed on seat sheet p.20"}, headers=admin)
    assert fix.status_code == 200, fix.text
    # a critical correction withdraws verification, and the hall conflict itself needs an explicit, evidenced resolution
    assert client.post(url, json={"decision": "approve", "note": "hall verified against both PDFs"}, headers=admin).status_code == 422
    pdf = "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-seat.pdf"
    assert client.post(f"/api/vsb-allocation/records/{rec['id']}/verification", json={
        "status": "FULLY_VERIFIED", "hall_pdf_reference": pdf, "seat_pdf_reference": pdf, "note": "both PDFs re-checked"}, headers=admin).status_code == 200
    assert client.post(url, json={"decision": "approve", "note": "hall verified against both PDFs"}, headers=admin).status_code == 422
    assert client.post(f"/api/vsb-allocation/records/{rec['id']}/resolve-conflict", json={
        "flag": "hall_mismatch", "pdf_reference": pdf, "note": "seat sheet p.20 prints MB III A04"}, headers=admin).status_code == 200
    assert client.post(url, json={"decision": "approve", "note": "hall verified against both PDFs"}, headers=admin).status_code == 200


@requires_provenance
def test_uploaded_row_that_differs_from_the_mirror_database_is_flagged(client, admin):
    reg = source_register(exam_date="2026-11-17", session="AN", hall_number="MB III A103", seat_number="23", subject_code="23ECT307")
    body, _ = write(client, admin, {reg: [row(reg, seat="24")]})   # mirror says seat 23
    rec = recs(client, admin, body["batches"][0]["id"])[0]
    assert "provenance_mismatch" in rec["flags"] and rec["blocking"] is True


def test_malformed_provenance_file_is_refused_not_ignored(tmp_path):
    assert oi.load_provenance(tmp_path / "missing.json") is None
    bad = tmp_path / "p.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(oi.ImportRefused):
        oi.load_provenance(bad)
    bad.write_text(json.dumps({"records": []}), encoding="utf-8")
    with pytest.raises(oi.ImportRefused):
        oi.load_provenance(bad)


def test_deeply_nested_upload_is_a_clean_422(client, admin):
    raw = b"[" * 100000 + b"]" * 100000
    r = client.post(IMPORT, files={"file": ("x.json", raw, "application/json")}, headers=admin)
    assert r.status_code == 422


def test_import_is_audited_and_creates_no_students(client, admin, db):
    before = db.scalar(select(func.count()).select_from(models.Student))
    body, sha = write(client, admin, sample_payload())
    assert db.scalar(select(func.count()).select_from(models.Student)) == before   # no fabricated student rows
    entry = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "vsb_alloc.original_imported"))
    assert entry is not None and sha in (entry.details or "")


def test_source_data_and_charts_are_never_served_as_static_files(client):
    """The static site serves only app/static. The mirror's source JSON, provenance and charts must not be reachable."""
    for path in ("/data/original_portal/source/allotments.json",
                 "/data/original_portal/allocation_provenance.json",
                 f"/data/original_portal/seating_charts/{CHART}"):
        assert client.get(path).status_code == 404, path


def test_a_correction_cannot_create_a_seat_collision_that_is_then_approved(client, admin):
    """Regression: an edit that moves a record onto a seat another register already holds must not be approvable.
    Before the fix, the stored flags were never recomputed after an edit, and an edited record skipped the hard-conflict rule."""
    body, _ = write(client, admin, sample_payload())
    bid = next(b["id"] for b in body["batches"] if b["session"] == "AN")
    other = next(r for r in recs(client, admin, bid) if r["register_number"] == "992696352301")
    fix = client.patch(f"/api/vsb-allocation/records/{other['id']}",
                       json={"hall": "MB III A103", "seat": "23", "reason": "moved to the sample's seat (test)"}, headers=admin)
    assert fix.status_code == 200, fix.text
    url = f"/api/vsb-allocation/records/{other['id']}/review"
    r = client.post(url, json={"decision": "approve", "note": "checked", "acknowledge": True}, headers=admin)
    assert r.status_code == 422, r.text                       # the seat is already held by SAMPLE_REG in this batch
    # both sides of the clash are marked so the reviewer sees it in the list
    flags_by_reg = {x["register_number"]: x["flags"] for x in recs(client, admin, bid)}
    assert "duplicate_seat" in flags_by_reg["992696352301"] and "duplicate_seat" in flags_by_reg[SAMPLE_REG]
