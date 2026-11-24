"""Official-source integration: the verified page, link extraction/classification on the REAL link list, host rules."""
from datetime import date

from app import vsb_sources as vs

OFFICIAL = "https://vsbec.edu.in/controller-of-examination/"
BASE = "https://vsbec.edu.in/wp-content/uploads/"
# Link texts and addresses exactly as listed on the official page (checked 15 Nov 2026), plus the other PDF/links found there.
REAL_HTML = f"""
<nav><a href="{BASE}2026/03/IQAC-composition-2025-2026.pdf">IQAC</a><a href="{BASE}2021/10/ARIIA-2021-Report_.pdf">ARIIA</a></nav>
<table><tr>
<td><a href="https://coe.vsbec.edu.in/students/">Results</a></td>
<td><a href="{BASE}2026/10/NOV_DEC_2026-END-SEM-TIME-TABLE-PHASE_1.pdf">End-Semester Examination Timetable</a></td>
<td><a href="{BASE}2026/08/Academic-schedule-for-2026-27-ODD-SEM.pdf">Academic Schedule</a></td></tr>
<tr><td><a href="https://coe.vsbec.edu.in/internals/">COE Staff Login</a></td>
<td><a href="{BASE}2026/10/Anna-University-Malpractice_punishments.pdf">PUNISHMENT FOR MALPRACTICE CASES</a></td></tr>
<tr><td><a href="{BASE}2026/11/14.11.26-FN-HALL.pdf">HALL ALLOTMENT - FN (14.11.2026)</a></td>
<td><a href="{BASE}2026/11/14.11.26-AN-HALL.pdf">HALL ALLOTMENT - AN (14.11.2026)</a></td></tr>
<tr><td><a href="{BASE}2026/11/14.11.26-FN-SEAT.pdf">SEATING ALLOTMENT - FN (14.11.2026)</a></td>
<td><a href="{BASE}2026/11/14.11.26-AN-SEAT.pdf">SEATING ALLOTMENT - AN (14.11.2026)</a></td></tr>
<tr><td><a href="{BASE}2026/11/16.11.26-FN-HALL.pdf">HALL ALLOTMENT - FN (16.11.2026)</a></td>
<td><a href="{BASE}2026/11/16.11.26-AN-SEAT.pdf">SEATING ALLOTMENT - AN (16.11.2026)</a></td></tr></table>
<a href="http://evil.example/x.pdf">offsite</a><a href="https://vsbec.edu.in.evil.example/y.pdf">lookalike</a>
"""


def test_verified_official_sources_are_preserved():
    urls = {s["key"]: s["url"] for s in vs.CONFIRMED_SOURCES}
    assert urls["coe_page"] == OFFICIAL
    assert vs.coe_page_url() == OFFICIAL
    crawl = [s["key"] for s in vs.CONFIRMED_SOURCES if s["crawl"]]
    assert crawl == ["coe_page"]


def test_only_official_https_pdf_links_are_extracted():
    links = vs.extract_pdf_links(REAL_HTML, OFFICIAL)
    urls = [l["url"] for l in links]
    assert all(u.startswith("https://vsbec.edu.in/") and u.endswith(".pdf") for u in urls)
    assert not any("evil" in u or "coe.vsbec" in u for u in urls)
    assert len(urls) == len(set(urls)) == 11


def test_real_allotment_links_are_classified_with_date_and_session():
    got = {l["url"].rsplit("/", 1)[1]: vs.classify(l["url"], l["text"]) for l in vs.extract_pdf_links(REAL_HTML, OFFICIAL)}
    c = got["14.11.26-FN-HALL.pdf"]
    assert (c["doc_kind"], c["exam_date"], c["session"], c["upload_month"]) == ("hall_allotment", date(2026, 11, 14), "FN", "2026-11")
    c = got["14.11.26-AN-SEAT.pdf"]
    assert (c["doc_kind"], c["exam_date"], c["session"]) == ("seating_allotment", date(2026, 11, 14), "AN")
    assert got["16.11.26-FN-HALL.pdf"]["exam_date"] == date(2026, 11, 16)
    assert got["16.11.26-AN-SEAT.pdf"]["doc_kind"] == "seating_allotment"
    assert got["NOV_DEC_2026-END-SEM-TIME-TABLE-PHASE_1.pdf"]["doc_kind"] == "timetable"
    assert got["Anna-University-Malpractice_punishments.pdf"]["doc_kind"] == "notice"
    assert got["Academic-schedule-for-2026-27-ODD-SEM.pdf"]["doc_kind"] == "other"
    assert got["IQAC-composition-2025-2026.pdf"]["doc_kind"] == "other"


