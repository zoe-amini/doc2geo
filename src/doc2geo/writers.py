"""Writing records out.

GeoJSON and CSV are written here with no dependencies at all, because the common case should
not require a GDAL stack. Shapefile, GeoPackage and anything else OGR knows go through pyogrio,
installed with the `gdal` extra.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

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


def write_csv(records: list[Record], path: Path) -> Path:
    """Flat table with lon/lat first, then the union of all property keys."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for record in records:
        for key in record.properties:
            if key not in keys:
                keys.append(key)
    columns = ["lon", "lat", *keys, "source_crs", "accuracy_m", "confidence", "page", "origin"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = {
                "lon": record.lon,
                "lat": record.lat,
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
    """Shapefile, GeoPackage and friends, via pyogrio."""
    try:
        import pyogrio
    except ImportError as exc:  # pragma: no cover  depends on the optional extra
        raise WriteError(f"writing {driver} needs the gdal extra: pip install 'doc2geo[gdal]'") from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    geometry = [f"POINT ({r.lon} {r.lat})" for r in records]
    keys: list[str] = []
    for record in records:
        for key in record.properties:
            if key not in keys:
                keys.append(key)
    fields = {key: [str(r.properties.get(key, "")) for r in records] for key in keys}
    fields["confidence"] = [round(r.confidence, 3) for r in records]
    fields["src_crs"] = [r.source_crs for r in records]
    pyogrio.write_dataframe(
        _frame(fields, geometry),
        path,
        driver=driver,
        crs="EPSG:4326",
    )
    return path


def _frame(fields: dict, geometry: list[str]):
    """Build the GeoDataFrame pyogrio wants, importing geopandas only when this path is used."""
    try:
        import geopandas
        from shapely import from_wkt
    except ImportError as exc:  # pragma: no cover
        raise WriteError(
            "writing OGR formats needs geopandas and shapely: pip install 'doc2geo[gdal]'"
        ) from exc
    return geopandas.GeoDataFrame(fields, geometry=[from_wkt(w) for w in geometry], crs="EPSG:4326")


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
