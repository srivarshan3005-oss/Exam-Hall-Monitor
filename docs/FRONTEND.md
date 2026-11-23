# Front end (Phase 5)

Static, build-free single-page app served by FastAPI from `backend/app/static/`:

```
index.html            shell, skip link, script tags (no inline scripts: the CSP forbids them)
css/app.css           design system: tokens, light/dark themes, components, responsive layout, print rules
js/core.js            EM runtime: API client (errors, 401 → sign-in, 429), dialogs, toasts, form helpers with
                      double-submit guard and field-level backend errors, sortable/searchable/paginated grid, router
js/main.js            public/app layouts, role-aware sidebar, boot, public landing + authentication pages
js/pages-dash.js      role dashboards + student pages
js/pages-exams.js     examinations, audience, subjects, years & terms
js/pages-people.js    students, accounts & permissions, results
js/pages-seating.js   allocation, reports, rosters/seating charts, halls & campus, announcements
js/pages-docs.js      timetable PDFs (upload, OCR review, import, history), seating PDF import, register candidates
js/pages-admin.js     security dashboard, audit history, my account
```
Routes use the URL hash (`#/exams`, `#/documents/12/review`), so refresh and the back button keep the page. The session token lives in `sessionStorage` (cleared when the tab closes); only the light/dark preference is stored in `localStorage`.

## Pages per role
| Route | Admin / Super | Staff | Invigilator | Student |
|---|---|---|---|---|
| `#/` dashboard | ✔ (security + audit widgets) | ✔ | ✔ upcoming exams | ✔ own seats/results |
| `exams`, `subjects`, `terms` | ✔ | ✔ (terms read-only; no delete) | | |
| `results` | ✔ | | | |
| `allocation`, `reports`, `halls` | ✔ (commit, verify, edit) | ✔ preview/manual seats, read halls | | |
| `rosters`, `seating` | via Reports | via Reports | ✔ read-only | |
| `documents`, `seating-import`, `register-candidates` | ✔ edit/approve/import | upload, extract, view | | |
| `students` | ✔ create/edit | ✔ read | | |
| `accounts`, `security`, `audit` | ✔ | | | |
| `announcements` | ✔ | ✔ (no delete) | view | view |
| `my-exams`, `my-results` | | | | ✔ |
| `account` | ✔ | ✔ | ✔ | ✔ |

Pages declare `roles`; the router refuses others in the UI **and** each API call is independently authorised by the server.

## Adding a page
`EM.page({ name, title, roles, nav:{group,icon,label,order}, render: async (root, ctx) => {...} })`. Use `EM.esc` for every interpolated value, `EM.onSubmit` for forms, `EM.delegate` for buttons, `EM.ask`/`EM.confirm` for dialogs.
