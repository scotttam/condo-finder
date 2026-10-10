import csv
import io
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from listings.models import FeedEvent, Vote
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


def test_column_choices_are_saved_per_person_and_follow_them(client, owner, member_client):
    good("fits", zip_code="97209")
    response = client.post("/search/columns/", {"cols": ["address", "price", "zip"], "query": "q=&sort=-price&page=2"},
                           HTTP_HX_REQUEST="true")
    assert response["HX-Redirect"] == "/search/?q=&sort=-price"
    owner.profile.refresh_from_db()
    assert owner.profile.search_columns == ["address", "price", "zip"]
    content = page(client, "?q=")
    assert re.search(r'<td class="col-zip">\s*97209\s*</td>', content) and '<td class="col-sqft">' not in content
    assert '<td class="col-sqft">' in member_client.get("/search/?q=").content.decode()  # Alex still has the defaults


def test_reset_brings_back_the_default_columns(client, owner):
    client.post("/search/columns/", {"cols": ["address"], "query": ""})
    client.post("/search/columns/", {"reset": "1", "query": ""})
    owner.profile.refresh_from_db()
    assert owner.profile.search_columns == []


def test_columns_in_a_link_win_and_are_kept_while_filtering(client):
    good("fits", zip_code="97209")
    content = page(client, "?q=&cols=address,zip")
    assert re.search(r'<td class="col-zip">\s*97209\s*</td>', content) and '<td class="col-price">' not in content
    assert '<input type="hidden" name="cols" value="address,zip">' in content
    assert "Keep these columns" in content


def test_unknown_columns_are_ignored(client):
    good("fits")
    assert '<td class="col-price">' in page(client, "?q=&cols=nonsense")


def test_csv_exports_every_match_with_the_same_filters(client):
    for n in range(105):
        good(f"fits-{n:03}", price=3000 + n)
    good("one-bed", beds=1)
    response = client.get("/search/csv/?min_beds=2&sort=price")
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"].startswith('attachment; filename="search-')
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][:3] == ["Address", "Unit", "City"] and rows[0][-1] == "Link"
    assert len(rows) == 106  # header + every match, not just a page
    assert rows[1][rows[0].index("Price")] == "3000"
    assert "/listing/" in rows[1][-1] and rows[1][-1].startswith("http")


def test_search_page_links_to_its_csv(client):
    good("fits")
    content = page(client, "?q=balcony")
    assert re.search(r'<a class="csv-link" href="/search/csv/\?[^"]*q=balcony', content)


def test_rows_have_a_status_menu_and_vote_buttons(client):
    row = good("fits")
    content = page(client, "?q=")
    assert re.search(rf'<form id="status-menu-{row.pk}" class="status-menu"[^>]*hx-trigger="change"', content)
    assert f'<form class="votes" id="votes-{row.pk}"' in content


def test_changing_status_from_the_menu_saves_and_tells_the_group(client):
    row = good("fits")
    response = client.post(f"/listing/{row.pk}/status/", {"status": "toured", "variant": "menu"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert f'<form id="status-menu-{row.pk}"' in html and '<option value="toured" selected>Toured</option>' in html
    assert FeedEvent.objects.filter(listing=row, kind=FeedEvent.Kind.STATUS).exists()


def test_voting_from_a_row(client):
    row = good("fits")
    client.post(f"/listing/{row.pk}/vote/", {"value": "up"}, HTTP_HX_REQUEST="true")
    assert Vote.objects.filter(listing=row).count() == 1
    assert re.search(r'class="vote mine" aria-pressed="true"[^>]*>👍 1', page(client, "?q="))
