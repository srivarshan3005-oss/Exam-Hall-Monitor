"""Review report for hall-label variant records (the records the importer flags `hall_label_variant`).

It reads only the operator-supplied data (allotments.json and allocation_provenance.json, not distributed in the public package), uses the importer's own alternate-spelling
rule, and writes one CSV row per flagged record with the evidence an administrator needs to check it against the
official PDFs. It never changes the database and never decides which spelling is correct.

    python scripts/report_hall_label_variants.py            (writes ../docs/hall_label_variant_review.csv and prints a summary)
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.vsb_alloc.original_import import _hall_alternative  # noqa: E402  (single source of truth for the rule)

DATA = BACKEND / "data" / "original_portal"
OUT = BACKEND.parent / "docs" / "hall_label_variant_review.csv"
EVIDENCE = ("Official hall master or invigilation sheet showing whether '{a}' and '{b}' are the same physical room "
            "(room code, block, seat count); the page header of the official hall-list PDF page {hp} and seat-sheet page "
            "{sp} naming the room; confirmation that seat {seat} exists in the room named on the record.")


def main() -> int:
    src = json.loads((DATA / "source" / "allotments.json").read_text(encoding="utf-8"))
    prov = json.loads((DATA / "allocation_provenance.json").read_text(encoding="utf-8"))["records"]
    rows = [dict(r, register_number=reg) for reg, items in src.items() for r in items]
    halls_by_session = defaultdict(set)
    for r in rows:
        halls_by_session[(r["exam_date"], r["session"])].add(r["hall_number"])
    seat_owner = {}
    for r in rows:
        seat_owner[(r["exam_date"], r["session"], r["hall_number"], str(r["seat_number"]))] = r["register_number"]

    flagged = []
    for r in rows:
        alt = _hall_alternative(r["hall_number"])
        if alt and alt in halls_by_session[(r["exam_date"], r["session"])]:
            flagged.append((r, alt))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ["register_number", "exam_date", "session", "subject_code", "seat_number", "hall_recorded", "alternate_spelling",
              "same_seat_taken_under_alternate_by", "hall_list_pdf", "hall_list_pdf_page", "hall_list_label", "seat_sheet_pdf",
              "seat_sheet_pdf_page", "seat_sheet_label", "pdfs_agree", "verification_status", "evidence_required"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, alt in flagged:
            key = f"{r['register_number']}|{r['exam_date']}|{r['session']}"
            p = prov.get(key, {})
            other = seat_owner.get((r["exam_date"], r["session"], alt, str(r["seat_number"])), "")
            hp, sp = p.get("hall_pdf_page"), p.get("seat_pdf_page")
            w.writerow({"register_number": r["register_number"], "exam_date": r["exam_date"], "session": r["session"],
                        "subject_code": r.get("subject_code") or "", "seat_number": r["seat_number"],
                        "hall_recorded": r["hall_number"], "alternate_spelling": alt,
                        "same_seat_taken_under_alternate_by": other,
                        "hall_list_pdf": p.get("hall_pdf_url", ""), "hall_list_pdf_page": hp if hp is not None else "",
                        "hall_list_label": p.get("hall_pdf_label", ""), "seat_sheet_pdf": p.get("seat_pdf_url", ""),
                        "seat_sheet_pdf_page": sp if sp is not None else "", "seat_sheet_label": p.get("seat_pdf_label", ""),
                        "pdfs_agree": "yes" if p.get("hall_pdf_label") == p.get("seat_pdf_label") else "no",
                        "verification_status": "UNVERIFIED (no official PDF or hall master checked)",
                        "evidence_required": EVIDENCE.format(a=r["hall_number"], b=alt, hp=hp, sp=sp, seat=r["seat_number"])})

    # ---- summary (printed; copied into docs/HALL_LABEL_VARIANT_REVIEW.md)
    per_session = Counter((r["exam_date"], r["session"]) for r, _ in flagged)
    pairs = Counter(tuple(sorted([r["hall_number"], alt])) for r, alt in flagged)
    shared = sum(1 for r, alt in flagged if (r["exam_date"], r["session"], alt, str(r["seat_number"])) in seat_owner)
    disagree = sum(1 for r, _ in flagged if prov.get(f"{r['register_number']}|{r['exam_date']}|{r['session']}", {}).get("hall_pdf_label")
                   != prov.get(f"{r['register_number']}|{r['exam_date']}|{r['session']}", {}).get("seat_pdf_label"))
    print(f"flagged records: {len(flagged)}")
    for (d, s), n in sorted(per_session.items()):
        print(f"  {d} {s}: {n}")
    print(f"spelling pairs: {len(pairs)}")
    for pair, n in sorted(pairs.items(), key=lambda x: -x[1]):
        print(f"  {pair[0]} / {pair[1]}: {n}")
    print(f"same seat number already taken under the alternate spelling by another register in the same session: {shared}")
    print(f"no such seat conflict: {len(flagged) - shared}")
    print(f"records where the hall-list PDF and seat-sheet PDF print different labels: {disagree}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
