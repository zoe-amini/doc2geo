#!/usr/bin/env bash
# Regenerate samples/outputs/ from the documents in samples/.
#
# Everything under outputs/ is produced by these commands and nothing else, so the files in the
# repository are exactly what the tool writes today. Rerun after changing the extractor.
set -euo pipefail
cd "$(dirname "$0")/.."

out=samples/outputs
rm -rf "$out"
mkdir -p "$out"
run() { echo "+ doc2geo $*"; uv run doc2geo "$@"; echo; }

# A scanned bibliography with no text layer: OCR, then packed-DMS extents per record.
# The same records, written to three formats, so each can be opened and compared.
run convert samples/jica_10891885_04.pdf --ocr-repair --max-pages 40 \
    -o "$out/jica_10891885_04.extents.geojson"
run convert samples/jica_10891885_04.pdf --ocr-repair --max-pages 40 \
    -o "$out/jica_10891885_04.extents.gpkg"
run convert samples/jica_10891885_04.pdf --ocr-repair --max-pages 40 \
    -o "$out/jica_10891885_04.extents.shp"
run convert samples/jica_10891885_04.pdf --ocr-repair --max-pages 40 \
    -o "$out/jica_10891885_04.extents.csv"

# A scanned soil survey: prose and profile forms, and whatever is locatable in them.
run convert samples/fao_BWA_4.pdf --max-pages 40 --bbox 19.9,-26.95,29.4,-17.75 \
    -o "$out/fao_BWA_4.points.geojson" || true

# Born-digital reports: which pages are maps, and what the graticule says about them.
run maps samples/jica_12301594_01.pdf --list-only --json > /dev/null
uv run doc2geo maps samples/jica_12301594_01.pdf --list-only --json \
    > "$out/jica_12301594_01.map-pages.json"
uv run doc2geo maps samples/usgs_cp46.pdf --list-only --georeference --json \
    > "$out/usgs_cp46.map-pages.json"
uv run doc2geo maps samples/tender_naming_pattern.pdf --list-only --json \
    > "$out/tender_naming_pattern.map-pages.json"

# Licence corner coordinates: the worked example from the README, as a real file.
cat > "$out/../licence_corners.csv" <<'CSV'
licence,corner,lon,lat
PL-142,1,25.10,-21.05
PL-142,2,25.60,-21.05
PL-142,3,25.60,-21.45
PL-142,4,25.10,-21.45
PL-143,1,25.70,-21.10
PL-143,2,26.15,-21.10
PL-143,3,26.15,-21.55
PL-143,4,25.70,-21.55
CSV
run convert samples/licence_corners.csv -o "$out/licence_corners.blocks.geojson"
run convert samples/licence_corners.csv -o "$out/licence_corners.blocks.shp"

echo "wrote:"
ls -la "$out"
