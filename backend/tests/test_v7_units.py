"""V7 unit tests: pure helpers (no network, no PDFs) and failure conditions of the public API."""
from datetime import date

import pytest
from sqlalchemy.exc import OperationalError

from app import doc_models as dm
from app.regno import normalize_register_number
from app.vsb_live import discovery, locations, notify, pipeline


@pytest.mark.parametrize("raw,expected", [("922523105015", "922523105015"), (" 9225 2310 5015 ", "922523105015"), ("9225-2310-5015", "922523105015"),
                                          ("922523105015\t", "922523105015"), ("abc123def", "ABC123DEF")])
def test_register_number_normalisation(raw, expected):
    assert normalize_register_number(raw) == expected


@pytest.mark.parametrize("bad", ["", "12", "9225231050151234567890123", "9225$231050", "<script>", "9225 2310 \u0661\u0662", "a" * 40])
def test_register_number_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        normalize_register_number(bad)


def test_weekday_is_calculated_not_read_from_the_pdf():
    assert pipeline.weekday_name(date(2026, 11, 20)) == "Friday"
    assert pipeline.weekday_name(date(2028, 2, 29)) == "Tuesday"
    assert pipeline.weekday_name(date(2026, 11, 22)) == "Sunday"


@pytest.mark.parametrize("label,expected", [("BE-CIVIL", ("BE", "CIVIL")), ("B.E. - ECE", ("BE", "ECE")), ("B.TECH - IT", ("BTECH", "IT")),
                                            ("ME-VLSI", ("ME", "VLSI")), ("MBA", ("MBA", None)), ("Civil", (None, "Civil")), ("", (None, None)), (None, (None, None))])
def test_programme_and_department_split(label, expected):
    assert pipeline.split_programme(label) == expected


def test_classification_matrix_never_upgrades_uncertain_records():
    c = lambda flags, **k: pipeline.classify(flags, hall_doc_present=True, seat_doc_present=True, **{"has_hall": True, "has_seat": True, **k})  # noqa: E731
    assert c([]) == "CONFIRMED" and c(["department_inferred"]) == "CONFIRMED"
    assert c(["hall_mismatch"]) == "CONFLICT" and c(["conflicting_seats"]) == "CONFLICT" and c(["source_documents_disagree"]) == "CONFLICT"
    assert c(["ocr_text"]) == "MANUAL_REVIEW" and c(["seat_from_text_order"]) == "MANUAL_REVIEW"
    assert c(["missing_in_seating_pdf"], has_seat=False) == "HALL_ONLY"
    assert c(["missing_in_hall_pdf"], has_hall=False) == "SEAT_ONLY"
    assert c(["hall_mismatch", "ocr_text"]) == "CONFLICT"                     # the stronger statement wins
    assert c([], has_hall=False, has_seat=False) == "MANUAL_REVIEW"


def test_fingerprint_changes_with_any_published_fact_and_is_order_independent():
    a = {"reg": "1", "hall": "MB III 02", "seat": "2", "d": "2026-11-20"}
    assert pipeline.fingerprint_of(a) == pipeline.fingerprint_of(dict(reversed(list(a.items()))))
    for k, v in (("hall", "MB III 03"), ("seat", "3"), ("d", "2026-11-21")):
        assert pipeline.fingerprint_of({**a, k: v}) != pipeline.fingerprint_of(a)


def test_material_change_rules():
    old = dm.LiveAllotment(subject_code="X", hall="MB III 02", seat="2")
    row = lambda **k: {"subject_code": "X", "hall": "MB III 02", "seat": "2", "status": "CONFIRMED", **k}  # noqa: E731
    assert not pipeline.is_material_change(dm.LiveAllotment(subject_code="X", hall="MB III 02", seat=None), row())     # seat added
    assert pipeline.is_material_change(old, row(hall="MB III 09")) and pipeline.is_material_change(old, row(seat="5"))
    assert pipeline.is_material_change(old, row(subject_code="Y"))
    assert not pipeline.is_material_change(old, row(hall=None, seat=None, status="CONFLICT"))        # flagged, not silently "revised"


def test_embedded_pdf_extraction_and_host_filtering():
    html = ('<iframe src="/wp-content/uploads/a.pdf"></iframe><embed src="https://vsbec.edu.in/b.pdf">'
            '<object data="https://evil.example/c.pdf"></object>'
            '<iframe src="/pdfjs/viewer.html?file=https%3A%2F%2Fvsbec.edu.in%2Fd.pdf"></iframe><iframe src="/page.html"></iframe>')
    urls = {i["url"] for i in discovery.extract_embedded_pdf_links(html, "https://vsbec.edu.in/controller-of-examination/")}
    assert urls == {"https://vsbec.edu.in/wp-content/uploads/a.pdf", "https://vsbec.edu.in/b.pdf", "https://vsbec.edu.in/d.pdf"}


def test_sitemap_parsing_is_safe():
    urls, kids = discovery._loc_values(b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://vsbec.edu.in/x.pdf</loc></url></urlset>')
    assert urls == ["https://vsbec.edu.in/x.pdf"] and kids == []
    urls, kids = discovery._loc_values(b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://vsbec.edu.in/s1.xml</loc></sitemap></sitemapindex>')
    assert urls == [] and kids == ["https://vsbec.edu.in/s1.xml"]
    with pytest.raises(Exception):
        discovery._loc_values(b"<not xml")
    with pytest.raises(Exception):                               # entity expansion / external entities are not honoured
        discovery._loc_values(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><urlset><url><loc>&a;</loc></url></urlset>')


def test_coordinate_and_email_validation():
    assert locations.valid_coord(10.9, 78.0) and not locations.valid_coord(None, 78) and not locations.valid_coord(91, 0) and not locations.valid_coord(float("nan"), 1)
    assert notify.valid_email("a.b@example.org") and not notify.valid_email("a@b") and not notify.valid_email("a b@c.org") and not notify.valid_email("a@b.org\nBcc: x@y.z")


def test_public_api_degrades_gracefully_when_the_database_is_unavailable(client, monkeypatch):
    from app.routers import public_live

    def broken(db, reg):
        raise OperationalError("SELECT 1", {}, Exception("database is locked"))
    monkeypatch.setattr(public_live, "lookup", broken)
    r = client.get("/api/public/lookup/922523105015")
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    assert "temporarily unavailable" in r.json()["detail"]
    assert "OperationalError" not in r.text and "database is locked" not in r.text and "Traceback" not in r.text   # no internals leaked
