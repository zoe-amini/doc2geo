"""doc2geo — turn documents into geospatial data.

Readers pull tables, text and page images out of PDFs, scans, Word files and spreadsheets.
The detector finds coordinates in them. Writers emit GeoJSON, Shapefile, GeoPackage or CSV.
Everything carries its provenance: source CRS, transformation, confidence and page.
"""

from __future__ import annotations

__version__ = "0.3.0"

from .crs import GeoPoint, crs_from_hint, guess_precision_m, parse_dms, to_wgs84
from .detect import extract_records
from .geometry import parse_packed_dms, parse_wkt
from .readers import UnsupportedInput, read
from .records import Extraction, Record, Table, TextBlock

__all__ = [
    "Extraction",
    "GeoPoint",
    "Record",
    "Table",
    "TextBlock",
    "UnsupportedInput",
    "__version__",
    "crs_from_hint",
    "extract_records",
    "guess_precision_m",
    "parse_dms",
    "parse_packed_dms",
    "parse_wkt",
    "read",
    "to_wgs84",
]
