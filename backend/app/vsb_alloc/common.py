"""Shared types and small helpers for the VSB allocation parsers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

PARSER_VERSION = "vsb-alloc-1.0"

SEVERITIES = ("info", "warning", "error")


@dataclass
class Issue:
    """Something a human must look at. `kind` is a stable machine code, `message` is shown to the administrator."""
    kind: str
    severity: str
    message: str
    page: int | None = None          # 0-based page index
    hall: str | None = None
    register_number: str | None = None
    subject_code: str | None = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {"kind": self.kind, "severity": self.severity, "message": self.message, "page": self.page,
             "hall": self.hall, "register_number": self.register_number, "subject_code": self.subject_code}
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class Word:
    """One word with its box on the page (PDF points, origin top-left, y down)."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class PageInput:
    index: int
    text: str
    words: list[Word] = field(default_factory=list)      # empty when only the text layer / OCR text is known
    method: str = "text_layer"                            # text_layer | ocr | empty
    ocr_confidence: float | None = None


# ----------------------------------------------------------------------------- text helpers
_WS = re.compile(r"\s+")


def squash(s: str) -> str:
    return _WS.sub(" ", (s or "").replace("\u00a0", " ")).strip()


def norm_hall(label: str | None) -> str | None:
    """Canonical spelling of a hall label: upper-case, single spaces. 'mb  iii 02' -> 'MB III 02'."""
    if not label:
        return None
    v = squash(label).upper().strip(" :-")
    v = re.sub(r"\s*-\s*", "-", v)
    return v or None


# ----------------------------------------------------------------------------- header: date + session
_HEADER = re.compile(
    r"DATE\s+OF\s+EXAM(?:INATION)?\s*[:\-]?\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{4})"
    r"(?:.*?SESSION\s*[:\-]?\s*([FA]\.?\s?N\.?))?", re.I)
_SESSION_ONLY = re.compile(r"SESSION\s*[:\-]?\s*([FA]\.?\s?N\.?)\b", re.I)


def parse_exam_header(text: str) -> tuple[date | None, str | None, bool]:
    """(exam date, 'FN'|'AN', malformed) from page text. `malformed` = a date label was found but unreadable."""
    for line in (text or "").splitlines():
        m = _HEADER.search(line)
        if not m:
            continue
        d, mo, y = (int(x) for x in m.group(1, 2, 3))
        try:
            dt = date(y, mo, d)
        except ValueError:
            return None, _norm_session(m.group(4)), True
        sess = _norm_session(m.group(4))
        if sess is None:
            s2 = _SESSION_ONLY.search(line)
            sess = _norm_session(s2.group(1)) if s2 else None
        return dt, sess, False
    if re.search(r"DATE\s+OF\s+EXAM", text or "", re.I):
        return None, None, True
    return None, None, False


def _norm_session(v: str | None) -> str | None:
    if not v:
        return None
    return re.sub(r"[^A-Z]", "", v.upper())[:2] or None


# ----------------------------------------------------------------------------- register-number sanity
_OCR_CONFUSABLE = set("OoIlSsBZ")
_DIGITSISH = re.compile(r"^[0-9OoIlSsBZ]{10,14}$")


def ocr_suspect(token: str) -> str | None:
    """If a token looks like a 12-digit register number damaged by OCR (O/0, l/1, S/5, B/8, Z/2), return the digit-only
    reading as a *suggestion*. The caller must never apply it silently."""
    t = token.strip(",.;:")
    if not _DIGITSISH.match(t) or t.isdigit():
        return None
    if not any(c in _OCR_CONFUSABLE for c in t):
        return None
    table = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "s": "5", "B": "8", "Z": "2"})
    return t.translate(table)


def dept_code(reg: str) -> str | None:
    """Programme code inside a standard 12-digit VSB register number (digits 7-9: 9225 YY DDD NNN). Used only to
    carry a department label learned from the same document onto a number that lacks one; always flagged."""
    return reg[6:9] if re.fullmatch(r"\d{12}", reg or "") else None
