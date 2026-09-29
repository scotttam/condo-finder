import re
from decimal import Decimal

import pytest

from listings.filters import apply_filters
from listings.forms import ListingFilterForm, default_filter_data
from listings.models import Listing
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db

PEARL_BOX = {"north": "45.535", "south": "45.520", "east": "-122.670", "west": "-122.690"}


def listing(key, lat, lng):
    return make_listing(address_key=key, street=f"{key} St", price=3000, beds=2, baths=Decimal("2"), parking_spaces=2,
                        property_type="condo", latitude=lat, longitude=lng)


def test_filters_to_the_map_area():
    listing("pearl", 45.527, -122.681)
    listing("gresham", 45.50, -122.43)
    listing("unlocated", None, None)
    form = ListingFilterForm(default_filter_data() | PEARL_BOX)
    assert form.is_valid(), form.errors
    assert list(apply_filters(Listing.objects.all(), form.cleaned_data).values_list("address_key", flat=True)) == ["pearl"]


def test_partial_bounds_are_ignored():
    listing("pearl", 45.527, -122.681)
    listing("gresham", 45.50, -122.43)
    form = ListingFilterForm(default_filter_data() | {"north": "45.535"})
    assert form.is_valid()
    assert apply_filters(Listing.objects.all(), form.cleaned_data).count() == 2


def test_bounds_ride_along_in_the_form_and_show_a_clearable_chip(client):
    query = "&".join(f"{k}={v}" for k, v in PEARL_BOX.items())
    content = client.get(f"/?min_beds=2&{query}").content.decode()
    for name, value in PEARL_BOX.items():
        assert re.search(rf'<input type="hidden" name="{name}" value="{re.escape(value)}"', content), name
    assert "data-clear-area" in content and "Map area" in content
    assert "data-search-area" in content  # the map's "Search this area" button


def test_bounds_are_not_counted_as_more_filters(client):
    assert all(key not in default_filter_data() for key in PEARL_BOX)
