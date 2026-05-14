"""
Schemas Router
--------------
CRUD endpoints for document extraction schemas.

Key rule: schemas store rules only.
Never document values, never coordinates.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.schema import DocSchema, SchemaFeedback, SchemaVersion
from app.config import settings

router = APIRouter(prefix="/schemas", tags=["Schemas"])


# ── Pydantic request / response models ─────────────────────────────────────

class SchemaFieldIn(BaseModel):
    json_key: str
    label: str
    field_type: str = "string"
    # string | number | date | currency | boolean | table
    hints: list[str] = []
    anchors: list[str] = []
    exclude_if_near: list[str] = []
    section: str = ""
    position_preference: str = ""
    description: str = ""
    required: bool = False
    validation: str = ""
    confidence_threshold: float = 0.80
    table_columns: list[dict] = []
    # Maturity signal (1.0 = new, decreases as feedback is applied).
    # Preserved across edits so apply_feedback history isn't lost.
    feedback_weight: float = 1.0


class SchemaCreateIn(BaseModel):
    name: str
    document_type: str
    description: Optional[str] = None
    fields: list[SchemaFieldIn] = []


class SchemaUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    fields: Optional[list[SchemaFieldIn]] = None


class SchemaOut(BaseModel):
    id: str
    name: str
    document_type: str
    description: Optional[str]
    version: int
    status: str
    fields: list[dict]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[SchemaOut],
    summary="List all schemas"
)
def list_schemas(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all schemas.
    Filter by status: active | draft | archived
    """
    query = db.query(DocSchema)
    if status:
        query = query.filter(DocSchema.status == status)
    return query.order_by(DocSchema.created_at.desc()).all()


@router.post(
    "/",
    response_model=SchemaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new schema"
)
def create_schema(
    body: SchemaCreateIn,
    db: Session = Depends(get_db),
):
    """
    Create a new schema.
    Saved as draft until explicitly activated.
    Fields store rules only — no document values.
    """
    schema = DocSchema(
        name=body.name,
        document_type=body.document_type,
        description=body.description,
        status="draft",
        fields=[f.model_dump() for f in body.fields],
    )
    db.add(schema)
    db.commit()
    db.refresh(schema)
    return schema


@router.get(
    "/{schema_id}",
    response_model=SchemaOut,
    summary="Get a schema by ID"
)
def get_schema(
    schema_id: str,
    db: Session = Depends(get_db),
):
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )
    return schema


@router.put(
    "/{schema_id}",
    response_model=SchemaOut,
    summary="Update a schema"
)
def update_schema(
    schema_id: str,
    body: SchemaUpdateIn,
    db: Session = Depends(get_db),
):
    """
    Update schema name, description, status, or fields.
    When fields change, version is incremented automatically.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )

    if body.name is not None:
        schema.name = body.name

    if body.description is not None:
        schema.description = body.description

    if body.status is not None:
        allowed = ("draft", "active", "archived")
        if body.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {allowed}"
            )
        schema.status = body.status

    if body.fields is not None:
        # Snapshot the current version before overwriting
        snapshot = SchemaVersion(
            schema_id=schema.id,
            version=schema.version,
            fields_snapshot=schema.fields,
        )
        db.add(snapshot)
        schema.fields = [f.model_dump() for f in body.fields]
        schema.version += 1  # Increment on every field change

    schema.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(schema)
    return schema


@router.delete(
    "/{schema_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive a schema"
)
def archive_schema(
    schema_id: str,
    db: Session = Depends(get_db),
):
    """
    Soft delete — marks schema as archived.
    Archived schemas cannot be used for new documents.
    Historical documents that used this schema are not affected.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )
    schema.status = "archived"
    schema.updated_at = datetime.utcnow()
    db.commit()


