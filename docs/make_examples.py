"""Regenerate the figures in the README from the committed samples.

    uv run python docs/make_examples.py

Everything here is derived from files in samples/, so the pictures in the README cannot drift
away from what the library actually does: rerun this after changing the detector and the
figures change with it. Pillow only — no plotting stack, no basemap, no network.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from doc2geo.detect import extract_records  # noqa: E402
from doc2geo.mappages import find_map_pages  # noqa: E402
from doc2geo.readers import read  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
OUT = Path(__file__).resolve().parent / "examples"

INK = (28, 30, 34)
MUTED = (120, 126, 134)
PAPER = (250, 250, 248)
RULE = (208, 212, 218)
ACCENT = (198, 74, 48)
GOOD = (34, 120, 84)
FILL = (198, 74, 48, 70)

FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
BOLDS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for path in BOLDS if bold else FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render(pdf: Path, page: int, width: int) -> Image.Image:
    """One PDF page as an image, scaled to `width`."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                "pdftoppm",
                "-r",
                "80",
                "-png",
                "-singlefile",
                "-f",
                str(page),
                "-l",
                str(page),
                str(pdf),
                f"{tmp}/p",
            ],
            check=True,
            capture_output=True,
        )
        image = Image.open(f"{tmp}/p.png").convert("RGB")
    height = round(image.height * width / image.width)
    return image.resize((width, height), Image.LANCZOS)


def framed(image: Image.Image) -> Image.Image:
    out = image.copy()
    ImageDraw.Draw(out).rectangle([0, 0, out.width - 1, out.height - 1], outline=RULE)
    return out


def caption(draw: ImageDraw.ImageDraw, xy: tuple[int, int], title: str, lines: list[str]) -> int:
    x, y = xy
    draw.text((x, y), title, font=font(15, bold=True), fill=INK)
    y += 22
    for line in lines:
        draw.text((x, y), line, font=font(12), fill=MUTED)
        y += 16
    return y


def plot_geometry(records, size: tuple[int, int], pad: float = 0.35) -> Image.Image:
    """Extents on a labelled graticule. No basemap: this shows what was extracted, nothing more."""
    width, height = size
    canvas = Image.new("RGB", size, PAPER)
    draw = ImageDraw.Draw(canvas, "RGBA")

    points = [p for record in records for p in record.vertices()]
    if not points:
        return canvas
    west, east = min(p[0] for p in points), max(p[0] for p in points)
    south, north = min(p[1] for p in points), max(p[1] for p in points)
    span = max(east - west, north - south, 0.01)
    west, east = west - span * pad, east + span * pad
    south, north = south - span * pad, north + span * pad
    margin = 54

    def to_px(lon: float, lat: float) -> tuple[float, float]:
        x = margin + (lon - west) / (east - west) * (width - margin - 20)
        y = 20 + (north - lat) / (north - south) * (height - margin - 20)
        return x, y

    step = 0.5 if (east - west) < 4 else 5.0
    value = round(west / step) * step
    if value < west:
        value += step
    while value <= east:
        x, _ = to_px(value, north)
        draw.line([(x, 20), (x, height - margin)], fill=RULE)
        draw.text(
            (x - 14, height - margin + 6),
            f"{abs(value):g}°{'E' if value >= 0 else 'W'}",
            font=font(11),
            fill=MUTED,
        )
        value += step
    value = round(south / step) * step
    if value < south:
        value += step
    while value <= north:
        _, y = to_px(west, value)
        draw.line([(margin, y), (width - 20, y)], fill=RULE)
        # Skip a label that would sit on top of the longitude axis at the bottom edge.
        if y < height - margin - 12:
            draw.text((6, y - 7), f"{abs(value):g}°{'N' if value >= 0 else 'S'}", font=font(11), fill=MUTED)
        value += step

    for record in records:
        if record.geom_type == "Polygon":
            for ring in record.geometry["coordinates"]:
                draw.polygon([to_px(*p) for p in ring], fill=FILL, outline=ACCENT)
        elif record.geom_type == "LineString":
            draw.line([to_px(*p) for p in record.geometry["coordinates"]], fill=ACCENT, width=3)
        else:
            x, y = to_px(record.lon, record.lat)
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=ACCENT, outline=PAPER)
    draw.rectangle([margin, 20, width - 20, height - margin], outline=RULE)
    return canvas


