from listings.forms import SORT_FIELDS
from listings.search_columns import COLUMNS, DEFAULT_KEYS, headers, keys_from


def test_defaults_match_the_decisions():
    assert DEFAULT_KEYS == ["photo", "address", "area", "price", "beds_baths", "sqft", "ppsf", "parking", "features",
                            "dom", "status", "votes"]


def test_every_sortable_column_has_a_sort():
    assert all(column.sort in SORT_FIELDS for column in COLUMNS if column.sort)


def test_keys_from_keeps_known_keys_in_registry_order():
    assert keys_from(["price", "bogus", "address"]) == ["address", "price"]
    assert keys_from([]) == DEFAULT_KEYS
    assert keys_from(["bogus"]) == DEFAULT_KEYS


def test_headers_toggle_direction_and_show_an_arrow():
    url = lambda sort: f"?sort={sort}"
    by_key = {h["key"]: h for h in headers(["photo", "price", "sqft"], "price", url)}
    assert by_key["photo"]["sort_key"] == "" and by_key["photo"]["url"] == ""
    assert (by_key["price"]["arrow"], by_key["price"]["next_sort"], by_key["price"]["url"]) == ("↑", "-price", "?sort=-price")
    assert (by_key["sqft"]["arrow"], by_key["sqft"]["next_sort"]) == ("", "sqft")
    assert {h["key"]: h for h in headers(["price"], "-price", url)}["price"]["next_sort"] == "price"


def test_csv_cells_never_start_a_formula():
    from listings.search_columns import csv_cell

    assert csv_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert csv_cell("+1") == "'+1" and csv_cell("-1") == "'-1" and csv_cell("@sum") == "'@sum"
    assert csv_cell("821 NW 11th") == "821 NW 11th" and csv_cell(3000) == 3000 and csv_cell(None) == ""


def test_csv_dates_are_local_days():
    from datetime import datetime, timezone as dt_timezone
    from types import SimpleNamespace

    from listings.search_columns import CSV_FIELDS

    evening = datetime(2026, 10, 3, 4, 30, tzinfo=dt_timezone.utc)  # 9:30 pm Oct 2 in Portland
    row = SimpleNamespace(first_seen_at=evening, last_seen_at=evening)
    values = {label: value(row) for label, value in CSV_FIELDS if label in ("First seen", "Last seen")}
    assert {str(v) for v in values.values()} == {"2026-10-02"}
