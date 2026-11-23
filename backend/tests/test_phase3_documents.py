"""Phase 3 API: secure upload, processing, review workspace, audit trail and confirmed timetable import."""
import io
from pathlib import Path
import pytest
from sqlalchemy import select
from app import models, doc_models as dm
from app.config import settings
from app.routers.docproc import storage_dir
from conftest import make_student, make_exam
import pdf_factory as pf

B = "/api/admin/doc-processing"


def upload(client, headers, data=None, name="tt.pdf", title="Nov 2026 timetable", **extra):
    data = data if data is not None else pf.table_pdf()
    return client.post(B + "/upload", headers=headers, files={"file": (name, io.BytesIO(data), "application/pdf")},
                       data={"title": title, "doc_kind": "timetable", **extra})


def uploaded(client, headers, **kw):
    r = upload(client, headers, **kw)
    assert r.status_code == 201, r.text
    return r.json()["version_id"]


def processed(client, headers, **kw):
    vid = uploaded(client, headers, **kw)
    r = client.post(f"{B}/{vid}/process", headers=headers)
    assert r.status_code == 200, r.text
    return vid


def catalogue(db):
    for code, name in (("CS3251", "Programming in C"), ("MA3151", "Matrices and Calculus"), ("EC3452", "Electromagnetic Fields")):
        db.add(models.Subject(code=code, name=name, active=True))
    db.commit()


def approve_all(client, admin, vid):
    r = client.post(f"{B}/{vid}/entries/bulk-decision", headers=admin, json={"decision": "approved", "only_confident": False})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ access control
def test_access_control(client, db, staff, admin, student_auth):
    for method, path in (("get", ""), ("get", "/capabilities"), ("get", "/1"), ("get", "/1/download"),
                         ("get", "/1/pages/1/preview"), ("post", "/1/process"), ("post", "/1/import/preview")):
        assert getattr(client, method)(B + path, headers=student_auth).status_code == 403
        assert getattr(client, method)(B + path).status_code == 401
    vid = processed(client, staff)
    eid = client.get(f"{B}/{vid}/review", headers=staff).json()["entries"][0]["id"]
    for method, path, body in (("patch", f"/entries/{eid}", {"subject_name": "x"}), ("post", f"/entries/{eid}/decision", {"decision": "approved"}),
                               ("post", f"/{vid}/decision", {"decision": "approved"}), ("post", f"/{vid}/import", {"confirm": True}),
                               ("patch", f"/{vid}/header", {"exam_name": "x"}), ("post", f"/{vid}/entries", {"subject_code": "AB123"}),
                               ("post", f"/{vid}/entries/bulk-decision", {"decision": "approved"})):
        assert getattr(client, method)(B + path, headers=staff, json=body).status_code == 403, path
    assert client.get(f"{B}/{vid}/review", headers=admin).status_code == 200


# ------------------------------------------------------------------ upload security
def test_upload_validation(client, db, staff):
    assert upload(client, staff, name="x.txt").status_code == 415
    assert upload(client, staff, data=b"not a pdf at all").status_code == 415
    assert upload(client, staff, data=b"%PDF-1.4 garbage").status_code == 422          # damaged
    assert upload(client, staff, title="  ").status_code == 422
    js = pf.table_pdf() + b"\n1 0 obj << /S /JavaScript /JS (app.alert(1)) >> endobj"
    assert upload(client, staff, data=js).status_code == 422
    settings.max_upload_mb = 0
    assert upload(client, staff).status_code == 413
    settings.max_upload_mb = 25
    assert db.scalar(select(dm.OfficialDocument.id)) is None


def test_encrypted_pdf_rejected(client, staff):
    import fitz
    d = fitz.open(); d.new_page()
    enc = d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    assert upload(client, staff, data=enc).status_code == 422


