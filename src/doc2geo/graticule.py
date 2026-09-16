"""Georeferencing a map page from the numbers printed around its edge.

A map sheet carries its own control points: the tick labels on the frame. Read those, pair
each with the place it sits on the page, and you have enough to fit the affine transform that
turns page coordinates into world coordinates — a world file, which QGIS and GDAL understand.

The important part is knowing when not to. A projected map is not affine in page space: on the
USGS Circum-Pacific sheet the ten degrees from 10°S to 10°N occupy twice the paper of the ten
from 10°N to 20°N. Fitting an affine to that produces a plausible-looking world file that is
quietly wrong. So the fit is always scored, the residuals are always reported, and a poor fit
returns the control points for a human to place in QGIS instead of a transform nobody checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .crs import parse_dms

# A tick label, captured so the hemisphere letter survives: 25°00'S, 120°E, 21° 30' 00" N
TICK = re.compile(
    r"""(?x)
    \b(\d{1,3})\s*[°º]\s*
    (?:(\d{1,2})\s*['’])?\s*
    (?:(\d{1,2})\s*["”])?\s*
    ([NSEW])\b
    """
)
# A bare degree tick with no hemisphere letter, as used on the prime meridian or equator.
BARE_TICK = re.compile(r"\b(\d{1,3})\s*[°º](?![\d°º])")

# Beyond this, in degrees, the affine fit is not describing the same surface as the labels.
GOOD_FIT_DEGREES = 0.05


@dataclass
class Tick:
    """One graticule label and where it sits on the page, in PDF points."""

    value: float
    axis: str  # "lon" or "lat"
    x: float
    y: float
    text: str


@dataclass
class Georeference:
    """The outcome of trying to georeference a page."""

    ticks: list[Tick] = field(default_factory=list)
    transform: tuple[float, float, float, float, float, float] | None = None
    residual_deg: float | None = None
    fitted: bool = False
    note: str = ""

    @property
    def control_points(self) -> list[dict]:
        """GCPs in the shape QGIS's georeferencer imports: pixel x/y against world x/y."""
        return [
            {"page_x": t.x, "page_y": t.y, "axis": t.axis, "value": t.value, "label": t.text}
            for t in self.ticks
        ]


def ticks_from_tokens(tokens: list[tuple[float, float, str]]) -> list[Tick]:
    """Turn positioned text tokens into graticule ticks.

    `tokens` is (x, y, text) in PDF points. A token holding several labels at once — readers
    often merge a whole row of ticks into one string — is skipped rather than guessed at, since
    its individual positions are gone and a wrong position is worse than a missing one.
    """
    ticks: list[Tick] = []
    for x, y, text in tokens:
        matches = TICK.findall(text)
        if len(matches) != 1:
            continue  # zero, or a merged run whose positions cannot be recovered
        degrees, minutes, seconds, hemisphere = matches[0]
        value = parse_dms(f"{degrees}°{minutes or 0}'{seconds or 0}\"{hemisphere}")
        if value is None:
            continue
        axis = "lat" if hemisphere.upper() in ("N", "S") else "lon"
        ticks.append(Tick(value=value, axis=axis, x=x, y=y, text=text.strip()))
    return ticks


def _fit_axis(samples: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Least-squares fit of value = scale * position + offset. Returns (scale, offset, residual)."""
    if len(samples) < 2:
        return None
    n = len(samples)
    sx = sum(p for p, _ in samples)
    sy = sum(v for _, v in samples)
    sxx = sum(p * p for p, _ in samples)
    sxy = sum(p * v for p, v in samples)
    denominator = n * sxx - sx * sx
    if abs(denominator) < 1e-9:
        return None
    scale = (n * sxy - sx * sy) / denominator
    offset = (sy - scale * sx) / n
    residual = max(abs(v - (scale * p + offset)) for p, v in samples)
    return scale, offset, residual


def georeference_page(tokens: list[tuple[float, float, str]]) -> Georeference:
    """Fit a north-up affine from graticule ticks, and say honestly how well it fits."""
    ticks = ticks_from_tokens(tokens)
    lons = [(t.x, t.value) for t in ticks if t.axis == "lon"]
    lats = [(t.y, t.value) for t in ticks if t.axis == "lat"]
    result = Georeference(ticks=ticks)

    if len(lons) < 2 or len(lats) < 2:
        result.note = (
            f"need at least two ticks on each axis; found {len(lons)} longitude and {len(lats)} latitude"
        )
        return result

    x_fit, y_fit = _fit_axis(lons), _fit_axis(lats)
    if not x_fit or not y_fit:
        result.note = "ticks are collinear on one axis; cannot fit"
        return result

    x_scale, x_offset, x_residual = x_fit
    y_scale, y_offset, y_residual = y_fit
    result.residual_deg = round(max(x_residual, y_residual), 6)
    # World file order: pixel size x, rotation y, rotation x, pixel size y, origin x, origin y.
    result.transform = (x_scale, 0.0, 0.0, y_scale, x_offset, y_offset)

    if result.residual_deg > GOOD_FIT_DEGREES:
        result.note = (
            f"affine fit is off by up to {result.residual_deg:.3f}° at the control points: the sheet is "
            "probably projected, not plate carrée. Control points are provided; georeference it in QGIS."
        )
        return result

    result.fitted = True
    result.note = f"affine fit within {result.residual_deg:.4f}° at {len(ticks)} control points"
    return result


def write_world_file(
    geo: Georeference, image: Path, page_width: float, page_height: float, pixels: tuple[int, int]
) -> Path | None:
    """Write the .pgw/.jgw beside a rendered page image, if and only if the fit was good.

    The affine is fitted in PDF points, so it is rescaled here to the pixel grid of the render,
    and the y term is negated because image rows run down while latitude runs up.
    """
    if not geo.fitted or not geo.transform:
        return None
    x_scale, _, _, y_scale, x_offset, y_offset = geo.transform
    width_px, height_px = pixels
    points_per_px_x = page_width / width_px
    points_per_px_y = page_height / height_px

    a = x_scale * points_per_px_x
    e = -abs(y_scale * points_per_px_y)
    # Centre of the top-left pixel, in world coordinates.
    c = x_offset + x_scale * (points_per_px_x / 2)
    f = y_offset + y_scale * (page_height - points_per_px_y / 2)

    suffix = {".png": ".pgw", ".jpg": ".jgw", ".jpeg": ".jgw", ".tif": ".tfw", ".tiff": ".tfw"}
    path = image.with_suffix(suffix.get(image.suffix.lower(), ".wld"))
    path.write_text("\n".join(f"{v:.10f}" for v in (a, 0.0, 0.0, e, c, f)) + "\n", encoding="utf-8")
    image.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
        encoding="utf-8",
    )
    return path


def tokens_from_pdf_page(pdf: Path, page_number: int) -> list[tuple[float, float, str]]:
    """Positioned text tokens for one page, via pypdf's text visitor."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    page = reader.pages[page_number - 1]
    tokens: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, font, size):  # noqa: ANN001  pypdf's callback signature
        stripped = (text or "").strip()
        if stripped:
            tokens.append((float(tm[4]), float(tm[5]), stripped))

    page.extract_text(visitor_text=visit)
    return tokens
