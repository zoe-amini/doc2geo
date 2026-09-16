"""Finding the map pages inside a report.

Reports bury a handful of maps in a hundred pages of prose, tables and photographs. Pulling
those pages out by hand is the boring half of every data-collation job, so this module scores
each page on signals that maps have and body text does not, and hands back the ones that pass.

No single signal is trusted. A colour choropleth and a monochrome line map look nothing alike;
a landscape page might be a wide table; a page full of vector art might be an org chart. Each
signal contributes a weighted vote and the reasons travel with the score so a caller can see
why a page was picked and argue with it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

# Tick labels around a map frame: 25°00'S, 120°E, 21° 30' 00" N.
GRATICULE = re.compile(r"\d{1,3}\s*[°º]\s*(?:\d{1,2}\s*['’])?\s*(?:\d{1,2}\s*[\"”])?\s*[NSEW]?")

# Words that appear on maps and rarely in running prose.
CARTO_WORDS = (
    "scale 1:",
    "legend",
    "contour",
    "projection",
    "datum",
    "utm",
    "grid",
    "kilometres",
    "kilometers",
    "map sheet",
    "index map",
    "quadrangle",
    "geological map",
    "geologic map",
    "soil units",
    "mapping units",
    "borehole",
    "lineament",
)
CAPTION = re.compile(r"(?i)\b(?:fig(?:ure)?|plate|map|sheet)\s*\.?\s*\d+[.\-—:]?\s*[^\n]{0,80}")

DEFAULT_THRESHOLD = 0.5
RENDER_DPI = 40  # Enough to judge colour and ink; cheap enough to run on every page.


@dataclass
class PageSignals:
    """Everything measured about one page, before any judgement is made."""

    page: int
    width: float
    height: float
    chars: int
    graticule_labels: int
    carto_words: int
    images: int
    largest_image_bytes: int
    landscape: bool
    oversized: bool
    sparse_text: bool
    chroma: float | None = None
    colours: int | None = None
    ink: float | None = None
    caption: str = ""


@dataclass
class MapPage:
    """A page the detector believes is a map."""

    page: int
    score: float
    reasons: list[str] = field(default_factory=list)
    signals: PageSignals | None = None
    caption: str = ""
    image_path: Path | None = None

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "caption": self.caption,
            "image": str(self.image_path) if self.image_path else None,
        }


def _page_signals(reader, index: int, modal_area: float, median_chars: float) -> PageSignals:
    page = reader.pages[index]
    box = page.mediabox
    width, height = float(box.width), float(box.height)
    try:
        text = page.extract_text() or ""
    except Exception:  # noqa: BLE001  a damaged page should not sink the whole document
        text = ""
    low = text.lower()

    images, largest = 0, 0
    try:
        for image in page.images:
            images += 1
            largest = max(largest, len(image.data))
    except Exception:  # noqa: BLE001  pypdf raises on exotic colour spaces
        pass

    caption_match = CAPTION.search(text)
    return PageSignals(
        page=index + 1,
        width=width,
        height=height,
        chars=len(text),
        graticule_labels=len(GRATICULE.findall(text)),
        carto_words=sum(1 for w in CARTO_WORDS if w in low),
        images=images,
        largest_image_bytes=largest,
        landscape=width > height * 1.05,
        oversized=(width * height) > modal_area * 1.4,
        sparse_text=len(text) < max(200.0, median_chars * 0.35),
        caption=caption_match.group(0).strip()[:120] if caption_match else "",
    )


def _render_stats(
    pdf: Path, first: int, last: int, dpi: int = RENDER_DPI
) -> dict[int, tuple[float, int, float]]:
    """Colour and ink coverage per page, via poppler. Empty when poppler or Pillow is missing."""
    if not shutil.which("pdftoppm"):
        return {}
    try:
        from PIL import Image
    except ImportError:
        return {}

    stats: dict[int, tuple[float, int, float]] = {}
    with tempfile.TemporaryDirectory(prefix="doc2geo-render-") as tmp:
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-png", "-f", str(first), "-l", str(last), str(pdf), f"{tmp}/p"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            return {}
        for rendered in sorted(Path(tmp).glob("p-*.png")):
            number = int(re.sub(r"\D", "", rendered.stem.split("-")[-1]) or 0)
            image = Image.open(rendered).convert("RGB").resize((160, 160))
            # tobytes() rather than getdata(): same numbers, no version-dependent accessor.
            raw = image.tobytes()
            pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
            total = len(pixels)
            ink = sum(1 for r, g, b in pixels if not (r > 240 and g > 240 and b > 240))
            chroma = sum(1 for r, g, b in pixels if max(r, g, b) - min(r, g, b) > 28)
            buckets = {(r // 32, g // 32, b // 32) for r, g, b in pixels}
            stats[number] = (chroma / total, len(buckets), ink / total)
    return stats


def score_page(signals: PageSignals) -> tuple[float, list[str]]:
    """Weighted vote over the signals. Returns the score and the reasons behind it."""
    score = 0.0
    reasons: list[str] = []

    if signals.graticule_labels >= 3:
        score += 0.45
        reasons.append(f"{signals.graticule_labels} graticule tick labels")
    elif signals.graticule_labels > 0:
        score += 0.15
        reasons.append(f"{signals.graticule_labels} coordinate label(s)")

    if signals.carto_words:
        score += min(0.30, 0.12 * signals.carto_words)
        reasons.append(f"{signals.carto_words} cartographic term(s)")

    if signals.chroma is not None:
        if signals.chroma > 0.25 or (signals.colours or 0) > 80:
            score += 0.45
            reasons.append(
                f"strongly polychrome page (chroma {signals.chroma:.2f}, {signals.colours} colours)"
            )
        elif signals.chroma > 0.08 or (signals.colours or 0) > 24:
            score += 0.35
            reasons.append(f"polychrome page (chroma {signals.chroma:.2f}, {signals.colours} colours)")
        elif (signals.ink or 0) > 0.05 and signals.chars < 400:
            # A monochrome line map: plenty of ink, almost no text layer.
            score += 0.20
            reasons.append(f"dense monochrome graphics with little text (ink {signals.ink:.2f})")

    if signals.oversized:
        score += 0.20
        reasons.append("page much larger than the document's usual size")
    if signals.landscape:
        score += 0.12
        reasons.append("landscape orientation")
    if signals.sparse_text:
        score += 0.12
        reasons.append("little or no body text")

    if signals.images > 20:
        score += 0.12
        reasons.append(f"{signals.images} embedded images (composite artwork)")
    elif signals.largest_image_bytes > 200_000:
        score += 0.10
        reasons.append("one large embedded image")

    if signals.caption and re.search(r"(?i)\bmap\b", signals.caption):
        score += 0.20
        reasons.append(f"caption reads as a map: {signals.caption[:60]!r}")

    return min(score, 1.0), reasons


def find_map_pages(
    pdf: Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    render: bool = True,
    max_pages: int | None = None,
) -> list[MapPage]:
    """Score every page and return the ones that look like maps, in page order.

    `render` adds the colour pass, which is what separates a colour map from a text page in a
    document that is entirely scanned images. It needs poppler's pdftoppm and Pillow; without
    them the detector falls back to the text-layer signals alone.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    count = len(reader.pages) if max_pages is None else min(len(reader.pages), max_pages)
    if not count:
        return []

    areas = [float(p.mediabox.width) * float(p.mediabox.height) for p in reader.pages[:count]]
    modal_area = median(areas)
    char_counts = []
    for page in reader.pages[:count]:
        try:
            char_counts.append(len(page.extract_text() or ""))
        except Exception:  # noqa: BLE001
            char_counts.append(0)
    median_chars = median(char_counts) if char_counts else 0.0

    render_stats = _render_stats(Path(pdf), 1, count) if render else {}

    found: list[MapPage] = []
    for index in range(count):
        signals = _page_signals(reader, index, modal_area, median_chars)
        if signals.page in render_stats:
            signals.chroma, signals.colours, signals.ink = render_stats[signals.page]
        score, reasons = score_page(signals)
        if score >= threshold:
            found.append(
                MapPage(
                    page=signals.page, score=score, reasons=reasons, signals=signals, caption=signals.caption
                )
            )
    return found


def extract_map_pages(
    pdf: Path,
    out_dir: Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    dpi: int = 300,
    render: bool = True,
    max_pages: int | None = None,
) -> list[MapPage]:
    """Find the map pages and write each one out as a PNG at `dpi`."""
    pages = find_map_pages(pdf, threshold=threshold, render=render, max_pages=max_pages)
    if not pages:
        return []
    if not shutil.which("pdftoppm"):
        raise RuntimeError("writing page images needs poppler's pdftoppm on PATH")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(pdf).stem
    for found in pages:
        prefix = out_dir / f"{stem}_p{found.page:04d}"
        subprocess.run(
            [
                "pdftoppm",
                "-r",
                str(dpi),
                "-png",
                "-singlefile",
                "-f",
                str(found.page),
                "-l",
                str(found.page),
                str(pdf),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        found.image_path = prefix.with_suffix(".png")
    return pages
