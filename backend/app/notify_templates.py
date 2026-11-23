"""Notification / e-mail texts. Plain text only, fixed placeholder whitelist, sanitised values.

Administrators may override subject and body (table email_templates) but only with the placeholders listed
for that template, so a template can never pull in a password, token, register number or marks."""
import re

CATEGORIES = {
    "exam": "Examinations", "timetable": "Timetable changes", "seating": "Hall & seat allocation",
    "result": "Results", "announcement": "Announcements", "reminder": "Reminders", "account": "Account & security",
}
PRIORITIES = ("low", "normal", "high", "urgent")
_COMMON = ["college"]
TEMPLATES: dict[str, dict] = {
    "exam_published": {"label": "Examination published", "category": "exam", "priority": "normal",
        "placeholders": ["exam_title", "subject_code", "exam_date", "exam_time", "venue"],
        "subject": "New examination: {exam_title}",
        "body": "{exam_title} ({subject_code}) has been published.\nDate: {exam_date}\nTime: {exam_time}\nVenue: {venue}\n"
                "Check the portal for your hall and seat once they are allotted."},
    "exam_updated": {"label": "Examination / timetable changed", "category": "timetable", "priority": "high",
        "placeholders": ["exam_title", "subject_code", "exam_date", "exam_time", "venue", "changes"],
        "subject": "Timetable change: {exam_title}",
        "body": "The schedule of {exam_title} ({subject_code}) was changed.\nChanged: {changes}\nNew date: {exam_date}\n"
                "New time: {exam_time}\nVenue: {venue}"},
    "exam_withdrawn": {"label": "Examination withdrawn / cancelled", "category": "exam", "priority": "high",
        "placeholders": ["exam_title", "subject_code", "exam_date"],
        "subject": "Examination withdrawn: {exam_title}",
        "body": "{exam_title} ({subject_code}) scheduled for {exam_date} has been withdrawn from the published timetable. "
                "Do not rely on the earlier schedule; a new notice will follow if it is re-published."},
    "seat_allocated": {"label": "Hall & seat allocated", "category": "seating", "priority": "normal",
        "placeholders": ["exam_title", "subject_code", "exam_date", "exam_time", "hall", "seat"],
        "subject": "Your seat for {exam_title}",
        "body": "Your seating for {exam_title} ({subject_code}) is available.\nDate: {exam_date}  Time: {exam_time}\n"
                "Hall: {hall}\nSeat: {seat}"},
    "seat_corrected": {"label": "Seat allocation corrected", "category": "seating", "priority": "high",
        "placeholders": ["exam_title", "subject_code", "exam_date", "exam_time", "hall", "seat", "old_hall", "old_seat"],
        "subject": "Seat changed for {exam_title}",
        "body": "Your seat for {exam_title} ({subject_code}) on {exam_date} at {exam_time} was corrected.\n"
                "Previous: Hall {old_hall}, Seat {old_seat}\nNow: Hall {hall}, Seat {seat}"},
    "seat_removed": {"label": "Seat allocation removed", "category": "seating", "priority": "high",
        "placeholders": ["exam_title", "subject_code", "exam_date", "exam_time", "old_hall", "old_seat"],
        "subject": "Seat allocation removed: {exam_title}",
        "body": "Your earlier seat (Hall {old_hall}, Seat {old_seat}) for {exam_title} ({subject_code}, {exam_date}) was removed. "
                "A new seat will be notified; please check the portal before the examination."},
    "exam_reminder": {"label": "Examination reminder", "category": "reminder", "priority": "high",
        "placeholders": ["exam_title", "subject_code", "exam_date", "exam_time", "venue", "time_left", "seat_line"],
        "subject": "Reminder: {exam_title} starts {time_left}",
        "body": "{exam_title} ({subject_code}) starts {time_left}.\nDate: {exam_date}  Time: {exam_time}\nVenue: {venue}\n{seat_line}"},
    "result_published": {"label": "Result published", "category": "result", "priority": "normal",
        "placeholders": ["exam_title", "subject_code"],
        "subject": "Result published: {exam_title}",
        "body": "Your result for {exam_title} ({subject_code}) is now available. Sign in to the portal to view it."},
    "announcement": {"label": "Announcement", "category": "announcement", "priority": "normal",
        "placeholders": ["announcement_title", "announcement_body"],
        "subject": "{announcement_title}", "body": "{announcement_body}"},
    "announcement_reminder": {"label": "Announcement reminder", "category": "reminder", "priority": "high",
        "placeholders": ["announcement_title", "announcement_body"],
        "subject": "Reminder: {announcement_title}", "body": "{announcement_body}"},
    "account_activated": {"label": "Account activated", "category": "account", "priority": "normal",
        "placeholders": ["college"],
        "subject": "Your Exam Monitor account is active",
        "body": "Your account has been activated. You can now sign in to the {college} Exam Monitor portal."},
    "password_changed": {"label": "Password changed", "category": "account", "priority": "high",
        "placeholders": ["college"],
        "subject": "Your Exam Monitor password was changed",
        "body": "The password of your {college} Exam Monitor account was just changed. If this was not you, "
                "contact your administrator immediately."},
    "test_email": {"label": "Administrator test e-mail", "category": "account", "priority": "low",
        "placeholders": ["college"],
        "subject": "Exam Monitor test e-mail",
        "body": "This is a test message from the {college} Exam Monitor. If you can read it, outgoing e-mail works."},
}
_PH = re.compile(r"\{(\w+)\}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(value, limit: int = 300, multiline: bool = False) -> str:
    """Make a user-controlled value safe for a plain-text notification / e-mail header."""
    s = _CTRL.sub("", str(value if value is not None else ""))
    if not multiline:
        s = re.sub(r"\s+", " ", s)
    else:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def validate_template(key: str, subject: str, body: str) -> list[str]:
    spec = TEMPLATES.get(key)
    if not spec:
        return ["Unknown template"]
    errs = []
    allowed = set(spec["placeholders"]) | set(_COMMON)
    if not (3 <= len(subject.strip()) <= 150):
        errs.append("Subject must be 3–150 characters")
    if "\n" in subject or "\r" in subject:
        errs.append("Subject must be a single line")
    if not (5 <= len(body.strip()) <= 3000):
        errs.append("Body must be 5–3000 characters")
    if _CTRL.search(subject) or _CTRL.search(body):
        errs.append("Control characters are not allowed")
    bad = sorted({m for m in _PH.findall(subject + " " + body) if m not in allowed})
    if bad:
        errs.append("Unknown placeholder(s): " + ", ".join("{" + b + "}" for b in bad) +
                    ". Allowed: " + ", ".join("{" + a + "}" for a in sorted(allowed)))
    return errs


def render_text(subject: str, body: str, ctx: dict) -> tuple[str, str]:
    def fill(text: str, multiline: bool) -> str:
        return _PH.sub(lambda m: clean(ctx.get(m.group(1), ""), 1500 if m.group(1) == "announcement_body" else 300,
                                       multiline and m.group(1) == "announcement_body")
                       if m.group(1) in ctx else m.group(0), text)
    return clean(fill(subject, False), 190), fill(body, True).strip()[:4000]
