# Student portal and operations overview (v0.8.0)

## Public student portal — `/portal/`
Dark academic theme modelled on the reference Exam Allotment Portal: live-notices banner, register-number search,
session-coloured examination cards (FN blue, AN amber), hall/seat grid, seating chart, print slip and footer.
Files: `backend/app/static/portal/index.html`, `portal.css`, `portal.js` (no inline script/style handlers: the
Content-Security-Policy is `default-src 'self'`, which blocks them).

Behaviour
* Opens **empty**: no example number, no prefilled value, no automatic search, no modal or popup.
* `/portal/?reg=REGISTER_NUMBER` is the only thing that prefills and searches. Spaces/hyphens are ignored; 6–20 letters/digits.
* States: loading, invalid number, not found, rate-limited, server error, network error (with "Try again"),
  "Not allotted / not yet published", and "allotted but not yet published" (count only, no details).
* Each card shows only stored data: date, weekday, session, start/end time (when stored), subject code, subject name
  (when linked), semester (when stored), hall, seat, and building/block/floor/room **only for administrator-verified halls**.
* Seating chart (button on each card): seat-number map of the student's own hall; highlights the student's seat and shows
  allotted/vacant seats. It lists seat **numbers only** — never another student's name or register number. Vacant seats are
  shown only when the hall has a verified seat inventory; otherwise only allotted seats are listed and the page says so.
  The physical row/column layout of a room is not stored, so none is drawn.
* Print slip: *Print Slip / Save PDF* uses the browser print dialog; `@media print` hides the interface and prints a clean
  A4 slip with college name, register number, generated time and every card.
* Admin landing at `/` (signed-out view) also lost its example register number placeholder and autofocus.

## Public API added (read-only, rate limited, published records only)
| Endpoint | Purpose |
|---|---|
| `GET /api/portal/notices` | Upcoming published exam dates with FN/AN sessions and seat counts, plus public announcements |
| `GET /api/portal/lookup/{register_number}` | The student's published seats with session/time/subject name/semester. Unpublished allotments are never counted or mentioned (see the disclosure note below) |
| `GET /api/portal/seatmap/{register_number}?kind=allotment\|vsb&ref=ID` | Seat map of one of the caller's own published allotments |

`/api/lookup/{reg}` is unchanged (its privacy whitelist test still passes). Name is returned only if `PUBLIC_SHOW_NAMES=true`
(default `false`). Misses are counted per IP exactly as for `/api/lookup`.

## Admin: operations overview — `GET /api/operations/overview` (staff/admin/super admin)
Shown as the **Operations overview** card on the dashboard. Staff are limited to their department; recent activity and
publication history are shown to admin/super admin only. Everything is computed from stored data with listed rules
(returned in `rules`, shown under "How these checks work"): no allotments, incomplete allocation, unknown hall, unverified hall,
over capacity, duplicate seat, student time clash, not eligible, bad time, missing subject. Readiness is *ready / review / blocked*.
Hall utilisation compares the largest single-examination load with **verified** capacity only. No AI service is used.

## Tests
* `backend/tests/test_phase13_portal.py` — 27 pytest tests (API, privacy, seat map, VSB, static-page/CSP contract, operations).
* `python backend/tests/portal_dom/run_portal_dom.py` — 26 DOM checks in jsdom against a real server and a throw-away DB.
* `python backend/tests/e2e_jsdom/run_e2e.py` — existing e2e, repaired for the current landing page, plus operations-card checks.
* Portal smoke test: `python tests/portal_dom/run_portal_dom.py` (real server + jsdom; needs Node and `npm install` in `backend/tests/e2e_jsdom`).

## Known limitations
* No real-browser visual/pixel verification was possible in the build environment; layout was reviewed from the CSS and
  exercised through jsdom only. Test on a phone and a desktop browser before relying on it.
* Windows scripts (`install.bat`, `start.bat`, …) were not executed on Windows; they were reviewed statically.
* The portal draws seat *numbers* in order, not the room's physical layout, because that layout is not stored.
* Student "semester" is not stored on students; the portal shows semester only from the exam's term/subject, and the
  dashboard reports students by *year*.
* The operations overview checks at most 60 examinations per request (upcoming first; `exam_limit` up to 200).

### Disclosure note (this release)

`GET /api/portal/lookup/{register_number}` no longer returns a `pending_unpublished` count, and the portal no longer says
that a seat is "allotted, not yet published". Before this change, an unauthenticated visitor who entered a register number
learned that an unpublished allotment existed and how many there were. The response for a student with only unpublished
allotments is now identical to the response for a student with none (apart from the student's own identity block), and the
seat-map endpoint returns the same 404 for an unpublished allotment as for a missing one. Published results are unchanged.
Regression tests: `backend/tests/test_portal_disclosure.py`.
