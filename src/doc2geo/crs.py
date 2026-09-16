"""Coordinate reference systems, as they actually turn up in documents.

Survey data does not arrive as EPSG codes. It arrives as "Arc 1950 / UTM 34S" in a page
header, "Cape Datum" in a footnote, or nothing at all. This module turns those hints into
a real CRS, transforms to WGS84, and keeps a record of what it did so the caller can show
its work: the source CRS, the transformation, and how precise the numbers looked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyproj import CRS, Transformer
from pyproj.crs import ProjectedCRS
from pyproj.crs.coordinate_operation import UTMConversion

# Datum names met in the wild, mapped to their geographic EPSG code. Matched case-insensitively
# as substrings, so "ARC 1950 (Botswana)" and "arc1950" both land on 4209.
DATUM_HINTS: dict[str, int] = {
    "wgs84": 4326,
    "wgs 84": 4326,
    "cape": 4222,
    "arc 1950": 4209,
    "arc1950": 4209,
    "arc 1960": 4210,
    "arc1960": 4210,
    "luzon": 4253,
    "prs92": 4683,
    "prs 92": 4683,
    "zanderij": 4311,
    "adindan": 4201,
    "minna": 4263,
    "sad69": 4618,
    "nad27": 4267,
    "nad83": 4269,
    "ed50": 4230,
    "osgb": 4277,
    "pulkovo": 4284,
}

_UTM = re.compile(r"utm\s*(?:zone\s*)?(\d{1,2})\s*([ns])?", re.I)
_EPSG = re.compile(r"epsg:\s*\d+", re.I)

WGS84 = CRS.from_epsg(4326)


@dataclass(frozen=True)
class GeoPoint:
    """A point in WGS84, with the provenance of how it got there."""

    lon: float
    lat: float
    source_crs: str
    transform: str
    accuracy_m: float | None = None


def crs_from_hint(hint: str | int | None, default: int = 4326) -> CRS:
    """Resolve an EPSG code, WKT, PROJ string, or a datum name lifted from a document.

    A datum name combined with a UTM zone ("Arc 1950 UTM 34S") composes the projected CRS
    on that datum, so the EPSG datum shift to WGS84 is preserved rather than silently
    treating the coordinates as if they were already WGS84.
    """
    if hint is None:
        return CRS.from_epsg(default)
    if isinstance(hint, int):
        return CRS.from_epsg(hint)

    text = hint.strip()
    if not text:
        return CRS.from_epsg(default)
    if _EPSG.fullmatch(text):
        return CRS.from_user_input(text.replace(" ", ""))
    if text.isdigit():
        return CRS.from_epsg(int(text))

    low = text.lower()
    for name, code in DATUM_HINTS.items():
        if name not in low:
            continue
        geodetic = CRS.from_epsg(code)
        zone = _UTM.search(low)
        if not zone:
            return geodetic
        number = int(zone.group(1))
        hemisphere = (zone.group(2) or "n").upper()
        if code == 4326:
            return CRS.from_epsg((32600 if hemisphere == "N" else 32700) + number)
        return ProjectedCRS(
            conversion=UTMConversion(number, hemisphere),
            geodetic_crs=geodetic,
            name=f"{geodetic.name} / UTM zone {number}{hemisphere}",
        )

    # A bare UTM zone with no datum named: assume WGS84, which is what modern GPS output is.
    zone = _UTM.search(low)
    if zone:
        number = int(zone.group(1))
        hemisphere = (zone.group(2) or "n").upper()
        return CRS.from_epsg((32600 if hemisphere == "N" else 32700) + number)

    return CRS.from_user_input(text)


def to_wgs84(
    x: float,
    y: float,
    source: str | int | CRS | None,
    *,
    accuracy_m: float | None = None,
) -> GeoPoint:
    """Transform a single coordinate pair into WGS84, recording the CRS and operation used."""
    src = source if isinstance(source, CRS) else crs_from_hint(source)
    transformer = Transformer.from_crs(src, WGS84, always_xy=True)
    lon, lat = transformer.transform(x, y)
    label = src.name if src.name and src.name != "undefined" else src.to_string()
    description = getattr(transformer, "description", None) or str(transformer)
    return GeoPoint(round(lon, 7), round(lat, 7), label[:120], description[:120], accuracy_m)


_DMS = re.compile(
    r"""(?x)
    (?P<deg>-?\d{1,3})\s*(?:°|d|:|\s)\s*
    (?P<min>\d{1,2}(?:[.,]\d+)?)?\s*(?:'|’|m|:|\s)?\s*
    (?P<sec>\d{1,2}(?:[.,]\d+)?)?\s*(?:"|”|''|s)?\s*
    (?P<hemi>[NSEWnsew])?
    """,
)
_DECIMAL = re.compile(r"(?i)^\s*(-?\d+(?:[.,]\d+)?)\s*°?\s*([NSEW])?\s*$")


def parse_dms(text: str) -> float | None:
    """Parse the coordinate spellings documents use.

    Handles 21°34'12"S, 21 34 12 S, 21d34m12sS, -21.57 and 21,57S. Returns decimal degrees,
    negative for south and west, or None when the text is not a coordinate at all.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    decimal = _DECIMAL.match(raw)
    if decimal:
        value = float(decimal.group(1).replace(",", "."))
        hemisphere = (decimal.group(2) or "").upper()
        return -abs(value) if hemisphere in ("S", "W") else value

    match = _DMS.fullmatch(raw)
    if not match or match.group("deg") is None:
        return None
    degrees = float(match.group("deg"))
    minutes = float((match.group("min") or "0").replace(",", "."))
    seconds = float((match.group("sec") or "0").replace(",", "."))
    if minutes >= 60 or seconds >= 60:
        return None
    value = abs(degrees) + minutes / 60 + seconds / 3600
    hemisphere = (match.group("hemi") or "").upper()
    if degrees < 0 or hemisphere in ("S", "W"):
        value = -value
    return round(value, 7)


def guess_precision_m(lon: float, lat: float) -> float:
    """Estimate positional precision from how many decimals the document actually carried.

    A table rounded to three decimals is telling you it is good to roughly 100 m, whatever
    the report's methods section claims.
    """

    def decimals(value: float) -> int:
        text = f"{value:.8f}".rstrip("0")
        return len(text.split(".")[1]) if "." in text else 0

    places = min(decimals(lon), decimals(lat))
    return round(111_320 / (10**places), 1) if places < 8 else 0.01
