"""
Dashboard Router
----------------
Live queue, quick stats, document history summary, and analytics.

Spec Section 8 — Dashboard:
  - Live Queue:       Documents in PROCESSING or PENDING_REVIEW
  - Quick Stats:      Counts for today's activity
  - Document History: Searchable/filterable full history table
  - Analytics:        Volume, avg confidence, per-schema performance

All endpoints are read-only — no state mutations.
"""
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.document import Document, Extraction
from app.models.schema import DocSchema

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ── Live Queue ─────────────────────────────────────────────────────────────

@router.get(
    "/queue",
    summary="Live processing queue"
)
def live_queue(db: Session = Depends(get_db)):
    """
    Returns all documents currently in PROCESSING or PENDING_REVIEW state.
    Designed for the dashboard live queue panel — refresh every 30 seconds.
    """
    active_states = ("PROCESSING", "PENDING_REVIEW", "RECEIVED")

    docs = (
        db.query(Document)
        .filter(Document.state.in_(active_states))
        .order_by(Document.created_at.desc())
        .all()
    )

    queue = []
    now = datetime.utcnow()

    for doc in docs:
        time_in_state_s = int((now - doc.updated_at).total_seconds())
        queue.append({
            "doc_id": doc.id,
            "label": doc.label or doc.filename,
            "filename": doc.filename,
            "schema_id": doc.schema_id,
            "state": doc.state,
            "progress": doc.progress,
            "source": doc.source,
            "require_review": doc.require_review,
            "time_in_state_seconds": time_in_state_s,
            "created_at": doc.created_at.isoformat(),
        })

    return {
        "count": len(queue),
        "items": queue,
    }


# ── Quick Stats ────────────────────────────────────────────────────────────

@router.get(
    "/stats",
    summary="Quick stats for today"
)
def quick_stats(db: Session = Depends(get_db)):
    """
    Counts for the current day's activity.
    Refreshes every 30 seconds in the dashboard.

    Returns:
      - documents_today:    Total uploaded today
      - pending_review:     Currently in PENDING_REVIEW
      - verified_today:     Moved to VERIFIED or DOWNLOADED today
      - failed_today:       Moved to FAILED today
      - processing_now:     Currently in PROCESSING
      - avg_confidence_today: Average confidence score for today's docs
    """
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    total_today = (
        db.query(func.count(Document.id))
        .filter(Document.created_at >= today_start)
        .scalar()
    )

    pending_review = (
        db.query(func.count(Document.id))
        .filter(Document.state == "PENDING_REVIEW")
        .scalar()
    )

    verified_today = (
        db.query(func.count(Document.id))
        .filter(
            Document.state.in_(("VERIFIED", "DOWNLOADED")),
            Document.updated_at >= today_start,
        )
        .scalar()
    )

    failed_today = (
        db.query(func.count(Document.id))
        .filter(
            Document.state == "FAILED",
            Document.updated_at >= today_start,
        )
        .scalar()
    )

    processing_now = (
        db.query(func.count(Document.id))
        .filter(Document.state.in_(("RECEIVED", "PROCESSING")))
        .scalar()
    )

    avg_conf_row = (
        db.query(func.avg(Document.avg_confidence))
        .filter(
            Document.created_at >= today_start,
            Document.avg_confidence.isnot(None),
        )
        .scalar()
    )
    avg_confidence_today = round(avg_conf_row, 3) if avg_conf_row else None

    return {
        "as_of": datetime.utcnow().isoformat(),
        "documents_today": total_today,
        "pending_review": pending_review,
        "verified_today": verified_today,
        "failed_today": failed_today,
        "processing_now": processing_now,
        "avg_confidence_today": avg_confidence_today,
    }


# ── Document History ───────────────────────────────────────────────────────

