"""Optical character recognition for pages that carry no text layer.

Two backends ship here. `tesseract` runs locally and needs the Tesseract binary plus the
`ocr` extra. `http` posts the file to any service that accepts a multipart upload and answers
with blocks of text, which is how you plug in a hosted OCR service without this package
depending on it. Every block records the backend and a confidence so a caller can route
low-confidence output to review instead of trusting it.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path

from .records import TextBlock

RASTER_DPI = 200
DEFAULT_MAX_PAGES = 40


class OcrUnavailable(RuntimeError):
    """Raised when a backend was asked for by name but cannot run on this machine."""


def available_backends() -> list[str]:
    """Backends that could actually run right now, best first."""
    found = []
    if os.environ.get("DOC2GEO_OCR_URL"):
        found.append("http")
    if _tesseract_ready():
        found.append("tesseract")
    return found


def _tesseract_ready() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _rasterise(path: Path, max_pages: int) -> tuple[list[tuple[int, Path]], Path | None]:
    """PDF pages as greyscale PNGs via poppler's pdftoppm. Images pass through untouched."""
    if path.suffix.lower() != ".pdf":
        return [(1, path)], None
    if not shutil.which("pdftoppm"):
        raise OcrUnavailable("scanned PDFs need poppler's pdftoppm on PATH")
    tmp = Path(tempfile.mkdtemp(prefix="doc2geo-ocr-"))
    subprocess.run(
        ["pdftoppm", "-r", str(RASTER_DPI), "-gray", "-l", str(max_pages), "-png", str(path), str(tmp / "p")],
        check=True,
        capture_output=True,
    )
    return [(i, f) for i, f in enumerate(sorted(tmp.glob("p-*.png")), 1)], tmp


def _tesseract(path: Path, max_pages: int) -> list[TextBlock]:
    if not _tesseract_ready():
        raise OcrUnavailable("tesseract backend needs the Tesseract binary and `pip install doc2geo[ocr]`")
    import pytesseract
    from PIL import Image

    pages, tmp = _rasterise(path, max_pages)
    blocks: list[TextBlock] = []
    try:
        for number, image_path in pages:
            data = pytesseract.image_to_data(Image.open(image_path), output_type=pytesseract.Output.DICT)
            lines: dict[tuple[int, int, int], list[str]] = {}
            confidences: list[float] = []
            for index, word in enumerate(data["text"]):
                if not word.strip():
                    continue
                key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
                lines.setdefault(key, []).append(word)
                value = float(data["conf"][index])
                confidences.append(value / 100 if value >= 0 else 0.0)
            if lines:
                text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
                blocks.append(
                    TextBlock(
                        text=text,
                        page=number,
                        confidence=round(sum(confidences) / len(confidences), 3),
                        backend="tesseract",
                    )
                )
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return blocks


def _http(path: Path) -> list[TextBlock]:
    """POST the file to DOC2GEO_OCR_URL as multipart/form-data under the field `file`.

    The service is expected to answer with JSON shaped
    `{"blocks": [{"page": 1, "kind": "text", "text": "...", "confidence": 0.97}]}`.
    DOC2GEO_OCR_TOKEN, when set, is sent as a bearer token.
    """
    url = os.environ.get("DOC2GEO_OCR_URL")
    if not url:
        raise OcrUnavailable("http backend needs DOC2GEO_OCR_URL")
    boundary = uuid.uuid4().hex
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    token = os.environ.get("DOC2GEO_OCR_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    timeout = float(os.environ.get("DOC2GEO_OCR_TIMEOUT", "120"))
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  caller-supplied URL
        payload = json.loads(response.read().decode("utf-8"))
    return [
        TextBlock(
            text=block.get("text", ""),
            page=int(block.get("page", 1)),
            kind=block.get("kind", "text"),
            confidence=float(block.get("confidence", 0.0)),
            backend="http",
            bbox=block.get("bbox"),
        )
        for block in payload.get("blocks", [])
        if block.get("text")
    ]


def run_ocr(path: Path, backend: str = "auto", max_pages: int = DEFAULT_MAX_PAGES) -> list[TextBlock]:
    """OCR a PDF or image. `auto` tries the hosted service first, then Tesseract.

    Returns an empty list when nothing is configured, so callers can degrade rather than crash.
    """
    if backend == "http":
        return _http(path)
    if backend == "tesseract":
        return _tesseract(path, max_pages)
    if backend != "auto":
        raise ValueError(f"unknown OCR backend: {backend}")

    for name in available_backends():
        try:
            return _http(path) if name == "http" else _tesseract(path, max_pages)
        except (OcrUnavailable, OSError, subprocess.CalledProcessError, ValueError):
            continue
    return []
