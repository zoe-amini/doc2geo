"""Readers turn a file into tables and text. One module per family of formats."""

from __future__ import annotations

from pathlib import Path

from ..records import Extraction
from .docx_reader import read_docx
from .image_reader import read_image
from .pdf_reader import read_pdf
from .tabular import CSV_SUFFIXES, EXCEL_SUFFIXES, read_csv, read_excel

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED = CSV_SUFFIXES | EXCEL_SUFFIXES | IMAGE_SUFFIXES | {".pdf", ".docx"}


class UnsupportedInput(ValueError):
    """The file extension has no reader."""


def read(path: Path, *, ocr_backend: str = "auto", max_pages: int = 40) -> Extraction:
    """Dispatch on extension. Raises `UnsupportedInput` for anything with no reader."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()

    if suffix in CSV_SUFFIXES:
        return read_csv(path)
    if suffix in EXCEL_SUFFIXES:
        return read_excel(path)
    if suffix == ".pdf":
        return read_pdf(path, ocr_backend=ocr_backend, max_pages=max_pages)
    if suffix == ".docx":
        return read_docx(path)
    if suffix in IMAGE_SUFFIXES:
        return read_image(path, ocr_backend=ocr_backend)
    if suffix == ".xls":
        raise UnsupportedInput(
            ".xls is the pre-2007 binary format; re-save as .xlsx or convert it with LibreOffice"
        )
    if suffix == ".doc":
        raise UnsupportedInput(".doc is the pre-2007 binary format; re-save as .docx")
    raise UnsupportedInput(f"no reader for {suffix or path.name}; supported: {', '.join(sorted(SUPPORTED))}")


__all__ = [
    "SUPPORTED",
    "Extraction",
    "UnsupportedInput",
    "read",
    "read_csv",
    "read_docx",
    "read_excel",
    "read_image",
    "read_pdf",
]
