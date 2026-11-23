"""Discovery of official allotment PDFs by several independent, public, read-only methods.

Methods (each one is recorded in vsb_source_health, so a dashboard can say which one works and which one does not):
  html      the official listing pages (links, <iframe>/<embed>/<object> sources, PDF-viewer ?file= wrappers)
  wp_media  WordPress REST  /wp-json/wp/v2/media?mime_type=application/pdf   (public by default)
  wp_search WordPress REST  /wp-json/wp/v2/search?search=...  -> the few matching pages are then read like listing pages
  sitemap   public XML sitemaps (wp-sitemap.xml, sitemap_index.xml, sitemap.xml) -> direct .pdf entries

Rules: only https URLs on the allow-listed official hosts are ever requested; robots.txt is obeyed by the shared HTTP client;
no login, no private endpoint, no URL is guessed or built from a file-name pattern. A method that fails is recorded and
skipped; the others still run. Existing links/documents are never removed because a method failed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import doc_models as dm
from ..config import settings

log = logging.getLogger("exam_monitor.discovery")

MAX_SITEMAPS = 12
MAX_WP_PAGES = 3
MAX_SEARCH_PAGES = 8
SEARCH_TERMS = ("hall allotment", "seating allotment", "hall seating")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Candidate:
    url: str
    text: str
    method: str
    listing_url: str


@dataclass
class MethodResult:
    key: str
    method: str
    url: str
    ok: bool = False
    items: int = 0
    http_status: int | None = None
    error: str | None = None
    skipped: bool = False


@dataclass
class Collected:
    candidates: list[Candidate] = field(default_factory=list)
    results: list[MethodResult] = field(default_factory=list)
    pages_read: set[str] = field(default_factory=set)         # listing pages that were read successfully this run

    @property
    def any_ok(self) -> bool:
        return any(r.ok for r in self.results)


# ----------------------------------------------------------------------------- HTML: links + embedded documents
class _EmbedParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("iframe", "embed", "source"):
            raw = a.get("src") or a.get("data-src")
        elif tag == "object":
            raw = a.get("data")
        elif tag == "a":
            raw = a.get("data-pdf") or a.get("data-file")        # lazy-loaded viewers
        else:
            return
        if raw:
            self.items.append((raw.strip(), a.get("title") or "Embedded document"))


def extract_embedded_pdf_links(html: str, base_url: str) -> list[dict]:
    """PDFs referenced by <iframe>/<embed>/<object>, including viewers such as viewer.html?file=<pdf url>."""
    from ..vsb_sources import is_allowed_url
    p = _EmbedParser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001
        pass
    out, seen = [], set()
    for raw, text in p.items:
        cands = [urljoin(base_url, raw)]
        q = parse_qs(urlparse(raw).query)
        for k in ("file", "url", "src", "pdf"):
            for v in q.get(k, []):
                cands.append(urljoin(base_url, v))
        for c in cands:
            c = urldefrag(c)[0]
            if urlparse(c).path.lower().endswith(".pdf") and is_allowed_url(c) and c not in seen:
                seen.add(c)
                out.append({"url": c[:1000], "text": text})
    return out


# ----------------------------------------------------------------------------- helpers per method
def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def _health_key(method: str, url: str) -> str:
    return f"{method}:{url}"[:300]


def _try(http, url: str, limit: int, res: MethodResult):
    """GET with the shared polite client. Returns body bytes or None (the failure is written to `res`)."""
    from ..vsb_sources import FetchError
    try:
        status, headers, body = http.get(url, {"Accept": "application/json, text/html, application/xml, */*"}, limit=limit)
        res.http_status = status
        if status == 304 or not body:
            res.error = "empty response"
            return None, headers
        return body, headers
    except FetchError as e:
        res.http_status, res.error = e.status, str(e)[:480]
    except Exception as e:  # noqa: BLE001
        res.error = f"{type(e).__name__}: {str(e)[:200]}"
    return None, {}


def _from_html(http, page_url: str, col: Collected) -> str | None:
    from ..vsb_sources import extract_pdf_links, is_allowed_url
    res = MethodResult(_health_key("html", page_url), "html", page_url)
    col.results.append(res)
    if not is_allowed_url(page_url):
        res.skipped, res.error = True, "not an https address on an official host"
        return None
    body, _ = _try(http, page_url, 3 * 1024 * 1024, res)
    if body is None:
        return None
    html = body.decode("utf-8", "replace")
    links = extract_pdf_links(html, page_url) + extract_embedded_pdf_links(html, page_url)
    seen = set()
    for it in links:
        if it["url"] not in seen:
            seen.add(it["url"])
            col.candidates.append(Candidate(it["url"], it["text"], "html", page_url))
    res.ok, res.items = True, len(seen)
    col.pages_read.add(page_url)
    return html


def _from_wp_media(http, origin: str, col: Collected) -> None:
    from ..vsb_sources import is_allowed_url
    base = f"{origin}/wp-json/wp/v2/media"
    res = MethodResult(_health_key("wp_media", base), "wp_media", base)
    col.results.append(res)
    total_pages, found = 1, 0
    page = 1
    while page <= min(total_pages, MAX_WP_PAGES):
        url = f"{base}?mime_type=application/pdf&per_page=100&orderby=date&order=desc&page={page}"
        body, headers = _try(http, url, 4 * 1024 * 1024, res)
        if body is None:
            if page > 1:
                break                       # earlier pages already worked; keep them
            return
        try:
            data = json.loads(body.decode("utf-8", "replace"))
            assert isinstance(data, list)
        except Exception:  # noqa: BLE001
            res.error = "the media endpoint did not return a JSON list (feature disabled or blocked)"
            return
        h = {k.lower(): v for k, v in headers.items()}
        try:
            total_pages = int(h.get("x-wp-totalpages", "1"))
        except ValueError:
            total_pages = 1
        for item in data:
            src = str(item.get("source_url") or "")
            if src.lower().endswith(".pdf") and is_allowed_url(src):
                title = ((item.get("title") or {}).get("rendered") or "") if isinstance(item.get("title"), dict) else ""
                col.candidates.append(Candidate(src[:1000], re.sub(r"<[^>]+>", "", title)[:300], "wp_media", url[:1000]))
                found += 1
        res.ok, res.items, res.error = True, found, None
        page += 1


def _from_wp_search(http, origin: str, col: Collected) -> None:
    from ..vsb_sources import is_allowed_url
    base = f"{origin}/wp-json/wp/v2/search"
    res = MethodResult(_health_key("wp_search", base), "wp_search", base)
    col.results.append(res)
    urls: list[str] = []
    for term in SEARCH_TERMS:
        body, _ = _try(http, f"{base}?search={term.replace(' ', '+')}&per_page=20", 1024 * 1024, res)
        if body is None:
            if not res.ok:
                return
            continue
        try:
            for item in json.loads(body.decode("utf-8", "replace")):
                u = str(item.get("url") or "")
                if is_allowed_url(u) and u not in urls:
                    urls.append(u)
        except Exception:  # noqa: BLE001
            res.error = "the search endpoint did not return JSON"
            return
        res.ok = True
    found = 0
    for u in urls[:MAX_SEARCH_PAGES]:
        sub = MethodResult(_health_key("wp_search_page", u), "wp_search", u)
        body, _ = _try(http, u, 3 * 1024 * 1024, sub)
        if body is None:
            continue
        html = body.decode("utf-8", "replace")
        from ..vsb_sources import extract_pdf_links
        for it in extract_pdf_links(html, u) + extract_embedded_pdf_links(html, u):
            col.candidates.append(Candidate(it["url"], it["text"], "wp_search", u))
            found += 1
    res.items = found


def _loc_values(xml: bytes) -> tuple[list[str], list[str]]:
    """(urls, child sitemaps) from a sitemap or sitemap index. XXE-safe: ElementTree does not resolve external entities."""
    root = ElementTree.fromstring(xml)
    tag = root.tag.rsplit("}", 1)[-1].lower()
    locs = [e.text.strip() for e in root.iter() if e.tag.rsplit("}", 1)[-1].lower() == "loc" and e.text]
    return ([], locs) if tag == "sitemapindex" else (locs, [])


def _from_sitemaps(http, origin: str, col: Collected) -> None:
    from ..vsb_sources import is_allowed_url
    queue = [f"{origin}/wp-sitemap.xml", f"{origin}/sitemap_index.xml", f"{origin}/sitemap.xml"]
    first = MethodResult(_health_key("sitemap", origin), "sitemap", origin)
    col.results.append(first)
    seen, found, fetched = set(), 0, 0
    while queue and fetched < MAX_SITEMAPS:
        u = queue.pop(0)
        if u in seen or not is_allowed_url(u):
            continue
        seen.add(u)
        sub = MethodResult(u, "sitemap", u)
        body, _ = _try(http, u, 4 * 1024 * 1024, sub)
        fetched += 1
        if body is None:
            first.http_status, first.error = sub.http_status, first.error or sub.error
            continue
        try:
            urls, children = _loc_values(body)
        except Exception:  # noqa: BLE001
            first.error = "a sitemap could not be parsed"
            continue
        first.ok, first.error = True, None
        for c in children:
            if c.lower().endswith(".xml") and c not in seen:
                queue.append(c)
        for c in urls:
            if urlparse(c).path.lower().endswith(".pdf") and is_allowed_url(c):
                col.candidates.append(Candidate(c[:1000], "", "sitemap", u))
                found += 1
        if first.ok and found:
            pass
    first.items = found


# ----------------------------------------------------------------------------- public entry point
def collect(http, primary_page: str) -> Collected:
    """Run every enabled discovery method. Never raises."""
    from ..vsb_sources import is_allowed_url
    col = Collected()
    pages = [primary_page] + [u for u in settings.extra_listing_pages if u != primary_page]
    origins = []
    for p in pages:
        try:
            _from_html(http, p, col)
        except Exception as e:  # noqa: BLE001
            log.warning("html discovery crashed for %s: %s", p, type(e).__name__)
        o = _origin(p)
        if is_allowed_url(p) and o not in origins:
            origins.append(o)
    for o in origins:
        for enabled, fn in ((settings.vsb_wp_discovery, _from_wp_media), (settings.vsb_wp_discovery, _from_wp_search),
                            (settings.vsb_sitemap_discovery, _from_sitemaps)):
            if not enabled:
                continue
            try:
                fn(http, o, col)
            except Exception as e:  # noqa: BLE001
                log.warning("%s discovery crashed: %s", fn.__name__, type(e).__name__)
    return col


def record_health(db: Session, results: list[MethodResult]) -> None:
    stamp = _now()
    for r in results:
        row = db.scalar(select(dm.VsbSourceHealth).where(dm.VsbSourceHealth.source_key == r.key))
        if row is None:
            row = dm.VsbSourceHealth(source_key=r.key, method=r.method, url=r.url[:1000], consecutive_failures=0, items_found=0)
            db.add(row)
        row.last_attempt_at, row.last_http_status = stamp, r.http_status
        if r.skipped:
            row.last_status, row.last_error = "skipped", (r.error or None) and r.error[:500]
        elif r.ok:
            row.last_status, row.last_error, row.last_success_at = "ok", None, stamp
            row.consecutive_failures, row.items_found = 0, r.items
        else:
            row.last_status, row.last_error = "failed", (r.error or "unknown error")[:500]
            row.consecutive_failures = (row.consecutive_failures or 0) + 1
    db.commit()
