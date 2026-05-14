"""
LLM Service
-----------
Handles all LLM communication for document field extraction.
Supports any provider: Groq, OpenAI, Anthropic, Ollama,
or any OpenAI-compatible endpoint.

To switch providers — change .env only. No code change needed.
"""
from typing import Optional, Any, List
from pydantic import BaseModel, create_model, Field
import instructor
import openai

from app.config import settings


# ── Build client based on configured provider ──────────────────────────────
def _build_client():
    """
    Build an Instructor-wrapped client for the configured LLM provider.
    All providers are wrapped with Instructor so they all return
    typed Pydantic models — same interface regardless of provider.
    """
    provider = settings.llm_provider.lower()

    # ── Groq ──────────────────────────────────────────────────────────
    if provider == "groq":
        from groq import Groq
        groq_client = Groq(api_key=settings.llm_api_key)
        return instructor.from_groq(
            groq_client,
            mode=instructor.Mode.JSON
        )

    # ── OpenAI ────────────────────────────────────────────────────────
    elif provider == "openai":
        openai_client = openai.OpenAI(
            api_key=settings.llm_api_key
        )
        return instructor.from_openai(openai_client)

    # ── Anthropic ─────────────────────────────────────────────────────
    elif provider == "anthropic":
        import anthropic
        anthropic_client = anthropic.Anthropic(
            api_key=settings.llm_api_key
        )
        return instructor.from_anthropic(anthropic_client)

    # ── Ollama (local) ────────────────────────────────────────────────
    elif provider == "ollama":
        base_url = settings.llm_base_url or "http://localhost:11434/v1"
        openai_client = openai.OpenAI(
            api_key="ollama",  # Ollama doesn't need a real key
            base_url=base_url,
        )
        return instructor.from_openai(openai_client)

    # ── Any OpenAI-compatible endpoint ────────────────────────────────
    elif provider == "openai_compatible":
        if not settings.llm_base_url:
            raise ValueError(
                "LLM_BASE_URL must be set for openai_compatible provider"
            )
        openai_client = openai.OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        return instructor.from_openai(openai_client)

    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Supported: groq, openai, anthropic, ollama, openai_compatible"
        )


# Initialise client once at startup
client = _build_client()


# ── Result models ──────────────────────────────────────────────────────────
class FieldResult(BaseModel):
    value: Optional[Any] = None
    confidence: float = 0.0
    missing: bool = False


class ExtractionOutput(BaseModel):
    fields: dict[str, FieldResult]
    avg_confidence: float


# ── Dynamic Pydantic model builder ────────────────────────────────────────
def build_extraction_model(schema_fields: list[dict]) -> type[BaseModel]:
    """
    Build a Pydantic model dynamically from schema field definitions.
    Instructor uses this to force the LLM into typed JSON output.
    """
    field_definitions: dict[str, Any] = {}

    for f in schema_fields:
        key = f["json_key"]
        ftype = f.get("field_type", "string")

        if ftype == "number":
            field_definitions[key] = (
                Optional[float],
                Field(default=None)
            )
        elif ftype == "boolean":
            field_definitions[key] = (
                Optional[bool],
                Field(default=None)
            )
        elif ftype == "table":
            cols = f.get("table_columns", [])
            if cols:
                # Full table: build a typed row model from column definitions
                col_defs: dict[str, Any] = {
                    c["json_key"]: (Optional[str], Field(default=None))
                    for c in cols
                }
                RowModel = create_model(f"{key}_row", **col_defs)
                field_definitions[key] = (
                    Optional[list[RowModel]],
                    Field(default=None)
                )
            else:
                # No column definitions — the LLM may return strings, dicts, or numbers.
                # Accept Any so Pydantic never rejects the response.
                field_definitions[key] = (
                    Optional[list[Any]],
                    Field(default=None)
                )
        else:
            # string | date | currency — all returned as strings
            field_definitions[key] = (
                Optional[str],
                Field(default=None)
            )

    return create_model("ExtractionModel", **field_definitions)


