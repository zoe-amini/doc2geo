"""Lines and polygons, assembled from the ways documents actually store them.

Documents almost never hand you a polygon. They hand you the corner coordinates of a licence
block, one per row, and expect you to know that the rows belong together. Or they give a
bounding box as four numbers in a catalogue field. Or, when someone has already done the work,
a WKT string in a cell.

All three routes end in a `Record` with a real geometry. The rules for turning a list of
vertices into a ring rather than a path are explicit and conservative: guessing a polygon where
the document meant a traverse invents area that was never surveyed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .crs import crs_from_hint, to_wgs84
from .records import Record, Table, TextBlock

# Column names that group rows into one shape, and that order the vertices within it.
GROUP_NAMES = (
    "block",
    "licence",
    "license",
    "polygon",
    "area",
    "claim",
    "tenement",
    "permit",
    "zone_id",
    "group",
    "feature",
    "shape",
    "line",
    "traverse",
    "section",
    "id",
)
ORDER_NAMES = ("order", "seq", "sequence", "vertex", "point_no", "corner", "node", "index", "no")
# Words in a grouping column's name that say the vertices enclose an area rather than trace a path.
AREA_WORDS = ("block", "licence", "license", "polygon", "area", "claim", "tenement", "permit", "boundary")
LINE_WORDS = ("line", "traverse", "section", "profile", "route", "track", "path")

WKT = re.compile(
    r"(?i)^\s*(POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON)\s*(Z|M|ZM)?\s*\((.*)\)\s*$",
    re.S,
)

# Packed degrees-minutes-seconds as catalogues write them: S060000, E0340000, 0213412S.
# A little punctuation is tolerated between the letter and the digits, because scanners speckle
# ("S.060000"); the letter itself is still required.
PACKED = re.compile(r"(?i)(?:([NSEW])[^0-9A-Za-z]{0,3}(\d{6,7})|(\d{6,7})[^0-9A-Za-z]{0,3}([NSEW]))\b")

# Glyphs a poor scan puts where a hemisphere letter should be. Used only by the opt-in repair,
# and only when the field's own label already fixes the axis, so the choice is between two
# hemispheres rather than four. Every repaired value is flagged in the record's properties.
HEMISPHERE_GLYPHS: dict[str, str] = {
    "$": "S",
    "§": "S",
    "5": "S",
    "8": "S",
    "£": "E",
    "K": "E",
    "#": "E",
    "H": "E",
    "€": "E",
}
NOISY_PACKED = re.compile(r"([^\s0-9A-Za-z]|[0-9A-Za-z])[^0-9A-Za-z]{0,2}(\d{6,7})\b")
# "Latitude: S060000 ; S030000" / "Longitude: E0340000 ; E0390000".
# The label tolerates the space OCR likes to insert mid-word ("Longi tude"), and the value run
# is tempered so it swallows the `;` between values but stops at the next label.
LABELLED = re.compile(
    r"""(?ix)
    \b(lat\s*(?:i\s*tude)?|long?\s*(?:i\s*tude)?)\s*[:.]?\s*
    ((?:(?!\blat\s*(?:i\s*tude)?\b|\blong?\s*(?:i\s*tude)?\b)[^\n]){0,80})
    """
)

MIN_RING_VERTICES = 3


@dataclass
class Group:
    """Rows that belong to one shape, in the order the document gave them."""

    key: str
    coordinates: list[list[float]]
    properties: dict[str, Any]
    closed_by_source: bool = False


def parse_packed_dms(
    text: str,
    *,
    axis: str | None = None,
    repair: bool = False,
    assume_hemisphere: str | None = None,
) -> float | None:
    """Parse S060000 or 0213412S into decimal degrees.

    Six digits are DDMMSS, seven are DDDMMSS (longitudes past 99°). A hemisphere letter is
    required: without one there is no way to know the sign, and assuming north-east silently
    puts African data in Kazakhstan.

    `repair` accepts a glyph a bad scan left in the hemisphere's place ("$060000", "5030000"),
    but only when `axis` says which pair of hemispheres is even possible. It is off by default:
    a misread sign is the one error that moves a point to another continent without looking
    wrong. Callers that switch it on should expect to explain themselves, which is why every
    repaired record is flagged.

    `assume_hemisphere` supplies the letter from a legible sibling in the same field. Both
    longitudes of one bounding box share a hemisphere unless the box straddles the meridian,
    which makes the sibling a far better source than guessing at a glyph.
    """
    if not text:
        return None
    raw = str(text)
    match = PACKED.search(raw)
    hemisphere = ""
    digits = ""
    if match:
        hemisphere = (match.group(1) or match.group(4) or "").upper()
        digits = match.group(2) or match.group(3) or ""
    elif repair and axis:
        noisy = NOISY_PACKED.search(raw)
        if noisy:
            wanted = ("N", "S") if axis == "lat" else ("E", "W")
            candidate = HEMISPHERE_GLYPHS.get(noisy.group(1).upper())
            if candidate not in wanted and assume_hemisphere in wanted:
                candidate = assume_hemisphere
            if candidate in wanted:
                hemisphere, digits = candidate, noisy.group(2)
        elif assume_hemisphere in (("N", "S") if axis == "lat" else ("E", "W")):
            bare = re.search(r"\b(\d{6,7})\b", raw)
            if bare:
                hemisphere, digits = assume_hemisphere, bare.group(1)
    if not hemisphere or len(digits) not in (6, 7):
        return None
    split = len(digits) - 4
    degrees, minutes, seconds = int(digits[:split]), int(digits[split : split + 2]), int(digits[split + 2 :])
    if minutes >= 60 or seconds >= 60:
        return None
    value = degrees + minutes / 60 + seconds / 3600
    if hemisphere in ("S", "W"):
        value = -value
    limit = 90 if hemisphere in ("N", "S") else 180
    return round(value, 7) if abs(value) <= limit else None


def _coordinate_list(body: str) -> list[list[float]]:
    points = []
    for chunk in body.split(","):
        parts = chunk.replace("(", " ").replace(")", " ").split()
        if len(parts) >= 2:
            try:
                points.append([float(parts[0]), float(parts[1])])
            except ValueError:
                return []
    return points


def parse_wkt(text: str) -> dict[str, Any] | None:
    """A small WKT reader for the shapes that turn up in spreadsheet cells.

    Deliberately not shapely: the core install stays dependency-free, and a cell holding
    `POLYGON((...))` needs reading, not topology.
    """
    match = WKT.match(str(text or ""))
    if not match:
        return None
    kind = match.group(1).upper()
    body = match.group(3).strip()

    if kind == "POINT":
        points = _coordinate_list(body)
        return {"type": "Point", "coordinates": points[0]} if len(points) == 1 else None
    if kind == "LINESTRING":
        points = _coordinate_list(body)
        return {"type": "LineString", "coordinates": points} if len(points) >= 2 else None
    if kind == "MULTIPOINT":
        points = _coordinate_list(body)
        return {"type": "MultiPoint", "coordinates": points} if points else None
    if kind == "POLYGON":
        rings = [_coordinate_list(r) for r in re.findall(r"\(([^()]*)\)", body)]
        rings = [r for r in rings if len(r) >= MIN_RING_VERTICES]
        if not rings:
            return None
        for ring in rings:
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
        return {"type": "Polygon", "coordinates": rings}
    if kind == "MULTILINESTRING":
        parts = [_coordinate_list(r) for r in re.findall(r"\(([^()]*)\)", body)]
        parts = [p for p in parts if len(p) >= 2]
        return {"type": "MultiLineString", "coordinates": parts} if parts else None
    if kind == "MULTIPOLYGON":
        polygons = []
        for block in re.findall(r"\(\s*(\([^()]*\)(?:\s*,\s*\([^()]*\))*)\s*\)", body):
            rings = [_coordinate_list(r) for r in re.findall(r"\(([^()]*)\)", block)]
            rings = [r for r in rings if len(r) >= MIN_RING_VERTICES]
            for ring in rings:
                if ring[0] != ring[-1]:
                    ring.append(list(ring[0]))
            if rings:
                polygons.append(rings)
        return {"type": "MultiPolygon", "coordinates": polygons} if polygons else None
    return None


def records_from_wkt_table(table: Table, *, crs_hint: str | int | None = None) -> list[Record]:
    """Rows whose cells already hold WKT geometry."""
    rows = table.as_dicts()
    if not rows:
        return []
    column = next(
        (name for name in rows[0] if any(parse_wkt(row.get(name, "")) for row in rows[:5])),
        None,
    )
    if column is None:
        return []

    crs = crs_from_hint(crs_hint)
    records: list[Record] = []
    for index, row in enumerate(rows, 1):
        geometry = parse_wkt(row.get(column, ""))
        if not geometry:
            continue
        if crs.to_epsg() != 4326:
            geometry = _reproject(geometry, crs)
        properties = {k: v for k, v in row.items() if k != column and str(v).strip()}
        records.append(
            Record(
                geometry=geometry,
                properties=properties,
                source_crs=crs.name if crs.name != "undefined" else str(crs_hint or "WGS 84"),
                transform="WKT read from the document" if crs.to_epsg() == 4326 else "reprojected to WGS84",
                confidence=0.95,
                page=table.page,
                origin=f"wkt:{table.name or 'unnamed'} row {index}",
            )
        )
    return records


def _reproject(geometry: dict[str, Any], crs) -> dict[str, Any]:  # noqa: ANN001  pyproj CRS
    def convert(node: Any) -> Any:
        if isinstance(node, list) and len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
            point = to_wgs84(float(node[0]), float(node[1]), crs)
            return [point.lon, point.lat]
        return [convert(child) for child in node]

    return {"type": geometry["type"], "coordinates": convert(geometry["coordinates"])}


def _shape_kind(group_column: str, explicit: str | None) -> str:
    """polygon, line, or unknown — from a `type` column if there is one, else the group name."""
    if explicit:
        low = explicit.strip().lower()
        if any(w in low for w in ("polygon", "area", "block", "boundary", "ring")):
            return "polygon"
        if any(w in low for w in ("line", "linestring", "traverse", "path", "route")):
            return "line"
    low = group_column.lower()
    if any(w in low for w in AREA_WORDS):
        return "polygon"
    if any(w in low for w in LINE_WORDS):
        return "line"
    return "unknown"


def group_vertices(
    table: Table,
    lon_column: str,
    lat_column: str,
    *,
    group_column: str,
    order_column: str | None = None,
    type_column: str | None = None,
) -> list[Group]:
    """Collect rows into shapes by their grouping column, ordered by `order_column` if present."""
    groups: dict[str, Group] = {}
    for position, row in enumerate(table.as_dicts()):
        key = str(row.get(group_column, "")).strip()
        if not key:
            continue
        try:
            lon = float(str(row[lon_column]).replace(",", "."))
            lat = float(str(row[lat_column]).replace(",", "."))
        except (KeyError, ValueError):
            continue
        if key not in groups:
            shared = {
                k: v
                for k, v in row.items()
                if k not in (lon_column, lat_column, order_column) and str(v).strip()
            }
            groups[key] = Group(key=key, coordinates=[], properties=shared)
        sort_key: float = position
        if order_column:
            try:
                sort_key = float(str(row.get(order_column, position)).replace(",", "."))
            except ValueError:
                sort_key = position
        groups[key].coordinates.append([lon, lat, sort_key])

    ordered: list[Group] = []
    for group in groups.values():
        group.coordinates.sort(key=lambda c: c[2])
        points = [[c[0], c[1]] for c in group.coordinates]
        group.closed_by_source = len(points) > 2 and points[0] == points[-1]
        group.coordinates = points
        ordered.append(group)
    return ordered


def records_from_groups(
    groups: list[Group],
    *,
    kind: str,
    crs_hint: str | int | None = None,
    page: int = 1,
    table_name: str = "",
) -> list[Record]:
    """Turn grouped vertices into polygons, lines or points.

    A group becomes a polygon when the document says so — the source closed the ring, or the
    grouping column is named for an area. Otherwise it stays a line, because inventing a
    closing edge invents area that was never surveyed.
    """
    crs = crs_from_hint(crs_hint)
    reproject = crs.to_epsg() != 4326
    records: list[Record] = []

    for group in groups:
        points = group.coordinates
        if reproject:
            points = [[p.lon, p.lat] for p in (to_wgs84(x, y, crs) for x, y in points)]
        shared = dict(
            properties={**group.properties, "group": group.key},
            source_crs=crs.name if crs.name != "undefined" else "WGS 84",
            transform="reprojected to WGS84" if reproject else "none",
            confidence=0.9,
            page=page,
            origin=f"group:{table_name or 'unnamed'}/{group.key}",
        )

        wants_area = kind == "polygon" or group.closed_by_source
        if wants_area and len(points) >= MIN_RING_VERTICES:
            ring = points[:-1] if group.closed_by_source else points
            if len(ring) >= MIN_RING_VERTICES:
                records.append(Record.polygon(ring, **shared))
                continue
        if len(points) >= 2:
            records.append(Record.line(points, **shared))
        elif len(points) == 1:
            records.append(Record.point(points[0][0], points[0][1], **shared))
    return records


def bbox_from_text(block: TextBlock, *, repair: bool = False) -> list[Record]:
    """Bounding boxes written as labelled latitude and longitude pairs.

    Catalogue records state an extent as two latitudes and two longitudes in packed DMS
    (`Latitude: S060000 ; S030000  Longitude: E0340000 ; E0390000`). That is a polygon, and
    reducing it to a point would throw away the extent the cataloguer bothered to record.
    """
    text = block.text or ""
    buckets: list[dict[str, Any]] = []
    current: dict[str, Any] = {"lat": [], "lon": [], "unreadable": 0}

    for match in LABELLED.finditer(text):
        axis = "lat" if match.group(1).lower().replace(" ", "").startswith("lat") else "lon"
        # A latitude label on a bucket that already has both axes starts the next record.
        if axis == "lat" and current["lat"] and current["lon"]:
            buckets.append(current)
            current = {"lat": [], "lon": [], "unreadable": 0}
        limit = 90 if axis == "lat" else 180
        tokens = [t for t in re.split(r"[;,]", match.group(2)) if t.strip()]
        parsed: list[float | None] = [parse_packed_dms(t, axis=axis, repair=repair) for t in tokens]

        if repair and any(v is None for v in parsed) and any(v is not None for v in parsed):
            # A legible value in the same field names the hemisphere for its neighbours.
            readable = next(v for v in parsed if v is not None)
            sibling = ("S" if readable < 0 else "N") if axis == "lat" else ("W" if readable < 0 else "E")
            parsed = [
                value
                if value is not None
                else parse_packed_dms(token, axis=axis, repair=True, assume_hemisphere=sibling)
                for token, value in zip(tokens, parsed, strict=True)
            ]

        for token, value in zip(tokens, parsed, strict=True):
            if value is None:
                if re.search(r"\d{6,7}", token):
                    current["unreadable"] += 1
            elif -limit <= value <= limit:
                current[axis].append(value)
    buckets.append(current)

    records: list[Record] = []
    for bucket in buckets:
        latitudes, longitudes = bucket["lat"], bucket["lon"]
        if len(latitudes) < 2 or len(longitudes) < 2:
            continue
        south, north = min(latitudes), max(latitudes)
        west, east = min(longitudes), max(longitudes)
        if south == north or west == east:
            continue
        records.append(_bbox_record(block, south, north, west, east, repair, bucket["unreadable"]))
    return records


def _bbox_record(
    block: TextBlock,
    south: float,
    north: float,
    west: float,
    east: float,
    repair: bool,
    unreadable: int,
) -> Record:
    ring = [[west, south], [east, south], [east, north], [west, north]]
    properties: dict[str, Any] = {"extent": f"{south}/{north} {west}/{east}"}
    confidence = 0.7 * block.confidence
    if repair:
        properties["ocr_repair_enabled"] = True
        confidence *= 0.7
    if unreadable:
        properties["unreadable_values"] = unreadable
    return Record.polygon(
        ring,
        properties=properties,
        confidence=round(confidence, 3),
        page=block.page,
        origin=f"bbox:page {block.page}",
    )
