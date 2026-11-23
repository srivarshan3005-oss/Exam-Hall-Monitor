"""Phase 3 extraction: PDF text layer -> OCR fallback -> conservative timetable parsing.

Rules baked in:
* Nothing is invented. A value that is not printed (or cannot be read) stays None and is flagged.
* Every entry carries `confidence`, `flags` and `uncertain_fields` so a human can review it.
* Inherited values (e.g. a date carried down from a merged cell) are flagged, never silent.
* OCR is a fallback for pages without a usable text layer; OCR text is always lower confidence.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date

from .regno import normalize_register_number

EXTRACTOR_VERSION = "p3-fitz-tess-v1"
MIN_TEXT_CHARS = 40          # below this a page is treated as image-only
MAX_PAGES = 300
OCR_DPI = 300
LOW_CONF = 0.75              # entry/field confidence below this is highlighted
LANG_RE = re.compile(r"^[A-Za-z_]{2,12}(\+[A-Za-z_]{2,12}){0,3}$")

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ----------------------------------------------------------------------------- data classes
@dataclass
class PageText:
    index: int
    text: str
    method: str                      # text_layer | ocr | empty
    ocr_confidence: float | None = None
    width: float | None = None
    height: float | None = None
    tables: list[list[list[str]]] = field(default_factory=list)   # digital tables (rows of cells)
    warning: str | None = None


@dataclass
class Entry:
    row_no: int
    page_index: int
    exam_date: date | None = None
    start_time: str | None = None
    end_time: str | None = None
    session: str | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    department: str | None = None
    year: int | None = None
    semester: int | None = None
    raw_text: str = ""
    source: str = "text_layer"       # text_layer | table | ocr
    confidence: float = 0.9
    flags: list[str] = field(default_factory=list)
    uncertain_fields: list[str] = field(default_factory=list)


@dataclass
class Header:
    exam_name: str | None = None
    session_label: str | None = None
    academic_year: str | None = None
    department: str | None = None
    semester: int | None = None
    instructions: list[str] = field(default_factory=list)
    register_numbers: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass
class Parsed:
    header: Header
    entries: list[Entry]
    issues: list[str]


# ----------------------------------------------------------------------------- PDF reading
def available_ocr_languages() -> list[str]:
    try:
        import pytesseract
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def ocr_available() -> bool:
    try:
        import fitz  # noqa: F401
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _preprocess(img):
    """Grayscale + autocontrast + mild sharpen; upscale small renders. Never alters content."""
    from PIL import ImageFilter, ImageOps
    g = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
    if min(g.size) < 1400:
        g = g.resize((g.width * 2, g.height * 2))
    return g.filter(ImageFilter.SHARPEN)


def ocr_page(page, lang: str = "eng", timeout: int = 90) -> tuple[str, float | None]:
    """OCR one fitz page. Returns (text, mean word confidence 0..1 or None)."""
    import fitz
    import pytesseract
    from PIL import Image
    pix = page.get_pixmap(matrix=fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72), alpha=False)
    img = _preprocess(Image.open(io.BytesIO(pix.tobytes("png"))))
    try:  # fix 90/180/270 degree scans when Tesseract's orientation model is installed
        osd = pytesseract.image_to_osd(img, config="--psm 0", timeout=timeout)
        m = re.search(r"Rotate:\s+(\d+)", osd)
        if m and int(m.group(1)) in (90, 180, 270):
            img = img.rotate(-int(m.group(1)), expand=True)
    except Exception:
        pass
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT,
                                     timeout=timeout)
    lines: dict[tuple, list[str]] = {}
    confs = []
    for i, w in enumerate(data["text"]):
        w = (w or "").strip()
        if not w:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(w)
        try:
            c = float(data["conf"][i])
            if c >= 0:
                confs.append(c)
        except (TypeError, ValueError):
            pass
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    return text, (round(sum(confs) / len(confs) / 100, 3) if confs else None)


def _page_tables(page) -> list[list[list[str]]]:
    out = []
    try:
        for t in page.find_tables().tables:
            rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                out.append(rows)
    except Exception:
        pass
    return out


def read_pdf(path: str, lang: str = "eng", force_ocr: bool = False, allow_ocr: bool = True) -> list[PageText]:
    """Text layer first; OCR for image-only pages (or all pages with force_ocr)."""
    import fitz
    if not LANG_RE.match(lang):
        raise ValueError("Invalid OCR language code")
    doc = fitz.open(path)
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        if len(doc) == 0:
            raise ValueError("The PDF has no pages")
        if len(doc) > MAX_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PAGES} page processing limit")
        can_ocr = allow_ocr and ocr_available()
        pages: list[PageText] = []
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            pt = PageText(i, text, "text_layer" if text.strip() else "empty",
                          width=float(page.rect.width), height=float(page.rect.height))
            if len(text.strip()) >= MIN_TEXT_CHARS and not force_ocr:
                pt.tables = _page_tables(page)
            else:
                if can_ocr:
                    try:
                        otext, conf = ocr_page(page, lang)
                        if otext.strip():
                            pt.text, pt.method, pt.ocr_confidence = otext, "ocr", conf
                            if conf is not None and conf < 0.6:
                                pt.warning = "Poor scan quality: OCR confidence is low; verify every value"
                        else:
                            pt.warning = "OCR found no text on this page"
                    except Exception as exc:  # pragma: no cover - depends on tesseract runtime
                        pt.warning = f"OCR failed: {str(exc)[:120]}"
                else:
                    pt.warning = "No text layer and OCR is unavailable"
            pages.append(pt)
        return pages
    finally:
        doc.close()


def render_page_png(path: str, page_index: int, dpi: int = 110) -> bytes:
    import fitz
    doc = fitz.open(path)
    try:
        if not 0 <= page_index < len(doc):
            raise IndexError("page")
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


# ----------------------------------------------------------------------------- field parsers
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})(?!\d)")
DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_TXT = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-.,]*" + _MON + r"[a-z]*[\s\-.,]*(\d{4}|\d{2})(?!\d)", re.I)
DATE_TXT2 = re.compile(_MON + r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)
TIME_T = r"(\d{1,2})\s*[:.]\s*(\d{2})\s*([ap]\.?m\.?)?"
TIME_RANGE = re.compile(TIME_T + r"\s*(?:-|–|—|to|TO)\s*" + TIME_T, re.I)
CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5}\s?\d{3,5}[A-Z]?)(?![A-Za-z0-9])")
SESSION_RE = re.compile(r"(?<![A-Za-z])(FN|AN|F\.N\.?|A\.N\.?|forenoon|afternoon)(?![A-Za-z])", re.I)
DAY_RE = re.compile(r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\b\.?", re.I)


_NOT_CODE = {"YEAR", "SEM", "SEMESTER", "DATE", "PAGE", "NO", "AY", "SESSION", "BATCH", "REGULATION", "REG"} | \
    {m.upper() for m in MONTHS} | {"JUNE", "JULY", "SEPT", "NOV", "DEC"}


def codes_in(text: str) -> list[re.Match]:
    """Subject-code candidates; month/year words such as DEC2026 or YEAR2026 are not codes."""
    out = []
    for m in CODE_RE.finditer(text.upper()):
        letters = re.match(r"[A-Z]+", m[1])[0]
        digits = re.sub(r"\D", "", m[1])
        if letters in _NOT_CODE and re.fullmatch(r"(19|20)\d\d|\d{1,2}", digits):
            continue
        out.append(m)
    return out


def _year4(y: str) -> int:
    return int(y) if len(y) == 4 else 2000 + int(y)


def find_dates(line: str, dmy: bool = True) -> list[tuple[date, str, bool, tuple[int, int]]]:
    """-> [(date, matched_text, ambiguous_dm, span)]. Invalid calendar dates are skipped."""
    out = []
    for m in DATE_ISO.finditer(line):
        try:
            out.append((date(int(m[1]), int(m[2]), int(m[3])), m[0], False, m.span()))
        except ValueError:
            pass
    for m in DATE_NUM.finditer(line):
        a, b, y = int(m[1]), int(m[2]), _year4(m[3])
        amb = a <= 12 and b <= 12 and a != b
        d, mth = (a, b) if dmy else (b, a)
        if a > 12:
            d, mth = a, b
        elif b > 12:
            d, mth = b, a
        try:
            out.append((date(y, mth, d), m[0], amb, m.span()))
        except ValueError:
            pass
    for m in DATE_TXT.finditer(line):
        try:
            out.append((date(_year4(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), m[0], False, m.span()))
        except ValueError:
            pass
    for m in DATE_TXT2.finditer(line):
        try:
            out.append((date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), m[0], False, m.span()))
        except ValueError:
            pass
    out.sort(key=lambda x: x[3][0])
    dedup, last_end = [], -1
    for item in out:  # drop overlapping matches (e.g. numeric inside ISO)
        if item[3][0] >= last_end:
            dedup.append(item); last_end = item[3][1]
    return dedup


def _to24(h: str, mi: str, ap: str | None) -> str | None:
    h, mi = int(h), int(mi)
    if mi > 59:
        return None
    if ap:
        ap = ap.lower().replace(".", "")
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if ap == "pm" else 0)
    elif h > 23:
        return None
    return f"{h:02d}:{mi:02d}"


def find_time_range(line: str) -> tuple[str | None, str | None, str, tuple[int, int], bool] | None:
    """-> (start, end, text, span, meridiem_inferred). A bare '9.30 - 12.30' stays 24-hour as printed."""
    m = TIME_RANGE.search(line)
    if not m:
        return None
    ap1, ap2 = m[3], m[6]
    inferred = False
    if ap2 and not ap1:  # "9.30 - 12.30 pm": only infer the start's meridiem if the result is consistent
        s24 = _to24(m[1], m[2], ap2)
        e24 = _to24(m[4], m[5], ap2)
        if s24 and e24 and s24 < e24:
            ap1, inferred = ap2, True
        else:
            ap1 = "am"; inferred = True
    start, end = _to24(m[1], m[2], ap1), _to24(m[4], m[5], ap2)
    return start, end, m[0], m.span(), inferred


def parse_session(text: str) -> str | None:
    m = SESSION_RE.search(text)
    if not m:
        return None
    t = m[1].lower().replace(".", "")
    return "FN" if t in ("fn", "forenoon") else "AN"


def clean_name(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -–—|:,;.\t")
    return s[:200]


# ----------------------------------------------------------------------------- header parsing
EXAM_NAME_RE = re.compile(r"(?i)\b(end[\s-]*semester|mid[\s-]*semester|semester|model|internal|university|"
                          r"supplementary|arrear|practical|continuous assessment|cat[\s-]?\d)\b.*\b(exam|examination|examinations|test)s?\b"
                          r"|\b(exam|examination)s?\b.*\b(nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct)[a-z]*[\s/,-]*(20\d\d)")
AY_RE = re.compile(r"(?i)(?:academic\s+year|a\.?y\.?)\s*[:\-]?\s*(20\d\d\s*[-–/]\s*(?:20)?\d\d)|\b(20\d\d\s*[-–]\s*(?:20)?\d\d)\b")
DEPT_RE = re.compile(r"(?i)\bdepartment\s+of\s+([A-Za-z&,\s]{3,70}?)(?=\s{2,}|\n|$|[,;(]|\s+(?:semester|year|sem)\b)|\bdept\.?\s+of\s+([A-Za-z&\s]{3,60})")
SEM_RE = re.compile(r"(?i)\b(?:semester|sem)\s*[:\-]?\s*([IVX]{1,4}|\d{1,2})\b|\b(\d{1,2})(?:st|nd|rd|th)\s+semester\b")
YEAR_RE = re.compile(r"(?i)\b([IVX]{1,3}|\d)\s*(?:st|nd|rd|th)?\s*year\b|\byear\s*[:\-]?\s*([IVX]{1,3}|\d)\b")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
INSTR_HEAD = re.compile(r"(?i)^\s*(instructions?|note|notes|important|general instructions?|guidelines)\b\s*[:\-]?\s*(.*)$")
INSTR_LINE = re.compile(r"(?i)^\s*(?:\d{1,2}[.)]|[•\-*]|note\s*[:\-])\s*(.{8,300})$")


def _num(token: str | None, maxv: int) -> int | None:
    if not token:
        return None
    t = token.upper()
    v = ROMAN.get(t) or (int(t) if t.isdigit() else None)
    return v if v and 1 <= v <= maxv else None


def parse_header(lines: list[str]) -> Header:
    h = Header()
    head = lines[:25]
    for ln in head:
        if not h.exam_name and EXAM_NAME_RE.search(ln) and len(ln) < 160 and not find_time_range(ln):
            h.exam_name = clean_name(ln)
        if not h.academic_year:
            m = AY_RE.search(ln)
            if m:
                h.academic_year = re.sub(r"\s+", "", (m[1] or m[2])).replace("–", "-").replace("/", "-")
        if not h.department:
            m = DEPT_RE.search(ln)
            if m:
                h.department = clean_name(m[1] or m[2])
        if h.semester is None:
            m = SEM_RE.search(ln)
            if m:
                h.semester = _num(m[1] or m[2], 12)
    for ln in head:
        s = parse_session(ln) if re.search(r"(?i)\bsession\b", ln) else None
        if s:
            h.session_label = s
            break
    # instructions: block after a heading, or note-like lines anywhere
    i = 0
    while i < len(lines):
        m = INSTR_HEAD.match(lines[i])
        if m and not CODE_RE.search(lines[i]) and not find_dates(lines[i]):
            if m[2] and len(m[2]) >= 8:
                h.instructions.append(clean_name(m[2]))
            j = i + 1
            while j < len(lines) and j < i + 15:
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                mm = INSTR_LINE.match(nxt)
                if mm and not (find_dates(nxt) and CODE_RE.search(nxt)):
                    h.instructions.append(clean_name(mm[1]))
                elif len(nxt) > 25 and not CODE_RE.search(nxt) and not find_dates(nxt):
                    h.instructions.append(clean_name(nxt))
                else:
                    break
                j += 1
            i = j
        else:
            i += 1
    seen, uniq = set(), []
    for x in h.instructions:
        if x and x.lower() not in seen:
            seen.add(x.lower()); uniq.append(x)
    h.instructions = uniq[:30]
    return h


def find_register_numbers(text: str) -> list[str]:
    """12-digit numbers only (the standard format); other id shapes are not guessed from free text."""
    seen, out = set(), []
    for m in re.finditer(r"(?<!\d)\d{12}(?!\d)", text):
        v = normalize_register_number(m[0])
        if v not in seen:
            seen.add(v); out.append(v)
    return out[:5000]


# ----------------------------------------------------------------------------- table parsing
_HDR = {
    "date": re.compile(r"(?i)\b(date|day\s*&?\s*date|exam\s*date)\b"),
    "time": re.compile(r"(?i)\b(time|timing|timings|hours)\b"),
    "session": re.compile(r"(?i)\b(session|fn|an|shift)\b"),
    "code": re.compile(r"(?i)\b(sub(?:ject)?\.?\s*code|course\s*code|paper\s*code|code)\b"),
    "name": re.compile(r"(?i)\b(sub(?:ject)?\.?\s*(?:name|title)|course\s*(?:name|title)|paper|title|subject|course)\b"),
    "dept": re.compile(r"(?i)\b(dept|department|branch|programme|program)\b"),
    "year": re.compile(r"(?i)\byear\b"),
    "sem": re.compile(r"(?i)\bsem(?:ester)?\b"),
}


def _map_header(row: list[str]) -> dict[str, int] | None:
    colmap: dict[str, int] = {}
    for idx, cell in enumerate(row):
        c = cell.strip()
        if not c:
            continue
        for key in ("code", "date", "time", "session", "dept", "year", "sem", "name"):
            if key not in colmap and _HDR[key].search(c):
                colmap[key] = idx
                break
    return colmap if ("code" in colmap or "name" in colmap) and ("date" in colmap or "time" in colmap or "session" in colmap) else None


def _entry_from_cells(cells: dict[str, str], row_no: int, page: int, dmy: bool, ctx: dict) -> Entry | None:
    joined = " | ".join(v for v in cells.values() if v)
    if not joined.strip():
        return None
    e = Entry(row_no=row_no, page_index=page, raw_text=joined[:500], source="table", confidence=0.95)
    dstr = cells.get("date", "")
    ds = find_dates(dstr, dmy)
    if ds:
        e.exam_date = ds[0][0]
        ctx["last_date"] = (e.exam_date, dstr)
        if ds[0][2] and not ctx.get("dmy_known"):
            e.flags.append("ambiguous_date_format"); e.uncertain_fields.append("exam_date")
    elif dstr.strip():
        e.flags.append("unreadable_date"); e.uncertain_fields.append("exam_date")
    elif ctx.get("last_date"):  # merged / blank cell: inherited, flagged
        e.exam_date = ctx["last_date"][0]
        e.flags.append("date_inherited_from_previous_row"); e.uncertain_fields.append("exam_date")
    tstr = cells.get("time", "") or cells.get("session", "")
    tr = find_time_range(tstr)
    if tr:
        e.start_time, e.end_time = tr[0], tr[1]
        if tr[4]:
            e.flags.append("meridiem_inferred"); e.uncertain_fields += ["start_time"]
        if not (tr[0] and tr[1]):
            e.flags.append("invalid_time"); e.uncertain_fields += ["start_time", "end_time"]
    e.session = parse_session(cells.get("session", "")) or parse_session(tstr)
    code = cells.get("code", "")
    cl = codes_in(code) or codes_in(joined)
    m = cl[0] if cl else None
    if m:
        e.subject_code = re.sub(r"\s+", "", m[1])
    elif code.strip():
        e.subject_code = re.sub(r"\s+", "", code.upper())[:30]
        e.flags.append("unusual_subject_code"); e.uncertain_fields.append("subject_code")
    else:
        e.flags.append("missing_subject_code"); e.uncertain_fields.append("subject_code")
    e.subject_name = clean_name(cells.get("name", "")) or None
    e.department = clean_name(cells.get("dept", "")) or None
    e.year = _num(re.sub(r"\D*(\d|[IVX]+).*", r"\1", cells.get("year", "").strip().upper()) or None, 6) if cells.get("year") else None
    e.semester = _num(cells.get("sem", "").strip().upper() or None, 12) if cells.get("sem") else None
    return e


def parse_tables(tables: list[list[list[str]]], page: int, dmy: bool, ctx: dict, start_row: int) -> list[Entry]:
    out: list[Entry] = []
    row_no = start_row
    for rows in tables:
        colmap = None
        for r in rows:
            hm = _map_header(r)
            if hm:
                colmap = hm
                continue
            if not colmap:
                continue
            cells = {k: (r[i] if i < len(r) else "") for k, i in colmap.items()}
            e = _entry_from_cells(cells, row_no + 1, page, dmy, ctx)
            if e and (e.subject_code or e.subject_name) :
                row_no += 1
                out.append(e)
    return out


# ----------------------------------------------------------------------------- line parsing
def parse_lines(lines: list[str], page: int, dmy: bool, ctx: dict, start_row: int, ocr: bool) -> list[Entry]:
    """Free-text layouts: one timetable row per line (dates may be given once above several rows)."""
    out: list[Entry] = []
    row_no = start_row
    for ln in lines:
        raw = ln.strip()
        if len(raw) < 6:
            continue
        up = raw.upper()
        cl = codes_in(raw)
        code = cl[0] if cl else None
        ds = find_dates(raw, dmy)
        if not code:
            if ds and not find_time_range(raw) and not parse_session(raw):  # date-only line: applies to following rows
                ctx["pending_date"] = (ds[0][0], ds[0][2])
                continue
            if not (ds and (find_time_range(raw) or parse_session(raw))):
                continue
            # a dated, timed row whose subject code cannot be read: keep it, flagged, never guess the code
        e = Entry(row_no=row_no + 1, page_index=page, raw_text=raw[:500], source="ocr" if ocr else "text_layer",
                  confidence=0.9 if not ocr else 0.72)
        rest = raw
        if ds:
            e.exam_date = ds[0][0]
            ctx["pending_date"] = (ds[0][0], ds[0][2])
            if ds[0][2] and not ctx.get("dmy_known"):
                e.flags.append("ambiguous_date_format"); e.uncertain_fields.append("exam_date")
            rest = rest.replace(ds[0][1], " ", 1)
        elif ctx.get("pending_date"):
            e.exam_date = ctx["pending_date"][0]
            e.flags.append("date_inherited_from_previous_row"); e.uncertain_fields.append("exam_date")
        tr = find_time_range(rest)
        if tr:
            e.start_time, e.end_time = tr[0], tr[1]
            if tr[4]:
                e.flags.append("meridiem_inferred"); e.uncertain_fields.append("start_time")
            if not (tr[0] and tr[1]):
                e.flags.append("invalid_time"); e.uncertain_fields += ["start_time", "end_time"]
            rest = rest.replace(tr[2], " ", 1)
        e.session = parse_session(rest)
        rest = SESSION_RE.sub(" ", rest)
        rest = DAY_RE.sub(" ", rest)
        if code:
            e.subject_code = re.sub(r"\s+", "", code[1])
            cm = re.search(re.escape(code[1]).replace(r"\ ", r"\s?"), rest, re.I)
            after = rest[cm.end():] if cm else rest
            before = rest[:cm.start()] if cm else ""
            name = clean_name(after) or clean_name(before)
        else:
            e.flags.append("missing_subject_code"); e.uncertain_fields.append("subject_code")
            name = clean_name(rest)
        e.subject_name = name if len(re.sub(r"[^A-Za-z]", "", name)) >= 3 else None
        out.append(e)
        row_no += 1
    return out


# ----------------------------------------------------------------------------- orchestration
def _score(e: Entry, page: PageText, dmy_known: bool) -> None:
    c = e.confidence
    if page.method == "ocr":
        c = min(c, 0.55 + 0.4 * (page.ocr_confidence or 0.5))
    if e.exam_date is None:
        e.flags.append("missing_date"); e.uncertain_fields.append("exam_date"); c -= 0.25
    if e.start_time is None or e.end_time is None:
        e.flags.append("missing_time" if not e.session else "times_not_printed_session_only")
        e.uncertain_fields += ["start_time", "end_time"]; c -= 0.15
    elif e.end_time <= e.start_time:
        e.flags.append("end_before_start"); e.uncertain_fields += ["start_time", "end_time"]; c -= 0.3
    if not e.subject_name:
        e.flags.append("missing_subject_name"); e.uncertain_fields.append("subject_name"); c -= 0.1
    if "missing_subject_code" in e.flags:
        c -= 0.25
    if "date_inherited_from_previous_row" in e.flags:
        c -= 0.12
    if "ambiguous_date_format" in e.flags:
        c -= 0.15
    if e.exam_date and not (2000 <= e.exam_date.year <= 2100):
        e.flags.append("implausible_year"); e.uncertain_fields.append("exam_date"); c -= 0.3
    if page.method == "ocr":
        e.flags.append("ocr_source")
    e.confidence = round(max(0.05, min(0.99, c)), 2)
    e.flags = sorted(set(e.flags))
    e.uncertain_fields = sorted(set(e.uncertain_fields))


def detect_dmy(texts: list[str]) -> tuple[bool, bool]:
    """-> (day_first, known). Known when some date in the document can only be read one way."""
    dm = md = 0
    for t in texts:
        for m in DATE_NUM.finditer(t):
            a, b = int(m[1]), int(m[2])
            if a > 12 >= b:
                dm += 1
            elif b > 12 >= a:
                md += 1
    if dm or md:
        return (dm >= md), True
    return True, False


def parse_timetable(pages: list[PageText]) -> Parsed:
    issues: list[str] = []
    alltext = [p.text for p in pages]
    dmy, known = detect_dmy(alltext)
    lines_all = [ln for t in alltext for ln in t.splitlines() if ln.strip()]
    header = parse_header(lines_all)
    header.register_numbers = find_register_numbers("\n".join(alltext))
    if not known and any(DATE_NUM.search(t) for t in alltext):
        header.flags.append("date_format_assumed_day_first")
        issues.append("Dates like 05/06/2026 are ambiguous; day-first (DD/MM) was assumed. Verify dates.")
    entries: list[Entry] = []
    ctx: dict = {"dmy_known": known}
    for p in pages:
        if p.method == "empty":
            issues.append(f"Page {p.index + 1}: no readable text ({p.warning or 'blank'})")
            continue
        if p.warning:
            issues.append(f"Page {p.index + 1}: {p.warning}")
        got = parse_tables(p.tables, p.index, dmy, ctx, len(entries)) if p.tables else []
        if not got:
            got = parse_lines(p.text.splitlines(), p.index, dmy, ctx, len(entries), p.method == "ocr")
        for e in got:
            _score(e, p, known)
        entries.extend(got)
    for n, e in enumerate(entries, 1):
        e.row_no = n
    if not entries:
        issues.append("No timetable rows were recognised. The document may not be a timetable, or its layout "
                      "is unsupported; nothing was imported. Add entries manually in the review workspace.")
    if header.department is None:
        header.flags.append("department_not_found")
    if header.exam_name is None:
        header.flags.append("exam_name_not_found")
    if header.academic_year is None:
        header.flags.append("academic_year_not_found")
    return Parsed(header, entries, issues)


def normalise_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
