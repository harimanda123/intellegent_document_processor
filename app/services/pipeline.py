"""
Pipeline Service
----------------
Orchestrates the full document extraction pipeline.

Stages:
  0. Validate file exists
  1. OCR — extract text and positions
  2. Layout analysis (header/footer strip)
  3. Table detection & stitching
  4. Load schema
  5. LLM Extraction — extract fields using schema rules
  6. Save extraction results
  7. Final state — VERIFIED or PENDING_REVIEW

Retry policy:
  Retryable errors (OCR_FAILED, EXTRACTION_FAILED) are retried up to
  MAX_RETRIES times. After that the document moves to ABANDONED.

Runs as a FastAPI BackgroundTask so the upload
response is returned immediately to the user.
"""
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.document import Document, Extraction, AuditLog
from app.models.schema import DocSchema
from app.services.ocr_service import (
    run_ocr,
    build_llm_document_text,
    find_spatial_anchor,
)
from app.services.table_service import run_table_detection, build_table_text
from app.services.llm_service import extract_fields
from app.config import settings

MAX_RETRIES = 3

RETRYABLE_ERRORS = {"OCR_FAILED", "EXTRACTION_FAILED", "PIPELINE_ERROR"}


# ── State transition helper ────────────────────────────────────────────────

def update_state(
    db: Session,
    doc: Document,
    state: str,
    progress: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """
    Update document state and write an audit log entry.
    Every state transition is recorded immutably.
    """
    old_state = doc.state

    doc.state = state
    doc.progress = progress
    doc.updated_at = datetime.utcnow()

    if error_code:
        doc.error_code = error_code
        doc.error_message = error_message

    # Immutable audit log entry
    log = AuditLog(
        doc_id=doc.id,
        action=f"state_change",
        actor="system",
        old_value=old_state,
        new_value=f"{state}" + (f":{progress}" if progress else ""),
    )
    db.add(log)
    db.commit()


# ── Retry helper ───────────────────────────────────────────────────────────

def _maybe_retry(doc_id: str, db: Session) -> None:
    """
    After a FAILED state, check if the document is eligible for retry.
    Retryable error codes are retried up to MAX_RETRIES times.
    Beyond that the document moves to ABANDONED.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        return

    if doc.error_code not in RETRYABLE_ERRORS:
        return

    if doc.retry_count >= MAX_RETRIES:
        update_state(
            db, doc, "ABANDONED",
            error_code=doc.error_code,
            error_message=(
                f"Abandoned after {MAX_RETRIES} retries. "
                f"Last error: {doc.error_message}"
            ),
        )
        return

    # Increment retry counter and re-queue
    doc.retry_count += 1
    doc.updated_at = datetime.utcnow()
    db.commit()

    log = AuditLog(
        doc_id=doc_id,
        action="retry_queued",
        actor="system",
        new_value=f"attempt={doc.retry_count}/{MAX_RETRIES}",
    )
    db.add(log)
    db.commit()

    # Re-run synchronously within the same background task
    run_pipeline(doc_id, db)


def retry_document(doc_id: str, db: Session) -> None:
    """
    Manually trigger a retry for a FAILED document.
    Called from the admin UI or API. Resets retry_count to allow
    another full set of MAX_RETRIES attempts.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        return
    if doc.state not in ("FAILED", "ABANDONED"):
        return

    doc.retry_count = 0
    doc.error_code = None
    doc.error_message = None
    doc.updated_at = datetime.utcnow()
    update_state(db, doc, "RECEIVED")

    run_pipeline(doc_id, db)

def run_pipeline(doc_id: str, db: Session) -> None:
    """
    Run the full extraction pipeline for a document.

    Called as a FastAPI BackgroundTask after upload.
    The HTTP response has already been sent to the user
    before this function runs.
    """
    # Load document
    doc = db.get(Document, doc_id)
    if not doc:
        return

    start_time = time.time()

    try:
        # ── Stage 1: Validate file ───────────────────────────────────
        file_path = Path(doc.file_path)
        if not file_path.exists():
            update_state(
                db, doc, "FAILED",
                error_code="FILE_NOT_FOUND",
                error_message=f"File not found: {file_path}",
            )
            return

        # ── Stage 2: OCR ─────────────────────────────────────────────
        update_state(db, doc, "PROCESSING", progress="ocr_running")

        try:
            ocr_result = run_ocr(file_path)
        except NotImplementedError as e:
            update_state(
                db, doc, "FAILED",
                error_code="FILE_UNSUPPORTED",
                error_message=str(e),
            )
            return
        except Exception as e:
            update_state(
                db, doc, "FAILED",
                error_code="OCR_FAILED",
                error_message=str(e),
            )
            return

        # Save OCR metadata to document
        doc.file_type = ocr_result.file_type
        doc.page_count = ocr_result.page_count
        update_state(db, doc, "PROCESSING", progress="ocr_complete")

        # ── Stage 3: Table Detection & Stitching ─────────────────────
        update_state(db, doc, "PROCESSING", progress="table_detection")

        try:
            table_detection = run_table_detection(ocr_result)
        except Exception:
            # Table detection failure is non-fatal — proceed without tables
            from app.services.table_service import TableDetectionResult
            table_detection = TableDetectionResult(tables=[])

        # ── Stage 4: Load schema ─────────────────────────────────────
        schema = db.get(DocSchema, doc.schema_id)
        if not schema:
            update_state(
                db, doc, "FAILED",
                error_code="SCHEMA_NOT_FOUND",
                error_message=f"Schema not found: {doc.schema_id}",
            )
            return

        if not schema.fields:
            update_state(
                db, doc, "FAILED",
                error_code="SCHEMA_EMPTY",
                error_message="Schema has no fields defined.",
            )
            return

        # ── Stage 5: LLM Extraction ──────────────────────────────────
        update_state(db, doc, "PROCESSING", progress="ai_extraction")

        # Combine OCR body text with structured table text for the LLM
        document_text = build_llm_document_text(ocr_result)
        table_text = build_table_text(table_detection)
        if table_text:
            document_text = document_text + "\n\nDETECTED TABLES:\n" + table_text

        try:
            extraction_output = extract_fields(
                document_text=document_text,
                schema_fields=schema.fields,
            )
        except Exception as e:
            update_state(
                db, doc, "FAILED",
                error_code="EXTRACTION_FAILED",
                error_message=str(e),
            )
            return

        # ── Stage 6: Save results ────────────────────────────────────
        update_state(db, doc, "PROCESSING", progress="saving")

        # Remove any previous extractions for this document
        db.query(Extraction).filter(
            Extraction.doc_id == doc.id
        ).delete()

        # Save each field result
        for field_key, field_result in extraction_output.fields.items():

            # Find field definition to get field_type
            field_def = next(
                (f for f in schema.fields if f["json_key"] == field_key),
                None
            )
            field_type = (
                field_def.get("field_type", "string")
                if field_def else "string"
            )

            # Find spatial anchor for this field
            # Generated fresh from THIS document's OCR
            # Never from schema or sample document
            spatial_anchor = None
            if (
                field_result.value
                and not field_result.missing
                and field_type != "table"
            ):
                spatial_anchor = find_spatial_anchor(
                    str(field_result.value),
                    ocr_result,
                )

            extraction = Extraction(
                doc_id=doc.id,
                field_key=field_key,
                field_type=field_type,
                value_json={"value": field_result.value},
                confidence=field_result.confidence,
                missing=field_result.missing,
                human_edited=False,
                spatial_anchor=spatial_anchor,
            )
            db.add(extraction)

        # Update document summary stats
        processing_ms = int((time.time() - start_time) * 1000)
        doc.processing_ms = processing_ms
        doc.avg_confidence = extraction_output.avg_confidence

        # Record which LLM was used
        doc.llm_provider = settings.llm_provider
        doc.llm_model = settings.llm_model

        # ── Stage 7: Final state ─────────────────────────────────────
        # Determine whether review is needed:
        #   require_review=True → always PENDING_REVIEW
        #   require_review_mode="auto" → decide by confidence score
        #   otherwise → VERIFIED (sits here until user downloads)

        needs_review = doc.require_review

        if not needs_review and doc.require_review_mode == "auto":
            avg_conf = extraction_output.avg_confidence
            if avg_conf < settings.auto_review_threshold:
                needs_review = True

        if needs_review:
            update_state(
                db, doc, "PENDING_REVIEW",
                progress="pending_review",
            )
        else:
            update_state(db, doc, "VERIFIED")

    except Exception as e:
        # Safety net — catch any unexpected error
        error_code = getattr(e, "error_code", "PIPELINE_ERROR")
        update_state(
            db, doc, "FAILED",
            error_code=error_code,
            error_message=str(e),
        )
        _maybe_retry(doc_id, db)