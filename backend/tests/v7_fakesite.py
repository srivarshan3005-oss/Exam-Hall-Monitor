"""Offline stand-in for the official VSB websites (FIXTURE tests only - never the live source).

It replaces the single network call of the crawler (vsb_sources._Http._raw), so URL allow-listing, robots.txt handling, HTTP
status handling, conditional requests, content-type / size / PDF-signature validation, retries and hashing are the REAL code.
"""
from __future__ import annotations

import io
import urllib.error
from pathlib import Path

from app import vsb_sources as vs
from app.config import settings

BASE = "https://vsbec.edu.in"
COE = f"{BASE}/controller-of-examination/"
UPLOADS = f"{BASE}/wp-content/uploads/2026/11/"
HALL_URL = UPLOADS + "20.11.26-AN-HALL.pdf"
SEAT_URL = UPLOADS + "20.11.26-AN-SEAT.pdf"
COE_HOST = "https://coe.vsbec.edu.in/"


class FakeSite:
    def __init__(self):
        self.routes: dict[str, dict] = {}
        self.calls: list[str] = []

    def add(self, url, body=b"", status=200, ctype="text/html; charset=utf-8", headers=None, exc=None):
        if isinstance(body, str):
            body = body.encode()
        h = {"Content-Type": ctype, **(headers or {})}
        self.routes[url] = {"status": status, "body": body, "headers": h, "exc": exc}

    def add_pdf(self, url, path_or_bytes, etag=None, ctype="application/pdf", **kw):
        data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
        self.add(url, bytes(data), ctype=ctype, headers={"ETag": etag} if etag else None, **kw)

    def remove(self, url):
        self.routes.pop(url, None)

    def listing(self, urls_and_text, extra=""):
        links = "".join(f'<a href="{u}">{t}</a>' for u, t in urls_and_text)
        self.add(COE, f"<html><body>{links}{extra}</body></html>")

    def install(self, monkeypatch):
        site = self
        monkeypatch.setattr(settings, "vsb_request_delay_seconds", 0.0)
        monkeypatch.setattr(settings, "vsb_max_retries", 0)

        def raw(self_, url, headers=None, limit=None):
            site.calls.append(url)
            r = site.routes.get(url)
            if url.endswith("/robots.txt") and r is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
            if r is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
            if r["exc"] is not None:
                raise r["exc"]
            if r["status"] >= 400:
                raise urllib.error.HTTPError(url, r["status"], "err", r["headers"], io.BytesIO())
            hdr = {k.lower(): v for k, v in (headers or {}).items()}
            etag = r["headers"].get("ETag")
            if etag and hdr.get("if-none-match") == etag:
                raise urllib.error.HTTPError(url, 304, "Not Modified", r["headers"], io.BytesIO())
            body = r["body"]
            if limit and len(body) > limit:
                raise vs.FetchError("blocked", "File is larger than the limit")
            return r["status"], dict(r["headers"]), body

        monkeypatch.setattr(vs._Http, "_raw", raw)
        return self


def standard_site(hall_pdf, seat_pdf, monkeypatch, *, with_seat=True, wp=True, sitemap=True):
    """A site that lists the 20-Nov AN hall list (and seat sheets) on the COE page, plus a COE-host page, WP media and sitemap."""
    s = FakeSite().install(monkeypatch)
    items = [(HALL_URL, "HALL ALLOTMENT - AN (20.11.2026)")]
    if with_seat:
        items.append((SEAT_URL, "SEATING ALLOTMENT - AN (20.11.2026)"))
    s.listing(items)
    s.add(COE_HOST, f'<html><body><iframe src="{HALL_URL}"></iframe></body></html>')
    s.add_pdf(HALL_URL, hall_pdf, etag='"h1"')
    if with_seat:
        s.add_pdf(SEAT_URL, seat_pdf, etag='"s1"')
    if wp:
        import json
        s.add(f"{BASE}/wp-json/wp/v2/media?mime_type=application/pdf&per_page=100&orderby=date&order=desc&page=1",
              json.dumps([{"source_url": HALL_URL, "title": {"rendered": "20.11.26-AN-HALL"}}]), ctype="application/json",
              headers={"X-WP-TotalPages": "1"})
    if sitemap:
        s.add(f"{BASE}/wp-sitemap.xml", f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                         f"<url><loc>{SEAT_URL}</loc></url></urlset>", ctype="application/xml")
    return s
