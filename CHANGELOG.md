# Changelog

## 0.3.0 — 2026-09-16

First release published to PyPI. 0.1.0 and 0.2.0 exist in the git history but were never
published, so everything below is new to anyone installing this.

### Extracting coordinates

- Reads `.csv`, `.tsv`, `.xlsx`, `.xlsm`, `.docx`, `.pdf` and images.
- Finds coordinate columns by name (`longitude`, `easting`, `lat`, `utm_n`, …) or, where the
  headers are useless, by the shape of the values. Ambiguity is reported at lower confidence
  rather than resolved by a coin flip.
- Reads the spellings documents actually use: `21°34'12"S`, `-21.5701`, `21,5701 S`,
  `zone 34S 512345 mE 7612345 mN`, and packed DMS such as `S060000` / `E0340000`.
- A datum named in the document (`Arc 1950 / UTM zone 34S`) composes the projected CRS on that
  datum, so the EPSG datum shift is applied instead of the numbers being treated as WGS84.
- Every record carries its source CRS, the transformation used, an accuracy estimate derived
  from the decimals the document actually printed, and a confidence.

### Geometry

- Points, lines and polygons through one pipeline.
- WKT in a cell is read directly.
- Rows of vertices grouped by a `licence`, `block`, `claim` or `tenement` column become
  polygons; rows grouped by a `line`, `traverse` or `section` column stay LineStrings. Closing a
  survey path would invent area nobody surveyed, so it is not done.
- A `corner`, `seq` or `order` column sets vertex order. Open rings are closed.
- Catalogue bounding boxes (`Latitude: S060000 ; S030000  Longitude: E0340000 ; E0390000`)
  become polygons, one per record.

### Map pages

- `doc2geo maps` scores every page of a PDF and extracts the ones that are maps, weighing
  graticule labels, cartographic vocabulary, page geometry against the document's norm, text
  density, embedded image count and — after a cheap 40 dpi render — how polychrome the page is.
  The reasons behind each score are printed.
- `--georeference` fits a north-up affine from graticule tick labels and writes a world file and
  `.prj`, but only when the residuals justify it. A projected sheet is not affine in page space,
  so the control points are handed back instead of a transform nobody checked.

### OCR

- Tesseract locally, or any service that accepts a multipart upload, via `DOC2GEO_OCR_URL`.
- Line structure is preserved, so records on separate lines stay separate.
- Bad scans lose hemisphere letters. Those values are dropped by default. `--ocr-repair` accepts
  a glyph standing in for the letter, or takes the hemisphere from a legible sibling in the same
  field — flagged in the output, at reduced confidence, and never inventing digits.

### Output

- GeoJSON and CSV with no dependencies beyond the core install.
- Shapefile, GeoPackage, FlatGeobuf, GML and KML through the `gdal` extra, which is `pyogrio`
  and `numpy` — geometry is encoded to WKB in-package, so there is no geopandas or shapely.
- Shapefile field names are truncated to ten characters and kept unique; mixed geometry types
  are refused with a message naming them.
- Checks report and never edit: out-of-range coordinates, unclosed or degenerate rings, null
  island, coarse precision, duplicates, and — with `--bbox` — the lon/lat column swap that is
  the most common failure in hand-built coordinate tables.