def test_safe_storage_names_and_location(client, db, staff):
    vid = uploaded(client, staff, name="../../etc/passwd<script>.pdf")
    v = db.get(dm.DocumentVersion, vid)
    p = Path(v.storage_path).resolve()
    assert p.parent == storage_dir() and p.name.endswith(".pdf") and len(p.stem) == 32
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    assert static not in p.parents
    info = client.get(f"{B}/{vid}", headers=staff).json()
    assert "/" not in info["original_filename"] and "<" not in info["original_filename"]


def test_duplicate_upload_detected(client, staff):
    data = pf.table_pdf()
    vid = uploaded(client, staff, data=data)
    r = upload(client, staff, data=data, title="again")
    assert r.status_code == 409 and r.json()["detail"]["duplicate"] and r.json()["detail"]["version_id"] == vid
    assert len(client.get(B, headers=staff).json()) == 1


def test_path_traversal_in_stored_path_is_refused(client, db, staff):
    vid = uploaded(client, staff)
    v = db.get(dm.DocumentVersion, vid)
    v.storage_path = "/etc/passwd"; db.commit()
    assert client.get(f"{B}/{vid}/download", headers=staff).status_code == 404
    assert client.post(f"{B}/{vid}/process", headers=staff).status_code == 404


def test_download_preview_and_text(client, staff, db):
    vid = processed(client, staff)
    r = client.get(f"{B}/{vid}/download", headers=staff)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-") and "attachment" in r.headers["content-disposition"]
    assert r.content == pf.table_pdf() or len(r.content) > 500
    p = client.get(f"{B}/{vid}/pages/1/preview", headers=staff)
    assert p.status_code == 200 and p.content[:4] == b"\x89PNG" and "no-store" in p.headers["cache-control"]
    assert client.get(f"{B}/{vid}/pages/9/preview", headers=staff).status_code == 404
    t = client.get(f"{B}/{vid}/pages/1/text", headers=staff).json()
    assert "CS3251" in t["text"] and t["method"] == "text_layer"
    events = [e["event"] for e in client.get(f"{B}/{vid}/history", headers=staff).json()["events"]]
    assert {"uploaded", "processed", "downloaded"} <= set(events)


# ------------------------------------------------------------------ processing
def test_process_and_review_listing(client, staff, db):
    catalogue(db)
    vid = processed(client, staff)
    d = client.get(f"{B}/{vid}/review", headers=staff).json()
    assert d["version"]["processing_status"] == "needs_review"      # inherited date -> needs a human look
    assert [e["subject_code"] for e in d["entries"]] == ["CS3251", "MA3151", "EC3452"]
    assert d["entries"][0]["catalogue_match"]["name"] == "Programming in C"
    assert d["header"]["department"] == "Electronics and Communication Engineering"
    only = client.get(f"{B}/{vid}/review?only_uncertain=true", headers=staff).json()["entries"]
    assert [e["subject_code"] for e in only] == ["MA3151"]


@pytest.mark.skipif(not __import__("app.doc_extract", fromlist=["x"]).ocr_available(), reason="no tesseract")
def test_scanned_document_end_to_end(client, staff, admin):
    vid = processed(client, staff, data=pf.scanned(pf.table_pdf()))
    d = client.get(f"{B}/{vid}/review", headers=staff).json()
    assert d["version"]["ocr_used"] is True and d["version"]["processing_status"] == "needs_review"
    assert any(e["subject_code"] == "CS3251" and e["source"] == "ocr" for e in d["entries"])
    assert client.get(f"{B}/{vid}/pages/1/text", headers=staff).json()["method"] == "ocr"


def test_blank_pdf_processes_with_issue_and_no_entries(client, staff):
    vid = uploaded(client, staff, data=pf.blank_pdf())
    r = client.post(f"{B}/{vid}/process", headers=staff).json()
    assert r["entries"] == 0 and r["issues"] and r["processing_status"] == "needs_review"