def test_file_name_alone_is_enough_when_text_is_empty():
    c = vs.classify(BASE + "2026/11/14.11.26-AN-HALL.pdf", "")
    assert (c["doc_kind"], c["exam_date"], c["session"]) == ("hall_allotment", date(2026, 11, 14), "AN")


def test_new_address_for_same_document_is_a_new_link():
    html = f'<a href="{BASE}2026/11/14.11.26-FN-HALL-REVISED.pdf">HALL ALLOTMENT - FN (14.11.2026) revised</a>'
    l = vs.extract_pdf_links(html, OFFICIAL)[0]
    c = vs.classify(l["url"], l["text"])
    assert c["doc_kind"] == "hall_allotment" and c["session"] == "FN" and l["url"].endswith("REVISED.pdf")


def test_host_rules():
    assert vs.is_allowed_url("https://vsbec.edu.in/a.pdf")
    assert not vs.is_allowed_url("http://vsbec.edu.in/a.pdf")
    assert not vs.is_allowed_url("https://vsbec.edu.in.evil.example/a.pdf")
    assert not vs.is_allowed_url("https://user:pw@vsbec.edu.in/a.pdf")
    # V7: the COE results/notice portal is the second official source the operator asked for; no OTHER subdomain is trusted
    assert vs.is_allowed_url("https://coe.vsbec.edu.in/")
    assert not vs.is_allowed_url("https://evil.vsbec.edu.in/internals/")
    assert not vs.is_allowed_url("https://coe.vsbec.edu.in.evil.example/")


def test_scheduled_polling_is_five_minutes_with_backoff_after_failures_and_startup_scan(db, monkeypatch):
    """V7: default polling is 5 minutes (safe range 5..1440); failures back off 5, 10, 20, 30 (cap) minutes; start-up always scans."""
    from datetime import datetime, timedelta, timezone
    from app import doc_models as dm, vsb_sources as vs
    from app.config import settings
    monkeypatch.setattr(settings, "vsb_auto_discover_enabled", True)
    monkeypatch.setattr(settings, "vsb_poll_seconds", 0)       # 0 = legacy minutes mode, which this test covers
    monkeypatch.setattr(settings, "vsb_poll_minutes", 5)
    assert settings.poll_minutes == 5
    monkeypatch.setattr(settings, "vsb_poll_minutes", 1)
    assert settings.poll_minutes == 5                  # never below the safe minimum
    monkeypatch.setattr(settings, "vsb_poll_minutes", 999999)
    assert settings.poll_minutes == 1440               # never above the safe maximum
    monkeypatch.setattr(settings, "vsb_poll_minutes", 5)
    t0 = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    assert vs.scheduled_due(db, t0)                                           # never run: due
    db.add(dm.VsbCrawlRun(started_at=t0, trigger="scheduler", actor="scheduler", status="ok", page_url="https://vsbec.edu.in/x"))
    db.commit()
    assert not vs.scheduled_due(db, t0 + timedelta(minutes=4)) and vs.scheduled_due(db, t0 + timedelta(minutes=5))
    assert vs.scheduled_due(db, t0 + timedelta(minutes=1), startup=True)       # start-up scan ignores the interval
    monkeypatch.setattr(settings, "vsb_scan_on_startup", False)
    assert not vs.scheduled_due(db, t0 + timedelta(minutes=1), startup=True)
    monkeypatch.setattr(settings, "vsb_scan_on_startup", True)
    # two consecutive failures -> wait 10 minutes; four -> capped at 30
    for i in (1, 2):
        db.add(dm.VsbCrawlRun(started_at=t0 + timedelta(minutes=5 * i), trigger="scheduler", actor="scheduler", status="failed", page_url="x"))
    db.commit()
    last = t0 + timedelta(minutes=10)
    assert not vs.scheduled_due(db, last + timedelta(minutes=9)) and vs.scheduled_due(db, last + timedelta(minutes=10))
    for i in (3, 4, 5):
        db.add(dm.VsbCrawlRun(started_at=t0 + timedelta(minutes=5 * i), trigger="scheduler", actor="scheduler", status="failed", page_url="x"))
    db.commit()
    last = t0 + timedelta(minutes=25)
    assert vs.scheduled_due(db, last + timedelta(minutes=30)) and not vs.scheduled_due(db, last + timedelta(minutes=29))
    # a success resets the wait
    db.add(dm.VsbCrawlRun(started_at=t0 + timedelta(minutes=60), trigger="scheduler", actor="scheduler", status="ok", page_url="x"))
    db.commit()
    assert vs.scheduled_due(db, t0 + timedelta(minutes=65))


