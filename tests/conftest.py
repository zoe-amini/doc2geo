from __future__ import annotations

import csv
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def pytest_configure(config):
    config.addinivalue_line("markers", "samples: needs the sample documents from samples/fetch.sh")


@pytest.fixture
def sample_pdf():
    """Path to a downloaded sample, or skip. Samples are not redistributed with the package."""

    def _get(name: str) -> Path:
        path = SAMPLES / name
        if not path.is_file():
            pytest.skip(f"{name} not present; run samples/fetch.sh")
        return path

    return _get


@pytest.fixture
def points_csv(tmp_path) -> Path:
    path = tmp_path / "points.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["site_id", "name", "longitude", "latitude", "grade_gt"])
        writer.writerow(["S1", "Mmadinare", "27.1234", "-21.8765", "1.4"])
        writer.writerow(["S2", "Selebi", "27.8", "-21.97", "0.8"])
        writer.writerow(["S3", "Tati", "27.5432", "-21.1", "2.1"])
    return path


@pytest.fixture
def dms_csv(tmp_path) -> Path:
    path = tmp_path / "dms.csv"
    path.write_text(
        "hole,lat,lon\nBH-1,21°34'12\"S,25°12'03\"E\nBH-2,21°35'00\"S,25°13'30\"E\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def utm_csv(tmp_path) -> Path:
    """Eastings and northings with no CRS column: the caller must supply --crs."""
    path = tmp_path / "utm.csv"
    path.write_text(
        "hole,easting,northing\nBH-1,512345,7612345\nBH-2,513000,7613000\n",
        encoding="utf-8",
    )
    return path
