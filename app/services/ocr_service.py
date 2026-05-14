"""
OCR Service
-----------
Extracts text and positional data from documents.

Current: PyMuPDF for native text PDFs.
Future:  PaddleOCR for scanned images (v1.1).

The extracted text is used to:
  1. Build the LLM prompt
  2. Generate spatial anchors (bounding boxes) for the review UI

Spatial anchors are generated fresh from each document.
They are NEVER stored in schemas or copied from sample documents.
"""
from pathlib import Path
from dataclasses import dataclass, field


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class Word:
    """A single word extracted from the document with its position."""
    text: str
    page: int
    x: float
    y: float
    w: float
    h: float
    confidence: float = 1.0  # Always 1.0 for native PDFs


@dataclass
class PageData:
    """All extracted data for a single page."""
    page_num: int
    text: str           # Full page text
    words: list[Word]   # Individual words with positions


@dataclass
class OCRResult:
    """Complete OCR output for an entire document."""
    file_type: str      # native_text | scanned_image | mixed
    page_count: int
    full_text: str      # All pages concatenated
    pages: list[PageData]


# ── File type detection ────────────────────────────────────────────────────

def detect_file_type(file_path: Path) -> str:
    """
    Detect whether a PDF contains native text or is scanned.

    Native text PDFs: text is embedded in the PDF structure.
    Scanned PDFs: pages are images with no embedded text.
    Mixed: some pages native, some scanned.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(str(file_path))
    total_pages = len(doc)
    pages_with_text = 0

    for page in doc:
        text = page.get_text().strip()
        if len(text) > 20:  # More than 20 chars = has real text
            pages_with_text += 1

    doc.close()

    if total_pages == 0:
        return "native_text"

    ratio = pages_with_text / total_pages

    if ratio >= 0.8:
        return "native_text"
    elif ratio >= 0.3:
        return "mixed"
    else:
        return "scanned_image"


# ── Native PDF extraction ──────────────────────────────────────────────────

def extract_native_pdf(file_path: Path) -> OCRResult:
    """
    Extract text and word positions from a native text PDF.
    Uses PyMuPDF — no OCR needed, very fast and accurate.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(str(file_path))
    pages: list[PageData] = []

    for page_num, page in enumerate(doc, start=1):
        # Get individual words with positions
        # Returns: (x0, y0, x1, y1, word, block_no, line_no, word_no)
        raw_words = page.get_text("words")

        words: list[Word] = []
        for w in raw_words:
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            words.append(Word(
                text=text,
                page=page_num,
                x=round(x0, 2),
                y=round(y0, 2),
                w=round(x1 - x0, 2),
                h=round(y1 - y0, 2),
                confidence=1.0,
            ))

        # Get full page text — preserves layout better than joining words
        page_text = page.get_text().strip()

        pages.append(PageData(
            page_num=page_num,
            text=page_text,
            words=words,
        ))

    doc.close()

    full_text = "\n\n".join(
        f"[Page {p.page_num}]\n{p.text}"
        for p in pages
    )

    return OCRResult(
        file_type="native_text",
        page_count=len(pages),
        full_text=full_text,
        pages=pages,
    )


# ── Build LLM prompt text ──────────────────────────────────────────────────

def build_llm_document_text(ocr_result: OCRResult) -> str:
    """
    Build clean structured text to send to the LLM.

    Each page is labelled. Page headers and footers are stripped
    (top 8% and bottom 8% of each page) to avoid noise.
    """
    lines: list[str] = []

    for page in ocr_result.pages:
        lines.append(f"[Page {page.page_num}]")

        if not page.words:
            lines.append(page.text)
            continue

        # Strip header and footer words by vertical position
        ys = [w.y for w in page.words]
        if not ys:
            lines.append(page.text)
            continue

        min_y = min(ys)
        max_y = max(ys)
        page_height = max_y - min_y or 1

        body_words = [
            w for w in page.words
            if 0.08 < (w.y - min_y) / page_height < 0.92
        ]

        if body_words:
            # Rebuild text from body words only
            body_text = " ".join(w.text for w in body_words)
            lines.append(body_text)
        else:
            # Fallback — use full page text
            lines.append(page.text)

        lines.append("")  # Blank line between pages

    return "\n".join(lines)


# ── Spatial anchor builder ─────────────────────────────────────────────────

def find_spatial_anchor(
    value: str,
    ocr_result: OCRResult
) -> dict | None:
    """
    Find where a value appears in the document and return
    its bounding box as a spatial anchor.

    Spatial anchors are generated fresh from each document's
    own OCR output — never from the schema or sample document.
    """
    if not value:
        return None

    value_lower = value.lower().strip()

    for page in ocr_result.pages:
        # Try to find the value in this page's words
        page_words = page.words
        page_text_lower = page.text.lower()

        if value_lower not in page_text_lower:
            continue

        # Find the word(s) that match
        for i, word in enumerate(page_words):
            if value_lower in word.text.lower():
                return {
                    "page": page.page_num,
                    "x": word.x,
                    "y": word.y,
                    "w": word.w,
                    "h": word.h,
                }

            # Check multi-word match (e.g. "INV-2026-00421")
            # by looking at consecutive words
            combined = " ".join(
                w.text for w in page_words[i:i+3]
            ).lower()
            if value_lower in combined:
                # Use bounding box spanning the matched words
                matched = page_words[i:i+3]
                return {
                    "page": page.page_num,
                    "x": matched[0].x,
                    "y": matched[0].y,
                    "w": matched[-1].x + matched[-1].w - matched[0].x,
                    "h": max(w.h for w in matched),
                }

    return None


# ── Main entry point ───────────────────────────────────────────────────────

def run_ocr(file_path: Path) -> OCRResult:
    """
    Main OCR entry point.
    Detects file type and routes to the correct extractor.

    Currently supports native text PDFs.
    PaddleOCR for scanned images will be added in v1.1.
    """
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        file_type = detect_file_type(file_path)

        if file_type == "native_text":
            return extract_native_pdf(file_path)

        elif file_type == "mixed":
            # Extract native pages — scanned pages get what text they have
            # PaddleOCR will improve this in v1.1
            result = extract_native_pdf(file_path)
            result.file_type = "mixed"
            return result

        else:
            # Scanned PDF — attempt native extraction as fallback
            # PaddleOCR integration point for v1.1
            result = extract_native_pdf(file_path)
            result.file_type = "scanned_image"
            return result

    elif suffix in (".tiff", ".tif", ".jpg", ".jpeg", ".png"):
        # Image files — PaddleOCR integration point for v1.1
        raise NotImplementedError(
            f"Image files ({suffix}) require PaddleOCR "
            f"which will be added in v1.1. "
            f"Please use a PDF for now."
        )

    else:
        raise ValueError(
            f"Unsupported file type: {suffix}. "
            f"Supported: .pdf, .tiff, .jpg, .jpeg, .png"
        )