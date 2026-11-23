"""Outgoing e-mail transport (Phase 6).

* SMTP is configured only through environment variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
  SMTP_SECURITY = starttls | ssl | none, SMTP_FROM, SMTP_FROM_NAME, SMTP_TIMEOUT_SECONDS).
* "sent" is returned only after the SMTP server accepted the message (send_message returned without error
  and without refused recipients). Nothing else is ever reported as sent.
* Without SMTP_HOST: development/test write a clearly separate file outbox (status "outbox", NOT "sent");
  production reports "not_configured".
* Logs never contain credentials, addresses or message content.
"""
import logging, re, smtplib, socket, ssl, time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from .config import settings

log = logging.getLogger("exam_monitor.mail")
BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTBOX = BACKEND_DIR / "outbox"


def resolve_outbox_path(raw: str | None) -> Path:
    """Turn the MAIL_OUTBOX_DIR setting into an absolute folder. Blank keeps the default (backend/outbox).
    Raises ValueError for a value that cannot be used (a NUL character, or a path that exists as a file)."""
    value = (raw or "").strip()
    if not value:
        return DEFAULT_OUTBOX
    if "\x00" in value:
        raise ValueError("the path contains an invalid character")
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = BACKEND_DIR / p
    p = p.resolve()
    if p.exists() and not p.is_dir():
        raise ValueError("the path exists and is a file, not a folder")
    return p


def _load_outbox() -> tuple[Path | None, str | None]:
    """(folder, None) when usable; (None, problem) when the configured value cannot be used. Never silently falls back."""
    try:
        return resolve_outbox_path(settings.mail_outbox_dir), None
    except ValueError as e:
        return None, f"MAIL_OUTBOX_DIR is not usable: {e}. Messages cannot be written until it is corrected."


OUTBOX, OUTBOX_PROBLEM = _load_outbox()
_ADDR = re.compile(r"[\w.+'-]+@[\w-]+(\.[\w-]+)+")


class MailError(Exception):
    def __init__(self, code: str, message: str, transient: bool):
        super().__init__(message)
        self.code, self.transient = code, transient


def redact(text: str) -> str:
    """Strip anything that could be a secret or an address from a provider message before it is stored."""
    t = _ADDR.sub("[address]", str(text or ""))
    for secret in (settings.smtp_password, settings.smtp_user):
        if secret and len(secret) >= 3:
            t = t.replace(secret, "[redacted]")
    return re.sub(r"\s+", " ", t).strip()[:200]


def mail_mode() -> str:
    if settings.smtp_host:
        return "smtp"
    return "outbox" if settings.environment in ("development", "test") else "none"


def config_status() -> dict:
    """Configuration overview for administrators. Never contains the password or the user name itself."""
    return {"mode": mail_mode(), "smtp_configured": bool(settings.smtp_host), "host": settings.smtp_host or None,
            "port": settings.smtp_port if settings.smtp_host else None, "security": settings.smtp_security_mode,
            "username_set": bool(settings.smtp_user), "password_set": bool(settings.smtp_password),
            "from_address": settings.smtp_from, "from_name": settings.smtp_from_name,
            "timeout_seconds": settings.smtp_timeout_seconds, "max_attempts": settings.mail_max_attempts,
            "retry_backoff_seconds": settings.mail_retry_backoff_seconds,
            "outbox_directory": (str(OUTBOX) if OUTBOX else None) if mail_mode() == "outbox" else None,
            "outbox_problem": OUTBOX_PROBLEM if mail_mode() == "outbox" else None,
            "environment": settings.environment,
            "note": {"smtp": "Messages are submitted to the configured SMTP server.",
                     "outbox": "Development outbox: messages are written to files, nothing leaves this computer.",
                     "none": "SMTP is not configured: no e-mail can be delivered. Set SMTP_HOST in the environment."}[mail_mode()]}


