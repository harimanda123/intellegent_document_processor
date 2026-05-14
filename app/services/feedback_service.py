"""
Feedback Service
----------------
Applies accumulated reviewer corrections to improve schema field rules.

Spec Section 4.8 / Technical Spec Section 3.2 Step 5:
  "Every human correction during document review automatically
   improves the schema for future documents."

How it works:
  1. Read all SchemaFeedback rows for a schema that haven't been applied yet.
  2. For each field_edited correction:
     - The new value's label text → added to hints if not already present.
     - The old (wrong) value's spatial context is unknown at this stage,
       so we increase confidence_threshold slightly to demand more certainty.
  3. For each approved row (all fields accepted, high confidence):
     - Decrease confidence_threshold slightly (schema is maturing).
     - Increase feedback_weight to signal stability.
  4. Mark feedback rows as applied by recording apply timestamp.

This runs either:
  - On demand via POST /api/schemas/{id}/apply-feedback
  - Automatically after every document approval (called from pipeline)
"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.schema import DocSchema, SchemaFeedback


# ── Tunables ───────────────────────────────────────────────────────────────

# How much to raise the confidence threshold per edit correction
THRESHOLD_BUMP_PER_EDIT = 0.01

# How much to lower the threshold per approved (stable) field
THRESHOLD_EASE_PER_APPROVAL = 0.005

# Clamps
MIN_THRESHOLD = 0.60
MAX_THRESHOLD = 0.98

# Minimum edit corrections before we start bumping threshold
MIN_EDITS_TO_TUNE = 2


# ── Main apply function ────────────────────────────────────────────────────

def apply_feedback(schema_id: str, db: Session) -> dict:
    """
    Apply all pending SchemaFeedback rows for a schema to improve its rules.

    Returns a summary of what was changed.
    """
    schema = db.get(DocSchema, schema_id)
    if not schema:
        return {"error": f"Schema '{schema_id}' not found"}

    # Load all unprocessed feedback for this schema
    pending = (
        db.query(SchemaFeedback)
        .filter(
            SchemaFeedback.schema_id == schema_id,
            SchemaFeedback.applied_at.is_(None),
        )
        .all()
    )

    if not pending:
        return {
            "schema_id": schema_id,
            "feedback_applied": 0,
            "fields_updated": 0,
            "changes": [],
        }

    # Build a mutable copy of schema fields indexed by json_key
    fields_by_key: dict[str, dict] = {
        f["json_key"]: dict(f) for f in schema.fields
    }

    changes: list[str] = []

    # Group feedback by field_key
    by_field: dict[str, list[SchemaFeedback]] = {}
    for fb in pending:
        by_field.setdefault(fb.field_key, []).append(fb)

    for field_key, feedbacks in by_field.items():
        if field_key not in fields_by_key:
            continue

        field = fields_by_key[field_key]
        hints: list[str] = list(field.get("hints", []))
        threshold: float = float(field.get("confidence_threshold", 0.80))
        feedback_weight: float = float(field.get("feedback_weight", 1.0))

        edits = [fb for fb in feedbacks if fb.action == "field_edited"]
        approvals = [fb for fb in feedbacks if fb.action == "approved"]

        # ── Apply edits ────────────────────────────────────────────────
        if len(edits) >= MIN_EDITS_TO_TUNE:
            for edit in edits:
                # Add the corrected value as a hint if it looks like a label
                # (short text, not a number or long sentence)
                after = edit.after_json or {}
                corrected = str(after.get("value", "")).strip()
                if (
                    corrected
                    and len(corrected) <= 60
                    and corrected not in hints
                    and not corrected.replace(".", "").replace(",", "").isdigit()
                ):
                    hints.append(corrected)
                    changes.append(
                        f"{field_key}: added hint '{corrected}'"
                    )

            # Bump threshold — AI was wrong, demand higher confidence
            new_threshold = min(
                threshold + THRESHOLD_BUMP_PER_EDIT * len(edits),
                MAX_THRESHOLD,
            )
            if new_threshold != threshold:
                changes.append(
                    f"{field_key}: confidence_threshold "
                    f"{threshold:.3f} → {new_threshold:.3f}"
                )
                threshold = new_threshold

        # ── Apply approvals ────────────────────────────────────────────
        if approvals:
            # High-confidence approvals → schema is maturing, ease threshold
            high_conf_approvals = [
                fb for fb in approvals
                if (fb.confidence_at_feedback or 0) >= 0.90
            ]
            if high_conf_approvals:
                new_threshold = max(
                    threshold - THRESHOLD_EASE_PER_APPROVAL * len(high_conf_approvals),
                    MIN_THRESHOLD,
                )
                if new_threshold != threshold:
                    changes.append(
                        f"{field_key}: confidence_threshold eased "
                        f"{threshold:.3f} → {new_threshold:.3f}"
                    )
                    threshold = new_threshold

                # feedback_weight signals schema maturity
                # As schemas mature, updates become more conservative
                feedback_weight = max(0.5, feedback_weight - 0.01 * len(high_conf_approvals))

        # Write back
        field["hints"] = hints
        field["confidence_threshold"] = round(threshold, 3)
        field["feedback_weight"] = round(feedback_weight, 3)
        fields_by_key[field_key] = field

    # Persist updated fields to the schema
    schema.fields = list(fields_by_key.values())
    schema.updated_at = datetime.utcnow()

    # Mark all feedback rows as applied
    now = datetime.utcnow()
    for fb in pending:
        fb.applied_at = now

    db.commit()

    return {
        "schema_id": schema_id,
        "feedback_applied": len(pending),
        "fields_updated": len(by_field),
        "changes": changes,
    }
