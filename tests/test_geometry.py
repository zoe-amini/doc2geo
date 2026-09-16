"""Lines and polygons: WKT cells, grouped vertex tables, and catalogue bounding boxes."""

from __future__ import annotations

import csv

import pytest

from doc2geo.detect import extract_records, records_from_table_shapes
from doc2geo.geometry import bbox_from_text, parse_packed_dms, parse_wkt
from doc2geo.readers import read
from doc2geo.records import Extraction, Table, TextBlock
from doc2geo.writers import to_wkt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("S060000", -6.0),
        ("N060000", 6.0),
        ("E0340000", 34.0),
        ("W0340000", -34.0),
        ("S0213412", -21.570000),
        ("0213412S", -21.570000),
    ],
)
def test_parse_packed_dms(text, expected):
    assert parse_packed_dms(text) == pytest.approx(expected, abs=1e-5)


@pytest.mark.parametrize("text", ["060000", "", "S06", "S069999", "Z060000", None])
def test_packed_dms_needs_a_hemisphere_and_valid_parts(text):
    """Without a hemisphere letter the sign is unknowable, and guessing relocates the data."""
    assert parse_packed_dms(text) is None


def test_parse_wkt_point_and_line():
    assert parse_wkt("POINT (25.2 -21.5)")["coordinates"] == [25.2, -21.5]
    line = parse_wkt("LINESTRING (25.2 -21.5, 25.3 -21.6)")
    assert line["type"] == "LineString"
    assert len(line["coordinates"]) == 2


def test_parse_wkt_polygon_closes_an_open_ring():
    polygon = parse_wkt("POLYGON ((0 0, 1 0, 1 1, 0 1))")
    ring = polygon["coordinates"][0]
    assert ring[0] == ring[-1]
    assert len(ring) == 5


def test_parse_wkt_keeps_polygon_holes():
    polygon = parse_wkt("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))")
    assert len(polygon["coordinates"]) == 2


def test_parse_wkt_rejects_rubbish():
    assert parse_wkt("not geometry at all") is None
    assert parse_wkt("POLYGON ((0 0, 1 1))") is None  # too few vertices for a ring


def test_wkt_round_trip_through_the_csv_writer():
    geometry = parse_wkt("POLYGON ((0 0, 1 0, 1 1, 0 0))")
    assert to_wkt(geometry).startswith("POLYGON ((")
    assert parse_wkt(to_wkt(geometry)) == geometry


def test_licence_corners_become_a_polygon():
    table = Table(
        header=["licence", "corner", "lon", "lat"],
        rows=[
            ["PL-1", "1", "25.0", "-21.0"],
            ["PL-1", "2", "25.5", "-21.0"],
            ["PL-1", "3", "25.5", "-21.5"],
            ["PL-1", "4", "25.0", "-21.5"],
        ],
        name="blocks",
    )
    records = records_from_table_shapes(table)
    assert len(records) == 1
    assert records[0].geom_type == "Polygon"
    ring = records[0].geometry["coordinates"][0]
    assert ring[0] == ring[-1]
    assert records[0].properties["group"] == "PL-1"


def test_two_licences_become_two_polygons():
    rows = []
    for name in ("PL-1", "PL-2"):
        offset = 0.0 if name == "PL-1" else 2.0
        for order, (x, y) in enumerate([(25.0, -21.0), (25.5, -21.0), (25.5, -21.5)], 1):
            rows.append([name, str(order), str(x + offset), str(y)])
    table = Table(header=["licence", "corner", "lon", "lat"], rows=rows, name="blocks")
    records = records_from_table_shapes(table)
    assert len(records) == 2
    assert {r.geom_type for r in records} == {"Polygon"}


def test_a_traverse_stays_a_line():
    """A named line is a path. Closing it would invent area nobody surveyed."""
    table = Table(
        header=["line", "station", "lon", "lat"],
        rows=[
            ["L-1", "1", "25.0", "-21.0"],
            ["L-1", "2", "25.2", "-21.1"],
            ["L-1", "3", "25.4", "-21.2"],
        ],
        name="traverses",
    )
    records = records_from_table_shapes(table)
    assert len(records) == 1
    assert records[0].geom_type == "LineString"
    assert len(records[0].geometry["coordinates"]) == 3


def test_a_closed_ring_is_a_polygon_even_under_a_neutral_group_name():
    table = Table(
        header=["feature", "seq", "lon", "lat"],
        rows=[
            ["F1", "1", "25.0", "-21.0"],
            ["F1", "2", "25.5", "-21.0"],
            ["F1", "3", "25.5", "-21.5"],
            ["F1", "4", "25.0", "-21.0"],
        ],
    )
    records = records_from_table_shapes(table)
    assert records[0].geom_type == "Polygon"


def test_vertices_are_ordered_by_the_order_column_not_row_order():
    table = Table(
        header=["block", "corner", "lon", "lat"],
        rows=[
            ["B", "3", "25.5", "-21.5"],
            ["B", "1", "25.0", "-21.0"],
            ["B", "2", "25.5", "-21.0"],
        ],
    )
    ring = records_from_table_shapes(table)[0].geometry["coordinates"][0]
    assert ring[0] == [25.0, -21.0]
    assert ring[1] == [25.5, -21.0]


