"""Display formatting by locale, shared by the dashboard and Gate 3 (display only).

Values keep full precision in every JSON; they are rounded only when shown. The dashboard
is in Spanish (``es``: 58.800 and 27,9 %); the report may be in English (``en``: 58,800
and 27.9%). Gate 3 formats each cited figure with the locale of its citation, so a figure
written correctly in either language is not flagged.

Units (the ``unit`` of a registered figure): ``COP_m`` COP millions, whole from a thousand
up and one decimal below; ``share`` a percentage with one decimal; ``ratio`` two decimals
(SPI, CPI); ``count`` a whole number.
"""
from __future__ import annotations

LOCALES = ("es", "en")
DASH = "—"


def _number(value: float, decimals: int, locale: str) -> str:
    if locale not in LOCALES:
        raise ValueError(f"unknown locale {locale!r}; use one of {LOCALES}")
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".") if locale == "es" else text


def format_cop_m(value, locale: str = "es") -> str:
    if value is None:
        return DASH
    return f"COP {_number(value, 0 if abs(value) >= 1000 else 1, locale)} M"


def format_pct(share, locale: str = "es") -> str:
    if share is None:
        return DASH
    number = _number(share * 100, 1, locale)
    return f"{number} %" if locale == "es" else f"{number}%"


def format_ratio(value, locale: str = "es") -> str:
    return DASH if value is None else _number(value, 2, locale)


def format_count(value, locale: str = "es") -> str:
    return DASH if value is None else _number(value, 0, locale)


UNITS = {"COP_m": format_cop_m, "share": format_pct, "ratio": format_ratio, "count": format_count}


def format_figure(value, unit: str, locale: str) -> str:
    """A registered figure as it must be written in a document of that locale."""
    if unit not in UNITS:
        raise ValueError(f"unknown unit {unit!r}; use one of {sorted(UNITS)}")
    if locale not in LOCALES:
        raise ValueError(f"unknown locale {locale!r}; use one of {LOCALES}")
    return UNITS[unit](value, locale)
