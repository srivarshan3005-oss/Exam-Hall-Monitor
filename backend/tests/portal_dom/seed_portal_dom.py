"""Seed a throw-away database for the portal DOM test: the generated 20-Nov fixture PDFs are ingested exactly like downloads."""
import sys, os, tempfile
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
from app import dbcheck
dbcheck.migrate()
from app.database import SessionLocal
from app.vsb_live import pipeline
from v7_pdfs import write_hall_pdf, write_seat_pdf
tmp = Path(tempfile.mkdtemp())
hp, sp = write_hall_pdf(tmp / "20.11.26-AN-HALL.pdf"), write_seat_pdf(tmp / "20.11.26-AN-SEAT.pdf")
with SessionLocal() as db:
    pipeline.import_local_pdf(db, hp, "hall", source_url="https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-HALL.pdf")
    pipeline.import_local_pdf(db, sp, "seat", source_url="https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-SEAT.pdf")
    print(pipeline.ingest_pending(db), pipeline.rebuild_index(db)["stats"])