def test_a_plain_point_table_is_not_turned_into_a_shape(points_csv):
    """Every site_id is distinct, so there is nothing to group: these stay points."""
    table = read(points_csv).tables[0]
    assert records_from_table_shapes(table) is None
    records = extract_records(read(points_csv))
    assert {r.geom_type for r in records} == {"Point"}


def test_points_mode_disables_shape_assembly(tmp_path):
    path = tmp_path / "corners.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["licence", "corner", "lon", "lat"])
        for order, (x, y) in enumerate([(25.0, -21.0), (25.5, -21.0), (25.5, -21.5)], 1):
            writer.writerow(["PL-1", order, x, y])

    assert extract_records(read(path))[0].geom_type == "Polygon"
    as_points = extract_records(read(path), geometry="points")
    assert len(as_points) == 3
    assert {r.geom_type for r in as_points} == {"Point"}


def test_catalogue_bounding_box_becomes_a_polygon():
    block = TextBlock(
        text="COORDINATES: Latitude: S060000 ; S030000; Longitude: E0340000 ; E0390000",
        confidence=0.75,
    )
    records = bbox_from_text(block)
    assert len(records) == 1
    assert records[0].geom_type == "Polygon"
    ring = records[0].geometry["coordinates"][0]
    longitudes = [p[0] for p in ring]
    latitudes = [p[1] for p in ring]
    assert min(longitudes) == 34.0
    assert max(longitudes) == 39.0
    assert min(latitudes) == -6.0
    assert max(latitudes) == -3.0
    assert records[0].confidence < 0.75


def test_a_single_pair_is_not_a_bounding_box():
    block = TextBlock(text="COORDINATES: Latitude: S060000 Longitude: E0340000")
    assert bbox_from_text(block) == []


def test_extraction_prefers_the_bounding_box_over_loose_points():
    extraction = Extraction(
        source="catalogue.pdf",
        blocks=[TextBlock(text="Latitude: S060000 ; S030000 Longitude: E0340000 ; E0390000")],
    )
    records = extract_records(extraction)
    assert [r.geom_type for r in records] == ["Polygon"]


def test_punctuation_between_letter_and_digits_is_tolerated():
    """Scanners speckle; "S.060000" is still unambiguous."""
    assert parse_packed_dms("S.060000") == -6.0
    assert parse_packed_dms("° S033000") == pytest.approx(-3.5)


def test_repair_is_off_by_default():
    block = TextBlock(text="Latitude: $060000 ; 5030000 Longitude: E0394000 ; E0393000")
    assert bbox_from_text(block) == []


def test_repair_reads_a_hemisphere_glyph_when_asked():
    block = TextBlock(text="Latitude: $060000 ; $033000 Longitude: E0394000 ; E0393000")
    records = bbox_from_text(block, repair=True)
    assert len(records) == 1
    assert records[0].properties["ocr_repair_enabled"] is True
    assert records[0].confidence < 0.5


def test_repair_takes_the_hemisphere_from_a_legible_sibling():
    """The second longitude lost its E; the first one still has it."""
    block = TextBlock(text="Latitude: S060000 ; S033000 Longitude: E0394000 ; 0393000")
    records = bbox_from_text(block, repair=True)
    assert len(records) == 1
    ring = records[0].geometry["coordinates"][0]
    assert min(p[0] for p in ring) == pytest.approx(39.5)
    assert max(p[0] for p in ring) == pytest.approx(39.6666667)


def test_repair_reads_a_digit_that_stood_in_for_the_hemisphere():
    """ "5030000" is "S030000" with the S misread as a 5: the glyph splits off, six digits remain."""
    assert parse_packed_dms("5030000", axis="lat", repair=True) == pytest.approx(-3.0)


def test_repair_still_rejects_an_out_of_range_value():
    """Repair supplies a hemisphere, never a plausible number: 503 degrees is still nonsense."""
    assert parse_packed_dms("S5030000", axis="lat", repair=True) is None
    assert parse_packed_dms("9930000", axis="lat", repair=True) is None


def test_each_catalogue_record_gets_its_own_box():
    """Pooling values across records would invent an extent that is the union of all of them."""
    block = TextBlock(
        text=(
            "Latitude: S060000 ; S033000 Longitude: E0394000 ; E0393000\n"
            "Latitude: S040000 ; S033000 Longitude: E0344000 ; E0343000"
        )
    )
    records = bbox_from_text(block)
    assert len(records) == 2
    firsts = [min(p[0] for p in r.geometry["coordinates"][0]) for r in records]
    assert firsts[0] != firsts[1]


def test_repair_drops_a_record_whose_digits_are_mangled():
    """Repair supplies a missing hemisphere. It cannot, and must not, invent digits.

    This is the real shape of a line from a poor scan: the first latitude is legible, the
    second lost its letter *and* gained a digit, so it reads 503 degrees. Dropping the record
    beats emitting a box whose corner is somewhere it has never been.
    """
    block = TextBlock(text="Latitude: S060000 .;..5030000 Longitude: E0400000 ; H0890000")
    assert bbox_from_text(block, repair=True) == []
