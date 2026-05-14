"""
ERP Integration Router
----------------------
Machine-to-machine interface for ERP systems.

Two endpoints only:
  POST /erp/submit        — ERP pushes document + metadata
  GET  /erp/status/{id}  — ERP polls for result

No webhooks. No SFTP. No sync response.
ERP always initiates. IDG never calls back.
"""
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException,
    UploadFile, File, Form,
    BackgroundTasks, Header
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document import Document, Extraction, AuditLog
from app.models.schema import DocSchema
from app.config import settings
from app.services.pipeline import run_pipeline
from app.routers.documents import (
    validate_upload,
    build_result_payload,
)

router = APIRouter(prefix="/erp", tags=["ERP Integration"])


# ── Auth dependency ────────────────────────────────────────────────────────

def verify_erp_auth(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """
    Verify ERP API credentials from request headers.

    MVP: basic key length check.
    v1.1: verify against database — one key per ERP system.
    """
    if not x_tenant_id or not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Tenant-ID or X-API-Key header"
        )
    if len(x_api_key) < 8:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    return {
        "tenant_id": x_tenant_id,
        "api_key": x_api_key,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post(
    "/submit",
    status_code=202,
    summary="ERP submits a document for extraction"
)
async def erp_submit(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    schema_id: str = Form(...),
    erp_reference_id: str = Form(...),
    require_review: str = Form("false"),
    priority: str = Form("normal"),
    source_system: str = Form("ERP"),
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_erp_auth),
):
    """
    ERP submits a document for extraction.

    Returns 202 immediately with doc_id.
    ERP must poll GET /erp/status/{doc_id} for the result.

    require_review values:
      false (default) — auto-deliver when AI completes
      true            — hold for human review first
      auto            — IDG decides based on confidence score
    """
    # ── Idempotency check ──────────────────────────────────────────────
    # Same erp_reference_id returns existing result without reprocessing
    existing = (
        db.query(Document)
        .filter(Document.erp_reference_id == erp_reference_id)
        .first()
    )
    if existing:
        return {
            "api_version": "1.0",
            "doc_id": existing.id,
            "erp_reference_id": erp_reference_id,
            "state": existing.state,
            "idempotent": True,
            "message": (
                "Document already exists. "
                "Poll status_url for current result."
            ),
            "status_url": f"/api/erp/status/{existing.id}",
        }

    # ── Validate ───────────────────────────────────────────────────────
    validate_upload(file)

    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )
    if schema.status != "active":
        raise HTTPException(
            status_code=422,
            detail=f"Schema '{schema_id}' is not active (status: {schema.status})"
        )

    # ── Read file ──────────────────────────────────────────────────────
    contents = await file.read()
    if len(contents) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large: {len(contents)/1024/1024:.1f}MB. "
                f"Maximum: {settings.max_file_size_mb}MB"
            )
        )

    # ── Resolve require_review flag ────────────────────────────────────
    # Store the original string so the pipeline can handle "auto" mode.
    rr_lower = require_review.lower()
    resolve_review = rr_lower in ("true", "1")

    # ── Save file ──────────────────────────────────────────────────────
    doc_id = str(uuid.uuid4())
    suffix = Path(file.filename or "upload").suffix.lower()
    file_path = settings.upload_path / f"{doc_id}{suffix}"

    with open(file_path, "wb") as f:
        f.write(contents)

    # ── Create document record ─────────────────────────────────────────
    doc = Document(
        id=doc_id,
        filename=file.filename or f"{doc_id}{suffix}",
        file_path=str(file_path),
        file_size=len(contents),
        schema_id=schema_id,
        schema_version=schema.version,
        state="RECEIVED",
        require_review=resolve_review,
        require_review_mode=rr_lower,
        source="erp",
        erp_reference_id=erp_reference_id,
    )
    db.add(doc)

    # Audit log
    log = AuditLog(
        doc_id=doc_id,
        action="erp_submit",
        actor=source_system,
        new_value=(
            f"erp_reference_id={erp_reference_id}, "
            f"schema={schema_id}, "
            f"require_review={require_review}"
        ),
    )
    db.add(log)
    db.commit()

    # ── Queue pipeline ─────────────────────────────────────────────────
    background_tasks.add_task(run_pipeline, doc_id, db)

    return {
        "api_version": "1.0",
        "doc_id": doc_id,
        "erp_reference_id": erp_reference_id,
        "state": "RECEIVED",
        "poll_after_ms": 3000,
        "status_url": f"/api/erp/status/{doc_id}",
    }


