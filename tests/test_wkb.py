"""WKB encoding, and the OGR formats that depend on it."""

from __future__ import annotations

import struct

import pytest

from doc2geo import wkb
from doc2geo.records import Record
from doc2geo.writers import WriteError, write

pyogrio = pytest.importorskip("pyogrio", reason="needs the gdal extra")

SQUARE = [[25.0, -21.0], [25.5, -21.0], [25.5, -21.5], [25.0, -21.5]]


def test_point_encoding_is_little_endian_type_one():
    blob = wkb.dumps({"type": "Point", "coordinates": [25.2, -21.57]})
    assert blob[0:1] == b"\x01"
    assert struct.unpack("<I", blob[1:5])[0] == 1
    assert struct.unpack("<dd", blob[5:]) == (25.2, -21.57)


def test_polygon_encoding_counts_rings_and_points():
    ring = [*SQUARE, SQUARE[0]]
    blob = wkb.dumps({"type": "Polygon", "coordinates": [ring]})
    assert struct.unpack("<I", blob[1:5])[0] == 3
    assert struct.unpack("<I", blob[5:9])[0] == 1  # one ring
    assert struct.unpack("<I", blob[9:13])[0] == len(ring)  # closed, so five points


def test_linestring_encoding():
    blob = wkb.dumps({"type": "LineString", "coordinates": SQUARE})
    assert struct.unpack("<I", blob[1:5])[0] == 2
    assert struct.unpack("<I", blob[5:9])[0] == 4


def test_multipolygon_nests_complete_geometries():
    blob = wkb.dumps({"type": "MultiPolygon", "coordinates": [[[*SQUARE, SQUARE[0]]]]})
    assert struct.unpack("<I", blob[1:5])[0] == 6
    assert struct.unpack("<I", blob[5:9])[0] == 1
    assert blob[9:10] == b"\x01"  # the nested polygon carries its own byte-order flag


def test_unsupported_geometry_is_named():
    with pytest.raises(wkb.UnsupportedGeometry, match="GeometryCollection"):
        wkb.dumps({"type": "GeometryCollection", "coordinates": []})


def _records() -> list[Record]:
    return [
        Record.polygon(SQUARE, properties={"licence": "PL-142", "holder": "Example Ltd"}),
        Record.polygon([[p[0] + 1, p[1]] for p in SQUARE], properties={"licence": "PL-143"}),
    ]


@pytest.mark.parametrize(
    ("suffix", "geometry"),
    [(".gpkg", "Polygon"), (".shp", "Polygon"), (".fgb", "Polygon")],
)
def test_ogr_round_trip(tmp_path, suffix, geometry):
    path = write(_records(), tmp_path / f"blocks{suffix}")
    info = pyogrio.read_info(str(path))
    assert info["features"] == 2
    assert geometry in str(info["geometry_type"])
    assert "EPSG:4326" in str(info["crs"]) or "4326" in str(info["crs"])
    assert "licence" in info["fields"]


def test_shapefile_field_names_are_truncated_and_unique(tmp_path):
    records = [
        Record.point(
            25.0,
            -21.0,
            properties={
                "a_very_long_field_name_one": "x",
                "a_very_long_field_name_two": "y",
            },
        )
    ]
    path = write(records, tmp_path / "points.shp")
    fields = list(pyogrio.read_info(str(path))["fields"])
    assert all(len(name) <= 10 for name in fields)
    assert len(set(fields)) == len(fields)


def test_shapefile_refuses_mixed_geometry(tmp_path):
    """One shapefile, one geometry type. Say so rather than writing a surprising file."""
    mixed = [Record.point(25.0, -21.0), Record.polygon(SQUARE)]
    with pytest.raises(WriteError, match="one geometry type"):
        write(mixed, tmp_path / "mixed.shp")


def test_ogr_refuses_an_empty_layer(tmp_path):
    with pytest.raises(WriteError, match="nothing to write"):
        write([], tmp_path / "empty.gpkg")
