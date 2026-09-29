import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from listings.models import PriceChange, SourceListing
from tests.helpers import make_listing, make_source

pytestmark = pytest.mark.django_db


def home(**fields):
    base = dict(price=4600, beds=4, baths=Decimal("2.5"), sqft=3117, parking_spaces=2, has_washer_dryer=True, has_ac=None,
                property_type="house", quadrant="NW", neighborhood="Cedar Mill", available="Available Now",
                title="Charming Foursquare", listed_at=date(2026, 8, 22), latitude=45.5, longitude=-122.8)
    base.update(fields)
    return make_listing(**base)


def page(client, listing):
    return client.get(f"/listing/{listing.pk}/").content.decode()


def test_header_has_address_location_price_and_title(client):
    content = page(client, home())
    header = content[content.index('class="listing-header"'):content.index('class="listing-body"')]
    assert "937 NW Glisan Street" in header and "Portland · NW · Cedar Mill · House" in header
    assert '<div class="listing-price">$4,600<span>/mo</span>' in header
    assert "Charming Foursquare" in header


def test_price_drop_pill_in_header(client):
    listing = home()
    PriceChange.objects.create(listing=listing, price=4800, event="Listed for rent",
                               seen_at=timezone.make_aware(datetime(2026, 8, 22, 12)))
    header = page(client, listing).split('class="listing-body"')[0]
    assert '<span class="drop-pill">↓ $200 (4%) since listed</span>' in header


def test_stat_tiles(client):
    content = page(client, home())
    tiles = dict(re.findall(r'<div class="stat"><div class="stat-value">(.*?)</div><div class="stat-label">(.*?)</div>', content))
    tiles = {label: value for value, label in tiles.items()}
    assert tiles["Beds"] == "4" and tiles["Baths"] == "2.5"
    assert tiles["Sq ft"].startswith("3,117") and "$1.48/sqft" in tiles["Sq ft"]
    assert tiles["Parking"] == "2" and "days on market" in tiles["Listed"]
    assert tiles["Available"] == "Available Now"


def test_source_badges_link_out_and_fade_when_gone(client):
    listing = home()
    SourceListing.objects.create(listing=listing, source=make_source("zillow"), external_id="z", url="https://z.example/1")
    SourceListing.objects.create(listing=listing, source=make_source("redfin"), external_id="r", url="https://r.example/1", is_active=False)
    content = page(client, listing)
    assert '<a class="source-link" href="https://z.example/1"' in content
    assert '<a class="source-link gone" href="https://r.example/1"' in content and "Redfin (gone)" in content


def test_long_description_is_collapsible(client):
    content = page(client, home(description="Lovely home. " * 120))
    assert 'class="description collapsible"' in content and "data-expand" in content
    short = page(client, home(address_key="short", street="2 Short St", description="Short and sweet."))
    assert "collapsible" not in short.split('class="listing-body"')[1].split("<aside")[0]


def test_map_sits_in_the_main_column(client):
    content = page(client, home())
    main = content.split('class="listing-body"')[1].split("<aside")[0]
    assert 'id="map"' in main
