import json
from datetime import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from listings.models import PriceChange, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def listing(key, **fields):
    base = dict(address_key=key, street=f"{key} St", price=2850, beds=2, baths=Decimal("2"), parking_spaces=2,
                property_type="condo", latitude=45.5, longitude=-122.6)
    base.update(fields)
    return make_listing(**base)


def test_map_view_is_a_split_with_cards_linked_by_id(client):
    home = listing("a")
    content = client.get("/").content.decode()
    assert 'class="split"' in content and 'class="map-pane"' in content and 'class="cards-pane"' in content
    assert f'data-listing-id="{home.pk}"' in content


def test_list_view_keeps_the_full_width_table(client):
    listing("a")
    content = client.get("/?view=list").content.decode()
    assert 'class="listing-table"' in content and 'class="split"' not in content


def test_pins_carry_short_price_and_status(client):
    plain = listing("plain", price=2850)
    liked = listing("liked", price=3100, status=Status.INTERESTED)
    dropped = listing("dropped", price=4400)
    PriceChange.objects.create(listing=dropped, price=5200, seen_at=timezone.make_aware(datetime(2026, 9, 1, 12)))
    points = {p["id"]: p for p in client.get("/?sort=price").context["map_points"]}
    assert points[plain.pk]["short"] == "$2.85k"
    assert points[liked.pk]["short"] == "$3.1k" and points[liked.pk]["status"] == "interested"
    assert points[dropped.pk]["drop"] is True and points[plain.pk]["drop"] is False
    assert points[plain.pk]["active"] is True


def test_pin_data_is_embedded_for_the_map_script(client):
    home = listing("a")
    content = client.get("/").content.decode()
    data = json.loads(content.split('id="map-points" type="application/json">')[1].split("</script>")[0])
    assert data[0]["id"] == home.pk and data[0]["url"] == f"/listing/{home.pk}/"


def test_pin_labels_and_classes_by_status(client):
    liked = listing("liked", price=3100, status=Status.INTERESTED)
    rejected = listing("rejected", price=2400, status=Status.REJECTED)
    plain = listing("plain", price=2850)
    points = {p["id"]: p for p in client.get("/?statuses=new&statuses=interested&statuses=rejected").context["map_points"]}
    assert points[liked.pk]["label"] == "♥ $3.1k" and "pin-liked" in points[liked.pk]["classes"]
    assert points[rejected.pk]["label"] == "✕ $2.4k" and "pin-rejected" in points[rejected.pk]["classes"]
    assert points[plain.pk]["label"] == "$2.85k" and points[plain.pk]["classes"] == "pin"