def test_scheduled_polling_in_seconds_mode(db, monkeypatch):
    """VSB_POLL_SECONDS (default 60, range 15..300) sets the scan interval; a failed run still backs off."""
    from datetime import datetime, timedelta, timezone
    from app import vsb_sources as vs, doc_models as dm
    from app.config import settings
    monkeypatch.setattr(settings, "vsb_auto_discover_enabled", True)
    monkeypatch.setattr(settings, "vsb_poll_seconds", 60)
    t0 = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    db.add(dm.VsbCrawlRun(started_at=t0, trigger="scheduler", actor="scheduler", status="ok", page_url="x")); db.commit()
    assert not vs.scheduled_due(db, t0 + timedelta(seconds=59)) and vs.scheduled_due(db, t0 + timedelta(seconds=60))
    monkeypatch.setattr(settings, "vsb_poll_seconds", 1)           # clamped up to 15
    assert not vs.scheduled_due(db, t0 + timedelta(seconds=14)) and vs.scheduled_due(db, t0 + timedelta(seconds=15))


def test_official_hall_label_wins_over_seat_word_in_combined_filename():
    url = BASE + "2026/11/24.11.26-FN-HALL-SEAT.pdf"
    c = vs.classify(url, "HALL ALLOTMENT - FN (24.11.2026)")
    assert c["doc_kind"] == "hall_allotment"
    assert c["exam_date"] == date(2026, 11, 24)
    assert c["session"] == "FN"


def test_official_seating_label_wins_over_hall_word_in_filename():
    url = BASE + "2026/11/24.11.26-FN-HALL-SEAT.pdf"
    c = vs.classify(url, "SEATING ALLOTMENT - FN (24.11.2026)")
    assert c["doc_kind"] == "seating_allotment"



def test_existing_filename_only_link_is_reclassified_from_official_listing_and_reparsed(db, monkeypatch):
    """A filename-only first discovery must not permanently misclassify an existing PDF."""
    from app import doc_models as dm
    from app.vsb_live import discovery as disc

    url = BASE + "2026/11/24.11.26-FN-HALL-SEAT.pdf"
    doc = dm.OfficialDocument(
        source_url=url, title="24.11.26 FN HALL SEAT", doc_kind="seating_allotment",
        exam_date=date(2026, 11, 24), session="FN", origin="crawler", status="active",
    )
    db.add(doc)
    db.flush()
    version = dm.DocumentVersion(
        document_id=doc.id, version_no=1, sha256="a" * 64, size_bytes=10,
        storage_path="24.11.26-FN-HALL-SEAT.pdf", is_current=True,
    )
    db.add(version)
    db.flush()
    ingest = dm.LiveIngest(version_id=version.id, status="ok", attempts=1, records=84, pages=14)
    link = dm.VsbSourceLink(
        url=url, title="24.11.26 FN HALL SEAT", doc_kind="seating_allotment",
        exam_date=date(2026, 11, 24), session="FN", upload_month="2026-11",
        listing_url=OFFICIAL, document_id=doc.id, download_status="unchanged",
    )
    db.add_all([ingest, link])
    db.commit()

    col = disc.Collected(
        candidates=[disc.Candidate(url, "HALL ALLOTMENT - FN (24.11.2026)", "html", OFFICIAL)],
        results=[disc.MethodResult("html:" + OFFICIAL, "html", OFFICIAL, ok=True, items=1)],
        pages_read={OFFICIAL},
    )
    monkeypatch.setattr(disc, "collect", lambda http, page_url: col)

    result = vs.run_discovery(db, actor="regression-test", trigger="test", download=False)
    db.refresh(link)
    db.refresh(doc)
    db.refresh(ingest)

    assert result["status"] == "ok"
    assert link.doc_kind == doc.doc_kind == "hall_allotment"
    assert doc.exam_date == date(2026, 11, 24) and doc.session == "FN"
    assert ingest.status == "pending" and ingest.attempts == 0 and ingest.error is None




def test_candidate_merge_prefers_official_html_allotment_label():
    from app.vsb_live.discovery import Candidate

    url = BASE + "2026/11/24.11.26-FN-HALL-SEAT.pdf"
    candidates = [
        Candidate(url, "24.11.26 FN HALL SEAT", "wp_media", "https://vsbec.edu.in/wp-json/wp/v2/media"),
        Candidate(url, "HALL ALLOTMENT - FN (24.11.2026)", "html", OFFICIAL),
    ]
    merged = vs.merge_discovery_candidates(candidates)
    result = merged[url]
    assert result.method == "html"
    assert result.listing_url == OFFICIAL
    assert result.text == "HALL ALLOTMENT - FN (24.11.2026)"
    assert vs.classify(result.url, result.text)["doc_kind"] == "hall_allotment"
