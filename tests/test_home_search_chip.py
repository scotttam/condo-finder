import re
from decimal import Decimal

import pytest

from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


def good(key, **extra):
    fields = dict(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    fields.update(extra)
    return make_listing(**fields)


def test_a_search_link_filters_the_home_page_and_shows_a_chip(client):
    good("balcony", description="balcony", zip_code="97209")
    good("plain", zip_code="97209")
    response = client.get("/?q=balcony&zips=97209&zips=97210&min_beds=2")
    assert {listing.address_key for listing in response.context["listings"]} == {"balcony"}
    content = response.content.decode()
    assert '<input type="hidden" name="q" value="balcony" data-search-only>' in content
    assert content.count('name="zips"') == 2
    assert re.search(r'<a href="/search/\?[^"]*q=balcony[^"]*">2 more filters from Search</a>', content)


def test_no_chip_without_search_only_filters(client):
    good("a")
    assert "from Search</a>" not in client.get("/?min_beds=2").content.decode()


def test_search_only_filters_survive_home_changes_and_saved_defaults(client):
    good("a", description="balcony")
    client.post("/filters/defaults/", {"q": "balcony", "min_beds": "2", "max_price": "8000", "min_price": "0"})
    assert home_group().default_filters["q"] == "balcony"
    content = client.get("/").content.decode()  # no URL filters: starts from the saved defaults
    assert '<input type="hidden" name="q" value="balcony" data-search-only>' in content
    assert "1 more filter from Search" in content


def test_cols_and_saved_in_a_link_dont_count_as_filters_on_home(client):
    good("fits")
    good("one-bed", beds=1)
    keys = {listing.address_key for listing in client.get("/?cols=address&saved=3").context["listings"]}
    assert keys == {"fits"}  # still the defaults
