"""Runs the importer on the REAL original allotments.json (the operator's copy under backend/data/original_portal, or ORIGINAL_ALLOTMENTS_JSON).

    pytest tests/test_original_import_real_data.py          (needs the operator's copy; or set ORIGINAL_ALLOTMENTS_JSON; skipped otherwise)
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from conftest import make_student
from test_original_import import SRC_URL, IMPORT
from operator_data import correction_register, source_register

# Defaults to the operator's copy (backend/data/original_portal/source/allotments.json). Not in the public package.
SRC = os.environ.get("ORIGINAL_ALLOTMENTS_JSON") or str(Path(__file__).resolve().parents[1] / "data" / "original_portal" / "source" / "allotments.json")
pytestmark = pytest.mark.skipif(not Path(SRC).is_file(), reason="operator-supplied original allotments.json not present (not in the public package)")
# The sample student is looked up in the operator's own file (never written into source code).
SAMPLE_REG = source_register(exam_date="2026-11-17", session="AN", hall_number="MB III A103", seat_number="23",
                             subject_code="23ECT307") if Path(SRC).is_file() else None


def test_real_original_allotments(client, admin, db):
    raw = Path(SRC).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    upload = lambda dry, confirm: client.post(f"{IMPORT}?dry_run={str(dry).lower()}&confirm={str(confirm).lower()}",
                                              files={"file": ("allotments.json", raw, "application/json")}, headers=admin)
    dry = upload(True, False).json()
    assert dry["rows_read"] == 3306 and dry["registers"] == 2934 and dry["rows_rejected"] == 0
    assert dry["conflicts_total"] == 0 and dry["duplicate_seats"] == 0

    make_student(db, SAMPLE_REG, "Sample Student", "ECE", 2)   # the only student row this test creates
    applied = upload(False, True)
    assert applied.status_code == 200, applied.text
    rep = applied.json()
    assert rep["file_sha256"] == sha and rep["records_to_stage"] == 3306 and len(rep["batches"]) == 6
    flagged = sum(s["flagged"] for s in rep["sessions"])

    bid = next(b["id"] for b in rep["batches"] if b["exam_date"] == "2026-11-17" and b["session"] == "AN")
    rec = next(r for r in client.get(f"/api/vsb-allocation/batches/{bid}/records", params={"limit": 1000}, headers=admin)
               .json()["records"] if r["register_number"] == SAMPLE_REG)
    expected = {"exam_date": "2026-11-17", "session": "AN", "hall": "MB III A103", "seat": "23", "subject_code": "23ECT307",
                "subject_title": "DIGITAL ELECTRONICS", "seat_page": 23, "seating_chart": "d12cded03485_17.11.26-AN-seat_page_23.png"}
    got = {"exam_date": rec["exam_date"], "session": rec["session"], "hall": rec["hall"], "seat": rec["seat"],
           "subject_code": rec["subject_code"], "subject_title": rec["subject_title"], "seat_page": rec["seat_page"],
           "seating_chart": rec["seating_chart"]}
    assert got == expected
    assert rec["review_status"] == "pending" and rec["published"] is False

    # Approve only after the administrator has checked the chart; then publish; then the student can see the seat.
    assert client.post(f"/api/vsb-allocation/records/{rec['id']}/review", json={"decision": "approve", "note": "Checked hall and seat against seat-sheet p.23", "acknowledge": True}, headers=admin).status_code == 200
    p = client.post(f"/api/vsb-allocation/batches/{bid}/publish/preview", headers=admin).json()
    pub = client.post(f"/api/vsb-allocation/batches/{bid}/publish", json={"signature": p["signature"], "confirm": True,
                      "acknowledge_open_issues": p["open_error_issues"] > 0}, headers=admin)
    assert pub.status_code == 200, pub.text
    look = client.get(f"/api/portal/lookup/{SAMPLE_REG}").json()
    entry = next(e for e in look["entries"] if e["kind"] == "vsb" and e["date"] == "2026-11-17")
    assert (entry["session"], entry["hall"], entry["seat"], entry["subject_code"]) == ("AN", "MB III A103", "23", "23ECT307")
    assert entry["source"]["url"] == SRC_URL

    out = os.environ.get("ORIGINAL_REPORT_OUT")
    if out:
        Path(out).write_text(json.dumps({"dry_run": {k: v for k, v in dry.items() if k not in ("rejected", "conflicts")},
                                         "applied_sessions": rep["sessions"], "flagged_records": flagged,
                                         "sample_record": rec, "sample_portal_entry": entry}, indent=2, default=str))


def test_every_staged_record_matches_the_source_field_by_field(client, admin, db):
    """Strongest data check: all 3,306 original rows are compared with the mirror's JSON and with its own database."""
    from sqlalchemy import select
    from app import doc_models as dm
    from app.vsb_alloc import original_import as oi
    from app.vsb_alloc.common import norm_hall
    raw = Path(SRC).read_bytes()
    payload = json.loads(raw)
    r = client.post(f"{IMPORT}?dry_run=false&confirm=true", files={"file": ("allotments.json", raw, "application/json")}, headers=admin)
    assert r.status_code == 200, r.text
    stored = db.execute(select(dm.VsbAllocRecord, dm.VsbAllocBatch).join(
        dm.VsbAllocBatch, dm.VsbAllocBatch.id == dm.VsbAllocRecord.batch_id)).all()
    assert len(stored) == 3306
    by_key = {(rec.register_number, b.exam_date.isoformat(), b.session): (rec, b) for rec, b in stored}
    assert len(by_key) == 3306                                              # no duplicate or lost rows
    prov = oi.load_provenance()["records"]
    hall_conflicts = 0
    for reg, items in payload.items():
        for it in items:
            key = (reg, it["exam_date"], it["session"])
            rec, _ = by_key[key]
            assert rec.register_number == reg
            assert rec.hall == norm_hall(it["hall_number"])
            assert rec.seat == str(it["seat_number"])
            assert rec.subject_code == it["subject_code"]
            assert rec.subject_title == ((it.get("subject_name") or "").strip()[:300] or None)
            detail = json.loads(rec.detail)
            assert detail["source_url"] == it["source_url"] and detail["json_page"] == it["page"]
            assert detail["seating_chart"] == it["seating_image"].rsplit("/", 1)[-1]
            p = prov["|".join(key)]
            assert detail["hall_pdf_page"] == p["hall_pdf_page"] and detail["seat_pdf_page"] == p["seat_pdf_page"]
            assert detail["hall_pdf_hall"] == p["hall_pdf_label"] and detail["seat_pdf_hall"] == p["seat_pdf_label"]
            flags = json.loads(rec.flags)
            if "hall_mismatch" in flags:
                hall_conflicts += 1
                assert reg == correction_register("hall")
            assert "provenance_mismatch" not in flags                       # every upload row agrees with the mirror database
            assert rec.review_status == "pending" and rec.published is False  # nothing approved or published by the import
    assert hall_conflicts == 1                                               # the one known hall disagreement is caught
