"""Dedicated parser for the VSB "HALL SEATING FOR THE END SEMESTER EXAMINATIONS" (hall-allotment) PDF.

Input: the text of each page (PyMuPDF `get_text("text")`, stored by the document pipeline, or OCR text).
Layout (verified on the official 14.11.26-FN-HALL.pdf text layer):

    DATE OF EXAMINATION: 14-11-2026 SESSION : FN
    [23CET304R] WATER SUPPLY AND WASTEWATER ENGINEERING          <- subject
    996615568001, 996615568002, ..., 996615568005 MB III 202 5   <- register numbers, hall, hall total
    996615568006, ..., 996615568012,                             <- long lists wrap; every wrapped line ends with a comma
    996615568013 ... MB III 203 12
    BE-CIVIL                                                     <- programme footer (may repeat on a continuation page)
    TOTAL 35                                                     <- programme total (printed on the programme's last page)

Nothing is guessed: a group without a readable hall/total, a count that disagrees with the printed total, an OCR-damaged
number, a repeated student or a programme total that does not add up is reported as an Issue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..regno import expand_register_list
from .common import Issue, PageInput, norm_hall, ocr_suspect, parse_exam_header, squash

_SKIP = re.compile(
    r"^(V\.?\s?S\.?\s?B\.?\s+ENGINEERING\s+COLLEGE|\(An\s+Autonomous|Approved\s+by\s+AICTE|NH\s*-?\s*67\b|"
    r"OFFICE\s+OF\s+THE\s+CONTROLLER|Programme\s+List\s+of\s+students|Hall\s+Number\s+Total|Powered\s+by\s+TCPDF|"
    r"DATE\s+OF\s+EXAM|List\s+of\s+students\s+registered)", re.I)
_TITLE = re.compile(r"^HALL\s+SEATING\s+FOR\s+THE\s+(.+)$", re.I)
_SUBJECT = re.compile(r"^[\[\(]\s*([A-Za-z0-9]{5,12})\s*[\]\)]\s*(.*)$")
_TOTAL = re.compile(r"^TOTAL\s*[:\-]?\s*(\d{1,5})$", re.I)
_DEPT = re.compile(r"^(?:B\.?\s?E\.?|B\.?\s?TECH\.?|M\.?\s?E\.?|M\.?\s?TECH\.?|MBA|MCA)(?![A-Za-z])[\s.\-–]*.*$", re.I)
_ROOM = re.compile(r"^[A-Za-z]{0,3}-?\d{1,4}[A-Za-z]?$")
_BLOCK = re.compile(r"^[A-Za-z]{1,6}$")
_TOKEN = re.compile(r"[A-Za-z0-9]+")


@dataclass
class HallGroup:
    """One printed block: a subject, the register numbers seated in one hall, and that hall's printed total."""
    page: int
    exam_date: date | None
    session: str | None
    department: str | None
    subject_code: str | None
    subject_title: str | None
    hall: str | None
    declared_count: int | None
    register_numbers: list[str]
    raw: str
    method: str = "text_layer"
    issues: list[Issue] = field(default_factory=list)


@dataclass
class DeptTotal:
    department: str
    declared: int | None
    extracted: int
    pages: list[int]
    ok: bool | None            # None = no total printed


@dataclass
class HallDocument:
    title: str | None
    groups: list[HallGroup]
    dept_totals: list[DeptTotal]
    issues: list[Issue]
    sessions: list[tuple[date, str | None]]
    page_count: int

    def all_issues(self) -> list[Issue]:
        return self.issues + [i for g in self.groups for i in g.issues]

    def total_students(self) -> int:
        return len({(g.exam_date, g.session, r) for g in self.groups for r in g.register_numbers})

    def hall_totals(self) -> dict[tuple, int]:
        out: dict[tuple, int] = {}
        for g in self.groups:
            k = (g.exam_date, g.session, g.hall)
            out[k] = out.get(k, 0) + len(g.register_numbers)
        return out


# ----------------------------------------------------------------------------- tail: "<hall label> <count>"
def split_tail(text: str) -> tuple[str, str, int] | None:
    """'... 996615568005 MB III 202 5' -> ('... 996615568005', 'MB III 202', 5). None if the text has no hall tail."""
    toks = text.split()
    if len(toks) < 2 or not toks[-1].isdigit():
        return None
    room = toks[-2]
    if not _ROOM.match(room):
        return None
    j = len(toks) - 2
    while j - 1 >= 0 and _BLOCK.match(toks[j - 1]) and toks[j - 1].upper() != "TOTAL":
        j -= 1
    return " ".join(toks[:j]), " ".join(toks[j:len(toks) - 1]), int(toks[-1])


