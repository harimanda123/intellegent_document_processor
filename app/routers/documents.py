"""
Documents Router
----------------
Upload documents, poll status, get results, download JSON.

UI path only:
  Upload → Extract → (Optional Review) → Download JSON

ERP path is separate in erp.py.
No ERP push from this router.
"""
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException,
    UploadFile, File, Form,
    BackgroundTasks, status
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.document import Document, Extraction, AuditLog
from app.models.schema import DocSchema, SchemaFeedback
from app.config import settings
from app.services.pipeline import run_pipeline, retry_document

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_EXTENSIONS = {".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png"}


# ── Pydantic response models ───────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    label: Optional[str]
    filename: str
    schema_id: str
    schema_version: int
    state: str
    progress: Optional[str]
    file_type: Optional[str]
    page_count: Optional[int]
    processing_ms: Optional[int]
    avg_confidence: Optional[float]
    error_code: Optional[str]
    error_message: Optional[str]
    require_review: bool
    llm_provider: Optional[str]
    llm_model: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ────────────────────────────────────────────────────────────────

def validate_upload(file: UploadFile) -> None:
    """Validate file extension."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"File type '{suffix}' is not supported. "
                f"Accepted: {sorted(ALLOWED_EXTENSIONS)}"
            )
        )


def build_result_payload(
    doc: Document,
    extractions: list[Extraction]
) -> dict:
    """
    Build the full JSON result payload from a document
    and its extraction results.
    """
    data: dict = {}
    total = len(extractions)
    edited = sum(1 for e in extractions if e.human_edited)
    missing = sum(1 for e in extractions if e.missing)
    auto_accepted = total - edited - missing

    for ext in extractions:
        value = (
            ext.value_json.get("value")
            if ext.value_json else None
        )
        field_data = {
            "value": value,
            "confidence": ext.confidence,
            "human_edited": ext.human_edited,
            "missing": ext.missing,
            "spatial_anchor": ext.spatial_anchor,
        }
        if ext.human_edited and ext.original_value_json:
            field_data["original_value"] = (
                ext.original_value_json.get("value")
            )
        data[ext.field_key] = field_data

    return {
        "api_version": "1.0",
        "doc_id": doc.id,
        "label": doc.label,
        "filename": doc.filename,
        "state": doc.state,
        "schema_id": doc.schema_id,
        "schema_version": doc.schema_version,
        "file_type": doc.file_type,
        "page_count": doc.page_count,
        "processing_ms": doc.processing_ms,
        "avg_confidence": doc.avg_confidence,
        "llm_provider": doc.llm_provider,
        "llm_model": doc.llm_model,
        "extraction_summary": {
            "total_fields": total,
            "auto_accepted": auto_accepted,
            "human_edited": edited,
            "missing_fields": missing,
        },
        "data": data,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[DocumentOut],
    summary="List all documents"
)
def list_documents(
    state: Optional[str] = None,
    schema_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List documents with optional state and schema filters."""
    query = db.query(Document)
    if state:
        query = query.filter(Document.state == state)
    if schema_id:
        query = query.filter(Document.schema_id == schema_id)
    return (
        query
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for extraction"
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    schema_id: str = Form(...),
    label: Optional[str] = Form(None),
    require_review: bool = Form(False),
    db: Session = Depends(get_db),
):
    """
    Upload a document for AI extraction.

    Returns 202 immediately — processing runs in the background.
    Poll GET /documents/{id}/status to track progress.

    require_review=False (default): document auto-moves to VERIFIED.
    require_review=True: document waits in PENDING_REVIEW for approval.
    """
    # Validate file type
    validate_upload(file)

    # Validate schema exists and is usable
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )
    if schema.status == "archived":
        raise HTTPException(
            status_code=422,
            detail=f"Schema '{schema_id}' is archived and cannot be used"
        )
    if schema.status == "draft":
        raise HTTPException(
            status_code=422,
            detail=f"Schema '{schema_id}' is still a draft. Activate it first."
        )

    # Read and validate file size
    contents = await file.read()
    if len(contents) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large: {len(contents) / 1024 / 1024:.1f}MB. "
                f"Maximum: {settings.max_file_size_mb}MB"
            )
        )

    # Save file to disk
    doc_id = str(uuid.uuid4())
    suffix = Path(file.filename or "upload").suffix.lower()
    safe_filename = f"{doc_id}{suffix}"
    file_path = settings.upload_path / safe_filename

    with open(file_path, "wb") as f:
        f.write(contents)

    # Create document record
    doc = Document(
        id=doc_id,
        label=label,
        filename=file.filename or safe_filename,
        file_path=str(file_path),
        file_size=len(contents),
        schema_id=schema_id,
        schema_version=schema.version,
        state="RECEIVED",
        require_review=require_review,
        source="ui",
    )
    db.add(doc)

    # Audit log
    log = AuditLog(
        doc_id=doc_id,
        action="document_uploaded",
        actor="user",
        new_value=(
            f"schema={schema_id}, "
            f"file={file.filename}, "
            f"require_review={require_review}"
        ),
    )
    db.add(log)
    db.commit()
    db.refresh(doc)

    # Queue pipeline as background task
    # Response is returned before pipeline runs
    background_tasks.add_task(run_pipeline, doc_id, db)

    return doc


