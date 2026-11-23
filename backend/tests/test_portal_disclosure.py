"""Regression tests: an unauthenticated visitor must learn nothing about UNPUBLISHED allotments.

Before this fix, GET /api/portal/lookup/{register} returned `pending_unpublished` (the exact number of unpublished classic
allotments for that register) and the portal displayed "Seat allotted, not yet published". Both disclosed that an
allotment existed before publication. Published results must keep working.
"""
from datetime import date, timedelta

from app import models
from conftest import REG1, REG2, make_exam, make_student

FUTURE = (date.today() + timedelta(days=400)).isoformat()


def _seat(db, student, exam, hall="HALL-SECRET", n="6"):
    db.add(models.Allotment(student_id=student.id, exam_id=exam.id, hall=hall, seat=n))
    db.commit()


def test_unpublished_allotment_is_not_disclosed(client, db):
    s = make_student(db, REG1)
    _seat(db, s, make_exam(db, "draft", "Secret Exam Title", "SECRETCODE", FUTURE))
    r = client.get(f"/api/portal/lookup/{REG1}")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == []
    assert "pending_unpublished" not in body                  # no count of unpublished allotments
    for leaked in ("Secret Exam Title", "SECRETCODE", "HALL-SECRET", "awaiting publication"):
        assert leaked not in r.text, leaked


def test_student_with_only_unpublished_allotments_looks_like_one_with_none(client, db):
    s1 = make_student(db, REG1)
    make_student(db, REG2)
    _seat(db, s1, make_exam(db, "draft", "Draft", "D1", FUTURE))
    a = client.get(f"/api/portal/lookup/{REG1}").json()
    b = client.get(f"/api/portal/lookup/{REG2}").json()
    # apart from the student's own identity block, the two responses must be identical
    strip = lambda d: {k: v for k, v in d.items() if k != "student"}
    assert strip(a) == strip(b)


def test_seat_map_refuses_an_unpublished_allotment_exactly_like_a_missing_one(client, db):
    s = make_student(db, REG1)
    draft = make_exam(db, "draft", "Draft", "D1", FUTURE)
    _seat(db, s, draft)
    unpublished = client.get(f"/api/portal/seatmap/{REG1}", params={"kind": "allotment", "ref": draft.id})
    missing = client.get(f"/api/portal/seatmap/{REG1}", params={"kind": "allotment", "ref": 999999})
    assert unpublished.status_code == missing.status_code == 404
    assert unpublished.json() == missing.json()


def test_published_results_still_show_for_the_student(client, db):
    s = make_student(db, REG1)
    pub = make_exam(db, "published", "Published Exam", "P1", FUTURE)
    _seat(db, s, pub, hall="HALL-A", n="5")
    d = client.get(f"/api/portal/lookup/{REG1}").json()
    assert [e["exam"] for e in d["entries"]] == ["Published Exam"]
    assert (d["entries"][0]["hall"], d["entries"][0]["seat"]) == ("HALL-A", "5")
    assert "pending_unpublished" not in d


def test_unknown_register_still_gets_404_and_invalid_still_422(client, db):
    make_student(db, REG1)
    assert client.get(f"/api/portal/lookup/{REG2}").status_code == 404
    assert client.get("/api/portal/lookup/!!").status_code == 422


def test_public_seat_map_never_reveals_another_students_register_number(client, db):
    """Two students share a published hall. The seat map for one of them must not contain the other's register number."""
    s1 = make_student(db, REG1)
    s2 = make_student(db, REG2)
    pub = make_exam(db, "published", "Shared Hall Exam", "SH1", FUTURE)
    _seat(db, s1, pub, hall="HALL-SHARED", n="5")
    _seat(db, s2, pub, hall="HALL-SHARED", n="6")
    r = client.get(f"/api/portal/seatmap/{REG1}", params={"kind": "allotment", "ref": pub.id})
    assert r.status_code == 200
    assert REG2 not in r.text                                 # the other student's register number is never returned
    body = r.json()
    assert body["your_seat"] == "5"                           # the requester's own seat is shown
    assert [x for x in body["seats"] if x["l"] == "5"][0]["s"] == "yours"   # and it is highlighted


def test_public_responses_never_carry_seating_chart_references(client, db):
    s = make_student(db, REG1)
    pub = make_exam(db, "published", "Pub", "P1", FUTURE)
    _seat(db, s, pub, hall="HALL-A", n="5")
    for text in (client.get(f"/api/portal/lookup/{REG1}").text,
                 client.get(f"/api/portal/seatmap/{REG1}", params={"kind": "allotment", "ref": pub.id}).text):
        for forbidden in ("seating_chart", "seating_image", ".png", "/data/", "vsb-allocation/charts"):
            assert forbidden not in text, forbidden
