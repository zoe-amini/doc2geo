"""Sanity checks on extracted records.

Every check reports; none of them edits. A document that says a borehole is in the Atlantic
is telling you something about the document, and silently moving the point would destroy that
evidence. Fixing is the caller's decision, made with the findings in hand.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .records import Record


@dataclass
class Finding:
    level: str  # error | warn | info
    check: str
    message: str
    index: int | None = None


@dataclass
class CheckReport:
    n: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.level == "warn")

    def summary(self) -> dict[str, Any]:
        return {
            "records": self.n,
            "errors": self.errors,
            "warnings": self.warnings,
            "by_check": dict(Counter(f.check for f in self.findings)),
        }


def check_records(
    records: list[Record],
    *,
    bbox: tuple[float, float, float, float] | None = None,
    precision_warn_m: float = 1000.0,
    low_confidence: float = 0.7,
) -> CheckReport:
    """Range, ring closure, duplication, precision and (optionally) an expected bounding box.

    `bbox` is (min_lon, min_lat, max_lon, max_lat). When given, points outside it are errors,
    and a point that would fall inside it with lon and lat exchanged is flagged as a likely
    column swap — the single most common failure in hand-built coordinate tables.
    """
    report = CheckReport(n=len(records))
    seen: Counter[tuple[float, float]] = Counter()
    swapped = 0

    for index, record in enumerate(records):
        vertices = record.vertices()
        if not vertices:
            report.findings.append(Finding("error", "empty-geometry", "record has no coordinates", index))
            continue

        out_of_range = [(x, y) for x, y in vertices if not (-180 <= x <= 180 and -90 <= y <= 90)]
        if out_of_range:
            first = out_of_range[0]
            report.findings.append(
                Finding(
                    "error",
                    "out-of-range",
                    f"{first[0]}, {first[1]} is not a geographic coordinate"
                    + (f" ({len(out_of_range)} of {len(vertices)} vertices)" if len(vertices) > 1 else ""),
                    index,
                )
            )
            continue

        if record.geom_type == "Polygon":
            for ring in record.geometry.get("coordinates", []):
                if len(ring) < 4:
                    report.findings.append(
                        Finding(
                            "error",
                            "degenerate-ring",
                            f"ring has {len(ring)} points; a polygon needs 4",
                            index,
                        )
                    )
                elif ring[0] != ring[-1]:
                    report.findings.append(Finding("error", "unclosed-ring", "ring does not close", index))
        if record.geom_type == "LineString" and len(vertices) < 2:
            report.findings.append(Finding("error", "degenerate-line", "a line needs two points", index))

        centre = record.centroid()
        if centre is None:
            continue
        lon, lat = centre
        if lon == 0 and lat == 0:
            report.findings.append(
                Finding("warn", "null-island", "0, 0 is almost always a parse failure", index)
            )

        if bbox:
            inside = bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]
            if not inside:
                if bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
                    swapped += 1
                    report.findings.append(
                        Finding(
                            "warn", "lon-lat-swapped", f"{lon}, {lat} fits the area only if swapped", index
                        )
                    )
                else:
                    report.findings.append(
                        Finding(
                            "error", "outside-area", f"{lon}, {lat} falls outside the expected area", index
                        )
                    )

        if record.accuracy_m is not None and record.accuracy_m > precision_warn_m:
            report.findings.append(
                Finding(
                    "warn",
                    "coarse-precision",
                    f"rounded to about {record.accuracy_m:.0f} m by the source document",
                    index,
                )
            )
        if record.confidence < low_confidence:
            report.findings.append(
                Finding(
                    "info", "low-confidence", f"confidence {record.confidence:.2f}; review before use", index
                )
            )
        if record.geom_type == "Point":
            seen[(round(lon, 6), round(lat, 6))] += 1

    for (lon, lat), count in seen.items():
        if count > 1:
            report.findings.append(Finding("info", "duplicate-point", f"{count} records share {lon}, {lat}"))

    if swapped and swapped > max(2, len(records) * 0.2):
        report.findings.append(
            Finding("error", "systematic-swap", f"{swapped} records look swapped: check the column mapping")
        )
    return report
