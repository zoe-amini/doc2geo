"""The shapes that travel between a reader, the detector, and a writer.

A reader's job is to turn any input file into `Table`s and `TextBlock`s without knowing
anything about geography. The detector's job is to turn those into `Record`s. Writers only
ever see `Record`s. Adding a new input format means adding a reader and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TextBlock:
    """A run of text with enough provenance to point a reviewer back at the page."""

    text: str
    page: int = 1
    kind: str = "text"  # text | table | figure | map | stamp | handwriting
    confidence: float = 1.0
    backend: str = "native"
    bbox: list[float] | None = None


@dataclass
class Table:
    """A rectangular block. `header` may be empty when a reader cannot tell."""

    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    page: int = 1
    name: str = ""
    confidence: float = 1.0
    backend: str = "native"

    def as_dicts(self) -> list[dict[str, str]]:
        """Rows keyed by header, with blank or duplicate headers given positional names."""
        names: list[str] = []
        for i, raw in enumerate(self.header):
            name = (raw or "").strip() or f"col_{i + 1}"
            if name in names:
                name = f"{name}_{i + 1}"
            names.append(name)
        out = []
        for row in self.rows:
            padded = list(row) + [""] * (len(names) - len(row))
            out.append({names[i]: padded[i] for i in range(len(names))})
        return out


@dataclass
class Extraction:
    """Everything one reader pulled out of one file."""

    source: Path
    tables: list[Table] = field(default_factory=list)
    blocks: list[TextBlock] = field(default_factory=list)
    pages: int = 0
    backend: str = "native"
    note: str = ""

    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.kind in ("text", "handwriting"))

    def low_confidence(self, threshold: float = 0.8) -> list[TextBlock]:
        """Blocks a human should look at before the output is trusted."""
        return [b for b in self.blocks if b.confidence < threshold]


@dataclass
class Record:
    """One located thing, in WGS84, with its provenance intact.

    `geometry` is a GeoJSON geometry dict, so a record is a point, a line or a polygon without
    the rest of the pipeline caring which. Use `Record.point()` for the common case.
    """

    geometry: dict[str, Any]
    properties: dict[str, Any] = field(default_factory=dict)
    source_crs: str = "WGS 84"
    transform: str = "none"
    accuracy_m: float | None = None
    confidence: float = 1.0
    page: int = 1
    origin: str = ""  # "table:Appendix B row 12" or "text:page 4"

    @classmethod
    def point(cls, lon: float, lat: float, **kwargs: Any) -> Record:
        return cls(geometry={"type": "Point", "coordinates": [lon, lat]}, **kwargs)

    @classmethod
    def line(cls, coordinates: Sequence[Sequence[float]], **kwargs: Any) -> Record:
        return cls(geometry={"type": "LineString", "coordinates": [list(c) for c in coordinates]}, **kwargs)

    @classmethod
    def polygon(cls, ring: Sequence[Sequence[float]], **kwargs: Any) -> Record:
        """A single-ring polygon. The ring is closed here if the source did not close it."""
        closed = [list(c) for c in ring]
        if closed and closed[0] != closed[-1]:
            closed.append(list(closed[0]))
        return cls(geometry={"type": "Polygon", "coordinates": [closed]}, **kwargs)

    @property
    def geom_type(self) -> str:
        return str(self.geometry.get("type", "")) if self.geometry else ""

    @property
    def lon(self) -> float | None:
        """Longitude for a point; None for anything else."""
        return self.geometry["coordinates"][0] if self.geom_type == "Point" else None

    @property
    def lat(self) -> float | None:
        return self.geometry["coordinates"][1] if self.geom_type == "Point" else None

    def vertices(self) -> list[tuple[float, float]]:
        """Every coordinate in the geometry, flattened, for range and bounds checking."""
        out: list[tuple[float, float]] = []

        def walk(node: Any) -> None:
            if (
                isinstance(node, (list, tuple))
                and len(node) >= 2
                and all(isinstance(v, (int, float)) for v in node[:2])
            ):
                out.append((float(node[0]), float(node[1])))
                return
            if isinstance(node, (list, tuple)):
                for child in node:
                    walk(child)

        walk(self.geometry.get("coordinates", []))
        return out

    def centroid(self) -> tuple[float, float] | None:
        """Mean of the vertices. Good enough to ask "is this in the right country?"."""
        points = self.vertices()
        if not points:
            return None
        return (
            round(sum(p[0] for p in points) / len(points), 7),
            round(sum(p[1] for p in points) / len(points), 7),
        )

    def to_feature(self) -> dict[str, Any]:
        """GeoJSON Feature. Provenance rides along under `_doc2geo` so it survives a round trip."""
        properties = dict(self.properties)
        properties["_doc2geo"] = {
            "source_crs": self.source_crs,
            "transform": self.transform,
            "accuracy_m": self.accuracy_m,
            "confidence": round(self.confidence, 3),
            "page": self.page,
            "origin": self.origin,
        }
        return {"type": "Feature", "geometry": self.geometry, "properties": properties}
