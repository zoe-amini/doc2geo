from __future__ import annotations

import pytest

from doc2geo.crs import crs_from_hint, guess_precision_m, parse_dms, to_wgs84


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("21°34'12\"S", -21.570000),
        ("21 34 12 S", -21.570000),
        ("25°12'03\"E", 25.200833),
        ("-21.5701", -21.5701),
        ("21.5701S", -21.5701),
        ("21,5701 S", -21.5701),
        ("180°", 180.0),
    ],
)
def test_parse_dms(text, expected):
    assert parse_dms(text) == pytest.approx(expected, abs=1e-5)


@pytest.mark.parametrize("text", ["", "north", "abc", None, "21°99'00\"S"])
def test_parse_dms_rejects_non_coordinates(text):
    assert parse_dms(text) is None


def test_crs_from_hint_reads_epsg():
    assert crs_from_hint("EPSG:32734").to_epsg() == 32734
    assert crs_from_hint(4326).to_epsg() == 4326
    assert crs_from_hint("4326").to_epsg() == 4326


def test_crs_from_hint_reads_a_datum_name():
    assert crs_from_hint("Arc 1950 Datum").to_epsg() == 4209
    assert crs_from_hint("Cape").to_epsg() == 4222


def test_crs_from_hint_composes_datum_and_utm_zone():
    """The datum must survive: Arc 1950 UTM 34S is not WGS84 UTM 34S."""
    crs = crs_from_hint("Arc 1950 / UTM zone 34S")
    assert crs.is_projected
    assert "Arc 1950" in crs.name


def test_crs_from_hint_defaults_a_bare_utm_zone_to_wgs84():
    assert crs_from_hint("UTM zone 34S").to_epsg() == 32734
    assert crs_from_hint("utm 34n").to_epsg() == 32634


def test_to_wgs84_keeps_provenance():
    point = to_wgs84(512345, 7612345, "EPSG:32734")
    assert -27 < point.lon < 32
    assert -25 < point.lat < -18
    assert "34S" in point.source_crs or "32734" in point.source_crs
    assert point.transform


def test_datum_shift_actually_moves_the_point():
    """Arc 1950 and WGS84 differ by a few hundred metres in Botswana; a no-op would be a bug."""
    arc = to_wgs84(512345, 7612345, "Arc 1950 / UTM zone 34S")
    wgs = to_wgs84(512345, 7612345, "EPSG:32734")
    assert abs(arc.lon - wgs.lon) > 1e-4 or abs(arc.lat - wgs.lat) > 1e-4


def test_guess_precision_reflects_decimals():
    assert guess_precision_m(25.2, -21.5) > guess_precision_m(25.200833, -21.570001)
