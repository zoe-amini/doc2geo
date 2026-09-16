from __future__ import annotations

from doc2geo.detect import crs_hint_from_text, pick_columns, records_from_table, records_from_text
from doc2geo.readers import read
from doc2geo.records import Table, TextBlock


def test_picks_columns_by_name(points_csv):
    table = read(points_csv).tables[0]
    pick = pick_columns(table)
    assert pick is not None
    assert pick.lon == "longitude"
    assert pick.lat == "latitude"
    assert pick.confidence > 0.9


def test_picks_easting_northing():
    table = Table(header=["hole", "Easting", "Northing"], rows=[["a", "512345", "7612345"]])
    pick = pick_columns(table)
    assert (pick.lon, pick.lat) == ("Easting", "Northing")


def test_records_carry_properties_but_not_the_coordinate_columns(points_csv):
    table = read(points_csv).tables[0]
    records, _ = records_from_table(table)
    assert len(records) == 3
    assert records[0].properties["name"] == "Mmadinare"
    assert "longitude" not in records[0].properties
    assert records[0].lat < 0


def test_reads_dms_cells(dms_csv):
    table = read(dms_csv).tables[0]
    records, _ = records_from_table(table)
    assert len(records) == 2
    assert records[0].lat == -21.57
    assert 25.2 < records[0].lon < 25.21


def test_utm_needs_a_crs_hint_and_uses_it(utm_csv):
    table = read(utm_csv).tables[0]
    without, _ = records_from_table(table)
    # Treated as degrees with no hint, which the range check will reject downstream.
    with_hint, _ = records_from_table(table, crs_hint="EPSG:32734")
    assert len(with_hint) == 2
    assert -25 < with_hint[0].lat < -18
    assert with_hint[0] != without[0] if without else True


def test_infers_columns_from_values_when_headers_are_useless():
    table = Table(
        header=["a", "b", "c"],
        rows=[["x", "-21.87", "27.12"], ["y", "-21.97", "27.80"], ["z", "-21.10", "27.54"]],
    )
    pick = pick_columns(table)
    assert pick is not None
    assert pick.confidence < 0.9
    assert (pick.lon, pick.lat) == ("c", "b")


def test_finds_a_pair_in_prose():
    block = TextBlock(text="The collar sits at 21°34'12\"S, 25°12'03\"E on the farm boundary.")
    records = records_from_text(block)
    assert len(records) == 1
    assert records[0].lat == -21.57
    assert records[0].confidence < 0.8


def test_finds_utm_easting_northing_in_prose():
    block = TextBlock(text="Collar at zone 34S 512345 mE 7612345 mN, surveyed 1998.")
    records = records_from_text(block)
    assert len(records) == 1
    assert -25 < records[0].lat < -18


def test_crs_hint_from_text():
    assert "arc 1950" in (crs_hint_from_text("Coordinates are Arc 1950 / UTM zone 34S.") or "").lower()
    assert crs_hint_from_text("No projection is stated anywhere.") is None
