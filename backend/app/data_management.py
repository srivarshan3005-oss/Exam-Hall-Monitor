"""Phase 8.2 data management: verified backups, safe restore, exports, imports and integrity checks.

Restore is deliberately CLI-only: replacing a live database from an HTTP request is unsafe while
other workers may hold sessions. Administrative HTTP routes can create/list backups and inspect data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, models
from .config import settings
from .database import engine

BACKEND_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BACKEND_DIR / "backups"
UPLOAD_DIR = Path(settings.document_storage_dir).resolve() if settings.document_storage_dir else BACKEND_DIR / "uploads"
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
STUDENT_COLUMNS = ("register_number", "full_name", "department", "year", "email", "course")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pg_env(url):
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    # libpq connection parameters are environment variables, not pg_dump/pg_restore flags.
    for key, env_name in (("sslmode", "PGSSLMODE"), ("sslrootcert", "PGSSLROOTCERT"),
                          ("sslcert", "PGSSLCERT"), ("sslkey", "PGSSLKEY"),
                          ("connect_timeout", "PGCONNECT_TIMEOUT")):
        if key in url.query:
            env[env_name] = str(url.query[key])
    return env


def _pg_args(url) -> list[str]:
    args = ["--no-password"]
    for key, flag in (("host", "--host"), ("port", "--port"), ("username", "--username"), ("database", "--dbname")):
        value = getattr(url, key)
        if value is not None:
            args.extend([flag, str(value)])
    return args


def _copy_uploads(zf: zipfile.ZipFile) -> list[dict[str, str]]:
    entries = []
    if UPLOAD_DIR.exists():
        for path in sorted(UPLOAD_DIR.rglob("*")):
            if path.is_file() and not path.is_symlink():
                rel = path.relative_to(UPLOAD_DIR).as_posix()
                arc = "uploads/" + rel
                zf.write(path, arcname=arc)
                entries.append({"path": arc, "sha256": _sha256(path)})
    return entries


def create_backup() -> dict[str, Any]:
    """Create a ZIP containing a consistent DB snapshot/dump, uploads and SHA-256 manifest."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = BACKUP_DIR / f"exam-monitor-backup-{stamp}.zip"
    url = make_url(str(engine.url))
    with tempfile.TemporaryDirectory(prefix="exam-monitor-backup-") as td:
        tmp = Path(td)
        db_file = tmp / ("database.sqlite3" if url.get_backend_name() == "sqlite" else "database.dump")
        if url.get_backend_name() == "sqlite":
            db_path = Path(url.database or "")
            if not db_path.is_absolute():
                db_path = (Path.cwd() / db_path).resolve()
            if not db_path.is_file():
                raise FileNotFoundError(f"Configured SQLite database does not exist: {db_path}")
            src = sqlite3.connect(str(db_path), timeout=30)
            dst = sqlite3.connect(str(db_file))
            try:
                src.backup(dst)
                check = dst.execute("PRAGMA quick_check").fetchone()[0]
                if check != "ok":
                    raise RuntimeError(f"SQLite backup integrity check failed: {check}")
            finally:
                dst.close()
                src.close()
            db_kind = "sqlite"
        elif url.get_backend_name() == "postgresql":
            exe = shutil.which("pg_dump")
            if not exe:
                raise RuntimeError("pg_dump is required for PostgreSQL backups; install PostgreSQL client tools")
            cmd = [exe, "--format=custom", "--no-owner", "--no-acl", *_pg_args(url), "--file", str(db_file)]
            run = subprocess.run(cmd, env=_pg_env(url), capture_output=True, text=True, timeout=600)
            if run.returncode:
                raise RuntimeError("pg_dump failed: " + (run.stderr[-1200:] or "unknown error"))
            db_kind = "postgresql"
        else:
            raise RuntimeError("Unsupported database backend")

        manifest = {"format_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                    "database_type": db_kind, "database_file": db_file.name,
                    "database_sha256": _sha256(db_file), "uploads": []}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(db_file, arcname=db_file.name)
            manifest["uploads"] = _copy_uploads(zf)
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    os.chmod(target, 0o600)
    verify_backup(target)
    return {"filename": target.name, "size_bytes": target.stat().st_size, "sha256": _sha256(target),
            "created_at": datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat(),
            "database_type": db_kind}


