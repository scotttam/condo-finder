from datetime import timedelta

import pytest
from django.utils import timezone

from listings.models import PropertyType, Status
from tests.helpers import make_listing, status_of

pytestmark = pytest.mark.django_db


def test_listing_defaults():
    listing = make_listing()
    assert status_of(listing) == Status.NEW
    assert listing.property_type == PropertyType.UNKNOWN
    assert listing.is_active is True
    assert listing.overrides == {}
    assert listing.has_ac is None


def test_price_per_sqft():
    assert make_listing(price=2800, sqft=1105).price_per_sqft == 2.53


def test_price_per_sqft_missing_sqft():
    assert make_listing(price=2800).price_per_sqft is None


def test_days_on_market_active_listing_counts_to_now():
    listing = make_listing(first_seen_at=timezone.now() - timedelta(days=5))
    assert listing.days_on_market == 5


def test_days_on_market_off_market_listing_counts_to_last_seen():
    now = timezone.now()
    listing = make_listing(
        first_seen_at=now - timedelta(days=10),
        last_seen_at=now - timedelta(days=3),
        is_active=False,
    )
    assert listing.days_on_market == 7
