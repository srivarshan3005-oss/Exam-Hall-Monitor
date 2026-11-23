"""V.S.B. Engineering College (Karur) hall-allotment and seating-allotment PDF parsing and reconciliation.

Pure-Python package: no database, web framework or PDF library is imported here, so every rule can be tested with
plain text / word-coordinate fixtures. The database workflow lives in app/routers/vsb_alloc.py and
app/vsb_alloc/service.py.

Layouts handled (verified against the official PDFs published at https://vsbec.edu.in/controller-of-examination/
on 15 Nov 2026, text layer only - see docs/VSB_ALLOCATION.md for what was and was not verified):
* HALL PDF  ("HALL SEATING FOR THE END SEMESTER EXAMINATIONS"): per programme, per subject "[CODE] TITLE",
  wrapped comma lists of register numbers followed by "MB III <room> <total>", footer "<programme>" + "TOTAL n".
* SEAT PDF  (one page per hall, "EXAM HALL : MB III 02"): a four-column serpentine seat grid (seat, register) plus a
  "CODE / TITLE / TOTAL / REGISTER NUMBERS" table with compressed lists such as "996701510092 - 093, 095 - 105".

Rule: nothing is guessed. An unreadable or contradictory value becomes an Issue and an empty field.
"""
