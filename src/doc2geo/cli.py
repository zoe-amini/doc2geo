"""Command line: `doc2geo convert`, `doc2geo maps`, `doc2geo inspect`."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .checks import check_records
from .detect import extract_records
from .graticule import georeference_page, tokens_from_pdf_page, write_world_file
from .mappages import DEFAULT_THRESHOLD, extract_map_pages, find_map_pages
from .readers import SUPPORTED, UnsupportedInput, read
from .writers import WriteError, write


def _bbox(text: str | None) -> tuple[float, float, float, float] | None:
    if not text:
        return None
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be min_lon,min_lat,max_lon,max_lat")
    return parts[0], parts[1], parts[2], parts[3]


def cmd_convert(args: argparse.Namespace) -> int:
    try:
        extraction = read(Path(args.input), ocr_backend=args.ocr, max_pages=args.max_pages)
    except UnsupportedInput as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    records = extract_records(
        extraction, crs_hint=args.crs, geometry=args.geometry, ocr_repair=args.ocr_repair
    )
    if args.min_confidence:
        records = [r for r in records if r.confidence >= args.min_confidence]

    report = check_records(records, bbox=_bbox(args.bbox))
    if not records:
        note = extraction.note or "no coordinates matched"
        print(f"no records found in {args.input} ({note})", file=sys.stderr)
        if args.strict:
            return 1

    output = Path(args.output) if args.output else Path(args.input).with_suffix(".geojson")
    try:
        write(records, output)
    except WriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    kinds = Counter(r.geom_type for r in records)
    summary = {
        "input": str(args.input),
        "output": str(output),
        "records": len(records),
        "geometries": dict(kinds),
        "backend": extraction.backend,
        "checks": report.summary(),
    }
    if args.json:
        print(json.dumps(summary, indent=1))
    else:
        mix = ", ".join(f"{count} {kind.lower()}" for kind, count in kinds.most_common()) or "nothing"
        print(f"{len(records)} record(s) -> {output}  [{mix}; {extraction.backend}]")
        for finding in report.findings[: args.max_findings]:
            print(f"  {finding.level:>5}  {finding.check}: {finding.message}")
        remaining = len(report.findings) - args.max_findings
        if remaining > 0:
            print(f"  ... {remaining} more finding(s)")
    return 1 if (args.strict and report.errors) else 0


def cmd_maps(args: argparse.Namespace) -> int:
    pdf = Path(args.input)
    if pdf.suffix.lower() != ".pdf":
        print("error: `maps` works on PDFs", file=sys.stderr)
        return 2

    if args.list_only:
        pages = find_map_pages(
            pdf, threshold=args.threshold, render=not args.no_render, max_pages=args.max_pages
        )
    else:
        pages = extract_map_pages(
            pdf,
            Path(args.out_dir),
            threshold=args.threshold,
            dpi=args.dpi,
            render=not args.no_render,
            max_pages=args.max_pages,
        )

    manifest = []
    for found in pages:
        entry = found.as_dict()
        if args.georeference:
            geo = georeference_page(tokens_from_pdf_page(pdf, found.page))
            entry["georeference"] = {
                "fitted": geo.fitted,
                "residual_deg": geo.residual_deg,
                "note": geo.note,
                "control_points": geo.control_points,
            }
            if found.image_path and geo.fitted:
                from PIL import Image

                with Image.open(found.image_path) as image:
                    pixels = image.size
                signals = found.signals
                world = (
                    write_world_file(geo, found.image_path, signals.width, signals.height, pixels)
                    if signals
                    else None
                )
                entry["georeference"]["world_file"] = str(world) if world else None
        manifest.append(entry)

    if args.json:
        print(json.dumps({"input": str(pdf), "map_pages": manifest}, indent=1))
        return 0

    if not pages:
        print(f"no map pages found in {pdf.name} (threshold {args.threshold})")
        return 0
    print(f"{len(pages)} map page(s) in {pdf.name}:")
    for found, entry in zip(pages, manifest, strict=True):
        print(f"  page {found.page:>4}  score {found.score:.2f}  {'; '.join(found.reasons)}")
        if found.image_path:
            print(f"             -> {found.image_path}")
        geo = entry.get("georeference")
        if geo:
            print(f"             georeference: {geo['note']}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    try:
        extraction = read(Path(args.input), ocr_backend=args.ocr, max_pages=args.max_pages)
    except UnsupportedInput as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {
        "source": str(extraction.source),
        "pages": extraction.pages,
        "backend": extraction.backend,
        "note": extraction.note,
        "tables": [
            {"name": t.name, "page": t.page, "rows": len(t.rows), "header": t.header[:12]}
            for t in extraction.tables
        ],
        "text_blocks": len(extraction.blocks),
        "characters": len(extraction.text()),
        "low_confidence_blocks": len(extraction.low_confidence()),
    }
    print(json.dumps(payload, indent=1))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2geo",
        description="Turn documents into geospatial data.",
        epilog=f"supported inputs: {', '.join(sorted(SUPPORTED))}",
    )
    parser.add_argument("--version", action="version", version=f"doc2geo {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("input", help="file to read")
    common.add_argument("--ocr", default="auto", choices=("auto", "tesseract", "http"), help="OCR backend")
    common.add_argument("--max-pages", type=int, default=40, help="page limit for OCR and detection")

    convert = subparsers.add_parser(
        "convert", parents=[common], help="extract coordinates to a geospatial file"
    )
    convert.add_argument("-o", "--output", help="output path; extension picks the format")
    convert.add_argument(
        "--crs", help="CRS of the source coordinates, e.g. 'Arc 1950 / UTM 34S' or EPSG:20934"
    )
    convert.add_argument("--bbox", help="expected area as min_lon,min_lat,max_lon,max_lat")
    convert.add_argument(
        "--geometry",
        default="auto",
        choices=("auto", "points"),
        help="auto builds lines and polygons where the document supports it; points keeps rows as points",
    )
    convert.add_argument(
        "--ocr-repair",
        action="store_true",
        help="accept a glyph where a badly scanned hemisphere letter should be; flagged in the output",
    )
    convert.add_argument(
        "--min-confidence", type=float, default=0.0, help="drop records below this confidence"
    )
    convert.add_argument("--max-findings", type=int, default=10, help="findings to print")
    convert.add_argument("--strict", action="store_true", help="exit non-zero on errors or no records")
    convert.add_argument("--json", action="store_true", help="machine-readable summary")
    convert.set_defaults(func=cmd_convert)

    maps = subparsers.add_parser("maps", help="find and extract the map pages of a PDF")
    maps.add_argument("input", help="PDF to scan")
    maps.add_argument("-o", "--out-dir", default="map_pages", help="where to write page images")
    maps.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD, help="score needed to count as a map"
    )
    maps.add_argument("--dpi", type=int, default=300, help="render resolution for extracted pages")
    maps.add_argument("--list-only", action="store_true", help="report pages without writing images")
    maps.add_argument("--no-render", action="store_true", help="skip the colour pass (text signals only)")
    maps.add_argument("--georeference", action="store_true", help="fit a world file from graticule labels")
    maps.add_argument("--max-pages", type=int, default=None, help="only look at the first N pages")
    maps.add_argument("--json", action="store_true", help="machine-readable manifest")
    maps.set_defaults(func=cmd_maps)

    inspect = subparsers.add_parser(
        "inspect", parents=[common], help="show what a reader found, without converting"
    )
    inspect.set_defaults(func=cmd_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"error: no such file: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
