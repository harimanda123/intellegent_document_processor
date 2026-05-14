"""
Table Service
-------------
Detects and extracts table structures from documents.

Current: Heuristic detection from OCR word positions.
Future:  Table Transformer (MIT licence) for production accuracy.
         Integration point is the run_table_detection() function.

Table Transformer Reference:
  Model: microsoft/table-transformer-detection
  Licence: MIT
  Achieves 0.91 AP on PubTables-1M (1M annotated tables).
  Requires: transformers, torch — add to pyproject.toml for v1.1.
"""
from dataclasses import dataclass, field
from app.services.ocr_service import OCRResult, Word


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class TableCell:
    """A single cell in a detected table."""
    text: str
    row_index: int
    col_index: int
    page: int
    x: float
    y: float
    w: float
    h: float


@dataclass
class DetectedTable:
    """
    A table detected in the document.
    Contains the header row and all data rows.
    pages_spanned tracks which pages the table covers.
    """
    table_index: int
    headers: list[str]
    rows: list[list[str]]       # rows[row_idx][col_idx]
    pages_spanned: list[int]
    cells: list[TableCell] = field(default_factory=list)

    def as_dicts(self) -> list[dict]:
        """Return rows as list of dicts keyed by header."""
        result = []
        for row in self.rows:
            row_dict = {}
            for i, header in enumerate(self.headers):
                row_dict[header] = row[i] if i < len(row) else ""
            result.append(row_dict)
        return result


@dataclass
class TableDetectionResult:
    """Complete table detection output for an entire document."""
    tables: list[DetectedTable]

    @property
    def table_count(self) -> int:
        return len(self.tables)


# ── Heuristic table detector ───────────────────────────────────────────────