def build_message(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    clean = lambda v: re.sub(r"[\r\n]+", " ", str(v)).strip()  # noqa: E731 - header-injection guard
    msg["From"] = formataddr((clean(settings.smtp_from_name), clean(settings.smtp_from)))
    msg["To"], msg["Subject"] = clean(to), clean(subject)[:190]
    msg["Date"], msg["Message-ID"] = formatdate(localtime=False), make_msgid(domain="exam-monitor.local")
    msg.set_content(body)
    return msg


def smtp_submit(msg: EmailMessage) -> None:
    """Submit to the SMTP server. Returns normally ONLY when the server accepted the message."""
    sec, ctx = settings.smtp_security_mode, ssl.create_default_context()
    try:
        if sec == "ssl":
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds, context=ctx)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
        with client as s:
            s.ehlo()
            if sec == "starttls":
                s.starttls(context=ctx)
                s.ehlo()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            refused = s.send_message(msg)
        if refused:
            raise MailError("recipient_refused", "The server refused the recipient", False)
    except MailError:
        raise
    except smtplib.SMTPRecipientsRefused:
        raise MailError("recipient_refused", "The server refused the recipient", False)
    except smtplib.SMTPAuthenticationError:
        raise MailError("auth_failed", "SMTP authentication failed (check SMTP_USER / SMTP_PASSWORD)", False)
    except smtplib.SMTPNotSupportedError:
        raise MailError("not_supported", "The server does not support the requested security mode", False)
    except smtplib.SMTPResponseException as e:
        transient = 400 <= int(e.smtp_code) < 500
        raise MailError(f"smtp_{e.smtp_code}", f"SMTP {e.smtp_code}: {redact(e.smtp_error if isinstance(e.smtp_error, str) else e.smtp_error.decode('utf-8', 'replace'))}", transient)
    except (socket.timeout, TimeoutError):
        raise MailError("timeout", "Timed out talking to the SMTP server", True)
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, ConnectionError, socket.gaierror):
        raise MailError("connection_error", "Could not connect to the SMTP server", True)
    except ssl.SSLError:
        raise MailError("tls_error", "TLS negotiation with the SMTP server failed", False)
    except smtplib.SMTPException as e:
        raise MailError("smtp_error", "SMTP error: " + redact(type(e).__name__), True)
    except OSError:
        raise MailError("connection_error", "Network error while contacting the SMTP server", True)


def write_outbox(to: str, subject: str, body: str) -> None:
    if OUTBOX is None:
        raise MailError("outbox_invalid", OUTBOX_PROBLEM or "The development outbox folder is not usable.", transient=False)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    (OUTBOX / f"{int(time.time() * 1000)}-{time.monotonic_ns() % 100000}.txt").write_text(
        f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")


def attempt(to: str, subject: str, body: str) -> tuple[str, str | None, str | None, str]:
    """One delivery attempt -> (status, error_code, error_text, mode); status in sent|outbox|not_configured|error."""
    mode = mail_mode()
    try:
        if mode == "smtp":
            smtp_submit(build_message(to, subject, body))
            return "sent", None, None, "smtp"
        if mode == "outbox":
            write_outbox(to, subject, body)
            return "outbox", None, None, "outbox"
        return "not_configured", "not_configured", "SMTP is not configured (set SMTP_HOST)", "none"
    except MailError as e:
        return ("error:transient" if e.transient else "error:permanent"), e.code, str(e), mode
    except Exception as e:  # noqa: BLE001 - delivery problems must never crash a request or worker
        return "error:transient", "unexpected", "Unexpected delivery error: " + type(e).__name__, mode


def send_mail(to: str, subject: str, body: str) -> str:
    """Compatibility entry point for password-reset / activation mail (Phase 4 callers).
    One immediate attempt, recorded in email_deliveries WITHOUT the body (it contains a one-time link).
    Returns 'smtp' | 'outbox' | 'not-configured'. Never raises."""
    from .database import SessionLocal
    from . import delivery
    try:
        with SessionLocal() as db:
            row = delivery.create(db, to=to, subject=subject, body=body, kind="account", sensitive=True)
            status = delivery.deliver_row(db, row, allow_retry=False)
            db.commit()
        return {"sent": "smtp", "outbox": "outbox"}.get(status, "not-configured")
    except Exception:  # noqa: BLE001
        log.warning("mail delivery failed (account message)")
        return "not-configured"


def attempt_message(msg: EmailMessage) -> tuple[str, str | None, str | None, str]:
    """Like attempt(), for a ready-made message (used for e-mail with attachments). Same status vocabulary.
    Outbox mode (development/test only) writes the message - including its attachments - to the outbox folder."""
    mode = mail_mode()
    try:
        if mode == "smtp":
            smtp_submit(msg)
            return "sent", None, None, "smtp"
        if mode == "outbox":
            if OUTBOX is None:
                raise MailError("outbox_invalid", OUTBOX_PROBLEM or "The development outbox folder is not usable.", transient=False)
            OUTBOX.mkdir(parents=True, exist_ok=True)
            stem = f"{int(time.time() * 1000)}-{time.monotonic_ns() % 100000}"
            names = []
            for part in msg.iter_attachments():
                fn = re.sub(r"[^A-Za-z0-9._-]", "_", part.get_filename() or "attachment")
                (OUTBOX / f"{stem}-{fn}").write_bytes(part.get_payload(decode=True) or b"")
                names.append(fn)
            body = msg.get_body(preferencelist=("plain",))
            (OUTBOX / f"{stem}.txt").write_text(
                f"To: {msg['To']}\nSubject: {msg['Subject']}\nAttachments: {', '.join(names) or 'none'}\n\n"
                f"{body.get_content() if body else ''}\n", encoding="utf-8")
            return "outbox", None, None, "outbox"
        return "not_configured", "not_configured", "SMTP is not configured (set SMTP_HOST)", "none"
    except MailError as e:
        return ("error:transient" if e.transient else "error:permanent"), e.code, str(e), mode
    except Exception as e:  # noqa: BLE001
        return "error:transient", "unexpected", "Unexpected delivery error: " + type(e).__name__, mode

