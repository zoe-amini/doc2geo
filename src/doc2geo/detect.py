"""Finding coordinates in things that were not written for machines.

Two routes. Tables get their columns identified by name where possible and by the shape of
their values where not. Free text gets scanned for coordinate pairs written the way people
write them in reports. Both routes end in the same place: `Record`s in WGS84.

Nothing here guesses silently. Every record carries the CRS it came from, the transformation
applied and a confidence, so a caller can filter on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .crs import crs_from_hint, guess_precision_m, parse_dms, to_wgs84
from .records import Extraction, Record, Table, TextBlock

LON_NAMES = ("longitude", "long", "lon", "lng", "easting", "east", "x_coord", "utm_e", "x")
LAT_NAMES = ("latitude", "lat", "northing", "north", "y_coord", "utm_n", "y")
CRS_NAMES = ("crs", "epsg", "datum", "projection", "proj", "srs", "coordinate_system")

# "Arc 1950 / UTM zone 34S", "EPSG:32734", "WGS84 UTM 35N", "Cape Datum"
_CRS_IN_TEXT = re.compile(
    r"(?i)\b(epsg:\s*\d{4,6}|(?:wgs\s*-?84|arc\s*19[56]0|cape|luzon|prs\s*92|zanderij|adindan|minna|"
    r"nad\s*(?:27|83)|ed\s*50|pulkovo)(?:[^\n]{0,30}?utm\s*(?:zone\s*)?\d{1,2}\s*[ns]?)?|"
    r"utm\s*(?:zone\s*)?\d{1,2}\s*[ns])\b"
)

# A coordinate pair in prose: "21°34'12\"S, 25°12'03\"E" or "-21.5701, 25.2009"
_DMS_TOKEN = (
    r"-?\d{1,3}\s*(?:°|\s)\s*\d{1,2}(?:[.,]\d+)?\s*(?:'|’|\s)\s*(?:\d{1,2}(?:[.,]\d+)?\s*(?:\"|”)?)?\s*[NSEW]"
)
_DEC_TOKEN = r"-?\d{1,3}[.,]\d{3,}\s*°?\s*[NSEW]?"
_PAIR = re.compile(rf"(?i)({_DMS_TOKEN}|{_DEC_TOKEN})\s*[,;/ ]\s*({_DMS_TOKEN}|{_DEC_TOKEN})")

# "Zone 34S 512345E 7612345N" and the bare "512345 mE 7612345 mN" form.
_UTM_PAIR = re.compile(
    r"(?i)(?:zone\s*(\d{1,2})\s*([ns])\b[^\d]{0,20})?(\d{6,7})\s*(?:m\s*)?E\b[^\d]{0,12}(\d{6,8})\s*(?:m\s*)?N\b"
)


@dataclass
class ColumnPick:
    """Which columns the detector decided to use, and how sure it is."""

    lon: str
    lat: str
    crs: str | None = None
    confidence: float = 1.0
    reason: str = ""


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _match_column(names: list[str], candidates: tuple[str, ...]) -> str | None:
    """Exact normalised match first, then prefix, so `lat_wgs84` beats nothing at all."""
    normalised = {_normalise(n): n for n in names}
    for candidate in candidates:
        if candidate in normalised:
            return normalised[candidate]
    for candidate in candidates:
        for norm, original in normalised.items():
            if norm.startswith(candidate) or norm.endswith(candidate):
                return original
    return None


def _numeric(value: str) -> float | None:
    """A number as spreadsheets write them, including 1 234,56 and 1,234.56."""
    if value is None:
        return None
    text = str(value).strip().replace(" ", " ")
    if not text:
        return None
    text = re.sub(r"(?<=\d)[ ](?=\d{3}\b)", "", text)
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rindex(".") > text.rindex(",") else text.replace(".", "")
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _coordinate(value: str) -> float | None:
    """Either a plain number or a DMS string."""
    parsed = parse_dms(str(value))
    return parsed if parsed is not None else _numeric(value)


def pick_columns(table: Table) -> ColumnPick | None:
    """Identify the coordinate columns of a table, by name where possible, by values where not."""
    names = list(table.as_dicts()[0].keys()) if table.rows else list(table.header)
    if not names:
        return None

    lon = _match_column(names, LON_NAMES)
    lat = _match_column(names, LAT_NAMES)
    crs = _match_column(names, CRS_NAMES)
    if lon and lat and lon != lat:
        return ColumnPick(lon, lat, crs, 0.95, "matched column names")

    # No usable headers: look for two columns that behave like coordinates.
    rows = table.as_dicts()
    if len(rows) < 3:
        return None
    geographic: list[str] = []
    for name in names:
        values = [_coordinate(r.get(name, "")) for r in rows[:50]]
        values = [v for v in values if v is not None]
        if len(values) < max(3, len(rows[:50]) // 2):
            continue
        if all(-180 <= v <= 180 for v in values) and any(abs(v) > 0.0001 for v in values):
            geographic.append(name)
    if len(geographic) >= 2:
        first, second = geographic[0], geographic[1]
        # Latitude is the one that never leaves [-90, 90].
        firsts = [v for v in (_coordinate(r.get(first, "")) for r in rows) if v is not None]
        seconds = [v for v in (_coordinate(r.get(second, "")) for r in rows) if v is not None]
        first_fits_lat = all(-90 <= v <= 90 for v in firsts)
        second_fits_lat = all(-90 <= v <= 90 for v in seconds)
        if first_fits_lat and not second_fits_lat:
            return ColumnPick(second, first, None, 0.6, "inferred from value ranges")
        if second_fits_lat and not first_fits_lat:
            return ColumnPick(first, second, None, 0.6, "inferred from value ranges")
        # Both columns could be either. Reports overwhelmingly print latitude first, so assume
        # that, and say plainly that it was assumed: a bbox check will catch it if it is wrong.
        return ColumnPick(second, first, None, 0.45, "ambiguous ranges; assumed latitude-first order")
    return None


def crs_hint_from_text(text: str) -> str | None:
    """The first CRS-looking phrase in a document, used when the caller gives no `--crs`."""
    match = _CRS_IN_TEXT.search(text or "")
    return match.group(0).strip() if match else None


def records_from_table(
    table: Table,
    *,
    crs_hint: str | int | None = None,
    origin: str = "",
) -> tuple[list[Record], ColumnPick | None]:
    """Every row of a table that carries a usable coordinate pair."""
    pick = pick_columns(table)
    if not pick:
        return [], None

    records: list[Record] = []
    for index, row in enumerate(table.as_dicts(), 1):
        x = _coordinate(row.get(pick.lon, ""))
        y = _coordinate(row.get(pick.lat, ""))
        if x is None or y is None:
            continue
        row_hint = row.get(pick.crs) if pick.crs else None
        source = row_hint or crs_hint
        crs = crs_from_hint(source)
        if crs.is_geographic:
            point = to_wgs84(x, y, crs, accuracy_m=guess_precision_m(x, y))
        else:
            point = to_wgs84(x, y, crs)
        properties = {k: v for k, v in row.items() if k not in {pick.lon, pick.lat} and str(v).strip()}
        records.append(
            Record(
                lon=point.lon,
                lat=point.lat,
                properties=properties,
                source_crs=point.source_crs,
                transform=point.transform,
                accuracy_m=point.accuracy_m,
                confidence=round(pick.confidence * table.confidence, 3),
                page=table.page,
                origin=origin or f"table:{table.name or 'unnamed'} row {index}",
            )
        )
    return records, pick


def records_from_text(
    block: TextBlock,
    *,
    crs_hint: str | int | None = None,
) -> list[Record]:
    """Coordinate pairs written into prose, including UTM eastings and northings."""
    records: list[Record] = []
    text = block.text or ""

    for match in _PAIR.finditer(text):
        first, second = parse_dms(match.group(1)), parse_dms(match.group(2))
        if first is None or second is None:
            continue
        # Hemisphere letters settle the order; otherwise assume the report wrote lat first.
        if re.search(r"(?i)[EW]\s*$", match.group(1).strip()):
            lon, lat = first, second
        else:
            lat, lon = first, second
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        records.append(
            Record(
                lon=round(lon, 7),
                lat=round(lat, 7),
                properties={"text": match.group(0).strip()},
                accuracy_m=guess_precision_m(lon, lat),
                confidence=round(0.75 * block.confidence, 3),
                page=block.page,
                origin=f"text:page {block.page}",
            )
        )

    for match in _UTM_PAIR.finditer(text):
        zone, hemisphere, easting, northing = match.groups()
        hint = crs_hint
        if zone:
            hint = f"UTM zone {zone}{(hemisphere or 'N').upper()}"
        if hint is None:
            continue
        crs = crs_from_hint(hint)
        if crs.is_geographic:
            continue
        point = to_wgs84(float(easting), float(northing), crs, accuracy_m=1.0)
        records.append(
            Record(
                lon=point.lon,
                lat=point.lat,
                properties={"text": match.group(0).strip()},
                source_crs=point.source_crs,
                transform=point.transform,
                accuracy_m=point.accuracy_m,
                confidence=round(0.7 * block.confidence, 3),
                page=block.page,
                origin=f"text:page {block.page}",
            )
        )
    return records


def extract_records(extraction: Extraction, *, crs_hint: str | int | None = None) -> list[Record]:
    """Everything locatable in one file. Tables first, then prose."""
    hint = crs_hint or crs_hint_from_text(extraction.text())
    records: list[Record] = []
    for table in extraction.tables:
        found, _ = records_from_table(table, crs_hint=hint)
        records.extend(found)
    for block in extraction.blocks:
        records.extend(records_from_text(block, crs_hint=hint))
    return records
