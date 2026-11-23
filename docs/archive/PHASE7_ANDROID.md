# Phase 7 - Android application

See `android/README.md` for build and configuration. This page records design decisions and the manual test plan.

## Architecture
`core/` pure Kotlin (roles, permissions, navigation rules, error mapping, validation, date logic, DTO validation) -
`data/` Retrofit API, OkHttp interceptors, encrypted storage, session manager, per-user cache, repositories -
`ui/` ViewModels (StateFlow), Compose screens, Navigation Compose. `AppContainer` wires everything; the API is rebuilt only if the server address changes while signed out.

## Backend changes
None. Phase 7 is client-only plus `backend/tests/test_phase7_android_contract.py` (read-only tests of existing endpoints).
Endpoint facts the app depends on (discovered, not assumed): report endpoints live under `/api/admin/reports/...`; notification action
responses carry the new `unread` count; forced password change returns 403 "Password change required..." everywhere except profile/change-password/logout.

## Role matrix (UI; the backend remains the authority)
Student: own timetable/seat/results, notifications, announcements. Invigilator: exam list, halls, allocations (read). Staff/admin: plus dashboard,
exam summary, student seat lookup, publish/unpublish. Super administrator = administrator in the app.

## Manual test checklist (not yet executed)
1. Wrong password shows the server message; 5 failures lock the account (429 message with wait time).
2. Student login -> Home shows next exam; Timetable shows hall/seat; tap card -> details; Results lists published results only.
3. Airplane mode after loading -> pull to refresh shows the amber "Saved copy" banner with the time; sign out -> sign in as another user -> no old data visible.
4. Administrator: Exams -> publish a draft (confirm dialog) -> student receives a notification; unpublish -> timetable updates.
5. Alerts: unread badge, mark read/unread, archive, mark all read, load more, open detail, preferences save.
6. Administrator resets a user's password in the web portal -> user signs in -> forced change screen -> new password works, old token rejected.
7. Revoke the session from the web portal ("force logout") -> next action returns to login with "session has ended".
8. Rotate the device and toggle dark mode during loading; no crash, state kept.
9. Release build refuses an `http://` server address.
