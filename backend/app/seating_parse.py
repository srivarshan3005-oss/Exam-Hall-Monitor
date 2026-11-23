"""Seating-allotment page text -> candidate rows. Pure functions (no database).

Principle: never guess. A hall comes only from a 'Hall/Room/Venue' label; a seat only from an explicit
'Seat' label or, as a weaker signal, the single bare number left on the line. Anything else stays empty
and is flagged for a human. OCR text is always flagged and scored lower.
"""
import re
from dataclasses import dataclass, field

REG = re.compile(r"(?<!\d)\d{12}(?!\d)")
HALL_LABEL = re.compile(r"\b(?:hall|room|venue)\b\s*(?:no\.?|number|name|code)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{0,24}(?: [A-Za-z0-9\-]{1,10})?)", re.I)
SEAT_LABEL = re.compile(r"\bseat\b\s*(?:no\.?|number)?\s*[:\-]?\s*([A-Za-z]?\d{1,4}[A-Za-z]?)\b", re.I)


@dataclass
class Row:
    row_no: int
    page_index: int
    register_number: str
    hall: str | None
    seat: str | None
    raw_text: str
    source: str
    confidence: float
    flags: list[str] = field(default_factory=list)


def _clean_hall(v: str) -> str:
    v = re.split(r"\s{2,}|\bseat\b|\bregister\b", v, flags=re.I)[0]
    return re.sub(r"\s+", " ", v).strip(" -:").upper()[:40]


def parse_pages(pages: list[dict]) -> list[Row]:
    """pages: [{'index': int, 'text': str, 'method': 'text_layer'|'ocr'|..., 'confidence': float|None}]"""
    rows: list[Row] = []
    for pg in pages:
        ocr = (pg.get("method") or "").startswith("ocr")
        hall_ctx = None
        for line in (pg.get("text") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            regs = REG.findall(line)
            if not regs:
                m = HALL_LABEL.search(line)           # header line such as "Hall: A101"
                if m:
                    hall_ctx = _clean_hall(m.group(1)) or hall_ctx
                continue
            flags, hall, seat, conf = [], None, None, 0.95
            m = HALL_LABEL.search(REG.sub(" ", line))
            if m:
                hall = _clean_hall(m.group(1))
            elif hall_ctx:
                hall = hall_ctx
            rest = REG.sub(" ", line)
            if len(regs) > 1:
                flags.append("several_register_numbers_on_one_line")
            else:
                sm = SEAT_LABEL.search(rest)
                if sm:
                    seat = sm.group(1).upper()
                else:
                    stripped = HALL_LABEL.sub(" ", rest)
                    nums = re.findall(r"(?<![\w.])\d{1,3}(?![\w.])", stripped)
                    if len(nums) == 1:
                        seat, conf = nums[0], 0.75
                        flags.append("seat_taken_from_unlabelled_number")
                    elif len(nums) > 1:
                        flags.append("ambiguous_seat")
            if not hall:
                flags.append("hall_not_found")
            if not seat:
                flags.append("seat_not_found")
            if ocr:
                flags.append("ocr_text")
                conf = min(conf, 0.6) * (0.8 if (pg.get("confidence") or 0) < 70 else 1.0)
            if "hall_not_found" in flags or "seat_not_found" in flags or len(regs) > 1:
                conf = min(conf, 0.3)
            for r in regs:
                rows.append(Row(len(rows) + 1, pg["index"], r, hall, seat if len(regs) == 1 else None, line[:300],
                                "ocr" if ocr else "text", round(conf, 2), list(flags)))
    return rows


def find_internal_conflicts(rows: list[dict]) -> dict[int, list[str]]:
    """rows: dicts with id, register_number, hall, seat (only non-rejected rows).
    Returns {row id: [problems]} for duplicate students and clashing seats inside the document."""
    out: dict[int, list[str]] = {}
    by_reg, by_seat = {}, {}
    for r in rows:
        by_reg.setdefault(r["register_number"], []).append(r)
        if r["hall"] and r["seat"]:
            by_seat.setdefault((r["hall"].upper(), r["seat"].upper()), []).append(r)
    for reg, items in by_reg.items():
        if len(items) > 1:
            same = len({((i["hall"] or "").upper(), (i["seat"] or "").upper()) for i in items}) == 1
            for i in items:
                out.setdefault(i["id"], []).append("duplicate student (same place repeated)" if same
                                                    else "conflicting allocations for the same student")
    for (h, s), items in by_seat.items():
        if len({i["register_number"] for i in items}) > 1:
            for i in items:
                out.setdefault(i["id"], []).append(f"seat {h}/{s} given to several students")
    return out
