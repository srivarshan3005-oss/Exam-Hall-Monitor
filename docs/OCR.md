# Document processing, OCR and timetable import (Phase 3)

## Install
`pip install -r backend/requirements.txt` installs PyMuPDF, pytesseract and Pillow. The **Tesseract binary** is separate:
* Windows: install Tesseract (e.g. the UB Mannheim build) and add it to PATH. Add language packs you need (e.g. `tam`).
* Ubuntu/Debian: `sudo apt install tesseract-ocr` (+ `tesseract-ocr-tam` etc.).
* Docker: the supplied `backend/Dockerfile` installs the `tesseract-ocr` package (English data). Add `tesseract-ocr-<lang>` packages to the image for other languages.
Without Tesseract, digital PDFs still work; scanned pages are reported as "OCR unavailable" (never silently skipped).
`GET /api/admin/doc-processing/capabilities` and the workspace header show whether OCR is available.

## How extraction works
1. **Text layer first** (PyMuPDF). Tables with ruled cells are read as tables (header-mapped columns: date, session/time, code, name, department, year, semester).
2. **OCR fallback** for pages with < 40 characters of text (300 DPI render, grayscale/autocontrast/sharpen, orientation fix, per-word confidence). `force_ocr` re-reads every page.
3. **Line parser** for free-text and OCR layouts (one row per line; dates, times, FN/AN, subject codes).
4. **Header**: examination name, academic year, department, semester, instruction lines, count of 12-digit register numbers (kept private, never imported).

Nothing is invented: unreadable/missing fields stay empty and are flagged. Dates carried down from a blank/merged cell, assumed DD/MM order, inferred AM/PM, session-only rows (times not printed), and all OCR rows are flagged and scored lower; rows below 75 % confidence are highlighted.
Month/year words such as `DEC2026` are never treated as subject codes.

## Known limitations
* OCR of tables whose cells wrap onto several lines may split a row; such rows show as incomplete and need manual correction.
* Handwriting, heavy skew, very low DPI scans and non-Latin scripts without the language pack are unreliable. Always compare with the preview.
* Layouts with several timetables per page, or dates written in words in another language, are not recognised.
* Sessions without printed times (only FN/AN) are not converted to times; an administrator must enter them.

## Review → import
Extract → review/correct (admin) → approve rows → approve document → **import preview** → confirm. Imports create *draft* examinations, never publish, never change existing exams unless "update existing" is ticked for that row, and are blocked when the data changed after the preview (signature check).