def test_reprocess_replaces_machine_output(client, staff):
    vid = processed(client, staff)
    again = client.post(f"{B}/{vid}/process", headers=staff)
    assert again.status_code == 200
    assert len(client.get(f"{B}/{vid}/review", headers=staff).json()["entries"]) == 3


def test_possible_duplicate_content_flagged(client, staff):
    a = processed(client, staff)
    b = processed(client, staff, data=pf.table_pdf() + b"\n% trailing comment makes the bytes differ", title="copy")
    assert any("Possible duplicate" in i for i in client.get(f"{B}/{b}", headers=staff).json()["header"]["issues"])


# ------------------------------------------------------------------ review + audit trail
def test_edit_entry_records_audit_and_resets_approval(client, staff, admin, db):
    vid = processed(client, staff)
    rows = client.get(f"{B}/{vid}/review", headers=admin).json()["entries"]
    e = rows[1]
    client.post(f"{B}/entries/{e['id']}/decision", headers=admin, json={"decision": "approved"})
    r = client.patch(f"{B}/entries/{e['id']}", headers=admin, json={"exam_date": "2027-01-16", "reason": "checked original PDF"})
    assert r.status_code == 200 and r.json()["exam_date"] == "2027-01-16" and r.json()["review_status"] == "pending"
    assert "exam_date" not in r.json()["uncertain_fields"] and r.json()["edited"] is True
    h = client.get(f"{B}/{vid}/history", headers=admin).json()
    assert h["edits"][0]["field"] == "exam_date" and h["edits"][0]["old"] == "2027-01-15" and h["edits"][0]["new"] == "2027-01-16"
    assert h["edits"][0]["by"] == "admin1" and h["edits"][0]["reason"] == "checked original PDF"
    assert db.scalar(select(models.AuditLog.id).where(models.AuditLog.action == "document.entry_edited")) is not None


def test_edit_validation(client, staff, admin):
    vid = processed(client, staff)
    eid = client.get(f"{B}/{vid}/review", headers=admin).json()["entries"][0]["id"]
    for body in ({"start_time": "25:00"}, {"end_time": "09:00"}, {"exam_date": "2027-02-30"}, {"subject_code": "bad code!"},
                 {"subject_id": 9999}, {"year": 9}):
        assert client.patch(f"{B}/entries/{eid}", headers=admin, json=body).status_code == 422, body
    assert client.patch(f"{B}/entries/99999", headers=admin, json={"subject_name": "x"}).status_code == 404


def test_cannot_approve_incomplete_row_and_document_needs_all_rows_decided(client, staff, admin):
    vid = processed(client, staff, data=pf.text_pdf())
    rows = client.get(f"{B}/{vid}/review", headers=admin).json()["entries"]
    bad = next(r for r in rows if not r["subject_code"])
    r = client.post(f"{B}/entries/{bad['id']}/decision", headers=admin, json={"decision": "approved"})
    assert r.status_code == 422 and "subject code" in r.json()["detail"]
    assert client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"}).status_code == 409   # pending rows
    bulk = client.post(f"{B}/{vid}/entries/bulk-decision", headers=admin, json={"decision": "approved"}).json()
    assert bad["id"] in bulk["skipped_ids"]
    client.post(f"{B}/entries/{bad['id']}/decision", headers=admin, json={"decision": "rejected"})
    uncertain = [r["id"] for r in client.get(f"{B}/{vid}/review?status=pending", headers=admin).json()["entries"]]
    for i in uncertain:
        client.post(f"{B}/entries/{i}/decision", headers=admin, json={"decision": "approved"})
    assert client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"}).status_code == 200


