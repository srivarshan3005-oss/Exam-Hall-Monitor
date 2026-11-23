"""Dedicated parser for the VSB seating-allotment PDF (one page per examination hall).

Each page holds (a) a four-column serpentine seat grid - pairs of "seat number | register number" - and (b) a table
"CODE | TITLE OF THE PAPER | TOTAL | REGISTER NUMBERS" with compressed lists ("996701510092 - 093, 095 - 105").

Why coordinates matter: in the text layer an EMPTY seat prints only its seat number, so a row such as
    1 14 15 28 996701510013
cannot be assigned to a seat from the text alone. This parser therefore maps every register-number word to the seat-number
word that sits in the SAME ROW and the SAME COLUMN, using word boxes. When boxes are unavailable (OCR text) it falls back to
text order and flags every seat as unconfirmed. A seat that cannot be mapped is left empty and reported - never inferred.

The subject table is parsed from text lines. Because a table cell is vertically centred, the register lines of a subject can
be printed BEFORE its "CODE TITLE TOTAL" line (seen on the official PDF for halls MB III A203 / A204). Lines are therefore
attached to rows by consuming them until each row's printed TOTAL is met exactly; a row that cannot be reconciled is flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from statistics import median

from ..regno import expand_register_list
from .common import Issue, PageInput, Word, norm_hall, ocr_suspect, parse_exam_header, squash

_HALL = re.compile(r"EXAM\s+HALL\s*[:\-]?\s*(.+?)(?:\s+Name\s+of\s+the\s+Hall|\s*$)", re.I)
# Heading variants seen / expected on VSB seat sheets: "CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS" (20-Nov-2026 AN),
# "CODE / TITLE OF THE PAPER ...", "SUBJECT CODE TITLE ...", "PAPER CODE - TITLE ...". Only the leading CODE..TITLE words are required.
_TABLE_HEAD = re.compile(r"^(?:(?:SUBJECT|PAPER|COURSE)\s+)?CODE\s*[/\-–|,]?\s*(?:AND\s+)?(?:SUBJECT\s+|PAPER\s+|COURSE\s+)?TITLE\b", re.I)
_TOTAL = re.compile(r"^TOTAL\s*[:\-]?\s*(\d{1,4})$", re.I)
_CODE_LINE = re.compile(r"^(\d{2}[A-Z]{2,5}\d{2,4}[A-Z]{0,2})\b\s*(.*)$")
_LABEL = re.compile(r"^\d{1,4}$")
_REGISH = re.compile(r"^[A-Za-z0-9]{6,20}$")
_ONLY_REGS = re.compile(r"^[\d\s,\-–—A-Za-z]+$")


@dataclass
class SeatAssignment:
    seat: int | None
    register_number: str
    row: int | None
    col: int | None
    subject_code: str | None = None
    x: float | None = None
    y: float | None = None
    flags: list[str] = field(default_factory=list)      # seat_label_missing | seat_label_ambiguous | seat_from_text_order | seat_cell_ambiguous


@dataclass
class SubjectRow:
    code: str
    title: str | None
    declared: int | None
    register_numbers: list[str]
    raw: str
    issues: list[Issue] = field(default_factory=list)


@dataclass
class SeatSheet:
    page: int
    hall: str | None
    exam_date: date | None
    session: str | None
    layout: str                                   # coordinates | text | none
    assignments: list[SeatAssignment]
    empty_seats: list[int]
    subjects: list[SubjectRow]
    declared_total: int | None
    issues: list[Issue] = field(default_factory=list)
    method: str = "text_layer"

    @property
    def grid_count(self) -> int:
        return len(self.assignments)


@dataclass
class SeatDocument:
    sheets: list[SeatSheet]
    issues: list[Issue]
    sessions: list[tuple[date, str | None]]
    page_count: int

    def all_issues(self) -> list[Issue]:
        out = list(self.issues)
        for s in self.sheets:
            out += s.issues + [i for sub in s.subjects for i in sub.issues]
        return out


# ----------------------------------------------------------------------------- helpers
def _count(text: str) -> int:
    return len(expand_register_list(text).numbers)


def _is_regs_only(line: str) -> bool:
    """A line made only of register numbers / 3-digit suffixes / commas / dashes."""
    toks = re.findall(r"[A-Za-z0-9]+|[-–—,]", line)
    if not toks:
        return False
    return all(re.fullmatch(r"\d{3}|\d{6,20}|[-–—,]", t) or (re.fullmatch(r"[A-Za-z0-9]{6,20}", t) and any(c.isdigit() for c in t))
               for t in toks)


def _split_code_rest(rest: str) -> tuple[str | None, int | None, str]:
    """'FOUNDATIONS OF DATA SCIENCE 13 996701510001 - 013' / '10 ENVIRONMENTAL ...' / 'TITLE 12'  ->  (title, total, inline regs)."""
    toks = rest.split()
    limit = next((i for i, t in enumerate(toks) if re.fullmatch(r"\d{6,}", t)), len(toks))   # the total precedes any register number
    total_idx = next((i for i, t in enumerate(toks[:limit]) if re.fullmatch(r"\d{1,3}", t)), None)
    if total_idx is None:
        return (squash(rest) or None), None, ""
    title = " ".join(toks[:total_idx]) or None
    after = " ".join(toks[total_idx + 1:])
    if title is None and after and not _is_regs_only(after):
        # "23GET401R 10 ENVIRONMENTAL SCIENCE AND ENGINEERING": the title follows the total
        words = []
        k = total_idx + 1
        while k < len(toks) and not re.fullmatch(r"\d{3,}", toks[k]):
            words.append(toks[k])
            k += 1
        title = " ".join(words) or None
        after = " ".join(toks[k:])
    return title, int(toks[total_idx]), after


def parse_subject_table(lines: list[str], page: int) -> tuple[list[SubjectRow], int | None]:
    """Rows of the CODE/TITLE/TOTAL/REGISTER table (text lines in stream order). Returns (rows, printed hall total)."""
    rows: list[dict] = []
    gaps: list[list[str]] = [[]]
    declared_total: int | None = None
    for raw in lines:
        line = squash(raw)
        if not line or re.match(r"^Powered\s+by", line, re.I):
            continue
        mt = _TOTAL.match(line)
        if mt:
            declared_total = int(mt.group(1))
            continue
        mc = _CODE_LINE.match(line)
        if mc:
            title, total, inline = _split_code_rest(mc.group(2))
            rows.append({"code": mc.group(1), "title": title, "total": total, "inline": inline, "raw": line})
            gaps.append([])
        elif _is_regs_only(line):
            gaps[-1].append(line)
        elif rows and not re.search(r"\d", line):
            rows[-1]["title"] = squash((rows[-1]["title"] or "") + " " + line)      # wrapped title text
    out: list[SubjectRow] = []
    if not rows:
        return out, declared_total
    assigned: list[list[str]] = [[] for _ in rows]
    assigned[0] += gaps[0]
    unreconciled = set()
    for k, row in enumerate(rows):
        g = gaps[k + 1]
        if k == len(rows) - 1:
            assigned[k] += g
            break
        have = _count(" ".join([row["inline"]] + assigned[k]))
        take = 0
        total = row["total"]
        if total is None:
            assigned[k] += g
            unreconciled.add(k)
            continue
        while have < total and take < len(g):
            take += 1
            have = _count(" ".join([row["inline"]] + assigned[k] + g[:take]))
        if have != total:
            unreconciled.add(k)
        assigned[k] += g[:take]
        assigned[k + 1] += g[take:]
    for k, row in enumerate(rows):
        text = " ".join([row["inline"]] + assigned[k]).strip()
        res = expand_register_list(text)
        sr = SubjectRow(row["code"], row["title"], row["total"], res.numbers, squash(row["raw"] + " | " + text)[:600])
        for pi in res.issues:
            sev = "warning" if pi.kind in ("nonstandard_id", "duplicate") else "error"
            sr.issues.append(Issue({"nonstandard_id": "nonstandard_register_number", "duplicate": "duplicate_in_subject"}.get(pi.kind, pi.kind),
                                   sev, f"{row['code']}: {pi.token}: {pi.message}", page=page, subject_code=row["code"]))
        if row["total"] is None:
            sr.issues.append(Issue("subject_total_missing", "error", f"{row['code']}: the printed TOTAL could not be read.",
                                   page=page, subject_code=row["code"]))
        elif len(res.numbers) != row["total"] or k in unreconciled:
            sr.issues.append(Issue("subject_count_mismatch", "error",
                                   f"{row['code']}: printed total {row['total']} but {len(res.numbers)} register numbers were attached to it.",
                                   page=page, subject_code=row["code"], detail={"declared": row["total"], "extracted": len(res.numbers)}))
        out.append(sr)
    return out, declared_total


# ----------------------------------------------------------------------------- the seat grid
def _cluster(values: list[float], gap: float) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def grid_from_words(words: list[Word]) -> tuple[list[SeatAssignment], list[int], list[Issue]] | None:
    """Map register-number words to seat-number words by row and column. None when the words cannot be used."""
    labels = [w for w in words if _LABEL.match(w.text)]
    regs = [w for w in words if _REGISH.match(w.text) and any(c.isdigit() for c in w.text) and not _LABEL.match(w.text)]
    if not regs:
        return [], [int(w.text) for w in labels], []
    if len(labels) < 2:
        return None
    heights = [w.y1 - w.y0 for w in words if w.y1 > w.y0]
    tol = max(2.0, 0.6 * (median(heights) if heights else 8.0))
    anchors = [sum(c) / len(c) for c in _cluster([w.xc for w in labels], 30.0)]

    def col_of_label(w: Word) -> int:
        return min(range(len(anchors)), key=lambda i: abs(anchors[i] - w.xc))

    def col_of_reg(w: Word) -> int | None:
        idx = [i for i, a in enumerate(anchors) if a <= w.x0 + 4]
        return idx[-1] if idx else None

    rows_y: list[float] = []
    for y in sorted(w.yc for w in labels + regs):
        if not rows_y or y - rows_y[-1] > tol:
            rows_y.append(y)

    def row_of(w: Word) -> int:
        return min(range(len(rows_y)), key=lambda i: abs(rows_y[i] - w.yc))

    cell_labels: dict[tuple[int, int], list[Word]] = {}
    for w in labels:
        if abs(anchors[col_of_label(w)] - w.xc) <= 30:
            cell_labels.setdefault((row_of(w), col_of_label(w)), []).append(w)
    issues: list[Issue] = []
    out: list[SeatAssignment] = []
    used: set[tuple[int, int]] = set()
    for w in sorted(regs, key=lambda r: (row_of(r), r.x0)):
        r, c = row_of(w), col_of_reg(w)
        sa = SeatAssignment(None, w.text.strip(",").upper(), r, c, x=round(w.x0, 1), y=round(w.yc, 1))
        sug = ocr_suspect(w.text)
        if sug:
            sa.flags.append("ocr_ambiguous")
        if c is None:
            sa.flags.append("seat_label_missing")
        else:
            cell = cell_labels.get((r, c), [])
            if len(cell) == 1:
                sa.seat = int(cell[0].text)
                used.add((r, c))
            elif len(cell) > 1:
                sa.flags.append("seat_label_ambiguous")
            else:
                sa.flags.append("seat_label_missing")
        out.append(sa)
    empty = sorted(int(w.text) for (r, c), ws in cell_labels.items() if (r, c) not in used for w in ws)
    return out, empty, issues


def grid_from_text(lines: list[str]) -> tuple[list[SeatAssignment], list[int]]:
    """Fallback when no word boxes exist: pair each register number with the seat number printed immediately before it.
    Every pair is flagged; a row with more seat numbers than register numbers is flagged as ambiguous."""
    out: list[SeatAssignment] = []
    empty: list[int] = []
    for rno, raw in enumerate(lines):
        toks = squash(raw).split()
        labels = [t for t in toks if _LABEL.match(t)]
        regs = [t for t in toks if _REGISH.match(t) and not _LABEL.match(t) and any(c.isdigit() for c in t)]
        for k, t in enumerate(toks):
            if not (_REGISH.match(t) and not _LABEL.match(t) and any(c.isdigit() for c in t)):
                continue
            sa = SeatAssignment(None, t.upper(), rno, None, flags=["seat_from_text_order"])
            if k > 0 and _LABEL.match(toks[k - 1]):
                sa.seat = int(toks[k - 1])
            else:
                sa.flags.append("seat_label_missing")
            if len(labels) > len(regs) and len(regs) < 4:
                sa.flags.append("seat_cell_ambiguous")
            out.append(sa)
        taken = {a.seat for a in out if a.seat is not None}
        empty += [int(t) for t in labels if int(t) not in taken]
    return out, sorted(set(empty))


# ----------------------------------------------------------------------------- one page / whole document
def parse_seat_page(pg: PageInput) -> SeatSheet:
    text = pg.text or ""
    lines = [squash(l) for l in text.splitlines() if squash(l)]
    issues: list[Issue] = []
    d, s, malformed = parse_exam_header(text)
    if d is None:
        issues.append(Issue("exam_date_unreadable" if malformed else "exam_date_missing", "error",
                            f"Page {pg.index + 1}: examination date could not be read.", page=pg.index))
    if s is None:
        issues.append(Issue("session_missing", "error", f"Page {pg.index + 1}: FN/AN session could not be read.", page=pg.index))
    hall = None
    for ln in lines:
        m = _HALL.search(ln)
        if m:
            hall = norm_hall(re.sub(r"\bName\s+of\s+the.*$", "", m.group(1), flags=re.I))
            break
    if not hall:
        issues.append(Issue("hall_missing", "error", f"Page {pg.index + 1}: 'EXAM HALL' label not found.", page=pg.index))
    hdr_i = next((i for i, l in enumerate(lines) if _HALL.search(l)), -1)
    tbl_i = next((i for i, l in enumerate(lines) if _TABLE_HEAD.match(l)), None)
    headerless = False
    if tbl_i is None and hdr_i >= 0:
        # No recognisable heading line: fall back to the first subject-code line after the hall header. The table is still
        # read, but the page is reported so a human knows the heading was not found.
        first_code = next((i for i in range(hdr_i + 1, len(lines)) if _CODE_LINE.match(lines[i])), None)
        if first_code is not None:
            tbl_i, headerless = first_code - 1, True
            issues.append(Issue("table_header_variant", "warning",
                                f"Page {pg.index + 1}: no 'CODE / TITLE OF THE PAPER' heading line was recognised; the subject table "
                                "was located from its first subject-code line.", page=pg.index, hall=hall))
    if tbl_i is None:
        issues.append(Issue("table_header_missing", "error",
                            f"Page {pg.index + 1}: the 'CODE / TITLE OF THE PAPER' table was not found.", page=pg.index, hall=hall))
        subjects, declared_total = [], None
        grid_lines = lines[hdr_i + 1:]
    else:
        grid_lines = lines[hdr_i + 1:tbl_i]
        subjects, declared_total = parse_subject_table(lines[tbl_i + 1:], pg.index)

    layout, assignments, empty = "none", [], []
    if pg.words:
        zone = _grid_zone(pg.words)
        got = grid_from_words(zone) if zone else None
        if got is not None:
            assignments, empty, extra = got
            issues += extra
            layout = "coordinates"
    if layout == "none":
        assignments, empty = grid_from_text(grid_lines)
        layout = "text"
        if assignments:
            issues.append(Issue("seat_map_from_text_order", "warning",
                                f"{hall or 'Page ' + str(pg.index + 1)}: word positions are unavailable, so seats were paired from text order "
                                "and are unconfirmed. Verify each seat against the PDF.", page=pg.index, hall=hall))
    if pg.method == "ocr":
        issues.append(Issue("ocr_text", "warning", "Read from OCR text; verify every number against the PDF.", page=pg.index, hall=hall))

    for a in assignments:
        if "seat_label_missing" in a.flags or "seat_label_ambiguous" in a.flags:
            issues.append(Issue("seat_unresolved", "error",
                                f"{a.register_number} in {hall}: the seat number could not be read from the cell "
                                f"({'no seat number printed in this cell' if 'seat_label_missing' in a.flags else 'several seat numbers overlap'}); "
                                "no seat was assigned.", page=pg.index, hall=hall, register_number=a.register_number))
        if "ocr_ambiguous" in a.flags:
            issues.append(Issue("ocr_ambiguous_register", "error",
                                f"{a.register_number} in {hall} looks like an OCR-damaged register number; verify it.",
                                page=pg.index, hall=hall, register_number=a.register_number))
    by_subject: dict[str, list[str]] = {}
    for sub in subjects:
        for r in sub.register_numbers:
            by_subject.setdefault(r, []).append(sub.code)
    seen_reg, seen_seat = {}, {}
    for a in assignments:
        codes = by_subject.get(a.register_number, [])
        a.subject_code = codes[0] if len(codes) == 1 else None
        if len(codes) > 1:
            issues.append(Issue("student_in_several_subjects", "error",
                                f"{a.register_number} is listed under {', '.join(codes)} in {hall}.", page=pg.index, hall=hall,
                                register_number=a.register_number))
        if a.register_number in seen_reg:
            issues.append(Issue("duplicate_student_in_hall", "error", f"{a.register_number} appears twice on the seat grid of {hall}.",
                                page=pg.index, hall=hall, register_number=a.register_number))
        seen_reg[a.register_number] = a
        if a.seat is not None:
            if a.seat in seen_seat:
                issues.append(Issue("duplicate_seat", "error",
                                    f"Seat {a.seat} of {hall} is given to {seen_seat[a.seat]} and {a.register_number}.",
                                    page=pg.index, hall=hall, register_number=a.register_number))
            seen_seat[a.seat] = a.register_number
    grid = {a.register_number for a in assignments}
    table = {r for sub in subjects for r in sub.register_numbers}
    if subjects and assignments is not None and grid != table:
        only_grid, only_table = sorted(grid - table), sorted(table - grid)
        issues.append(Issue("grid_table_mismatch", "error",
                            f"{hall}: seat grid and subject table disagree (in grid only: {len(only_grid)}, in table only: {len(only_table)}).",
                            page=pg.index, hall=hall, detail={"grid_only": only_grid[:40], "table_only": only_table[:40]}))
    if declared_total is not None:
        if len(grid) != declared_total or (subjects and sum(len(x.register_numbers) for x in subjects) != declared_total):
            issues.append(Issue("hall_total_mismatch", "error",
                                f"{hall}: printed hall total {declared_total}, seat grid holds {len(grid)}, subject table lists "
                                f"{sum(len(x.register_numbers) for x in subjects)}.", page=pg.index, hall=hall,
                                detail={"declared": declared_total, "grid": len(grid), "table": sum(len(x.register_numbers) for x in subjects)}))
    elif tbl_i is not None:
        issues.append(Issue("hall_total_missing", "warning", f"{hall}: no printed hall 'TOTAL' line was found.", page=pg.index, hall=hall))
    for i in issues:
        i.hall = i.hall or hall
    return SeatSheet(pg.index, hall, d, s, layout, assignments, empty, subjects, declared_total, issues, pg.method)


def _grid_zone(words: list[Word]) -> list[Word]:
    """Words strictly between the 'EXAM HALL ... Superintendent' header line and the 'CODE TITLE' table header."""
    top = bottom = None
    for w in words:
        t = w.text.upper().strip(":")
        if t == "EXAM" and any(o.text.upper().startswith("HALL") and abs(o.yc - w.yc) < 4 for o in words):
            top = w.yc if top is None else min(top, w.yc)
        if t == "CODE" and any(o.text.upper() == "TITLE" and abs(o.yc - w.yc) < 4 for o in words):
            bottom = w.yc
    if top is None or bottom is None or bottom <= top:
        return []
    return [w for w in words if top + 4 < w.yc < bottom - 4]


def parse_seat_pdf(pages: list[PageInput]) -> SeatDocument:
    sheets, issues, sessions = [], [], []
    for pg in pages:
        if not (pg.text or "").strip():
            issues.append(Issue("empty_page", "warning", f"Page {pg.index + 1} has no readable text.", page=pg.index))
            continue
        sh = parse_seat_page(pg)
        sheets.append(sh)
        if sh.exam_date and (sh.exam_date, sh.session) not in sessions:
            sessions.append((sh.exam_date, sh.session))
    seen: dict[tuple, int] = {}
    for sh in sheets:
        k = (sh.exam_date, sh.session, sh.hall)
        if sh.hall and k in seen:
            issues.append(Issue("hall_sheet_repeated", "error",
                                f"{sh.hall} has seating sheets on pages {seen[k] + 1} and {sh.page + 1}; the same hall cannot be seated twice.",
                                page=sh.page, hall=sh.hall))
        seen.setdefault(k, sh.page)
    if not sheets:
        issues.append(Issue("no_sheets", "error", "No hall seating sheets were recognised in this PDF."))
    if len(set(sessions)) > 1:
        issues.append(Issue("several_sessions", "warning", "The PDF contains more than one date/session; each is reconciled separately."))
    return SeatDocument(sheets, issues, sessions, len(pages))
