import re
from decimal import Decimal

import pytest

from listings.filters import apply_filters
from listings.forms import PRICE_SLIDER_MAX, ListingFilterForm, default_filter_data
from listings.models import Listing
from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


def page(client, query=""):
    return client.get(f"/{query}").content.decode()


def chip(content, name):
    """The HTML of one filter chip (its <details> element)."""
    match = re.search(rf'<details class="chip[^"]*" data-chip="{name}".*?</details>', content, re.S)
    assert match, f"no {name} chip"
    return match.group(0)


def test_filter_bar_replaces_the_sidebar(client):
    content = page(client)
    for name in ("price", "beds", "area", "type", "more"):
        chip(content, name)
    assert 'class="filters"' not in content  # the old sidebar
    assert 'id="filter-defaults"' in content  # defaults the chip labels and "More" count compare against


def test_price_is_a_two_handled_slider(client):
    price = chip(page(client), "price")
    assert 'type="range" name="min_price" value="2000"' in price
    assert 'type="range" name="max_price" value="5000"' in price
    assert f'max="{PRICE_SLIDER_MAX}"' in price


def test_beds_and_baths_are_button_rows_reflecting_current_values(client):
    beds = chip(page(client, "?min_beds=3&min_baths=1.5"), "beds")
    assert re.search(r'name="min_beds" value="3"[^>]*checked', beds)
    assert re.search(r'name="min_baths" value="1.5"[^>]*checked', beds)
    assert not re.search(r'name="min_beds" value="2"[^>]*checked', beds)


def test_area_has_cities_quadrant_grid_and_neighborhood(client):
    area = chip(page(client, "?quadrants=NW&quadrants=SE"), "area")
    for city in ("Portland", "Beaverton", "Lake Oswego"):
        assert f'value="{city}"' in area
    assert area.count('class="quadrant-tile') == 6
    assert re.search(r'value="NW"[^>]*checked', area) and re.search(r'value="SE"[^>]*checked', area)
    assert 'name="neighborhood"' in area


def test_type_chip(client):
    types = chip(page(client), "type")
    assert re.search(r'value="condo"[^>]*checked', types)
    assert not re.search(r'value="apartment"[^>]*checked', types)


def test_more_filters_drawer_holds_the_rest(client):
    from tests.helpers import make_source

    make_source("zillow")
    more = chip(page(client), "more")
    for name in ("min_parking", "parking_unknown", "wd", "ac", "outdoor", "price_reduced", "sources", "statuses", "show_inactive"):
        assert f'name="{name}"' in more, name


def test_sort_lives_in_the_results_header_but_belongs_to_the_form(client):
    content = page(client)
    assert re.search(r'<select[^>]*name="sort"[^>]*form="filters"|<select[^>]*form="filters"[^>]*name="sort"', content)
    assert 'id="filters"' in content


def test_slider_at_its_top_means_no_maximum():
    make_listing(address_key="big", price=9500, beds=3, baths=Decimal("2"), parking_spaces=2, property_type="house")
    form = ListingFilterForm(default_filter_data() | {"max_price": str(PRICE_SLIDER_MAX)})
    assert form.is_valid()
    assert list(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True)) == ["big"]
