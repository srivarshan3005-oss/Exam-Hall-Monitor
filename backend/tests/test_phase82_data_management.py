import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app import models
from app.data_management import (create_backup, integrity_report, list_backups, parse_student_import,
                                 preview_student_import, commit_student_import, verify_backup)
from conftest import make_student, make_user, login, STRONG


def test_student_import_preview_detects_required_fields_duplicates_and_existing(db):
    make_student(db, "EXISTING-1")
    rows = [
        {"register_number": "EXISTING-1", "full_name": "A", "department": "CSE", "year": 1},
        {"register_number": "NEW-1", "full_name": "B", "department": "CSE", "year": 2},
        {"register_number": "NEW-1", "full_name": "C", "department": "ECE", "year": 2},
        {"register_number": "", "full_name": "Missing", "department": "CSE", "year": 1},
    ]
    result = preview_student_import(db, rows)
    assert result["total_rows"] == 4
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 3
    assert "register number already exists" in result["errors"][0]["errors"]


def test_student_import_commit_is_atomic_and_imports_all_rows(db):
    admin = make_user(db, "importadmin", "admin")
    rows = [{"register_number": f"BULK-{i}", "full_name": f"Student {i}", "department": "CSE", "year": 2}
            for i in range(125)]
    result = commit_student_import(db, rows, admin)
    assert result == {"imported": 125, "rejected": 0}
    assert db.scalar(select(models.Student).where(models.Student.register_number == "BULK-124")) is not None


def test_student_import_rejects_invalid_batch_without_partial_writes(db):
    admin = make_user(db, "importadmin2", "admin")
    rows = [{"register_number": "GOOD-1", "full_name": "Good", "department": "CSE", "year": 2},
            {"register_number": "BAD-1", "full_name": "Bad", "department": "", "year": 2}]
    with pytest.raises(ValueError):
        commit_student_import(db, rows, admin)
    assert db.scalar(select(models.Student).where(models.Student.register_number == "GOOD-1")) is None


def test_parse_csv_json_and_xlsx_imports():
    import io
    from openpyxl import Workbook
    csv_data = b"register_number,full_name,department,year\nCSV-1,Name,CSE,2\n"
    assert parse_student_import("students.csv", csv_data)[0]["register_number"] == "CSV-1"
    json_data = json.dumps([{"register_number": "JSON-1", "full_name": "Name", "department": "CSE", "year": 2}]).encode()
    assert parse_student_import("students.json", json_data)[0]["register_number"] == "JSON-1"
    wb = Workbook(); ws = wb.active
    ws.append(["register_number", "full_name", "department", "year"])
    ws.append(["XLSX-1", "Name", "CSE", 2])
    buf = io.BytesIO(); wb.save(buf)
    assert parse_student_import("students.xlsx", buf.getvalue())[0]["register_number"] == "XLSX-1"


