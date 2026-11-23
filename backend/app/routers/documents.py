"""Admin-only PDF intake, conservative text extraction and human approval workflow."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, re, uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models, doc_models, audit
from ..database import get_db
from ..deps import require_roles
from ..config import settings

router=APIRouter(prefix="/api/admin/documents",tags=["PDF documents"])
MAX_UPLOAD=25*1024*1024
STORAGE=Path(__file__).resolve().parents[2]/"uploads"
REGNO_RE=re.compile(r"(?<![A-Z0-9])[A-Z0-9]{6,20}(?![A-Z0-9])",re.I)

@router.get("")
def list_documents(db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    rows=db.scalars(select(doc_models.OfficialDocument).order_by(doc_models.OfficialDocument.id.desc()).limit(100)).all()
    return [{"id":d.id,"title":d.title,"kind":d.doc_kind,"origin":d.origin,"status":d.status,
      "versions":[{"id":v.id,"version":v.version_no,"pages":v.page_count,"processing_status":v.processing_status,"processing_error":v.processing_error,"review_status":v.review_status,"size_bytes":v.size_bytes} for v in d.versions]} for d in rows]

@router.post("/upload",status_code=201)
async def upload_pdf(request:Request,file:UploadFile=File(...),title:str=Form(...),doc_kind:str=Form("other"),
                     db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    if (file.content_type not in ("application/pdf","application/octet-stream") and not (file.filename or "").lower().endswith(".pdf")):
        raise HTTPException(415,"Only PDF documents are accepted")
    if doc_kind not in doc_models.DOC_KINDS: raise HTTPException(422,"Invalid document kind")
    if not title.strip() or len(title.strip())>300: raise HTTPException(422,"A document title of 1–300 characters is required")
    data=await file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD: raise HTTPException(413,"PDF exceeds the 25 MB upload limit")
    if not data.startswith(b"%PDF-"): raise HTTPException(415,"Uploaded file is not a valid PDF")
    digest=hashlib.sha256(data).hexdigest()
    existing=db.scalar(select(doc_models.DocumentVersion).where(doc_models.DocumentVersion.sha256==digest))
    if existing:
        return {"document_id":existing.document_id,"version_id":existing.id,"duplicate":True,"detail":"This exact PDF is already stored"}
    STORAGE.mkdir(parents=True,exist_ok=True)
    path=STORAGE/(uuid.uuid4().hex+".pdf"); path.write_bytes(data)
    doc=doc_models.OfficialDocument(source_url="upload://"+digest,title=title.strip()[:300],doc_kind=doc_kind,origin="upload")
    db.add(doc); db.flush()
    version=doc_models.DocumentVersion(document_id=doc.id,version_no=1,sha256=digest,size_bytes=len(data),storage_path=str(path),processing_status="pending")
    db.add(version); db.flush()
    audit.record(db,user.username,"document.uploaded",str(doc.id),{"bytes":len(data),"kind":doc_kind},request,user.role)
    db.commit()
    return {"document_id":doc.id,"version_id":version.id,"duplicate":False,"processing_status":"pending"}

@router.post("/{version_id}/process")
def process_pdf(version_id:int,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    version=db.get(doc_models.DocumentVersion,version_id)
    if not version: raise HTTPException(404,"Document version not found")
    path=Path(version.storage_path)
    if not path.is_file() or STORAGE.resolve() not in path.resolve().parents: raise HTTPException(404,"Stored PDF is unavailable")
    if db.scalar(select(doc_models.PdfPage.id).where(doc_models.PdfPage.version_id==version.id).limit(1)):
        raise HTTPException(409,"This version already has extracted page records")
    try:
        from pypdf import PdfReader
        reader=PdfReader(str(path),strict=False)
        if reader.is_encrypted: raise ValueError("Encrypted PDFs are not supported")
        if len(reader.pages)>500: raise ValueError("PDF exceeds the 500 page processing limit")
        pages=[]; created=0
        for index,page in enumerate(reader.pages):
            text=page.extract_text() or ""
            p=doc_models.PdfPage(version_id=version.id,page_index=index,width_pt=float(page.mediabox.width),height_pt=float(page.mediabox.height),text_chars=len(text),text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
            db.add(p); db.flush(); pages.append(p)
            seen=set()
            for match in REGNO_RE.finditer(text.upper()):
                reg=match.group(0)
                if not any(ch.isdigit() for ch in reg) or reg in seen: continue
                seen.add(reg)
                db.add(doc_models.RegisterEntry(version_id=version.id,page_id=p.id,register_number=reg,
                    id_kind="standard12" if len(reg)==12 and reg.isdigit() else "nonstandard",
                    source_text=text[max(0,match.start()-45):match.end()+45][:300],extraction_method="text_layer",
                    confidence=None,review_status="pending")); created+=1
        version.page_count=len(reader.pages); version.processing_status="processed" if created else "needs_review"
        version.processed_at=datetime.now(timezone.utc); version.extractor_version="pypdf-text-v1"
        version.processing_error=None
        audit.record(db,user.username,"document.processed",str(version.id),{"pages":len(reader.pages),"candidate_registers":created,"ocr_performed":False},request,user.role)
        db.commit()
        return {"version_id":version.id,"pages":len(reader.pages),"candidate_registers":created,"ocr_available":False,"note":"Candidates remain unpublished until an administrator reviews and approves them."}
    except ImportError:
        version.processing_status="failed"; version.processing_error="Install the pinned pypdf dependency to process PDFs."; db.commit()
        raise HTTPException(503,"PDF text extraction dependency is unavailable")
    except Exception as exc:
        db.rollback(); version=db.get(doc_models.DocumentVersion,version_id)
        if version: version.processing_status="failed"; version.processing_error=str(exc)[:1000]; db.commit()
        raise HTTPException(422,"PDF processing failed; check that the file is a readable, non-encrypted PDF")

@router.get("/{version_id}/review")
def review_queue(version_id:int,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    v=db.get(doc_models.DocumentVersion,version_id)
    if not v: raise HTTPException(404,"Document version not found")
    rows=db.scalars(select(doc_models.RegisterEntry).where(doc_models.RegisterEntry.version_id==version_id).order_by(doc_models.RegisterEntry.page_id,doc_models.RegisterEntry.register_number).limit(2000)).all()
    output=[]
    for r in rows:
        sheet=db.get(doc_models.SeatingSheet,r.sheet_id) if r.sheet_id else None
        output.append({"id":r.id,"register_number":r.register_number,"page_number":db.get(doc_models.PdfPage,r.page_id).page_index+1,
            "source_text":r.source_text,"method":r.extraction_method,"status":r.review_status,"hall_code":sheet.hall_code_raw if sheet else None})
    return output

@router.post("/entries/{entry_id}/review")
def review_entry(entry_id:int,request:Request,decision:str=Form(...),db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    if decision not in ("approved","rejected","needs_review"): raise HTTPException(422,"Invalid review decision")
    entry=db.get(doc_models.RegisterEntry,entry_id)
    if not entry: raise HTTPException(404,"Extraction entry not found")
    entry.review_status=decision; entry.reviewed_by=user.username; entry.reviewed_at=datetime.now(timezone.utc)
    audit.record(db,user.username,"document.entry_reviewed",str(entry.id),{"decision":decision,"page_id":entry.page_id},request,user.role)
    db.commit(); return {"id":entry.id,"review_status":decision}

@router.post("/{version_id}/approve")
def approve_version(version_id:int,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    v=db.get(doc_models.DocumentVersion,version_id)
    if not v: raise HTTPException(404,"Document version not found")
    if v.processing_status not in ("processed","needs_review") or v.page_count is None:
        raise HTTPException(409,"Process the PDF before approving its document version")
    pending=db.scalar(select(func.count()).select_from(doc_models.RegisterEntry).where(doc_models.RegisterEntry.version_id==version_id,doc_models.RegisterEntry.review_status.in_(("pending","needs_review")))) or 0
    if pending: raise HTTPException(409,f"{pending} extraction entries still require review")
    v.review_status="approved"; v.reviewed_by=user.username; v.reviewed_at=datetime.now(timezone.utc)
    audit.record(db,user.username,"document.approved",str(v.id),request=request,role=user.role); db.commit()
    return {"version_id":v.id,"review_status":"approved"}

@router.get("/{version_id}/page/{page_number}")
def source_page(version_id:int,page_number:int,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    if page_number<1: raise HTTPException(422,"Page numbers start at 1")
    page=db.scalar(select(doc_models.PdfPage).where(doc_models.PdfPage.version_id==version_id,doc_models.PdfPage.page_index==page_number-1))
    if not page: raise HTTPException(404,"PDF page not found")
    return {"version_id":version_id,"page_number":page_number,"text_chars":page.text_chars,"ocr_used":page.ocr_used,"review_status":page.review_status}

@router.post("/{version_id}/ocr")
def run_ocr(version_id:int,request:Request,lang:str=Query("eng",max_length=40),db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    """Optional local OCR. Requires the OCR extra and a separately installed Tesseract binary."""
    v=db.get(doc_models.DocumentVersion,version_id)
    if not v: raise HTTPException(404,"Document version not found")
    path=Path(v.storage_path)
    if not path.is_file() or STORAGE.resolve() not in path.resolve().parents: raise HTTPException(404,"Stored PDF is unavailable")
    if not re.fullmatch(r"[A-Za-z+]{1,40}", lang):
        raise HTTPException(422,"OCR language must be a Tesseract language code such as eng or tam+eng")
    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        raise HTTPException(503,"OCR packages are not installed. See docs/OCR.md for the optional local setup.")
    created=0; processed=0
    try:
        pdf=fitz.open(path)
        if len(pdf)>500: raise ValueError("PDF exceeds the 500 page OCR limit")
        v.page_count=len(pdf)
        for index,page in enumerate(pdf):
            existing=db.scalar(select(doc_models.PdfPage).where(doc_models.PdfPage.version_id==v.id,doc_models.PdfPage.page_index==index))
            if existing and existing.text_chars>30: continue
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            text=pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))),lang=lang)
            if not existing:
                existing=doc_models.PdfPage(version_id=v.id,page_index=index,width_pt=float(page.rect.width),height_pt=float(page.rect.height),text_chars=len(text),ocr_used=True)
                db.add(existing); db.flush()
            else:
                existing.text_chars=len(text); existing.ocr_used=True
            processed+=1; seen=set()
            for match in REGNO_RE.finditer(text.upper()):
                reg=match.group(0)
                if not any(ch.isdigit() for ch in reg) or reg in seen: continue
                seen.add(reg)
                duplicate=db.scalar(select(doc_models.RegisterEntry.id).where(doc_models.RegisterEntry.version_id==v.id,doc_models.RegisterEntry.page_id==existing.id,doc_models.RegisterEntry.register_number==reg))
                if duplicate: continue
                db.add(doc_models.RegisterEntry(version_id=v.id,page_id=existing.id,register_number=reg,
                    id_kind="standard12" if len(reg)==12 and reg.isdigit() else "nonstandard",
                    source_text=text[max(0,match.start()-45):match.end()+45][:300],extraction_method="ocr",review_status="pending")); created+=1
        v.ocr_used=processed>0; v.processing_status="needs_review"; v.processed_at=datetime.now(timezone.utc)
        audit.record(db,user.username,"document.ocr_processed",str(v.id),{"pages_ocr_processed":processed,"candidate_registers":created},request,user.role)
        db.commit(); return {"version_id":v.id,"pages_ocr_processed":processed,"candidate_registers":created,"review_required":True}
    except Exception:
        db.rollback(); raise HTTPException(422,"OCR could not process this PDF. Check the Tesseract installation and PDF integrity.")