def test_manual_entry_and_header_edit(client, staff, admin):
    vid = processed(client, staff)
    r = client.post(f"{B}/{vid}/entries", headers=admin, json={"subject_code": "ph3151", "subject_name": "Physics",
                    "exam_date": "2027-01-20", "start_time": "09:30", "end_time": "12:30"})
    assert r.status_code == 201 and r.json()["subject_code"] == "PH3151" and r.json()["source"] == "manual"
    h = client.patch(f"{B}/{vid}/header", headers=admin, json={"exam_name": "Corrected Exam Title", "reason": "typo"}).json()
    assert h["exam_name"] == "Corrected Exam Title"
    edits = client.get(f"{B}/{vid}/history", headers=admin).json()["edits"]
    assert {e["field"] for e in edits} >= {"exam_name", "(row added)"}


def test_reject_document(client, staff, admin):
    vid = processed(client, staff)
    approve_all(client, admin, vid)
    r = client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "rejected", "note": "wrong semester"})
    assert r.status_code == 200 and r.json()["review_status"] == "rejected"
    assert client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": "x"}).status_code == 409


# ------------------------------------------------------------------ import
def ready(client, db, staff, admin, **kw):
    catalogue(db)
    vid = processed(client, staff, **kw)
    approve_all(client, admin, vid)
    # inherited-date row needs approval too (only_confident False above approved all complete rows)
    assert client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"}).status_code == 200
    return vid


def test_import_preview_then_confirmed_import(client, db, staff, admin):
    make_student(db, "990025106001", dept="Electronics and Communication", year=2)
    vid = ready(client, db, staff, admin)
    before = db.query(models.Exam).count()
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    assert pv["will_create"] == 3 and pv["blocked"] == 0 and db.query(models.Exam).count() == before   # preview writes nothing
    assert client.post(f"{B}/{vid}/import", headers=admin, json={"signature": pv["signature"]}).status_code == 422   # needs confirm
    r = client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv["signature"]})
    assert r.status_code == 200, r.text
    exams = db.query(models.Exam).order_by(models.Exam.exam_date, models.Exam.start_time).all()
    assert len(exams) == 3 and all(e.status == "draft" and e.subject_id for e in exams)
    assert [(e.subject_code, e.exam_date, e.start_time, e.end_time) for e in exams][0] == ("CS3251", "2027-01-15", "09:30", "12:30")
    assert exams[0].duration_minutes == 180
    assert db.query(models.AuditLog).filter_by(action="exam.imported_from_document").count() == 3
    d = client.get(f"{B}/{vid}", headers=staff).json()
    assert d["imported_at"] and d["entry_counts"] == {"imported": 3}
    # import is not repeatable and processing is blocked afterwards
    assert client.post(f"{B}/{vid}/process", headers=staff).status_code == 409
    again = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    assert again["will_create"] == 0


def test_import_requires_fresh_signature_and_approval(client, db, staff, admin):
    catalogue(db)
    vid = processed(client, staff)
    approve_all(client, admin, vid)
    assert client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": "x"}).status_code == 409  # not approved
    client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"})
    assert client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": "stale"}).status_code == 409
    assert db.query(models.Exam).count() == 0


def test_signature_goes_stale_when_exams_change(client, db, staff, admin):
    vid = ready(client, db, staff, admin)
    sig = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()["signature"]
    make_exam(db, code="ZZ999", date="2027-03-01")
    r = client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": sig})
    assert r.status_code == 409 and "changed" in r.json()["detail"]


def test_unmapped_subject_blocks_unless_creation_allowed(client, db, staff, admin):
    db.add(models.Subject(code="CS3251", name="Programming in C", active=True)); db.commit()   # others missing
    vid = processed(client, staff)
    approve_all(client, admin, vid)
    client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"})
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    blocked = [i for i in pv["items"] if i["action"] == "blocked"]
    assert len(blocked) == 2 and "not in the catalogue" in blocked[0]["errors"][0]
    r = client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv["signature"]})
    assert r.status_code == 409 and len(r.json()["detail"]["blocked"]) == 2
    pv2 = client.post(f"{B}/{vid}/import/preview", headers=staff, json={"create_missing_subjects": True}).json()
    assert pv2["will_create"] == 3
    ok = client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv2["signature"], "create_missing_subjects": True})
    assert ok.status_code == 200
    assert db.query(models.Subject).count() == 3 and db.query(models.Exam).count() == 3


