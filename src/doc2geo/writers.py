"""Writing records out.

GeoJSON and CSV are written here with no dependencies at all, because the common case should
not require a GDAL stack. Shapefile, GeoPackage and anything else OGR knows go through pyogrio,
installed with the `gdal` extra.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from . import wkb
from .records import Record

GEOJSON_SUFFIXES = {".geojson", ".json"}
CSV_SUFFIXES = {".csv"}
OGR_DRIVERS = {
    ".shp": "ESRI Shapefile",
    ".gpkg": "GPKG",
    ".fgb": "FlatGeobuf",
    ".gml": "GML",
    ".kml": "KML",
}


class WriteError(RuntimeError):
    pass


def feature_collection(records: list[Record]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [r.to_feature() for r in records],
    }


def write_geojson(records: list[Record], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_collection(records), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def to_wkt(geometry: dict) -> str:
    """GeoJSON geometry to WKT, so a CSV can carry a polygon rather than lose it."""
    kind = str(geometry.get("type", "")).upper()
    coordinates = geometry.get("coordinates", [])

    def pair(point) -> str:
        return f"{point[0]} {point[1]}"

    def ring(points) -> str:
        return "(" + ", ".join(pair(p) for p in points) + ")"

    if kind == "POINT":
        return f"POINT ({pair(coordinates)})" if coordinates else "POINT EMPTY"
    if kind in ("LINESTRING", "MULTIPOINT"):
        return f"{kind} {ring(coordinates)}"
    if kind in ("POLYGON", "MULTILINESTRING"):
        return f"{kind} (" + ", ".join(ring(part) for part in coordinates) + ")"
    if kind == "MULTIPOLYGON":
        return (
            "MULTIPOLYGON ("
            + ", ".join("(" + ", ".join(ring(r) for r in polygon) + ")" for polygon in coordinates)
            + ")"
        )
    return "GEOMETRYCOLLECTION EMPTY"


def write_csv(records: list[Record], path: Path) -> Path:
    """Flat table with the geometry as WKT, then lon/lat, then the union of property keys."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for record in records:
        for key in record.properties:
            if key not in keys:
                keys.append(key)
    columns = ["geometry", "lon", "lat", *keys, "source_crs", "accuracy_m", "confidence", "page", "origin"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            centre = record.centroid()
            row = {
                "geometry": to_wkt(record.geometry),
                "lon": record.lon if record.lon is not None else (centre[0] if centre else ""),
                "lat": record.lat if record.lat is not None else (centre[1] if centre else ""),
                "source_crs": record.source_crs,
                "accuracy_m": record.accuracy_m,
                "confidence": round(record.confidence, 3),
                "page": record.page,
                "origin": record.origin,
            }
            row.update({k: v for k, v in record.properties.items()})
            writer.writerow(row)
    return path


def write_ogr(records: list[Record], path: Path, driver: str) -> Path:
    """Shapefile, GeoPackage and friends, through pyogrio.

    Geometry is encoded to WKB here rather than via geopandas, so the optional install is one
    wheel instead of a pandas and shapely stack. `pyogrio.raw.write` is the entry point that
    takes WKB directly; the round-trip test in the suite is what catches it if that changes.
    """
    try:
        import numpy
        from pyogrio.raw import write as ogr_write
    except ImportError as exc:  # pragma: no cover  depends on the optional extra
        raise WriteError(f"writing {driver} needs the gdal extra: pip install 'doc2geo[gdal]'") from exc

    if not records:
        raise WriteError(f"nothing to write: {driver} cannot store an empty layer usefully")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kinds = {r.geom_type for r in records}
    if len(kinds) > 1 and driver == "ESRI Shapefile":
        raise WriteError(
            f"a shapefile holds one geometry type; these records are {', '.join(sorted(kinds))}. "
            "Write GeoPackage (.gpkg) or GeoJSON instead."
        )

    try:
        geometry = numpy.array([wkb.dumps(r.geometry) for r in records], dtype=object)
    except wkb.UnsupportedGeometry as exc:
        raise WriteError(str(exc)) from exc

    keys: list[str] = []
    for record in records:
        for key in record.properties:
            if key not in keys and not key.startswith("_"):
                keys.append(key)
    names = _shapefile_safe(keys) if driver == "ESRI Shapefile" else keys

    columns = {
        name: [_flat(r.properties.get(key, "")) for r in records]
        for name, key in zip(names, keys, strict=True)
    }
    columns["confidence"] = [round(r.confidence, 3) for r in records]
    columns["src_crs"] = [r.source_crs for r in records]
    columns["origin"] = [r.origin for r in records]

    ogr_write(
        str(path),
        geometry=geometry,
        field_data=[numpy.array(values, dtype=object) for values in columns.values()],
        fields=numpy.array(list(columns), dtype=object),
        driver=driver,
        geometry_type=_ogr_geometry_type(kinds),
        crs="EPSG:4326",
    )
    return path


def _flat(value: object) -> str:
    """OGR fields hold scalars; a nested value becomes compact JSON rather than being dropped."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "" if value is None else str(value)


def _shapefile_safe(keys: list[str]) -> list[str]:
    """Shapefile field names are 10 characters. Truncate, then keep them unique."""
    out: list[str] = []
    for key in keys:
        name = key[:10]
        if name in out:
            for suffix in range(1, 100):
                candidate = f"{key[: 10 - len(str(suffix))]}{suffix}"
                if candidate not in out:
                    name = candidate
                    break
        out.append(name)
    return out


def _ogr_geometry_type(kinds: set[str]) -> str:
    return next(iter(kinds)) if len(kinds) == 1 else "Unknown"


def write(records: list[Record], path: Path) -> Path:
    """Dispatch on the output extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in GEOJSON_SUFFIXES:
        return write_geojson(records, path)
    if suffix in CSV_SUFFIXES:
        return write_csv(records, path)
    if suffix in OGR_DRIVERS:
        return write_ogr(records, path, OGR_DRIVERS[suffix])
    raise WriteError(
        f"no writer for {suffix or path.name}; supported: "
        f"{', '.join(sorted(GEOJSON_SUFFIXES | CSV_SUFFIXES | set(OGR_DRIVERS)))}"
    )
