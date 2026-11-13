"""Tests for display formatting by locale: the dashboard (es) and Gate 3 citations (es | en)."""
import pytest

from src.predict360 import dashboard_render
from src.predict360.formatting import format_cop_m, format_figure, format_pct


@pytest.mark.parametrize("value,locale,expected", [
    (58800.0, "es", "COP 58.800 M"),
    (58800.0, "en", "COP 58,800 M"),
    (168.333333, "es", "COP 168,3 M"),
    (168.333333, "en", "COP 168.3 M"),
    (-92.24, "en", "COP -92.2 M"),
    (None, "en", "—"),
])
def test_cop_millions_by_locale(value, locale, expected):
    assert format_cop_m(value, locale) == expected


@pytest.mark.parametrize("value,locale,expected", [(0.279, "es", "27,9 %"), (0.279, "en", "27.9%")])
def test_percent_by_locale(value, locale, expected):
    assert format_pct(value, locale) == expected


@pytest.mark.parametrize("value,unit,locale,expected", [
    (58800.0, "COP_m", "es", "COP 58.800 M"),
    (0.2788484320217882, "share", "en", "27.9%"),
    (0.7550812985772358, "ratio", "es", "0,76"),
    (0.7550812985772358, "ratio", "en", "0.76"),
    (125000, "count", "es", "125.000"),
    (125000, "count", "en", "125,000"),
])
def test_figure_is_formatted_by_its_unit(value, unit, locale, expected):
    assert format_figure(value, unit, locale) == expected


@pytest.mark.parametrize("unit,locale", [("COP_m", "fr"), ("furlongs", "es")])
def test_unknown_locale_or_unit_is_refused(unit, locale):
    with pytest.raises(ValueError):
        format_figure(1.0, unit, locale)


def test_spanish_is_the_dashboard_default():
    assert format_cop_m(58800.0) == "COP 58.800 M"
    assert dashboard_render.format_cop_m is format_cop_m   # one formatter for the page and for Gate 3
