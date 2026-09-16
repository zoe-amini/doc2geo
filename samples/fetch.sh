#!/usr/bin/env bash
# Fetch the public documents the `samples` tests run against.
#
# These are third-party publications. They are downloaded here for testing and are deliberately
# not committed to this repository: this code is MIT, their contents are not ours to relicense.
set -euo pipefail
cd "$(dirname "$0")"

fetch() {
  local name="$1" url="$2"
  if [[ -f "$name" ]]; then
    echo "have  $name"
    return
  fi
  echo "fetch $name"
  curl -fsSL --max-time 300 -o "$name" "$url"
}

# FAO, Soil Survey of Botswana (text volume: prose and profile description forms, no map sheets).
fetch fao_BWA_4.pdf          "https://www.fao.org/fileadmin/user_upload/soils/import_pdf/BWA_4.pdf"
# JICA, born-digital report with an A3 colour map on page 3 and figure maps throughout.
fetch jica_12301594_01.pdf   "https://openjicareport.jica.go.jp/pdf/12301594_01.pdf"
# JICA, scanned GEOREF bibliography: coordinates in the text, no maps.
fetch jica_10891885_04.pdf   "https://openjicareport.jica.go.jp/pdf/10891885_04.pdf"
# USGS Circum-Pacific: monochrome projected map sheets with graticule labels in the text layer.
fetch usgs_cp46.pdf          "https://pubs.usgs.gov/cp/46/report.pdf"

echo "done"