def _expand(reg_text: str, ocr: bool) -> tuple[list[str], list[Issue]]:
    issues: list[Issue] = []
    kept: list[str] = []
    for tok in re.split(r"(\s+)", reg_text):
        sug = ocr_suspect(tok)
        if sug:
            issues.append(Issue("ocr_ambiguous_register", "error",
                                f"'{tok.strip(',')}' looks like a register number damaged by OCR (digit reading would be {sug}); "
                                "it was NOT used. Correct it manually.", detail={"token": tok.strip(','), "suggestion": sug}))
            kept.append(" ")
        else:
            kept.append(tok)
    res = expand_register_list("".join(kept))
    for pi in res.issues:
        sev = "warning" if pi.kind in ("nonstandard_id", "duplicate") else "error"
        kind = {"nonstandard_id": "nonstandard_register_number", "duplicate": "duplicate_in_group"}.get(pi.kind, pi.kind)
        issues.append(Issue(kind, sev, f"{pi.token}: {pi.message}", detail={"token": pi.token}))
    return res.numbers, issues


# ----------------------------------------------------------------------------- the parser
def parse_hall_pdf(pages: list[PageInput]) -> HallDocument:
    doc_issues: list[Issue] = []
    groups: list[HallGroup] = []
    totals: list[DeptTotal] = []
    title: str | None = None
    sessions: list[tuple[date, str | None]] = []

    cur_date: date | None = None
    cur_sess: str | None = None
    pending: list[HallGroup] = []                 # groups printed since the last programme footer
    run: dict[str, list[HallGroup]] = {}          # programme label -> groups of its current (unfinished) run
    run_pages: dict[str, list[int]] = {}
    last_label: str | None = None

    for pg in pages:
        text = pg.text or ""
        ocr = pg.method == "ocr"
        if not text.strip():
            doc_issues.append(Issue("empty_page", "warning", f"Page {pg.index + 1} has no readable text.", page=pg.index))
            continue
        d, s, malformed = parse_exam_header(text)
        if malformed and d is None:
            doc_issues.append(Issue("exam_date_unreadable", "error",
                                    f"Page {pg.index + 1}: the 'DATE OF EXAMINATION' line could not be read; the date was not guessed.",
                                    page=pg.index))
        if d is not None:
            cur_date = d
        elif cur_date is not None and not malformed:
            doc_issues.append(Issue("header_inherited", "info",
                                    f"Page {pg.index + 1} has no examination date; the previous page's date was used.", page=pg.index))
        if s is not None:
            cur_sess = s
        if cur_date and (cur_date, cur_sess) not in sessions:
            sessions.append((cur_date, cur_sess))
        page_date, page_sess = (d or cur_date), (s or cur_sess)

        subject_code: str | None = None
        subject_title: str | None = None
        buf: list[str] = []

        def finish(reg_text: str, hall: str | None, declared: int | None, raw: str) -> None:
            if subject_code is None and hall is None and declared is None and not re.search(r"\d{6,}", reg_text):
                return                                  # stray text on a page that is not a hall list
            nums, iss = _expand(reg_text, ocr)
            g = HallGroup(pg.index, page_date, page_sess, None, subject_code, subject_title, norm_hall(hall), declared,
                          nums, squash(raw)[:600], pg.method, iss)
            if subject_code is None:
                g.issues.append(Issue("subject_missing", "error", "Register numbers were found before any '[CODE] TITLE' line.",
                                      page=pg.index, hall=g.hall))
            if hall is None or declared is None:
                g.issues.append(Issue("hall_or_total_missing", "error",
                                      "The hall or its total could not be read for this block; it cannot be used until corrected.",
                                      page=pg.index, subject_code=subject_code))
            elif declared != len(nums):
                g.issues.append(Issue("group_count_mismatch", "error",
                                      f"{g.hall} / {subject_code}: printed total {declared} but {len(nums)} register numbers were read.",
                                      page=pg.index, hall=g.hall, subject_code=subject_code,
                                      detail={"declared": declared, "extracted": len(nums)}))
            if page_date is None or page_sess is None:
                g.issues.append(Issue("session_unknown", "error", "Examination date or FN/AN session is unknown for this block.",
                                      page=pg.index, hall=g.hall))
            if ocr:
                g.issues.append(Issue("ocr_text", "warning", "Read from OCR text; verify every number against the PDF.",
                                      page=pg.index, hall=g.hall))
            for i in g.issues:
                i.page = i.page if i.page is not None else pg.index
                i.hall = i.hall or g.hall
                i.subject_code = i.subject_code or subject_code
            groups.append(g)
            pending.append(g)

        for raw in text.splitlines():
            line = squash(raw)
            if not line:
                continue
            mt = _TITLE.match(line)
            if mt:
                title = title or "HALL SEATING FOR THE " + squash(mt.group(1))
                continue
            if _SKIP.match(line):
                continue
            ms = _SUBJECT.match(line)
            if ms:
                if buf:
                    finish(" ".join(buf), None, None, " ".join(buf))
                    buf = []
                subject_code, subject_title = ms.group(1).upper(), squash(ms.group(2)) or None
                continue
            mtot = _TOTAL.match(line)
            if mtot:
                if buf:
                    finish(" ".join(buf), None, None, " ".join(buf))
                    buf = []
                if last_label is None:
                    doc_issues.append(Issue("total_without_department", "warning",
                                            f"Page {pg.index + 1}: a 'TOTAL {mtot.group(1)}' line has no programme label above it.",
                                            page=pg.index))
                    continue
                label = last_label
                members = run.pop(label, [])
                extracted = sum(len(g.register_numbers) for g in members)
                declared = int(mtot.group(1))
                ok = declared == extracted
                totals.append(DeptTotal(label, declared, extracted, sorted(set(run_pages.pop(label, []))), ok))
                if not ok:
                    doc_issues.append(Issue("department_total_mismatch", "error",
                                            f"{label}: printed total {declared} but {extracted} register numbers were read across its blocks.",
                                            page=pg.index, detail={"declared": declared, "extracted": extracted, "department": label}))
                last_label = None
                continue
            if _DEPT.match(line) and not re.search(r"\d{3,}", line):
                if buf:
                    finish(" ".join(buf), None, None, " ".join(buf))
                    buf = []
                label = squash(line).upper()
                for g in pending:
                    g.department = label
                run.setdefault(label, []).extend(pending)
                run_pages.setdefault(label, []).append(pg.index)
                pending = []
                last_label = label
                continue
            # register material (possibly with the hall tail)
            buf.append(line)
            joined = " ".join(buf)
            tail = split_tail(joined)
            if tail and (tail[0].strip() or len(buf) > 1):
                reg_text, hall, n = tail
                finish(reg_text, hall, n, joined)
                buf = []
            elif not re.search(r"\d", line) and not buf[:-1] and subject_code and groups_has_title_room(subject_title):
                buf.pop()
                subject_title = squash((subject_title or "") + " " + line)
        if buf:
            finish(" ".join(buf), None, None, " ".join(buf))

    for g in pending:
        g.issues.append(Issue("department_missing", "error", "No programme label (e.g. 'BE-CSE') followed this block.",
                              page=g.page, hall=g.hall, subject_code=g.subject_code))
    for label, members in run.items():
        doc_issues.append(Issue("department_total_missing", "warning",
                                f"{label}: no 'TOTAL n' line was found after its last block; its total could not be checked.",
                                detail={"department": label}))
        totals.append(DeptTotal(label, None, sum(len(g.register_numbers) for g in members), sorted(set(run_pages.get(label, []))), None))
    if not groups:
        doc_issues.append(Issue("no_groups", "error",
                                "No hall blocks were recognised. This does not look like a VSB hall-allotment PDF, or its layout changed; "
                                "nothing was extracted."))
    if not sessions:
        doc_issues.append(Issue("exam_date_missing", "error", "No examination date was found in the document."))
    elif any(sess is None for _, sess in sessions):
        doc_issues.append(Issue("session_missing", "error", "The FN/AN session could not be read from the document header."))
    if len({s for s in sessions}) > 1:
        doc_issues.append(Issue("several_sessions", "warning",
                                "The PDF contains more than one date/session; each is reconciled separately."))
    return HallDocument(title, groups, totals, doc_issues, sessions, len(pages))


def groups_has_title_room(title: str | None) -> bool:
    """A subject title line may wrap onto a second text line; only accept this for a short, still-open title."""
    return bool(title) and len(title) < 90