# ── Prompt builder ─────────────────────────────────────────────────────────
def build_extraction_prompt(
    document_text: str,
    schema_fields: list[dict]
) -> str:
    """
    Build the extraction prompt for the LLM.
    Each field includes all disambiguation rules from the schema:
    hints, anchors, exclusions, section, position preference.
    """
    field_instructions: list[str] = []

    for f in schema_fields:
        key            = f["json_key"]
        label          = f.get("label", key)
        ftype          = f.get("field_type", "string")
        hints          = f.get("hints", [label])
        anchors        = f.get("anchors", [])
        exclude        = f.get("exclude_if_near", [])
        section        = f.get("section", "")
        position       = f.get("position_preference", "")
        description    = f.get("description", "")
        required       = f.get("required", False)

        lines = [
            f"- {key} ({ftype}{'  REQUIRED' if required else ''}):"
        ]
        lines.append(f"  Look for labels: {hints}")

        if anchors:
            lines.append(
                f"  Prefer occurrence if nearby text includes: {anchors}"
            )
        if exclude:
            lines.append(
                f"  Reject occurrence if nearby text includes: {exclude}"
            )
        if section:
            lines.append(
                f"  Expected in document section: {section}"
            )
        if position:
            lines.append(
                f"  If multiple found, take: {position}"
            )
        if description:
            lines.append(f"  Important: {description}")

        if ftype == "table":
            cols = [c["json_key"] for c in f.get("table_columns", [])]
            if cols:
                col_hints = {
                    c["json_key"]: c.get("hints", [c["json_key"]])
                    for c in f.get("table_columns", [])
                }
                lines.append(
                    f"  Extract as array of row objects with columns: {cols}"
                )
                lines.append(
                    f"  Column label hints: {col_hints}"
                )
                lines.append(
                    "  Include ALL rows — even if table spans multiple pages."
                )
            else:
                # No column definitions — extract every occurrence as a flat list
                lines.append(
                    f"  This value repeats for each line/row in the document."
                )
                lines.append(
                    "  Extract as a flat JSON array — one element per row, in order."
                )
                lines.append(
                    "  Include ALL occurrences — do not pick just the first one."
                )

        field_instructions.append("\n".join(lines))

    fields_text = "\n\n".join(field_instructions)

    return f"""You are a document data extraction expert.

RULES:
- Extract ONLY the fields listed below.
- Return null for any field not found in the document.
- Never invent or guess values.
- Only extract text that is explicitly present in the document.
- For fields with multiple candidate locations, use the
  anchor and exclusion hints to pick the correct one.
- For table fields, extract every row as an object
  with the specified column keys.
- Return values exactly as they appear in the document.

FIELDS TO EXTRACT:
{fields_text}

DOCUMENT TEXT:
{document_text}
"""


# ── Confidence calculator ──────────────────────────────────────────────────
def calculate_confidence(value: Any, field_type: str) -> float:
    """
    Estimate confidence score for an extracted value.
    Range: 0.0 (missing/empty) to 1.0 (present and plausible).
    """
    if value is None:
        return 0.0

    if isinstance(value, list):
        if len(value) == 0:
            return 0.0
        return 0.88  # Table with rows extracted

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0.0
        if len(stripped) < 3:
            return 0.70
        return 0.90

    if isinstance(value, (int, float)):
        return 0.90

    return 0.80


# ── Main extraction function ───────────────────────────────────────────────
def extract_fields(
    document_text: str,
    schema_fields: list[dict],
) -> ExtractionOutput:
    """
    Extract fields from document text using the configured LLM.
    Returns typed ExtractionOutput with per-field confidence scores.

    Works with any provider — Groq, OpenAI, Anthropic, Ollama.
    The provider is determined by LLM_PROVIDER in .env.
    """
    if not schema_fields:
        return ExtractionOutput(fields={}, avg_confidence=0.0)

    # Build dynamic Pydantic model and prompt
    ExtractionModel = build_extraction_model(schema_fields)
    prompt = build_extraction_prompt(document_text, schema_fields)

    # Call LLM via Instructor
    # Instructor forces the response into the typed Pydantic model
    # regardless of which provider is used
    result = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a document extraction expert. "
                    "Extract fields exactly as instructed. "
                    "Return only valid JSON. "
                    "Never include explanations or extra text."
                ),
            },
            {
                "role": "user",
                "content": prompt
            },
        ],
        response_model=ExtractionModel,
        temperature=0,      # Always deterministic for extraction
        max_tokens=4096,
    )

    # Build per-field results with confidence scores
    field_results: dict[str, FieldResult] = {}
    confidences: list[float] = []

    for f in schema_fields:
        key = f["json_key"]
        raw_value = getattr(result, key, None)

        # Convert Pydantic row models to plain dicts for full table fields
        if f.get("field_type") == "table" and raw_value is not None:
            if f.get("table_columns"):
                # Full table with columns — convert row models to dicts
                raw_value = [
                    row.model_dump()
                    if hasattr(row, "model_dump")
                    else row
                    for row in raw_value
                ]
            # else: flat list of scalars — already plain Python, no conversion needed

        confidence = calculate_confidence(
            raw_value, f.get("field_type", "string")
        )
        missing = (
            raw_value is None
            or raw_value == []
            or raw_value == ""
        )

        field_results[key] = FieldResult(
            value=raw_value if not missing else None,
            confidence=confidence,
            missing=missing,
        )
        confidences.append(confidence)

    avg_confidence = (
        sum(confidences) / len(confidences)
        if confidences else 0.0
    )

    return ExtractionOutput(
        fields=field_results,
        avg_confidence=round(avg_confidence, 3),
    )


