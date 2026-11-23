# Phase 6 - Notifications, e-mail delivery and communication (v0.7.0)

## What it does
* **In-app notifications** per user: read/unread, mark one/all read, archive/restore, delete (soft delete), categories
  (exam, timetable, seating, result, announcement, reminder, account), priorities (low/normal/high/urgent),
  filter + search + pagination (`X-Total-Count`), unread count, per-user preferences (in-app / e-mail per category;
  account/security notices cannot be switched off in-app).
* **E-mail** through SMTP configured only by environment variables (see `.env.example`). Statuses in `email_deliveries`:
  `queued, sending, retrying, sent, failed, outbox, not_configured`. **`sent` is written only after the SMTP server accepted
  the message.** Without `SMTP_HOST`: development/test write files to the outbox folder (status `outbox`, never "sent"). The folder is `backend/outbox` by default and can be set with `MAIL_OUTBOX_DIR` (absolute, or relative to `backend`); an unusable value is reported by `check-config` and is never silently replaced by the default folder;
  production reports `not_configured`. Transient errors (connect, timeout, 4xx) retry with doubling back-off up to
  `MAIL_MAX_ATTEMPTS`; permanent errors (auth, refused recipient, 5xx, TLS validation) fail at once. Error text is redacted
  (addresses, user, password); logs contain only id/status/attempt/error code.
* **Events** (after the action's own commit; a notification failure never undoes the action): exam published / schedule
  changed / withdrawn (= unpublished), including changes applied by a timetable-PDF import; seat allocated / corrected /
  removed (manual, automatic plan commit, seating-PDF import); result published (never contains marks or grade);
  announcements; account activated, password changed/reset (plus the existing activation/reset e-mails, unchanged).
* **Audience**: students who are eligible for the exam (audience rules + overrides) with an active account; department
  staff only when their department is represented (staff without department: all); invigilators; the acting user is
  excluded. Seat/result notices go only to the affected student. Drafts never notify. Announcements: roles, department, year;
  department staff can only notify their own department's students; targeted announcements are not shown on the public page.
* **Reminders** (background thread, `SCHEDULER_ENABLED`): exam reminders `REMINDER_EXAM_HOURS` before start (text states
  the real time left and the student's hall/seat if allotted), announcement reminders (`remind_at`), scheduled
  announcements (`publish_at`). Time zone `APP_TIMEZONE`, **default Asia/Kolkata**. Result publication and timetable changes are
  *event-driven* (immediate), not scheduled reminders.
* **Duplicate prevention**: `UNIQUE(user_id, event_key)` on notifications and `UNIQUE(dedup_key)` on e-mail rows; e-mail rows are
  claimed with an atomic UPDATE so two workers cannot send the same row. A deleted notification keeps its key.
* **Administrator controls** (admin/super_admin only): `/api/admin/communications/` email-status (no secrets), test-email
  (own address or an address of an existing user/student record; 5/hour), deliveries (masked recipients, filters), retry
  (not for sent messages; not for messages carrying one-time links, which are never stored), stats, templates (whitelisted
  placeholders, preview, reset), run-scheduler. Audited: test e-mail, retry, template changes, scheduler runs, announcements.

## Run without the built-in worker
`SCHEDULER_ENABLED=false`, then call `POST /api/admin/communications/run-scheduler` from a cron job with an admin session, or
`python -c "from app import scheduler; print(scheduler.run_cycle())"` from `backend/`.

## Upgrade
Back up, `python -m app.cli migrate` (migration `0009`, additive; existing announcements keep behaviour: public, no notification).
Windows: `pip install -r requirements.txt` adds `tzdata`.

## Real SMTP verification (NOT done in development)
Automated tests use a real local SMTP server (aiosmtpd) and a self-signed TLS server; no real provider was contacted.
To verify your provider: set SMTP_* in `backend/.env`, restart, open **Communications**, send a test e-mail to your own
address and confirm it arrives. Gmail/Office 365 need an app password / SMTP AUTH enabled.

## SMTP timeout and security notes
* `SMTP_TIMEOUT_SECONDS` (default 15) is a **per-socket-operation** timeout handed to Python's `smtplib` (connect and each read/write). It is **not**
  an overall deadline for a delivery attempt or for the HTTP request. One attempt performs several operations (connect, EHLO, STARTTLS, login,
  sender, recipient, data), so a slow or stalling server can keep a single attempt open for a multiple of this value.
* Activation and password-reset e-mail and the administrator "send test e-mail" make one attempt **inside the request** that triggered it, so that request can
  take noticeably longer than `SMTP_TIMEOUT_SECONDS` when the SMTP server is unresponsive. Queued notification e-mail is sent by the background worker, not in a request,
  and is retried up to `MAIL_MAX_ATTEMPTS` times with doubling back-off.
* `SMTP_SECURITY=none` together with `SMTP_USER` can send the SMTP login without encryption. `check-config` prints a non-blocking warning in production; use `starttls` or `ssl`.

## Limitations
* STARTTLS and plain AUTH are exercised only against the local test server; real-provider TLS/auth/deliverability (SPF/DKIM) untested.
* One in-process worker; with several API workers the DB claim/unique keys prevent duplicates, but each runs its own loop.
* E-mail is plain text. Bounces after SMTP acceptance are not tracked.
* No push/SMS. No notification retention/purge job (soft-deleted rows remain). Exam "cancelled" = unpublished (no separate status).
* Rate limiting is in-process (see SECURITY.md).
