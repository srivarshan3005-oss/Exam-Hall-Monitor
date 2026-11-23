# Security notes (release 0.2.0)

## Implemented and covered by automated tests
| Control | Detail | Test file |
|---|---|---|
| Strong signing key required | ≥32 chars, rejects placeholders/low variety; app refuses to start; `python -m app.cli gen-secret` | test_security, test_static_and_startup |
| No default accounts | demo seeding off by default, never creates a login, refused in production; a legacy `admin / ChangeMe123!` account blocks startup until `reset-password` | test_static_and_startup, test_cli_and_seed |
| No prefilled credentials in UI | | test_static_and_startup |
| Password policy | ≥12 chars, letter+digit, not common, not containing the username; PBKDF2-SHA256 (310,000 rounds default) | test_security, test_admin |
| Login throttling | 20 attempts / 15 min per IP; 5 failures per username → 15 min lockout; same behaviour for unknown usernames; lock stored in DB so it survives restarts/workers; `unlock-user` CLI / admin API | test_auth, test_admin |
| Token hardening | HS256 only (alg checked), issuer, expiry, per-account `ver` (password change, logout, role change, deactivation revoke tokens immediately) | test_security, test_auth, test_admin |
| Roles | `admin`, `staff`, `student`; endpoint × role matrix tested (53 cases) | test_authorization |
| Private data | public card hides names by default; results need sign-in; only *published* exam allotments are public; inactive students hidden | test_students, test_results, test_allotments |
| Anti-enumeration | 60 lookups/min/IP, 30 misses/15 min/IP then 429 (even for valid numbers); unknown register → same shape on allotments; invalid format counts as a miss | test_students, test_allotments |
| Audit trail | every admin write + login/lockout/password events; written in the same transaction as the change; stores field **names**, never marks, names, passwords | test_admin, test_exams, test_results |
| Input validation | Pydantic models; real dates/times; LIKE wildcards escaped; ORM only (no string-built SQL) | test_exams, test_students |
| Browser hardening | CSP, X-Frame-Options, nosniff, Referrer-Policy, no-store on API; HSTS in production; token in sessionStorage; all UI output HTML-escaped | test_static_and_startup |
| CORS | only `CORS_ORIGINS` | test_static_and_startup |

## Known limitations — read before any real deployment
1. **Register-number lookup is still enumerable in principle.** 12-digit numbers are structured and guessable; rate limits slow an attacker but
   cannot stop a distributed one. Decide with the college whether lookups should need a second factor (e.g. date of birth, OTP) before real data is loaded.
2. **Rate limiters are per process** (in memory). Several workers/servers need a shared limiter (reverse proxy, WAF, Redis). Login lockout is DB-backed.
3. **Campus NAT:** many students behind one public IP share the per-IP budget. Tune `PUBLIC_LOOKUP_*` for your network.
4. `TRUST_PROXY=true` must only be set behind a proxy you control (it trusts the right-most `X-Forwarded-For`).
5. **Not implemented yet:** admin MFA, CSRF tokens (not needed while auth is a bearer header, revisit if cookies are introduced), secure PDF upload validation (Phase 3), backups/restore tooling, security headers for a separately hosted frontend, an independent security review.
6. Login lockout can be abused to lock a known admin username for 15 minutes (a trade-off; admins can run `unlock-user`).
7. PostgreSQL support is designed for (portable SQLAlchemy + Alembic) but the migrations and tests have **not** been run on PostgreSQL.

## Production checklist (summary)
HTTPS reverse proxy · `ENVIRONMENT=production` · PostgreSQL with least-privilege role · managed secret store · `ENABLE_DOCS=false` · shared rate limiter ·
encrypted backups with a tested restore · log shipping + alerts · written authorization from the college · privacy notice and retention policy.

## Expanded Phase 2 implementation notes

PDF uploads are admin/staff-only, limited to 25 MiB, checked for a PDF signature, assigned a server-generated UUID filename and stored outside the static web root. SHA-256 is used for duplicate detection. Extracted register candidates remain pending and are never returned to student lookup until both the candidate and its document version are administrator-approved. OCR is optional and runs locally; it does not bypass review.

Hall records are hidden from the public hall directory until explicitly verified. If a configured hall is used for an allotment, it must be verified; if a seat inventory exists, the seat must be active and present. Existing free-text hall allocations are retained for compatibility when no directory record matches.

The current checkpoint has not undergone final security testing. Apply HTTPS, restrictive CORS, production secret management, access logging, backup retention, database hardening and institutional privacy review before production use.

## Phase 3 document handling
Uploads: `.pdf` only, magic-byte check, size limit (`MAX_UPLOAD_MB`), structural validation by opening (never executing), encrypted PDFs and PDFs with JavaScript/Launch actions rejected, SHA-256 duplicate detection. Files are stored under random names in `DOCUMENT_STORAGE_DIR` (default `backend/uploads`, outside the static site, mode 0600); the stored path is re-resolved and must stay inside that directory. Original filenames are sanitised and used only for display/download. Preview/download/text endpoints require admin or staff and send `Cache-Control: no-store`; downloads are logged. Register numbers found in documents are counted, not exposed in lists, and never imported. Edits, approvals and imports are recorded in `extraction_edits`, `document_events` and `audit_logs`.


## V7 additions
* **Original page image is unmasked on purpose** (requirement of the operator): the page shown is the same document the college
  publishes at its own website. Consequently anyone who searches one valid register number can *see* the other numbers that
  appear on that page. This is the content of the official PDF; the portal adds no new data and offers no listing or export.
  Mitigations: per-IP rate limits, repeated-miss throttling, input validation, no bulk endpoints, no directory listing,
  private storage of PDFs (served only through the page endpoint, never by path).
* Public API accepts one validated register number; `record_id` must belong to that number or the response is 404.
* Management API requires authentication; writes need the administrator role; e-mail addresses are administrator-only and
  masked in histories; credentials only from environment variables; secrets are redacted from stored error text.
* Crawler: https + allow-listed hosts only (`vsbec.edu.in`, `www.`, `coe.`), robots.txt per host, size/type/signature checks, no private endpoints.
* Supabase mirror: service key stays on the server; RLS enabled with no public policy.