# ── Schema proposal models ─────────────────────────────────────────────────

class TableColumnProposal(BaseModel):
    json_key: str
    hints: List[str] = []
    type: str = "string"


class FieldProposal(BaseModel):
    json_key: str
    label: str
    field_type: str = "string"
    hints: List[str] = []
    anchors: List[str] = []
    exclude_if_near: List[str] = []
    section: str = ""
    position_preference: str = ""
    description: str = ""
    required: bool = False
    confidence_threshold: float = 0.80
    feedback_weight: float = 1.0
    ambiguity_flag: bool = False
    table_columns: List[TableColumnProposal] = []


class SchemaProposal(BaseModel):
    document_type_detected: str = ""
    fields: List[FieldProposal]


# ── Schema proposal function ───────────────────────────────────────────────

def propose_schema(
    document_text: str,
    document_type_hint: str = "",
) -> SchemaProposal:
    """
    Call the configured LLM to propose a complete extraction schema
    from a sample document's OCR text.

    This is a one-time call per schema creation — not per document processed.
    The proposed fields contain only rules (hints, anchors, types) —
    never any values from the sample document.

    Returns a SchemaProposal that the user can review, edit, and save.
    """
    type_hint = (
        f"The document type is likely: {document_type_hint}. "
        if document_type_hint
        else ""
    )

    prompt = f"""Analyse the document text below and propose an extraction schema.

{type_hint}

STRICT RULE: Only propose fields whose label or key explicitly appears in the document text.
Do NOT invent fields based on your knowledge of typical documents.
Do NOT add fields for information that is absent from this document.

--- DETECTING TABLES ---
A table is a section of the document where the SAME set of column headers repeats for multiple rows of data.
Look for a group of column header labels followed by repeating rows of values.

If you detect a table:
- Create ONE field with field_type="table" representing the entire table.
- Use a descriptive snake_case json_key for the table (e.g. "line_items", "charges_table").
- In table_columns, list EVERY column header that appears in the table.
  For each column: set json_key (snake_case), label (exact header text), hints (2-3 label variations), field_type (string/number/currency/date).
- Do NOT create separate scalar fields for columns that belong to the table
  (e.g. if QUANTITY is a table column, do not also add a scalar "quantity" field).

--- SCALAR FIELDS ---
For each label that appears ONCE (not repeating per row):
- Suggest a snake_case json_key
- Copy the exact label text from the document
- Generate 2-4 hint aliases
- If it appears in multiple locations, set ambiguity_flag=true and add anchors/exclude_if_near
- Set section: header | table | footer
- Set field_type: string | number | date | currency | boolean
- Write a 1-sentence description
- Set required=true only if clearly critical for this document type
- Set confidence_threshold between 0.70 and 0.95

IMPORTANT:
- Propose extraction rules only — never include actual values from the document
- Only propose fields you can directly see in the document text
- Table columns must all go inside one table field's table_columns — not as separate scalar fields

DOCUMENT TEXT:
{document_text}
"""

    return client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a document analyst. "
                    "Your job is to read the provided document text and propose extraction rules "
                    "ONLY for fields that are explicitly visible in that document. "
                    "Never invent fields based on your training knowledge of typical document types. "
                    "If a field is not in the document, do not include it. "
                    "Return only valid JSON matching the response model."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_model=SchemaProposal,
        temperature=0,
        max_tokens=4096,
    )