@router.get(
    "/status/{doc_id}",
    summary="ERP polls extraction status and result"
)
def erp_poll_status(
    doc_id: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_erp_auth),
):
    """
    Poll document status.

    Keep polling until state = DELIVERED, FAILED, or ABANDONED.
    Honour retry_after_ms to avoid rate limiting.

    When state = DELIVERED, the full result is included
    in the response — ERP can stop polling.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{doc_id}' not found"
        )

    # ── Map internal states to ERP-facing states ───────────────────────
    # VERIFIED and DOWNLOADED both map to DELIVERED for the ERP
    state_map = {
        "RECEIVED":       "RECEIVED",
        "PROCESSING":     "PROCESSING",
        "PENDING_REVIEW": "PENDING_REVIEW",
        "VERIFIED":       "DELIVERED",
        "DOWNLOADED":     "DELIVERED",
        "FAILED":         "FAILED",
        "ABANDONED":      "ABANDONED",
    }
    erp_state = state_map.get(doc.state, doc.state)

    # ── Retry hint based on current progress ───────────────────────────
    retry_hints = {
        "ocr_running":    5000,
        "ocr_complete":   2000,
        "ai_extraction":  4000,
        "saving":         1000,
        "pending_review": 30000,  # Human review — poll slowly
    }
    retry_after_ms = (
        retry_hints.get(doc.progress or "", 3000)
        if erp_state in ("RECEIVED", "PROCESSING", "PENDING_REVIEW")
        else None
    )

    response = {
        "api_version": "1.0",
        "doc_id": doc_id,
        "erp_reference_id": doc.erp_reference_id,
        "state": erp_state,
        "progress": doc.progress,
        "retry_after_ms": retry_after_ms,
    }

    # ── Include full result when DELIVERED ─────────────────────────────
    if erp_state == "DELIVERED":
        extractions = (
            db.query(Extraction)
            .filter(Extraction.doc_id == doc_id)
            .all()
        )
        response["result"] = build_result_payload(doc, extractions)
        response["retry_after_ms"] = None

        # Log delivery
        log = AuditLog(
            doc_id=doc_id,
            action="erp_delivered",
            actor="system",
        )
        db.add(log)
        db.commit()

    # ── Include error info when FAILED or ABANDONED ────────────────────
    if erp_state in ("FAILED", "ABANDONED"):
        response["error"] = {
            "code": doc.error_code,
            "message": doc.error_message,
            "retryable": doc.error_code in (
                "OCR_FAILED",
                "EXTRACTION_FAILED",
            ),
        }

    return response


@router.get(
    "/schemas",
    summary="ERP lists available active schemas"
)
def erp_list_schemas(
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_erp_auth),
):
    """
    List all active schemas available for ERP submission.
    Returns scalar_fields and table_fields separately
    so ERP can map columns to its own field names.
    """
    schemas = (
        db.query(DocSchema)
        .filter(DocSchema.status == "active")
        .all()
    )

    result = []
    for s in schemas:
        scalar_fields = [
            f["json_key"]
            for f in s.fields
            if f.get("field_type") != "table"
        ]
        table_fields = [
            {
                "json_key": f["json_key"],
                "columns": [
                    c["json_key"]
                    for c in f.get("table_columns", [])
                ],
            }
            for f in s.fields
            if f.get("field_type") == "table"
        ]
        result.append({
            "schema_id": s.id,
            "name": s.name,
            "document_type": s.document_type,
            "version": s.version,
            "scalar_fields": scalar_fields,
            "table_fields": table_fields,
        })

    return {
        "api_version": "1.0",
        "schemas": result,
    }


# ── Batch submit ───────────────────────────────────────────────────────────

MAX_BATCH_SIZE = 50


@router.post(
    "/submit/batch",
    status_code=202,
    summary="ERP submits up to 50 documents in one call"
)
async def erp_submit_batch(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_erp_auth),
    source_system: str = Form("ERP"),
    files: list[UploadFile] = File(...),
    metas: list[str] = Form(...),
):
    """
    Submit up to 50 documents in a single API call.

    Each document requires a matching metadata entry.
    Files and metas are paired by position: files[0] uses metas[0], etc.

    Meta JSON format per document:
      {
        "schema_id": "sch_inv_dhl_sg_v1",
        "erp_reference_id": "REF-001",
        "require_review": "false",
        "priority": "normal"
      }

    One document failing validation does not block others.
    One batch call counts as one request against the rate limit.
    Each document gets its own doc_id and must be polled independently.
    """
    import json as _json

    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Batch size {len(files)} exceeds maximum of {MAX_BATCH_SIZE}. "
                f"Split into multiple requests."
            )
        )

    if len(files) != len(metas):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Mismatch: {len(files)} file(s) but {len(metas)} meta(s). "
                f"Each file must have a matching meta entry."
            )
        )

    submitted: list[dict] = []
    rejected: list[dict] = []

    for i, (file, meta_str) in enumerate(zip(files, metas)):
        # Parse meta JSON
        try:
            meta = _json.loads(meta_str)
        except Exception:
            rejected.append({
                "index": i,
                "filename": file.filename,
                "error": "Invalid JSON in meta",
            })
            continue

        schema_id = meta.get("schema_id", "")
        erp_reference_id = meta.get("erp_reference_id", "")
        require_review_flag = meta.get("require_review", "false")

        if not schema_id or not erp_reference_id:
            rejected.append({
                "index": i,
                "filename": file.filename,
                "erp_reference_id": erp_reference_id,
                "error": "schema_id and erp_reference_id are required in meta",
            })
            continue

        # Idempotency check
        existing = (
            db.query(Document)
            .filter(Document.erp_reference_id == erp_reference_id)
            .first()
        )
        if existing:
            submitted.append({
                "index": i,
                "erp_reference_id": erp_reference_id,
                "doc_id": existing.id,
                "state": existing.state,
                "idempotent": True,
                "status_url": f"/api/erp/status/{existing.id}",
            })
            continue

        # Validate file type
        suffix = Path(file.filename or "").suffix.lower()
        allowed = {".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png"}
        if suffix not in allowed:
            rejected.append({
                "index": i,
                "filename": file.filename,
                "erp_reference_id": erp_reference_id,
                "error": f"Unsupported file type: {suffix}",
            })
            continue

        # Validate schema
        schema = db.get(DocSchema, schema_id)
        if not schema or schema.status != "active":
            rejected.append({
                "index": i,
                "filename": file.filename,
                "erp_reference_id": erp_reference_id,
                "error": (
                    f"Schema '{schema_id}' not found or not active"
                ),
            })
            continue

        # Read file
        contents = await file.read()
        if len(contents) > settings.max_file_size_bytes:
            rejected.append({
                "index": i,
                "filename": file.filename,
                "erp_reference_id": erp_reference_id,
                "error": (
                    f"File too large: "
                    f"{len(contents)/1024/1024:.1f}MB > "
                    f"{settings.max_file_size_mb}MB"
                ),
            })
            continue

        # Resolve review mode
        rr_lower = require_review_flag.lower()
        resolve_review = rr_lower in ("true", "1")

        # Save file
        doc_id = str(uuid.uuid4())
        file_path = settings.upload_path / f"{doc_id}{suffix}"
        with open(file_path, "wb") as fh:
            fh.write(contents)

        # Create document record
        doc = Document(
            id=doc_id,
            filename=file.filename or f"{doc_id}{suffix}",
            file_path=str(file_path),
            file_size=len(contents),
            schema_id=schema_id,
            schema_version=schema.version,
            state="RECEIVED",
            require_review=resolve_review,
            require_review_mode=rr_lower,
            source="erp",
            erp_reference_id=erp_reference_id,
        )
        db.add(doc)

        log = AuditLog(
            doc_id=doc_id,
            action="erp_batch_submit",
            actor=source_system,
            new_value=(
                f"batch_index={i}, "
                f"erp_reference_id={erp_reference_id}, "
                f"schema={schema_id}"
            ),
        )
        db.add(log)

        # Queue pipeline per document
        background_tasks.add_task(run_pipeline, doc_id, db)

        poll_after_ms = 3000 + (i * 200)  # Stagger hints slightly
        submitted.append({
            "index": i,
            "erp_reference_id": erp_reference_id,
            "doc_id": doc_id,
            "state": "RECEIVED",
            "poll_after_ms": poll_after_ms,
            "status_url": f"/api/erp/status/{doc_id}",
        })

    db.commit()

    return {
        "api_version": "1.0",
        "submitted": len(submitted),
        "rejected": len(rejected),
        "documents": submitted,
        "errors": rejected if rejected else None,
    }