@router.get(
    "/history",
    summary="Full document history with search and filters"
)
def document_history(
    state: Optional[str] = Query(None, description="Filter by state"),
    schema_id: Optional[str] = Query(None, description="Filter by schema ID"),
    source: Optional[str] = Query(None, description="Filter by source: ui | erp"),
    date_from: Optional[date] = Query(None, description="From date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="To date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search label or filename"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Full document history table for the dashboard.
    Supports filtering by state, schema, source, date range, and text search.
    Returns total count for pagination alongside the page of results.
    """
    query = db.query(Document)

    if state:
        query = query.filter(Document.state == state)
    if schema_id:
        query = query.filter(Document.schema_id == schema_id)
    if source:
        query = query.filter(Document.source == source)
    if date_from:
        query = query.filter(
            Document.created_at >= datetime.combine(date_from, datetime.min.time())
        )
    if date_to:
        query = query.filter(
            Document.created_at <= datetime.combine(date_to, datetime.max.time())
        )
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            Document.label.ilike(pattern) | Document.filename.ilike(pattern)
        )

    total = query.count()

    docs = (
        query
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for doc in docs:
        items.append({
            "doc_id": doc.id,
            "label": doc.label or doc.filename,
            "filename": doc.filename,
            "schema_id": doc.schema_id,
            "schema_version": doc.schema_version,
            "state": doc.state,
            "source": doc.source,
            "erp_reference_id": doc.erp_reference_id,
            "require_review": doc.require_review,
            "avg_confidence": doc.avg_confidence,
            "processing_ms": doc.processing_ms,
            "file_type": doc.file_type,
            "page_count": doc.page_count,
            "error_code": doc.error_code,
            "retry_count": doc.retry_count,
            "created_at": doc.created_at.isoformat(),
            "updated_at": doc.updated_at.isoformat(),
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


# ── Analytics ──────────────────────────────────────────────────────────────

@router.get(
    "/analytics",
    summary="Volume, confidence, and per-schema performance analytics"
)
def analytics(
    days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    db: Session = Depends(get_db),
):
    """
    Analytics data for the dashboard charts.

    Returns:
      - daily_volume:       Document count per day for the lookback period
      - state_funnel:       Count of documents in each terminal state
      - by_schema:          Per-schema performance (volume, avg confidence, edit rate)
      - overall_avg_confidence: Overall average confidence across all docs
      - human_edit_rate:    Fraction of extraction fields edited by reviewers
      - avg_processing_ms:  Average pipeline duration
    """
    since = datetime.utcnow() - timedelta(days=days)

    # ── Daily volume ───────────────────────────────────────────────────
    daily_rows = (
        db.query(
            func.date(Document.created_at).label("day"),
            func.count(Document.id).label("count"),
        )
        .filter(Document.created_at >= since)
        .group_by(func.date(Document.created_at))
        .order_by(func.date(Document.created_at))
        .all()
    )
    daily_volume = [
        {"date": str(row.day), "count": row.count}
        for row in daily_rows
    ]

    # ── State funnel ───────────────────────────────────────────────────
    state_rows = (
        db.query(
            Document.state,
            func.count(Document.id).label("count"),
        )
        .filter(Document.created_at >= since)
        .group_by(Document.state)
        .all()
    )
    state_funnel = {row.state: row.count for row in state_rows}

    # ── Per-schema performance ─────────────────────────────────────────
    schema_rows = (
        db.query(
            Document.schema_id,
            func.count(Document.id).label("volume"),
            func.avg(Document.avg_confidence).label("avg_confidence"),
            func.avg(Document.processing_ms).label("avg_processing_ms"),
        )
        .filter(Document.created_at >= since)
        .group_by(Document.schema_id)
        .all()
    )

    by_schema = []
    for row in schema_rows:
        schema = db.get(DocSchema, row.schema_id)
        schema_name = schema.name if schema else row.schema_id

        # Human edit rate for this schema
        total_fields = (
            db.query(func.count(Extraction.id))
            .join(Document, Document.id == Extraction.doc_id)
            .filter(
                Document.schema_id == row.schema_id,
                Document.created_at >= since,
            )
            .scalar()
        ) or 0

        edited_fields = (
            db.query(func.count(Extraction.id))
            .join(Document, Document.id == Extraction.doc_id)
            .filter(
                Document.schema_id == row.schema_id,
                Document.created_at >= since,
                Extraction.human_edited.is_(True),
            )
            .scalar()
        ) or 0

        edit_rate = round(edited_fields / total_fields, 3) if total_fields else 0.0

        by_schema.append({
            "schema_id": row.schema_id,
            "schema_name": schema_name,
            "volume": row.volume,
            "avg_confidence": round(row.avg_confidence, 3) if row.avg_confidence else None,
            "avg_processing_ms": int(row.avg_processing_ms) if row.avg_processing_ms else None,
            "human_edit_rate": edit_rate,
        })

    # ── Overall stats ──────────────────────────────────────────────────
    overall_conf = (
        db.query(func.avg(Document.avg_confidence))
        .filter(
            Document.created_at >= since,
            Document.avg_confidence.isnot(None),
        )
        .scalar()
    )

    overall_ms = (
        db.query(func.avg(Document.processing_ms))
        .filter(
            Document.created_at >= since,
            Document.processing_ms.isnot(None),
        )
        .scalar()
    )

    total_fields_all = (
        db.query(func.count(Extraction.id))
        .join(Document, Document.id == Extraction.doc_id)
        .filter(Document.created_at >= since)
        .scalar()
    ) or 0

    edited_fields_all = (
        db.query(func.count(Extraction.id))
        .join(Document, Document.id == Extraction.doc_id)
        .filter(
            Document.created_at >= since,
            Extraction.human_edited.is_(True),
        )
        .scalar()
    ) or 0

    return {
        "period_days": days,
        "since": since.isoformat(),
        "overall_avg_confidence": round(overall_conf, 3) if overall_conf else None,
        "avg_processing_ms": int(overall_ms) if overall_ms else None,
        "human_edit_rate": (
            round(edited_fields_all / total_fields_all, 3)
            if total_fields_all else 0.0
        ),
        "daily_volume": daily_volume,
        "state_funnel": state_funnel,
        "by_schema": by_schema,
    }