def test_backup_creation_manifest_and_listing(db, tmp_path, monkeypatch):
    import app.data_management as dm
    backup_dir = tmp_path / "backups"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    (upload_dir / "sample.pdf").write_bytes(b"synthetic upload")
    monkeypatch.setattr(dm, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(dm, "UPLOAD_DIR", upload_dir)
    result = create_backup()
    path = backup_dir / result["filename"]
    manifest = verify_backup(path)
    assert manifest["database_type"] == "sqlite"
    assert manifest["uploads"][0]["path"] == "uploads/sample.pdf"
    assert list_backups()[0]["verified"] is True
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None


def test_backup_rejects_corrupt_archive(tmp_path):
    p = tmp_path / "broken.zip"
    p.write_bytes(b"not a zip")
    with pytest.raises(Exception):
        verify_backup(p)


def test_integrity_report_is_read_only_and_healthy_for_empty_database(db):
    before = db.query(models.Student).count()
    report = integrity_report(db)
    after = db.query(models.Student).count()
    assert before == after
    assert report["issue_count"] == 0


def test_admin_data_routes_require_admin(client, db):
    make_user(db, "ordinary-staff", "staff")
    headers = login(client, "ordinary-staff", STRONG)
    assert client.get("/api/admin/data/status", headers=headers).status_code == 403


def test_admin_data_routes_backup_integrity_and_export(client, db, admin, tmp_path, monkeypatch):
    import app.data_management as dm
    monkeypatch.setattr(dm, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(dm, "UPLOAD_DIR", tmp_path / "uploads")
    make_student(db, "EXPORT-1")
    status = client.get("/api/admin/data/status", headers=admin)
    assert status.status_code == 200 and status.json()["connected"] is True
    integrity = client.get("/api/admin/data/integrity", headers=admin)
    assert integrity.status_code == 200 and "checks" in integrity.json()
    exported = client.get("/api/admin/data/export/students?format=json", headers=admin)
    assert exported.status_code == 200 and exported.json()["count"] == 1
    backup = client.post("/api/admin/data/backups", headers=admin)
    assert backup.status_code == 201, backup.text
    assert backup.json()["filename"].endswith(".zip")


def test_student_import_api_preview_then_explicit_commit(client, admin):
    data = {"file": ("students.csv", b"register_number,full_name,department,year\nAPI-1,Api Student,CSE,2", "text/csv")}
    preview = client.post("/api/admin/data/import/students?mode=preview", headers=admin, files=data)
    assert preview.status_code == 200 and preview.json()["valid_rows"] == 1
    data = {"file": ("students.csv", b"register_number,full_name,department,year\nAPI-1,Api Student,CSE,2", "text/csv")}
    denied = client.post("/api/admin/data/import/students?mode=commit", headers=admin, files=data)
    assert denied.status_code == 400
    data = {"file": ("students.csv", b"register_number,full_name,department,year\nAPI-1,Api Student,CSE,2", "text/csv")}
    committed = client.post("/api/admin/data/import/students?mode=commit&confirm=true", headers=admin, files=data)
    assert committed.status_code == 200, committed.text
    assert committed.json()["imported"] == 1


def test_sqlite_restore_requires_confirmation_and_creates_safety_backup(tmp_path, monkeypatch):
    import app.data_management as dm
    from sqlalchemy import create_engine, text
    db_path = tmp_path / "restore-target.sqlite3"
    test_engine = create_engine("sqlite:///" + db_path.as_posix())
    with test_engine.begin() as conn:
        conn.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO sample VALUES (1, 'before')"))
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(dm, "engine", test_engine)
    monkeypatch.setattr(dm, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(dm, "UPLOAD_DIR", tmp_path / "uploads")
    backup = dm.create_backup()
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE sample SET value='after' WHERE id=1"))
    with pytest.raises(ValueError):
        dm.restore_backup(backup["filename"], confirmed=False)
    restored = dm.restore_backup(backup["filename"], confirmed=True)
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM sample WHERE id=1")).scalar_one() == "before"
    assert restored["safety_backup"] != backup["filename"]
    test_engine.dispose()


def test_scheduled_backup_interval_and_retention(tmp_path, monkeypatch):
    import app.data_management as dm
    from app.config import settings
    from datetime import datetime, timezone, timedelta
    monkeypatch.setattr(dm, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(dm, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "backup_schedule_enabled", True)
    monkeypatch.setattr(settings, "backup_interval_hours", 24)
    monkeypatch.setattr(settings, "backup_retention_count", 2)
    now = datetime.now(timezone.utc) + timedelta(seconds=2)
    first = dm.run_scheduled_backup(now)
    assert first and first["filename"].endswith(".zip")
    assert dm.run_scheduled_backup(now + timedelta(hours=1)) is None
    # Build extra valid archives, then ensure only the configured newest verified set is retained.
    dm.create_backup(); dm.create_backup()
    result = dm.prune_backups()
    assert result["removed"] >= 1
    assert len([x for x in dm.list_backups() if x["verified"]]) == 2
