"""Command line helpers:  python -m app.cli <command>"""
import argparse, getpass, os, secrets, sys
from datetime import datetime, timezone
from sqlalchemy import select
from . import models, audit
from .config import settings
from .database import SessionLocal
from .security import check_secret_key, hash_password, validate_password_strength


def cmd_gen_secret(_args) -> int:
    print(secrets.token_urlsafe(48))
    return 0


def cmd_init_env(_args) -> int:
    """Create backend/.env from .env.example with a freshly generated SECRET_KEY (never overwrites)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    target, example = root / ".env", root / ".env.example"
    if target.exists():
        print(".env already exists - left untouched")
        return 0
    text = example.read_text(encoding="utf-8").replace("SECRET_KEY=", "SECRET_KEY=" + secrets.token_urlsafe(48), 1)
    target.write_text(text, encoding="utf-8")
    print("Created", target)
    return 0


def cmd_check_config(_args) -> int:
    problems = check_secret_key(settings.secret_key)
    for p in problems:
        print("PROBLEM:", p)
    if settings.environment == "production" and settings.database_url.startswith("sqlite"):
        problems.append("production should use PostgreSQL")
        print("PROBLEM: production should use PostgreSQL")
    if settings.environment == "production":
        from .config import production_placeholder_problems
        for msg in production_placeholder_problems(settings):
            if msg.endswith("(warning)"):
                print("WARNING:", msg)
            else:
                problems.append(msg)
                print("PROBLEM:", msg)
    from . import mailer
    if mailer.mail_mode() == "outbox" and mailer.OUTBOX_PROBLEM:
        problems.append(mailer.OUTBOX_PROBLEM)
        print("PROBLEM:", mailer.OUTBOX_PROBLEM)
    print("Configuration OK" if not problems else "Configuration has problems")
    return 1 if problems else 0


def cmd_migrate(_args) -> int:
    from .dbcheck import migrate
    print("Database is at revision", migrate())
    return 0


def cmd_db_audit(_args) -> int:
    from .dbcheck import audit_schema
    r = audit_schema()
    print(f"Revision: {r['revision'] or 'none'}   (application needs {r['head']})")
    for key, label in (("drift", "Schema differs from the models"), ("missing_constraints", "Constraints not present"),
                       ("duplicate_student_links", "Students linked to more than one account"),
                       ("foreign_key_violations", "Foreign-key violations")):
        if r[key]:
            print(f"PROBLEM: {label}: {r[key]}")
    for name, n in r["violations"].items():
        print(f"  {name}: {n} existing row(s) violate it - correct those rows, then re-run the migration step (see docs/MIGRATIONS.md)")
    print("Database schema OK" if r["ok"] else "Database schema needs attention (nothing was changed)")
    return 0 if r["ok"] else 1


def create_account(username: str, password: str, role: str = "admin") -> models.User:
    username = username.strip().lower()
    problems = validate_password_strength(password, username)
    if problems:
        raise ValueError("; ".join(problems))
    db = SessionLocal()
    try:
        if db.scalar(select(models.User).where(models.User.username == username)):
            raise ValueError(f"User '{username}' already exists")
        u = models.User(username=username, password_hash=hash_password(password), role=role)
        db.add(u)
        audit.record(db, "cli", "user.created", username, {"role": role, "via": "cli"})
        db.commit()
        return u
    finally:
        db.close()


def cmd_create_admin(args) -> int:
    password = os.environ.get("EM_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("New admin password (min 12 chars, letters + digits): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match")
            return 1
    try:
        create_account(args.username, password, getattr(args, "role", "admin"))
    except ValueError as exc:
        print("ERROR:", exc)
        return 1
    print(f"Account '{args.username.strip().lower()}' created with role {getattr(args, 'role', 'admin')}.")
    return 0


def cmd_unlock(args) -> int:
    db = SessionLocal()
    try:
        u = db.scalar(select(models.User).where(models.User.username == args.username.strip().lower()))
        if not u:
            print("No such user")
            return 1
        u.locked_until, u.failed_attempts = None, 0
        audit.record(db, "cli", "user.unlocked", u.username)
        db.commit()
        print("Unlocked", u.username)
        return 0
    finally:
        db.close()


def cmd_reset_password(args) -> int:
    password = os.environ.get("EM_NEW_PASSWORD")
    if not password:
        password = getpass.getpass("New password (min 12 chars, letters + digits): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match")
            return 1
    name = args.username.strip().lower()
    problems = validate_password_strength(password, name)
    if problems:
        print("ERROR:", "; ".join(problems))
        return 1
    db = SessionLocal()
    try:
        u = db.scalar(select(models.User).where(models.User.username == name))
        if not u:
            print("No such user")
            return 1
        u.password_hash = hash_password(password)
        u.token_version += 1
        u.must_change_password = False
        u.locked_until, u.failed_attempts = None, 0
        db.execute(models.AuthSession.__table__.update().where(models.AuthSession.user_id == u.id).values(revoked_at=models.utcnow()))
        audit.record(db, "cli", "user.password_reset", u.username, {"via": "cli"})
        db.commit()
        print("Password changed for", u.username)
        return 0
    finally:
        db.close()


def cmd_seed_demo(_args) -> int:
    from .seed import seed_demo
    if settings.environment == "production":
        print("Refusing to load demo data when ENVIRONMENT=production")
        return 1
    db = SessionLocal()
    try:
        print("Demo data created:", seed_demo(db))
    finally:
        db.close()
    return 0



def cmd_backup(_args) -> int:
    from .data_management import create_backup
    import json
    try:
        print(json.dumps(create_backup(), indent=2))
        return 0
    except Exception as exc:
        print("ERROR:", str(exc))
        return 1


def cmd_backup_list(_args) -> int:
    from .data_management import list_backups
    import json
    print(json.dumps(list_backups(), indent=2))
    return 0


def cmd_restore_backup(args) -> int:
    from .data_management import restore_backup
    if not args.confirm_restore:
        print("Refusing restore without --confirm-restore")
        return 2
    try:
        import json
        print(json.dumps(restore_backup(args.filename, confirmed=True), indent=2))
        return 0
    except Exception as exc:
        print("ERROR:", str(exc))
        return 1

# ----------------------------------------------------------------------------- V7 live-system commands
def _print_records(res: dict) -> None:
    print(f"Register number : {res['register_number']}")
    print(f"Result          : {res['status']}  -  {res.get('message', '')}")
    print(f"Last synchronised: {res.get('last_synchronised_at') or 'never'}")
    for r in res["records"]:
        print("-" * 60)
        print(f"  {r['date']} ({r['weekday']}) {r['session']}   {r['subject_code'] or '-'} {r['subject_name'] or ''}")
        print(f"  Programme/Dept: {r['programme'] or '-'} / {r['department'] or '-'}")
        print(f"  Hall: {r['hall'] or '-'}   Seat: {r['seat'] or '-'}   [{r['status']}] {r['status_label']}")
        for n in r["notes"]:
            print(f"  note: {n}")
        for s in r["sources"]:
            print(f"  {s['label']}: {s['filename']} page {s['page']}  {s['official_url'] or ''}")


def cmd_search(args) -> int:
    from .regno import normalize_register_number
    from .routers.public_live import lookup
    try:
        reg = normalize_register_number(args.register_number)
    except ValueError as e:
        print("ERROR:", e)
        return 2
    with SessionLocal() as db:
        res = lookup(db, reg)
    if args.json:
        import json
        print(json.dumps(res, indent=2, default=str))
    else:
        _print_records(res)
    return 0 if res["records"] else 1


def cmd_run_cycle(args) -> int:
    """One full monitoring cycle (discover, download, validate, parse, index, notify, optional sync)."""
    import json
    from .vsb_live import cycle
    try:
        out = cycle.run_cycle(trigger="cli", actor="cli", rebuild=args.rebuild)
    except RuntimeError:
        print("Another cycle is already running")
        return 3
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("status") != "failed" else 1


def cmd_discover(args) -> int:
    """Discover official PDF links only (nothing is downloaded)."""
    from . import vsb_sources as vs
    with SessionLocal() as db:
        run = vs.run_discovery(db, actor="cli", trigger="cli", download=False, auto_process=None)
    print(run["status"], "-", run["links_found"], "links,", run["new_links"], "new.", run["message"] or "")
    return 0 if run["status"] != "failed" else 1


def cmd_download(args) -> int:
    """Download every discovered allotment PDF that is new or changed (no parsing)."""
    from . import vsb_sources as vs
    with SessionLocal() as db:
        run = vs.run_discovery(db, actor="cli", trigger="cli", download=True, auto_process=None)
    print(run["status"], "-", run["downloaded"], "downloaded,", run["duplicates"], "duplicates,", run["failed"], "failed.", run["message"] or "")
    return 0 if run["status"] != "failed" else 1


def cmd_ingest_pdf(args) -> int:
    """Ingest a local PDF as if it had been downloaded (then parse and index)."""
    from .vsb_live import pipeline
    with SessionLocal() as db:
        try:
            v = pipeline.import_local_pdf(db, args.path, args.kind, source_url=args.source_url, actor="cli")
        except (ValueError, OSError, Exception) as e:  # noqa: BLE001
            print("ERROR:", getattr(e, "args", [e])[0] if e.args else type(e).__name__)
            return 1
        vid, vsha = v.id, v.sha256
        ing = pipeline.ingest_pending(db)
        r = pipeline.rebuild_index(db) if ing["parsed"] else {"stats": {}}
    print("version", vid, "sha256", vsha[:16], "| parsed:", ing, "| index:", r["stats"])
    return 0 if not ing["failed"] else 1


def cmd_test_pair(args) -> int:
    """Parse a hall PDF and a seating PDF (no database) and show how they reconcile."""
    from collections import Counter
    from .vsb_live import pipeline as P
    hp, _ = P.read_pages_with_ocr(args.hall)
    sp, _ = P.read_pages_with_ocr(args.seat)
    hd, sd = P.parse_hall_pdf(hp), P.parse_seat_pdf(sp)
    print("hall sessions:", hd.sessions, "| seat sessions:", sd.sessions)
    for d, s in sorted(set(hd.sessions) & set(sd.sessions), key=str):
        rec = P.reconcile(hd, sd, d, s, None)
        st = Counter(P.classify(r.flags, hall_doc_present=True, seat_doc_present=True, has_hall=bool(r.hall_pdf_hall),
                                has_seat=r.seat is not None) for r in rec.records)
        print(f"{d} {s}: {len(rec.records)} students; ", dict(st), "; errors:", sum(1 for i in rec.issues if i.severity == "error"))
        for i in [i for i in rec.issues if i.severity == "error"][:10]:
            print("   -", i.kind, i.message[:140])
    return 0


def cmd_status(_args) -> int:
    from .vsb_live import cycle
    from sqlalchemy import func
    from . import doc_models as dm
    with SessionLocal() as db:
        st = cycle.status_summary(db)
        print("Last scan        :", st["last_scan_at"], st["last_scan_status"])
        print("Last success     :", st["last_success_at"])
        print("Poll interval    :", settings.poll_minutes, "minutes")
        print("Records indexed  :", db.scalar(select(func.count()).select_from(dm.LiveAllotment).where(dm.LiveAllotment.is_current == True)))  # noqa: E712
        for h in db.scalars(select(dm.VsbSourceHealth)).all():
            print(f"  source {h.method:9} {h.last_status:7} fails={h.consecutive_failures} items={h.items_found}  {h.url[:70]}")
    return 0


def cmd_test_email(args) -> int:
    from .vsb_live import notify
    r = notify.send_test(args.to)
    print(r["status"], "-", r["message"])
    return 0 if r["status"] == "sent" else 1


def cmd_health(_args) -> int:
    """Health check used by health_check.bat, Docker and CI. Exit code 0 = healthy."""
    from sqlalchemy import text
    from . import doc_extract as dx, mailer
    from .dbcheck import current_revision, head_revision
    from .routers import docproc
    ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        print("database        : reachable")
    except Exception as e:  # noqa: BLE001
        print("database        : FAILED", type(e).__name__)
        return 1
    rev, head = current_revision(), head_revision()
    print(f"migrations      : {rev} (head {head})", "OK" if rev == head else "-> run: python -m app.cli migrate")
    ok &= rev == head
    try:
        t = docproc.storage_dir() / ".health"
        t.write_bytes(b"1")
        t.unlink()
        print("document storage: writable")
    except OSError:
        print("document storage: NOT writable")
        ok = False
    print("OCR (Tesseract) :", "available" if dx.ocr_available() else "not installed (text PDFs still work)")
    print("e-mail mode     :", mailer.mail_mode())
    print("supabase mirror :", "configured" if settings.supabase_enabled else "off (optional)")
    problems = check_secret_key(settings.secret_key)
    for p in problems:
        print("secret key      : PROBLEM -", p)
    ok &= not problems
    print("HEALTHY" if ok else "NOT HEALTHY")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("search", help="search one register number (same result as the public website)")
    sc.add_argument("register_number")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(fn=cmd_search)
    rc = sub.add_parser("run-cycle", help="one full monitoring cycle: discover, download, validate, parse, index, notify")
    rc.add_argument("--rebuild", action="store_true", help="re-index even when nothing new was downloaded")
    rc.set_defaults(fn=cmd_run_cycle)
    sub.add_parser("discover", help="discover official PDF links (no download)").set_defaults(fn=cmd_discover)
    sub.add_parser("download", help="download new/changed discovered PDFs (no parsing)").set_defaults(fn=cmd_download)
    ip = sub.add_parser("ingest-pdf", help="ingest a local hall/seat PDF, parse it and update the index")
    ip.add_argument("path")
    ip.add_argument("--kind", choices=["hall", "seat"], required=True)
    ip.add_argument("--source-url", default=None, help="official address of the PDF, if known")
    ip.set_defaults(fn=cmd_ingest_pdf)
    tp = sub.add_parser("test-pair", help="parse a hall PDF + a seating PDF (no database) and show the match")
    tp.add_argument("hall")
    tp.add_argument("seat")
    tp.set_defaults(fn=cmd_test_pair)
    sub.add_parser("status", help="monitoring status and source health").set_defaults(fn=cmd_status)
    te = sub.add_parser("test-email", help="send a test e-mail through the configured SMTP / outbox")
    te.add_argument("to")
    te.set_defaults(fn=cmd_test_email)
    sub.add_parser("health", help="health check (database, migrations, storage, OCR, mail)").set_defaults(fn=cmd_health)
    sub.add_parser("gen-secret", help="print a new random SECRET_KEY").set_defaults(fn=cmd_gen_secret)
    sub.add_parser("init-env", help="create .env with a generated SECRET_KEY").set_defaults(fn=cmd_init_env)
    sub.add_parser("check-config", help="validate settings").set_defaults(fn=cmd_check_config)
    sub.add_parser("db-audit", help="read-only schema/data-integrity report").set_defaults(fn=cmd_db_audit)
    sub.add_parser("migrate", help="create/upgrade the database schema").set_defaults(fn=cmd_migrate)
    sub.add_parser("backup", help="create a verified database and uploads backup").set_defaults(fn=cmd_backup)
    sub.add_parser("backup-list", help="list and verify available backups").set_defaults(fn=cmd_backup_list)
    rb = sub.add_parser("restore-backup", help="restore a verified backup while the application is stopped")
    rb.add_argument("filename", help="backup ZIP filename from backend/backups")
    rb.add_argument("--confirm-restore", action="store_true", help="confirm replacement; a safety backup is created first")
    rb.set_defaults(fn=cmd_restore_backup)
    a = sub.add_parser("create-admin", help="create an administrator account")
    a.add_argument("--username", default="admin")
    a.add_argument("--role", default="admin", choices=["admin", "super_admin"],
                   help="admin = Examination administrator, super_admin = Super administrator")
    a.set_defaults(fn=cmd_create_admin)
    u = sub.add_parser("unlock-user", help="clear a login lockout")
    u.add_argument("username")
    u.set_defaults(fn=cmd_unlock)
    r = sub.add_parser("reset-password", help="set a new password for an existing user")
    r.add_argument("username")
    r.set_defaults(fn=cmd_reset_password)
    sub.add_parser("seed-demo", help="load synthetic demo students/exam (no login account)").set_defaults(fn=cmd_seed_demo)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