def test_manual_subject_mapping_resolves_blocked_row(client, db, staff, admin):
    db.add(models.Subject(code="CS3251", name="Programming in C", active=True))
    sub = models.Subject(code="MA3151X", name="Matrices and Calculus", active=True); db.add(sub); db.commit()
    vid = processed(client, staff, data=pf.table_pdf(rows=[["Date", "Session", "Subject Code", "Subject Name"],
                    ["15/01/2027", "FN 09:30 AM - 12:30 PM", "MA3151", "Matrices and Calculus"]]))
    eid = client.get(f"{B}/{vid}/review", headers=admin).json()["entries"][0]["id"]
    client.patch(f"{B}/entries/{eid}", headers=admin, json={"subject_id": sub.id, "reason": "catalogue uses X suffix"})
    client.post(f"{B}/entries/{eid}/decision", headers=admin, json={"decision": "approved"})
    client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"})
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    assert pv["items"][0]["action"] == "create" and pv["items"][0]["subject"]["code"] == "MA3151X"


def test_ocr_confusable_code_gets_suggestion(client, db, staff, admin):
    db.add(models.Subject(code="CS3251", name="Programming in C", active=True)); db.commit()
    vid = processed(client, staff, data=pf.table_pdf(rows=[["Date", "Session", "Subject Code", "Subject Name"],
                    ["15/01/2027", "FN 09:30 AM - 12:30 PM", "CS3Z51", "Programming in C"]]))
    e = client.get(f"{B}/{vid}/review", headers=admin).json()["entries"][0]
    client.post(f"{B}/entries/{e['id']}/decision", headers=admin, json={"decision": "approved"})
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    assert pv["items"][0]["action"] == "blocked" and "CS3251" in pv["items"][0]["suggestions"]


def test_duplicates_existing_and_reschedule_need_explicit_choice(client, db, staff, admin):
    catalogue(db)
    cs = db.query(models.Subject).filter_by(code="CS3251").one()
    same = models.Exam(title="Existing CS", subject_code="CS3251", subject_id=cs.id, exam_date="2027-01-15",
                       start_time="09:30", end_time="12:30", venue="V", status="published")
    ma = db.query(models.Subject).filter_by(code="MA3151").one()
    moved = models.Exam(title="Existing MA", subject_code="MA3151", subject_id=ma.id, exam_date="2027-01-15",
                        start_time="10:00", end_time="13:00", venue="V2", status="published")
    db.add_all([same, moved]); db.commit()
    vid = processed(client, staff); approve_all(client, admin, vid)
    client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"})
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    acts = {i["subject_code"]: i["action"] for i in pv["items"]}
    assert acts["CS3251"] == "skip_existing" and acts["MA3151"] == "conflict_existing" and acts["EC3452"] == "create"
    rows = client.get(f"{B}/{vid}/review", headers=admin).json()["entries"]
    ma_id = next(r["id"] for r in rows if r["subject_code"] == "MA3151")
    # without opt-in the conflicting row blocks the import
    assert client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv["signature"]}).status_code == 409
    pv2 = client.post(f"{B}/{vid}/import/preview", headers=staff, json={"update_existing_entry_ids": [ma_id]}).json()
    assert {i["subject_code"]: i["action"] for i in pv2["items"]}["MA3151"] == "update_existing"
    r = client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv2["signature"], "update_existing_entry_ids": [ma_id]})
    assert r.status_code == 200 and r.json()["updated_exam_ids"] == [moved.id]
    db.expire_all()
    assert db.get(models.Exam, moved.id).start_time == "13:30" and db.get(models.Exam, moved.id).venue == "V2"
    assert db.get(models.Exam, same.id).title == "Existing CS" and db.get(models.Exam, same.id).status == "published"
    assert db.query(models.Exam).count() == 3        # only EC3452 added
    assert db.query(models.AuditLog).filter_by(action="exam.updated_from_document").count() == 1


