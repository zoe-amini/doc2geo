"""Well-known binary, written by hand.

Shapefiles and GeoPackages are written through pyogrio, which wants geometry as WKB. The usual
way to produce that is shapely, via geopandas — roughly a hundred megabytes of pandas, numpy
and shapely to encode a few dozen coordinate pairs. The format is a byte order flag, a type
code and a count of doubles, so it is encoded here instead and the optional install stays one
wheel rather than a stack.
"""

from __future__ import annotations

import struct
from typing import Any

LITTLE_ENDIAN = b"\x01"
TYPE_CODES = {
    "Point": 1,
    "LineString": 2,
    "Polygon": 3,
    "MultiPoint": 4,
    "MultiLineString": 5,
    "MultiPolygon": 6,
}


class UnsupportedGeometry(ValueError):
    """A geometry type with no WKB encoder here."""


def _point(coordinates: Any) -> bytes:
    return struct.pack("<dd", float(coordinates[0]), float(coordinates[1]))


def _ring(points: Any) -> bytes:
    return struct.pack("<I", len(points)) + b"".join(_point(p) for p in points)


def _header(kind: str) -> bytes:
    return LITTLE_ENDIAN + struct.pack("<I", TYPE_CODES[kind])


def dumps(geometry: dict[str, Any]) -> bytes:
    """Encode a GeoJSON geometry dict as little-endian WKB."""
    kind = str(geometry.get("type", ""))
    coordinates = geometry.get("coordinates")
    if kind not in TYPE_CODES:
        raise UnsupportedGeometry(f"no WKB encoder for {kind or 'an empty geometry'}")
    if coordinates is None:
        raise UnsupportedGeometry(f"{kind} has no coordinates")

    if kind == "Point":
        return _header(kind) + _point(coordinates)
    if kind in ("LineString", "MultiPoint"):
        if kind == "MultiPoint":
            # Each point in a MultiPoint carries its own header, unlike a LineString's vertices.
            return (
                _header(kind)
                + struct.pack("<I", len(coordinates))
                + b"".join(_header("Point") + _point(p) for p in coordinates)
            )
        return _header(kind) + _ring(coordinates)
    if kind == "Polygon":
        return _header(kind) + struct.pack("<I", len(coordinates)) + b"".join(_ring(r) for r in coordinates)
    if kind == "MultiLineString":
        return (
            _header(kind)
            + struct.pack("<I", len(coordinates))
            + b"".join(_header("LineString") + _ring(line) for line in coordinates)
        )
    # MultiPolygon: each polygon is a complete WKB geometry in its own right.
    return (
        _header(kind)
        + struct.pack("<I", len(coordinates))
        + b"".join(
            _header("Polygon") + struct.pack("<I", len(rings)) + b"".join(_ring(r) for r in rings)
            for rings in coordinates
        )
    )
