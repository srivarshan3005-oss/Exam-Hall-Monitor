"""Official V.S.B. Engineering College source integration.

Rules this module enforces
* Only URLs that appear on an official page (or that an administrator already stored) are ever requested.
  Nothing is guessed, constructed from a file-name pattern, or taken from a third-party site.
* Hosts are allow-listed (vsbec.edu.in); every request and every redirect must be https on an allowed host.
* robots.txt is read and obeyed; requests are spaced out and identify this application.
* A failure (offline, 404, 5xx, robots, bad PDF) is recorded against the link and never deletes anything.
  If the listing page itself cannot be read, no link is marked as "no longer listed".
* Downloaded PDFs become ordinary OfficialDocument / DocumentVersion rows (origin "crawler"), so the existing
  PDF/OCR review (Timetable PDFs) and seating-import workflow works on them unchanged.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
import uuid
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import doc_models as dm
from .config import settings

log = logging.getLogger("exam_monitor.vsb")

ALLOWED_HOSTS = frozenset({"vsbec.edu.in", "www.vsbec.edu.in", "coe.vsbec.edu.in"})
SOURCE_LABEL = "V.S.B. Engineering College – Controller of Examinations"
USER_AGENT = "ExamMonitorUltimate/0.8 (student-convenience tool; polite, robots.txt-aware)"
# Kinds that are downloaded automatically. Every other PDF on the page is listed but only downloaded on request.
AUTO_KINDS = ("hall_allotment", "seating_allotment", "timetable", "notice")
OK_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream",
                              "application/force-download", "application/download"})

# Pages confirmed as official. `confirmed` records how: they are linked from the college's own Controller of
# Examinations page (live check on 15 Nov 2026). Nothing else is presented as an official source.
CONFIRMED_SOURCES = [
    {"key": "college_home", "title": "V.S.B. Engineering College – official website", "url": "https://vsbec.edu.in/",
     "purpose": "College home page", "crawl": False,
     "confirmed": "Canonical address of the college site (og:url / site home link on the official COE page)."},
    {"key": "coe_page", "title": "Controller of Examinations – notices, timetable, hall & seating allotments",
     "url": "https://vsbec.edu.in/controller-of-examination/", "purpose": "Examination notices and PDFs", "crawl": True,
     "confirmed": "Official page listing End-Semester timetable, hall allotment and seating allotment PDFs (live check 15 Nov 2026)."},
    {"key": "coe_results", "title": "Results portal (linked from the official COE page)", "url": "https://coe.vsbec.edu.in/students/",
     "purpose": "Published results", "crawl": False,
     "confirmed": "Linked as 'Results' on the official COE page. Opened in a new tab only; this application does not crawl it."},
    {"key": "downloads", "title": "College downloads page", "url": "https://vsbec.edu.in/downloads/",
     "purpose": "General college downloads", "crawl": False,
     "confirmed": "Linked as 'Downloads' in the footer of the official COE page. Reference link only; not crawled."},
]

_run_lock = threading.Lock()


# ----------------------------------------------------------------------------- pure helpers
def now() -> datetime:
    return datetime.now(timezone.utc)


def is_allowed_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in ALLOWED_HOSTS and not u.username and not u.password


def coe_page_url() -> str:
    """The configured listing page, but only if it is on an allowed host (never an arbitrary URL)."""
    u = (settings.vsb_coe_page_url or "").strip()
    return u if is_allowed_url(u) else CONFIRMED_SOURCES[1]["url"]


class _LinkParser(HTMLParser):
    """Extract link labels plus nearby cell/list context from official notice pages."""
    _CONTAINERS = {"td", "th", "li", "p", "div", "tr", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._attrs: list[str] = []
        self._text: list[str] = []
        self._containers: list[dict] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in self._CONTAINERS:
            self._containers.append({"tag": tag, "text": [], "links": []})
        if tag == "a":
            self._href = values.get("href")
            self._attrs = [values.get("title", ""), values.get("aria-label", "")]
            self._text = []
            self._active_container = self._containers[-1] if self._containers else None

    def handle_data(self, data):
        if not data:
            return
        for container in self._containers:
            container["text"].append(data)
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            label = " ".join(" ".join(self._attrs + [" ".join(self._text)]).split())
            record = {"href": self._href, "label": label, "context": ""}
            self.links.append(record)
            if self._active_container is not None:
                self._active_container["links"].append(record)
            self._href = None
            self._attrs, self._text = [], []
            self._active_container = None
        if tag in self._CONTAINERS:
            # HTML is often imperfect; close the most recent matching container.
            for i in range(len(self._containers) - 1, -1, -1):
                if self._containers[i]["tag"] == tag:
                    container = self._containers.pop(i)
                    context = " ".join(" ".join(container["text"]).split())
                    for link in container["links"]:
                        link["context"] = context
                    break



def extract_pdf_links(html: str, base_url: str) -> list[dict]:
    """PDF links found on an official page: [{url, text}], absolute, fragment-free, de-duplicated, allow-listed."""
    p = _LinkParser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - malformed HTML must not abort a run
        pass
    out, seen = [], set()
    for item in p.links:
        href = item["href"]
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urldefrag(urljoin(base_url, href.strip()))[0]
        if not urlparse(url).path.lower().endswith(".pdf") or not is_allowed_url(url) or url in seen:
            continue
        seen.add(url)
        # Anchor labels can simply say "PDF" while the official allotment title is
        # printed beside it in the same table cell/list item. Preserve that context.
        text = " ".join(dict.fromkeys(x for x in (item["label"], item["context"]) if x))
        out.append({"url": url[:1000], "text": text[:500]})
    return out


_DATE_TEXT = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
_DATE_FILE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{2})(?!\d)")
_SESSION = re.compile(r"(?<![A-Za-z])(FN|AN)(?![A-Za-z])", re.I)
_UPLOAD_MONTH = re.compile(r"/wp-content/uploads/(\d{4})/(\d{2})/")


def _mk_date(d: str, m: str, y: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def classify(url: str, text: str) -> dict:
    """Kind / exam date / session / upload month, using ONLY what the link text and file name actually state."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    label = (text or "").upper().replace("_", " ")
    hay = f"{text} {name}".upper().replace("_", " ")
    # Prefer the official listing label over filename keywords. Some VSB hall PDFs
    # are named like 24.11.26-FN-HALL-SEAT.pdf; "SEAT" in that filename must not
    # override the explicit "HALL ALLOTMENT" label on the official COE page.
    if "SEATING ALLOTMENT" in label:
        kind = "seating_allotment"
    elif "HALL ALLOTMENT" in label:
        kind = "hall_allotment"
    elif "SEATING ALLOTMENT" in hay or re.search(r"[-. ]SEAT(\\b|[-. ])", hay):
        kind = "seating_allotment"
    elif "HALL ALLOTMENT" in hay or "HALL SEATING" in hay or re.search(r"[-. ]HALL(\\b|[-. ])", hay):
        kind = "hall_allotment"
    elif "TIME TABLE" in hay or "TIMETABLE" in hay or "TIME-TABLE" in hay:
        kind = "timetable"
    elif any(k in hay for k in ("NOTICE", "CIRCULAR", "MALPRACTICE")):
        kind = "notice"
    else:
        kind = "other"
    exam_date = None
    m = _DATE_TEXT.search(text or "")
    if m:
        exam_date = _mk_date(*m.groups())
    if exam_date is None:
        m = _DATE_FILE.match(name)           # e.g. 14.11.26-FN-HALL.pdf  (date at the start of the file name)
        if m:
            exam_date = _mk_date(m.group(1), m.group(2), "20" + m.group(3))
    s = _SESSION.search(text or "") or _SESSION.search(name)
    um = _UPLOAD_MONTH.search(url)
    return {"doc_kind": kind, "exam_date": exam_date, "session": s.group(1).upper() if s else None,
            "upload_month": f"{um.group(1)}-{um.group(2)}" if um else None}