def _cluster_words_into_rows(
    words: list[Word],
    row_tolerance: float = 4.0,
) -> list[list[Word]]:
    """
    Group words into horizontal rows by their Y position.
    Words within row_tolerance pixels of each other are in the same row.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w.y, w.x))
    rows: list[list[Word]] = []
    current_row: list[Word] = [sorted_words[0]]

    for word in sorted_words[1:]:
        last_y = current_row[-1].y
        if abs(word.y - last_y) <= row_tolerance:
            current_row.append(word)
        else:
            rows.append(current_row)
            current_row = [word]

    if current_row:
        rows.append(current_row)

    # Sort words within each row left to right
    return [sorted(row, key=lambda w: w.x) for row in rows]


def _detect_column_boundaries(
    rows: list[list[Word]],
) -> list[float]:
    """
    Estimate column X boundaries from word positions across rows.
    Uses word start positions to cluster columns.
    """
    all_x = []
    for row in rows:
        for w in row:
            all_x.append(w.x)

    if not all_x:
        return []

    # Sort and cluster X positions that are close together
    sorted_x = sorted(set(all_x))
    clusters: list[float] = [sorted_x[0]]

    for x in sorted_x[1:]:
        if x - clusters[-1] > 20:  # 20pt gap = new column
            clusters.append(x)

    return clusters


def _assign_words_to_columns(
    row_words: list[Word],
    col_boundaries: list[float],
) -> list[str]:
    """
    Place each word into a column bucket based on its X position.
    Returns a list of cell strings, one per column.
    """
    cells = [""] * len(col_boundaries)

    for word in row_words:
        # Find the closest column boundary to the left of this word
        col_idx = 0
        for i, boundary in enumerate(col_boundaries):
            if word.x >= boundary - 5:
                col_idx = i

        if col_idx < len(cells):
            cells[col_idx] = (
                (cells[col_idx] + " " + word.text).strip()
                if cells[col_idx]
                else word.text
            )

    return cells


def _looks_like_table_region(rows: list[list[Word]]) -> bool:
    """
    Heuristic: a region looks like a table if it has multiple rows
    where each row has a consistent number of word groups (columns).
    """
    if len(rows) < 3:
        return False

    word_counts = [len(row) for row in rows]
    avg = sum(word_counts) / len(word_counts)

    # At least 2 words per row on average and consistent column count
    if avg < 2:
        return False

    variance = sum((c - avg) ** 2 for c in word_counts) / len(word_counts)
    return variance < (avg * 2)  # Reasonably consistent column count


def detect_tables_heuristic(ocr_result: OCRResult) -> TableDetectionResult:
    """
    Detect tables using word-position heuristics from OCR output.

    This is a lightweight fallback. Table Transformer (MIT) will
    replace this in v1.1 for production-quality table detection.

    Strategy:
    1. Cluster words into rows by Y position
    2. Find regions where rows have consistent column structure
    3. Treat first row in each region as the header
    4. Extract all subsequent rows as data rows
    """
    tables: list[DetectedTable] = []
    table_index = 0

    for page in ocr_result.pages:
        if not page.words:
            continue

        # Filter out header/footer words (top and bottom 8%)
        ys = [w.y for w in page.words]
        if not ys:
            continue
        min_y, max_y = min(ys), max(ys)
        page_height = max_y - min_y or 1

        body_words = [
            w for w in page.words
            if 0.08 < (w.y - min_y) / page_height < 0.92
        ]

        rows = _cluster_words_into_rows(body_words)

        if not _looks_like_table_region(rows):
            continue

        col_boundaries = _detect_column_boundaries(rows)
        if len(col_boundaries) < 2:
            continue

        # First row is the header
        header_row = _assign_words_to_columns(rows[0], col_boundaries)
        headers = [h for h in header_row if h]

        if len(headers) < 2:
            continue

        # Remaining rows are data
        data_rows: list[list[str]] = []
        cells: list[TableCell] = []

        for row_idx, row_words in enumerate(rows[1:], start=1):
            row_cells = _assign_words_to_columns(row_words, col_boundaries)
            data_rows.append(row_cells[: len(headers)])

            for col_idx, cell_text in enumerate(row_cells[: len(headers)]):
                if col_idx < len(row_words):
                    w = row_words[col_idx]
                    cells.append(TableCell(
                        text=cell_text,
                        row_index=row_idx,
                        col_index=col_idx,
                        page=page.page_num,
                        x=w.x, y=w.y, w=w.w, h=w.h,
                    ))

        if data_rows:
            tables.append(DetectedTable(
                table_index=table_index,
                headers=headers,
                rows=data_rows,
                pages_spanned=[page.page_num],
                cells=cells,
            ))
            table_index += 1

    return TableDetectionResult(tables=tables)


# ── Multi-page table stitching ─────────────────────────────────────────────

def stitch_multi_page_tables(
    detection: TableDetectionResult,
) -> TableDetectionResult:
    """
    Merge tables that continue across page boundaries.

    Step 1: If the last table on page N has the same headers as the
            first table on page N+1, they are the same table.
    Step 2: Remove repeated header rows from continuation pages.
    Step 3: Join all rows into a single DetectedTable.

    This matches the spec: Stage 3 — Table Detection, Structure
    Recognition & Stitching.
    """
    if len(detection.tables) <= 1:
        return detection

    stitched: list[DetectedTable] = []
    i = 0

    while i < len(detection.tables):
        current = detection.tables[i]

        # Look ahead — can this table be merged with the next?
        while i + 1 < len(detection.tables):
            nxt = detection.tables[i + 1]

            # Same headers = continuation table
            if current.headers == nxt.headers:
                # Merge rows
                current = DetectedTable(
                    table_index=current.table_index,
                    headers=current.headers,
                    rows=current.rows + nxt.rows,
                    pages_spanned=current.pages_spanned + nxt.pages_spanned,
                    cells=current.cells + nxt.cells,
                )
                i += 1
            else:
                break

        stitched.append(current)
        i += 1

    return TableDetectionResult(tables=stitched)


# ── Build LLM table text ───────────────────────────────────────────────────

def build_table_text(detection: TableDetectionResult) -> str:
    """
    Convert detected tables to structured text for injection
    into the LLM extraction prompt.

    Format:
      [TABLE 0 — Pages 1-2]
      Headers: Description | Qty | Unit Price | Total
      Row 1: Widget A | 10 | 5.00 | 50.00
      ...
    """
    if not detection.tables:
        return ""

    lines: list[str] = []

    for table in detection.tables:
        pages = ", ".join(str(p) for p in table.pages_spanned)
        lines.append(f"[TABLE {table.table_index} — Page(s) {pages}]")
        lines.append(f"Headers: {' | '.join(table.headers)}")

        for row_idx, row in enumerate(table.rows, start=1):
            lines.append(f"Row {row_idx}: {' | '.join(row)}")

        lines.append("")  # Blank line between tables

    return "\n".join(lines)


# ── Main entry point ───────────────────────────────────────────────────────

def run_table_detection(ocr_result: OCRResult) -> TableDetectionResult:
    """
    Main table detection entry point.

    Current implementation: heuristic word-position analysis.
    v1.1 integration point: replace with Table Transformer.

    Table Transformer usage (v1.1):
        from transformers import TableTransformerForObjectDetection
        model = TableTransformerForObjectDetection.from_pretrained(
            "microsoft/table-transformer-detection"
        )
        # Feed page images → detect bounding boxes → extract cells
    """
    detection = detect_tables_heuristic(ocr_result)
    detection = stitch_multi_page_tables(detection)
    return detection
