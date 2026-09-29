from decimal import Decimal

import pytest

from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def listing():
    return make_listing(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo",
                        latitude=45.5, longitude=-122.6)


def test_map_view_has_the_phone_map_toggle_and_mini_card(client):
    listing()
    content = client.get("/").content.decode()
    assert "<button type=\"button\" class=\"map-toggle\"" in content and 'class="mini-card"' in content


def test_list_view_has_no_map_toggle(client):
    listing()
    content = client.get("/?view=list").content.decode()
    assert "<button type=\"button\" class=\"map-toggle\"" not in content