@router.post(
    "/{schema_id}/activate",
    response_model=SchemaOut,
    summary="Activate a draft schema"
)
def activate_schema(
    schema_id: str,
    db: Session = Depends(get_db),
):
    """
    Activate a draft schema for production use.
    Requires at least one field to be defined.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )
    if not schema.fields:
        raise HTTPException(
            status_code=400,
            detail="Cannot activate a schema with no fields. Add at least one field first."
        )
    schema.status = "active"
    schema.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(schema)
    return schema


@router.post(
    "/{schema_id}/duplicate",
    response_model=SchemaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a schema"
)
def duplicate_schema(
    schema_id: str,
    db: Session = Depends(get_db),
):
    """
    Create a copy of an existing schema as a new draft.
    Useful when two document types have similar structures.
    """
    original = db.get(DocSchema, schema_id)
    if not original:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )

    new_schema = DocSchema(
        name=f"{original.name} (copy)",
        document_type=original.document_type,
        description=original.description,
        status="draft",
        fields=original.fields,
        version=1,
    )
    db.add(new_schema)
    db.commit()
    db.refresh(new_schema)
    return new_schema


# ── AI-first Schema Proposal ───────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png"}


@router.post(
    "/propose",
    summary="AI proposes a schema from a sample document"
)
async def propose_schema_from_sample(
    file: UploadFile = File(...),
    document_type: Optional[str] = Form(""),
):
    """
    Upload a sample document and get a complete AI-generated schema proposal.

    The system runs OCR on the sample document, analyses the structure,
    and proposes all field definitions including:
    - Field names, types, hints
    - Ambiguity detection and anchor rules
    - Table column mappings

    The proposal is returned for user review — nothing is saved to the database.
    The sample document is discarded after analysis (never stored).

    Typical flow:
      POST /schemas/propose  → review proposal in UI
      POST /schemas/         → save accepted fields as a draft schema
      POST /schemas/{id}/activate → activate for production use
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"File type '{suffix}' is not supported. "
                f"Accepted: {sorted(ALLOWED_EXTENSIONS)}"
            )
        )

    contents = await file.read()
    if len(contents) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large: {len(contents) / 1024 / 1024:.1f}MB. "
                f"Maximum: {settings.max_file_size_mb}MB"
            )
        )

    # Save to a temp file for OCR (discarded immediately after)
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False
    ) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        from app.services.ocr_service import run_ocr, build_llm_document_text
        from app.services.table_service import run_table_detection, build_table_text
        from app.services.llm_service import propose_schema

        ocr_result = run_ocr(tmp_path)
        table_detection = run_table_detection(ocr_result)

        # Combine OCR text with detected table structure for LLM
        doc_text = build_llm_document_text(ocr_result)
        table_text = build_table_text(table_detection)
        if table_text:
            doc_text = doc_text + "\n\nDETECTED TABLES:\n" + table_text

        proposal = propose_schema(
            document_text=doc_text,
            document_type_hint=document_type or "",
        )

    except NotImplementedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Schema proposal failed: {str(e)}"
        )
    finally:
        # Always discard the sample document — never stored
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "api_version": "1.0",
        "document_type_detected": proposal.document_type_detected,
        "field_count": len(proposal.fields),
        "fields": [f.model_dump() for f in proposal.fields],
        "note": (
            "Review and correct this proposal, then POST to /schemas/ "
            "to save as a draft. Sample document has been discarded."
        ),
    }


# ── Schema Test (no values persisted) ─────────────────────────────────────

