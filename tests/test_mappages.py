"""Map-page detection, including against the real reports when they have been fetched."""

from __future__ import annotations

import pytest

from doc2geo.graticule import georeference_page, ticks_from_tokens
from doc2geo.mappages import PageSignals, score_page


def signals(**kwargs) -> PageSignals:
    base = dict(
        page=1,
        width=595,
        height=842,
        chars=3000,
        graticule_labels=0,
        carto_words=0,
        images=0,
        largest_image_bytes=0,
        landscape=False,
        oversized=False,
        sparse_text=False,
    )
    base.update(kwargs)
    return PageSignals(**base)


def test_body_text_page_scores_low():
    score, _ = score_page(signals())
    assert score == 0.0


def test_graticule_labels_dominate():
    score, reasons = score_page(signals(graticule_labels=9, chars=300, sparse_text=True))
    assert score >= 0.5
    assert any("graticule" in r for r in reasons)


def test_colour_map_is_detected_without_any_text():
    score, reasons = score_page(signals(chars=0, sparse_text=True, chroma=0.31, colours=117, ink=0.44))
    assert score >= 0.5
    assert any("polychrome" in r for r in reasons)


def test_a_colourful_page_of_prose_is_not_a_map():
    """Text pages stay below the line even when they carry a logo or a coloured header."""
    score, _ = score_page(signals(chars=4000, chroma=0.02, colours=12, ink=0.42))
    assert score < 0.5


def test_ticks_skip_merged_tokens():
    """A token holding a whole row of labels has lost their individual positions."""
    ticks = ticks_from_tokens([(346.7, 527.9, "100°E"), (382.0, 527.9, "120°E 140°E 160°E 180°")])
    assert len(ticks) == 1
    assert ticks[0].axis == "lon"
    assert ticks[0].value == 100


def test_georeference_refuses_without_enough_ticks():
    result = georeference_page([(10.0, 20.0, "100°E"), (10.0, 40.0, "10°N")])
    assert not result.fitted
    assert "at least two" in result.note


def test_georeference_fits_a_plate_carree_grid():
    tokens = [
        (100.0, 500.0, "20°E"),
        (300.0, 500.0, "24°E"),
        (50.0, 200.0, "22°S"),
        (50.0, 400.0, "18°S"),
    ]
    result = georeference_page(tokens)
    assert result.fitted
    assert result.residual_deg == 0


def test_georeference_refuses_a_projected_sheet():
    """Unequal paper distance for equal degree steps means the sheet is not plate carree."""
    tokens = [
        (100.0, 500.0, "20°E"),
        (300.0, 500.0, "24°E"),
        (50.0, 180.0, "10°S"),
        (50.0, 283.5, "10°N"),
        (50.0, 326.3, "20°N"),
    ]
    result = georeference_page(tokens)
    assert not result.fitted
    assert result.residual_deg > 0.05
    assert "projected" in result.note
    assert len(result.control_points) == 5


@pytest.mark.samples
def test_finds_the_map_page_in_the_usgs_report(sample_pdf):
    from doc2geo.mappages import find_map_pages

    pages = find_map_pages(sample_pdf("usgs_cp46.pdf"))
    assert 12 in [p.page for p in pages]


@pytest.mark.samples
def test_ignores_a_scanned_report_that_has_no_maps(sample_pdf):
    """FAO BWA_4 is the soil survey's text volume: prose and profile forms, no map sheets."""
    from doc2geo.mappages import find_map_pages

    assert find_map_pages(sample_pdf("fao_BWA_4.pdf")) == []