def verify_backup(path: Path) -> dict[str, Any]:
    """Verify ZIP structure, safe member names, manifest and every file digest."""
    with zipfile.ZipFile(path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise ValueError(f"Backup ZIP CRC failed for {bad}")
        names = zf.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Backup contains duplicate archive paths")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError("Backup contains an unsafe path")
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format_version") != 1:
            raise ValueError("Unsupported backup format")
        expected = [manifest["database_file"], *(x["path"] for x in manifest.get("uploads", []))]
        if any(n not in names for n in expected):
            raise ValueError("Backup is missing a manifest-listed file")
        for item in [{"path": manifest["database_file"], "sha256": manifest["database_sha256"]}, *manifest.get("uploads", [])]:
            if hashlib.sha256(zf.read(item["path"])).hexdigest() != item["sha256"]:
                raise ValueError(f"Backup checksum mismatch: {item['path']}")
        return manifest


def list_backups() -> list[dict[str, Any]]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(BACKUP_DIR.glob("exam-monitor-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        item = {"filename": path.name, "size_bytes": path.stat().st_size,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
        try:
            manifest = verify_backup(path)
            item.update({"verified": True, "database_type": manifest["database_type"], "sha256": _sha256(path)})
        except Exception as exc:
            item.update({"verified": False, "error": str(exc)[:200]})
        out.append(item)
    return out


def restore_backup(filename: str, *, confirmed: bool = False) -> dict[str, Any]:
    """Restore from a verified backup. Must be run offline from CLI with explicit confirmation."""
    if not confirmed:
        raise ValueError("Restore requires --confirm-restore")
    if Path(filename).name != filename or not filename.endswith(".zip"):
        raise ValueError("Invalid backup filename")
    archive = BACKUP_DIR / filename
    if not archive.is_file():
        raise FileNotFoundError("Backup not found")
    manifest = verify_backup(archive)
    target_url = make_url(str(engine.url))
    if target_url.get_backend_name() != manifest["database_type"]:
        raise ValueError("Backup database type does not match the configured database")
    # A safety snapshot of the current state is always created before any restore.
    safety = create_backup()
    with tempfile.TemporaryDirectory(prefix="exam-monitor-restore-") as td:
        tmp = Path(td)
        with zipfile.ZipFile(archive) as zf:
            db_bytes = zf.read(manifest["database_file"])
            staged = tmp / manifest["database_file"]
            staged.write_bytes(db_bytes)
            if manifest["database_type"] == "sqlite":
                check = sqlite3.connect(str(staged))
                try:
                    result = check.execute("PRAGMA quick_check").fetchone()[0]
                    if result != "ok":
                        raise ValueError(f"Restored SQLite database failed integrity check: {result}")
                finally:
                    check.close()
                db_path = Path(target_url.database or "")
                if not db_path.is_absolute():
                    db_path = (Path.cwd() / db_path).resolve()
                engine.dispose()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                replacement = db_path.with_name(db_path.name + ".restore-tmp")
                shutil.copy2(staged, replacement)
                os.replace(replacement, db_path)
            else:
                exe = shutil.which("pg_restore")
                if not exe:
                    raise RuntimeError("pg_restore is required; install PostgreSQL client tools")
                cmd = [exe, "--clean", "--if-exists", "--no-owner", "--no-acl", *_pg_args(target_url), str(staged)]
                run = subprocess.run(cmd, env=_pg_env(target_url), capture_output=True, text=True, timeout=900)
                if run.returncode:
                    raise RuntimeError("pg_restore failed; safety backup retained: " + (run.stderr[-1200:] or "unknown error"))
            # Upload restoration is staged and path-checked; files not in the archive are left untouched.
            upload_root = tmp / "uploads"
            upload_root.mkdir()
            for item in manifest.get("uploads", []):
                rel = PurePosixPath(item["path"]).relative_to("uploads")
                dest = upload_root.joinpath(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(item["path"]))
            if manifest.get("uploads"):
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                for src in upload_root.rglob("*"):
                    if src.is_file():
                        dest = UPLOAD_DIR / src.relative_to(upload_root)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
    return {"restored": filename, "safety_backup": safety["filename"], "database_type": manifest["database_type"]}



def prune_backups(retain: int | None = None) -> dict[str, int]:
    """Remove only older verified archives; corrupt archives are retained for manual investigation."""
    keep = settings.backup_retention_count if retain is None else max(0, int(retain))
    candidates = []
    for path in sorted(BACKUP_DIR.glob("exam-monitor-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            verify_backup(path)
            candidates.append(path)
        except Exception:
            continue
    removed = 0
    if keep > 0:
        for path in candidates[keep:]:
            path.unlink(missing_ok=True)
            removed += 1
    return {"verified_backups": len(candidates), "removed": removed, "retained": min(len(candidates), keep) if keep else len(candidates)}


def run_scheduled_backup(now: datetime | None = None) -> dict[str, Any] | None:
    """Create a backup when the configured interval elapsed; disabled by default."""
    if not settings.backup_schedule_enabled:
        return None
    now = now or datetime.now(timezone.utc)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    latest = max(BACKUP_DIR.glob("exam-monitor-backup-*.zip"), key=lambda p: p.stat().st_mtime, default=None)
    interval = max(1, int(settings.backup_interval_hours)) * 3600
    if latest is not None and now.timestamp() - latest.stat().st_mtime < interval:
        return None
    result = create_backup()
    result["retention"] = prune_backups()
    return result

def _student_rows(db: Session, limit: int = 10000, offset: int = 0) -> list[dict[str, Any]]:
    return [{"register_number": s.register_number, "full_name": s.full_name, "department": s.department,
             "year": s.year, "email": s.email, "course": s.course}
            for s in db.scalars(select(models.Student).order_by(models.Student.register_number).limit(limit).offset(offset)).all()]


def export_dataset(db: Session, dataset: str, limit: int = 10000, offset: int = 0) -> tuple[list[str], list[list[Any]], list[dict[str, Any]]]:
    if dataset == "students":
        data = _student_rows(db, limit, offset); cols = list(STUDENT_COLUMNS)
        return cols, [[x.get(c) for c in cols] for x in data], data
    if dataset == "exams":
        data = [{"id": e.id, "title": e.title, "subject_code": e.subject_code, "exam_date": e.exam_date,
                 "start_time": e.start_time, "end_time": e.end_time, "venue": e.venue, "status": e.status}
                for e in db.scalars(select(models.Exam).order_by(models.Exam.id).limit(limit).offset(offset)).all()]
    elif dataset == "results":
        data = [{"student_id": r.student_id, "exam_id": r.exam_id, "marks": r.marks, "max_marks": r.max_marks,
                 "grade": r.grade, "published": r.published}
                for r in db.scalars(select(models.Result).order_by(models.Result.id).limit(limit).offset(offset)).all()]
    elif dataset == "allotments":
        data = [{"student_id": a.student_id, "exam_id": a.exam_id, "hall": a.hall, "seat": a.seat}
                for a in db.scalars(select(models.Allotment).order_by(models.Allotment.id).limit(limit).offset(offset)).all()]
    else:
        raise ValueError("Unsupported export dataset")
    cols = list(data[0]) if data else ({"exams": ["id", "title", "subject_code", "exam_date", "start_time", "end_time", "venue", "status"],
                                       "results": ["student_id", "exam_id", "marks", "max_marks", "grade", "published"],
                                       "allotments": ["student_id", "exam_id", "hall", "seat"]}[dataset])
    return cols, [[x.get(c) for c in cols] for x in data], data


def parse_student_import(filename: str, content: bytes) -> list[dict[str, Any]]:
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("Import file exceeds 10 MB")
    ext = Path(filename).suffix.lower()
    if ext == ".json":
        raw = json.loads(content.decode("utf-8-sig"))
        if not isinstance(raw, list):
            raise ValueError("JSON import must be an array of student objects")
        records = raw
    elif ext == ".csv":
        text_data = content.decode("utf-8-sig")
        records = list(csv.DictReader(io.StringIO(text_data)))
    elif ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = [str(x).strip() if x is not None else "" for x in next(rows, ())]
        records = [dict(zip(header, row)) for row in rows]
        wb.close()
    else:
        raise ValueError("Only CSV, XLSX and JSON imports are supported")
    if len(records) > MAX_IMPORT_ROWS:
        raise ValueError(f"Import exceeds {MAX_IMPORT_ROWS} rows")
    cleaned = []
    for idx, item in enumerate(records, 2):
        if not isinstance(item, dict):
            raise ValueError(f"Row {idx} is not an object")
        cleaned.append({str(k).strip(): v for k, v in item.items()})
    return cleaned


def preview_student_import(db: Session, records: list[dict[str, Any]]) -> dict[str, Any]:
    existing = {x.casefold() for x in db.scalars(select(models.Student.register_number)).all()}
    seen: set[str] = set(); valid = []; errors = []
    for n, row in enumerate(records, 2):
        reg = str(row.get("register_number") or "").strip()
        name = str(row.get("full_name") or "").strip()
        dept = str(row.get("department") or "").strip()
        try:
            year = int(row.get("year") or 1)
        except (TypeError, ValueError):
            year = 0
        problems = []
        if not reg or len(reg) > 30: problems.append("register_number is required (max 30 characters)")
        if not name or len(name) > 150: problems.append("full_name is required (max 150 characters)")
        if not dept or len(dept) > 100: problems.append("department is required (max 100 characters)")
        if year < 1 or year > 8: problems.append("year must be between 1 and 8")
        key = reg.casefold()
        if key in existing: problems.append("register number already exists")
        if key in seen: problems.append("duplicate register number within this file")
        seen.add(key)
        email = str(row.get("email") or "").strip() or None
        course = str(row.get("course") or "").strip() or None
        if email and len(email) > 150: problems.append("email exceeds 150 characters")
        if course and len(course) > 100: problems.append("course exceeds 100 characters")
        if problems:
            errors.append({"row": n, "register_number": reg, "errors": problems})
        else:
            valid.append({"register_number": reg, "full_name": name, "department": dept,
                          "year": year, "email": email, "course": course})
    return {"total_rows": len(records), "valid_rows": len(valid), "invalid_rows": len(errors),
            "errors": errors[:500], "preview": valid[:100]}


def commit_student_import(db: Session, records: list[dict[str, Any]], actor: models.User) -> dict[str, int]:
    report = preview_student_import(db, records)
    if report["invalid_rows"]:
        raise ValueError("Import contains invalid rows; correct them and preview again")
    # Rebuild the complete validated row set (the preview response is intentionally capped at 100 rows).
    existing = {x.casefold() for x in db.scalars(select(models.Student.register_number)).all()}
    rows = []
    for row in records:
        reg = str(row.get("register_number") or "").strip()
        key = reg.casefold()
        if key in existing:
            raise ValueError("Import conflicts with a register number added after preview; preview again")
        existing.add(key)
        rows.append(models.Student(register_number=reg, full_name=str(row["full_name"]).strip(),
                                   department=str(row["department"]).strip(), year=int(row.get("year") or 1),
                                   email=(str(row.get("email") or "").strip() or None),
                                   course=(str(row.get("course") or "").strip() or None)))
    try:
        db.add_all(rows)
        audit.record(db, actor.username, "data.students_imported", "students", {"rows": len(rows)}, role=actor.role)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Import conflicted with existing data; no rows were imported") from exc
    return {"imported": len(rows), "rejected": 0}


def integrity_report(db: Session) -> dict[str, Any]:
    checks = []
    def add(code: str, label: str, count: int, detail: str):
        checks.append({"code": code, "label": label, "count": int(count), "detail": detail})
    dup_students = db.execute(text("SELECT COUNT(*) FROM (SELECT lower(register_number) FROM students GROUP BY lower(register_number) HAVING COUNT(*) > 1) q")).scalar() or 0
    add("duplicate_student_registers", "Duplicate student register numbers", dup_students, "Must be resolved before importing more student records.")
    dup_links = db.execute(text("SELECT COUNT(*) FROM (SELECT student_id FROM users WHERE student_id IS NOT NULL GROUP BY student_id HAVING COUNT(*) > 1) q")).scalar() or 0
    add("duplicate_student_accounts", "Students linked to multiple accounts", dup_links, "Each student should have at most one login account.")
    orphan_alloc = db.execute(text("SELECT COUNT(*) FROM allotments a LEFT JOIN students s ON s.id=a.student_id LEFT JOIN exams e ON e.id=a.exam_id WHERE s.id IS NULL OR e.id IS NULL")).scalar() or 0
    add("orphan_allocations", "Allocations with missing student or exam", orphan_alloc, "Review source records; no automatic deletion is performed.")
    orphan_results = db.execute(text("SELECT COUNT(*) FROM results r LEFT JOIN students s ON s.id=r.student_id LEFT JOIN exams e ON e.id=r.exam_id WHERE s.id IS NULL OR e.id IS NULL")).scalar() or 0
    add("orphan_results", "Results with missing student or exam", orphan_results, "Review source records; no automatic deletion is performed.")
    bad_marks = db.execute(text("SELECT COUNT(*) FROM results WHERE marks < 0 OR max_marks <= 0 OR marks > max_marks")).scalar() or 0
    add("invalid_result_marks", "Results outside marks range", bad_marks, "Marks must be between zero and max_marks.")
    blank_seats = db.execute(text("SELECT COUNT(*) FROM allotments WHERE trim(hall)='' OR trim(seat)=''")).scalar() or 0
    add("blank_allotment_location", "Allocations with blank hall or seat", blank_seats, "Hall and seat must both be populated.")
    orphan_user_students = db.execute(text("SELECT COUNT(*) FROM users u LEFT JOIN students s ON s.id=u.student_id WHERE u.student_id IS NOT NULL AND s.id IS NULL")).scalar() or 0
    add("orphan_student_accounts", "Student accounts without a student record", orphan_user_students, "Repair the student link or account through an authorized administrative workflow.")
    duplicate_seats = db.execute(text("SELECT COUNT(*) FROM (SELECT exam_id, upper(trim(hall)), upper(trim(seat)) FROM allotments GROUP BY exam_id, upper(trim(hall)), upper(trim(seat)) HAVING COUNT(*) > 1) q")).scalar() or 0
    add("duplicate_exam_seats", "Duplicate hall/seat assignments within an examination", duplicate_seats, "A physical seat can be assigned only once per examination.")
    invalid_exam_times = 0
    exam_rows = db.execute(select(models.Exam.exam_date, models.Exam.start_time, models.Exam.end_time)).all()
    from datetime import date as _date, time as _time
    for exam_date, start_time, end_time in exam_rows:
        try:
            _date.fromisoformat(str(exam_date))
            start = _time.fromisoformat(str(start_time))
            end = _time.fromisoformat(str(end_time))
            if start >= end:
                invalid_exam_times += 1
        except (TypeError, ValueError):
            invalid_exam_times += 1
    add("invalid_exam_schedule", "Examinations with invalid dates or times", invalid_exam_times, "Dates must be ISO YYYY-MM-DD and start time must precede end time.")
    allocations = db.execute(text("SELECT a.student_id, e.exam_date, e.start_time, e.end_time, e.id FROM allotments a JOIN exams e ON e.id=a.exam_id ORDER BY a.student_id, e.exam_date, e.start_time")).all()
    overlaps = 0
    parsed = []
    for student_id, exam_date, start_time, end_time, exam_id in allocations:
        try:
            from datetime import datetime as _datetime
            start = _datetime.fromisoformat(f"{exam_date}T{start_time}")
            end = _datetime.fromisoformat(f"{exam_date}T{end_time}")
            parsed.append((student_id, exam_id, start, end))
        except (TypeError, ValueError):
            continue
    for i, (student_id, exam_id, start, end) in enumerate(parsed):
        for other_student, other_exam, other_start, other_end in parsed[i + 1:]:
            if other_student != student_id:
                if other_student > student_id:
                    break
                continue
            if other_exam != exam_id and start.date() == other_start.date() and start < other_end and other_start < end:
                overlaps += 1
    add("overlapping_student_allocations", "Students allocated to overlapping examinations", overlaps, "Review timetable and allocation history; no records are moved automatically.")
    fk_violations = 0
    if engine.dialect.name == "sqlite":
        fk_violations = len(db.execute(text("PRAGMA foreign_key_check")).all())
    add("foreign_key_violations", "Foreign-key violations", fk_violations,
        "SQLite PRAGMA foreign_key_check; PostgreSQL relies on enforced FK constraints.")
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "issue_count": sum(x["count"] for x in checks), "healthy": all(x["count"] == 0 for x in checks)}
