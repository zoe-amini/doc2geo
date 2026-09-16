from __future__ import annotations

import json

import pytest

from doc2geo.checks import check_records
from doc2geo.detect import extract_records
from doc2geo.readers import UnsupportedInput, read
from doc2geo.records import Record
from doc2geo.writers import WriteError, write, write_csv, write_geojson

BOTSWANA = (19.9, -26.95, 29.4, -17.75)


def test_reader_rejects_legacy_formats(tmp_path):
    legacy = tmp_path / "old.xls"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(UnsupportedInput, match="re-save as .xlsx"):
        read(legacy)


def test_reader_rejects_unknown_formats(tmp_path):
    other = tmp_path / "notes.rtf"
    other.write_text("hello")
    with pytest.raises(UnsupportedInput):
        read(other)


def test_excel_round_trip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "sites.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "collars"
    sheet.append(["hole", "lon", "lat"])
    sheet.append(["BH-1", 25.2008, -21.5700])
    sheet.append(["BH-2", 25.2250, -21.5833])
    workbook.save(path)

    records = extract_records(read(path))
    assert len(records) == 2
    assert records[0].properties["hole"] == "BH-1"


def test_docx_tables_and_prose(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "report.docx"
    document = docx.Document()
    document.add_paragraph("The anomaly centres on 21°34'12\"S, 25°12'03\"E.")
    table = document.add_table(rows=2, cols=3)
    for column, value in enumerate(["hole", "lon", "lat"]):
        table.cell(0, column).text = value
    for column, value in enumerate(["BH-9", "25.30", "-21.44"]):
        table.cell(1, column).text = value
    document.save(path)

    extraction = read(path)
    assert extraction.tables and extraction.blocks
    records = extract_records(extraction)
    assert len(records) == 2


def test_geojson_output_is_valid_and_keeps_provenance(tmp_path, points_csv):
    records = extract_records(read(points_csv))
    out = write_geojson(records, tmp_path / "out.geojson")
    payload = json.loads(out.read_text())
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 3
    first = payload["features"][0]
    assert first["geometry"]["type"] == "Point"
    assert first["properties"]["_doc2geo"]["source_crs"]


def test_csv_output_has_a_stable_header(tmp_path, points_csv):
    records = extract_records(read(points_csv))
    out = write_csv(records, tmp_path / "out.csv")
    header = out.read_text().splitlines()[0]
    assert header.startswith("lon,lat,")
    assert "confidence" in header


def test_write_rejects_unknown_extension(tmp_path):
    with pytest.raises(WriteError):
        write([], tmp_path / "out.dxf")


def test_checks_flag_swapped_columns():
    swapped = [Record(lon=-21.87, lat=27.12), Record(lon=-21.97, lat=27.80), Record(lon=-21.10, lat=27.54)]
    report = check_records(swapped, bbox=BOTSWANA)
    assert any(f.check == "lon-lat-swapped" for f in report.findings)
    assert any(f.check == "systematic-swap" for f in report.findings)


def test_checks_pass_clean_records(points_csv):
    records = extract_records(read(points_csv))
    report = check_records(records, bbox=BOTSWANA)
    assert report.errors == 0


def test_checks_flag_null_island():
    report = check_records([Record(lon=0.0, lat=0.0)])
    assert any(f.check == "null-island" for f in report.findings)
