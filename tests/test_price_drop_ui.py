from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from listings.filters import apply_filters
from listings.forms import ListingFilterForm, default_filter_data
from listings.models import Listing, PriceChange
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def at(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=12))


def cornell(**fields):
    """10805 NW Cornell Rd: rented at $3,800 in 2020, relisted Aug 22 at $4,800, cut to $4,600 Sep 22."""
    base = dict(address_key=f"cornell-{fields.pop('key', 1)}", price=4600, beds=4, baths=Decimal("2.5"),
                parking_spaces=2, property_type="house", listed_at=date(2026, 8, 22))
    base.update(fields)
    listing = make_listing(**base)
    for day, price, event in [(date(2020, 11, 25), 5200, "Listed for rent"), (date(2026, 8, 22), 4800, "Listed for rent"),
                              (date(2026, 9, 22), 4600, "Price change")]:
        PriceChange.objects.create(listing=listing, price=price, seen_at=at(day), event=event, source="Zillow")
    return listing


def test_price_drop_counts_only_the_current_listing():
    assert cornell().price_drop == 200  # the 2020 listing at $5,200 is a different rental period


def test_price_drop_without_listed_date_uses_all_history():
    assert cornell(key=2, listed_at=None).price_drop == 600


def test_no_drop_when_price_never_fell():
    listing = make_listing(price=3000, listed_at=date(2026, 9, 1))
    PriceChange.objects.create(listing=listing, price=3000, seen_at=at(date(2026, 9, 1)), event="Listed for rent")
    assert listing.price_drop == 0


def test_price_reduced_filter():
    cornell()
    make_listing(address_key="steady", price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    form = ListingFilterForm(default_filter_data() | {"price_reduced": "on"})
    assert form.is_valid(), form.errors
    assert list(apply_filters(Listing.objects.all(), form.cleaned_data).values_list("address_key", flat=True)) == ["cornell-1"]
    assert "price_reduced" not in default_filter_data()  # off by default


def test_badge_on_cards_and_table(client):
    cornell()
    assert "↓ $200" in client.get("/").content.decode()
    assert "↓ $200" in client.get("/?view=list").content.decode()


def test_detail_shows_history_with_changes_and_listed_date(client):
    listing = cornell()
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert "Aug 22, 2026" in content and "days on market" in content
    assert "Listed for rent" in content and "Price change" in content and "Zillow" in content
    assert "−$200 (−4%)" in content  # Sep 22 vs Aug 22
