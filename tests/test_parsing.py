from decimal import Decimal

import pytest

from listings.parsing import parse_beds_baths, parse_int, parse_price


@pytest.mark.parametrize(
    "text,expected",
    [("$2,800", 2800), ("$1,625/mo.", 1625), ("RENT $ 3100", 3100), ("Call for price", None), ("", None), (None, None)],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [("1,105", 1105), ("Square Feet: 925", 925), ("", None)])
def test_parse_int(text, expected):
    assert parse_int(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2 bd / 2 ba", (2, Decimal("2"))),
        ("Beds: 2 Baths: 1.0", (2, Decimal("1.0"))),
        ("3 bedrooms, 2.5 baths", (3, Decimal("2.5"))),
        ("Studio / 1 ba", (0, Decimal("1"))),
        ("", (None, None)),
    ],
)
def test_parse_beds_baths(text, expected):
    assert parse_beds_baths(text) == expected