@router.post(
    "/{schema_id}/test",
    summary="Test a schema against a document (no values stored)"
)
async def test_schema(
    schema_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Test a schema against a real document without creating any records.

    Runs the full OCR + table detection + LLM extraction pipeline
    and returns the results as a live preview.

    No document record is created. No extraction values are stored.
    The uploaded file is discarded immediately after processing.

    Use this before activating a schema to verify field accuracy.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_id}' not found"
        )
    if not schema.fields:
        raise HTTPException(
            status_code=400,
            detail="Schema has no fields. Add fields before testing."
        )

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"File type '{suffix}' is not supported. "
                f"Accepted: {sorted(ALLOWED_EXTENSIONS)}"
            )
        )

    contents = await file.read()
    if len(contents) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large: {len(contents) / 1024 / 1024:.1f}MB. "
                f"Maximum: {settings.max_file_size_mb}MB"
            )
        )

    import tempfile, os, time
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False
    ) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        from app.services.ocr_service import (
            run_ocr, build_llm_document_text, find_spatial_anchor
        )
        from app.services.table_service import run_table_detection, build_table_text
        from app.services.llm_service import extract_fields, calculate_confidence

        start = time.time()

        ocr_result = run_ocr(tmp_path)
        table_detection = run_table_detection(ocr_result)

        doc_text = build_llm_document_text(ocr_result)
        table_text = build_table_text(table_detection)
        if table_text:
            doc_text = doc_text + "\n\nDETECTED TABLES:\n" + table_text

        extraction_output = extract_fields(
            document_text=doc_text,
            schema_fields=schema.fields,
        )

        processing_ms = int((time.time() - start) * 1000)

        # Build preview result — spatial anchors included, nothing saved
        preview: dict = {}
        for f in schema.fields:
            key = f["json_key"]
            field_result = extraction_output.fields.get(key)
            if field_result is None:
                continue

            value = field_result.value
            spatial_anchor = None
            if (
                value
                and not field_result.missing
                and f.get("field_type") != "table"
            ):
                spatial_anchor = find_spatial_anchor(str(value), ocr_result)

            preview[key] = {
                "value": value,
                "confidence": field_result.confidence,
                "missing": field_result.missing,
                "spatial_anchor": spatial_anchor,
            }

    except NotImplementedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[TEST EXTRACTION ERROR]\n{tb}")
        err_str = str(e)
        # Surface rate-limit / quota errors clearly instead of a generic 500
        if "rate_limit" in err_str.lower() or "429" in err_str or "ratelimit" in err_str.lower():
            raise HTTPException(
                status_code=429,
                detail=(
                    "LLM rate limit reached. "
                    "You have used your daily token quota for this model. "
                    "Please wait and try again later, or switch to a different model in .env."
                ),
            )
        if "RetryError" in type(e).__name__ or "InstructorRetry" in type(e).__name__:
            # Unwrap instructor retry exception to find the real cause
            cause = str(getattr(e, '__cause__', e) or e)
            if "rate_limit" in cause.lower() or "429" in cause:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "LLM rate limit reached. "
                        "Daily token quota exhausted. "
                        "Please wait and try again later."
                    ),
                )
            raise HTTPException(
                status_code=500,
                detail=f"LLM extraction failed after retries: {cause[:300]}",
            )
        raise HTTPException(
            status_code=500,
            detail=f"Test extraction failed: {type(e).__name__}: {err_str[:300]}"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "api_version": "1.0",
        "schema_id": schema_id,
        "schema_version": schema.version,
        "filename": file.filename,
        "file_type": ocr_result.file_type,
        "page_count": ocr_result.page_count,
        "tables_detected": table_detection.table_count,
        "processing_ms": processing_ms,
        "avg_confidence": extraction_output.avg_confidence,
        "note": "Test only — no records created, no values stored.",
        "fields": preview,
    }


# ── Schema Feedback ────────────────────────────────────────────────────────