def test_conflicts_inside_document_and_with_existing_exams(client, db, staff, admin):
    catalogue(db)
    make_student(db, "990025106001", dept="Electronics and Communication Engineering", year=2)
    rows = [["Date", "Session", "Subject Code", "Subject Name", "Department", "Year"],
            ["15/01/2027", "FN 09:30 AM - 12:30 PM", "CS3251", "Programming in C", "Electronics and Communication Engineering", "2"],
            ["15/01/2027", "FN 10:00 AM - 01:00 PM", "MA3151", "Matrices and Calculus", "Electronics and Communication Engineering", "2"],
            ["15/01/2027", "FN 10:00 AM - 01:00 PM", "EC3452", "Electromagnetic Fields", "Electronics and Communication Engineering", "3"]]
    ec = db.query(models.Subject).filter_by(code="EC3452").one()
    other = models.Exam(title="Other", subject_code="XY1000", exam_date="2027-01-15", start_time="09:00", end_time="11:00", venue="Z", status="draft")
    db.add(other); db.flush()
    db.add(models.ExamEligibilityRule(exam_id=other.id, department="Electronics and Communication Engineering", year=3)); db.commit()
    vid = processed(client, staff, data=pf.table_pdf(rows=rows))
    approve_all(client, admin, vid)
    client.post(f"{B}/{vid}/decision", headers=admin, json={"decision": "approved"})
    items = {i["subject_code"]: i for i in client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()["items"]}
    assert items["CS3251"]["action"] == "create"
    assert items["MA3151"]["action"] == "blocked" and "overlaps row 1" in items["MA3151"]["errors"][0]       # same dept+year clash
    assert items["EC3452"]["action"] == "blocked" and "overlaps examination" in items["EC3452"]["errors"][0]    # clash with existing audience
    assert all(i["errors"] for i in items.values() if i["action"] == "blocked")


def test_audience_rule_created_only_for_known_department(client, db, staff, admin):
    make_student(db, "990025106001", dept="Electronics and Communication Engineering", year=2)
    vid = ready(client, db, staff, admin)
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv["signature"]})
    assert db.query(models.ExamEligibilityRule).filter_by(department="Electronics and Communication Engineering").count() == 3


def test_unknown_department_warns_and_creates_no_rule(client, db, staff, admin):
    vid = ready(client, db, staff, admin)          # no students at all
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={}).json()
    assert any("no audience rule" in w for w in pv["items"][0]["warnings"])
    client.post(f"{B}/{vid}/import", headers=admin, json={"confirm": True, "signature": pv["signature"]})
    assert db.query(models.ExamEligibilityRule).count() == 0


def test_term_window_enforced(client, db, staff, admin):
    from datetime import date
    y = models.AcademicYear(label="2026-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31), is_current=True)
    db.add(y); db.flush()
    t = models.ExamTerm(academic_year_id=y.id, name="Nov", start_date=date(2027, 1, 16), end_date=date(2027, 1, 31)); db.add(t); db.commit()
    vid = ready(client, db, staff, admin)
    pv = client.post(f"{B}/{vid}/import/preview", headers=staff, json={"term_id": t.id}).json()
    acts = {i["subject_code"]: i["action"] for i in pv["items"]}
    assert acts["CS3251"] == "blocked" and acts["EC3452"] == "create"


def test_phase1_document_endpoints_still_work(client, staff):
    assert client.get("/api/admin/documents", headers=staff).status_code == 200


def test_static_workspace_present(client):
    html = client.get("/").text
    assert "/js/pages-docs.js" in html
    assert client.get("/js/pages-docs.js").status_code == 200 and 'name: "documents"' in client.get("/js/pages-docs.js").text
