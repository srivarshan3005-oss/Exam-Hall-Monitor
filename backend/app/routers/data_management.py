"""Administrator-only data management endpoints (Phase 8.2)."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from .. import audit, models
from ..database import get_db
from ..deps import require_roles
from ..data_management import (BACKUP_DIR, MAX_IMPORT_BYTES, create_backup, export_dataset,
                               integrity_report, list_backups, parse_student_import,
                               preview_student_import, commit_student_import)
from ..exports import tabular

router = APIRouter(prefix="/api/admin/data", tags=["Database and data management"])


@router.get("/status")
def data_status(db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    from ..dbcheck import current_revision, head_revision
    from ..database import engine
    from sqlalchemy import inspect, text
    db.execute(text("SELECT 1"))
    pool = engine.pool
    return {"database_type": engine.dialect.name, "connected": True,
            "migration_revision": current_revision(), "migration_head": head_revision(),
            "tables": len(inspect(engine).get_table_names()), "backup_directory": str(BACKUP_DIR.name),
            "pool": {"checked_in": pool.checkedin(), "checked_out": pool.checkedout(),
                     "size": pool.size(), "overflow": pool.overflow()} if all(
                         hasattr(pool, attr) for attr in ("checkedin", "checkedout", "size", "overflow")) else None}


@router.get("/integrity")
def data_integrity(db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    return integrity_report(db)


@router.get("/backups")
def backups_list(db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    return {"backups": list_backups()}


@router.post("/backups", status_code=201)
def backups_create(db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    try:
        result = create_backup()
        audit.record(db, admin.username, "data.backup_created", result["filename"],
                     {"size_bytes": result["size_bytes"], "database_type": result["database_type"]}, role=admin.role)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=f"Backup could not be created: {str(exc)[:300]}")


@router.get("/export/{dataset}")
def data_export(dataset: str, format: str = Query("csv", pattern="^(json|csv|xlsx|pdf)$"),
                limit: int = Query(10000, ge=1, le=10000), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    try:
        columns, rows, payload = export_dataset(db, dataset, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit.record(db, admin.username, "data.exported", dataset,
                 {"format": format, "records": len(payload), "limit": limit, "offset": offset}, role=admin.role)
    db.commit()
    if format == "json":
        return {"dataset": dataset, "count": len(payload), "limit": limit, "offset": offset,
                "has_more": len(payload) == limit, "records": payload}
    return tabular(format, f"exam_monitor_{dataset}", f"Exam Monitor - {dataset.title()}", columns, rows,
                   [f"Records: {len(payload)}"])


@router.post("/import/students")
async def students_import(mode: str = Query("preview", pattern="^(preview|commit)$"),
                          confirm: bool = Query(False), file: UploadFile = File(...),
                          db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    filename = file.filename or ""
    content = await file.read(MAX_IMPORT_BYTES + 1)
    await file.close()
    try:
        records = parse_student_import(filename, content)
        if mode == "preview":
            return preview_student_import(db, records)
        if not confirm:
            raise HTTPException(status_code=400, detail="Commit requires confirm=true after reviewing the preview")
        return commit_student_import(db, records, admin)
    except HTTPException:
        raise
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:500])


@router.get("/migrations")
def migration_history(admin: models.User = Depends(require_roles("admin"))):
    """Read-only migration ledger and schema drift summary."""
    from ..dbcheck import current_revision, head_revision, audit_schema
    from alembic.script import ScriptDirectory
    from ..dbcheck import alembic_config
    scripts = ScriptDirectory.from_config(alembic_config())
    history = [{"revision": r.revision, "down_revision": r.down_revision,
                "description": (r.doc or "").splitlines()[0] if r.doc else ""}
               for r in scripts.walk_revisions()]
    audit = audit_schema()
    return {"current": current_revision(), "head": head_revision(),
            "up_to_date": current_revision() == head_revision(),
            "history": history, "schema_ok": audit.get("ok", False),
            "drift": audit.get("drift", [])}


@router.get("/backups/{filename}/verify")
def backup_verify(filename: str, db: Session = Depends(get_db),
                  admin: models.User = Depends(require_roles("admin"))):
    from pathlib import Path
    if Path(filename).name != filename or not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    path = BACKUP_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    try:
        from ..data_management import verify_backup, _sha256
        manifest = verify_backup(path)
        audit.record(db, admin.username, "data.backup_verified", filename, role=admin.role)
        db.commit()
        return {"verified": True, "filename": filename, "sha256": _sha256(path),
                "database_type": manifest["database_type"], "created_at": manifest["created_at"],
                "upload_count": len(manifest.get("uploads", []))}
    except Exception as exc:
        return {"verified": False, "filename": filename, "error": str(exc)[:300]}


@router.get("/backups/{filename}/download")
def backup_download(filename: str, db: Session = Depends(get_db),
                    admin: models.User = Depends(require_roles("admin"))):
    from pathlib import Path
    from fastapi.responses import FileResponse
    if Path(filename).name != filename or not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    path = BACKUP_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    from ..data_management import verify_backup
    try:
        verify_backup(path)
    except Exception:
        raise HTTPException(status_code=422, detail="Backup failed verification")
    audit.record(db, admin.username, "data.backup_downloaded", filename, role=admin.role)
    db.commit()
    return FileResponse(path, media_type="application/zip", filename=filename)