@router.get(
    "/{schema_id}/feedback",
    summary="List pending feedback for a schema"
)
def list_schema_feedback(
    schema_id: str,
    applied: Optional[bool] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    List SchemaFeedback rows for a schema.

    applied=None (default) — all feedback
    applied=false          — only pending (not yet applied to schema rules)
    applied=true           — only already applied
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")

    query = db.query(SchemaFeedback).filter(SchemaFeedback.schema_id == schema_id)

    if applied is False:
        query = query.filter(SchemaFeedback.applied_at.is_(None))
    elif applied is True:
        query = query.filter(SchemaFeedback.applied_at.isnot(None))

    rows = query.order_by(SchemaFeedback.created_at.desc()).limit(limit).all()

    return {
        "schema_id": schema_id,
        "count": len(rows),
        "items": [
            {
                "id": fb.id,
                "field_key": fb.field_key,
                "doc_id": fb.doc_id,
                "action": fb.action,
                "before": fb.before_json,
                "after": fb.after_json,
                "confidence_at_feedback": fb.confidence_at_feedback,
                "applied_at": fb.applied_at.isoformat() if fb.applied_at else None,
                "created_at": fb.created_at.isoformat(),
            }
            for fb in rows
        ],
    }


@router.post(
    "/{schema_id}/apply-feedback",
    summary="Apply pending feedback to improve schema rules"
)
def apply_schema_feedback(
    schema_id: str,
    db: Session = Depends(get_db),
):
    """
    Apply all pending reviewer corrections to improve this schema's rules.

    Updates field hints, confidence thresholds, and feedback weights
    based on accumulated reviewer corrections.

    Safe to call at any time — only unprocessed feedback rows are applied.
    Each feedback row is marked with applied_at once processed.
    """
    from app.services.feedback_service import apply_feedback

    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")

    result = apply_feedback(schema_id, db)
    return result


# ── Schema Version History ─────────────────────────────────────────────────

@router.get(
    "/{schema_id}/versions",
    summary="List all saved versions of a schema"
)
def list_schema_versions(
    schema_id: str,
    db: Session = Depends(get_db),
):
    """
    Return the version timeline for a schema.

    Each entry is a snapshot taken just before a field edit was saved.
    The current live state is always accessible via GET /schemas/{id}.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")

    rows = (
        db.query(SchemaVersion)
        .filter(SchemaVersion.schema_id == schema_id)
        .order_by(SchemaVersion.version.desc())
        .all()
    )

    return {
        "schema_id": schema_id,
        "current_version": schema.version,
        "history_count": len(rows),
        "versions": [
            {
                "id": r.id,
                "version": r.version,
                "field_count": len(r.fields_snapshot),
                "note": r.note,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get(
    "/{schema_id}/versions/{version}",
    summary="Get a specific historical version of a schema (read-only)"
)
def get_schema_version(
    schema_id: str,
    version: int,
    db: Session = Depends(get_db),
):
    """
    Retrieve the field definitions as they were at a specific version.
    Read-only — use POST /versions/{version}/restore to revert.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")

    row = (
        db.query(SchemaVersion)
        .filter(
            SchemaVersion.schema_id == schema_id,
            SchemaVersion.version == version,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version} not found for schema '{schema_id}'"
        )

    return {
        "schema_id": schema_id,
        "version": row.version,
        "fields": row.fields_snapshot,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


@router.post(
    "/{schema_id}/versions/{version}/restore",
    response_model=SchemaOut,
    summary="Restore a historical version (creates a new version)"
)
def restore_schema_version(
    schema_id: str,
    version: int,
    db: Session = Depends(get_db),
):
    """
    Restore the schema's fields to a historical version.

    This does NOT overwrite history — it snapshots the current state
    and then sets the live fields to the selected version's snapshot,
    incrementing the version counter. Think of it as 'revert as new commit'.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")

    row = (
        db.query(SchemaVersion)
        .filter(
            SchemaVersion.schema_id == schema_id,
            SchemaVersion.version == version,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version} not found for schema '{schema_id}'"
        )

    # Snapshot current live state before overwriting
    current_snapshot = SchemaVersion(
        schema_id=schema.id,
        version=schema.version,
        fields_snapshot=schema.fields,
        note=f"Auto-snapshotted before restoring to v{version}",
    )
    db.add(current_snapshot)

    # Apply the historical snapshot as the new live fields
    schema.fields = row.fields_snapshot
    schema.version += 1
    schema.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(schema)
    return schema