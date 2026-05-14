import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, Float, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class Document(Base):
    """
    A document submitted for extraction.
    Tracks the full lifecycle from upload to download.
    """
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=new_id
    )
    label: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    filename: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    file_path: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    schema_id: Mapped[str] = mapped_column(
        String, nullable=False
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1
    )

    # Source of the document
    source: Mapped[str] = mapped_column(
        String(50), default="ui"
    )
    # ui | erp

    # ERP integration fields
    erp_reference_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )

    # Review
    require_review: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    # Stores the original require_review flag from ERP/UI:
    # "false" | "true" | "auto"
    # "auto" lets the pipeline decide based on confidence score.
    require_review_mode: Mapped[str] = mapped_column(
        String(10), default="false"
    )

    # ── Lifecycle state ────────────────────────────────────────────────
    state: Mapped[str] = mapped_column(
        String(50), default="RECEIVED"
    )
    # RECEIVED | PROCESSING | VERIFIED | PENDING_REVIEW
    # FAILED | ABANDONED | DOWNLOADED

    progress: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    # queued | ocr_running | ocr_complete
    # table_detection | ai_extraction
    # pending_review | delivering

    error_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0
    )

    # ── Processing metadata ────────────────────────────────────────────
    file_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    # native_text | scanned_image | mixed

    page_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    processing_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    avg_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # LLM used for this document (captured at extraction time)
    llm_provider: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    llm_model: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Document id={self.id} state={self.state}>"


class Extraction(Base):
    """
    Per-field extraction result for a document.
    Spatial anchors are generated fresh from each document's
    own OCR output — never copied from schema or sample document.
    """
    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=new_id
    )
    doc_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    field_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    # string | number | date | currency | boolean | table

    # Scalar: {"value": "INV-2026-00421"}
    # Table:  {"value": [{"col1": "...", "col2": "..."}, ...]}
    value_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )

    confidence: Mapped[float] = mapped_column(
        Float, default=0.0
    )
    human_edited: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    # Stores original AI value when reviewer edits a field
    original_value_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    missing: Mapped[bool] = mapped_column(
        Boolean, default=False
    )

    # Bounding box — generated from THIS document's OCR
    # Never from the schema or any sample document
    spatial_anchor: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    # {"page": 1, "x": 142, "y": 88, "w": 210, "h": 18}

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def __repr__(self):
        return f"<Extraction doc={self.doc_id} field={self.field_key}>"


class AuditLog(Base):
    """
    Immutable audit trail. Every action on every document is logged.
    Append-only — rows are never updated or deleted.
    """
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=new_id
    )
    doc_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    # document_uploaded | state_change | field_edited
    # document_approved | document_rejected | json_downloaded
    # erp_submit | erp_delivered

    actor: Mapped[str] = mapped_column(
        String(100), default="system"
    )
    old_value: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    new_value: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def __repr__(self):
        return f"<AuditLog doc={self.doc_id} action={self.action}>"