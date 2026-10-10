import re
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def good(key, **extra):
    fields = dict(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    fields.update(extra)
    return make_listing(**fields)


def page(client, query=""):
    response = client.get(f"/search/{query}")
    assert response.status_code == 200
    return response.content.decode()


def test_search_is_in_the_nav_and_starts_from_the_group_defaults(client):
    good("fits")
    good("one-bed", beds=1)
    content = page(client)
    assert '<a href="/search/">Search</a>' in content
    assert re.search(r'<form id="search-filters"[^>]*hx-trigger="change, input delay:400ms"', content)
    assert re.search(r'<input id="search-q" type="search" name="q"', content)
    keys = {listing.address_key for listing in client.get("/search/").context["listings"]}
    assert keys == {"fits"}


def test_clear_all_searches_every_active_listing(client):
    good("fits")
    good("one-bed", beds=1)
    good("gone", is_active=False)
    content = page(client)
    assert '<a class="clear-all" href="/search/?q=">Clear all</a>' in content
    keys = {listing.address_key for listing in client.get("/search/?q=").context["listings"]}
    assert keys == {"fits", "one-bed"}


def test_header_and_page_links_keep_the_default_filters(client):
    for n in range(101):
        good(f"fits-{n:03}", price=3000 + n)
    good("one-bed", beds=1)
    response = client.get("/search/")
    headers = {h["key"]: h for h in response.context["headers"]}
    for url in (headers["price"]["url"], response.context["next_url"]):
        params = parse_qs(urlparse(url).query)
        assert params["min_beds"] == ["2"] and "types" in params, url
    assert parse_qs(urlparse(headers["price"]["url"]).query)["sort"] == ["price"]
    assert "page" not in parse_qs(urlparse(headers["price"]["url"]).query)


def test_results_page_at_100_with_a_count(client):
    for n in range(101):
        good(f"fits-{n:03}", price=3000 + n)
    content = page(client, "?q=")
    assert "101 listings" in content and "showing 1–100" in content
    assert content.count('<td class="m-card">') == 100
    assert "Page 1 of 2" in content


def test_clicking_a_header_sorts(client):
    good("cheap", price=2500)
    good("dear", price=3500)
    keys = [listing.address_key for listing in client.get("/search/?q=&sort=-price").context["listings"]]
    assert keys == ["dear", "cheap"]
    content = page(client, "?q=&sort=-price")
    assert re.search(r'<a href="/search/\?[^"]*sort=price[^"]*" data-sort="price" class="sort-link sorted">Price ↓</a>', content)


def test_default_columns_render(client):
    good("fits", sqft=1000, photo_url="https://example.com/p.jpg")
    content = page(client, "?q=")
    for key in ("photo", "address", "area", "price", "beds_baths", "sqft", "ppsf", "parking", "features", "dom", "status", "votes"):
        assert f'<td class="col-{key}">' in content, key
    assert "$3.00" in content  # $/sqft


def test_a_bad_value_skips_only_that_filter(client):
    good("fits", sqft=1000)
    good("one-bed", beds=1, sqft=1000)
    response = client.get("/search/?q=&min_beds=2&min_sqft=abc")
    assert {listing.address_key for listing in response.context["listings"]} == {"fits"}
    assert "Ignored Min sqft: Enter a whole number." in response.content.decode()


def test_keyword_matches_are_highlighted(client):
    good("a", description="Corner unit with a huge balcony.")
    content = page(client, "?q=balcony")
    assert '<div class="search-snippet">' in content and "<mark>balcony</mark>" in content


def test_filter_count_updates_out_of_band(client):
    content = page(client, "?q=&min_beds=3&zips=97209")
    assert '<span id="filter-count">(2)</span>' in content
    assert 'hx-select-oob="#filter-count"' in content


def test_search_only_and_shared_filters_render_in_the_panel(client):
    content = page(client, "?q=&wd=no&zips=97209&max_sqft=1500")
    assert re.search(r'<select name="wd"[^>]*>.*?<option value="no" selected>No</option>', content, re.S)
    assert re.search(r'<input type="checkbox" name="zips" value="97209"[^>]*checked', content)
    assert 'name="max_sqft" value="1500"' in content


def test_phone_layout_has_a_filters_drawer_and_compact_cards(client):
    good("fits")
    content = page(client)
    assert re.search(r'<button type="button" class="filters-toggle" data-filters-toggle', content)
    assert '<button type="button" class="filters-done" data-filters-toggle>Show results</button>' in content
    assert '<td class="m-card"><a class="m-card-link"' in content.replace("\n", "")
    assert "@media (max-width: 700px)" in content
