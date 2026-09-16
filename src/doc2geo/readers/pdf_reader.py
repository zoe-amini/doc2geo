"""PDFs, born-digital and scanned.

The text layer is tried first: it is exact, free, and covers every report produced this
century. When a page yields nothing, that page was an image, and OCR takes over — but only
if a backend is available, so the library stays usable without Tesseract installed.
"""

from __future__ import annotations

from pathlib import Path

from ..ocr import run_ocr
from ..records import Extraction, TextBlock

# Below this many characters a "text layer" is really just a stray label on a scan.
MIN_CHARS_PER_PAGE = 40


def read_pdf(path: Path, ocr_backend: str = "auto", max_pages: int = 40) -> Extraction:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    blocks: list[TextBlock] = []
    empty_pages = 0
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if len(text) >= MIN_CHARS_PER_PAGE:
            blocks.append(TextBlock(text=text, page=number, confidence=0.95, backend="pypdf"))
        else:
            empty_pages += 1

    if not blocks:
        ocr_blocks = run_ocr(path, backend=ocr_backend, max_pages=max_pages)
        if ocr_blocks:
            backend = ocr_blocks[0].backend
            return Extraction(
                source=path,
                blocks=ocr_blocks,
                pages=pages,
                backend=backend,
                note=f"no text layer; OCR via {backend} at {len(ocr_blocks)} page(s)",
            )
        return Extraction(
            source=path,
            pages=pages,
            backend="none",
            note="no text layer and no OCR backend available (install doc2geo[ocr] plus Tesseract)",
        )

    note = f"{empty_pages} of {pages} pages had no text layer" if empty_pages else ""
    return Extraction(source=path, blocks=blocks, pages=pages, backend="pypdf", note=note)
