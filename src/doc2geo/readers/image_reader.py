"""Scans and photographs. OCR is the only way in."""

from __future__ import annotations

from pathlib import Path

from ..ocr import run_ocr
from ..records import Extraction


def read_image(path: Path, ocr_backend: str = "auto") -> Extraction:
    blocks = run_ocr(path, backend=ocr_backend)
    if not blocks:
        return Extraction(
            source=path,
            pages=1,
            backend="none",
            note="no OCR backend available (install doc2geo[ocr] plus Tesseract)",
        )
    return Extraction(source=path, blocks=blocks, pages=1, backend=blocks[0].backend)