def side_by_side(
    left: Image.Image, right: Image.Image, headings: tuple[str, str], notes: tuple[list[str], list[str]]
) -> Image.Image:
    gap, top, bottom = 28, 64, 16
    height = max(left.height, right.height) + top + bottom
    width = left.width + right.width + gap + 2
    canvas = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    caption(draw, (0, 8), headings[0], notes[0])
    caption(draw, (left.width + gap, 8), headings[1], notes[1])
    canvas.paste(left, (0, top))
    canvas.paste(right, (left.width + gap, top))
    arrow_y = top + max(left.height, right.height) // 2
    draw.line([(left.width + 6, arrow_y), (left.width + gap - 6, arrow_y)], fill=ACCENT, width=2)
    draw.polygon(
        [
            (left.width + gap - 6, arrow_y),
            (left.width + gap - 14, arrow_y - 5),
            (left.width + gap - 14, arrow_y + 5),
        ],
        fill=ACCENT,
    )
    return canvas


def badge(image: Image.Image, text: str, colour: tuple[int, int, int]) -> Image.Image:
    out = image.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    box = draw.textbbox((0, 0), text, font=font(13, bold=True))
    width, height = box[2] - box[0] + 18, box[3] - box[1] + 12
    draw.rectangle([8, 8, 8 + width, 8 + height], fill=(*colour, 235))
    draw.text((17, 12), text, font=font(13, bold=True), fill=(255, 255, 255))
    draw.rectangle([0, 0, out.width - 1, out.height - 1], outline=colour, width=3)
    return out


def scans_to_polygons() -> None:
    """A scanned catalogue page with no text layer, and the extents OCR recovered from it."""
    pdf = SAMPLES / "jica_10891885_04.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdfseparate", "-f", "25", "-l", "25", str(pdf), f"{tmp}/p.pdf"], check=True, capture_output=True
        )
        page = Path(tmp) / "p.pdf"
        extraction = read(page)
        records = extract_records(extraction, ocr_repair=True)
        left = framed(render(page, 1, 460))

    right = plot_geometry(records, (460, left.height))

    def readable(record) -> str:
        points = record.vertices()
        west, east = min(p[0] for p in points), max(p[0] for p in points)
        south, north = min(p[1] for p in points), max(p[1] for p in points)
        return f"{abs(north):.2f}°S to {abs(south):.2f}°S, {east:.3f}°E to {west:.3f}°E".replace(
            "to -", "to "
        )

    extents = [readable(r) for r in records]
    figure = side_by_side(
        left,
        framed(right),
        ("Scanned page, no text layer", f"{len(records)} extents, as polygons"),
        (
            [
                "jica_10891885_04.pdf p25 — OCR at 0.75 confidence",
                "Coordinates are packed DMS: Latitude: S060000 ; S030000",
            ],
            ["doc2geo convert p25.pdf --ocr-repair -o out.geojson", *extents[:2]],
        ),
    )
    figure.save(OUT / "scan-to-polygons.png")
    print("scan-to-polygons.png", figure.size)


def map_page_detection() -> None:
    """The map page found among a report's prose."""
    pdf = SAMPLES / "jica_12301594_01.pdf"
    found = find_map_pages(pdf, max_pages=6)
    map_page = next(p for p in found if p.page == 3)
    left = framed(render(pdf, 4, 300))
    right = framed(render(pdf, 3, 300))
    figure = side_by_side(
        left,
        right,
        ("Page 4 — rejected", f"Page 3 — map, score {map_page.score:.2f}"),
        (["4263 characters of body text", "score 0.00, no signal fires"], [r for r in map_page.reasons[:3]]),
    )
    figure.save(OUT / "map-page-detection.png")
    print("map-page-detection.png", figure.size)


def licence_corners() -> None:
    """Rows of corner coordinates, and the polygons they become."""
    from doc2geo.detect import records_from_table_shapes
    from doc2geo.records import Table

    rows = [
        ["PL-142", "1", "25.10", "-21.05"],
        ["PL-142", "2", "25.60", "-21.05"],
        ["PL-142", "3", "25.60", "-21.45"],
        ["PL-142", "4", "25.10", "-21.45"],
        ["PL-143", "1", "25.70", "-21.10"],
        ["PL-143", "2", "26.15", "-21.10"],
        ["PL-143", "3", "26.15", "-21.55"],
        ["PL-143", "4", "25.70", "-21.55"],
    ]
    table = Table(header=["licence", "corner", "lon", "lat"], rows=rows, name="blocks")
    records = records_from_table_shapes(table)

    left = Image.new("RGB", (420, 300), PAPER)
    draw = ImageDraw.Draw(left)
    y = 16
    draw.text((16, y), "  licence   corner      lon       lat", font=font(13, bold=True), fill=INK)
    y += 24
    draw.line([(16, y), (404, y)], fill=RULE)
    y += 8
    for row in rows:
        draw.text((16, y), f"  {row[0]:<10}{row[1]:^8}{row[2]:>9}{row[3]:>10}", font=font(13), fill=INK)
        y += 22
    draw.rectangle([0, 0, 419, 299], outline=RULE)

    right = framed(plot_geometry(records, (420, 300)))
    figure = side_by_side(
        left,
        right,
        ("Eight rows of corner coordinates", f"{len(records)} polygons"),
        (
            ["grouped by `licence`, ordered by `corner`"],
            ["doc2geo convert blocks.csv -o blocks.geojson", "rings closed automatically"],
        ),
    )
    figure.save(OUT / "licence-corners.png")
    print("licence-corners.png", figure.size)


