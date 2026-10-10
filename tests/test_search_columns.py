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
