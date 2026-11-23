# Phase 4 — Authentication, access control and security (v0.5.0)

## Roles (enforced by the backend in `app/deps.py` + `app/permissions.py`)
| Role (stored value) | Meaning | Can |
|---|---|---|
| `super_admin` | Super administrator | everything `admin` can; create/change/suspend/reset administrator accounts |
| `admin` | Examination administrator (the original Phase 1 role, unchanged) | all admin endpoints, accounts of staff/invigilator/student, security dashboard, audit |
| `staff` | Department staff | Phase 1–3 staff endpoints. If the account has a *department*, student lists, hall rosters, allocation lists and seat lookups are limited to that department, and allotment edits to other departments are refused (403). Whole-hall seating charts are refused for department-scoped staff (they list every department). |
| `invigilator` | Read-only | examination list, hall rosters, hall occupancy, seating charts. No writes. |
| `student` | Student | own published results; public lookup as before |

`super_admin` is accepted wherever `admin` is. **Upgrade safety:** until the first active super administrator exists, `admin` keeps its Phase 1 powers over other administrators (so an upgraded system cannot lock itself out). Create one with `python -m app.cli create-admin --username boss --role super_admin`; from then on administrator-level management is reserved to super administrators. The last active administrator and the last active super administrator can never be removed.

## Authentication
* PBKDF2-SHA256 (310 000 rounds, per-password salt) — unchanged; policy ≥12 chars, letter+digit.
* **Server-side sessions** (`auth_sessions`): every token carries a session id; logout revokes that session, *logout-all* / password change / reset / role change / suspension revoke all; idle timeout (`SESSION_IDLE_MINUTES`, default 30), absolute expiry (`ACCESS_TOKEN_MINUTES`), max sessions per user (`MAX_SESSIONS_PER_USER`). Users can list/end their own sessions.
* Lockout and per-IP throttling (Phase 1) kept; unknown, suspended and pending accounts get the same "Incorrect username or password" answer.
* **Registration** (`POST /api/auth/register`, students only): needs the register number *and* the e-mail already on the student record; account is created `pending`; activation link e-mailed (`POST /api/auth/activate`). Identical 202 answer in every case. Administrators can also approve pending accounts. Disable with `ALLOW_SELF_REGISTRATION=false`.
* **Forgot/reset** (`/api/auth/forgot-password`, `/reset-password`): uniform answer, per-IP and per-identifier limits, one-time 30-minute token, stored only as SHA-256, older links die when a new one is issued, a weak new password keeps the link valid, success ends all sessions.
* **Administrator reset**: written reason, no self-reset, administrator targets need a super administrator, 10/hour limit, random temporary password shown once, forced change at next sign-in (until then every endpoint except `/api/auth/me`, `/profile`, `change-password`, `logout` returns 403), all sessions ended, audit + critical security event.
* Optional `PASSWORD_MAX_AGE_DAYS` forces periodic change.

## Web security
* **CSRF**: the API authenticates with a bearer header held in `sessionStorage`; there is no cookie, so a cross-site page has nothing to ride. As defence in depth, state-changing requests whose `Origin` is not this host or a listed `CORS_ORIGINS` entry (or is `null`) get 403. A cookie-based session was deliberately **not** added (it would need CSRF tokens and gains nothing here).
* Headers: CSP (`default-src 'self'`, `frame-ancestors 'none'`), `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP, `Cache-Control: no-store` on `/api/*`, HSTS in production.
* CORS: explicit origins only, no credentials; startup refuses `*`, and in production refuses non-https origins / `PUBLIC_BASE_URL`.
* Injection/XSS/IDOR: SQLAlchemy parameters only, `LIKE` input auto-escaped, every UI value passed through `esc()`, per-record checks (own results, own sessions, department scope). Phase 3 upload protections unchanged.
* Secrets: `.env` only (git-ignored), `SECRET_KEY` validated at start, audit details are scrubbed of keys that look like passwords/tokens, security events keep only username-shaped names (a password typed in the username box is stored as `(invalid-format)`), tokens are never logged.

## Account management & dashboard (web UI: "Accounts & security" panel)
Accounts (filter by text/role/status/department, create, change role, suspend/restore/approve, unlock, reset password, force sign-out, per-user activity), Security dashboard (24 h summary, event search by type/severity/user/IP/text/date, active sessions), Audit history (text/actor/action/date search), My account (change password, own sessions). Permission denials show the required role and are logged (`authz.denied`).

## Seating-allotment PDF import
`app/seating_parse.py`, `app/routers/seating.py`, tab "Seating PDF import". Works on the page text produced by Phase 3 *Process/OCR*. Hall comes only from a Hall/Room/Venue label, seat from an explicit "Seat" label (or the only bare number on the line, flagged and scored lower); otherwise empty + flagged. OCR rows always flagged. Duplicate students, conflicting allocations and shared seats are detected inside the document and against existing allotments (same checks as manual allocation: verified hall, active seat, eligibility, simultaneous exams). Only admin-approved, complete, conflict-free rows are imported, after an explicit confirmation tied to a signature of the previewed data. Staff can extract/preview; admins edit/approve/import.

## Migrations
`0007_auth_security_rbac` (users: email, status, must_change_password, password_changed_at, department, status_reason; tables `auth_sessions`, `password_tokens`, `security_events`; `status` back-filled from `active`) and `0008_seating_import` (`seating_entries`). Back up, then `python -m app.cli migrate`. Users sign in once more after the upgrade (old tokens have no session). No password is touched.