def title_for(url: str, text: str) -> str:
    t = (text or "").strip()
    if not t:
        t = urlparse(url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
    return t[:300] or "Untitled PDF"


def parse_http_date(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = parsedate_to_datetime(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- network layer
class FetchError(Exception):
    def __init__(self, outcome: str, message: str, status: int | None = None):
        super().__init__(message)
        self.outcome, self.status = outcome, status      # outcome: unavailable | failed | blocked


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_url(urljoin(req.full_url, newurl)):
            raise FetchError("blocked", "Redirected outside the official college host; refused")
        return super().redirect_request(req, fp, code, msg, headers, urljoin(req.full_url, newurl))


class _Http:
    """Polite client: allow-listed hosts only, robots.txt, spacing, timeouts, bounded retries."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_SafeRedirect())
        self._robots_by_host: dict[str, tuple[str, urllib.robotparser.RobotFileParser | None]] = {}   # host -> (state, parser)
        self._last = 0.0

    def _wait(self) -> None:
        gap = max(0.0, float(settings.vsb_request_delay_seconds))
        left = self._last + gap - time.monotonic()
        if left > 0:
            time.sleep(left)
        self._last = time.monotonic()

    def _raw(self, url: str, headers: dict | None = None, limit: int | None = None):
        if not is_allowed_url(url):
            raise FetchError("blocked", "URL is not an https address on the official college host")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})})
        self._wait()
        with self._opener.open(req, timeout=max(3, settings.vsb_http_timeout_seconds)) as r:
            body = r.read(limit + 1) if limit else r.read()
            if limit and len(body) > limit:
                raise FetchError("blocked", f"File is larger than the {settings.max_upload_mb} MB limit")
            return r.status, dict(r.headers.items()), body

    def _load_robots(self, url: str) -> tuple[str, urllib.robotparser.RobotFileParser | None]:
        host = (urlparse(url).hostname or "").lower()
        if host in self._robots_by_host:
            return self._robots_by_host[host]
        root = f"{urlparse(url).scheme}://{urlparse(url).netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        try:
            _, _, body = self._raw(root, limit=512 * 1024)
            rp.parse(body.decode("utf-8", "replace").splitlines())
            entry = ("ok", rp)
        except urllib.error.HTTPError as e:
            entry = ("missing", None) if e.code in (404, 410) else ("unreadable", None)     # no robots.txt = no restrictions published
        except Exception:  # noqa: BLE001
            entry = ("unreadable", None)
        if entry[0] != "unreadable":                  # an unreadable robots.txt is re-checked on the next request
            self._robots_by_host[host] = entry
        return entry

    def permitted(self, url: str) -> None:
        state, rp = self._load_robots(url)
        if state == "unreadable":
            raise FetchError("failed", "robots.txt could not be read right now; not fetching until it can be checked")
        if state == "ok" and rp and not rp.can_fetch(USER_AGENT, url):
            raise FetchError("blocked", "The site's robots.txt does not permit automatic access to this URL")

    def get(self, url: str, headers: dict | None = None, limit: int | None = None):
        """Returns (status, headers, body). 304 is returned as (304, headers, b'') for conditional requests."""
        self.permitted(url)
        attempts = max(0, settings.vsb_max_retries) + 1
        last: FetchError | None = None
        for i in range(attempts):
            try:
                return self._raw(url, headers, limit)
            except FetchError:
                raise
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return 304, dict(e.headers.items()), b""
                if e.code in (404, 410):
                    raise FetchError("unavailable", f"The official site returned HTTP {e.code} (file not found or removed)", e.code)
                if e.code in (401, 403):
                    raise FetchError("blocked", f"The official site refused access (HTTP {e.code})", e.code)
                last = FetchError("failed", f"The official site returned HTTP {e.code}", e.code)
                if e.code < 500 and e.code != 429:
                    raise last
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                reason = getattr(e, "reason", e)
                last = FetchError("failed", f"Network problem: {str(reason)[:200]}")
            if i < attempts - 1:
                time.sleep(min(8, 2 ** i))
        raise last or FetchError("failed", "Unknown network failure")


# ----------------------------------------------------------------------------- PDF intake (shared with the upload workflow)
def validate_pdf(data: bytes) -> int:
    """Same safety rules as a manual upload. Returns the page count or raises FetchError('blocked')."""
    from .routers import docproc
    from . import doc_extract as dx
    if not data:
        raise FetchError("failed", "The official site returned an empty response (0 bytes); nothing was stored")
    if not data.startswith(b"%PDF-"):
        raise FetchError("blocked", "The response was not a PDF (the address may now serve a web page)")
    if docproc._ACTIVE_CONTENT.search(data):
        raise FetchError("blocked", "PDF contains JavaScript or launch actions; rejected for safety")
    try:
        import fitz
        probe = fitz.open(stream=data, filetype="pdf")
        pages, locked = len(probe), probe.needs_pass or probe.is_encrypted
        probe.close()
    except Exception:  # noqa: BLE001
        raise FetchError("blocked", "The PDF is damaged or unreadable")
    if locked:
        raise FetchError("blocked", "Encrypted or password-protected PDFs are not supported")
    if not 1 <= pages <= dx.MAX_PAGES:
        raise FetchError("blocked", f"PDF must have 1–{dx.MAX_PAGES} pages")
    return pages


def _latest_version(db: Session, document_id: int) -> dm.DocumentVersion | None:
    return db.scalar(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == document_id)
                     .order_by(dm.DocumentVersion.version_no.desc()).limit(1))


def ingest(db: Session, link: dm.VsbSourceLink, status: int, headers: dict, data: bytes, actor: str) -> tuple[str, dm.DocumentVersion | None]:
    """Store downloaded bytes. Returns (outcome, version) with outcome downloaded | unchanged | duplicate."""
    from .routers import docproc
    pages = validate_pdf(data)
    digest = hashlib.sha256(data).hexdigest()
    h = {k.lower(): v for k, v in headers.items()}
    link.published_at = parse_http_date(h.get("last-modified")) or link.published_at
    same = db.scalar(select(dm.DocumentVersion).where(dm.DocumentVersion.sha256 == digest).limit(1))
    if same:
        if link.document_id and same.document_id == link.document_id:
            if not same.is_current:
                # the official file went back to content we already stored: make that version current again, keep history
                for other in db.scalars(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == same.document_id)).all():
                    other.is_current = other.id == same.id
                link.note = f"Content returned to stored version {same.version_no}."[:500]
            return "unchanged", same
        link.document_id = same.document_id
        link.note = f"Identical file already stored as document #{same.document_id}; not stored again."[:500]
        return "duplicate", same
    doc = db.get(dm.OfficialDocument, link.document_id) if link.document_id else None
    if doc is None:
        doc = db.scalar(select(dm.OfficialDocument).where(dm.OfficialDocument.source_url == link.url))
    path = docproc.storage_dir() / (uuid.uuid4().hex + ".pdf")
    path.write_bytes(data)
    try:
        import os
        os.chmod(path, 0o600)
    except OSError:
        pass
    if doc is None:
        doc = dm.OfficialDocument(source_url=link.url, listing_url=link.listing_url, title=link.title, doc_kind=link.doc_kind,
                                  exam_date=link.exam_date, session=link.session, published_at=link.published_at,
                                  origin="crawler", source_label=SOURCE_LABEL, uploaded_by=actor[:80],
                                  original_filename=docproc.safe_display_name(urlparse(link.url).path.rsplit("/", 1)[-1]))
        db.add(doc)
        db.flush()
    nxt = (db.scalar(select(func.max(dm.DocumentVersion.version_no)).where(dm.DocumentVersion.document_id == doc.id)) or 0) + 1
    for old in db.scalars(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == doc.id)).all():
        old.is_current = False
    v = dm.DocumentVersion(document_id=doc.id, version_no=nxt, sha256=digest, size_bytes=len(data), page_count=pages,
                           storage_path=str(path), http_etag=(h.get("etag") or "")[:200] or None,
                           http_last_modified=(h.get("last-modified") or "")[:100] or None, is_current=True,
                           processing_status="pending")
    db.add(v)
    doc.status, doc.last_checked_at, doc.published_at = "active", now(), link.published_at or doc.published_at
    db.flush()
    docproc.event(db, v.id, "downloaded" if nxt == 1 else "downloaded_new_version", actor,
                  {"url": link.url, "bytes": len(data), "pages": pages, "version": nxt, "source": "official college site"})
    link.document_id = doc.id
    link.last_downloaded_at = now()
    link.note = (f"Content at this URL changed; stored as version {nxt}." if nxt > 1 else None)
    return "downloaded", v


# ----------------------------------------------------------------------------- link bookkeeping
def _mark(link: dm.VsbSourceLink, status: str, http: int | None = None, error: str | None = None) -> None:
    link.download_status, link.last_http_status, link.last_attempt_at = status, http, now()
    link.last_error = (error or None) and error[:500]
    link.failure_count = (link.failure_count or 0) + 1 if status in ("failed", "unavailable") else 0


def download_link(db: Session, http: _Http, link: dm.VsbSourceLink, actor: str) -> tuple[str, dm.DocumentVersion | None]:
    """Fetch one stored link. Never raises for expected problems; records them on the link instead."""
    cond: dict = {}
    if link.document_id:
        last = _latest_version(db, link.document_id)
        if last and last.http_etag:
            cond["If-None-Match"] = last.http_etag
        elif last and last.http_last_modified:
            cond["If-Modified-Since"] = last.http_last_modified
    try:
        status, headers, body = http.get(link.url, cond, limit=settings.vsb_max_download_mb * 1024 * 1024)
        if status == 304:
            _mark(link, "unchanged", 304)
            return "unchanged", None
        ctype = {k.lower(): v for k, v in headers.items()}.get("content-type", "").split(";")[0].strip().lower()
        if ctype and ctype not in OK_CONTENT_TYPES:
            raise FetchError("blocked", f"Unexpected content type '{ctype[:60]}' (expected a PDF)", status)
        outcome, v = ingest(db, link, status, headers, body, actor)
        _mark(link, outcome, status)
        return outcome, v
    except FetchError as e:
        db.rollback()
        link = db.get(dm.VsbSourceLink, link.id)
        _mark(link, e.outcome, e.status, str(e))
        if e.outcome == "unavailable" and link.document_id:
            link.note = "The file is no longer served at this address; the stored copy and its history were kept."
        return e.outcome, None
    except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
        log.exception("VSB download failed for %s", link.url)
        db.rollback()
        link = db.get(dm.VsbSourceLink, link.id)
        _mark(link, "failed", None, f"Unexpected error: {type(e).__name__}")
        return "failed", None


def _note_replacements(db: Session) -> None:
    """Same kind/date/session reachable under a new URL while the old one is gone: say so, change nothing else."""
    rows = db.scalars(select(dm.VsbSourceLink).where(dm.VsbSourceLink.exam_date.is_not(None))).all()
    groups: dict[tuple, list[dm.VsbSourceLink]] = {}
    for r in rows:
        if r.doc_kind in AUTO_KINDS:
            groups.setdefault((r.doc_kind, r.exam_date, r.session), []).append(r)
    for items in groups.values():
        live = [i for i in items if i.still_listed]
        gone = [i for i in items if not i.still_listed]
        if len(live) > 1:
            # two different live addresses claim the same type/date/session (e.g. a corrected PDF added beside the old one)
            for l in live:
                other = next(o for o in live if o.id != l.id)
                if not l.note or l.note.startswith("Another link"):
                    l.note = f"Another link for the same type/date/session is also listed (link #{other.id}); choose the correct PDF when building the batch."[:500]
        if live and gone:
            for g in gone:
                if not g.note or g.note.startswith("Possibly"):
                    g.note = f"Possibly replaced by a newer address on the official page (link #{live[0].id})."[:500]


def merge_discovery_candidates(candidates):
    """Merge duplicate URLs while retaining the strongest official listing label."""
    merged = {}
    for candidate in candidates:
        current = merged.get(candidate.url)
        if current is None:
            merged[candidate.url] = candidate
            continue
        label = (candidate.text or "").upper().replace("_", " ")
        has_official_kind = "HALL ALLOTMENT" in label or "SEATING ALLOTMENT" in label
        if candidate.method == "html" and candidate.text and (current.method != "html" or has_official_kind):
            current.text = candidate.text
            current.method = candidate.method
            current.listing_url = candidate.listing_url
        elif not current.text and candidate.text:
            current.text = candidate.text
            current.method = candidate.method
            current.listing_url = candidate.listing_url
    return merged


# ----------------------------------------------------------------------------- discovery run
def run_discovery(db: Session, *, actor: str, trigger: str = "manual", download: bool = True,
                  auto_process=None) -> dict:
    """Read the official COE page, record every PDF link, download the relevant new/changed ones.
    `auto_process(db, version) -> str|None` is called for newly stored versions (manual runs only)."""
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("busy")
    run = dm.VsbCrawlRun(trigger=trigger, actor=actor[:80], status="running", page_url=coe_page_url())
    db.add(run)
    db.commit()
    notes: list[str] = []
    try:
        http = _Http()
        from .vsb_live import discovery as disc
        col = disc.collect(http, run.page_url)
        disc.record_health(db, col.results)
        if not col.any_ok:
            why = "; ".join(f"{r.method} ({r.url.split('//')[-1][:60]}): {r.error}" for r in col.results if r.error)[:900]
            run.status, run.finished_at = "failed", now()
            run.message = (f"Could not read the official page: {why or 'no discovery method succeeded'}. "
                           "Existing links, documents and history were left untouched.")
            db.commit()
            return run_dict(run)
        failed_methods = [r for r in col.results if not r.ok and not r.skipped and r.method == "html"]
        if failed_methods:
            notes.append("Some listing pages could not be read this time: " + "; ".join(f"{r.url} ({r.error})" for r in failed_methods)[:600])
        merged = merge_discovery_candidates(col.candidates)
        found = [{"url": c.url, "text": c.text, "listing": c.listing_url} for c in merged.values()]
        run.links_found = len(found)
        if not found:
            notes.append("The sources were read but no PDF links were found; existing links were not marked as removed "
                         "(the page layout may have changed).")
        seen_urls = set()
        for item in found:
            url, text, listing = item["url"], item["text"], item["listing"]
            seen_urls.add(url)
            meta = classify(url, text)
            link = db.scalar(select(dm.VsbSourceLink).where(dm.VsbSourceLink.url == url))
            if link is None:
                link = dm.VsbSourceLink(url=url, title=title_for(url, text), listing_url=listing, **meta,
                                        download_status="discovered" if meta["doc_kind"] in AUTO_KINDS else "skipped")
                existing = db.scalar(select(dm.OfficialDocument).where(dm.OfficialDocument.source_url == url))
                if existing:
                    link.document_id = existing.id
                db.add(link)
                run.new_links += 1
            else:
                link.last_seen_at, link.still_listed, link.listing_url = now(), True, listing
                if text and link.title != title_for(url, text):
                    link.title = title_for(url, text)
                if link.note and link.note.startswith("Possibly replaced"):
                    link.note = None

                # The same PDF can first be discovered through WordPress media/sitemap
                # (filename only), then later through the COE listing with its explicit
                # HALL/SEATING label.  Never let a filename-only first sighting freeze
                # the wrong kind forever: the official listing label is authoritative.
                label = (text or "").upper().replace("_", " ")
                explicit_kind = ("hall_allotment" if "HALL ALLOTMENT" in label else
                                 "seating_allotment" if "SEATING ALLOTMENT" in label else None)
                if explicit_kind:
                    link.doc_kind = explicit_kind
                    link.exam_date = meta["exam_date"] or link.exam_date
                    link.session = meta["session"] or link.session
                    link.upload_month = meta["upload_month"] or link.upload_month

                    existing = (db.get(dm.OfficialDocument, link.document_id) if link.document_id else
                                db.scalar(select(dm.OfficialDocument).where(dm.OfficialDocument.source_url == url)))
                    if existing is not None:
                        link.document_id = existing.id
                        if existing.doc_kind != explicit_kind:
                            existing.doc_kind = explicit_kind
                            existing.exam_date = meta["exam_date"] or existing.exam_date
                            existing.session = meta["session"] or existing.session
                            # A prior successful parse used the wrong parser. Requeue the
                            # current binary so the next cycle reparses it and rebuilds
                            # every affected register-number lookup, not just one test ID.
                            versions = db.scalars(select(dm.DocumentVersion).where(
                                dm.DocumentVersion.document_id == existing.id,
                                dm.DocumentVersion.is_current == True  # noqa: E712
                            )).all()
                            for version in versions:
                                ingest = db.scalar(select(dm.LiveIngest).where(
                                    dm.LiveIngest.version_id == version.id))
                                if ingest is not None:
                                    ingest.status, ingest.attempts, ingest.error = "pending", 0, None
                                    ingest.processed_at = None
                                from .vsb_live.pipeline import forget as forget_live_parse
                                forget_live_parse(version.id)
                    elif link.download_status == "skipped" and explicit_kind in AUTO_KINDS:
                        link.download_status = "discovered"
            link.last_seen_at = now()
        if found:
            # A link counts as removed ONLY when an HTML listing page that carried it was read successfully this run
            # and no discovery method still lists it. A failed method never removes anything.
            for gone in db.scalars(select(dm.VsbSourceLink).where(dm.VsbSourceLink.still_listed == True,  # noqa: E712
                                                                  dm.VsbSourceLink.listing_url.in_(list(col.pages_read)))).all():
                if gone.url not in seen_urls:
                    gone.still_listed = False
                    gone.note = gone.note or "No longer listed on the official page."
        db.flush()
        _note_replacements(db)
        db.commit()

        if download:
            todo = db.scalars(select(dm.VsbSourceLink).where(
                dm.VsbSourceLink.still_listed == True, dm.VsbSourceLink.doc_kind.in_(AUTO_KINDS),  # noqa: E712
                dm.VsbSourceLink.download_status.in_(("discovered", "failed", "unavailable", "unchanged", "downloaded")))
                .order_by(case((dm.VsbSourceLink.download_status == "discovered", 0), else_=1),
                          dm.VsbSourceLink.last_attempt_at.asc().nullsfirst(), dm.VsbSourceLink.id.desc())).all()
            budget = max(1, settings.vsb_max_downloads_per_run)
            for link in todo:
                # Already-stored links are only re-checked cheaply (conditional request), new ones are fetched in full.
                if budget <= 0:
                    notes.append(f"Download limit of {settings.vsb_max_downloads_per_run} per run reached; run again for the rest.")
                    break
                budget -= 1
                outcome, v = download_link(db, http, link, actor)
                db.commit()
                if outcome == "downloaded":
                    run.downloaded += 1
                    if v is not None and auto_process:
                        try:
                            msg = auto_process(db, v)
                            if msg:
                                notes.append(msg)
                        except Exception:  # noqa: BLE001
                            db.rollback()
                            notes.append(f"Link #{link.id}: downloaded, but automatic processing failed; use Process manually.")
                elif outcome == "duplicate":
                    run.duplicates += 1
                elif outcome == "unavailable":
                    run.unavailable += 1
                elif outcome in ("failed", "blocked"):
                    run.failed += 1
                db.commit()      # persist the counters now: the next failed download rolls back the session
        run = db.get(dm.VsbCrawlRun, run.id)
        run.status = "partial" if (run.failed or run.unavailable) else "ok"
        run.finished_at = now()
        run.message = " ".join(notes)[:4000] or None
        db.commit()
        return run_dict(run)
    except Exception as e:  # noqa: BLE001
        log.exception("VSB discovery run failed")
        db.rollback()
        run = db.get(dm.VsbCrawlRun, run.id)
        run.status, run.finished_at = "failed", now()
        run.message = f"Unexpected error ({type(e).__name__}); see server log. Nothing was deleted."
        db.commit()
        return run_dict(run)
    finally:
        _run_lock.release()


def download_one(db: Session, link_id: int, actor: str) -> tuple[dm.VsbSourceLink, str, dm.DocumentVersion | None]:
    link = db.get(dm.VsbSourceLink, link_id)
    if link is None:
        raise LookupError("link")
    if not is_allowed_url(link.url):
        raise ValueError("not-allowed")
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("busy")
    try:
        outcome, v = download_link(db, _Http(), link, actor)
        db.commit()
        return db.get(dm.VsbSourceLink, link_id), outcome, v
    finally:
        _run_lock.release()


def run_dict(r: dm.VsbCrawlRun) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": r.id, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "trigger": r.trigger,
            "actor": r.actor, "status": r.status, "page_url": r.page_url, "links_found": r.links_found,
            "new_links": r.new_links, "downloaded": r.downloaded, "duplicates": r.duplicates,
            "unavailable": r.unavailable, "failed": r.failed, "message": r.message}


FAILED_RETRY_MINUTES = 15
BACKOFF_CAP_MINUTES = 30


def scheduled_due(db: Session, at: datetime, startup: bool = False) -> bool:
    """Due when the configured polling interval (VSB_POLL_MINUTES, 5..1440) has passed since the last scheduled run.
    After failed runs the wait grows (poll, 2x, 4x ... capped at 30 min) instead of hammering an unreachable server.
    `startup=True` (first cycle after the server starts, VSB_SCAN_ON_STARTUP) is always due."""
    if not settings.vsb_auto_discover_enabled:
        return False
    if startup and settings.vsb_scan_on_startup:
        return True
    rows = db.execute(select(dm.VsbCrawlRun.started_at, dm.VsbCrawlRun.status).where(dm.VsbCrawlRun.trigger == "scheduler")
                      .order_by(dm.VsbCrawlRun.started_at.desc()).limit(6)).all()
    if not rows:
        return True
    last = rows[0][0] if rows[0][0].tzinfo else rows[0][0].replace(tzinfo=timezone.utc)
    wait = settings.poll_seconds
    streak = 0
    for _, st in rows:
        if st == "failed":
            streak += 1
        else:
            break
    if streak:
        wait = min(max(wait, wait * (2 ** (streak - 1))), max(wait, BACKOFF_CAP_MINUTES * 60))
    return (at - last).total_seconds() >= wait