def detection_gif() -> None:
    """Each page of a report, with the detector's verdict on it."""
    pdf = SAMPLES / "jica_12301594_01.pdf"
    pages = list(range(1, 11))
    found = {p.page: p for p in find_map_pages(pdf, max_pages=max(pages))}
    frames = []
    for number in pages:
        image = render(pdf, number, 340)
        canvas = Image.new("RGB", (360, 520), PAPER)
        canvas.paste(
            image.resize((340, min(460, image.height * 340 // image.width)), Image.LANCZOS), (10, 44)
        )
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 12), f"page {number} of 161", font=font(14, bold=True), fill=INK)
        hit = found.get(number)
        label = f"MAP  {hit.score:.2f}" if hit else "not a map"
        colour = ACCENT if hit else MUTED
        box = draw.textbbox((0, 0), label, font=font(13, bold=True))
        draw.rectangle([230, 8, 230 + box[2] + 18, 8 + box[3] + 12], fill=colour)
        draw.text((239, 12), label, font=font(13, bold=True), fill=(255, 255, 255))
        if hit:
            draw.rectangle([8, 42, 352, 44 + 462], outline=ACCENT, width=3)
            draw.text((10, 500), hit.reasons[0][:58], font=font(11), fill=ACCENT)
        frames.append(canvas)
    durations = [1600 if number in found else 650 for number in pages]
    frames[0].save(
        OUT / "map-detection.gif",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print("map-detection.gif", frames[0].size, len(frames), "frames")


def pipeline_gif() -> None:
    """Scan, OCR, parse, polygon — the four states of one page."""
    pdf = SAMPLES / "jica_10891885_04.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdfseparate", "-f", "25", "-l", "25", str(pdf), f"{tmp}/p.pdf"], check=True, capture_output=True
        )
        page = Path(tmp) / "p.pdf"
        extraction = read(page)
        records = extract_records(extraction, ocr_repair=True)
        scan = render(page, 1, 420)

    size = (460, 560)
    lines = [ln for ln in extraction.text().split("\n") if "OORDIN" in ln][:3]

    def shell(title: str, body: list[str], image: Image.Image | None) -> Image.Image:
        canvas = Image.new("RGB", size, PAPER)
        draw = ImageDraw.Draw(canvas)
        draw.text((14, 12), title, font=font(14, bold=True), fill=INK)
        y = 38
        for line in body:
            draw.text((14, y), line, font=font(11), fill=MUTED)
            y += 15
        if image is not None:
            canvas.paste(image, (20, y + 8))
        return canvas

    frames = [
        shell(
            "1. A scanned page. No text layer at all.",
            ["doc2geo inspect p25.pdf", '  "backend": "tesseract"'],
            scan.resize((420, 470), Image.LANCZOS),
        ),
        shell(
            "2. OCR, keeping the line structure.",
            ["Running the page together would merge three records into one."] + [ln[:66] for ln in lines],
            None,
        ),
        shell(
            "3. Packed DMS parsed per record.",
            [
                "S060000  ->  -6.0        E0394000  ->  39.667",
                "S033000  ->  -3.5        0393000   ->  hemisphere from its sibling",
                "",
                "Two latitudes and two longitudes are an extent, not a point.",
            ],
            None,
        ),
        shell(
            f"4. {len(records)} polygons, flagged and low-confidence.",
            [f"{r.properties.get('extent')}   confidence {r.confidence}" for r in records],
            framed(plot_geometry(records, (420, 330))),
        ),
    ]
    frames[0].save(
        OUT / "scan-pipeline.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[2600, 3000, 3200, 3600],
        loop=0,
        optimize=True,
    )
    print("scan-pipeline.gif", frames[0].size, len(frames), "frames")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    map_page_detection()
    scans_to_polygons()
    licence_corners()
    detection_gif()
    pipeline_gif()
    print("\nwrote", len(list(OUT.iterdir())), "files to", OUT)