@router.get(
    "/{doc_id}/status",
    response_model=DocumentOut,
    summary="Poll document processing status"
)
def get_status(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """Poll this endpoint until state = VERIFIED, PENDING_REVIEW, or FAILED."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    return doc


@router.get(
    "/{doc_id}/result",
    summary="Get extraction result"
)
def get_result(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """
    Get full extraction result.
    Available when state = VERIFIED or PENDING_REVIEW.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state in ("RECEIVED", "PROCESSING"):
        raise HTTPException(
            status_code=202,
            detail=f"Still processing. State: {doc.state}, Progress: {doc.progress}"
        )
    if doc.state in ("FAILED", "ABANDONED"):
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": doc.error_code,
                "error_message": doc.error_message,
            }
        )

    extractions = (
        db.query(Extraction)
        .filter(Extraction.doc_id == doc_id)
        .all()
    )
    return build_result_payload(doc, extractions)


@router.get(
    "/{doc_id}/download",
    summary="Download extraction result as JSON"
)
def download_json(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """
    Download extraction result as a JSON file.

    This is the only export method from the UI.
    No ERP push from this endpoint.
    Available when state = VERIFIED.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state not in ("VERIFIED", "PENDING_REVIEW", "DOWNLOADED"):
        raise HTTPException(
            status_code=400,
            detail=f"Document not ready for download. Current state: {doc.state}"
        )

    extractions = (
        db.query(Extraction)
        .filter(Extraction.doc_id == doc_id)
        .all()
    )
    payload = build_result_payload(doc, extractions)

    # Log download
    log = AuditLog(
        doc_id=doc_id,
        action="json_downloaded",
        actor="user",
    )
    db.add(log)

    # Mark as downloaded
    if doc.state == "VERIFIED":
        doc.state = "DOWNLOADED"
        doc.updated_at = datetime.utcnow()

    db.commit()

    # Return as downloadable file
    safe_label = (doc.label or doc.id).replace(" ", "_")
    filename = f"{safe_label}.json"

    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.put(
    "/{doc_id}/approve",
    summary="Approve a document in review"
)
def approve_document(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """
    Approve a document in PENDING_REVIEW state.
    Moves it to VERIFIED so it can be downloaded.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state != "PENDING_REVIEW":
        raise HTTPException(
            status_code=400,
            detail=f"Document is not in PENDING_REVIEW. Current: {doc.state}"
        )

    doc.state = "VERIFIED"
    doc.progress = None
    doc.updated_at = datetime.utcnow()

    log = AuditLog(
        doc_id=doc_id,
        action="document_approved",
        actor="reviewer",
    )
    db.add(log)

    # Schema feedback: all fields accepted → schema stability improves
    extractions = (
        db.query(Extraction)
        .filter(Extraction.doc_id == doc_id)
        .all()
    )
    for ext in extractions:
        if not ext.human_edited:
            feedback = SchemaFeedback(
                schema_id=doc.schema_id,
                field_key=ext.field_key,
                doc_id=doc_id,
                action="approved",
                before_json=ext.value_json,
                after_json=ext.value_json,
                confidence_at_feedback=ext.confidence,
            )
            db.add(feedback)

    db.commit()

    return {"message": "Document approved", "state": "VERIFIED"}


@router.put(
    "/{doc_id}/reject",
    summary="Reject a document in review"
)
def reject_document(
    doc_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Reject a document in PENDING_REVIEW.
    Records the rejection reason in the audit log.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state != "PENDING_REVIEW":
        raise HTTPException(
            status_code=400,
            detail=f"Document is not in PENDING_REVIEW. Current: {doc.state}"
        )

    reason = body.get("reason", "No reason provided")
    doc.state = "FAILED"
    doc.error_code = "REJECTED_BY_REVIEWER"
    doc.error_message = reason
    doc.updated_at = datetime.utcnow()

    log = AuditLog(
        doc_id=doc_id,
        action="document_rejected",
        actor="reviewer",
        new_value=reason,
    )
    db.add(log)
    db.commit()

    return {"message": "Document rejected", "reason": reason}


@router.put(
    "/{doc_id}/fields/{field_key}",
    summary="Edit an extracted field value"
)
def update_field(
    doc_id: str,
    field_key: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Edit an extracted field during review.
    Original AI value is preserved in original_value_json for audit.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state not in ("PENDING_REVIEW", "VERIFIED"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit fields in state: {doc.state}"
        )

    extraction = (
        db.query(Extraction)
        .filter(
            Extraction.doc_id == doc_id,
            Extraction.field_key == field_key,
        )
        .first()
    )
    if not extraction:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{field_key}' not found"
        )

    new_value = body.get("value")
    old_value = extraction.value_json

    # Preserve original AI value for audit
    if not extraction.human_edited:
        extraction.original_value_json = old_value

    extraction.value_json = {"value": new_value}
    extraction.human_edited = True
    extraction.missing = new_value is None

    # Audit log
    log = AuditLog(
        doc_id=doc_id,
        action="field_edited",
        actor="reviewer",
        old_value=str(old_value),
        new_value=str(new_value),
    )
    db.add(log)

    # Schema feedback loop — record correction for future schema improvement
    feedback = SchemaFeedback(
        schema_id=doc.schema_id,
        field_key=field_key,
        doc_id=doc_id,
        action="field_edited",
        before_json=old_value,
        after_json={"value": new_value},
        confidence_at_feedback=extraction.confidence,
    )
    db.add(feedback)

    db.commit()

    return {
        "message": "Field updated",
        "field_key": field_key,
        "new_value": new_value,
    }


@router.get(
    "/{doc_id}/audit",
    summary="Get audit log for a document"
)
def get_audit_log(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """Get the full immutable audit trail for a document."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.doc_id == doc_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )

    return [
        {
            "id": log.id,
            "action": log.action,
            "actor": log.actor,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "timestamp": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get(
    "/{doc_id}/download/csv",
    summary="Download extraction result as CSV"
)
def download_csv(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """
    Download extraction result as a denormalised CSV file.

    Scalar fields are repeated on every row.
    Table fields are expanded — one row per table row.
    If no table fields exist, a single row with all scalar values is returned.

    Available when state = VERIFIED, PENDING_REVIEW, or DOWNLOADED.
    """
    import csv, io

    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state not in ("VERIFIED", "PENDING_REVIEW", "DOWNLOADED"):
        raise HTTPException(
            status_code=400,
            detail=f"Document not ready for download. Current state: {doc.state}"
        )

    extractions = (
        db.query(Extraction)
        .filter(Extraction.doc_id == doc_id)
        .order_by(Extraction.field_key)
        .all()
    )

    # Separate scalar and table extractions
    scalars: dict[str, str] = {}
    tables: dict[str, list[dict]] = {}

    for ext in extractions:
        value = ext.value_json.get("value") if ext.value_json else None
        if ext.field_type == "table":
            tables[ext.field_key] = value if isinstance(value, list) else []
        else:
            scalars[ext.field_key] = "" if value is None else str(value)

    # Build CSV rows — denormalised (one row per table row, scalars repeated)
    output = io.StringIO()

    if tables:
        # Determine column order: scalar keys first, then table columns
        # Use the first table for column names (most docs have one line-item table)
        first_table_key = next(iter(tables))
        first_rows = tables[first_table_key]
        table_cols = list(first_rows[0].keys()) if first_rows else []

        # Strip internal metadata columns (_row_confidence, _page)
        table_cols = [c for c in table_cols if not c.startswith("_")]

        fieldnames = list(scalars.keys()) + table_cols
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        if first_rows:
            for row in first_rows:
                csv_row = {**scalars}
                for col in table_cols:
                    csv_row[col] = row.get(col, "")
                writer.writerow(csv_row)
        else:
            writer.writerow(scalars)
    else:
        # No tables — single row with all scalar values
        fieldnames = list(scalars.keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(scalars)

    # Audit log
    log = AuditLog(
        doc_id=doc_id,
        action="csv_downloaded",
        actor="user",
    )
    db.add(log)
    db.commit()

    safe_label = (doc.label or doc.id).replace(" ", "_")
    filename = f"{safe_label}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post(
    "/{doc_id}/retry",
    summary="Retry a failed document"
)
def retry_failed_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Manually retry a document that is in FAILED or ABANDONED state.

    Resets retry_count to zero and re-queues the pipeline.
    Returns 202 immediately — pipeline runs in the background.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )
    if doc.state not in ("FAILED", "ABANDONED"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only FAILED or ABANDONED documents can be retried. "
                f"Current state: {doc.state}"
            )
        )

    background_tasks.add_task(retry_document, doc_id, db)

    return {
        "message": "Retry queued",
        "doc_id": doc_id,
        "state": "RECEIVED",
    }