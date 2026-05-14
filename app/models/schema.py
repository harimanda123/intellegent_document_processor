import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class DocSchema(Base):
    """
    Tenant's extraction schema.
    Stores rules only — no document values, no coordinates.
    Every field definition contains hints, anchors, types.
    Never stores any content from sample documents.
    """
    __tablename__ = "doc_schemas"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=new_id
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    document_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    # commercial_invoice | packing_list | bill_of_lading | custom

    description: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1
    )
    status: Mapped[str] = mapped_column(
        String(50), default="draft"
    )
    # draft | active | archived

    # JSON array of field definitions.
    # Each field: json_key, label, field_type, hints,
    # anchors, exclude_if_near, section, position_preference,
    # description, required, validation, confidence_threshold,
    # table_columns (for table type fields)
    # IMPORTANT: rules only — never document values
    fields: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<DocSchema id={self.id} name={self.name} status={self.status}>"


class SchemaFeedback(Base):
    """
    Records every reviewer correction for the schema feedback loop.

    Each correction is used to automatically improve the schema:
    - Wrong field value found → hints updated
    - Wrong field location chosen → anchors / exclude_if_near updated
    - All fields accepted with high confidence → stability score rises

    Rows are append-only. Never updated or deleted.
    """
    __tablename__ = "schema_feedback"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=new_id
    )
    schema_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    doc_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    # field_edited | cell_edited | approved | rejected
    action: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    # Original AI extraction for this field
    before_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    # Reviewer's corrected value
    after_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    # Confidence at time of feedback
    confidence_at_feedback: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # Set when feedback_service.apply_feedback() processes this row
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def __repr__(self):
        return (
            f"<SchemaFeedback schema={self.schema_id} "
            f"field={self.field_key} action={self.action}>"
        )


class SchemaVersion(Base):
    """
    Immutable snapshot of a schema's fields at each version bump.

    A new row is written every time PUT /schemas/{id} increments
    the version counter.  Enables the version timeline, read-only
    inspection, and restore-as-new-version workflows.
    """
    __tablename__ = "schema_versions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=new_id
    )
    schema_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    # Complete snapshot of schema.fields at this version
    fields_snapshot: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    # Human-readable note (optional; set when restoring)
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def __repr__(self):
        return (
            f"<SchemaVersion schema={self.schema_id} v{self.version}>"
        )